from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.app.core.db.webhook_event import WebhookEventStatus
from src.app.platform.database import WebhookEvent
from src.app.webhooks import (
    WebhookIngestionRequest,
    WebhookReplayDetectedError,
    WebhookReplayKeyKind,
    WebhookReplayProtectionRequest,
    WebhookValidatedEvent,
    webhook_replay_protector,
)


def _build_webhook_request(raw_body: bytes) -> WebhookIngestionRequest:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/v1/webhooks/provider",
        "raw_path": b"/api/v1/webhooks/provider",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json; charset=utf-8")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
    }
    request = Request(scope)

    return WebhookIngestionRequest(
        request=request,
        raw_body=raw_body,
        content_type=request.headers.get("content-type"),
    )


def _build_existing_event(
    *,
    raw_body: bytes,
    event_type: str = "invoice.updated",
    delivery_id: str | None = None,
    event_id: str | None = None,
) -> WebhookEvent:
    event = WebhookEvent(
        source="stripe",
        endpoint_key="billing-events",
        event_type=event_type,
        status=WebhookEventStatus.RECEIVED.value,
        delivery_id=delivery_id,
        event_id=event_id,
        payload_sha256=sha256(raw_body).hexdigest(),
        payload_size_bytes=len(raw_body),
        received_at=datetime(2026, 4, 6, 21, 5, tzinfo=UTC),
    )
    event.id = 202
    return event


@pytest.mark.asyncio
async def test_webhook_replay_protector_returns_metadata_for_first_seen_identifier() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    request = WebhookReplayProtectionRequest(
        source="stripe",
        endpoint_key="billing-events",
        webhook_request=_build_webhook_request(b'{"id":"evt_123","type":"invoice.updated"}'),
        validated_event=WebhookValidatedEvent(
            event_type="invoice.updated",
            delivery_id="dlv_123",
            event_id="evt_123",
        ),
        replay_window_seconds=300,
        checked_at=datetime(2026, 4, 6, 21, 10, tzinfo=UTC),
    )

    result = await webhook_replay_protector.protect(session, request)

    assert result.key_kind is WebhookReplayKeyKind.DELIVERY_ID
    assert result.key_value == "dlv_123"
    assert result.payload_sha256 == sha256(b'{"id":"evt_123","type":"invoice.updated"}').hexdigest()
    assert result.as_processing_metadata() == {
        "replay_protection": {
            "checked_at": "2026-04-06T21:10:00+00:00",
            "key_kind": "delivery_id",
            "key_value": "dlv_123",
            "payload_sha256": result.payload_sha256,
            "window_seconds": 300,
            "delivery_id": "dlv_123",
            "event_id": "evt_123",
        }
    }


@pytest.mark.asyncio
async def test_webhook_replay_protector_falls_back_to_payload_hash_without_provider_identifiers() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    raw_body = b'{"type":"invoice.updated","attempt":1}'

    result = await webhook_replay_protector.protect(
        session,
        WebhookReplayProtectionRequest(
            source="stripe",
            endpoint_key="billing-events",
            webhook_request=_build_webhook_request(raw_body),
            validated_event=WebhookValidatedEvent(event_type="invoice.updated"),
            replay_window_seconds=300,
        ),
    )

    assert result.key_kind is WebhookReplayKeyKind.PAYLOAD_SHA256
    assert result.key_value == sha256(raw_body).hexdigest()


@pytest.mark.asyncio
async def test_webhook_replay_protector_detects_payload_hash_replays_without_provider_identifiers() -> None:
    session = AsyncMock(spec=AsyncSession)
    raw_body = b'{"type":"invoice.updated","attempt":1}'
    session.scalar.return_value = _build_existing_event(raw_body=raw_body, event_id=None)

    with pytest.raises(WebhookReplayDetectedError, match="payload_sha256"):
        await webhook_replay_protector.protect(
            session,
            WebhookReplayProtectionRequest(
                source="stripe",
                endpoint_key="billing-events",
                webhook_request=_build_webhook_request(raw_body),
                validated_event=WebhookValidatedEvent(event_type="invoice.updated"),
                replay_window_seconds=300,
            ),
        )
