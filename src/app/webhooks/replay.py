"""Replay-protection primitives for canonical webhook ingestion flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..platform.database import WebhookEvent
from .ingestion import WebhookIngestionRequest, WebhookValidatedEvent


class WebhookReplayKeyKind(StrEnum):
    """Supported identifiers for replay-protection lookups."""

    DELIVERY_ID = "delivery_id"
    EVENT_ID = "event_id"
    PAYLOAD_SHA256 = "payload_sha256"


@dataclass(slots=True, frozen=True)
class WebhookReplayProtectionRequest:
    """Canonical replay-protection input derived from a validated webhook delivery."""

    source: str
    endpoint_key: str
    webhook_request: WebhookIngestionRequest
    validated_event: WebhookValidatedEvent
    replay_window_seconds: int
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("Webhook replay protection source must not be empty")
        if not self.endpoint_key.strip():
            raise ValueError("Webhook replay protection endpoint_key must not be empty")
        if self.replay_window_seconds < 1:
            raise ValueError("Webhook replay window must be at least 1 second")

    @property
    def delivery_id(self) -> str | None:
        return self.validated_event.delivery_id

    @property
    def event_id(self) -> str | None:
        return self.validated_event.event_id

    @property
    def event_type(self) -> str:
        return self.validated_event.event_type

    @property
    def payload_sha256(self) -> str:
        return sha256(self.webhook_request.raw_body).hexdigest()

    @property
    def replay_window_started_at(self) -> datetime:
        return self.checked_at - timedelta(seconds=self.replay_window_seconds)

    @property
    def primary_key_kind(self) -> WebhookReplayKeyKind:
        if self.delivery_id is not None:
            return WebhookReplayKeyKind.DELIVERY_ID
        if self.event_id is not None:
            return WebhookReplayKeyKind.EVENT_ID
        return WebhookReplayKeyKind.PAYLOAD_SHA256

    @property
    def primary_key_value(self) -> str:
        if self.primary_key_kind is WebhookReplayKeyKind.DELIVERY_ID:
            return self.delivery_id or self.payload_sha256
        if self.primary_key_kind is WebhookReplayKeyKind.EVENT_ID:
            return self.event_id or self.payload_sha256
        return self.payload_sha256


@dataclass(slots=True, frozen=True)
class WebhookReplayProtectionResult:
    """Metadata recorded when a webhook clears replay checks."""

    source: str
    endpoint_key: str
    event_type: str
    key_kind: WebhookReplayKeyKind
    key_value: str
    payload_sha256: str
    replay_window_seconds: int
    checked_at: datetime
    delivery_id: str | None = None
    event_id: str | None = None

    def as_processing_metadata(self) -> dict[str, object]:
        """Render replay-protection details into webhook processing metadata."""

        replay_metadata: dict[str, object] = {
            "checked_at": self.checked_at.isoformat(),
            "key_kind": self.key_kind.value,
            "key_value": self.key_value,
            "payload_sha256": self.payload_sha256,
            "window_seconds": self.replay_window_seconds,
        }
        if self.delivery_id is not None:
            replay_metadata["delivery_id"] = self.delivery_id
        if self.event_id is not None:
            replay_metadata["event_id"] = self.event_id

        return {"replay_protection": replay_metadata}


@dataclass(slots=True, frozen=True)
class WebhookReplayMatch:
    """Snapshot of an existing webhook delivery that matched replay checks."""

    source: str
    endpoint_key: str
    matched_on: tuple[WebhookReplayKeyKind, ...]
    existing_event_id: int
    existing_status: str
    existing_received_at: datetime
    existing_payload_sha256: str | None
    candidate_payload_sha256: str
    delivery_id: str | None = None
    event_id: str | None = None


class WebhookReplayProtectionError(ValueError):
    """Base error raised when a webhook fails replay-protection checks."""


class WebhookReplayDetectedError(WebhookReplayProtectionError):
    """Raised when an inbound webhook matches a recent stored delivery."""

    def __init__(self, match: WebhookReplayMatch) -> None:
        self.match = match
        matched_on = ", ".join(kind.value for kind in match.matched_on)
        super().__init__(
            f"Webhook replay detected for {match.source}/{match.endpoint_key} on {matched_on}"
        )


class WebhookReplayFingerprintMismatchError(WebhookReplayProtectionError):
    """Raised when a stable webhook identifier is replayed with a different payload hash."""

    def __init__(self, match: WebhookReplayMatch) -> None:
        self.match = match
        matched_on = ", ".join(kind.value for kind in match.matched_on)
        super().__init__(
            "Webhook replay identifier matched an existing event with a different payload fingerprint "
            f"for {match.source}/{match.endpoint_key} on {matched_on}"
        )


class WebhookReplayProtector:
    """Check recent webhook deliveries for replayed or conflicting identifiers."""

    async def protect(
        self,
        session: AsyncSession,
        payload: WebhookReplayProtectionRequest,
    ) -> WebhookReplayProtectionResult:
        """Ensure the delivery is not a replay inside the configured replay window."""

        existing_event = await self._find_existing_event(session, payload)
        if existing_event is not None:
            match = self._build_match(payload, existing_event)
            if self._is_fingerprint_mismatch(match):
                raise WebhookReplayFingerprintMismatchError(match)
            raise WebhookReplayDetectedError(match)

        return WebhookReplayProtectionResult(
            source=payload.source,
            endpoint_key=payload.endpoint_key,
            event_type=payload.event_type,
            key_kind=payload.primary_key_kind,
            key_value=payload.primary_key_value,
            payload_sha256=payload.payload_sha256,
            replay_window_seconds=payload.replay_window_seconds,
            checked_at=payload.checked_at,
            delivery_id=payload.delivery_id,
            event_id=payload.event_id,
        )

    async def _find_existing_event(
        self,
        session: AsyncSession,
        payload: WebhookReplayProtectionRequest,
    ) -> WebhookEvent | None:
        base_statement = (
            select(WebhookEvent)
            .where(
                WebhookEvent.source == payload.source,
                WebhookEvent.endpoint_key == payload.endpoint_key,
                WebhookEvent.received_at >= payload.replay_window_started_at,
            )
            .order_by(WebhookEvent.received_at.desc(), WebhookEvent.id.desc())
            .limit(1)
        )

        identifier_filters = []
        if payload.delivery_id is not None:
            identifier_filters.append(WebhookEvent.delivery_id == payload.delivery_id)
        if payload.event_id is not None:
            identifier_filters.append(WebhookEvent.event_id == payload.event_id)

        if identifier_filters:
            return cast(
                WebhookEvent | None,
                await session.scalar(base_statement.where(or_(*identifier_filters))),
            )

        return cast(
            WebhookEvent | None,
            await session.scalar(
                base_statement.where(
                    WebhookEvent.event_type == payload.event_type,
                    WebhookEvent.payload_sha256 == payload.payload_sha256,
                )
            ),
        )

    def _build_match(
        self,
        payload: WebhookReplayProtectionRequest,
        existing_event: WebhookEvent,
    ) -> WebhookReplayMatch:
        matched_on = []
        if payload.delivery_id is not None and payload.delivery_id == existing_event.delivery_id:
            matched_on.append(WebhookReplayKeyKind.DELIVERY_ID)
        if payload.event_id is not None and payload.event_id == existing_event.event_id:
            matched_on.append(WebhookReplayKeyKind.EVENT_ID)
        if not matched_on and payload.payload_sha256 == existing_event.payload_sha256:
            matched_on.append(WebhookReplayKeyKind.PAYLOAD_SHA256)

        return WebhookReplayMatch(
            source=payload.source,
            endpoint_key=payload.endpoint_key,
            matched_on=tuple(matched_on) or (payload.primary_key_kind,),
            existing_event_id=existing_event.id,
            existing_status=existing_event.status,
            existing_received_at=existing_event.received_at,
            existing_payload_sha256=existing_event.payload_sha256,
            candidate_payload_sha256=payload.payload_sha256,
            delivery_id=payload.delivery_id,
            event_id=payload.event_id,
        )

    def _is_fingerprint_mismatch(self, match: WebhookReplayMatch) -> bool:
        if WebhookReplayKeyKind.PAYLOAD_SHA256 in match.matched_on:
            return False
        if match.existing_payload_sha256 is None:
            return False
        return match.existing_payload_sha256 != match.candidate_payload_sha256


webhook_replay_protector = WebhookReplayProtector()


__all__ = [
    "WebhookReplayDetectedError",
    "WebhookReplayFingerprintMismatchError",
    "WebhookReplayKeyKind",
    "WebhookReplayMatch",
    "WebhookReplayProtectionError",
    "WebhookReplayProtectionRequest",
    "WebhookReplayProtectionResult",
    "WebhookReplayProtector",
    "webhook_replay_protector",
]
