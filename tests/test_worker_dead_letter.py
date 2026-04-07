"""Tests for job dead-letter behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.core.worker.dead_letter import (
    JOB_DEAD_LETTER_NAMESPACE,
    JobDeadLetterRequest,
    JobDeadLetterResult,
    JobDeadLetterStore,
    build_dead_letter_request_from_job,
    job_dead_letter_store,
)


class TestJobDeadLetterRequest:
    def test_dead_letter_key_format(self) -> None:
        request = JobDeadLetterRequest(
            job_name="tasks.process_email",
            queue_name="default",
            correlation_id="req-123",
            attempt_count=2,
        )
        assert request.dead_letter_key == "tasks.process_email:req-123:2"

    def test_dead_letter_key_handles_missing_correlation(self) -> None:
        request = JobDeadLetterRequest(
            job_name="tasks.process_email",
            queue_name="default",
            correlation_id=None,
            attempt_count=1,
        )
        assert request.dead_letter_key == "tasks.process_email:no-correlation:1"

    def test_message_type_format(self) -> None:
        request = JobDeadLetterRequest(
            job_name="tasks.process_email",
            queue_name="default",
        )
        assert request.message_type == "job.tasks.process_email"


class TestBuildDeadLetterRequestFromJob:
    def test_builds_request_from_job_context(self) -> None:
        envelope = {
            "payload": {"email": "test@example.com"},
            "correlation_id": "req-456",
        }
        error = ValueError("Invalid email format")

        request = build_dead_letter_request_from_job(
            job_name="tasks.process_email",
            queue_name="default",
            envelope=envelope,
            error=error,
            attempt=2,
            max_attempts=3,
            error_category="ValidationError",
        )

        assert request.job_name == "tasks.process_email"
        assert request.queue_name == "default"
        assert request.correlation_id == "req-456"
        assert request.failure_category == "ValidationError"
        assert request.error_detail == "Invalid email format"
        assert request.attempt_count == 2
        assert request.max_attempts == 3
        assert request.payload_snapshot is not None
        assert request.payload_snapshot["envelope"]["correlation_id"] == "req-456"
        assert request.failure_context is not None
        assert request.failure_context["error_type"] == "ValueError"
        assert request.failure_context["attempt_number"] == 2

    def test_handles_missing_envelope_gracefully(self) -> None:
        error = RuntimeError("Connection timeout")

        request = build_dead_letter_request_from_job(
            job_name="tasks.fetch_data",
            queue_name="priority",
            envelope=None,
            error=error,
            attempt=1,
            max_attempts=5,
        )

        assert request.job_name == "tasks.fetch_data"
        assert request.queue_name == "priority"
        assert request.correlation_id is None
        assert request.payload_snapshot is not None
        assert "envelope" not in request.payload_snapshot
        assert request.failure_context["error_type"] == "RuntimeError"

    def test_extracts_error_code_if_present(self) -> None:
        error = MagicMock()
        error.code = "TIMEOUT_001"

        request = build_dead_letter_request_from_job(
            job_name="tasks.external_api_call",
            queue_name="default",
            envelope=None,
            error=error,
            attempt=3,
            max_attempts=3,
        )

        assert request.error_code == "TIMEOUT_001"


class TestJobDeadLetterStore:
    @pytest.mark.asyncio
    async def test_dead_letter_creates_record(self) -> None:
        session = AsyncMock()
        session.flush = AsyncMock()

        mock_record = MagicMock()
        mock_record.id = 99

        with patch(
            "src.app.core.worker.dead_letter.DeadLetterRecord",
            return_value=mock_record,
        ):
            store = JobDeadLetterStore()
            request = JobDeadLetterRequest(
                job_name="tasks.process_email",
                queue_name="default",
                correlation_id="req-123",
                failure_category="ValidationError",
                error_detail="Invalid format",
            )
            result = await store.dead_letter(session, request)

            assert result.dead_letter_record_id == 99
            assert result.job_name == "tasks.process_email"
            assert result.dead_letter_key == request.dead_letter_key
            session.add.assert_called_once_with(mock_record)
            session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mark_resolved_sets_status_and_timestamp(self) -> None:
        session = AsyncMock()
        session.flush = AsyncMock()

        record = MagicMock()
        record.status = "dead_lettered"
        record.resolved_at = None

        store = JobDeadLetterStore()
        result = await store.mark_resolved(session, record)

        assert result.status == "resolved"
        assert result.resolved_at is not None
        assert isinstance(result.resolved_at, datetime)
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mark_archived_sets_status_and_timestamp(self) -> None:
        session = AsyncMock()
        session.flush = AsyncMock()

        record = MagicMock()
        record.status = "dead_lettered"
        record.archived_at = None

        store = JobDeadLetterStore()
        result = await store.mark_archived(session, record)

        assert result.status == "archived"
        assert result.archived_at is not None
        assert isinstance(result.archived_at, datetime)
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mark_retrying_sets_status_and_retry_time(self) -> None:
        session = AsyncMock()
        session.flush = AsyncMock()

        record = MagicMock()
        record.status = "dead_lettered"
        record.next_retry_at = None

        retry_time = datetime.now(UTC)
        store = JobDeadLetterStore()
        result = await store.mark_retrying(session, record, next_retry_at=retry_time)

        assert result.status == "retrying"
        assert result.next_retry_at == retry_time
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mark_retrying_without_explicit_time(self) -> None:
        session = AsyncMock()
        session.flush = AsyncMock()

        record = MagicMock()
        record.status = "dead_lettered"
        record.next_retry_at = None

        store = JobDeadLetterStore()
        result = await store.mark_retrying(session, record)

        assert result.status == "retrying"
        assert result.next_retry_at is None
        session.flush.assert_awaited_once()


class TestJobDeadLetterResult:
    def test_has_default_dead_lettered_at(self) -> None:
        result = JobDeadLetterResult(
            dead_letter_record_id=42,
            job_name="tasks.process_email",
            dead_letter_key="tasks.process_email:req-123:1",
        )
        assert result.dead_lettered_at is not None
        assert isinstance(result.dead_lettered_at, datetime)


class TestJobDeadLetterNamespace:
    def test_namespace_constant(self) -> None:
        assert JOB_DEAD_LETTER_NAMESPACE == "jobs"


class TestJobDeadLetterExports:
    def test_all_expected_names_importable(self) -> None:
        from src.app.core.worker.dead_letter import (
            JOB_DEAD_LETTER_NAMESPACE,
            JobDeadLetterRequest,
            JobDeadLetterResult,
            JobDeadLetterStore,
            build_dead_letter_request_from_job,
        )

        assert JOB_DEAD_LETTER_NAMESPACE == "jobs"
        assert JobDeadLetterRequest is not None
        assert JobDeadLetterResult is not None
        assert JobDeadLetterStore is not None
        assert build_dead_letter_request_from_job is not None
        assert job_dead_letter_store is not None
