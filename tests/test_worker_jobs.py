from unittest.mock import AsyncMock

import pytest
from arq.worker import Retry
from pydantic import ValidationError
from structlog.contextvars import bind_contextvars, clear_contextvars

import src.app.core.worker.jobs as core_worker_jobs_module
from src.app.core.worker.jobs import JobEnvelope, JobRetryPolicy, RetryableJobError, WorkerJob
from src.app.core.worker.settings import build_worker_settings
from src.app.platform.config import load_settings
from src.app.workers.jobs import WorkerProbeJob, worker_functions, worker_probe_job


def test_job_retry_policy_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="max_tries must be at least 1"):
        JobRetryPolicy(max_tries=0)

    with pytest.raises(ValueError, match="defer_seconds cannot be negative"):
        JobRetryPolicy(defer_seconds=-1)


def test_job_envelope_tracks_context_and_rejects_negative_retry_count() -> None:
    envelope = WorkerProbeJob.build_envelope(
        payload={"purpose": "smoke-test"},
        correlation_id="req-123",
        tenant_id="tenant-123",
        organization_id="org-123",
        metadata={"source": "tests"},
    )

    assert envelope.payload == {"purpose": "smoke-test"}
    assert envelope.correlation_id == "req-123"
    assert envelope.tenant_context.tenant_id == "tenant-123"
    assert envelope.tenant_context.organization_id == "org-123"
    assert envelope.retry_count == 0
    assert envelope.metadata == {"source": "tests"}

    with pytest.raises(ValidationError, match="retry_count cannot be negative"):
        JobEnvelope(payload={}, retry_count=-1)


def test_job_envelope_defaults_correlation_id_from_current_context() -> None:
    clear_contextvars()
    bind_contextvars(request_id="req-123", correlation_id="corr-456")

    try:
        envelope = WorkerProbeJob.build_envelope(payload={"purpose": "smoke-test"})
    finally:
        clear_contextvars()

    assert envelope.correlation_id == "corr-456"


@pytest.mark.asyncio
async def test_worker_job_converts_retryable_error_to_arq_retry() -> None:
    class RetryingJob(WorkerJob):
        job_name = "tests.jobs.retrying"
        retry_policy = JobRetryPolicy(max_tries=4, defer_seconds=9.0)

        @classmethod
        async def run(cls, ctx: dict[str, object], envelope: JobEnvelope) -> str:
            raise RetryableJobError("retry this job")

    with pytest.raises(Retry) as exc_info:
        await RetryingJob.execute({"job_try": 1}, {"payload": {}})

    assert exc_info.value.defer_score == 9000


@pytest.mark.asyncio
async def test_worker_job_runtime_retry_count_comes_from_worker_context() -> None:
    class InspectingJob(WorkerJob):
        job_name = "tests.jobs.inspecting"

        @classmethod
        async def run(cls, ctx: dict[str, object], envelope: JobEnvelope) -> int:
            return envelope.retry_count

    retry_count = await InspectingJob.execute({"job_try": 3}, {"payload": {"purpose": "smoke-test"}, "retry_count": 0})

    assert retry_count == 2


def test_worker_probe_job_registration_uses_template_policy() -> None:
    assert worker_probe_job.name == WorkerProbeJob.job_name
    assert worker_probe_job.function.name == WorkerProbeJob.job_name
    assert worker_probe_job.function.max_tries == WorkerProbeJob.retry_policy.max_tries
    assert worker_functions == [worker_probe_job.function]


def test_build_worker_settings_applies_runtime_queue_and_retention_configuration() -> None:
    configured_settings = load_settings(
        _env_file=None,
        WORKER_QUEUE_NAME="template:workers:priority",
        WORKER_MAX_JOBS=32,
        WORKER_JOB_MAX_TRIES=7,
        WORKER_KEEP_RESULT_SECONDS=1800,
        WORKER_JOB_EXPIRES_EXTRA_MS=600000,
    )

    worker_settings = build_worker_settings(configured_settings)

    assert worker_settings.queue_name == "template:workers:priority"
    assert worker_settings.max_jobs == 32
    assert worker_settings.max_tries == 7
    assert worker_settings.keep_result == 1800
    assert worker_settings.keep_result_forever is False
    assert worker_settings.expires_extra_ms == 600000


def test_worker_job_definition_uses_configured_template_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    configured_settings = load_settings(
        _env_file=None,
        WORKER_JOB_MAX_TRIES=7,
        WORKER_JOB_RETRY_DELAY_SECONDS=12.5,
        WORKER_KEEP_RESULT_SECONDS=1800,
    )
    monkeypatch.setattr(core_worker_jobs_module, "settings", configured_settings)

    class ConfiguredDefaultJob(WorkerJob):
        job_name = "tests.jobs.configured_default"

        @classmethod
        async def run(cls, ctx: dict[str, object], envelope: JobEnvelope) -> None:
            return None

    definition = ConfiguredDefaultJob.definition()

    assert definition.retry_policy.max_tries == 7
    assert definition.retry_policy.defer_seconds == 12.5
    assert definition.function.max_tries == 7
    assert definition.function.keep_result_s == 1800


def test_worker_job_definition_supports_forever_result_retention(monkeypatch: pytest.MonkeyPatch) -> None:
    configured_settings = load_settings(
        _env_file=None,
        WORKER_KEEP_RESULT_FOREVER=True,
    )
    monkeypatch.setattr(core_worker_jobs_module, "settings", configured_settings)

    class ForeverRetentionJob(WorkerJob):
        job_name = "tests.jobs.forever_retention"

        @classmethod
        async def run(cls, ctx: dict[str, object], envelope: JobEnvelope) -> None:
            return None

    definition = ForeverRetentionJob.definition()

    assert definition.function.keep_result_forever is True
    assert definition.function.keep_result_s is None


@pytest.mark.asyncio
async def test_worker_probe_job_enqueue_uses_registered_name() -> None:
    queue_pool = AsyncMock()
    enqueued_job = object()
    queue_pool.enqueue_job = AsyncMock(return_value=enqueued_job)

    job = await WorkerProbeJob.enqueue(
        queue_pool,
        payload={"purpose": "smoke-test"},
        correlation_id="req-123",
        tenant_id="tenant-123",
        organization_id="org-123",
        metadata={"source": "tests"},
    )

    assert job is enqueued_job
    queue_pool.enqueue_job.assert_awaited_once_with(
        WorkerProbeJob.job_name,
        {
            "payload": {"purpose": "smoke-test"},
            "correlation_id": "req-123",
            "tenant_context": {"tenant_id": "tenant-123", "organization_id": "org-123"},
            "retry_count": 0,
            "metadata": {"source": "tests"},
        },
    )


@pytest.mark.asyncio
async def test_worker_probe_job_enqueue_defaults_correlation_id_from_current_context() -> None:
    queue_pool = AsyncMock()
    clear_contextvars()
    bind_contextvars(request_id="req-123", correlation_id="corr-456")

    try:
        await WorkerProbeJob.enqueue(
            queue_pool,
            payload={"purpose": "smoke-test"},
        )
    finally:
        clear_contextvars()

    queue_pool.enqueue_job.assert_awaited_once_with(
        WorkerProbeJob.job_name,
        {
            "payload": {"purpose": "smoke-test"},
            "correlation_id": "corr-456",
            "tenant_context": {"tenant_id": None, "organization_id": None},
            "retry_count": 0,
            "metadata": {},
        },
    )


@pytest.mark.asyncio
async def test_worker_probe_job_returns_operational_metadata() -> None:
    result = await WorkerProbeJob.execute(
        {"job_id": "job-123", "job_try": 1},
        {
            "payload": {},
            "correlation_id": "req-123",
            "metadata": {"source": "tests"},
        },
    )

    assert result == {
        "status": "ok",
        "job_name": WorkerProbeJob.job_name,
        "correlation_id": "req-123",
        "metadata": {"source": "tests"},
    }
