"""Dead-letter behavior for repeatedly failing webhook events.

This module provides reusable helpers for moving failed webhook events into
the shared ``dead_letter_record`` ledger and for triaging dead-lettered
events for retry or archival.  The primitives are template-owned and
provider-agnostic so cloned projects get consistent dead-letter behavior
without building ad hoc failure sinks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..platform.database import DeadLetterRecord, DeadLetterRecordStatus

if TYPE_CHECKING:
    from ..platform.database import WebhookEvent
    from .processing import WebhookProcessingOutcome


WEBHOOK_DEAD_LETTER_NAMESPACE = "webhooks"


@dataclass(slots=True, frozen=True)
class WebhookDeadLetterRequest:
    """Typed input for dead-lettering a failed webhook event."""

    webhook_event_id: int
    source: str
    endpoint_key: str
    event_type: str
    failure_category: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    correlation_id: str | None = None
    attempt_count: int = 0
    payload_snapshot: dict[str, Any] | None = None
    failure_context: dict[str, Any] | None = None

    @property
    def dead_letter_key(self) -> str:
        """Scoped unique key for dead-letter deduplication."""
        return f"{self.source}:{self.endpoint_key}:{self.webhook_event_id}"

    @property
    def message_type(self) -> str:
        return f"webhook.{self.source}.{self.event_type}"


@dataclass(slots=True, frozen=True)
class WebhookDeadLetterResult:
    """Outcome of a webhook dead-letter operation."""

    dead_letter_record_id: int
    webhook_event_id: int
    dead_letter_key: str
    dead_lettered_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_processing_metadata(self) -> dict[str, Any]:
        """Render dead-letter details for webhook event processing metadata."""
        return {
            "dead_letter": {
                "record_id": self.dead_letter_record_id,
                "key": self.dead_letter_key,
                "dead_lettered_at": self.dead_lettered_at.isoformat(),
            }
        }


def build_dead_letter_request_from_outcome(
    event: WebhookEvent,
    outcome: WebhookProcessingOutcome,
    *,
    correlation_id: str | None = None,
) -> WebhookDeadLetterRequest:
    """Build a dead-letter request from a webhook event and processing outcome."""
    payload_snapshot: dict[str, Any] = {
        "event_type": event.event_type,
        "source": event.source,
        "endpoint_key": event.endpoint_key,
    }
    if event.normalized_payload is not None:
        payload_snapshot["normalized_payload"] = dict(event.normalized_payload)
    if event.payload_sha256 is not None:
        payload_snapshot["payload_sha256"] = event.payload_sha256

    failure_context: dict[str, Any] = {}
    if outcome.processing_metadata:
        failure_context.update(outcome.processing_metadata)
    failure_context["final_status"] = outcome.status.value
    failure_context["attempt_number"] = outcome.attempt.attempt_number
    failure_context["max_attempts"] = outcome.attempt.max_attempts

    return WebhookDeadLetterRequest(
        webhook_event_id=event.id,
        source=event.source,
        endpoint_key=event.endpoint_key,
        event_type=event.event_type,
        failure_category=outcome.error_category,
        error_code=outcome.error_category,
        error_detail=outcome.error_message,
        correlation_id=correlation_id,
        attempt_count=outcome.attempt.attempt_number,
        payload_snapshot=payload_snapshot,
        failure_context=failure_context,
    )


class WebhookDeadLetterStore:
    """Persist webhook events into the shared dead-letter ledger."""

    async def dead_letter(
        self,
        session: AsyncSession,
        request: WebhookDeadLetterRequest,
    ) -> WebhookDeadLetterResult:
        """Create a dead-letter record for a failed webhook event."""
        now = datetime.now(UTC)
        record = DeadLetterRecord(
            dead_letter_namespace=WEBHOOK_DEAD_LETTER_NAMESPACE,
            dead_letter_key=request.dead_letter_key,
            message_type=request.message_type,
            status=DeadLetterRecordStatus.DEAD_LETTERED.value,
            source_system=request.source,
            source_reference=str(request.webhook_event_id),
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
        return WebhookDeadLetterResult(
            dead_letter_record_id=record.id,
            webhook_event_id=request.webhook_event_id,
            dead_letter_key=request.dead_letter_key,
            dead_lettered_at=now,
        )

    async def mark_resolved(
        self,
        session: AsyncSession,
        record: DeadLetterRecord,
    ) -> DeadLetterRecord:
        """Mark a dead-letter record as resolved after manual triage or replay."""
        record.status = DeadLetterRecordStatus.RESOLVED.value
        record.resolved_at = datetime.now(UTC)
        await session.flush()
        return record

    async def mark_archived(
        self,
        session: AsyncSession,
        record: DeadLetterRecord,
    ) -> DeadLetterRecord:
        """Archive a dead-letter record that does not need further attention."""
        record.status = DeadLetterRecordStatus.ARCHIVED.value
        record.archived_at = datetime.now(UTC)
        await session.flush()
        return record


webhook_dead_letter_store = WebhookDeadLetterStore()


__all__ = [
    "WEBHOOK_DEAD_LETTER_NAMESPACE",
    "WebhookDeadLetterRequest",
    "WebhookDeadLetterResult",
    "WebhookDeadLetterStore",
    "build_dead_letter_request_from_outcome",
    "webhook_dead_letter_store",
]
