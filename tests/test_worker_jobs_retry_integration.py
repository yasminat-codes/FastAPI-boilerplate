"""Integration tests for enhanced WorkerJob retry behavior.

Tests cover:
- NonRetryableJobError handling and propagation
- Backoff policy integration with RetryableJobError
- Alert hook invocation with correct parameters
- Alert hook exception handling
- Custom alert_hooks class variable override
"""

from unittest.mock import AsyncMock

import pytest
from arq.worker import Retry

from src.app.core.worker.jobs import JobRetryPolicy, RetryableJobError, WorkerJob
from src.app.core.worker.retry import (
    BACKOFF_FAST,
    BackoffPolicy,
    JobAlertHook,
    LoggingAlertHook,
    NonRetryableJobError,
)


class TestNonRetryableJobErrorHandling:
    """Tests for NonRetryableJobError handling in execute method."""

    @pytest.mark.asyncio
    async def test_non_retryable_error_propagates_without_conversion(self) -> None:
        """NonRetryableJobError should propagate up, not be caught/converted to Retry."""

        class NonRetryableTestJob(WorkerJob):
            job_name = "tests.jobs.non_retryable"
            retry_policy = JobRetryPolicy(max_tries=3, defer_seconds=5.0)

            @classmethod
            async def run(cls, ctx, envelope):
                raise NonRetryableJobError(
                    "Invalid input",
                    error_category="invalid_payload",
                    error_code="INVALID_INPUT",
                )

        # Should propagate the NonRetryableJobError, not convert to Retry
        with pytest.raises(NonRetryableJobError) as exc_info:
            await NonRetryableTestJob.execute({"job_try": 1}, {"payload": {}})

        assert str(exc_info.value) == "Invalid input"
        assert exc_info.value.error_category == "invalid_payload"
        assert exc_info.value.error_code == "INVALID_INPUT"

    @pytest.mark.asyncio
    async def test_non_retryable_error_calls_alert_hooks_with_is_final_attempt_true(
        self,
    ) -> None:
        """When NonRetryableJobError is raised, alert hooks should be called with is_final_attempt=True."""

        mock_alert_hook = AsyncMock(spec=JobAlertHook)

        class NonRetryableJobWithHook(WorkerJob):
            job_name = "tests.jobs.non_retryable_hook"
            retry_policy = JobRetryPolicy(max_tries=3, defer_seconds=5.0)
            alert_hooks = [mock_alert_hook]

            @classmethod
            async def run(cls, ctx, envelope):
                raise NonRetryableJobError(
                    "Resource not found",
                    error_category="not_found",
                )

        with pytest.raises(NonRetryableJobError):
            await NonRetryableJobWithHook.execute(
                {"job_try": 2},
                {"payload": {"id": "123"}},
            )

        # Verify alert hook was called with is_final_attempt=True
        mock_alert_hook.on_job_failure.assert_awaited_once()
        call_kwargs = mock_alert_hook.on_job_failure.call_args[1]
        assert call_kwargs["is_final_attempt"] is True
        assert call_kwargs["attempt"] == 2
        assert call_kwargs["max_attempts"] == 3
        assert call_kwargs["error_category"] == "not_found"

    @pytest.mark.asyncio
    async def test_non_retryable_error_on_final_attempt_calls_hooks_correctly(
        self,
    ) -> None:
        """NonRetryableJobError on final attempt should still call hooks with is_final_attempt=True."""

        mock_alert_hook = AsyncMock(spec=JobAlertHook)

        class NonRetryableJobFinalAttempt(WorkerJob):
            job_name = "tests.jobs.non_retryable_final"
            retry_policy = JobRetryPolicy(max_tries=2, defer_seconds=5.0)
            alert_hooks = [mock_alert_hook]

            @classmethod
            async def run(cls, ctx, envelope):
                raise NonRetryableJobError("Auth failed", error_category="authentication")

        with pytest.raises(NonRetryableJobError):
            await NonRetryableJobFinalAttempt.execute(
                {"job_try": 2},  # attempt 2 of 2
                {"payload": {}},
            )

        mock_alert_hook.on_job_failure.assert_awaited_once()
        assert (
            mock_alert_hook.on_job_failure.call_args[1]["is_final_attempt"] is True
        )


class TestBackoffPolicyIntegration:
    """Tests for backoff_policy integration with RetryableJobError."""

    @pytest.mark.asyncio
    async def test_backoff_policy_overrides_flat_defer_seconds(self) -> None:
        """When backoff_policy is set, it should override RetryableJobError.defer_seconds."""

        # Use deterministic backoff for predictable testing
        backoff = BackoffPolicy(
            base_delay_seconds=2.0,
            max_delay_seconds=100.0,
            multiplier=2.0,
            jitter=False,
        )

        class BackoffTestJob(WorkerJob):
            job_name = "tests.jobs.backoff_test"
            retry_policy = JobRetryPolicy(max_tries=3, defer_seconds=999.0)
            backoff_policy = backoff

            @classmethod
            async def run(cls, ctx, envelope):
                # This defer_seconds should be ignored because backoff_policy is set
                raise RetryableJobError(
                    "transient failure",
                    defer_seconds=777.0,
                )

        with pytest.raises(Retry) as exc_info:
            await BackoffTestJob.execute(
                {"job_try": 1},  # attempt 0 (0-indexed)
                {"payload": {}},
            )

        # Attempt 0: delay should be base_delay * (2^0) = 2.0
        # defer_score is in milliseconds
        assert exc_info.value.defer_score == 2000

    @pytest.mark.asyncio
    async def test_backoff_policy_scales_with_attempt_number(self) -> None:
        """Backoff policy should scale delay with each retry attempt."""

        backoff = BackoffPolicy(
            base_delay_seconds=1.0,
            max_delay_seconds=100.0,
            multiplier=2.0,
            jitter=False,
        )

        class BackoffScaleJob(WorkerJob):
            job_name = "tests.jobs.backoff_scale"
            retry_policy = JobRetryPolicy(max_tries=4, defer_seconds=0.0)
            backoff_policy = backoff

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        # Attempt 1 (job_try=2): retry_count=1, delay = 1.0 * 2^1 = 2.0s
        with pytest.raises(Retry) as exc_info:
            await BackoffScaleJob.execute({"job_try": 2}, {"payload": {}})
        assert exc_info.value.defer_score == 2000

        # Attempt 2 (job_try=3): retry_count=2, delay = 1.0 * 2^2 = 4.0s
        with pytest.raises(Retry) as exc_info:
            await BackoffScaleJob.execute({"job_try": 3}, {"payload": {}})
        assert exc_info.value.defer_score == 4000

    @pytest.mark.asyncio
    async def test_backoff_policy_none_uses_retry_error_defer_seconds(self) -> None:
        """When backoff_policy is None, RetryableJobError.defer_seconds should be used."""

        class NoBackoffJob(WorkerJob):
            job_name = "tests.jobs.no_backoff"
            retry_policy = JobRetryPolicy(max_tries=3, defer_seconds=5.0)
            backoff_policy = None  # Explicitly None

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError(
                    "transient failure",
                    defer_seconds=7.5,
                )

        with pytest.raises(Retry) as exc_info:
            await NoBackoffJob.execute({"job_try": 1}, {"payload": {}})

        # Should use the explicit defer_seconds from the exception
        assert exc_info.value.defer_score == 7500

    @pytest.mark.asyncio
    async def test_backoff_policy_none_falls_back_to_retry_policy_defer_seconds(
        self,
    ) -> None:
        """When backoff_policy is None and RetryableJobError.defer_seconds is None,
        use JobRetryPolicy.defer_seconds."""

        class FallbackJob(WorkerJob):
            job_name = "tests.jobs.fallback"
            retry_policy = JobRetryPolicy(max_tries=3, defer_seconds=6.0)
            backoff_policy = None

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("transient failure")
                # defer_seconds is None

        with pytest.raises(Retry) as exc_info:
            await FallbackJob.execute({"job_try": 1}, {"payload": {}})

        # Should fall back to retry_policy.defer_seconds
        assert exc_info.value.defer_score == 6000

    @pytest.mark.asyncio
    async def test_backoff_policy_respects_max_delay_cap(self) -> None:
        """Backoff policy should cap delays at max_delay_seconds."""

        backoff = BackoffPolicy(
            base_delay_seconds=10.0,
            max_delay_seconds=30.0,
            multiplier=2.0,
            jitter=False,
        )

        class BackoffCapJob(WorkerJob):
            job_name = "tests.jobs.backoff_cap"
            retry_policy = JobRetryPolicy(max_tries=5, defer_seconds=0.0)
            backoff_policy = backoff

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        # Attempt 3 (job_try=4): retry_count=3
        # Calculated: 10.0 * 2^3 = 80.0s, capped at 30.0s
        with pytest.raises(Retry) as exc_info:
            await BackoffCapJob.execute({"job_try": 4}, {"payload": {}})

        assert exc_info.value.defer_score == 30000


class TestAlertHooks:
    """Tests for alert hook invocation and handling."""

    @pytest.mark.asyncio
    async def test_alert_hooks_called_on_retryable_error(self) -> None:
        """Alert hooks should be called when RetryableJobError is raised."""

        mock_hook = AsyncMock(spec=JobAlertHook)

        class HookedJob(WorkerJob):
            job_name = "tests.jobs.hooked"
            retry_policy = JobRetryPolicy(max_tries=3, defer_seconds=5.0)
            alert_hooks = [mock_hook]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("transient issue")

        with pytest.raises(Retry):
            await HookedJob.execute({"job_try": 1}, {"payload": {"key": "value"}})

        mock_hook.on_job_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_alert_hooks_receive_correct_attempt_numbers(self) -> None:
        """Alert hooks should receive correct attempt and max_attempts."""

        mock_hook = AsyncMock(spec=JobAlertHook)

        class AttemptCountJob(WorkerJob):
            job_name = "tests.jobs.attempt_count"
            retry_policy = JobRetryPolicy(max_tries=4, defer_seconds=5.0)
            alert_hooks = [mock_hook]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        # job_try=3 means attempt 3 out of 4
        with pytest.raises(Retry):
            await AttemptCountJob.execute({"job_try": 3}, {"payload": {}})

        call_kwargs = mock_hook.on_job_failure.call_args[1]
        assert call_kwargs["attempt"] == 3
        assert call_kwargs["max_attempts"] == 4

    @pytest.mark.asyncio
    async def test_alert_hooks_is_final_attempt_false_on_retry(self) -> None:
        """Alert hooks should receive is_final_attempt=False when retry is possible."""

        mock_hook = AsyncMock(spec=JobAlertHook)

        class NotFinalJob(WorkerJob):
            job_name = "tests.jobs.not_final"
            retry_policy = JobRetryPolicy(max_tries=3, defer_seconds=5.0)
            alert_hooks = [mock_hook]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        # Attempt 1 of 3
        with pytest.raises(Retry):
            await NotFinalJob.execute({"job_try": 1}, {"payload": {}})

        call_kwargs = mock_hook.on_job_failure.call_args[1]
        assert call_kwargs["is_final_attempt"] is False

    @pytest.mark.asyncio
    async def test_alert_hooks_is_final_attempt_true_on_max_attempts(self) -> None:
        """Alert hooks should receive is_final_attempt=True on final attempt."""

        mock_hook = AsyncMock(spec=JobAlertHook)

        class FinalAttemptJob(WorkerJob):
            job_name = "tests.jobs.final_attempt"
            retry_policy = JobRetryPolicy(max_tries=3, defer_seconds=5.0)
            alert_hooks = [mock_hook]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        # Attempt 3 of 3 (job_try=3)
        with pytest.raises(Retry):
            await FinalAttemptJob.execute({"job_try": 3}, {"payload": {}})

        call_kwargs = mock_hook.on_job_failure.call_args[1]
        assert call_kwargs["attempt"] == 3
        assert call_kwargs["max_attempts"] == 3
        assert call_kwargs["is_final_attempt"] is True

    @pytest.mark.asyncio
    async def test_alert_hook_exception_is_caught_and_logged(self) -> None:
        """If an alert hook raises an exception, it should be caught and logged."""

        failing_hook = AsyncMock(spec=JobAlertHook)
        failing_hook.on_job_failure.side_effect = RuntimeError("Hook failed!")

        working_hook = AsyncMock(spec=JobAlertHook)

        class FailingHookJob(WorkerJob):
            job_name = "tests.jobs.failing_hook"
            retry_policy = JobRetryPolicy(max_tries=2, defer_seconds=5.0)
            alert_hooks = [failing_hook, working_hook]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        # The job execution should not crash due to hook failure
        with pytest.raises(Retry):
            await FailingHookJob.execute({"job_try": 1}, {"payload": {}})

        # Both hooks should have been called
        failing_hook.on_job_failure.assert_awaited_once()
        working_hook.on_job_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_alert_hooks_all_invoked(self) -> None:
        """All configured alert hooks should be invoked."""

        hook1 = AsyncMock(spec=JobAlertHook)
        hook2 = AsyncMock(spec=JobAlertHook)
        hook3 = AsyncMock(spec=JobAlertHook)

        class MultiHookJob(WorkerJob):
            job_name = "tests.jobs.multi_hook"
            retry_policy = JobRetryPolicy(max_tries=2, defer_seconds=5.0)
            alert_hooks = [hook1, hook2, hook3]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        with pytest.raises(Retry):
            await MultiHookJob.execute({"job_try": 1}, {"payload": {}})

        hook1.on_job_failure.assert_awaited_once()
        hook2.on_job_failure.assert_awaited_once()
        hook3.on_job_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_alert_hooks_receive_envelope_data(self) -> None:
        """Alert hooks should receive complete envelope data."""

        mock_hook = AsyncMock(spec=JobAlertHook)

        class EnvelopeDataJob(WorkerJob):
            job_name = "tests.jobs.envelope_data"
            retry_policy = JobRetryPolicy(max_tries=2, defer_seconds=5.0)
            alert_hooks = [mock_hook]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        with pytest.raises(Retry):
            await EnvelopeDataJob.execute(
                {"job_try": 1},
                {
                    "payload": {"user_id": "123"},
                    "correlation_id": "corr-456",
                    "tenant_context": {"tenant_id": "tenant-789"},
                },
            )

        call_kwargs = mock_hook.on_job_failure.call_args[1]
        envelope_data = call_kwargs["envelope_data"]
        assert envelope_data["payload"] == {"user_id": "123"}
        assert envelope_data["correlation_id"] == "corr-456"

    @pytest.mark.asyncio
    async def test_alert_hooks_receive_error_details(self) -> None:
        """Alert hooks should receive error category and message."""

        mock_hook = AsyncMock(spec=JobAlertHook)

        class ErrorDetailsJob(WorkerJob):
            job_name = "tests.jobs.error_details"
            retry_policy = JobRetryPolicy(max_tries=2, defer_seconds=5.0)
            alert_hooks = [mock_hook]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError(
                    "External API timeout",
                    # Note: RetryableJobError doesn't have error_category attr by default
                )

        with pytest.raises(Retry):
            await ErrorDetailsJob.execute({"job_try": 1}, {"payload": {}})

        call_kwargs = mock_hook.on_job_failure.call_args[1]
        assert call_kwargs["error_message"] == "External API timeout"

    @pytest.mark.asyncio
    async def test_custom_alert_hooks_override_default(self) -> None:
        """Custom alert_hooks class variable should override the default LoggingAlertHook."""

        custom_hook = AsyncMock(spec=JobAlertHook)

        class CustomHookJob(WorkerJob):
            job_name = "tests.jobs.custom_hook"
            retry_policy = JobRetryPolicy(max_tries=2, defer_seconds=5.0)
            alert_hooks = [custom_hook]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail")

        with pytest.raises(Retry):
            await CustomHookJob.execute({"job_try": 1}, {"payload": {}})

        # Custom hook should be called
        custom_hook.on_job_failure.assert_awaited_once()


class TestWorkerJobClassAttributes:
    """Tests for WorkerJob class attributes and defaults."""

    def test_default_alert_hooks_is_logging_alert_hook(self) -> None:
        """WorkerJob.alert_hooks should default to [LoggingAlertHook()]."""

        class DefaultHookJob(WorkerJob):
            job_name = "tests.jobs.default_hook"

            @classmethod
            async def run(cls, ctx, envelope):
                pass

        # Default alert_hooks should be a sequence
        assert len(DefaultHookJob.alert_hooks) > 0
        # First hook should be LoggingAlertHook
        assert isinstance(DefaultHookJob.alert_hooks[0], LoggingAlertHook)

    def test_default_backoff_policy_is_none(self) -> None:
        """WorkerJob.backoff_policy should default to None."""

        class NoBackoffJob(WorkerJob):
            job_name = "tests.jobs.no_backoff_default"

            @classmethod
            async def run(cls, ctx, envelope):
                pass

        assert NoBackoffJob.backoff_policy is None

    def test_custom_backoff_policy_can_be_set(self) -> None:
        """WorkerJob subclasses can set a custom backoff_policy."""

        class CustomBackoffJob(WorkerJob):
            job_name = "tests.jobs.custom_backoff"
            backoff_policy = BACKOFF_FAST

            @classmethod
            async def run(cls, ctx, envelope):
                pass

        assert CustomBackoffJob.backoff_policy is BACKOFF_FAST

    def test_custom_alert_hooks_can_be_set(self) -> None:
        """WorkerJob subclasses can set custom alert_hooks."""

        custom_hook = LoggingAlertHook()

        class CustomHooksJob(WorkerJob):
            job_name = "tests.jobs.custom_hooks"
            alert_hooks = [custom_hook]

            @classmethod
            async def run(cls, ctx, envelope):
                pass

        assert CustomHooksJob.alert_hooks[0] is custom_hook


class TestNonRetryableJobErrorExportAndImports:
    """Tests for verifying correct imports and exports."""

    def test_non_retryable_job_error_importable_from_core_worker_jobs(self) -> None:
        """NonRetryableJobError should be importable from core.worker.jobs."""
        from src.app.core.worker.jobs import NonRetryableJobError as CoreError

        assert CoreError is NonRetryableJobError

    def test_non_retryable_job_error_importable_from_workers_jobs(self) -> None:
        """NonRetryableJobError should be importable from workers.jobs."""
        from src.app.workers.jobs import NonRetryableJobError as WorkerError

        assert WorkerError is NonRetryableJobError

    def test_backoff_policy_importable_from_workers(self) -> None:
        """BackoffPolicy should be importable from workers package."""
        from src.app.workers import BackoffPolicy as WorkersBackoffPolicy

        assert WorkersBackoffPolicy is BackoffPolicy

    def test_job_alert_hook_importable_from_workers(self) -> None:
        """JobAlertHook should be importable from workers package."""
        from src.app.workers import JobAlertHook as WorkersJobAlertHook

        assert WorkersJobAlertHook is JobAlertHook

    def test_logging_alert_hook_importable_from_workers(self) -> None:
        """LoggingAlertHook should be importable from workers package."""
        from src.app.workers import LoggingAlertHook as WorkersLoggingAlertHook

        assert WorkersLoggingAlertHook is LoggingAlertHook


class TestRetryableErrorWithBackoffInteraction:
    """Integration tests for RetryableJobError and backoff_policy interaction."""

    @pytest.mark.asyncio
    async def test_retry_error_defer_seconds_ignored_when_backoff_policy_set(
        self,
    ) -> None:
        """When backoff_policy is set, RetryableJobError.defer_seconds should be ignored."""

        backoff = BackoffPolicy(
            base_delay_seconds=3.0,
            max_delay_seconds=100.0,
            multiplier=2.0,
            jitter=False,
        )

        class BackoffOverridesJob(WorkerJob):
            job_name = "tests.jobs.backoff_overrides"
            retry_policy = JobRetryPolicy(max_tries=3, defer_seconds=999.0)
            backoff_policy = backoff

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError(
                    "fail",
                    defer_seconds=888.0,
                )

        with pytest.raises(Retry) as exc_info:
            await BackoffOverridesJob.execute(
                {"job_try": 1},  # retry_count=0, attempt=1
                {"payload": {}},
            )

        # delay_for_attempt(0) = 3.0 * 2^0 = 3.0
        assert exc_info.value.defer_score == 3000

    @pytest.mark.asyncio
    async def test_priority_order_backoff_override_error_override_policy(
        self,
    ) -> None:
        """Priority: backoff_policy > error.defer_seconds > policy.defer_seconds."""

        backoff = BackoffPolicy(
            base_delay_seconds=1.0,
            max_delay_seconds=100.0,
            multiplier=2.0,
            jitter=False,
        )

        class PriorityJob(WorkerJob):
            job_name = "tests.jobs.priority"
            retry_policy = JobRetryPolicy(max_tries=3, defer_seconds=100.0)
            backoff_policy = backoff

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("fail", defer_seconds=50.0)

        with pytest.raises(Retry) as exc_info:
            await PriorityJob.execute({"job_try": 2}, {"payload": {}})

        # Should use backoff (1.0 * 2^1 = 2.0), not 50.0 or 100.0
        assert exc_info.value.defer_score == 2000


class TestAlertHooksWithNonRetryableError:
    """Tests for alert hook behavior with NonRetryableJobError."""

    @pytest.mark.asyncio
    async def test_alert_hook_receives_error_category_from_non_retryable_error(
        self,
    ) -> None:
        """Alert hooks should receive error_category from NonRetryableJobError."""

        mock_hook = AsyncMock(spec=JobAlertHook)

        class NonRetryableHookJob(WorkerJob):
            job_name = "tests.jobs.non_retryable_hook_cat"
            retry_policy = JobRetryPolicy(max_tries=2, defer_seconds=5.0)
            alert_hooks = [mock_hook]

            @classmethod
            async def run(cls, ctx, envelope):
                raise NonRetryableJobError(
                    "Invalid request",
                    error_category="invalid_payload",
                    error_code="BAD_INPUT",
                )

        with pytest.raises(NonRetryableJobError):
            await NonRetryableHookJob.execute({"job_try": 1}, {"payload": {}})

        call_kwargs = mock_hook.on_job_failure.call_args[1]
        assert call_kwargs["error_category"] == "invalid_payload"
        assert call_kwargs["error_message"] == "Invalid request"

    @pytest.mark.asyncio
    async def test_alert_hook_receives_none_error_category_for_retryable_without_category(
        self,
    ) -> None:
        """Alert hooks should receive None for error_category if RetryableJobError has none."""

        mock_hook = AsyncMock(spec=JobAlertHook)

        class RetryableNoCategoryJob(WorkerJob):
            job_name = "tests.jobs.retryable_no_category"
            retry_policy = JobRetryPolicy(max_tries=2, defer_seconds=5.0)
            alert_hooks = [mock_hook]

            @classmethod
            async def run(cls, ctx, envelope):
                raise RetryableJobError("transient issue")

        with pytest.raises(Retry):
            await RetryableNoCategoryJob.execute({"job_try": 1}, {"payload": {}})

        call_kwargs = mock_hook.on_job_failure.call_args[1]
        # RetryableJobError doesn't have error_category, so should be None
        assert call_kwargs["error_category"] is None
