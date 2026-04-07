"""Concurrency guidance and queue profile helpers for the worker platform.

Different queue types have different concurrency needs.  A webhook intake
queue benefits from high parallelism because each job is I/O-bound and
short-lived, while a report-generation queue should run fewer concurrent
jobs because each one is CPU- or memory-intensive.

This module provides :class:`QueueConcurrencyProfile` as a typed record of
recommended ARQ worker settings per queue purpose, and ships a set of
pre-built profiles that template adopters can use as starting points.

How ARQ concurrency works
-------------------------
ARQ controls concurrency with a single ``max_jobs`` setting on the worker
process.  Each worker polls one queue and runs up to ``max_jobs`` coroutines
concurrently.  To run different concurrency limits per queue you deploy
separate worker processes, each configured for its own queue name and
``max_jobs`` value.

Template guidance
-----------------

+--------------------+----------+------------------------------------------------+
| Queue purpose      | max_jobs | Rationale                                      |
+====================+==========+================================================+
| default            |    10    | Balanced starting point for mixed workloads.   |
+--------------------+----------+------------------------------------------------+
| webhook ingest     |    25    | Short I/O-bound jobs, high throughput needed.  |
+--------------------+----------+------------------------------------------------+
| email / notify     |    15    | Moderate I/O, often rate-limited by provider.  |
+--------------------+----------+------------------------------------------------+
| integration sync   |    10    | Mixed I/O with external API rate limits.       |
+--------------------+----------+------------------------------------------------+
| reports / export   |     3    | CPU/memory heavy, protect worker stability.    |
+--------------------+----------+------------------------------------------------+
| scheduled / cron   |     5    | Low volume, avoid starving other queues.       |
+--------------------+----------+------------------------------------------------+

Deploying multiple queue profiles
---------------------------------
Run one worker process per profile::

    # default queue
    WORKER_QUEUE_NAME=arq:platform:default WORKER_MAX_JOBS=10 uv run arq ...

    # webhook ingest queue
    WORKER_QUEUE_NAME=arq:webhooks:ingest WORKER_MAX_JOBS=25 uv run arq ...

    # heavy reports queue
    WORKER_QUEUE_NAME=arq:client:reports WORKER_MAX_JOBS=3 uv run arq ...
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QueueConcurrencyProfile:
    """Recommended concurrency settings for a class of queue work.

    Attributes
    ----------
    name:
        Human-readable profile label (e.g. ``"webhook-ingest"``).
    max_jobs:
        Suggested ``WORKER_MAX_JOBS`` for this queue type.
    description:
        Short rationale for the recommendation.
    job_timeout_seconds:
        Suggested per-job timeout.  ``None`` means use the ARQ default.
    """

    name: str
    max_jobs: int
    description: str
    job_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.max_jobs < 1:
            raise ValueError(f"max_jobs must be at least 1, got {self.max_jobs}")
        if self.job_timeout_seconds is not None and self.job_timeout_seconds <= 0:
            raise ValueError(f"job_timeout_seconds must be positive, got {self.job_timeout_seconds}")


# ---------------------------------------------------------------------------
# Pre-built profiles
# ---------------------------------------------------------------------------

PROFILE_DEFAULT = QueueConcurrencyProfile(
    name="default",
    max_jobs=10,
    description="Balanced starting point for mixed workloads.",
    job_timeout_seconds=300,
)

PROFILE_WEBHOOK_INGEST = QueueConcurrencyProfile(
    name="webhook-ingest",
    max_jobs=25,
    description="Short I/O-bound webhook processing jobs requiring high throughput.",
    job_timeout_seconds=60,
)

PROFILE_EMAIL = QueueConcurrencyProfile(
    name="email",
    max_jobs=15,
    description="Moderate I/O email delivery, often rate-limited by the provider.",
    job_timeout_seconds=120,
)

PROFILE_INTEGRATION_SYNC = QueueConcurrencyProfile(
    name="integration-sync",
    max_jobs=10,
    description="Mixed I/O workloads with external API rate limits.",
    job_timeout_seconds=300,
)

PROFILE_REPORTS = QueueConcurrencyProfile(
    name="reports",
    max_jobs=3,
    description="CPU/memory-intensive report generation; protect worker stability.",
    job_timeout_seconds=600,
)

PROFILE_SCHEDULED = QueueConcurrencyProfile(
    name="scheduled",
    max_jobs=5,
    description="Low-volume scheduled/cron jobs; avoid starving other queues.",
    job_timeout_seconds=300,
)

# Convenience collection for iteration and documentation.
ALL_PROFILES: tuple[QueueConcurrencyProfile, ...] = (
    PROFILE_DEFAULT,
    PROFILE_WEBHOOK_INGEST,
    PROFILE_EMAIL,
    PROFILE_INTEGRATION_SYNC,
    PROFILE_REPORTS,
    PROFILE_SCHEDULED,
)

__all__ = [
    "ALL_PROFILES",
    "PROFILE_DEFAULT",
    "PROFILE_EMAIL",
    "PROFILE_INTEGRATION_SYNC",
    "PROFILE_REPORTS",
    "PROFILE_SCHEDULED",
    "PROFILE_WEBHOOK_INGEST",
    "QueueConcurrencyProfile",
]
