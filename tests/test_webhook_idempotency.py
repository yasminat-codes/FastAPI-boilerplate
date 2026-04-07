from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.app.core.db.idempotency_key import IdempotencyKeyStatus
from src.app.platform.database import IdempotencyKey
from src.app.webhooks import (
    WebhookIdempotencyFingerprintMismatchError,
    WebhookIdempotencyProtector,
    WebhookIdempotencyRequest,
    WebhookIdempotencyViolationError,
    WebhookIngestionRequest,
    WebhookValidatedEvent,
    record_idempotency_key,
)


def _build_webhook_request(
    raw_body: bytes = b'{"id":"evt_123","type":"invoice.updated"}',
) -> WebhookIngestionRequest:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/v1/webhooks/provider",
        "raw_path": b"/api/v1/webhooks/provider",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
        "state": {},
    }
    return WebhookIngestionRequest(
        request=Request(scope),
        raw_body=raw_body,
        content_type="application/json",
    )


def _build_validated_event(
    event_type: str = "invoice.updated",
    event_id: str | None = "evt_123",
    delivery_id: str | None = None,
) -> WebhookValidatedEvent:
    return WebhookValidatedEvent(
        event_type=event_type,
        event_id=event_id,
        delivery_id=delivery_id,
    )


def _build_idempotency_request(
    raw_body: bytes = b'{"id":"evt_123","type":"invoice.updated"}',
    event_id: str | None = "evt_123",
    delivery_id: str | None = None,
    window_seconds: int = 300,
) -> WebhookIdempotencyRequest:
    return WebhookIdempotencyRequest(
        source="stripe",
        endpoint_key="billing-events",
        webhook_request=_build_webhook_request(raw_body),
        validated_event=_build_validated_event(
            event_id=event_id,
            delivery_id=delivery_id,
        ),
        idempotency_window_seconds=window_seconds,
    )


def _build_existing_idempotency_key(
    scope: str = "webhook:stripe:billing-events",
    key: str = "event_id:evt_123",
    fingerprint: str | None = None,
    raw_body: bytes = b'{"id":"evt_123","type":"invoice.updated"}',
) -> IdempotencyKey:
    resolved_fingerprint = fingerprint or sha256(raw_body).hexdigest()
    record = IdempotencyKey(
        scope=scope,
        key=key,
        status=IdempotencyKeyStatus.PROCESSING.value,
        request_fingerprint=resolved_fingerprint,
        first_seen_at=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
        last_seen_at=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
        hit_count=1,
    )
    record.id = 42
    return record


@pytest.mark.asyncio
async def test_idempotency_protector_allows_new_event() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    protector = WebhookIdempotencyProtector()
    request = _build_idempotency_request()

    result = await protector.protect(session, request)

    assert result.scope == "webhook:stripe:billing-events"
    assert result.idempotency_key == "event_id:evt_123"
    assert result.event_id == "evt_123"
    assert result.idempotency_window_seconds == 300


@pytest.mark.asyncio
async def test_idempotency_protector_rejects_duplicate() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = _build_existing_idempotency_key()
    protector = WebhookIdempotencyProtector()
    request = _build_idempotency_request()

    with pytest.raises(WebhookIdempotencyViolationError, match="idempotency violation"):
        await protector.protect(session, request)


@pytest.mark.asyncio
async def test_idempotency_protector_detects_fingerprint_mismatch() -> None:
    session = AsyncMock(spec=AsyncSession)
    existing = _build_existing_idempotency_key(
        fingerprint="different_fingerprint_hash",
    )
    session.scalar.return_value = existing
    protector = WebhookIdempotencyProtector()
    request = _build_idempotency_request()

    with pytest.raises(
        WebhookIdempotencyFingerprintMismatchError,
        match="different fingerprint",
    ):
        await protector.protect(session, request)


@pytest.mark.asyncio
async def test_idempotency_protector_increments_hit_count_on_duplicate() -> None:
    session = AsyncMock(spec=AsyncSession)
    existing = _build_existing_idempotency_key()
    existing.hit_count = 3
    session.scalar.return_value = existing
    protector = WebhookIdempotencyProtector()
    request = _build_idempotency_request()

    with pytest.raises(WebhookIdempotencyViolationError) as exc_info:
        await protector.protect(session, request)

    assert exc_info.value.match.existing_hit_count == 4
    assert existing.hit_count == 4


def test_idempotency_request_key_priority_event_id() -> None:
    request = _build_idempotency_request(event_id="evt_999")
    assert request.idempotency_key == "event_id:evt_999"


def test_idempotency_request_key_priority_delivery_id() -> None:
    request = _build_idempotency_request(event_id=None, delivery_id="del_777")
    assert request.idempotency_key == "delivery_id:del_777"


def test_idempotency_request_key_falls_back_to_payload_hash() -> None:
    raw_body = b'{"type":"test.event"}'
    request = _build_idempotency_request(
        raw_body=raw_body,
        event_id=None,
        delivery_id=None,
    )
    expected_hash = sha256(raw_body).hexdigest()
    assert request.idempotency_key == f"payload_sha256:{expected_hash}"


def test_idempotency_request_validates_source() -> None:
    with pytest.raises(ValueError, match="source must not be empty"):
        WebhookIdempotencyRequest(
            source="  ",
            endpoint_key="billing-events",
            webhook_request=_build_webhook_request(),
            validated_event=_build_validated_event(),
            idempotency_window_seconds=300,
        )


def test_idempotency_request_validates_window() -> None:
    with pytest.raises(ValueError, match="at least 1 second"):
        WebhookIdempotencyRequest(
            source="stripe",
            endpoint_key="billing-events",
            webhook_request=_build_webhook_request(),
            validated_event=_build_validated_event(),
            idempotency_window_seconds=0,
        )


def test_idempotency_result_metadata() -> None:
    result = WebhookIdempotencyRequest(
        source="stripe",
        endpoint_key="billing-events",
        webhook_request=_build_webhook_request(),
        validated_event=_build_validated_event(),
        idempotency_window_seconds=300,
    )
    from src.app.webhooks.idempotency import WebhookIdempotencyResult

    idempotency_result = WebhookIdempotencyResult(
        scope=result.scope,
        idempotency_key=result.idempotency_key,
        request_fingerprint=result.request_fingerprint,
        idempotency_window_seconds=300,
        checked_at=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
        event_id="evt_123",
    )
    metadata = idempotency_result.as_processing_metadata()
    assert "idempotency" in metadata
    assert metadata["idempotency"]["key"] == "event_id:evt_123"
    assert metadata["idempotency"]["window_seconds"] == 300


@pytest.mark.asyncio
async def test_record_idempotency_key_persists_to_session() -> None:
    session = AsyncMock(spec=AsyncSession)
    request = _build_idempotency_request()

    record = await record_idempotency_key(session, request)

    session.add.assert_called_once_with(record)
    session.flush.assert_awaited_once()
    assert record.scope == "webhook:stripe:billing-events"
    assert record.key == "event_id:evt_123"
    assert record.status == IdempotencyKeyStatus.PROCESSING.value
    assert record.hit_count == 1
    assert record.expires_at is not None
    expected_expiry = request.checked_at + timedelta(seconds=300)
    assert record.expires_at == expected_expiry
