# Scheduled and Recurring Jobs

The template includes a scheduler layer built on ARQ's native cron support.
Instead of adding an external scheduler dependency, recurring jobs run inside the same ARQ worker process that handles on-demand queue jobs.

## Quick example

```python
from src.app.core.worker.scheduler import (
    CronSchedule,
    ScheduledJob,
    SchedulerContext,
    register_scheduled_job,
)


@register_scheduled_job
class DailyReportJob(ScheduledJob):
    """Generate a daily summary report at 06:00 UTC."""

    job_name = "client.scheduled.daily_report"
    schedule = CronSchedule(hour=6, minute=0, second=0)
    timeout_seconds = 600.0

    @classmethod
    async def run(cls, ctx: SchedulerContext) -> dict:
        logger = cls.get_logger()
        logger.info("Generating daily report")
        # ... project-specific logic ...
        return {"rows_processed": 42}
```

Enable the scheduler by setting `SCHEDULER_ENABLED=true` in your environment, then start the worker normally:

```bash
SCHEDULER_ENABLED=true uv run arq src.app.workers.settings.WorkerSettings
```

## How it works

1. You define a `ScheduledJob` subclass with a `CronSchedule` and implement `run()`.
2. You register it with `register_scheduled_job()` (works as a decorator too).
3. When `SCHEDULER_ENABLED=true`, the worker settings builder calls `build_cron_jobs()` to compile all registered scheduled jobs into ARQ `CronJob` entries.
4. The ARQ worker evaluates cron triggers on each tick and fires matching jobs.

Scheduled jobs share the same worker lifecycle (startup, shutdown, Redis, database) as on-demand jobs, so they have access to the same shared resources.

## CronSchedule

`CronSchedule` maps directly to ARQ's cron parameters:

| Field     | Range    | Default | Meaning                         |
|-----------|----------|---------|---------------------------------|
| `second`  | 0--59    | `None`  | Seconds (wildcard = any)        |
| `minute`  | 0--59    | `None`  | Minutes (wildcard = any)        |
| `hour`    | 0--23    | `None`  | Hours (wildcard = any)          |
| `day`     | 1--31    | `None`  | Day of month (wildcard = any)   |
| `month`   | 1--12    | `None`  | Month (wildcard = any)          |
| `weekday` | 0--6     | `None`  | Day of week, Monday=0           |

Each field accepts `None` (wildcard), a single `int`, or a `set[int]`.

```python
# Every hour at minute 0
CronSchedule(minute=0, second=0)

# Every day at 03:00 and 15:00 UTC
CronSchedule(hour={3, 15}, minute=0, second=0)

# Every Monday at 09:00 UTC
CronSchedule(weekday=0, hour=9, minute=0, second=0)

# First of every month at midnight
CronSchedule(day=1, hour=0, minute=0, second=0)
```

## ScheduledJob attributes

| Attribute                          | Type              | Default           | Purpose                                        |
|------------------------------------|-------------------|-------------------|-------------------------------------------------|
| `job_name`                         | `str`             | (required)        | Unique job identifier                           |
| `schedule`                         | `CronSchedule`    | (required)        | When the job fires                              |
| `run_at_startup`                   | `bool`            | `False`           | Run immediately when the worker starts          |
| `unique`                           | `bool`            | `True`            | ARQ-level overlap prevention                    |
| `timeout_seconds`                  | `float`           | `300.0`           | Per-execution timeout                           |
| `max_tries`                        | `int`             | `1`               | Maximum retry attempts                          |
| `keep_result_seconds`              | `float`           | `3600.0`          | How long ARQ retains the result in Redis        |
| `lock_ttl_seconds`                 | `float` or `None` | settings fallback | Distributed lock TTL for duplicate protection   |
| `clock_drift_tolerance_seconds`    | `float` or `None` | settings fallback | Minimum interval between runs                   |
| `alert_hooks`                      | `Sequence`        | `[LoggingAlertHook()]` | Notified on execution failure              |

## Duplicate execution protection

When multiple worker processes run the same cron schedule, the same job could fire simultaneously on each process.
The template provides a Redis-based distributed lock to prevent this.

Before running `run()`, the execution wrapper attempts to acquire a lock at `scheduler:lock:{job_name}` using `SET NX EX`.
If the lock is already held, the job is skipped with status `skipped_duplicate`.

Configure the lock TTL:

- Per-job: set `lock_ttl_seconds` on the class.
- Template-wide: set `SCHEDULER_LOCK_TTL_SECONDS` in your environment (default: 300 seconds).
- Disabled: set `lock_ttl_seconds = 0` to skip locking entirely.

The lock is always released after execution completes (success or failure).

## Clock drift protection

If worker processes have slightly different system clocks, a job might fire twice in quick succession.
The clock drift guard tracks the timestamp of each run in Redis at `scheduler:last_run:{job_name}` and skips runs that happen within the tolerance window of the previous execution.

Configure the tolerance:

- Per-job: set `clock_drift_tolerance_seconds` on the class.
- Template-wide: set `SCHEDULER_CLOCK_DRIFT_TOLERANCE_SECONDS` in your environment (default: 10 seconds).
- Disabled: set `clock_drift_tolerance_seconds = 0` to skip the check.

## Observability

Every scheduled job execution emits structured log events:

- **Starting**: `"Scheduled job starting"` with `job_name` and `scheduled_at`
- **Completed**: `"Scheduled job completed"` with `job_name` and `duration_seconds`
- **Skipped (duplicate)**: `"Scheduled job skipped (duplicate execution detected)"`
- **Skipped (drift)**: `"Scheduled job skipped (clock drift protection)"`
- **Failed**: `"Scheduled job failed"` with error details and stack trace

Alert hooks (`JobAlertHook` protocol) fire on every failure, matching the same interface used by on-demand worker jobs.

For durable execution history, write to the `job_state_history` ledger from your `run()` implementation.

## Configuration

| Setting                                  | Default | Purpose                                   |
|------------------------------------------|---------|-------------------------------------------|
| `SCHEDULER_ENABLED`                      | `false` | Enable cron job registration               |
| `SCHEDULER_LOCK_TTL_SECONDS`             | `300.0` | Default distributed lock TTL               |
| `SCHEDULER_CLOCK_DRIFT_TOLERANCE_SECONDS`| `10.0`  | Default minimum interval between runs      |

## Running the scheduler

**Combined mode** (recommended for most deployments): on-demand jobs and cron jobs share one worker process.

```bash
SCHEDULER_ENABLED=true uv run arq src.app.workers.settings.WorkerSettings
```

**Dedicated mode**: run a separate process that only handles cron jobs when you want to isolate scheduled work from queue throughput.

```bash
SCHEDULER_ENABLED=true python -m src.app.scheduler
```

Both approaches use the same ARQ worker runtime underneath.

## Placeholder maintenance jobs

The template ships three placeholder scheduled jobs so template adopters can see the pattern in action.
All three are safe no-ops until project-specific logic is added:

| Job name                                         | Schedule          | Purpose                              |
|--------------------------------------------------|-------------------|--------------------------------------|
| `platform.scheduled.token_blacklist_cleanup`     | Daily at 03:00    | Prune expired token blacklist rows   |
| `platform.scheduled.webhook_event_retention`     | Daily at 04:00    | Remove old webhook event records     |
| `platform.scheduled.dead_letter_retention`       | Daily at 04:30    | Clean up resolved dead-letter entries|

To replace a placeholder with real logic, subclass it or edit the `run()` method directly.
To remove a placeholder, unregister it or remove it from the module imports.

## Adding a new scheduled job

1. Create a new module or add to an existing one:

    ```python
    from src.app.core.worker.scheduler import (
        CronSchedule,
        ScheduledJob,
        SchedulerContext,
        register_scheduled_job,
    )

    @register_scheduled_job
    class WeeklyDigestJob(ScheduledJob):
        job_name = "client.scheduled.weekly_digest"
        schedule = CronSchedule(weekday=0, hour=8, minute=0, second=0)
        timeout_seconds = 300.0

        @classmethod
        async def run(cls, ctx: SchedulerContext) -> dict:
            # Access database via the shared session helpers
            # Access Redis via ctx["redis"]
            # Access settings via ctx["settings"]
            return {"sent": 15}
    ```

2. Make sure the module is imported at worker startup (add the import to your project's worker entrypoint or jobs module).

3. Set `SCHEDULER_ENABLED=true` and restart the worker.
