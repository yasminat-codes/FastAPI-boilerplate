from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.app.core.db.webhook_event import WebhookEventStatus
from src.app.core.request_context import CORRELATION_ID_STATE_KEY, REQUEST_ID_STATE_KEY
from src.app.platform.config import load_settings
from src.app.platform.database import WebhookEvent
from src.app.webhooks import (
    InvalidWebhookSignatureError,
    WebhookEventEnqueueRequest,
    WebhookEventEnqueueResult,
    WebhookIngestionRequest,
    WebhookReplayDetectedError,
    WebhookReplayFingerprintMismatchError,
    WebhookReplayKeyKind,
    WebhookSignatureVerificationContext,
    WebhookSignatureVerificationResult,
    ingest_webhook_event,
    validate_json_webhook_event,
)


def _build_webhook_request(
    *,
    raw_body: bytes = b'{"id":"evt_123","type":"invoice.updated"}',
    headers: dict[str, str] | None = None,
    request_id: str | None = "req-123",
    correlation_id: str | None = "corr-456",
) -> WebhookIngestionRequest:
    request_headers = {
        "Content-Type": "application/json; charset=utf-8",
        **(headers or {}),
    }
    state: dict[str, str] = {}
    if request_id is not None:
        state[REQUEST_ID_STATE_KEY] = request_id
    if correlation_id is not None:
        state[CORRELATION_ID_STATE_KEY] = correlation_id

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/v1/webhooks/provider",
        "raw_path": b"/api/v1/webhooks/provider",
        "query_string": b"",
        "headers": [(name.lower().encode("utf-8"), value.encode("utf-8")) for name, value in request_headers.items()],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
        "state": state,
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
    delivery_id: str | None = None,
    event_id: str | None = "evt_123",
    status: str = WebhookEventStatus.ENQUEUED.value,
) -> WebhookEvent:
    event = WebhookEvent(
        source="stripe",
        endpoint_key="billing-events",
        event_type="invoice.updated",
        status=status,
        delivery_id=delivery_id,
        event_id=event_id,
        signature_verified=True,
        payload_content_type="application/json; charset=utf-8",
        payload_sha256=sha256(raw_body).hexdigest(),
        payload_size_bytes=len(raw_body),
        received_at=datetime(2026, 4, 6, 21, 0, tzinfo=UTC),
    )
    event.id = 101
    return event


async def _verify_provider_signature(
    context: WebhookSignatureVerificationContext,
) -> WebhookSignatureVerificationResult:
    signature = context.get_header("X-Provider-Signature", required=True)
    if signature != "sha256=expected":
        raise InvalidWebhookSignatureError("signature mismatch")

    return WebhookSignatureVerificationResult(
        provider=context.provider,
        endpoint_key=context.endpoint_key,
        signature=signature,
        algorithm="hmac-sha256",
    )


@pytest.mark.asyncio
async def test_ingest_webhook_event_runs_receive_validate_persist_acknowledge_enqueue_flow() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    webhook_request = _build_webhook_request(headers={"X-Provider-Signature": "sha256=expected"})

    async def enqueue(request: WebhookEventEnqueueRequest) -> WebhookEventEnqueueResult:
        assert request.source == "stripe"
        assert request.endpoint_key == "billing-events"
        assert request.validated_event.event_type == "invoice.updated"
        assert request.correlation_id == "corr-456"
        assert request.replay_protection is not None
        assert request.replay_protection.key_kind is WebhookReplayKeyKind.EVENT_ID

        return WebhookEventEnqueueResult(
            job_name="platform.webhooks.process",
            queue_name="arq:webhooks",
            job_id="job-123",
            processing_metadata={"worker": {"target": "platform.webhooks.process"}},
        )

    result = await ingest_webhook_event(
        session=session,
        webhook_request=webhook_request,
        source="stripe",
        endpoint_key="billing-events",
        verifier=_verify_provider_signature,
        enqueuer=enqueue,
    )

    session.add.assert_called_once_with(result.persisted_event)
    session.flush.assert_awaited_once()

    assert result.correlation_id == "corr-456"
    assert result.validated_event.event_type == "invoice.updated"
    assert result.validated_event.event_id == "evt_123"
    assert result.replay_protection is not None
    assert result.replay_protection.key_kind is WebhookReplayKeyKind.EVENT_ID
    assert result.replay_protection.key_value == "evt_123"
    assert result.enqueue_result is not None
    assert result.enqueue_result.job_id == "job-123"
    assert result.persisted_event.status == WebhookEventStatus.ENQUEUED.value
    assert result.persisted_event.acknowledged_at is not None
    assert result.persisted_event.signature_verified is True
    assert result.persisted_event.normalized_payload == {"id": "evt_123", "type": "invoice.updated"}
    assert result.persisted_event.processing_metadata == {
        "correlation_id": "corr-456",
        "signature": {
            "verified_at": (
                result.signature_verification.verified_at.isoformat()
                if result.signature_verification
                else ""
            ),
            "algorithm": "hmac-sha256",
        },
        "replay_protection": {
            "checked_at": result.replay_protection.checked_at.isoformat(),
            "key_kind": "event_id",
            "key_value": "evt_123",
            "payload_sha256": result.replay_protection.payload_sha256,
            "window_seconds": 300,
            "event_id": "evt_123",
        },
        "worker": {"target": "platform.webhooks.process"},
        "enqueue": {
            "job_name": "platform.webhooks.process",
            "queue_name": "arq:webhooks",
            "job_id": "job-123",
            "status": "queued",
        },
    }


@pytest.mark.asyncio
async def test_ingest_webhook_event_requires_verifier_when_signature_verification_is_enabled() -> None:
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(ValueError, match="signature verifier is required"):
        await ingest_webhook_event(
            session=session,
            webhook_request=_build_webhook_request(),
            source="stripe",
            endpoint_key="billing-events",
            enqueuer=lambda request: None,
        )


@pytest.mark.asyncio
async def test_ingest_webhook_event_allows_verifierless_flow_when_runtime_settings_disable_it() -> None:
    session = AsyncMock(spec=AsyncSession)
    configured_settings = load_settings(
        _env_file=None,
        WEBHOOK_SIGNATURE_VERIFICATION_ENABLED=False,
        WEBHOOK_REPLAY_PROTECTION_ENABLED=False,
    )

    result = await ingest_webhook_event(
        session=session,
        webhook_request=_build_webhook_request(),
        source="stripe",
        endpoint_key="billing-events",
        enqueuer=lambda request: None,
        runtime_settings=configured_settings,
    )

    assert result.signature_verification is None
    assert result.replay_protection is None
    assert result.persisted_event.signature_verified is None
    assert result.persisted_event.status == WebhookEventStatus.ENQUEUED.value
    assert result.persisted_event.processing_metadata == {
        "correlation_id": "corr-456",
        "enqueue": {"status": "queued"},
    }
    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_webhook_event_marks_failed_when_enqueue_raises() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    webhook_request = _build_webhook_request(headers={"X-Provider-Signature": "sha256=expected"})

    async def enqueue(request: WebhookEventEnqueueRequest) -> WebhookEventEnqueueResult:
        raise RuntimeError("queue unavailable")

    with pytest.raises(RuntimeError, match="queue unavailable"):
        await ingest_webhook_event(
            session=session,
            webhook_request=webhook_request,
            source="stripe",
            endpoint_key="billing-events",
            verifier=_verify_provider_signature,
            enqueuer=enqueue,
        )

    persisted_event = session.add.call_args.args[0]

    assert persisted_event.status == WebhookEventStatus.FAILED.value
    assert persisted_event.acknowledged_at is not None
    assert persisted_event.processing_error == "queue unavailable"
    assert persisted_event.processing_metadata == {
        "correlation_id": "corr-456",
        "signature": {
            "verified_at": persisted_event.processing_metadata["signature"]["verified_at"],
            "algorithm": "hmac-sha256",
        },
        "replay_protection": {
            "checked_at": persisted_event.processing_metadata["replay_protection"]["checked_at"],
            "key_kind": "event_id",
            "key_value": "evt_123",
            "payload_sha256": persisted_event.processing_metadata["replay_protection"]["payload_sha256"],
            "window_seconds": 300,
            "event_id": "evt_123",
        },
        "enqueue": {"status": "failed"},
    }


@pytest.mark.asyncio
async def test_ingest_webhook_event_rejects_recent_replay_before_persisting() -> None:
    session = AsyncMock(spec=AsyncSession)
    raw_body = b'{"id":"evt_123","type":"invoice.updated"}'
    session.scalar.return_value = _build_existing_event(raw_body=raw_body)

    with pytest.raises(WebhookReplayDetectedError, match="replay detected"):
        await ingest_webhook_event(
            session=session,
            webhook_request=_build_webhook_request(
                raw_body=raw_body,
                headers={"X-Provider-Signature": "sha256=expected"},
            ),
            source="stripe",
            endpoint_key="billing-events",
            verifier=_verify_provider_signature,
            enqueuer=lambda request: None,
        )

    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_webhook_event_rejects_identifier_reuse_with_changed_payload() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = _build_existing_event(raw_body=b'{"id":"evt_123","type":"invoice.updated"}')

    with pytest.raises(WebhookReplayFingerprintMismatchError, match="different payload fingerprint"):
        await ingest_webhook_event(
            session=session,
            webhook_request=_build_webhook_request(
                raw_body=b'{"id":"evt_123","type":"invoice.updated","attempt":2}',
                headers={"X-Provider-Signature": "sha256=expected"},
            ),
            source="stripe",
            endpoint_key="billing-events",
            verifier=_verify_provider_signature,
            enqueuer=lambda request: None,
        )

    session.add.assert_not_called()
    session.flush.assert_not_awaited()


def test_validate_json_webhook_event_requires_an_object_payload_with_a_type_field() -> None:
    with pytest.raises(ValueError, match="must include a non-empty 'type' field"):
        validate_json_webhook_event(_build_webhook_request(raw_body=b'{"id":"evt_123"}'))

    with pytest.raises(ValueError, match="must be an object"):
        validate_json_webhook_event(_build_webhook_request(raw_body=b'["not-an-object"]'))
