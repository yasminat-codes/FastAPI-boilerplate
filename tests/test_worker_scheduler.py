"""Tests for the scheduled and recurring job primitives."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.core.worker.scheduler import (
    SCHEDULER_LAST_RUN_PREFIX,
    SCHEDULER_LOCK_PREFIX,
    CronSchedule,
    DeadLetterRetentionJob,
    ScheduledJob,
    ScheduledJobResult,
    SchedulerContext,
    TokenBlacklistCleanupJob,
    WebhookEventRetentionJob,
    build_cron_jobs,
    get_all_scheduled_jobs,
    get_scheduled_job,
    register_scheduled_job,
)

# ---------------------------------------------------------------------------
# CronSchedule
# ---------------------------------------------------------------------------


class TestCronSchedule:
    """Tests for the CronSchedule dataclass."""

    def test_default_values(self) -> None:
        sched = CronSchedule()
        assert sched.second is None
        assert sched.minute is None
        assert sched.hour is None
        assert sched.day is None
        assert sched.month is None
        assert sched.weekday is None

    def test_int_values_normalized_to_sets(self) -> None:
        sched = CronSchedule(second=0, minute=30, hour=3)
        assert sched.arq_second == {0}
        assert sched.arq_minute == {30}
        assert sched.arq_hour == {3}

    def test_set_values_pass_through(self) -> None:
        sched = CronSchedule(hour={2, 14}, minute={0, 30})
        assert sched.arq_hour == {2, 14}
        assert sched.arq_minute == {0, 30}

    def test_none_passes_through(self) -> None:
        sched = CronSchedule(hour=None)
        assert sched.arq_hour is None

    def test_all_fields_set(self) -> None:
        sched = CronSchedule(second=0, minute=15, hour=3, day=1, month=6, weekday=0)
        assert sched.arq_second == {0}
        assert sched.arq_minute == {15}
        assert sched.arq_hour == {3}
        assert sched.arq_day == {1}
        assert sched.arq_month == {6}
        assert sched.arq_weekday == {0}

    def test_is_frozen(self) -> None:
        sched = CronSchedule(hour=3)
        with pytest.raises(AttributeError):
            sched.hour = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ScheduledJobResult
# ---------------------------------------------------------------------------


class TestScheduledJobResult:
    """Tests for the ScheduledJobResult container."""

    def test_to_dict(self) -> None:
        result = ScheduledJobResult(
            status="ok",
            job_name="test.job",
            scheduled_at="2026-04-07T03:00:00+00:00",
            completed_at="2026-04-07T03:00:05+00:00",
            duration_seconds=5.0,
            metadata={"rows": 42},
        )
        d = result.to_dict()
        assert d["status"] == "ok"
        assert d["job_name"] == "test.job"
        assert d["duration_seconds"] == 5.0
        assert d["metadata"] == {"rows": 42}
        assert d["error_message"] is None

    def test_to_dict_defaults(self) -> None:
        result = ScheduledJobResult(
            status="skipped_duplicate",
            job_name="test.job",
            scheduled_at="2026-04-07T03:00:00+00:00",
        )
        d = result.to_dict()
        assert d["completed_at"] is None
        assert d["duration_seconds"] is None
        assert d["metadata"] == {}

    def test_is_frozen(self) -> None:
        result = ScheduledJobResult(status="ok", job_name="x", scheduled_at="2026-01-01T00:00:00Z")
        with pytest.raises(AttributeError):
            result.status = "bad"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestScheduledJobRegistry:
    """Tests for the scheduled-job registration system."""

    def test_placeholder_jobs_registered(self) -> None:
        registry = get_all_scheduled_jobs()
        assert "platform.scheduled.token_blacklist_cleanup" in registry
        assert "platform.scheduled.webhook_event_retention" in registry
        assert "platform.scheduled.dead_letter_retention" in registry

    def test_get_scheduled_job_found(self) -> None:
        cls = get_scheduled_job("platform.scheduled.token_blacklist_cleanup")
        assert cls is TokenBlacklistCleanupJob

    def test_get_scheduled_job_not_found(self) -> None:
        assert get_scheduled_job("nonexistent.job") is None

    def test_register_custom_job(self) -> None:
        class CustomJob(ScheduledJob):
            job_name = "test.scheduled.custom"
            schedule = CronSchedule(hour=1)

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                return {"status": "ok"}

        register_scheduled_job(CustomJob)
        assert get_scheduled_job("test.scheduled.custom") is CustomJob

    def test_register_missing_job_name(self) -> None:
        class BadJob(ScheduledJob):
            job_name = ""
            schedule = CronSchedule()

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                return None

        with pytest.raises(ValueError, match="non-empty job_name"):
            register_scheduled_job(BadJob)

    def test_get_all_returns_copy(self) -> None:
        registry = get_all_scheduled_jobs()
        registry["fake"] = None  # type: ignore[assignment]
        assert get_scheduled_job("fake") is None

    def test_build_cron_jobs_returns_list(self) -> None:
        jobs = build_cron_jobs()
        assert isinstance(jobs, list)
        assert len(jobs) >= 3  # at least the three placeholders


# ---------------------------------------------------------------------------
# ScheduledJob base class
# ---------------------------------------------------------------------------


class TestScheduledJobBase:
    """Tests for ScheduledJob defaults and class attributes."""

    def test_default_attributes(self) -> None:
        assert TokenBlacklistCleanupJob.run_at_startup is False
        assert TokenBlacklistCleanupJob.unique is True
        assert TokenBlacklistCleanupJob.max_tries == 1
        assert TokenBlacklistCleanupJob.timeout_seconds == 120.0

    def test_cron_job_produces_arq_cron(self) -> None:
        cj = TokenBlacklistCleanupJob.cron_job()
        assert cj.name == "platform.scheduled.token_blacklist_cleanup"
        assert cj.run_at_startup is False
        assert cj.unique is True

    def test_webhook_event_retention_schedule(self) -> None:
        assert WebhookEventRetentionJob.schedule.hour == 4
        assert WebhookEventRetentionJob.schedule.minute == 0

    def test_dead_letter_retention_schedule(self) -> None:
        assert DeadLetterRetentionJob.schedule.hour == 4
        assert DeadLetterRetentionJob.schedule.minute == 30


# ---------------------------------------------------------------------------
# Execute wrapper — happy path
# ---------------------------------------------------------------------------


class TestScheduledJobExecution:
    """Tests for the _execute_wrapper observability and guard logic."""

    @pytest.fixture()
    def _mock_redis(self) -> AsyncMock:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=None)
        redis.delete = AsyncMock(return_value=1)
        return redis

    @pytest.fixture()
    def _ctx(self, _mock_redis: AsyncMock) -> dict[str, Any]:
        return {"redis": _mock_redis}

    def test_happy_path_returns_ok(self, _ctx: dict[str, Any]) -> None:
        class OkJob(ScheduledJob):
            job_name = "test.scheduled.ok"
            schedule = CronSchedule(minute=0)

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> dict[str, Any]:
                return {"cleaned": 5}

        result = asyncio.run(OkJob._execute_wrapper(_ctx))
        assert result["status"] == "ok"
        assert result["metadata"] == {"cleaned": 5}
        assert result["duration_seconds"] is not None

    def test_non_dict_result_returns_empty_metadata(self, _ctx: dict[str, Any]) -> None:
        class StringResultJob(ScheduledJob):
            job_name = "test.scheduled.string_result"
            schedule = CronSchedule(minute=0)

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                return "done"

        result = asyncio.run(StringResultJob._execute_wrapper(_ctx))
        assert result["status"] == "ok"
        assert result["metadata"] == {}


# ---------------------------------------------------------------------------
# Duplicate execution protection
# ---------------------------------------------------------------------------


class TestDuplicateProtection:
    """Tests for the Redis-based distributed lock."""

    def test_skips_when_lock_not_acquired(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=False)  # lock already held
        redis.delete = AsyncMock()
        ctx: dict[str, Any] = {"redis": redis}

        class LockedJob(ScheduledJob):
            job_name = "test.scheduled.locked"
            schedule = CronSchedule(minute=0)
            lock_ttl_seconds = 60.0

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                raise AssertionError("Should not run")

        result = asyncio.run(LockedJob._execute_wrapper(ctx))
        assert result["status"] == "skipped_duplicate"

    def test_runs_when_lock_acquired(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)  # lock acquired
        redis.get = AsyncMock(return_value=None)
        redis.delete = AsyncMock()
        ctx: dict[str, Any] = {"redis": redis}

        class UnlockedJob(ScheduledJob):
            job_name = "test.scheduled.unlocked"
            schedule = CronSchedule(minute=0)
            lock_ttl_seconds = 60.0

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                return {"ran": True}

        result = asyncio.run(UnlockedJob._execute_wrapper(ctx))
        assert result["status"] == "ok"

    def test_lock_released_after_success(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=None)
        redis.delete = AsyncMock()
        ctx: dict[str, Any] = {"redis": redis}

        class ReleaseJob(ScheduledJob):
            job_name = "test.scheduled.release"
            schedule = CronSchedule(minute=0)
            lock_ttl_seconds = 60.0

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                return {}

        asyncio.run(ReleaseJob._execute_wrapper(ctx))
        redis.delete.assert_called()

    def test_lock_released_after_failure(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=None)
        redis.delete = AsyncMock()
        ctx: dict[str, Any] = {"redis": redis}

        class FailJob(ScheduledJob):
            job_name = "test.scheduled.fail_release"
            schedule = CronSchedule(minute=0)
            lock_ttl_seconds = 60.0
            alert_hooks = []  # suppress alert hooks for cleaner test

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(FailJob._execute_wrapper(ctx))
        redis.delete.assert_called()

    def test_no_lock_when_no_redis(self) -> None:
        ctx: dict[str, Any] = {}

        class NoRedisJob(ScheduledJob):
            job_name = "test.scheduled.no_redis"
            schedule = CronSchedule(minute=0)

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                return {"ran": True}

        result = asyncio.run(NoRedisJob._execute_wrapper(ctx))
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Clock drift protection
# ---------------------------------------------------------------------------


class TestClockDriftProtection:
    """Tests for the minimum-interval clock drift guard."""

    def test_skips_when_within_tolerance(self) -> None:
        import time

        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        # Simulate last run was 2 seconds ago
        redis.get = AsyncMock(return_value=str(time.time() - 2))
        redis.delete = AsyncMock()
        ctx: dict[str, Any] = {"redis": redis}

        class DriftJob(ScheduledJob):
            job_name = "test.scheduled.drift"
            schedule = CronSchedule(minute=0)
            lock_ttl_seconds = 60.0
            clock_drift_tolerance_seconds = 30.0  # 30s tolerance

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                raise AssertionError("Should be skipped")

        result = asyncio.run(DriftJob._execute_wrapper(ctx))
        assert result["status"] == "skipped_clock_drift"

    def test_runs_when_outside_tolerance(self) -> None:
        import time

        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        # Simulate last run was 120 seconds ago
        redis.get = AsyncMock(return_value=str(time.time() - 120))
        redis.delete = AsyncMock()
        ctx: dict[str, Any] = {"redis": redis}

        class OldDriftJob(ScheduledJob):
            job_name = "test.scheduled.old_drift"
            schedule = CronSchedule(minute=0)
            lock_ttl_seconds = 60.0
            clock_drift_tolerance_seconds = 30.0

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                return {"ran": True}

        result = asyncio.run(OldDriftJob._execute_wrapper(ctx))
        assert result["status"] == "ok"

    def test_runs_when_no_previous_run(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=None)
        redis.delete = AsyncMock()
        ctx: dict[str, Any] = {"redis": redis}

        class FirstRunJob(ScheduledJob):
            job_name = "test.scheduled.first_run"
            schedule = CronSchedule(minute=0)
            lock_ttl_seconds = 60.0
            clock_drift_tolerance_seconds = 30.0

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                return {"ran": True}

        result = asyncio.run(FirstRunJob._execute_wrapper(ctx))
        assert result["status"] == "ok"

    def test_handles_corrupt_last_run_value(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value="not-a-number")
        redis.delete = AsyncMock()
        ctx: dict[str, Any] = {"redis": redis}

        class CorruptJob(ScheduledJob):
            job_name = "test.scheduled.corrupt"
            schedule = CronSchedule(minute=0)
            lock_ttl_seconds = 60.0
            clock_drift_tolerance_seconds = 30.0

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                return {"ran": True}

        result = asyncio.run(CorruptJob._execute_wrapper(ctx))
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Observability (alert hooks)
# ---------------------------------------------------------------------------


class TestScheduledJobAlertHooks:
    """Tests for failure alert hook integration."""

    def test_alert_hooks_called_on_failure(self) -> None:
        hook = MagicMock()
        hook.on_job_failure = AsyncMock()
        ctx: dict[str, Any] = {}

        class AlertJob(ScheduledJob):
            job_name = "test.scheduled.alert"
            schedule = CronSchedule(minute=0)
            alert_hooks = [hook]

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                raise RuntimeError("test failure")

        with pytest.raises(RuntimeError, match="test failure"):
            asyncio.run(AlertJob._execute_wrapper(ctx))

        hook.on_job_failure.assert_awaited_once()
        call_kwargs = hook.on_job_failure.call_args
        assert call_kwargs.kwargs["job_name"] == "test.scheduled.alert"
        assert call_kwargs.kwargs["is_final_attempt"] is True

    def test_alert_hook_failure_does_not_mask_job_error(self) -> None:
        hook = MagicMock()
        hook.on_job_failure = AsyncMock(side_effect=RuntimeError("hook broke"))
        ctx: dict[str, Any] = {}

        class BrokenHookJob(ScheduledJob):
            job_name = "test.scheduled.broken_hook"
            schedule = CronSchedule(minute=0)
            alert_hooks = [hook]

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                raise RuntimeError("original error")

        with pytest.raises(RuntimeError, match="original error"):
            asyncio.run(BrokenHookJob._execute_wrapper(ctx))


# ---------------------------------------------------------------------------
# Settings resolution
# ---------------------------------------------------------------------------


class TestSettingsResolution:
    """Tests for lock TTL and drift tolerance resolution."""

    def test_lock_ttl_uses_class_override(self) -> None:
        class OverrideJob(ScheduledJob):
            job_name = "test.scheduled.override_ttl"
            schedule = CronSchedule(minute=0)
            lock_ttl_seconds = 42.0

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                return None

        assert OverrideJob._resolved_lock_ttl({}) == 42.0

    def test_lock_ttl_falls_back_to_settings(self) -> None:
        mock_settings = MagicMock()
        mock_settings.SCHEDULER_LOCK_TTL_SECONDS = 120.0
        # Make isinstance check pass
        mock_settings.__class__ = type("FakeSettings", (), {})

        class FallbackJob(ScheduledJob):
            job_name = "test.scheduled.fallback_ttl"
            schedule = CronSchedule(minute=0)
            lock_ttl_seconds = None

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                return None

        # Without settings, falls back to default 300
        assert FallbackJob._resolved_lock_ttl({}) == 300.0

    def test_drift_tolerance_uses_class_override(self) -> None:
        class DriftOverrideJob(ScheduledJob):
            job_name = "test.scheduled.drift_override"
            schedule = CronSchedule(minute=0)
            clock_drift_tolerance_seconds = 5.0

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                return None

        assert DriftOverrideJob._resolved_clock_drift_tolerance({}) == 5.0

    def test_drift_tolerance_default(self) -> None:
        class DefaultDriftJob(ScheduledJob):
            job_name = "test.scheduled.drift_default"
            schedule = CronSchedule(minute=0)

            @classmethod
            async def run(cls, ctx: SchedulerContext) -> Any:
                return None

        assert DefaultDriftJob._resolved_clock_drift_tolerance({}) == 10.0


# ---------------------------------------------------------------------------
# Placeholder maintenance jobs
# ---------------------------------------------------------------------------


class TestPlaceholderJobs:
    """Tests for the three template-shipped placeholder maintenance jobs."""

    def test_token_blacklist_cleanup_runs(self) -> None:
        ctx: dict[str, Any] = {}
        result = asyncio.run(TokenBlacklistCleanupJob.run(ctx))
        assert result["status"] == "placeholder"

    def test_webhook_event_retention_runs(self) -> None:
        ctx: dict[str, Any] = {}
        result = asyncio.run(WebhookEventRetentionJob.run(ctx))
        assert result["status"] == "placeholder"

    def test_dead_letter_retention_runs(self) -> None:
        ctx: dict[str, Any] = {}
        result = asyncio.run(DeadLetterRetentionJob.run(ctx))
        assert result["status"] == "placeholder"

    def test_token_blacklist_schedule(self) -> None:
        assert TokenBlacklistCleanupJob.schedule.hour == 3
        assert TokenBlacklistCleanupJob.schedule.minute == 0
        assert TokenBlacklistCleanupJob.schedule.second == 0

    def test_webhook_event_retention_schedule(self) -> None:
        assert WebhookEventRetentionJob.schedule.hour == 4
        assert WebhookEventRetentionJob.schedule.minute == 0

    def test_dead_letter_retention_schedule(self) -> None:
        assert DeadLetterRetentionJob.schedule.hour == 4
        assert DeadLetterRetentionJob.schedule.minute == 30


# ---------------------------------------------------------------------------
# Redis key prefixes
# ---------------------------------------------------------------------------


class TestRedisKeyPrefixes:
    """Tests for the documented Redis key prefixes."""

    def test_lock_prefix(self) -> None:
        assert SCHEDULER_LOCK_PREFIX == "scheduler:lock:"

    def test_last_run_prefix(self) -> None:
        assert SCHEDULER_LAST_RUN_PREFIX == "scheduler:last_run:"


# ---------------------------------------------------------------------------
# Export surface
# ---------------------------------------------------------------------------


class TestSchedulerExports:
    """Tests verifying the scheduler exports are accessible."""

    def test_core_worker_exports(self) -> None:
        from src.app.core.worker import (  # noqa: F401
            SCHEDULER_LAST_RUN_PREFIX,
            SCHEDULER_LOCK_PREFIX,
            CronSchedule,
            DeadLetterRetentionJob,
            ScheduledJob,
            ScheduledJobResult,
            SchedulerContext,
            TokenBlacklistCleanupJob,
            WebhookEventRetentionJob,
            build_cron_jobs,
            get_all_scheduled_jobs,
            get_scheduled_job,
            register_scheduled_job,
        )

    def test_workers_boundary_exports(self) -> None:
        from src.app.workers import (  # noqa: F401
            SCHEDULER_LAST_RUN_PREFIX,
            SCHEDULER_LOCK_PREFIX,
            CronSchedule,
            DeadLetterRetentionJob,
            ScheduledJob,
            ScheduledJobResult,
            SchedulerContext,
            TokenBlacklistCleanupJob,
            WebhookEventRetentionJob,
            build_cron_jobs,
            get_all_scheduled_jobs,
            get_scheduled_job,
            register_scheduled_job,
        )

    def test_scheduler_entrypoint_importable(self) -> None:
        from src.app.scheduler import start_scheduler  # noqa: F401


# ---------------------------------------------------------------------------
# Config settings
# ---------------------------------------------------------------------------


class TestSchedulerSettings:
    """Tests for the scheduler runtime settings."""

    def test_scheduler_settings_defaults(self) -> None:
        from src.app.core.config import settings

        assert settings.SCHEDULER_ENABLED is False
        assert settings.SCHEDULER_LOCK_TTL_SECONDS == 300.0
        assert settings.SCHEDULER_CLOCK_DRIFT_TOLERANCE_SECONDS == 10.0
