"""Reusable worker job definitions and retry primitives."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Self, TypeAlias

from arq.connections import ArqRedis
from arq.jobs import Job as ArqJob
from arq.worker import Function, Retry, func
from pydantic import BaseModel, Field, model_validator
from structlog.stdlib import BoundLogger

from ..config import SettingsProfile, settings
from ..request_context import resolve_correlation_id
from .logging import bind_job_log_context, build_job_log_context, get_job_logger

WorkerContext: TypeAlias = dict[str, Any]


@dataclass(frozen=True, slots=True)
class JobRetryPolicy:
    """Base retry configuration shared across template worker jobs."""

    max_tries: int = 3
    defer_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.max_tries < 1:
            raise ValueError("Job retry policy max_tries must be at least 1")
        if self.defer_seconds < 0:
            raise ValueError("Job retry policy defer_seconds cannot be negative")


@dataclass(frozen=True, slots=True)
class JobDefinition:
    """Registered ARQ job metadata for template workers."""

    name: str
    function: Function
    retry_policy: JobRetryPolicy

    async def enqueue(self, pool: ArqRedis, *args: Any, **kwargs: Any) -> ArqJob | None:
        return await pool.enqueue_job(self.name, *args, **kwargs)


class RetryableJobError(Exception):
    """Signal that a job should be retried using the configured retry policy."""

    def __init__(self, message: str, *, defer_seconds: float | None = None) -> None:
        super().__init__(message)
        self.defer_seconds = defer_seconds


class JobTenantContext(BaseModel):
    """Optional tenant and organization context for worker jobs."""

    tenant_id: str | None = None
    organization_id: str | None = None


class JobEnvelope(BaseModel):
    """Standard worker payload envelope shared across template jobs."""

    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None
    tenant_context: JobTenantContext = Field(default_factory=JobTenantContext)
    retry_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_retry_count(self) -> Self:
        if self.retry_count < 0:
            raise ValueError("Job envelope retry_count cannot be negative")

        return self

    def with_retry_count(self, retry_count: int) -> JobEnvelope:
        return self.model_copy(update={"retry_count": retry_count})


def build_default_job_retry_policy(runtime_settings: SettingsProfile | None = None) -> JobRetryPolicy:
    """Build the template default retry policy from configured worker settings."""

    configured_settings = settings if runtime_settings is None else runtime_settings
    return JobRetryPolicy(
        max_tries=configured_settings.WORKER_JOB_MAX_TRIES,
        defer_seconds=configured_settings.WORKER_JOB_RETRY_DELAY_SECONDS,
    )


def get_default_keep_result_seconds(runtime_settings: SettingsProfile | None = None) -> float:
    """Return the configured default worker result retention."""

    configured_settings = settings if runtime_settings is None else runtime_settings
    return configured_settings.WORKER_KEEP_RESULT_SECONDS


def get_default_keep_result_forever(runtime_settings: SettingsProfile | None = None) -> bool:
    """Return whether worker results should be retained indefinitely by default."""

    configured_settings = settings if runtime_settings is None else runtime_settings
    return configured_settings.WORKER_KEEP_RESULT_FOREVER


class WorkerJob(ABC):
    """Base class for reusable template worker jobs."""

    job_name: ClassVar[str]
    retry_policy: ClassVar[JobRetryPolicy | None] = None
    timeout_seconds: ClassVar[float | None] = None
    keep_result_seconds: ClassVar[float | None] = None
    keep_result_forever: ClassVar[bool | None] = None

    @classmethod
    def definition(cls) -> JobDefinition:
        retry_policy = cls.resolved_retry_policy()
        keep_result_forever = cls.resolved_keep_result_forever()
        keep_result_seconds = None if keep_result_forever else cls.resolved_keep_result_seconds()

        return JobDefinition(
            name=cls.job_name,
            function=func(
                cls.execute,
                name=cls.job_name,
                timeout=cls.timeout_seconds,
                keep_result=keep_result_seconds,
                keep_result_forever=keep_result_forever,
                max_tries=retry_policy.max_tries,
            ),
            retry_policy=retry_policy,
        )

    @classmethod
    def resolved_retry_policy(cls) -> JobRetryPolicy:
        return build_default_job_retry_policy() if cls.retry_policy is None else cls.retry_policy

    @classmethod
    def resolved_keep_result_seconds(cls) -> float:
        return get_default_keep_result_seconds() if cls.keep_result_seconds is None else cls.keep_result_seconds

    @classmethod
    def resolved_keep_result_forever(cls) -> bool:
        return get_default_keep_result_forever() if cls.keep_result_forever is None else cls.keep_result_forever

    @classmethod
    def build_envelope(
        cls,
        *,
        payload: Mapping[str, Any],
        correlation_id: str | None = None,
        tenant_id: str | None = None,
        organization_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        retry_count: int = 0,
    ) -> JobEnvelope:
        return JobEnvelope(
            payload=dict(payload),
            correlation_id=resolve_correlation_id(correlation_id),
            tenant_context=JobTenantContext(tenant_id=tenant_id, organization_id=organization_id),
            retry_count=retry_count,
            metadata=dict(metadata or {}),
        )

    @classmethod
    async def enqueue(
        cls,
        pool: ArqRedis,
        *,
        payload: Mapping[str, Any],
        correlation_id: str | None = None,
        tenant_id: str | None = None,
        organization_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        **enqueue_options: Any,
    ) -> ArqJob | None:
        envelope = cls.build_envelope(
            payload=payload,
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            organization_id=organization_id,
            metadata=metadata,
        )
        return await cls.definition().enqueue(pool, envelope.model_dump(mode="python"), **enqueue_options)

    @classmethod
    def log_context(cls, ctx: WorkerContext, envelope: JobEnvelope | None = None) -> dict[str, Any]:
        return build_job_log_context(job_name=cls.job_name, ctx=ctx, envelope=envelope)

    @classmethod
    def get_logger(
        cls,
        *,
        ctx: WorkerContext | None = None,
        envelope: JobEnvelope | None = None,
        **bind_fields: Any,
    ) -> BoundLogger:
        return get_job_logger(job_name=cls.job_name, ctx=ctx, envelope=envelope, **bind_fields)

    @classmethod
    async def execute(cls, ctx: WorkerContext, envelope: JobEnvelope | dict[str, Any]) -> Any:
        parsed_envelope = envelope if isinstance(envelope, JobEnvelope) else JobEnvelope.model_validate(envelope)
        retry_count = cls._retry_count_from_context(ctx, fallback=parsed_envelope.retry_count)
        runtime_envelope = parsed_envelope.with_retry_count(retry_count)
        bind_job_log_context(job_name=cls.job_name, ctx=ctx, envelope=runtime_envelope)

        try:
            return await cls.run(ctx, runtime_envelope)
        except RetryableJobError as exc:
            retry_policy = cls.resolved_retry_policy()
            defer_seconds = retry_policy.defer_seconds if exc.defer_seconds is None else exc.defer_seconds
            raise Retry(defer=defer_seconds) from exc

    @classmethod
    @abstractmethod
    async def run(cls, ctx: WorkerContext, envelope: JobEnvelope) -> Any:
        """Execute the job payload."""

    @staticmethod
    def _retry_count_from_context(ctx: WorkerContext, *, fallback: int) -> int:
        job_try = ctx.get("job_try")
        if isinstance(job_try, int):
            return max(job_try - 1, 0)

        return fallback


class WorkerProbeJob(WorkerJob):
    """Internal platform job used to smoke-test the worker runtime."""

    job_name = "platform.jobs.worker_probe"
    retry_policy = JobRetryPolicy(max_tries=1, defer_seconds=0.0)
    keep_result_seconds = 60

    @classmethod
    async def run(cls, ctx: WorkerContext, envelope: JobEnvelope) -> dict[str, Any]:
        cls.get_logger(ctx=ctx, envelope=envelope).info("Worker probe completed")
        return {
            "status": "ok",
            "job_name": cls.job_name,
            "correlation_id": envelope.correlation_id,
            "metadata": dict(envelope.metadata),
        }


worker_probe_job = WorkerProbeJob.definition()
worker_functions: list[Function] = [worker_probe_job.function]

__all__ = [
    "build_default_job_retry_policy",
    "get_default_keep_result_forever",
    "get_default_keep_result_seconds",
    "JobEnvelope",
    "JobDefinition",
    "JobRetryPolicy",
    "JobTenantContext",
    "RetryableJobError",
    "WorkerContext",
    "WorkerJob",
    "WorkerProbeJob",
    "worker_functions",
    "worker_probe_job",
]
