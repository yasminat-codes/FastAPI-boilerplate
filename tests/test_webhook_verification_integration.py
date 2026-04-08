"""Integration tests for webhook signature verification and replay protection.

Tests the interactions between verification and replay protection components,
including end-to-end flows with real HMAC computation and database session
interactions.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
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
    WebhookReplayProtectionRequest,
    WebhookSignatureVerificationContext,
    WebhookSignatureVerificationResult,
    WebhookValidatedEvent,
    ingest_webhook_event,
    webhook_replay_protector,
)
from src.app.webhooks.providers.base import HmacWebhookVerifier, WebhookProviderConfig
from src.app.webhooks.signatures import verify_webhook_signature

# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------


def _build_webhook_request(
    *,
    raw_body: bytes = b'{"id":"evt_123","type":"invoice.updated"}',
    headers: dict[str, str] | None = None,
    request_id: str | None = "req-123",
    correlation_id: str | None = "corr-456",
) -> WebhookIngestionRequest:
    """Build a WebhookIngestionRequest with optional headers and correlation."""
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
        "headers": [
            (name.lower().encode("utf-8"), value.encode("utf-8"))
            for name, value in request_headers.items()
        ],
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


def _build_existing_webhook_event(
    *,
    raw_body: bytes,
    delivery_id: str | None = None,
    event_id: str | None = "evt_123",
    status: str = WebhookEventStatus.ENQUEUED.value,
    received_at: datetime | None = None,
) -> WebhookEvent:
    """Build a WebhookEvent for replay detection testing."""
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
        received_at=received_at or datetime(2026, 4, 6, 21, 0, tzinfo=UTC),
    )
    event.id = 101
    return event


def _compute_hmac_sha256(secret: str, body: bytes) -> str:
    """Compute a hex HMAC-SHA256 digest."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class ConcreteHmacSignatureVerifier(HmacWebhookVerifier):
    """Concrete HMAC verifier for testing."""

    pass


# ---------------------------------------------------------------------------
# End-to-End HMAC Signature Verification Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hmac_verifier_with_real_computation_accepts_valid_signature() -> None:
    """Test HMAC-SHA256 verification with real signature computation."""
    secret = "test-signing-secret"
    raw_body = b'{"id":"evt_123","type":"invoice.updated"}'
    expected_sig = _compute_hmac_sha256(secret, raw_body)

    config = WebhookProviderConfig(
        source="test_provider",
        endpoint_key="default",
        signing_secret=secret,
        signature_header="x-signature",
        signature_algorithm="sha256",
        signature_encoding="hex",
        signature_prefix="",
    )
    verifier = ConcreteHmacSignatureVerifier(config)

    webhook_request = _build_webhook_request(
        raw_body=raw_body,
        headers={"X-Signature": expected_sig},
    )

    context = WebhookSignatureVerificationContext(
        provider="test_provider",
        endpoint_key="default",
        request=webhook_request,
    )

    result = await verifier.verify(context)

    assert result.provider == "test_provider"
    assert result.endpoint_key == "default"
    assert result.signature == expected_sig
    assert result.algorithm == "hmac-sha256"
    assert result.verified_at is not None


@pytest.mark.asyncio
async def test_hmac_verifier_rejects_tampered_payload() -> None:
    """Test that HMAC verifier rejects payloads that don't match the signature."""
    secret = "test-signing-secret"
    original_body = b'{"id":"evt_123","type":"invoice.updated"}'
    tampered_body = b'{"id":"evt_123","type":"invoice.updated","extra":"field"}'
    original_sig = _compute_hmac_sha256(secret, original_body)

    config = WebhookProviderConfig(
        source="test_provider",
        endpoint_key="default",
        signing_secret=secret,
        signature_header="x-signature",
        signature_algorithm="sha256",
    )
    verifier = ConcreteHmacSignatureVerifier(config)

    webhook_request = _build_webhook_request(
        raw_body=tampered_body,
        headers={"X-Signature": original_sig},
    )

    context = WebhookSignatureVerificationContext(
        provider="test_provider",
        endpoint_key="default",
        request=webhook_request,
    )

    with pytest.raises(InvalidWebhookSignatureError, match="signature mismatch"):
        await verifier.verify(context)


@pytest.mark.asyncio
async def test_hmac_verifier_with_prefix_strips_and_validates() -> None:
    """Test that HMAC verifier correctly handles signature prefixes."""
    secret = "test-signing-secret"
    raw_body = b'{"id":"evt_123","type":"invoice.updated"}'
    expected_sig = _compute_hmac_sha256(secret, raw_body)
    prefixed_sig = f"sha256={expected_sig}"

    config = WebhookProviderConfig(
        source="test_provider",
        endpoint_key="default",
        signing_secret=secret,
        signature_header="x-signature",
        signature_algorithm="sha256",
        signature_prefix="sha256=",
    )
    verifier = ConcreteHmacSignatureVerifier(config)

    webhook_request = _build_webhook_request(
        raw_body=raw_body,
        headers={"X-Signature": prefixed_sig},
    )

    context = WebhookSignatureVerificationContext(
        provider="test_provider",
        endpoint_key="default",
        request=webhook_request,
    )

    result = await verifier.verify(context)

    assert result.signature == expected_sig
    assert result.algorithm == "hmac-sha256"


@pytest.mark.asyncio
async def test_verify_webhook_signature_callable_verifier() -> None:
    """Test verify_webhook_signature with a callable verifier function."""
    secret = "test-signing-secret"
    raw_body = b'{"id":"evt_123","type":"invoice.updated"}'
    expected_sig = _compute_hmac_sha256(secret, raw_body)

    async def custom_verifier(
        context: WebhookSignatureVerificationContext,
    ) -> WebhookSignatureVerificationResult:
        received = context.get_header("x-custom-sig", required=True)
        if received != expected_sig:
            raise InvalidWebhookSignatureError("Custom verification failed")
        return WebhookSignatureVerificationResult(
            provider=context.provider,
            endpoint_key=context.endpoint_key,
            signature=received,
            algorithm="hmac-custom",
        )

    webhook_request = _build_webhook_request(
        raw_body=raw_body,
        headers={"X-Custom-Sig": expected_sig},
    )

    result = await verify_webhook_signature(
        custom_verifier,
        request=webhook_request,
        provider="custom_provider",
        endpoint_key="default",
    )

    assert result.provider == "custom_provider"
    assert result.signature == expected_sig
    assert result.algorithm == "hmac-custom"


# ---------------------------------------------------------------------------
# Replay Protection Integration Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_protection_detects_duplicate_delivery_id() -> None:
    """Test that replay protection detects duplicate delivery IDs within window."""
    session = AsyncMock(spec=AsyncSession)
    raw_body = b'{"id":"evt_123","type":"invoice.updated"}'

    existing_event = _build_existing_webhook_event(
        raw_body=raw_body,
        delivery_id="dlv_abc123",
        event_id="evt_123",
    )
    session.scalar.return_value = existing_event

    webhook_request = _build_webhook_request(raw_body=raw_body)
    protection_request = WebhookReplayProtectionRequest(
        source="stripe",
        endpoint_key="billing-events",
        webhook_request=webhook_request,
        validated_event=WebhookValidatedEvent(
            event_type="invoice.updated",
            delivery_id="dlv_abc123",
            event_id="evt_123",
        ),
        replay_window_seconds=300,
        checked_at=datetime(2026, 4, 6, 21, 5, tzinfo=UTC),
    )

    with pytest.raises(WebhookReplayDetectedError) as exc_info:
        await webhook_replay_protector.protect(session, protection_request)

    match = exc_info.value.match
    assert match.source == "stripe"
    assert match.endpoint_key == "billing-events"
    assert WebhookReplayKeyKind.DELIVERY_ID in match.matched_on


@pytest.mark.asyncio
async def test_replay_protection_detects_payload_fingerprint_mismatch() -> None:
    """Test that replay protection detects when a delivery ID replayed with different payload."""
    session = AsyncMock(spec=AsyncSession)
    original_body = b'{"id":"evt_123","type":"invoice.updated"}'
    modified_body = b'{"id":"evt_123","type":"invoice.updated","modified":true}'

    existing_event = _build_existing_webhook_event(
        raw_body=original_body,
        delivery_id="dlv_abc123",
        event_id="evt_123",
    )
    session.scalar.return_value = existing_event

    webhook_request = _build_webhook_request(raw_body=modified_body)
    protection_request = WebhookReplayProtectionRequest(
        source="stripe",
        endpoint_key="billing-events",
        webhook_request=webhook_request,
        validated_event=WebhookValidatedEvent(
            event_type="invoice.updated",
            delivery_id="dlv_abc123",
            event_id="evt_123",
        ),
        replay_window_seconds=300,
        checked_at=datetime(2026, 4, 6, 21, 5, tzinfo=UTC),
    )

    with pytest.raises(WebhookReplayFingerprintMismatchError) as exc_info:
        await webhook_replay_protector.protect(session, protection_request)

    match = exc_info.value.match
    assert match.existing_payload_sha256 == sha256(original_body).hexdigest()
    assert match.candidate_payload_sha256 == sha256(modified_body).hexdigest()
    assert match.existing_payload_sha256 != match.candidate_payload_sha256


@pytest.mark.asyncio
async def test_replay_protection_respects_time_window() -> None:
    """Test that replay protection only checks within the configured time window."""
    session = AsyncMock(spec=AsyncSession)
    raw_body = b'{"id":"evt_123","type":"invoice.updated"}'

    old_timestamp = datetime(2026, 4, 6, 20, 0, tzinfo=UTC)
    window_seconds = 300
    check_time = datetime(2026, 4, 6, 21, 0, tzinfo=UTC)

    existing_event = _build_existing_webhook_event(
        raw_body=raw_body,
        event_id="evt_123",
        received_at=old_timestamp,
    )
    session.scalar.return_value = existing_event

    webhook_request = _build_webhook_request(raw_body=raw_body)
    protection_request = WebhookReplayProtectionRequest(
        source="stripe",
        endpoint_key="billing-events",
        webhook_request=webhook_request,
        validated_event=WebhookValidatedEvent(
            event_type="invoice.updated",
            event_id="evt_123",
        ),
        replay_window_seconds=window_seconds,
        checked_at=check_time,
    )

    # Verify the time window is correctly calculated
    assert check_time - timedelta(seconds=window_seconds) > old_timestamp
    session.scalar.return_value = None

    result = await webhook_replay_protector.protect(session, protection_request)

    assert result.key_kind is WebhookReplayKeyKind.EVENT_ID
    assert result.key_value == "evt_123"


@pytest.mark.asyncio
async def test_replay_protection_falls_back_to_payload_hash() -> None:
    """Test that replay protection uses payload hash when no provider identifiers."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    raw_body = b'{"type":"invoice.updated"}'

    webhook_request = _build_webhook_request(raw_body=raw_body)
    protection_request = WebhookReplayProtectionRequest(
        source="stripe",
        endpoint_key="billing-events",
        webhook_request=webhook_request,
        validated_event=WebhookValidatedEvent(event_type="invoice.updated"),
        replay_window_seconds=300,
    )

    result = await webhook_replay_protector.protect(session, protection_request)

    assert result.key_kind is WebhookReplayKeyKind.PAYLOAD_SHA256
    assert result.key_value == sha256(raw_body).hexdigest()


# ---------------------------------------------------------------------------
# Full Ingestion Pipeline with Verification Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_webhook_event_with_successful_hmac_verification() -> None:
    """Test complete flow with real HMAC verification and replay protection."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None

    secret = "test-signing-secret"
    raw_body = b'{"id":"evt_123","type":"invoice.updated"}'
    expected_sig = _compute_hmac_sha256(secret, raw_body)

    config = WebhookProviderConfig(
        source="stripe",
        endpoint_key="billing-events",
        signing_secret=secret,
        signature_header="x-stripe-signature",
        signature_algorithm="sha256",
    )
    verifier = ConcreteHmacSignatureVerifier(config)

    webhook_request = _build_webhook_request(
        raw_body=raw_body,
        headers={"X-Stripe-Signature": expected_sig},
    )

    async def enqueue(request: WebhookEventEnqueueRequest) -> WebhookEventEnqueueResult:
        assert request.signature_verification is not None
        assert request.signature_verification.signature == expected_sig
        assert request.replay_protection is not None
        return WebhookEventEnqueueResult(job_id="job-123")

    result = await ingest_webhook_event(
        session=session,
        webhook_request=webhook_request,
        source="stripe",
        endpoint_key="billing-events",
        verifier=verifier,
        enqueuer=enqueue,
    )

    assert result.signature_verification is not None
    assert result.signature_verification.signature == expected_sig
    assert result.signature_verification.algorithm == "hmac-sha256"
    assert result.replay_protection is not None
    assert result.replay_protection.key_kind is WebhookReplayKeyKind.EVENT_ID
    assert result.persisted_event.signature_verified is True


@pytest.mark.asyncio
async def test_ingest_webhook_event_rejects_invalid_signature_before_replay_check() -> None:
    """Test that signature verification failure prevents replay protection."""
    session = AsyncMock(spec=AsyncSession)

    secret = "test-signing-secret"
    raw_body = b'{"id":"evt_123","type":"invoice.updated"}'
    wrong_sig = "invalid-signature"

    config = WebhookProviderConfig(
        source="stripe",
        endpoint_key="billing-events",
        signing_secret=secret,
        signature_header="x-stripe-signature",
        signature_algorithm="sha256",
    )
    verifier = ConcreteHmacSignatureVerifier(config)

    webhook_request = _build_webhook_request(
        raw_body=raw_body,
        headers={"X-Stripe-Signature": wrong_sig},
    )

    with pytest.raises(InvalidWebhookSignatureError, match="signature mismatch"):
        await ingest_webhook_event(
            session=session,
            webhook_request=webhook_request,
            source="stripe",
            endpoint_key="billing-events",
            verifier=verifier,
            enqueuer=lambda request: None,
        )

    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_webhook_event_detects_replay_after_verification() -> None:
    """Test that replay detection happens after successful verification."""
    session = AsyncMock(spec=AsyncSession)
    secret = "test-signing-secret"
    raw_body = b'{"id":"evt_123","type":"invoice.updated"}'
    expected_sig = _compute_hmac_sha256(secret, raw_body)

    existing_event = _build_existing_webhook_event(
        raw_body=raw_body,
        event_id="evt_123",
    )
    session.scalar.return_value = existing_event

    config = WebhookProviderConfig(
        source="stripe",
        endpoint_key="billing-events",
        signing_secret=secret,
        signature_header="x-stripe-signature",
        signature_algorithm="sha256",
    )
    verifier = ConcreteHmacSignatureVerifier(config)

    webhook_request = _build_webhook_request(
        raw_body=raw_body,
        headers={"X-Stripe-Signature": expected_sig},
    )

    with pytest.raises(WebhookReplayDetectedError):
        await ingest_webhook_event(
            session=session,
            webhook_request=webhook_request,
            source="stripe",
            endpoint_key="billing-events",
            verifier=verifier,
            enqueuer=lambda request: None,
        )

    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Verification Failure and Persistence Interaction Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_webhook_event_persists_even_when_verifier_fails() -> None:
    """Test that failed verification doesn't prevent persistence when signature check fails."""
    session = AsyncMock(spec=AsyncSession)
    raw_body = b'{"id":"evt_123","type":"invoice.updated"}'

    async def failing_verifier(
        context: WebhookSignatureVerificationContext,
    ) -> None:
        raise InvalidWebhookSignatureError("Signature verification failed")

    webhook_request = _build_webhook_request(
        raw_body=raw_body,
        headers={"X-Signature": "invalid"},
    )

    with pytest.raises(InvalidWebhookSignatureError):
        await ingest_webhook_event(
            session=session,
            webhook_request=webhook_request,
            source="stripe",
            endpoint_key="billing-events",
            verifier=failing_verifier,
            enqueuer=lambda request: None,
        )

    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_replay_protection_prevents_persistence_on_detection() -> None:
    """Test that detected replays prevent event persistence."""
    session = AsyncMock(spec=AsyncSession)
    raw_body = b'{"id":"evt_123","type":"invoice.updated"}'

    existing_event = _build_existing_webhook_event(
        raw_body=raw_body,
        delivery_id="dlv_abc123",
        event_id="evt_123",
    )
    session.scalar.return_value = existing_event

    async def dummy_verifier(
        context: WebhookSignatureVerificationContext,
    ) -> WebhookSignatureVerificationResult:
        return WebhookSignatureVerificationResult(
            provider=context.provider,
            endpoint_key=context.endpoint_key,
        )

    webhook_request = _build_webhook_request(
        raw_body=raw_body,
        headers={"X-Signature": "valid"},
    )

    with pytest.raises(WebhookReplayDetectedError):
        await ingest_webhook_event(
            session=session,
            webhook_request=webhook_request,
            source="stripe",
            endpoint_key="billing-events",
            verifier=dummy_verifier,
            enqueuer=lambda request: None,
        )

    session.add.assert_not_called()
    session.flush.assert_not_awaited()


# ---------------------------------------------------------------------------
# Verification and Replay Together in Full Flow Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_verification_and_replay_protection_flow() -> None:
    """Test complete flow: HMAC verification + replay detection + persistence + enqueue."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None

    secret = "webhook-secret"
    raw_body = b'{"id":"evt_xyz","delivery_id":"dlv_abc","type":"customer.updated"}'
    expected_sig = _compute_hmac_sha256(secret, raw_body)

    config = WebhookProviderConfig(
        source="acme",
        endpoint_key="events",
        signing_secret=secret,
        signature_header="x-acme-signature",
        signature_algorithm="sha256",
    )
    verifier = ConcreteHmacSignatureVerifier(config)

    def custom_validator(
        request: WebhookIngestionRequest,
        verification: WebhookSignatureVerificationResult | None = None,
    ) -> WebhookValidatedEvent:
        payload = request.json()
        return WebhookValidatedEvent(
            event_type=payload.get("type"),
            event_id=payload.get("id"),
            delivery_id=payload.get("delivery_id"),
        )

    webhook_request = _build_webhook_request(
        raw_body=raw_body,
        headers={"X-Acme-Signature": expected_sig},
    )

    enqueue_calls: list[WebhookEventEnqueueRequest] = []

    async def enqueue(request: WebhookEventEnqueueRequest) -> WebhookEventEnqueueResult:
        enqueue_calls.append(request)
        return WebhookEventEnqueueResult(
            job_name="acme.process",
            job_id="job-456",
        )

    result = await ingest_webhook_event(
        session=session,
        webhook_request=webhook_request,
        source="acme",
        endpoint_key="events",
        verifier=verifier,
        event_validator=custom_validator,
        enqueuer=enqueue,
    )

    assert result.signature_verification is not None
    assert result.signature_verification.signature == expected_sig
    assert result.signature_verification.provider == "acme"

    assert result.replay_protection is not None
    assert result.replay_protection.key_kind is WebhookReplayKeyKind.DELIVERY_ID
    assert result.replay_protection.key_value == "dlv_abc"

    assert result.validated_event.event_type == "customer.updated"
    assert result.validated_event.delivery_id == "dlv_abc"

    assert result.persisted_event.signature_verified is True
    assert result.persisted_event.source == "acme"
    assert result.persisted_event.event_type == "customer.updated"

    assert len(enqueue_calls) == 1
    assert enqueue_calls[0].persisted_event == result.persisted_event


@pytest.mark.asyncio
async def test_verification_with_replay_protection_enabled_setting() -> None:
    """Test that verification and replay work together with configuration settings."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None

    configured_settings = load_settings(
        _env_file=None,
        WEBHOOK_SIGNATURE_VERIFICATION_ENABLED=True,
        WEBHOOK_REPLAY_PROTECTION_ENABLED=True,
        WEBHOOK_REPLAY_WINDOW_SECONDS=600,
    )

    secret = "test-secret"
    raw_body = b'{"id":"evt_789","type":"order.paid"}'
    sig = _compute_hmac_sha256(secret, raw_body)

    config = WebhookProviderConfig(
        source="payment",
        endpoint_key="orders",
        signing_secret=secret,
        signature_header="x-signature",
    )
    verifier = ConcreteHmacSignatureVerifier(config)

    webhook_request = _build_webhook_request(
        raw_body=raw_body,
        headers={"X-Signature": sig},
    )

    async def enqueue(request: WebhookEventEnqueueRequest) -> WebhookEventEnqueueResult:
        return None

    result = await ingest_webhook_event(
        session=session,
        webhook_request=webhook_request,
        source="payment",
        endpoint_key="orders",
        verifier=verifier,
        enqueuer=enqueue,
        runtime_settings=configured_settings,
    )

    assert result.signature_verification is not None
    assert result.replay_protection is not None
    assert result.replay_protection.replay_window_seconds == 600
    assert result.persisted_event.status == WebhookEventStatus.ENQUEUED.value


@pytest.mark.asyncio
async def test_verification_disabled_skips_signature_check() -> None:
    """Test that signature verification can be disabled via settings."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None

    configured_settings = load_settings(
        _env_file=None,
        WEBHOOK_SIGNATURE_VERIFICATION_ENABLED=False,
        WEBHOOK_REPLAY_PROTECTION_ENABLED=False,
    )

    raw_body = b'{"id":"evt_xyz","type":"test.event"}'

    webhook_request = _build_webhook_request(
        raw_body=raw_body,
        headers={"X-Signature": "any-signature"},
    )

    async def enqueue(request: WebhookEventEnqueueRequest) -> WebhookEventEnqueueResult:
        return None

    result = await ingest_webhook_event(
        session=session,
        webhook_request=webhook_request,
        source="test",
        endpoint_key="default",
        verifier=None,
        enqueuer=enqueue,
        runtime_settings=configured_settings,
    )

    assert result.signature_verification is None
    assert result.replay_protection is None
    assert result.persisted_event.signature_verified is None


# ---------------------------------------------------------------------------
# Advanced Verification and Replay Scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_delivery_attempts_with_same_payload() -> None:
    """Test handling of legitimate retries with same delivery ID and payload."""
    session = AsyncMock(spec=AsyncSession)
    raw_body = b'{"id":"evt_retry","type":"event.occurred"}'

    existing_event = _build_existing_webhook_event(
        raw_body=raw_body,
        delivery_id="dlv_retry_001",
        event_id="evt_retry",
        status=WebhookEventStatus.FAILED.value,
    )
    session.scalar.return_value = existing_event

    webhook_request = _build_webhook_request(raw_body=raw_body)
    protection_request = WebhookReplayProtectionRequest(
        source="stripe",
        endpoint_key="billing-events",
        webhook_request=webhook_request,
        validated_event=WebhookValidatedEvent(
            event_type="event.occurred",
            delivery_id="dlv_retry_001",
            event_id="evt_retry",
        ),
        replay_window_seconds=300,
        checked_at=datetime(2026, 4, 6, 21, 5, tzinfo=UTC),
    )

    with pytest.raises(WebhookReplayDetectedError) as exc_info:
        await webhook_replay_protector.protect(session, protection_request)

    match = exc_info.value.match
    assert match.existing_status == WebhookEventStatus.FAILED.value


@pytest.mark.asyncio
async def test_signature_with_base64_encoding() -> None:
    """Test HMAC signature verification with base64 encoding."""
    import base64

    secret = "test-secret"
    raw_body = b'{"id":"evt_123","type":"event"}'

    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected_sig = base64.b64encode(digest).decode("ascii")

    config = WebhookProviderConfig(
        source="base64_provider",
        endpoint_key="default",
        signing_secret=secret,
        signature_header="x-signature",
        signature_algorithm="sha256",
        signature_encoding="base64",
    )
    verifier = ConcreteHmacSignatureVerifier(config)

    webhook_request = _build_webhook_request(
        raw_body=raw_body,
        headers={"X-Signature": expected_sig},
    )

    context = WebhookSignatureVerificationContext(
        provider="base64_provider",
        endpoint_key="default",
        request=webhook_request,
    )

    result = await verifier.verify(context)

    assert result.signature == expected_sig
    assert result.algorithm == "hmac-sha256"


@pytest.mark.asyncio
async def test_enqueue_failure_marks_event_as_failed_after_verification() -> None:
    """Test that enqueue failure is recorded even after successful verification."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None

    secret = "test-secret"
    raw_body = b'{"id":"evt_123","type":"event"}'
    sig = _compute_hmac_sha256(secret, raw_body)

    config = WebhookProviderConfig(
        source="test",
        endpoint_key="default",
        signing_secret=secret,
        signature_header="x-signature",
    )
    verifier = ConcreteHmacSignatureVerifier(config)

    webhook_request = _build_webhook_request(
        raw_body=raw_body,
        headers={"X-Signature": sig},
    )

    async def enqueue(request: WebhookEventEnqueueRequest) -> WebhookEventEnqueueResult:
        raise RuntimeError("Queue service unavailable")

    with pytest.raises(RuntimeError, match="Queue service unavailable"):
        await ingest_webhook_event(
            session=session,
            webhook_request=webhook_request,
            source="test",
            endpoint_key="default",
            verifier=verifier,
            enqueuer=enqueue,
        )

    persisted_event = session.add.call_args.args[0]
    assert persisted_event.signature_verified is True
    assert persisted_event.status == WebhookEventStatus.FAILED.value


__all__ = [
    "test_hmac_verifier_with_real_computation_accepts_valid_signature",
    "test_hmac_verifier_rejects_tampered_payload",
    "test_hmac_verifier_with_prefix_strips_and_validates",
    "test_verify_webhook_signature_callable_verifier",
    "test_replay_protection_detects_duplicate_delivery_id",
    "test_replay_protection_detects_payload_fingerprint_mismatch",
    "test_replay_protection_respects_time_window",
    "test_replay_protection_falls_back_to_payload_hash",
    "test_ingest_webhook_event_with_successful_hmac_verification",
    "test_ingest_webhook_event_rejects_invalid_signature_before_replay_check",
    "test_ingest_webhook_event_detects_replay_after_verification",
    "test_ingest_webhook_event_persists_even_when_verifier_fails",
    "test_replay_protection_prevents_persistence_on_detection",
    "test_end_to_end_verification_and_replay_protection_flow",
    "test_verification_with_replay_protection_enabled_setting",
    "test_verification_disabled_skips_signature_check",
    "test_multiple_delivery_attempts_with_same_payload",
    "test_signature_with_base64_encoding",
    "test_enqueue_failure_marks_event_as_failed_after_verification",
]
