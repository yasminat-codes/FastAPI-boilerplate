"""Comprehensive integration tests for retry and dead-letter logic.

This module tests interactions between:
- WorkerJob execution with BackoffPolicy
- NonRetryableJobError handling and dead-letter flow
- JobDeadLetterStore and replay functionality
- Alert hook integration
- Backoff delay calculation with jitter across attempts
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from arq.worker import Retry

from src.app.core.worker.dead_letter import (
    JobDeadLetterRequest,
    JobDeadLetterStore,
    build_dead_letter_request_from_job,
)
from src.app.core.worker.jobs import JobRetryPolicy, RetryableJobError, WorkerJob
from src.app.core.worker.replay import (
    ReplayRequest,
    build_replay_request_from_dead_letter,
    replay_dead_lettered_job,
)
from src.app.core.worker.retry import (
    BackoffPolicy,
    JobAlertHook,
    NonRetryableJobError,
    calculate_backoff_delay_deterministic,
)


class TestWorkerJobWithBackoffPolicy:
    """Tests for WorkerJob execution with BackoffPolicy."""

    @pytest.mark.asyncio
    async def test_job_fails_transiently_and_retries_with_backoff_delay(self) -> None:
        """Job fails transiently and uses backoff policy for retry delay."""
        backoff = BackoffPolicy(
            base_delay_seconds=2.0,
            max_delay_seconds=100.0,
            multiplier=2.0,
            jitter=False,
        )

        class TransientFailureJob(WorkerJob):
            job_name = "tests.jobs.transient_failure"
            retry_policy = JobRetryPolicy(max_tries=4, defer_seconds=999.0)
            backoff_policy = backoff

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("Transient network timeout")

        # First attempt (job_try=1, retry_count=0)
        # Backoff delay = 2.0 * 2^0 = 2.0 seconds
        with pytest.raises(Retry) as exc_info:
            await TransientFailureJob.execute({"job_try": 1}, {"payload": {}})
        assert exc_info.value.defer_score == 2000

        # Second attempt (job_try=2, retry_count=1)
        # Backoff delay = 2.0 * 2^1 = 4.0 seconds
        with pytest.raises(Retry) as exc_info:
            await TransientFailureJob.execute({"job_try": 2}, {"payload": {}})
        assert exc_info.value.defer_score == 4000

        # Third attempt (job_try=3, retry_count=2)
        # Backoff delay = 2.0 * 2^2 = 8.0 seconds
        with pytest.raises(Retry) as exc_info:
            await TransientFailureJob.execute({"job_try": 3}, {"payload": {}})
        assert exc_info.value.defer_score == 8000

    @pytest.mark.asyncio
    async def test_backoff_delay_respects_max_delay_cap(self) -> None:
        """Backoff delay should not exceed max_delay_seconds."""
        backoff = BackoffPolicy(
            base_delay_seconds=1.0,
            max_delay_seconds=10.0,
            multiplier=2.0,
            jitter=False,
        )

        class CappedBackoffJob(WorkerJob):
            job_name = "tests.jobs.capped_backoff"
            retry_policy = JobRetryPolicy(max_tries=10, defer_seconds=0.0)
            backoff_policy = backoff

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        # Many attempts later - should cap at max_delay
        # Attempt 5 (job_try=5): delay = 1.0 * 2^4 = 16.0, capped to 10.0
        with pytest.raises(Retry) as exc_info:
            await CappedBackoffJob.execute({"job_try": 5}, {"payload": {}})
        assert exc_info.value.defer_score == 10000

        # Even later attempt should still be capped
        with pytest.raises(Retry) as exc_info:
            await CappedBackoffJob.execute({"job_try": 8}, {"payload": {}})
        assert exc_info.value.defer_score == 10000

    @pytest.mark.asyncio
    async def test_backoff_with_jitter_produces_variable_delays(self) -> None:
        """Backoff with jitter=True should produce variable delays in range."""
        backoff = BackoffPolicy(
            base_delay_seconds=1.0,
            max_delay_seconds=100.0,
            multiplier=2.0,
            jitter=True,
        )

        class JitteredBackoffJob(WorkerJob):
            job_name = "tests.jobs.jittered_backoff"
            retry_policy = JobRetryPolicy(max_tries=5, defer_seconds=0.0)
            backoff_policy = backoff

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        # Collect delays from multiple executions
        delays = []
        for _ in range(20):
            with pytest.raises(Retry) as exc_info:
                await JitteredBackoffJob.execute({"job_try": 2}, {"payload": {}})
            delays.append(exc_info.value.defer_score)

        # All delays should be within valid range: 0 to 4.0 seconds (4000 ms)
        # (retry_count=1, so 1.0 * 2^1 = 2.0, jitter between 0 and 2.0)
        assert all(0 <= delay <= 4000 for delay in delays)
        # Should have some variability (unlikely all identical with jitter)
        assert len(set(delays)) > 1


class TestNonRetryableJobErrorAndDeadLetter:
    """Tests for NonRetryableJobError triggering dead-letter flow."""

    @pytest.mark.asyncio
    async def test_non_retryable_error_fails_immediately(self) -> None:
        """NonRetryableJobError should propagate immediately without retry."""

        class NonRetryableJob(WorkerJob):
            job_name = "tests.jobs.non_retryable_dead_letter"
            retry_policy = JobRetryPolicy(max_tries=5, defer_seconds=10.0)

            @classmethod
            async def run(cls, ctx, envelope):
                raise NonRetryableJobError(
                    "Invalid API key format",
                    error_category="authentication",
                    error_code="INVALID_KEY",
                )

        # Should raise NonRetryableJobError, NOT Retry
        with pytest.raises(NonRetryableJobError) as exc_info:
            await NonRetryableJob.execute({"job_try": 1}, {"payload": {"key": "bad"}})

        assert exc_info.value.error_category == "authentication"
        assert exc_info.value.error_code == "INVALID_KEY"

    @pytest.mark.asyncio
    async def test_non_retryable_error_triggers_alert_with_final_attempt(
        self,
    ) -> None:
        """NonRetryableJobError should trigger alert hooks with is_final_attempt=True."""
        mock_alert = AsyncMock(spec=JobAlertHook)

        class AlertingNonRetryableJob(WorkerJob):
            job_name = "tests.jobs.alerting_non_retryable"
            retry_policy = JobRetryPolicy(max_tries=3, defer_seconds=5.0)
            alert_hooks = [mock_alert]

            @classmethod
            async def run(cls, ctx, envelope):
                raise NonRetryableJobError(
                    "Resource not found",
                    error_category="not_found",
                )

        with pytest.raises(NonRetryableJobError):
            await AlertingNonRetryableJob.execute(
                {"job_try": 2},
                {"payload": {"id": "missing"}},
            )

        mock_alert.on_job_failure.assert_awaited_once()
        call_args = mock_alert.on_job_failure.call_args[1]
        assert call_args["is_final_attempt"] is True
        assert call_args["error_category"] == "not_found"
        assert call_args["attempt"] == 2
        assert call_args["max_attempts"] == 3


class TestFullDeadLetterFlow:
    """Tests for complete dead-letter flow: failure -> storage -> replay."""

    @pytest.mark.asyncio
    async def test_job_exhausts_retries_then_dead_letter_stored(self) -> None:
        """After max retries exhausted, job can be dead-lettered."""
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_record = MagicMock()
        mock_record.id = 42

        with patch(
            "src.app.core.worker.dead_letter.DeadLetterRecord",
            return_value=mock_record,
        ):
            store = JobDeadLetterStore()

            # Simulate job that failed after exhausting retries
            error = RetryableJobError("Connection timeout")
            envelope = {
                "payload": {"url": "https://api.example.com/data"},
                "correlation_id": "req-123",
            }

            request = build_dead_letter_request_from_job(
                job_name="tasks.fetch_data",
                queue_name="default",
                envelope=envelope,
                error=error,
                attempt=3,
                max_attempts=3,
                error_category="transient",
            )

            result = await store.dead_letter(mock_session, request)

            assert result.dead_letter_record_id == 42
            assert result.job_name == "tasks.fetch_data"
            mock_session.add.assert_called_once()
            mock_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dead_letter_request_captures_failure_context(self) -> None:
        """Dead-letter request should capture comprehensive failure context."""
        error = ValueError("Invalid email format")
        envelope = {
            "payload": {"email": "not-an-email"},
            "correlation_id": "req-456",
            "tenant_context": {"tenant_id": "tenant-789"},
        }

        request = build_dead_letter_request_from_job(
            job_name="tasks.send_email",
            queue_name="priority",
            envelope=envelope,
            error=error,
            attempt=2,
            max_attempts=3,
            error_category="invalid_payload",
        )

        assert request.job_name == "tasks.send_email"
        assert request.queue_name == "priority"
        assert request.correlation_id == "req-456"
        assert request.failure_category == "invalid_payload"
        assert request.error_detail == "Invalid email format"
        assert request.attempt_count == 2
        assert request.max_attempts == 3
        assert request.failure_context["error_type"] == "ValueError"
        assert request.payload_snapshot["envelope"]["correlation_id"] == "req-456"

    @pytest.mark.asyncio
    async def test_dead_lettered_job_can_be_replayed(self) -> None:
        """Dead-lettered job can be replayed from dead letter record."""
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock()

        # Create a dead letter record mock
        record = MagicMock()
        record.id = 10
        record.message_type = "job.tasks.process_payment"
        record.correlation_id = "req-999"
        record.payload_snapshot = {
            "envelope": {
                "payload": {"amount": 99.99, "currency": "USD"},
            },
            "tenant_id": "tenant-111",
            "organization_id": "org-222",
        }

        # Build replay request from dead letter
        replay_request = build_replay_request_from_dead_letter(record)

        assert replay_request.job_name == "tasks.process_payment"
        assert replay_request.payload == {"amount": 99.99, "currency": "USD"}
        assert replay_request.correlation_id == "req-999"
        assert replay_request.tenant_id == "tenant-111"
        assert replay_request.organization_id == "org-222"

        # Replay the job
        result = await replay_dead_lettered_job(mock_pool, replay_request)

        assert result.enqueued is True
        assert result.dead_letter_record_id == 10
        mock_pool.enqueue_job.assert_awaited_once()
        call_args = mock_pool.enqueue_job.call_args
        assert call_args[0][0] == "tasks.process_payment"

    @pytest.mark.asyncio
    async def test_replay_handles_enqueue_failure(self) -> None:
        """Replay should return error result if enqueue fails."""
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(
            side_effect=RuntimeError("Redis connection failed")
        )

        replay_request = ReplayRequest(
            dead_letter_record_id=50,
            job_name="tasks.critical_task",
            payload={"data": "value"},
        )

        result = await replay_dead_lettered_job(mock_pool, replay_request)

        assert result.enqueued is False
        assert "RuntimeError" in result.error_message
        assert "Redis connection failed" in result.error_message

    @pytest.mark.asyncio
    async def test_full_workflow_failure_alert_storage_replay(self) -> None:
        """Full integration: job fails, alerts fire, stored in dead-letter, replayed."""
        mock_alert = AsyncMock(spec=JobAlertHook)
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock()

        mock_record = MagicMock()
        mock_record.id = 99
        mock_record.message_type = "job.tasks.process_order"
        mock_record.correlation_id = "order-123"
        mock_record.payload_snapshot = {
            "envelope": {
                "payload": {"order_id": "ord-456"},
            },
        }

        class IntegrationJob(WorkerJob):
            job_name = "tasks.process_order"
            retry_policy = JobRetryPolicy(max_tries=2, defer_seconds=5.0)
            alert_hooks = [mock_alert]

            @classmethod
            async def run(cls, ctx, envelope):
                raise NonRetryableJobError(
                    "Order not found",
                    error_category="not_found",
                )

        # Step 1: Job fails with NonRetryableJobError
        with pytest.raises(NonRetryableJobError):
            await IntegrationJob.execute({"job_try": 1}, {"payload": {"order_id": "ord-456"}})

        # Step 2: Alert should have been fired with is_final_attempt=True
        mock_alert.on_job_failure.assert_awaited_once()
        alert_call = mock_alert.on_job_failure.call_args[1]
        assert alert_call["is_final_attempt"] is True
        assert alert_call["error_category"] == "not_found"

        # Step 3: Dead-letter request can be built
        with patch(
            "src.app.core.worker.dead_letter.DeadLetterRecord",
            return_value=mock_record,
        ):
            store = JobDeadLetterStore()
            error = NonRetryableJobError("Order not found", error_category="not_found")
            envelope = {"payload": {"order_id": "ord-456"}}

            dl_request = build_dead_letter_request_from_job(
                job_name="tasks.process_order",
                queue_name="default",
                envelope=envelope,
                error=error,
                attempt=1,
                max_attempts=2,
                error_category="not_found",
            )

            dl_result = await store.dead_letter(mock_session, dl_request)
            assert dl_result.dead_letter_record_id == 99

            # Step 4: Replay from dead letter
            replay_request = build_replay_request_from_dead_letter(mock_record)
            replay_result = await replay_dead_lettered_job(mock_pool, replay_request)
            assert replay_result.enqueued is True


class TestAlertHookIntegration:
    """Tests for alert hook integration during job failures."""

    @pytest.mark.asyncio
    async def test_alert_hook_fires_on_every_failure(self) -> None:
        """Alert hooks should fire on every failure attempt."""
        mock_alert = AsyncMock(spec=JobAlertHook)

        class MultiFailureJob(WorkerJob):
            job_name = "tests.jobs.multi_failure"
            retry_policy = JobRetryPolicy(max_tries=3, defer_seconds=1.0)
            alert_hooks = [mock_alert]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("Transient error")

        # Attempt 1
        with pytest.raises(Retry):
            await MultiFailureJob.execute({"job_try": 1}, {"payload": {}})

        call_1 = mock_alert.on_job_failure.call_args[1]
        assert call_1["attempt"] == 1
        assert call_1["is_final_attempt"] is False

        # Attempt 2
        with pytest.raises(Retry):
            await MultiFailureJob.execute({"job_try": 2}, {"payload": {}})

        call_2 = mock_alert.on_job_failure.call_args[1]
        assert call_2["attempt"] == 2
        assert call_2["is_final_attempt"] is False

        # Final attempt
        with pytest.raises(Retry):
            await MultiFailureJob.execute({"job_try": 3}, {"payload": {}})

        call_3 = mock_alert.on_job_failure.call_args[1]
        assert call_3["attempt"] == 3
        assert call_3["is_final_attempt"] is True

        # Verify all 3 calls were made
        assert mock_alert.on_job_failure.await_count == 3

    @pytest.mark.asyncio
    async def test_alert_hook_receives_correct_is_final_attempt_flag(self) -> None:
        """Alert hooks should receive correct is_final_attempt flag."""
        mock_alert = AsyncMock(spec=JobAlertHook)

        class FinalAttemptJob(WorkerJob):
            job_name = "tests.jobs.final_attempt"
            retry_policy = JobRetryPolicy(max_tries=2, defer_seconds=1.0)
            alert_hooks = [mock_alert]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        # Attempt 1 of 2 - not final
        with pytest.raises(Retry):
            await FinalAttemptJob.execute({"job_try": 1}, {"payload": {}})

        first_call = mock_alert.on_job_failure.call_args[1]
        assert first_call["is_final_attempt"] is False
        assert first_call["attempt"] == 1
        assert first_call["max_attempts"] == 2

        # Attempt 2 of 2 - final
        mock_alert.reset_mock()
        with pytest.raises(Retry):
            await FinalAttemptJob.execute({"job_try": 2}, {"payload": {}})

        second_call = mock_alert.on_job_failure.call_args[1]
        assert second_call["is_final_attempt"] is True
        assert second_call["attempt"] == 2
        assert second_call["max_attempts"] == 2

    @pytest.mark.asyncio
    async def test_multiple_alert_hooks_all_fire(self) -> None:
        """Multiple alert hooks should all be invoked on job failure."""
        mock_alert_1 = AsyncMock(spec=JobAlertHook)
        mock_alert_2 = AsyncMock(spec=JobAlertHook)
        mock_alert_3 = AsyncMock(spec=JobAlertHook)

        class MultiHookJob(WorkerJob):
            job_name = "tests.jobs.multi_hook"
            retry_policy = JobRetryPolicy(max_tries=2, defer_seconds=1.0)
            alert_hooks = [mock_alert_1, mock_alert_2, mock_alert_3]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        with pytest.raises(Retry):
            await MultiHookJob.execute({"job_try": 1}, {"payload": {}})

        mock_alert_1.on_job_failure.assert_awaited_once()
        mock_alert_2.on_job_failure.assert_awaited_once()
        mock_alert_3.on_job_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_alert_hook_exception_doesnt_prevent_retry(self) -> None:
        """If an alert hook raises, it should not prevent the job from retrying."""
        mock_alert_1 = AsyncMock(spec=JobAlertHook)
        mock_alert_1.on_job_failure = AsyncMock(
            side_effect=RuntimeError("Alert system down")
        )
        mock_alert_2 = AsyncMock(spec=JobAlertHook)

        class FailingAlertJob(WorkerJob):
            job_name = "tests.jobs.failing_alert"
            retry_policy = JobRetryPolicy(max_tries=2, defer_seconds=1.0)
            alert_hooks = [mock_alert_1, mock_alert_2]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        # Should still raise Retry, not the alert exception
        with pytest.raises(Retry):
            await FailingAlertJob.execute({"job_try": 1}, {"payload": {}})

        # Both hooks should have been called
        mock_alert_1.on_job_failure.assert_awaited_once()
        mock_alert_2.on_job_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_alert_hook_receives_envelope_data(self) -> None:
        """Alert hooks should receive envelope_data in failure notification."""
        mock_alert = AsyncMock(spec=JobAlertHook)

        class EnvelopeAwareJob(WorkerJob):
            job_name = "tests.jobs.envelope_aware"
            retry_policy = JobRetryPolicy(max_tries=2, defer_seconds=1.0)
            alert_hooks = [mock_alert]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        envelope_dict = {
            "payload": {"key": "value", "id": 123},
            "correlation_id": "corr-789",
        }

        with pytest.raises(Retry):
            await EnvelopeAwareJob.execute({"job_try": 1}, envelope_dict)

        call_kwargs = mock_alert.on_job_failure.call_args[1]
        envelope_data = call_kwargs["envelope_data"]

        assert envelope_data["payload"] == {"key": "value", "id": 123}
        assert envelope_data["correlation_id"] == "corr-789"


class TestBackoffDelayCalculationWithJitter:
    """Tests for backoff delay calculation across multiple attempts."""

    @pytest.mark.asyncio
    async def test_backoff_without_jitter_is_deterministic(self) -> None:
        """Backoff without jitter should produce predictable delays."""
        backoff = BackoffPolicy(
            base_delay_seconds=1.0,
            max_delay_seconds=100.0,
            multiplier=2.0,
            jitter=False,
        )

        class DeterministicBackoffJob(WorkerJob):
            job_name = "tests.jobs.deterministic_backoff"
            retry_policy = JobRetryPolicy(max_tries=5, defer_seconds=0.0)
            backoff_policy = backoff

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        expected_delays = [1.0, 2.0, 4.0, 8.0, 16.0]

        for job_try, expected_delay_s in enumerate(expected_delays, start=1):
            with pytest.raises(Retry) as exc_info:
                await DeterministicBackoffJob.execute({"job_try": job_try}, {"payload": {}})
            assert exc_info.value.defer_score == int(expected_delay_s * 1000)

    @pytest.mark.asyncio
    async def test_backoff_with_jitter_within_expected_range(self) -> None:
        """Backoff with jitter should stay within [0, exponential_delay]."""
        backoff = BackoffPolicy(
            base_delay_seconds=2.0,
            max_delay_seconds=500.0,
            multiplier=2.0,
            jitter=True,
        )

        class JitteredJob(WorkerJob):
            job_name = "tests.jobs.jittered"
            retry_policy = JobRetryPolicy(max_tries=4, defer_seconds=0.0)
            backoff_policy = backoff

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        # For job_try=3 (retry_count=2): expected_delay = 2.0 * 2^2 = 8.0 seconds
        max_expected_ms = 8000
        delays = []

        for _ in range(50):
            with pytest.raises(Retry) as exc_info:
                await JitteredJob.execute({"job_try": 3}, {"payload": {}})
            delays.append(exc_info.value.defer_score)

        # All delays should be within range
        assert all(0 <= delay <= max_expected_ms for delay in delays)

    def test_backoff_delay_calculation_exponential_growth(self) -> None:
        """Backoff should grow exponentially with attempt number."""
        delays = []
        for attempt in range(5):
            delay = calculate_backoff_delay_deterministic(
                base_delay=1.0,
                attempt=attempt,
                max_delay=1000.0,
            )
            delays.append(delay)

        # Should be: 1, 2, 4, 8, 16
        assert delays == [1.0, 2.0, 4.0, 8.0, 16.0]
        # Each should roughly double (exactly with no jitter)
        for i in range(1, len(delays)):
            assert delays[i] == delays[i - 1] * 2

    def test_backoff_delay_exponential_growth_custom_base(self) -> None:
        """Backoff should scale with custom base delay."""
        delays = []
        for attempt in range(4):
            delay = calculate_backoff_delay_deterministic(
                base_delay=5.0,
                attempt=attempt,
                max_delay=1000.0,
            )
            delays.append(delay)

        # Should be: 5, 10, 20, 40
        assert delays == [5.0, 10.0, 20.0, 40.0]


class TestDeadLetterRecordCreation:
    """Tests for dead letter record creation from job failure context."""

    @pytest.mark.asyncio
    async def test_dead_letter_record_stores_job_metadata(self) -> None:
        """Dead letter record should store complete job metadata."""
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_record = MagicMock()
        mock_record.id = 55

        with patch(
            "src.app.core.worker.dead_letter.DeadLetterRecord",
            return_value=mock_record,
        ) as mock_dl_class:
            store = JobDeadLetterStore()
            request = JobDeadLetterRequest(
                job_name="tasks.webhook_delivery",
                queue_name="webhooks",
                correlation_id="webhook-event-123",
                failure_category="transient",
                error_code="TIMEOUT",
                error_detail="Connection timeout after 30s",
                attempt_count=2,
                max_attempts=3,
                payload_snapshot={"url": "https://example.com/hook"},
            )

            result = await store.dead_letter(mock_session, request)

            # Verify DeadLetterRecord was created with correct values
            call_args = mock_dl_class.call_args[1]
            assert call_args["dead_letter_key"] == request.dead_letter_key
            assert call_args["message_type"] == request.message_type
            assert call_args["source_system"] == "webhooks"
            assert call_args["correlation_id"] == "webhook-event-123"
            assert call_args["failure_category"] == "transient"
            assert result.dead_letter_record_id == 55

    @pytest.mark.asyncio
    async def test_dead_letter_record_with_error_extraction(self) -> None:
        """Dead letter should extract error code if present on exception."""

        class CustomError(Exception):
            def __init__(self, message: str, code: str):
                super().__init__(message)
                self.code = code

        error = CustomError("API rate limited", "RATE_LIMIT_429")
        envelope = {"payload": {"endpoint": "/api/data"}, "correlation_id": "req-999"}

        request = build_dead_letter_request_from_job(
            job_name="tasks.api_call",
            queue_name="api",
            envelope=envelope,
            error=error,
            attempt=1,
            max_attempts=5,
            error_category="rate_limited",
        )

        assert request.error_code == "RATE_LIMIT_429"
        assert request.error_detail == "API rate limited"

    @pytest.mark.asyncio
    async def test_dead_letter_record_handles_missing_correlation_id(self) -> None:
        """Dead letter should handle missing correlation_id gracefully."""
        error = ValueError("Invalid input")
        envelope = {"payload": {"data": "value"}}

        request = build_dead_letter_request_from_job(
            job_name="tasks.process",
            queue_name="default",
            envelope=envelope,
            error=error,
            attempt=1,
            max_attempts=3,
        )

        assert request.correlation_id is None
        assert "no-correlation" in request.dead_letter_key

    @pytest.mark.asyncio
    async def test_dead_letter_failure_context_includes_error_type(self) -> None:
        """Dead letter failure context should include exception type."""

        class CustomBusinessError(Exception):
            pass

        error = CustomBusinessError("Order validation failed")
        request = build_dead_letter_request_from_job(
            job_name="tasks.validate_order",
            queue_name="orders",
            envelope=None,
            error=error,
            attempt=3,
            max_attempts=3,
        )

        assert request.failure_context["error_type"] == "CustomBusinessError"
        assert request.failure_context["attempt_number"] == 3


class TestReplayFromDeadLetter:
    """Tests for replay functionality restoring original job payload."""

    @pytest.mark.asyncio
    async def test_replay_restores_original_job_payload(self) -> None:
        """Replay should restore the original job payload from dead letter."""
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock()

        record = MagicMock()
        record.id = 77
        record.message_type = "job.tasks.send_notification"
        record.correlation_id = "notif-event-1"
        record.payload_snapshot = {
            "envelope": {
                "payload": {
                    "user_id": "user-123",
                    "message": "Hello World",
                    "channel": "email",
                },
            },
        }

        request = build_replay_request_from_dead_letter(record)

        assert request.job_name == "tasks.send_notification"
        assert request.payload["user_id"] == "user-123"
        assert request.payload["message"] == "Hello World"
        assert request.payload["channel"] == "email"

        result = await replay_dead_lettered_job(mock_pool, request)
        assert result.enqueued is True

    @pytest.mark.asyncio
    async def test_replay_re_enqueues_with_all_context(self) -> None:
        """Replay should re-enqueue job with all context fields."""
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock()

        record = MagicMock()
        record.id = 88
        record.message_type = "job.tasks.process_payment"
        record.correlation_id = "payment-txn-456"
        record.payload_snapshot = {
            "envelope": {
                "payload": {"amount": 100.50, "currency": "USD"},
            },
            "tenant_id": "tenant-abc",
            "organization_id": "org-xyz",
            "metadata": {"source": "manual_replay"},
        }

        request = build_replay_request_from_dead_letter(record)
        assert request.tenant_id == "tenant-abc"
        assert request.organization_id == "org-xyz"
        assert request.metadata == {"source": "manual_replay"}

        result = await replay_dead_lettered_job(mock_pool, request)
        assert result.enqueued is True

        # Verify all context was passed to enqueue_job
        call_kwargs = mock_pool.enqueue_job.call_args[1]
        assert call_kwargs["tenant_id"] == "tenant-abc"
        assert call_kwargs["organization_id"] == "org-xyz"
        assert call_kwargs["metadata"] == {"source": "manual_replay"}
        assert call_kwargs["correlation_id"] == "payment-txn-456"
        assert call_kwargs["payload"] == {"amount": 100.50, "currency": "USD"}

    @pytest.mark.asyncio
    async def test_replay_with_queue_override(self) -> None:
        """Replay should support overriding the target queue."""
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock()

        replay_request = ReplayRequest(
            dead_letter_record_id=99,
            job_name="tasks.critical_task",
            payload={"data": "value"},
            override_queue="priority",
        )

        result = await replay_dead_lettered_job(mock_pool, replay_request)
        assert result.enqueued is True

        call_kwargs = mock_pool.enqueue_job.call_args[1]
        assert call_kwargs["_queue_name"] == "priority"

    @pytest.mark.asyncio
    async def test_replay_handles_missing_payload_snapshot(self) -> None:
        """Replay should handle missing payload_snapshot gracefully."""
        record = MagicMock()
        record.id = 111
        record.message_type = "job.tasks.cleanup"
        record.correlation_id = None
        record.payload_snapshot = None

        request = build_replay_request_from_dead_letter(record)

        assert request.job_name == "tasks.cleanup"
        assert request.payload == {}


class TestIntegrationScenarios:
    """Complex integration scenarios combining multiple components."""

    @pytest.mark.asyncio
    async def test_transient_failures_retry_with_backoff_then_succeed(self) -> None:
        """Job with transient failures should eventually succeed with retries."""
        attempt_count = 0

        class EventuallySuccessfulJob(WorkerJob):
            job_name = "tests.jobs.eventually_successful"
            retry_policy = JobRetryPolicy(max_tries=4, defer_seconds=1.0)
            backoff_policy = BackoffPolicy(
                base_delay_seconds=0.5,
                max_delay_seconds=10.0,
                multiplier=2.0,
                jitter=False,
            )

            @classmethod
            async def run(cls, ctx, envelope):
                nonlocal attempt_count
                attempt_count += 1
                if attempt_count < 3:
                    raise RetryableJobError("Service temporarily unavailable")
                return {"status": "success", "attempts": attempt_count}

        # First two attempts should raise Retry
        with pytest.raises(Retry) as exc_info:
            await EventuallySuccessfulJob.execute({"job_try": 1}, {"payload": {}})
        assert exc_info.value.defer_score == 500  # 0.5s

        with pytest.raises(Retry) as exc_info:
            await EventuallySuccessfulJob.execute({"job_try": 2}, {"payload": {}})
        assert exc_info.value.defer_score == 1000  # 1.0s

        # Third attempt should succeed
        result = await EventuallySuccessfulJob.execute({"job_try": 3}, {"payload": {}})
        assert result["status"] == "success"
        assert result["attempts"] == 3

    @pytest.mark.asyncio
    async def test_multiple_alert_hooks_different_strategies(self) -> None:
        """Multiple alert hooks with different strategies should all execute."""
        alerts_fired = []

        class AlertHook1(JobAlertHook):
            async def on_job_failure(
                self,
                *,
                job_name: str,
                envelope_data: dict,
                attempt: int,
                max_attempts: int,
                error_category: str | None,
                error_message: str,
                is_final_attempt: bool,
            ) -> None:
                alerts_fired.append(
                    ("hook1", job_name, attempt, is_final_attempt)
                )

        class AlertHook2(JobAlertHook):
            async def on_job_failure(
                self,
                *,
                job_name: str,
                envelope_data: dict,
                attempt: int,
                max_attempts: int,
                error_category: str | None,
                error_message: str,
                is_final_attempt: bool,
            ) -> None:
                alerts_fired.append(
                    ("hook2", job_name, attempt, is_final_attempt)
                )

        hook1 = AlertHook1()
        hook2 = AlertHook2()

        class DualAlertJob(WorkerJob):
            job_name = "tests.jobs.dual_alert"
            retry_policy = JobRetryPolicy(max_tries=2, defer_seconds=1.0)
            alert_hooks = [hook1, hook2]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        # First attempt
        with pytest.raises(Retry):
            await DualAlertJob.execute({"job_try": 1}, {"payload": {}})

        # Both hooks should have fired
        assert len(alerts_fired) == 2
        assert ("hook1", "tests.jobs.dual_alert", 1, False) in alerts_fired
        assert ("hook2", "tests.jobs.dual_alert", 1, False) in alerts_fired

    @pytest.mark.asyncio
    async def test_non_retryable_error_in_middle_of_max_retries(self) -> None:
        """NonRetryableJobError should fail immediately even in middle of retries."""
        mock_alert = AsyncMock(spec=JobAlertHook)

        class PermanentFailureJob(WorkerJob):
            job_name = "tests.jobs.permanent_failure"
            retry_policy = JobRetryPolicy(max_tries=5, defer_seconds=2.0)
            alert_hooks = [mock_alert]

            @classmethod
            async def run(cls, ctx, envelope):
                raise NonRetryableJobError(
                    "Permanent data corruption detected",
                    error_category="internal",
                )

        # Even on attempt 2 of 5, NonRetryableJobError should fail immediately
        with pytest.raises(NonRetryableJobError):
            await PermanentFailureJob.execute(
                {"job_try": 2},
                {"payload": {}},
            )

        # Alert should be called with is_final_attempt=True
        call_args = mock_alert.on_job_failure.call_args[1]
        assert call_args["is_final_attempt"] is True
        assert call_args["attempt"] == 2
        assert call_args["max_attempts"] == 5
