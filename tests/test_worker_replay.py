"""Tests for job replay behavior."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.core.worker.replay import (
    ReplayRequest,
    ReplayResult,
    build_replay_request_from_dead_letter,
    replay_dead_lettered_job,
)


class TestReplayRequest:
    def test_is_frozen_dataclass(self) -> None:
        request = ReplayRequest(
            dead_letter_record_id=1,
            job_name="tasks.process_email",
            payload={"email": "test@example.com"},
        )
        assert request.dead_letter_record_id == 1
        assert request.job_name == "tasks.process_email"
        assert request.payload == {"email": "test@example.com"}

        with pytest.raises(AttributeError):
            request.dead_letter_record_id = 2

    def test_has_expected_fields(self) -> None:
        request = ReplayRequest(
            dead_letter_record_id=1,
            job_name="tasks.process_email",
            payload={"data": "value"},
            correlation_id="req-123",
            tenant_id="tenant-456",
            organization_id="org-789",
            metadata={"source": "replay"},
            override_queue="priority",
        )
        assert request.correlation_id == "req-123"
        assert request.tenant_id == "tenant-456"
        assert request.organization_id == "org-789"
        assert request.metadata == {"source": "replay"}
        assert request.override_queue == "priority"


class TestReplayResult:
    def test_has_default_replayed_at(self) -> None:
        result = ReplayResult(
            dead_letter_record_id=1,
            job_name="tasks.process_email",
        )
        assert result.replayed_at is not None
        assert isinstance(result.replayed_at, datetime)

    def test_enqueued_defaults_to_false(self) -> None:
        result = ReplayResult(
            dead_letter_record_id=1,
            job_name="tasks.process_email",
        )
        assert result.enqueued is False

    def test_is_frozen_dataclass(self) -> None:
        result = ReplayResult(
            dead_letter_record_id=1,
            job_name="tasks.process_email",
        )
        with pytest.raises(AttributeError):
            result.dead_letter_record_id = 2


class TestBuildReplayRequestFromDeadLetter:
    def test_extracts_job_name_from_message_type(self) -> None:
        record = MagicMock()
        record.id = 42
        record.message_type = "job.tasks.process_email"
        record.correlation_id = "req-123"
        record.payload_snapshot = {
            "envelope": {
                "payload": {"email": "test@example.com"},
            },
        }

        request = build_replay_request_from_dead_letter(record)

        assert request.job_name == "tasks.process_email"

    def test_extracts_payload_from_nested_envelope(self) -> None:
        record = MagicMock()
        record.id = 1
        record.message_type = "job.tasks.fetch_data"
        record.correlation_id = None
        record.payload_snapshot = {
            "envelope": {
                "payload": {"url": "https://api.example.com/data"},
            },
        }

        request = build_replay_request_from_dead_letter(record)

        assert request.payload == {"url": "https://api.example.com/data"}

    def test_handles_missing_payload_snapshot(self) -> None:
        record = MagicMock()
        record.id = 2
        record.message_type = "job.tasks.cleanup"
        record.correlation_id = None
        record.payload_snapshot = None

        request = build_replay_request_from_dead_letter(record)

        assert request.job_name == "tasks.cleanup"
        assert request.payload == {}

    def test_handles_empty_payload_snapshot(self) -> None:
        record = MagicMock()
        record.id = 3
        record.message_type = "job.tasks.notify"
        record.correlation_id = None
        record.payload_snapshot = {}

        request = build_replay_request_from_dead_letter(record)

        assert request.job_name == "tasks.notify"
        assert request.payload == {}

    def test_extracts_contextual_information_from_snapshot(self) -> None:
        record = MagicMock()
        record.id = 4
        record.message_type = "job.tasks.process_email"
        record.correlation_id = "req-456"
        record.payload_snapshot = {
            "envelope": {
                "payload": {"email": "test@example.com"},
            },
            "tenant_id": "tenant-123",
            "organization_id": "org-456",
            "metadata": {"source": "manual_replay"},
        }

        request = build_replay_request_from_dead_letter(record)

        assert request.correlation_id == "req-456"
        assert request.tenant_id == "tenant-123"
        assert request.organization_id == "org-456"
        assert request.metadata == {"source": "manual_replay"}


class TestReplayDeadLetteredJob:
    @pytest.mark.asyncio
    async def test_enqueues_job_and_returns_success(self) -> None:
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock()

        request = ReplayRequest(
            dead_letter_record_id=1,
            job_name="tasks.process_email",
            payload={"email": "test@example.com"},
            correlation_id="req-123",
        )

        result = await replay_dead_lettered_job(pool, request)

        assert result.enqueued is True
        assert result.dead_letter_record_id == 1
        assert result.job_name == "tasks.process_email"
        assert result.error_message is None
        pool.enqueue_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_override_queue_as_queue_name(self) -> None:
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock()

        request = ReplayRequest(
            dead_letter_record_id=2,
            job_name="tasks.fetch_data",
            payload={"url": "https://api.example.com"},
            override_queue="priority",
        )

        await replay_dead_lettered_job(pool, request)

        call_args = pool.enqueue_job.call_args
        assert call_args.kwargs["_queue_name"] == "priority"

    @pytest.mark.asyncio
    async def test_returns_failure_result_on_exception(self) -> None:
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock(side_effect=ConnectionError("Redis unreachable"))

        request = ReplayRequest(
            dead_letter_record_id=3,
            job_name="tasks.notify",
            payload={},
        )

        result = await replay_dead_lettered_job(pool, request)

        assert result.enqueued is False
        assert result.dead_letter_record_id == 3
        assert result.error_message is not None
        assert "ConnectionError" in result.error_message
        assert "Redis unreachable" in result.error_message

    @pytest.mark.asyncio
    async def test_includes_all_context_in_enqueue_call(self) -> None:
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock()

        request = ReplayRequest(
            dead_letter_record_id=4,
            job_name="tasks.process_email",
            payload={"email": "test@example.com"},
            correlation_id="req-789",
            tenant_id="tenant-111",
            organization_id="org-222",
            metadata={"source": "replay"},
        )

        await replay_dead_lettered_job(pool, request)

        call_args = pool.enqueue_job.call_args
        assert call_args[0][0] == "tasks.process_email"
        assert call_args.kwargs["payload"] == {"email": "test@example.com"}
        assert call_args.kwargs["correlation_id"] == "req-789"
        assert call_args.kwargs["tenant_id"] == "tenant-111"
        assert call_args.kwargs["organization_id"] == "org-222"
        assert call_args.kwargs["metadata"] == {"source": "replay"}

    @pytest.mark.asyncio
    async def test_omits_none_context_fields(self) -> None:
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock()

        request = ReplayRequest(
            dead_letter_record_id=5,
            job_name="tasks.cleanup",
            payload={},
            correlation_id=None,
            tenant_id=None,
            organization_id=None,
            metadata=None,
        )

        await replay_dead_lettered_job(pool, request)

        call_args = pool.enqueue_job.call_args
        assert "correlation_id" not in call_args.kwargs
        assert "tenant_id" not in call_args.kwargs
        assert "organization_id" not in call_args.kwargs
        assert "metadata" not in call_args.kwargs


class TestReplayExports:
    def test_all_expected_names_importable(self) -> None:
        from src.app.core.worker.replay import (
            ReplayRequest,
            ReplayResult,
            build_replay_request_from_dead_letter,
            replay_dead_lettered_job,
        )

        assert ReplayRequest is not None
        assert ReplayResult is not None
        assert build_replay_request_from_dead_letter is not None
        assert replay_dead_lettered_job is not None
