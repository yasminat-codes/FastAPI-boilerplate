"""Retention policy helpers for webhook payload storage and event cleanup.

This module provides reusable retention contracts so the template can age out
raw payloads, prune old event records, and keep the ``webhook_event`` table
from growing unbounded in production deployments.

The retention primitives consume the ``WEBHOOK_PAYLOAD_RETENTION_DAYS`` and
``WEBHOOK_STORE_RAW_PAYLOADS`` settings from the template configuration layer.
Cloned projects can tune these settings per environment without modifying the
cleanup logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import SettingsProfile, settings
from ..platform.database import WebhookEvent, WebhookEventStatus


@dataclass(slots=True, frozen=True)
class WebhookRetentionPolicy:
    """Retention rules for webhook event payload data.

    * ``retention_days`` — number of days to keep raw payload text.  After this
      window, ``scrub_expired_payloads`` nulls out the ``raw_payload`` column
      while preserving the rest of the event record.
    * ``archive_days`` — number of days after which fully processed events can
      be hard-deleted.  Events in terminal states older than this are eligible
      for ``purge_archived_events``.
    * ``scrub_statuses`` — only events in these terminal statuses are eligible
      for payload scrubbing.  Events still being processed are never scrubbed.
    """

    retention_days: int
    archive_days: int = 90
    scrub_statuses: tuple[str, ...] = (
        WebhookEventStatus.PROCESSED.value,
        WebhookEventStatus.FAILED.value,
        WebhookEventStatus.REJECTED.value,
    )
    batch_size: int = 500

    def __post_init__(self) -> None:
        if self.retention_days < 0:
            raise ValueError("Retention days cannot be negative")
        if self.archive_days < self.retention_days:
            raise ValueError("Archive days must be greater than or equal to retention days")
        if self.batch_size < 1:
            raise ValueError("Batch size must be at least 1")


@dataclass(slots=True, frozen=True)
class WebhookRetentionResult:
    """Outcome of a webhook retention cleanup run."""

    payloads_scrubbed: int = 0
    events_purged: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    def as_summary(self) -> dict[str, Any]:
        """Render a human-readable summary of the cleanup run."""
        return {
            "payloads_scrubbed": self.payloads_scrubbed,
            "events_purged": self.events_purged,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


def build_retention_policy(
    runtime_settings: SettingsProfile | None = None,
) -> WebhookRetentionPolicy:
    """Build a retention policy from the template configuration layer."""
    configured_settings = settings if runtime_settings is None else runtime_settings
    return WebhookRetentionPolicy(
        retention_days=configured_settings.WEBHOOK_PAYLOAD_RETENTION_DAYS,
    )


class WebhookRetentionService:
    """Run retention cleanup operations against the webhook event table."""

    async def scrub_expired_payloads(
        self,
        session: AsyncSession,
        policy: WebhookRetentionPolicy,
    ) -> int:
        """Null out raw_payload on events older than the retention window.

        Returns the number of rows updated.  The normalized_payload, metadata,
        and event record itself are preserved for operational reference.
        """
        if policy.retention_days <= 0:
            return 0

        cutoff = datetime.now(UTC) - timedelta(days=policy.retention_days)
        stmt = (
            update(WebhookEvent)
            .where(
                WebhookEvent.received_at < cutoff,
                WebhookEvent.raw_payload.isnot(None),
                WebhookEvent.status.in_(policy.scrub_statuses),
            )
            .values(raw_payload=None)
        )
        result = await session.execute(stmt)
        return result.rowcount  # type: ignore[return-value]

    async def count_expired_payloads(
        self,
        session: AsyncSession,
        policy: WebhookRetentionPolicy,
    ) -> int:
        """Count events eligible for payload scrubbing without modifying data."""
        from sqlalchemy import func

        if policy.retention_days <= 0:
            return 0

        cutoff = datetime.now(UTC) - timedelta(days=policy.retention_days)
        stmt = select(func.count()).select_from(WebhookEvent).where(
            WebhookEvent.received_at < cutoff,
            WebhookEvent.raw_payload.isnot(None),
            WebhookEvent.status.in_(policy.scrub_statuses),
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def purge_archived_events(
        self,
        session: AsyncSession,
        policy: WebhookRetentionPolicy,
    ) -> int:
        """Hard-delete event records older than the archive window.

        Only events in terminal statuses are eligible.  Returns the number of
        rows deleted.

        .. warning::
            This is a destructive operation.  Run ``count_purgeable_events``
            first in production to preview the impact.
        """
        from sqlalchemy import delete

        cutoff = datetime.now(UTC) - timedelta(days=policy.archive_days)
        stmt = (
            delete(WebhookEvent)
            .where(
                WebhookEvent.received_at < cutoff,
                WebhookEvent.status.in_(policy.scrub_statuses),
            )
        )
        result = await session.execute(stmt)
        return result.rowcount  # type: ignore[return-value]

    async def count_purgeable_events(
        self,
        session: AsyncSession,
        policy: WebhookRetentionPolicy,
    ) -> int:
        """Count events eligible for hard-delete without modifying data."""
        from sqlalchemy import func

        cutoff = datetime.now(UTC) - timedelta(days=policy.archive_days)
        stmt = select(func.count()).select_from(WebhookEvent).where(
            WebhookEvent.received_at < cutoff,
            WebhookEvent.status.in_(policy.scrub_statuses),
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def run_full_cleanup(
        self,
        session: AsyncSession,
        policy: WebhookRetentionPolicy | None = None,
    ) -> WebhookRetentionResult:
        """Run both payload scrubbing and event purging in one pass."""
        resolved_policy = build_retention_policy() if policy is None else policy
        started_at = datetime.now(UTC)

        payloads_scrubbed = await self.scrub_expired_payloads(session, resolved_policy)
        events_purged = await self.purge_archived_events(session, resolved_policy)

        return WebhookRetentionResult(
            payloads_scrubbed=payloads_scrubbed,
            events_purged=events_purged,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )


webhook_retention_service = WebhookRetentionService()


__all__ = [
    "WebhookRetentionPolicy",
    "WebhookRetentionResult",
    "WebhookRetentionService",
    "build_retention_policy",
    "webhook_retention_service",
]
