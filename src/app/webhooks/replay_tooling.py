"""Replay tooling for webhook event re-processing in development and operations.

This module provides reusable helpers for replaying previously ingested webhook
events through the processing pipeline.  Operators can replay individual events
by ID or query for events matching source, status, or time-window criteria.

The replay tooling is template-owned and provider-agnostic.  It re-enqueues
events through the same background job path that the original intake used, so
retry-safety and dead-letter contracts stay consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..platform.database import WebhookEvent, WebhookEventStatus


@dataclass(slots=True, frozen=True)
class WebhookReplayFilter:
    """Query filter for selecting webhook events to replay.

    All filter fields are optional.  When multiple fields are set, they are
    combined with AND semantics.  An empty filter matches all events — callers
    should always set at least one constraint.
    """

    source: str | None = None
    endpoint_key: str | None = None
    event_type: str | None = None
    status: str | None = None
    statuses: tuple[str, ...] | None = None
    received_after: datetime | None = None
    received_before: datetime | None = None
    max_results: int = 100

    def __post_init__(self) -> None:
        if self.max_results < 1:
            raise ValueError("Replay filter max_results must be at least 1")
        if self.max_results > 1000:
            raise ValueError("Replay filter max_results must not exceed 1000")


@dataclass(slots=True, frozen=True)
class WebhookReplayRequest:
    """Typed request to replay a single webhook event."""

    webhook_event_id: int
    reason: str = "manual_replay"
    replayed_by: str | None = None
    replayed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_processing_metadata(self) -> dict[str, Any]:
        """Render replay details for the webhook event's processing metadata."""
        metadata: dict[str, Any] = {
            "reason": self.reason,
            "replayed_at": self.replayed_at.isoformat(),
        }
        if self.replayed_by is not None:
            metadata["replayed_by"] = self.replayed_by
        return {"replay": metadata}


@dataclass(slots=True, frozen=True)
class WebhookReplayResult:
    """Outcome of a webhook replay operation."""

    webhook_event_id: int
    previous_status: str
    new_status: str
    replayed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reason: str = "manual_replay"

    @property
    def was_replayed(self) -> bool:
        return self.new_status == WebhookEventStatus.ENQUEUED.value


class WebhookReplayService:
    """Service for replaying webhook events through the processing pipeline."""

    async def find_replayable_events(
        self,
        session: AsyncSession,
        replay_filter: WebhookReplayFilter,
    ) -> list[WebhookEvent]:
        """Query for webhook events matching the replay filter."""
        stmt = select(WebhookEvent).order_by(
            WebhookEvent.received_at.desc(),
            WebhookEvent.id.desc(),
        )

        if replay_filter.source is not None:
            stmt = stmt.where(WebhookEvent.source == replay_filter.source)
        if replay_filter.endpoint_key is not None:
            stmt = stmt.where(WebhookEvent.endpoint_key == replay_filter.endpoint_key)
        if replay_filter.event_type is not None:
            stmt = stmt.where(WebhookEvent.event_type == replay_filter.event_type)
        if replay_filter.status is not None:
            stmt = stmt.where(WebhookEvent.status == replay_filter.status)
        if replay_filter.statuses is not None:
            stmt = stmt.where(WebhookEvent.status.in_(replay_filter.statuses))
        if replay_filter.received_after is not None:
            stmt = stmt.where(WebhookEvent.received_at >= replay_filter.received_after)
        if replay_filter.received_before is not None:
            stmt = stmt.where(WebhookEvent.received_at <= replay_filter.received_before)

        stmt = stmt.limit(replay_filter.max_results)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    def prepare_for_replay(
        self,
        event: WebhookEvent,
        request: WebhookReplayRequest,
    ) -> WebhookReplayResult:
        """Mark a webhook event as ready for replay by resetting its status.

        This updates the event's status to ``enqueued`` and appends replay
        metadata.  The caller is responsible for actually enqueuing the
        processing job after calling this method.
        """
        previous_status = event.status
        event.status = WebhookEventStatus.ENQUEUED.value
        event.processed_at = None
        event.processing_error = None

        existing_metadata: dict[str, Any] = dict(event.processing_metadata or {})
        existing_metadata.update(request.as_processing_metadata())
        event.processing_metadata = existing_metadata

        return WebhookReplayResult(
            webhook_event_id=event.id,
            previous_status=previous_status,
            new_status=WebhookEventStatus.ENQUEUED.value,
            replayed_at=request.replayed_at,
            reason=request.reason,
        )

    async def find_failed_events(
        self,
        session: AsyncSession,
        *,
        source: str | None = None,
        hours: int = 24,
        max_results: int = 100,
    ) -> list[WebhookEvent]:
        """Convenience query for failed webhook events in a recent time window."""
        return await self.find_replayable_events(
            session,
            WebhookReplayFilter(
                source=source,
                status=WebhookEventStatus.FAILED.value,
                received_after=datetime.now(UTC) - timedelta(hours=hours),
                max_results=max_results,
            ),
        )


webhook_replay_service = WebhookReplayService()


__all__ = [
    "WebhookReplayFilter",
    "WebhookReplayRequest",
    "WebhookReplayResult",
    "WebhookReplayService",
    "webhook_replay_service",
]
