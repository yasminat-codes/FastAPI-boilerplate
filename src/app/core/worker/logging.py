"""Shared structured logging helpers for worker jobs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import structlog
from structlog.contextvars import bind_contextvars, get_contextvars, unbind_contextvars
from structlog.stdlib import BoundLogger

JOB_LOG_CONTEXT_KEYS = (
    "job_id",
    "job_name",
    "correlation_id",
    "tenant_id",
    "organization_id",
    "retry_count",
    "job_metadata",
)
DEFAULT_JOB_LOGGER_NAME = "app.worker.jobs"


def _get_field(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)

    return getattr(value, key, None)


def _filter_none(fields: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


def build_job_log_context(
    *,
    job_name: str | None = None,
    ctx: Mapping[str, Any] | None = None,
    envelope: Any | None = None,
) -> dict[str, Any]:
    """Build the structured context shared across worker-job logs."""

    tenant_context = _get_field(envelope, "tenant_context")
    envelope_retry_count = _get_field(envelope, "retry_count")
    job_try = None if ctx is None else ctx.get("job_try")

    retry_count = envelope_retry_count if isinstance(envelope_retry_count, int) else None
    if isinstance(job_try, int):
        retry_count = max(job_try - 1, 0)

    fields = {
        "job_id": None if ctx is None else ctx.get("job_id"),
        "job_name": job_name,
        "correlation_id": _get_field(envelope, "correlation_id"),
        "tenant_id": _get_field(tenant_context, "tenant_id"),
        "organization_id": _get_field(tenant_context, "organization_id"),
        "retry_count": retry_count,
        "job_metadata": _get_field(envelope, "metadata"),
    }
    return _filter_none(fields)


def bind_job_log_context(
    *,
    job_name: str | None = None,
    ctx: Mapping[str, Any] | None = None,
    envelope: Any | None = None,
) -> dict[str, Any]:
    """Bind worker-job contextvars for the current execution scope."""

    fields = build_job_log_context(job_name=job_name, ctx=ctx, envelope=envelope)
    if fields:
        bind_contextvars(**fields)
    return fields


def clear_job_log_context() -> None:
    """Remove worker-job contextvars without touching unrelated context."""

    current_context = get_contextvars()
    keys_to_remove = [key for key in JOB_LOG_CONTEXT_KEYS if key in current_context]
    if keys_to_remove:
        unbind_contextvars(*keys_to_remove)


def get_job_logger(
    *,
    job_name: str | None = None,
    ctx: Mapping[str, Any] | None = None,
    envelope: Any | None = None,
    **bind_fields: Any,
) -> BoundLogger:
    """Return a structured logger pre-bound with worker-job context."""

    fields = build_job_log_context(job_name=job_name, ctx=ctx, envelope=envelope)
    fields.update(_filter_none(bind_fields))
    logger = structlog.get_logger(DEFAULT_JOB_LOGGER_NAME)
    return cast(BoundLogger, logger.bind(**fields))


__all__ = [
    "DEFAULT_JOB_LOGGER_NAME",
    "JOB_LOG_CONTEXT_KEYS",
    "bind_job_log_context",
    "build_job_log_context",
    "clear_job_log_context",
    "get_job_logger",
]
