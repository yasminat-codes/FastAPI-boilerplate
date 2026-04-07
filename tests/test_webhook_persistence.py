from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.app.core.db.webhook_event import WebhookEvent, WebhookEventStatus
from src.app.platform.webhooks import WebhookEventPersistenceRequest as PlatformWebhookEventPersistenceRequest
from src.app.platform.webhooks import WebhookEventStore as PlatformWebhookEventStore
from src.app.platform.webhooks import webhook_event_store as platform_webhook_event_store
from src.app.webhooks import (
    WebhookEventPersistenceRequest,
    WebhookEventStore,
    WebhookIngestionRequest,
    WebhookSignatureVerificationResult,
    webhook_event_store,
)


def _build_webhook_request(
    *,
    raw_body: bytes = b'{"id":"evt_123","type":"invoice.updated"}',
    headers: dict[str, str] | None = None,
) -> WebhookIngestionRequest:
    request_headers = {
        "Content-Type": "application/json; charset=utf-8",
        **(headers or {}),
    }
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/webhooks/provider",
        "raw_path": b"/webhooks/provider",
        "query_string": b"",
        "headers": [(name.lower().encode("utf-8"), value.encode("utf-8")) for name, value in request_headers.items()],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
    }
    request = Request(scope)

    return WebhookIngestionRequest(
        request=request,
        raw_body=raw_body,
        content_type=request.headers.get("content-type"),
    )


def test_platform_webhook_surface_reexports_canonical_persistence_helpers() -> None:
    assert PlatformWebhookEventPersistenceRequest is WebhookEventPersistenceRequest
    assert PlatformWebhookEventStore is WebhookEventStore
    assert platform_webhook_event_store is webhook_event_store


@pytest.mark.asyncio
async def test_webhook_event_store_persists_ingestion_context_and_signature_metadata() -> None:
    webhook_request = _build_webhook_request()
    verified_at = datetime(2026, 4, 6, 20, 15, tzinfo=UTC)
    signed_at = datetime(2026, 4, 6, 20, 14, tzinfo=UTC)
    session = AsyncMock(spec=AsyncSession)

    event = await webhook_event_store.persist(
        session,
        WebhookEventPersistenceRequest(
            source="stripe",
            endpoint_key="billing-events",
            event_type="invoice.updated",
            webhook_request=webhook_request,
            delivery_id="delivery_123",
            event_id="evt_123",
            normalized_payload={"id": "evt_123", "type": "invoice.updated"},
            processing_metadata={"pipeline": {"stage": "receive"}},
            signature_verification=WebhookSignatureVerificationResult(
                provider="stripe",
                endpoint_key="billing-events",
                verified_at=verified_at,
                algorithm="hmac-sha256",
                key_id="primary",
                signed_at=signed_at,
            ),
        ),
    )

    session.add.assert_called_once_with(event)
    session.flush.assert_awaited_once()

    assert isinstance(event, WebhookEvent)
    assert event.source == "stripe"
    assert event.endpoint_key == "billing-events"
    assert event.event_type == "invoice.updated"
    assert event.status == WebhookEventStatus.RECEIVED.value
    assert event.delivery_id == "delivery_123"
    assert event.event_id == "evt_123"
    assert event.signature_verified is True
    assert event.payload_content_type == "application/json; charset=utf-8"
    assert event.payload_sha256 == sha256(webhook_request.raw_body).hexdigest()
    assert event.payload_size_bytes == len(webhook_request.raw_body)
    assert event.raw_payload == webhook_request.raw_body.decode("utf-8")
    assert event.normalized_payload == {"id": "evt_123", "type": "invoice.updated"}
    assert event.processing_metadata == {
        "pipeline": {"stage": "receive"},
        "signature": {
            "verified_at": verified_at.isoformat(),
            "algorithm": "hmac-sha256",
            "key_id": "primary",
            "signed_at": signed_at.isoformat(),
        },
    }


def test_webhook_event_store_can_build_unverified_records_without_storing_raw_payload() -> None:
    event = webhook_event_store.build_event(
        WebhookEventPersistenceRequest(
            source="stripe",
            endpoint_key="billing-events",
            event_type="invoice.updated",
            webhook_request=_build_webhook_request(),
            signature_verified=False,
            status=WebhookEventStatus.REJECTED,
            store_raw_payload=False,
            processing_metadata={"reason": "invalid_signature"},
        )
    )

    assert event.status == WebhookEventStatus.REJECTED.value
    assert event.signature_verified is False
    assert event.raw_payload is None
    assert event.processing_metadata == {"reason": "invalid_signature"}


def test_webhook_event_store_marks_lifecycle_transitions_and_merges_metadata() -> None:
    event = WebhookEvent(source="stripe", endpoint_key="billing-events", event_type="invoice.updated")
    acknowledged_at = datetime(2026, 4, 6, 20, 30, tzinfo=UTC)
    processed_at = datetime(2026, 4, 6, 20, 45, tzinfo=UTC)

    webhook_event_store.mark_acknowledged(
        event,
        acknowledged_at=acknowledged_at,
        processing_metadata={"intake": {"attempt": 1}},
    )
    webhook_event_store.mark_enqueued(
        event,
        processing_metadata={"queue": {"name": "webhooks"}},
    )
    webhook_event_store.mark_processed(
        event,
        processed_at=processed_at,
        processing_metadata={"worker": {"job_name": "process_webhook"}},
    )

    assert event.status == WebhookEventStatus.PROCESSED.value
    assert event.acknowledged_at == acknowledged_at
    assert event.processed_at == processed_at
    assert event.processing_metadata == {
        "intake": {"attempt": 1},
        "queue": {"name": "webhooks"},
        "worker": {"job_name": "process_webhook"},
    }


def test_webhook_event_store_marks_rejected_and_failed_terminal_states() -> None:
    event = WebhookEvent(source="stripe", endpoint_key="billing-events", event_type="invoice.updated")
    rejected_at = datetime(2026, 4, 6, 20, 32, tzinfo=UTC)
    failed_at = datetime(2026, 4, 6, 20, 47, tzinfo=UTC)

    webhook_event_store.mark_rejected(
        event,
        processed_at=rejected_at,
        processing_error="signature mismatch",
        processing_metadata={"reason": "invalid_signature"},
    )

    assert event.status == WebhookEventStatus.REJECTED.value
    assert event.processed_at == rejected_at
    assert event.processing_error == "signature mismatch"
    assert event.processing_metadata == {"reason": "invalid_signature"}

    webhook_event_store.mark_failed(
        event,
        processed_at=failed_at,
        processing_error="worker execution failed",
        processing_metadata={"worker": {"attempt": 3}},
    )

    assert event.status == WebhookEventStatus.FAILED.value
    assert event.processed_at == failed_at
    assert event.processing_error == "worker execution failed"
    assert event.processing_metadata == {
        "reason": "invalid_signature",
        "worker": {"attempt": 3},
    }


def test_webhook_event_store_rejects_unknown_status_values() -> None:
    with pytest.raises(ValueError, match="Unsupported webhook event status"):
        webhook_event_store.build_event(
            WebhookEventPersistenceRequest(
                source="stripe",
                endpoint_key="billing-events",
                event_type="invoice.updated",
                webhook_request=_build_webhook_request(),
                status="not-a-real-status",
            )
        )
