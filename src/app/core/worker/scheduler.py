"""Reusable scheduled and recurring job primitives.

This module provides a ``ScheduledJob`` base class for defining recurring jobs
that run on a cron-like schedule within the ARQ worker runtime.  It builds on
ARQ's native ``cron()`` support so the template does not introduce an external
scheduler dependency.

Key concepts
------------
- **ScheduledJob**: abstract base class for recurring jobs.  Subclasses define
  a ``CronSchedule``, implement ``run()``, and are registered via
  ``register_scheduled_job()`` or the ``@scheduled`` decorator.
- **CronSchedule**: lightweight cron-like schedule definition that maps to
  ARQ's ``cron()`` parameters.
- **Duplicate execution protection**: optional Redis-based distributed lock
  that prevents concurrent execution of the same scheduled job across
  multiple worker processes.
- **Clock drift protection**: optional minimum-interval guard that skips a
  run when the previous execution completed less than *tolerance* seconds
  ago, protecting against near-simultaneous triggers caused by clock skew
  across hosts.
- **Observability**: structured log events at start, completion, skip, and
  failure, plus pluggable ``JobAlertHook`` integration.
- **Placeholder maintenance jobs**: the template ships three example jobs
  (token-blacklist cleanup, webhook-event retention, dead-letter retention)
  so template adopters can see the pattern in action.  All three are safe
  no-ops until project-specific logic is added.

Database vs queue state
~~~~~~~~~~~~~~~~~~~~~~~
Scheduled jobs use the ARQ worker's built-in cron runner for *timing and
transport*.  Durable execution history should be written to the
``job_state_history`` ledger from the ``run()`` implementation when needed.
The template does not persist scheduled-job results automatically; that is
left to project-specific requirements.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar, TypeAlias

from arq.cron import cron

from ..config import SettingsProfile
from .logging import bind_job_log_context, get_job_logger
from .retry import JobAlertHook, LoggingAlertHook

SchedulerContext: TypeAlias = dict[str, Any]

# ---- Redis key prefixes for distributed lock and drift tracking ----

SCHEDULER_LOCK_PREFIX: str = "scheduler:lock:"
SCHEDULER_LAST_RUN_PREFIX: str = "scheduler:last_run:"


# ---- Schedule definition ----


@dataclass(frozen=True, slots=True)
class CronSchedule:
    """Cron-like schedule definition for recurring jobs.

    Each field accepts ``None`` (wildcard — any value matches), a single
    ``int``, or a ``set[int]`` of allowed values.  The semantics mirror
    ARQ's ``cron()`` parameters:

    - ``second``:  0–59
    - ``minute``:  0–59
    - ``hour``:    0–23
    - ``day``:     1–31
    - ``month``:   1–12
    - ``weekday``: 0–6 (Monday=0)

    The default ``second={0}`` means "at the top of the minute".
    """

    second: set[int] | int | None = None
    minute: set[int] | int | None = None
    hour: set[int] | int | None = None
    day: set[int] | int | None = None
    month: set[int] | int | None = None
    weekday: set[int] | int | None = None

    @staticmethod
    def _normalize(value: set[int] | int | None) -> set[int] | None:
        """Convert a single int or set[int] to the set form ARQ expects."""
        if value is None:
            return None
        if isinstance(value, int):
            return {value}
        return value

    @property
    def arq_second(self) -> set[int] | None:
        return self._normalize(self.second)

    @property
    def arq_minute(self) -> set[int] | None:
        return self._normalize(self.minute)

    @property
    def arq_hour(self) -> set[int] | None:
        return self._normalize(self.hour)

    @property
    def arq_day(self) -> set[int] | None:
        return self._normalize(self.day)

    @property
    def arq_month(self) -> set[int] | None:
        return self._normalize(self.month)

    @property
    def arq_weekday(self) -> set[int] | None:
        return self._normalize(self.weekday)


# ---- Result container ----


@dataclass(frozen=True, slots=True)
class ScheduledJobResult:
    """Lightweight result container for a single scheduled-job execution."""

    status: str
    job_name: str
    scheduled_at: str
    completed_at: str | None = None
    duration_seconds: float | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "job_name": self.job_name,
            "scheduled_at": self.scheduled_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
            "metadata": dict(self.metadata),
        }


# ---- ScheduledJob base class ----


class ScheduledJob(ABC):
    """Base class for recurring scheduled jobs.

    Subclass attributes
    -------------------
    job_name : str
        Unique identifier for this scheduled job (required).
    schedule : CronSchedule
        When the job should run.
    run_at_startup : bool
        Whether to fire immediately when the worker starts (default ``False``).
    unique : bool
        Whether ARQ should prevent overlapping executions (default ``True``).
    timeout_seconds : float
        Per-execution timeout in seconds (default 300).
    max_tries : int
        Maximum retry attempts per execution (default 1 — no retries).
    keep_result_seconds : float
        How long ARQ retains the result in Redis (default 3600).
    lock_ttl_seconds : float | None
        Override the template-wide ``SCHEDULER_LOCK_TTL_SECONDS`` setting.
    clock_drift_tolerance_seconds : float | None
        Override the template-wide ``SCHEDULER_CLOCK_DRIFT_TOLERANCE_SECONDS``.
    alert_hooks : Sequence[JobAlertHook]
        Notified on every failed execution.
    """

    job_name: ClassVar[str]
    schedule: ClassVar[CronSchedule]
    run_at_startup: ClassVar[bool] = False
    unique: ClassVar[bool] = True
    timeout_seconds: ClassVar[float] = 300.0
    max_tries: ClassVar[int] = 1
    keep_result_seconds: ClassVar[float] = 3600.0
    lock_ttl_seconds: ClassVar[float | None] = None
    clock_drift_tolerance_seconds: ClassVar[float | None] = None
    alert_hooks: ClassVar[Sequence[JobAlertHook]] = [LoggingAlertHook()]

    @classmethod
    def cron_job(cls) -> Any:
        """Build an ARQ CronJob from this scheduled job definition."""
        target_cls = cls

        async def _cron_wrapper(ctx: SchedulerContext) -> Any:
            return await target_cls._execute_wrapper(ctx)

        sched = cls.schedule
        return cron(
            _cron_wrapper,
            name=cls.job_name,
            second=sched.arq_second,
            minute=sched.arq_minute,
            hour=sched.arq_hour,
            day=sched.arq_day,
            month=sched.arq_month,
            weekday=sched.arq_weekday,
            run_at_startup=cls.run_at_startup,
            unique=cls.unique,
            timeout=int(cls.timeout_seconds),
            max_tries=cls.max_tries,
            keep_result=cls.keep_result_seconds,
        )

    # ---- Execution wrapper with observability and guards ----

    @classmethod
    async def _execute_wrapper(cls, ctx: SchedulerContext) -> dict[str, Any]:
        """Wrap ``run()`` with duplicate protection, drift guard, and logging."""
        logger = cls.get_logger()
        scheduled_at = datetime.now(UTC)
        start_time = time.monotonic()

        bind_job_log_context(job_name=cls.job_name, ctx=ctx)
        logger.info(
            "Scheduled job starting",
            job_name=cls.job_name,
            scheduled_at=scheduled_at.isoformat(),
        )

        redis = ctx.get("redis")

        # ---- Distributed lock (duplicate execution protection) ----
        lock_key = f"{SCHEDULER_LOCK_PREFIX}{cls.job_name}"
        lock_ttl = cls._resolved_lock_ttl(ctx)
        lock_acquired = False

        if redis is not None and lock_ttl > 0:
            lock_acquired = bool(await redis.set(lock_key, "1", nx=True, ex=int(lock_ttl)))
            if not lock_acquired:
                logger.warning(
                    "Scheduled job skipped (duplicate execution detected)",
                    job_name=cls.job_name,
                    lock_key=lock_key,
                )
                return ScheduledJobResult(
                    status="skipped_duplicate",
                    job_name=cls.job_name,
                    scheduled_at=scheduled_at.isoformat(),
                ).to_dict()

        # ---- Clock drift tolerance ----
        if redis is not None:
            drift_tolerance = cls._resolved_clock_drift_tolerance(ctx)
            if drift_tolerance > 0:
                last_run_key = f"{SCHEDULER_LAST_RUN_PREFIX}{cls.job_name}"
                last_run_raw = await redis.get(last_run_key)
                if last_run_raw is not None:
                    try:
                        last_run_ts = float(last_run_raw)
                        elapsed = scheduled_at.timestamp() - last_run_ts
                        if elapsed < drift_tolerance:
                            logger.warning(
                                "Scheduled job skipped (clock drift protection)",
                                job_name=cls.job_name,
                                elapsed_seconds=round(elapsed, 3),
                                tolerance_seconds=drift_tolerance,
                            )
                            await cls._release_lock(redis, lock_key, lock_acquired)
                            return ScheduledJobResult(
                                status="skipped_clock_drift",
                                job_name=cls.job_name,
                                scheduled_at=scheduled_at.isoformat(),
                            ).to_dict()
                    except (ValueError, TypeError):
                        pass

                # Record this run timestamp for drift tracking
                await redis.set(last_run_key, str(scheduled_at.timestamp()), ex=86400)

        # ---- Execute the job ----
        try:
            result = await cls.run(ctx)
            duration = time.monotonic() - start_time

            logger.info(
                "Scheduled job completed",
                job_name=cls.job_name,
                duration_seconds=round(duration, 3),
            )

            return ScheduledJobResult(
                status="ok",
                job_name=cls.job_name,
                scheduled_at=scheduled_at.isoformat(),
                completed_at=datetime.now(UTC).isoformat(),
                duration_seconds=round(duration, 3),
                metadata=result if isinstance(result, dict) else {},
            ).to_dict()

        except Exception as exc:
            duration = time.monotonic() - start_time
            error_message = str(exc)

            logger.error(
                "Scheduled job failed",
                job_name=cls.job_name,
                duration_seconds=round(duration, 3),
                error=error_message,
                exc_info=True,
            )

            await cls._fire_alert_hooks(error_message=error_message)
            raise

        finally:
            if redis is not None:
                await cls._release_lock(redis, lock_key, lock_acquired)

    # ---- Abstract run method ----

    @classmethod
    @abstractmethod
    async def run(cls, ctx: SchedulerContext) -> Any:
        """Execute the scheduled job logic.  Subclasses must implement."""

    # ---- Helpers ----

    @classmethod
    def get_logger(cls, **bind_fields: Any) -> Any:
        """Return a structured logger pre-bound with the job name."""
        return get_job_logger(job_name=cls.job_name, **bind_fields)

    @classmethod
    def _resolved_lock_ttl(cls, ctx: SchedulerContext) -> float:
        if cls.lock_ttl_seconds is not None:
            return cls.lock_ttl_seconds
        settings_obj = ctx.get("settings")
        if isinstance(settings_obj, SettingsProfile):
            return float(settings_obj.SCHEDULER_LOCK_TTL_SECONDS)
        return 300.0

    @classmethod
    def _resolved_clock_drift_tolerance(cls, ctx: SchedulerContext) -> float:
        if cls.clock_drift_tolerance_seconds is not None:
            return cls.clock_drift_tolerance_seconds
        settings_obj = ctx.get("settings")
        if isinstance(settings_obj, SettingsProfile):
            return float(settings_obj.SCHEDULER_CLOCK_DRIFT_TOLERANCE_SECONDS)
        return 10.0

    @staticmethod
    async def _release_lock(redis: Any, lock_key: str, acquired: bool) -> None:
        """Best-effort lock release."""
        if acquired:
            try:
                await redis.delete(lock_key)
            except Exception:
                pass

    @classmethod
    async def _fire_alert_hooks(cls, *, error_message: str) -> None:
        """Invoke all configured alert hooks for a scheduled-job failure."""
        for hook in cls.alert_hooks:
            try:
                await hook.on_job_failure(
                    job_name=cls.job_name,
                    envelope_data={},
                    attempt=1,
                    max_attempts=cls.max_tries,
                    error_category=None,
                    error_message=error_message,
                    is_final_attempt=True,
                )
            except Exception:
                get_job_logger(job_name=cls.job_name).warning(
                    "Alert hook failed",
                    hook_type=type(hook).__name__,
                    exc_info=True,
                )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_scheduled_job_registry: dict[str, type[ScheduledJob]] = {}


def register_scheduled_job(job_class: type[ScheduledJob]) -> type[ScheduledJob]:
    """Register a scheduled job class.  Can also be used as a decorator.

    Example::

        @register_scheduled_job
        class MyCleanupJob(ScheduledJob):
            job_name = "client.scheduled.my_cleanup"
            schedule = CronSchedule(hour=2, minute=0)

            @classmethod
            async def run(cls, ctx):
                ...
    """
    if not hasattr(job_class, "job_name") or not job_class.job_name:
        raise ValueError(f"ScheduledJob class {job_class.__name__} must define a non-empty job_name")
    if not hasattr(job_class, "schedule"):
        raise ValueError(f"ScheduledJob class {job_class.__name__} must define a schedule")
    _scheduled_job_registry[job_class.job_name] = job_class
    return job_class


def get_scheduled_job(name: str) -> type[ScheduledJob] | None:
    """Look up a registered scheduled job by name."""
    return _scheduled_job_registry.get(name)


def get_all_scheduled_jobs() -> dict[str, type[ScheduledJob]]:
    """Return a copy of the current scheduled-job registry."""
    return dict(_scheduled_job_registry)


def build_cron_jobs() -> list[Any]:
    """Build an ARQ-compatible ``cron_jobs`` list from all registered scheduled jobs."""
    return [job_cls.cron_job() for job_cls in _scheduled_job_registry.values()]


# ---------------------------------------------------------------------------
# Placeholder maintenance jobs
# ---------------------------------------------------------------------------


class TokenBlacklistCleanupJob(ScheduledJob):
    """Placeholder: prune expired token-blacklist entries.

    Runs daily at 03:00 UTC.  Replace the ``run()`` body with project-specific
    cleanup logic (e.g. ``DELETE FROM token_blacklist WHERE expires_at < now()``).
    """

    job_name = "platform.scheduled.token_blacklist_cleanup"
    schedule = CronSchedule(hour=3, minute=0, second=0)
    run_at_startup = False
    unique = True
    timeout_seconds = 120.0
    max_tries = 1

    @classmethod
    async def run(cls, ctx: SchedulerContext) -> dict[str, Any]:
        logger = cls.get_logger()
        logger.info("Token blacklist cleanup placeholder executed")
        return {"status": "placeholder", "note": "Replace with actual cleanup logic"}


class WebhookEventRetentionJob(ScheduledJob):
    """Placeholder: prune webhook-event records past the retention window.

    Runs daily at 04:00 UTC.  Replace with a query that removes rows older
    than ``WEBHOOK_PAYLOAD_RETENTION_DAYS``.
    """

    job_name = "platform.scheduled.webhook_event_retention"
    schedule = CronSchedule(hour=4, minute=0, second=0)
    run_at_startup = False
    unique = True
    timeout_seconds = 300.0
    max_tries = 1

    @classmethod
    async def run(cls, ctx: SchedulerContext) -> dict[str, Any]:
        logger = cls.get_logger()
        logger.info("Webhook event retention cleanup placeholder executed")
        return {"status": "placeholder", "note": "Replace with actual retention logic"}


class DeadLetterRetentionJob(ScheduledJob):
    """Placeholder: prune old dead-letter records.

    Runs daily at 04:30 UTC.  Replace with a query that removes resolved
    or expired dead-letter entries.
    """

    job_name = "platform.scheduled.dead_letter_retention"
    schedule = CronSchedule(hour=4, minute=30, second=0)
    run_at_startup = False
    unique = True
    timeout_seconds = 300.0
    max_tries = 1

    @classmethod
    async def run(cls, ctx: SchedulerContext) -> dict[str, Any]:
        logger = cls.get_logger()
        logger.info("Dead-letter retention cleanup placeholder executed")
        return {"status": "placeholder", "note": "Replace with actual retention logic"}


# Register the placeholder maintenance jobs so they are included when the
# scheduler is enabled.  Template adopters can unregister or replace them.

_PLACEHOLDER_JOBS: list[type[ScheduledJob]] = [
    TokenBlacklistCleanupJob,
    WebhookEventRetentionJob,
    DeadLetterRetentionJob,
]

for _job_cls in _PLACEHOLDER_JOBS:
    register_scheduled_job(_job_cls)


__all__ = [
    "CronSchedule",
    "DeadLetterRetentionJob",
    "SCHEDULER_LAST_RUN_PREFIX",
    "SCHEDULER_LOCK_PREFIX",
    "ScheduledJob",
    "ScheduledJobResult",
    "SchedulerContext",
    "TokenBlacklistCleanupJob",
    "WebhookEventRetentionJob",
    "build_cron_jobs",
    "get_all_scheduled_jobs",
    "get_scheduled_job",
    "register_scheduled_job",
]
