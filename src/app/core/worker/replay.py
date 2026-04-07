"""Manual replay tooling for dead-lettered background jobs.

This module provides functionality to replay jobs that have been dead-lettered
due to processing failures. It extracts job information from dead letter records
and re-enqueues them with optional configuration overrides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from arq.connections import ArqRedis

from ...platform.database import DeadLetterRecord

__all__ = [
    "ReplayRequest",
    "ReplayResult",
    "build_replay_request_from_dead_letter",
    "replay_dead_lettered_job",
]


@dataclass(frozen=True, slots=True)
class ReplayRequest:
    """Request to replay a dead-lettered background job.

    Attributes:
        dead_letter_record_id: The ID of the dead letter record being replayed.
        job_name: The name of the job to enqueue.
        payload: The job payload to send to the worker.
        correlation_id: Optional correlation ID for tracing related operations.
        tenant_id: Optional tenant ID for multi-tenant job routing.
        organization_id: Optional organization ID for multi-tenant job routing.
        metadata: Optional additional metadata to include with the job.
        override_queue: Optional queue name to override the job's default queue.
    """

    dead_letter_record_id: int
    job_name: str
    payload: dict[str, Any]
    correlation_id: str | None = None
    tenant_id: str | None = None
    organization_id: str | None = None
    metadata: dict[str, Any] | None = None
    override_queue: str | None = None


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Result of attempting to replay a dead-lettered job.

    Attributes:
        dead_letter_record_id: The ID of the dead letter record that was replayed.
        job_name: The name of the job that was replayed.
        replayed_at: Timestamp when the replay was attempted.
        enqueued: Whether the job was successfully enqueued.
        error_message: Error message if the replay failed, None if successful.
    """

    dead_letter_record_id: int
    job_name: str
    replayed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    enqueued: bool = False
    error_message: str | None = None


def build_replay_request_from_dead_letter(
    record: DeadLetterRecord,
) -> ReplayRequest:
    """Extract and build a ReplayRequest from a dead letter record.

    Extracts the job name from the message type (removing "job." prefix),
    payload from the envelope, and other contextual information from the
    payload snapshot.

    Args:
        record: The dead letter record to extract replay information from.

    Returns:
        A ReplayRequest populated with data from the dead letter record.
    """
    # Extract job name by removing "job." prefix from message_type
    job_name = record.message_type
    if job_name.startswith("job."):
        job_name = job_name[4:]

    # Extract payload from the envelope in the snapshot
    payload_snapshot = record.payload_snapshot or {}
    payload = payload_snapshot.get("envelope", {}).get("payload", {})

    # Extract optional fields from the snapshot
    correlation_id = record.correlation_id
    tenant_id = payload_snapshot.get("tenant_id")
    organization_id = payload_snapshot.get("organization_id")
    metadata = payload_snapshot.get("metadata")

    return ReplayRequest(
        dead_letter_record_id=record.id,
        job_name=job_name,
        payload=payload,
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        organization_id=organization_id,
        metadata=metadata,
    )


async def replay_dead_lettered_job(
    pool: ArqRedis,
    request: ReplayRequest,
) -> ReplayResult:
    """Replay a dead-lettered job by re-enqueueing it.

    Enqueues the job specified in the request using the provided Redis connection.
    On success, returns a ReplayResult with enqueued=True. On failure, returns a
    ReplayResult with enqueued=False and an error message.

    Note: This function does not mark the dead letter record as resolved. The caller
    is responsible for confirming success and updating the dead letter record status.

    Args:
        pool: The ArqRedis connection to use for enqueueing.
        request: The replay request containing job details.

    Returns:
        A ReplayResult indicating success or failure of the replay attempt.
    """
    try:
        # Build the job kwargs from request fields
        job_kwargs: dict[str, Any] = {"payload": request.payload}

        # Add optional context fields if provided
        if request.correlation_id is not None:
            job_kwargs["correlation_id"] = request.correlation_id
        if request.tenant_id is not None:
            job_kwargs["tenant_id"] = request.tenant_id
        if request.organization_id is not None:
            job_kwargs["organization_id"] = request.organization_id
        if request.metadata is not None:
            job_kwargs["metadata"] = request.metadata

        # Enqueue the job with optional queue override
        await pool.enqueue_job(
            request.job_name,
            **job_kwargs,
            _queue_name=request.override_queue,
        )

        return ReplayResult(
            dead_letter_record_id=request.dead_letter_record_id,
            job_name=request.job_name,
            enqueued=True,
        )

    except Exception as exc:
        error_message = f"{exc.__class__.__name__}: {str(exc)}"
        return ReplayResult(
            dead_letter_record_id=request.dead_letter_record_id,
            job_name=request.job_name,
            enqueued=False,
            error_message=error_message,
        )
