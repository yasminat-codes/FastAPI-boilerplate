"""Dead-letter behavior for repeatedly failing background worker jobs.

This module provides reusable helpers for moving failed jobs into the shared
``dead_letter_record`` ledger and for triaging dead-lettered jobs for retry or
archival. The primitives are template-owned and job-queue-agnostic so cloned
projects get consistent dead-letter behavior without building ad hoc failure
sinks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...platform.database import DeadLetterRecord, DeadLetterRecordStatus

JOB_DEAD_LETTER_NAMESPACE = "jobs"


@dataclass(slots=True, frozen=True)
class JobDeadLetterRequest:
    """Typed input for dead-lettering a failed job."""

    job_name: str
    queue_name: str
    correlation_id: str | None = None
    failure_category: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    attempt_count: int = 0
    max_attempts: int = 0
    payload_snapshot: dict[str, Any] | None = None
    failure_context: dict[str, Any] | None = None

    @property
    def dead_letter_key(self) -> str:
        """Scoped unique key for dead-letter deduplication."""
        return f"{self.job_name}:{self.correlation_id or 'no-correlation'}:{self.attempt_count}"

    @property
    def message_type(self) -> str:
        """Message type identifier for the job."""
        return f"job.{self.job_name}"


@dataclass(slots=True, frozen=True)
class JobDeadLetterResult:
    """Outcome of a job dead-letter operation."""

    dead_letter_record_id: int
    job_name: str
    dead_letter_key: str
    dead_lettered_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def build_dead_letter_request_from_job(
    job_name: str,
    queue_name: str,
    envelope: dict[str, Any] | None,
    error: Exception,
    attempt: int,
    max_attempts: int,
    error_category: str | None = None,
) -> JobDeadLetterRequest:
    """Build a dead-letter request from job context and failure information.

    Args:
        job_name: The name of the job that failed.
        queue_name: The queue the job was processed from.
        envelope: The job envelope/payload (if available).
        error: The exception that caused the failure.
        attempt: The current attempt number.
        max_attempts: The maximum number of attempts allowed.
        error_category: Optional categorization of the error (e.g., 'timeout', 'validation').

    Returns:
        A JobDeadLetterRequest ready for persistence.
    """
    payload_snapshot: dict[str, Any] = {
        "job_name": job_name,
        "queue_name": queue_name,
    }
    if envelope is not None:
        payload_snapshot["envelope"] = dict(envelope)

    correlation_id: str | None = None
    if envelope is not None and isinstance(envelope, dict):
        correlation_id = envelope.get("correlation_id")

    failure_context: dict[str, Any] = {
        "error_type": type(error).__name__,
        "attempt_number": attempt,
        "max_attempts": max_attempts,
    }

    error_code: str | None = None
    if hasattr(error, "code"):
        error_code = str(error.code)

    return JobDeadLetterRequest(
        job_name=job_name,
        queue_name=queue_name,
        correlation_id=correlation_id,
        failure_category=error_category,
        error_code=error_code,
        error_detail=str(error),
        attempt_count=attempt,
        max_attempts=max_attempts,
        payload_snapshot=payload_snapshot,
        failure_context=failure_context,
    )


class JobDeadLetterStore:
    """Persist worker jobs into the shared dead-letter ledger."""

    async def dead_letter(
        self,
        session: AsyncSession,
        request: JobDeadLetterRequest,
    ) -> JobDeadLetterResult:
        """Create a dead-letter record for a failed job.

        Args:
            session: The database session.
            request: The job dead-letter request.

        Returns:
            The result containing the record ID and dead-letter details.
        """
        now = datetime.now(UTC)
        record = DeadLetterRecord(
            dead_letter_namespace=JOB_DEAD_LETTER_NAMESPACE,
            dead_letter_key=request.dead_letter_key,
            message_type=request.message_type,
            status=DeadLetterRecordStatus.DEAD_LETTERED.value,
            source_system=request.queue_name,
            source_reference=request.job_name,
            correlation_id=request.correlation_id,
            failure_category=request.failure_category,
            attempt_count=request.attempt_count,
            first_seen_at=now,
            last_seen_at=now,
            dead_lettered_at=now,
            payload_snapshot=request.payload_snapshot,
            failure_context=request.failure_context,
            error_code=request.error_code,
            error_detail=request.error_detail,
        )
        session.add(record)
        await session.flush()
        return JobDeadLetterResult(
            dead_letter_record_id=record.id,
            job_name=request.job_name,
            dead_letter_key=request.dead_letter_key,
            dead_lettered_at=now,
        )

    async def mark_retrying(
        self,
        session: AsyncSession,
        record: DeadLetterRecord,
        *,
        next_retry_at: datetime | None = None,
    ) -> DeadLetterRecord:
        """Mark a dead-letter record as retrying after manual triage.

        Args:
            session: The database session.
            record: The dead-letter record to update.
            next_retry_at: Optional timestamp for when the next retry is scheduled.

        Returns:
            The updated dead-letter record.
        """
        record.status = DeadLetterRecordStatus.RETRYING.value
        record.last_seen_at = datetime.now(UTC)
        if next_retry_at is not None:
            record.next_retry_at = next_retry_at
        await session.flush()
        return record

    async def mark_resolved(
        self,
        session: AsyncSession,
        record: DeadLetterRecord,
    ) -> DeadLetterRecord:
        """Mark a dead-letter record as resolved after manual triage or replay.

        Args:
            session: The database session.
            record: The dead-letter record to update.

        Returns:
            The updated dead-letter record.
        """
        record.status = DeadLetterRecordStatus.RESOLVED.value
        record.resolved_at = datetime.now(UTC)
        await session.flush()
        return record

    async def mark_archived(
        self,
        session: AsyncSession,
        record: DeadLetterRecord,
    ) -> DeadLetterRecord:
        """Archive a dead-letter record that does not need further attention.

        Args:
            session: The database session.
            record: The dead-letter record to update.

        Returns:
            The updated dead-letter record.
        """
        record.status = DeadLetterRecordStatus.ARCHIVED.value
        record.archived_at = datetime.now(UTC)
        await session.flush()
        return record


job_dead_letter_store = JobDeadLetterStore()


__all__ = [
    "JOB_DEAD_LETTER_NAMESPACE",
    "JobDeadLetterRequest",
    "JobDeadLetterResult",
    "JobDeadLetterStore",
    "build_dead_letter_request_from_job",
    "job_dead_letter_store",
]
