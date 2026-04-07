"""Canonical scheduler runtime entrypoint.

The template scheduler is implemented as an ARQ worker with cron-job support
enabled.  When ``SCHEDULER_ENABLED=true`` in your environment, all registered
``ScheduledJob`` subclasses are compiled into ARQ ``CronJob`` entries and
executed alongside the regular worker function list.

Running the scheduler
~~~~~~~~~~~~~~~~~~~~~
The simplest approach is to set ``SCHEDULER_ENABLED=true`` and run the
standard ARQ worker — cron jobs and on-demand jobs share the same process::

    SCHEDULER_ENABLED=true uv run arq src.app.workers.settings.WorkerSettings

If you prefer a **dedicated** scheduler process that only handles cron jobs
(useful when the cron workload should not compete with on-demand job
throughput), run this module directly::

    SCHEDULER_ENABLED=true python -m src.app.scheduler

Both approaches use the same underlying ``start_arq_service()`` call.
The only difference is operational: a separate process isolates scheduled
work from queue-driven work.
"""

from .core.worker.settings import start_arq_service


def start_scheduler() -> None:
    """Start the ARQ worker runtime with scheduled-job support.

    This is a thin wrapper around ``start_arq_service()`` provided as a
    named entrypoint for clarity.  It relies on ``SCHEDULER_ENABLED=true``
    being set so the worker settings builder includes the registered cron
    jobs.
    """
    start_arq_service()


if __name__ == "__main__":
    start_scheduler()
