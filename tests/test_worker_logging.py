import pytest
from structlog.contextvars import clear_contextvars, get_contextvars

from src.app.core.worker.functions import on_job_end, on_job_start
from src.app.workers.jobs import WorkerProbeJob
from src.app.workers.logging import (
    JOB_LOG_CONTEXT_KEYS,
    bind_job_log_context,
    build_job_log_context,
    clear_job_log_context,
)


def test_build_job_log_context_includes_shared_job_fields() -> None:
    envelope = WorkerProbeJob.build_envelope(
        payload={"purpose": "smoke-test"},
        correlation_id="req-123",
        tenant_id="tenant-123",
        organization_id="org-123",
        metadata={"source": "tests"},
    )

    context = build_job_log_context(
        job_name=WorkerProbeJob.job_name,
        ctx={"job_id": "job-123", "job_try": 3},
        envelope=envelope,
    )

    assert context == {
        "job_id": "job-123",
        "job_name": WorkerProbeJob.job_name,
        "correlation_id": "req-123",
        "tenant_id": "tenant-123",
        "organization_id": "org-123",
        "retry_count": 2,
        "job_metadata": {"source": "tests"},
    }


def test_bind_and_clear_job_log_context_only_touch_job_keys() -> None:
    clear_contextvars()

    bind_job_log_context(
        job_name=WorkerProbeJob.job_name,
        ctx={"job_id": "job-123", "job_try": 2},
        envelope=WorkerProbeJob.build_envelope(payload={"purpose": "smoke-test"}, correlation_id="req-123"),
    )
    context = get_contextvars()
    assert context["job_id"] == "job-123"
    assert context["job_name"] == WorkerProbeJob.job_name
    assert context["correlation_id"] == "req-123"
    assert context["retry_count"] == 1

    clear_job_log_context()

    remaining_context = get_contextvars()
    assert not any(key in remaining_context for key in JOB_LOG_CONTEXT_KEYS)


@pytest.mark.asyncio
async def test_worker_hooks_bind_and_clear_job_logging_context() -> None:
    clear_contextvars()

    await on_job_start({"job_id": "job-123", "job_try": 4})
    started_context = get_contextvars()
    assert started_context["job_id"] == "job-123"
    assert started_context["retry_count"] == 3

    await on_job_end({"job_id": "job-123", "job_try": 4})
    ended_context = get_contextvars()
    assert not any(key in ended_context for key in JOB_LOG_CONTEXT_KEYS)
