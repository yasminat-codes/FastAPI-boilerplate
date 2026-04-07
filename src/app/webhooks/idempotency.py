"""Idempotency-protection primitives for canonical webhook ingestion flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..platform.database import IdempotencyKey, IdempotencyKeyStatus
from .ingestion import WebhookIngestionRequest, WebhookValidatedEvent

# re-used by _find_existing_record return type
_IdempotencyKeyOrNone = IdempotencyKey | None


@dataclass(slots=True, frozen=True)
class WebhookIdempotencyRequest:
    """Canonical idempotency-check input derived from a validated webhook delivery."""

    source: str
    endpoint_key: str
    webhook_request: WebhookIngestionRequest
    validated_event: WebhookValidatedEvent
    idempotency_window_seconds: int
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("Webhook idempotency source must not be empty")
        if not self.endpoint_key.strip():
            raise ValueError("Webhook idempotency endpoint_key must not be empty")
        if self.idempotency_window_seconds < 1:
            raise ValueError("Webhook idempotency window must be at least 1 second")

    @property
    def scope(self) -> str:
        """Build a scoped key namespace for this webhook source and endpoint."""
        return f"webhook:{self.source}:{self.endpoint_key}"

    @property
    def idempotency_key(self) -> str:
        """Derive the idempotency key from the strongest available identifier.

        Priority: event_id > delivery_id > payload SHA-256.
        """
        if self.validated_event.event_id is not None:
            return f"event_id:{self.validated_event.event_id}"
        if self.validated_event.delivery_id is not None:
            return f"delivery_id:{self.validated_event.delivery_id}"
        return f"payload_sha256:{self.request_fingerprint}"

    @property
    def request_fingerprint(self) -> str:
        """SHA-256 hex digest of the raw request body."""
        return sha256(self.webhook_request.raw_body).hexdigest()

    @property
    def window_started_at(self) -> datetime:
        return self.checked_at - timedelta(seconds=self.idempotency_window_seconds)


@dataclass(slots=True, frozen=True)
class WebhookIdempotencyResult:
    """Metadata recorded when a webhook clears idempotency checks."""

    scope: str
    idempotency_key: str
    request_fingerprint: str
    idempotency_window_seconds: int
    checked_at: datetime
    event_id: str | None = None
    delivery_id: str | None = None

    def as_processing_metadata(self) -> dict[str, object]:
        """Render idempotency-check details into webhook processing metadata."""

        idempotency_metadata: dict[str, object] = {
            "checked_at": self.checked_at.isoformat(),
            "scope": self.scope,
            "key": self.idempotency_key,
            "request_fingerprint": self.request_fingerprint,
            "window_seconds": self.idempotency_window_seconds,
        }
        if self.event_id is not None:
            idempotency_metadata["event_id"] = self.event_id
        if self.delivery_id is not None:
            idempotency_metadata["delivery_id"] = self.delivery_id

        return {"idempotency": idempotency_metadata}


@dataclass(slots=True, frozen=True)
class WebhookIdempotencyMatch:
    """Snapshot of an existing idempotency record that matched the candidate."""

    scope: str
    idempotency_key: str
    existing_record_id: int
    existing_status: str
    existing_first_seen_at: datetime
    existing_hit_count: int
    request_fingerprint: str | None
    candidate_fingerprint: str


class WebhookIdempotencyError(ValueError):
    """Base error raised when a webhook fails idempotency checks."""


class WebhookIdempotencyViolationError(WebhookIdempotencyError):
    """Raised when an inbound webhook matches an existing idempotency record."""

    def __init__(self, match: WebhookIdempotencyMatch) -> None:
        self.match = match
        super().__init__(
            f"Webhook idempotency violation for scope={match.scope} "
            f"key={match.idempotency_key} "
            f"(existing record {match.existing_record_id}, "
            f"status={match.existing_status}, "
            f"hits={match.existing_hit_count})"
        )


class WebhookIdempotencyFingerprintMismatchError(WebhookIdempotencyError):
    """Raised when an idempotency key is reused with a different request fingerprint."""

    def __init__(self, match: WebhookIdempotencyMatch) -> None:
        self.match = match
        super().__init__(
            f"Webhook idempotency key reused with different fingerprint for "
            f"scope={match.scope} key={match.idempotency_key} "
            f"(existing fingerprint={match.request_fingerprint}, "
            f"candidate fingerprint={match.candidate_fingerprint})"
        )


class WebhookIdempotencyProtector:
    """Check webhook deliveries for idempotency violations using the shared ledger."""

    async def protect(
        self,
        session: AsyncSession,
        payload: WebhookIdempotencyRequest,
    ) -> WebhookIdempotencyResult:
        """Ensure this delivery has not already been accepted within the idempotency window."""

        existing_record = await self._find_existing_record(session, payload)
        if existing_record is not None:
            existing_record.hit_count = (existing_record.hit_count or 1) + 1
            existing_record.last_seen_at = payload.checked_at

            match = self._build_match(payload, existing_record)
            if self._is_fingerprint_mismatch(match):
                raise WebhookIdempotencyFingerprintMismatchError(match)
            raise WebhookIdempotencyViolationError(match)

        return WebhookIdempotencyResult(
            scope=payload.scope,
            idempotency_key=payload.idempotency_key,
            request_fingerprint=payload.request_fingerprint,
            idempotency_window_seconds=payload.idempotency_window_seconds,
            checked_at=payload.checked_at,
            event_id=payload.validated_event.event_id,
            delivery_id=payload.validated_event.delivery_id,
        )

    async def _find_existing_record(
        self,
        session: AsyncSession,
        payload: WebhookIdempotencyRequest,
    ) -> IdempotencyKey | None:
        statement = (
            select(IdempotencyKey)
            .where(
                IdempotencyKey.scope == payload.scope,
                IdempotencyKey.key == payload.idempotency_key,
                IdempotencyKey.first_seen_at >= payload.window_started_at,
            )
            .order_by(IdempotencyKey.first_seen_at.desc())
            .limit(1)
        )
        result: _IdempotencyKeyOrNone = await session.scalar(statement)
        return result

    def _build_match(
        self,
        payload: WebhookIdempotencyRequest,
        existing_record: IdempotencyKey,
    ) -> WebhookIdempotencyMatch:
        return WebhookIdempotencyMatch(
            scope=payload.scope,
            idempotency_key=payload.idempotency_key,
            existing_record_id=existing_record.id,
            existing_status=existing_record.status,
            existing_first_seen_at=existing_record.first_seen_at,
            existing_hit_count=existing_record.hit_count,
            request_fingerprint=existing_record.request_fingerprint,
            candidate_fingerprint=payload.request_fingerprint,
        )

    def _is_fingerprint_mismatch(self, match: WebhookIdempotencyMatch) -> bool:
        if match.request_fingerprint is None:
            return False
        return match.request_fingerprint != match.candidate_fingerprint


webhook_idempotency_protector = WebhookIdempotencyProtector()


async def record_idempotency_key(
    session: AsyncSession,
    payload: WebhookIdempotencyRequest,
    *,
    processing_metadata: dict[str, Any] | None = None,
) -> IdempotencyKey:
    """Persist a new idempotency record after a webhook clears idempotency checks.

    Call this after the webhook is persisted and acknowledged so the next
    delivery of the same event within the idempotency window is detected.
    """

    record = IdempotencyKey(
        scope=payload.scope,
        key=payload.idempotency_key,
        status=IdempotencyKeyStatus.PROCESSING.value,
        request_fingerprint=payload.request_fingerprint,
        first_seen_at=payload.checked_at,
        last_seen_at=payload.checked_at,
        hit_count=1,
        expires_at=payload.checked_at + timedelta(seconds=payload.idempotency_window_seconds),
        processing_metadata=processing_metadata,
    )
    session.add(record)
    await session.flush()
    return record


__all__ = [
    "WebhookIdempotencyError",
    "WebhookIdempotencyFingerprintMismatchError",
    "WebhookIdempotencyMatch",
    "WebhookIdempotencyProtector",
    "WebhookIdempotencyRequest",
    "WebhookIdempotencyResult",
    "WebhookIdempotencyViolationError",
    "record_idempotency_key",
    "webhook_idempotency_protector",
]
