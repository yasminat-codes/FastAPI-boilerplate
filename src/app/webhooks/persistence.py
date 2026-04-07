"""Reusable webhook event persistence helpers backed by the platform inbox ledger."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..platform.database import WebhookEvent, WebhookEventStatus
from .ingestion import WebhookIngestionRequest
from .signatures import WebhookSignatureVerificationResult

WebhookEventStatusLike = WebhookEventStatus | str


@dataclass(slots=True, frozen=True)
class WebhookEventPersistenceRequest:
    """Canonical input contract for persisting an inbound webhook delivery."""

    source: str
    endpoint_key: str
    event_type: str
    webhook_request: WebhookIngestionRequest
    delivery_id: str | None = None
    event_id: str | None = None
    normalized_payload: dict[str, Any] | None = None
    processing_metadata: Mapping[str, Any] | None = None
    signature_verification: WebhookSignatureVerificationResult | None = None
    signature_verified: bool | None = None
    status: WebhookEventStatusLike = WebhookEventStatus.RECEIVED
    store_raw_payload: bool = True
    raw_payload_text: str | None = None
    received_at: datetime | None = None


class WebhookEventStore:
    """Persist and mutate shared webhook-event records without provider coupling."""

    async def persist(
        self,
        session: AsyncSession,
        payload: WebhookEventPersistenceRequest,
    ) -> WebhookEvent:
        """Create, add, and flush a webhook-event record within the caller-owned session."""

        event = self.build_event(payload)
        session.add(event)
        await session.flush()
        return event

    def build_event(self, payload: WebhookEventPersistenceRequest) -> WebhookEvent:
        """Build a webhook-event ORM instance from the canonical persistence contract."""

        request = payload.webhook_request
        return WebhookEvent(
            source=payload.source,
            endpoint_key=payload.endpoint_key,
            event_type=payload.event_type,
            status=_coerce_webhook_event_status(payload.status),
            delivery_id=payload.delivery_id,
            event_id=payload.event_id,
            signature_verified=_resolve_signature_verified(payload),
            payload_content_type=request.content_type,
            payload_sha256=sha256(request.raw_body).hexdigest(),
            payload_size_bytes=request.payload_size_bytes,
            received_at=payload.received_at or datetime.now(UTC),
            raw_payload=self._render_raw_payload(payload),
            normalized_payload=_copy_mapping(payload.normalized_payload),
            processing_metadata=self._build_processing_metadata(payload),
        )

    def mark_acknowledged(
        self,
        event: WebhookEvent,
        *,
        acknowledged_at: datetime | None = None,
        processing_metadata: Mapping[str, Any] | None = None,
    ) -> WebhookEvent:
        """Mark a webhook delivery as acknowledged to the upstream provider."""

        return self._set_status(
            event,
            WebhookEventStatus.ACKNOWLEDGED,
            acknowledged_at=acknowledged_at or datetime.now(UTC),
            processing_metadata=processing_metadata,
        )

    def mark_enqueued(
        self,
        event: WebhookEvent,
        *,
        processing_metadata: Mapping[str, Any] | None = None,
    ) -> WebhookEvent:
        """Mark a webhook delivery as handed off to asynchronous processing."""

        return self._set_status(
            event,
            WebhookEventStatus.ENQUEUED,
            processing_metadata=processing_metadata,
        )

    def mark_processed(
        self,
        event: WebhookEvent,
        *,
        processed_at: datetime | None = None,
        normalized_payload: dict[str, Any] | None = None,
        processing_metadata: Mapping[str, Any] | None = None,
    ) -> WebhookEvent:
        """Mark a webhook delivery as fully processed."""

        return self._set_status(
            event,
            WebhookEventStatus.PROCESSED,
            processed_at=processed_at or datetime.now(UTC),
            normalized_payload=normalized_payload,
            processing_metadata=processing_metadata,
        )

    def mark_rejected(
        self,
        event: WebhookEvent,
        *,
        processed_at: datetime | None = None,
        processing_error: str | None = None,
        processing_metadata: Mapping[str, Any] | None = None,
    ) -> WebhookEvent:
        """Mark a webhook delivery as rejected during intake or validation."""

        return self._set_status(
            event,
            WebhookEventStatus.REJECTED,
            processed_at=processed_at or datetime.now(UTC),
            processing_error=processing_error,
            processing_metadata=processing_metadata,
        )

    def mark_failed(
        self,
        event: WebhookEvent,
        *,
        processed_at: datetime | None = None,
        processing_error: str | None = None,
        processing_metadata: Mapping[str, Any] | None = None,
    ) -> WebhookEvent:
        """Mark a webhook delivery as failed after processing started."""

        return self._set_status(
            event,
            WebhookEventStatus.FAILED,
            processed_at=processed_at or datetime.now(UTC),
            processing_error=processing_error,
            processing_metadata=processing_metadata,
        )

    def _render_raw_payload(self, payload: WebhookEventPersistenceRequest) -> str | None:
        if not payload.store_raw_payload:
            return None

        if payload.raw_payload_text is not None:
            return payload.raw_payload_text

        return payload.webhook_request.text(errors="replace")

    def _build_processing_metadata(
        self,
        payload: WebhookEventPersistenceRequest,
    ) -> dict[str, Any] | None:
        metadata = _copy_mapping(payload.processing_metadata)
        signature_metadata = _build_signature_metadata(payload.signature_verification)
        if signature_metadata is None:
            return metadata

        combined_metadata = dict(metadata or {})
        existing_signature = combined_metadata.get("signature")
        combined_signature: dict[str, Any] = {}
        if isinstance(existing_signature, Mapping):
            combined_signature.update(dict(existing_signature))
        combined_signature.update(signature_metadata)
        combined_metadata["signature"] = combined_signature
        return combined_metadata or None

    def _set_status(
        self,
        event: WebhookEvent,
        status: WebhookEventStatusLike,
        *,
        acknowledged_at: datetime | None = None,
        processed_at: datetime | None = None,
        processing_error: str | None = None,
        normalized_payload: dict[str, Any] | None = None,
        processing_metadata: Mapping[str, Any] | None = None,
    ) -> WebhookEvent:
        event.status = _coerce_webhook_event_status(status)
        if acknowledged_at is not None:
            event.acknowledged_at = acknowledged_at
        if processed_at is not None:
            event.processed_at = processed_at
        if processing_error is not None:
            event.processing_error = processing_error
        if normalized_payload is not None:
            event.normalized_payload = dict(normalized_payload)

        merged_metadata = _merge_processing_metadata(event.processing_metadata, processing_metadata)
        if merged_metadata is not None or event.processing_metadata is not None:
            event.processing_metadata = merged_metadata

        return event


def _coerce_webhook_event_status(status: WebhookEventStatusLike) -> str:
    if isinstance(status, WebhookEventStatus):
        return status.value

    normalized_status = status.strip().lower()
    if normalized_status not in {value.value for value in WebhookEventStatus}:
        raise ValueError(f"Unsupported webhook event status: {status}")
    return normalized_status


def _copy_mapping(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return dict(value) or None


def _resolve_signature_verified(payload: WebhookEventPersistenceRequest) -> bool | None:
    if payload.signature_verified is not None:
        return payload.signature_verified

    if payload.signature_verification is not None:
        return True

    return None


def _build_signature_metadata(
    verification: WebhookSignatureVerificationResult | None,
) -> dict[str, Any] | None:
    if verification is None:
        return None

    signature_metadata: dict[str, Any] = {
        "verified_at": verification.verified_at.isoformat(),
    }
    if verification.algorithm is not None:
        signature_metadata["algorithm"] = verification.algorithm
    if verification.key_id is not None:
        signature_metadata["key_id"] = verification.key_id
    if verification.signed_at is not None:
        signature_metadata["signed_at"] = verification.signed_at.isoformat()
    return signature_metadata


def _merge_processing_metadata(
    existing: Mapping[str, Any] | None,
    updates: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if existing is None and updates is None:
        return None

    merged_metadata = dict(existing or {})
    merged_metadata.update(dict(updates or {}))
    return merged_metadata or None


webhook_event_store = WebhookEventStore()


__all__ = [
    "WebhookEventPersistenceRequest",
    "WebhookEventStore",
    "webhook_event_store",
]
