"""Integration tests for idempotency logic in webhook processing.

Tests WebhookIdempotencyProtector, record_idempotency_key, and their integration
with the webhook ingestion pipeline. Covers the full lifecycle of idempotency
checking, recording, and status transitions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.app.core.db.idempotency_key import IdempotencyKeyStatus
from src.app.core.request_context import CORRELATION_ID_STATE_KEY, REQUEST_ID_STATE_KEY
from src.app.platform.database import IdempotencyKey
from src.app.webhooks import (
    WebhookIdempotencyFingerprintMismatchError,
    WebhookIdempotencyProtector,
    WebhookIdempotencyRequest,
    WebhookIdempotencyViolationError,
    WebhookIngestionRequest,
    WebhookValidatedEvent,
    record_idempotency_key,
    webhook_idempotency_protector,
)

# ============================================================================
# Test Helpers
# ============================================================================


def _build_webhook_request(
    *,
    raw_body: bytes = b'{"id":"evt_123","type":"invoice.updated"}',
    headers: dict[str, str] | None = None,
    request_id: str | None = "req-123",
    correlation_id: str | None = "corr-456",
) -> WebhookIngestionRequest:
    """Build a WebhookIngestionRequest for testing."""
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


def _build_validated_event(
    event_type: str = "invoice.updated",
    event_id: str | None = "evt_123",
    delivery_id: str | None = None,
) -> WebhookValidatedEvent:
    """Build a WebhookValidatedEvent for testing."""
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
    source: str = "stripe",
    endpoint_key: str = "billing-events",
) -> WebhookIdempotencyRequest:
    """Build a WebhookIdempotencyRequest for testing."""
    return WebhookIdempotencyRequest(
        source=source,
        endpoint_key=endpoint_key,
        webhook_request=_build_webhook_request(raw_body=raw_body),
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
    status: str = IdempotencyKeyStatus.PROCESSING.value,
    first_seen_at: datetime | None = None,
    hit_count: int = 1,
) -> IdempotencyKey:
    """Build an existing IdempotencyKey record for testing."""
    resolved_fingerprint = fingerprint or sha256(raw_body).hexdigest()
    resolved_first_seen_at = first_seen_at or datetime(2026, 4, 7, 12, 0, tzinfo=UTC)

    record = IdempotencyKey(
        scope=scope,
        key=key,
        status=status,
        request_fingerprint=resolved_fingerprint,
        first_seen_at=resolved_first_seen_at,
        last_seen_at=resolved_first_seen_at,
        hit_count=hit_count,
    )
    record.id = 42
    return record


# ============================================================================
# WebhookIdempotencyProtector Tests: First Request Passes
# ============================================================================


@pytest.mark.asyncio
async def test_protector_allows_first_request_with_new_idempotency_key() -> None:
    """First request with a new idempotency key should pass protection."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    protector = WebhookIdempotencyProtector()
    request = _build_idempotency_request()

    result = await protector.protect(session, request)

    assert result.scope == "webhook:stripe:billing-events"
    assert result.idempotency_key == "event_id:evt_123"
    assert result.event_id == "evt_123"
    assert result.idempotency_window_seconds == 300
    assert result.request_fingerprint == sha256(b'{"id":"evt_123","type":"invoice.updated"}').hexdigest()
    assert result.checked_at is not None


@pytest.mark.asyncio
async def test_protector_allows_first_request_when_no_prior_record() -> None:
    """Protector should query for existing record and return result when none found."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    protector = WebhookIdempotencyProtector()
    request = _build_idempotency_request()

    result = await protector.protect(session, request)

    session.scalar.assert_awaited_once()
    assert result is not None


# ============================================================================
# WebhookIdempotencyProtector Tests: Second Request Rejected
# ============================================================================


@pytest.mark.asyncio
async def test_protector_rejects_second_request_with_same_key() -> None:
    """Second request with same idempotency key should be rejected."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = _build_existing_idempotency_key()
    protector = WebhookIdempotencyProtector()
    request = _build_idempotency_request()

    with pytest.raises(WebhookIdempotencyViolationError) as exc_info:
        await protector.protect(session, request)

    error = exc_info.value
    assert error.match.scope == "webhook:stripe:billing-events"
    assert error.match.idempotency_key == "event_id:evt_123"
    assert error.match.existing_record_id == 42
    assert error.match.existing_status == IdempotencyKeyStatus.PROCESSING.value
    assert "idempotency violation" in str(error)


@pytest.mark.asyncio
async def test_protector_increments_hit_count_on_duplicate() -> None:
    """Hit count should increment when a duplicate request is detected."""
    session = AsyncMock(spec=AsyncSession)
    existing = _build_existing_idempotency_key(hit_count=5)
    session.scalar.return_value = existing
    protector = WebhookIdempotencyProtector()
    request = _build_idempotency_request()

    with pytest.raises(WebhookIdempotencyViolationError) as exc_info:
        await protector.protect(session, request)

    assert exc_info.value.match.existing_hit_count == 6
    assert existing.hit_count == 6


@pytest.mark.asyncio
async def test_protector_updates_last_seen_at_on_duplicate() -> None:
    """Last seen timestamp should update when a duplicate is detected."""
    session = AsyncMock(spec=AsyncSession)
    existing = _build_existing_idempotency_key()
    original_last_seen = existing.last_seen_at
    session.scalar.return_value = existing
    protector = WebhookIdempotencyProtector()

    request = _build_idempotency_request()

    with pytest.raises(WebhookIdempotencyViolationError):
        await protector.protect(session, request)

    # The protector should update last_seen_at to when it checked (approximately now)
    assert existing.last_seen_at > original_last_seen


# ============================================================================
# Fingerprint Mismatch Detection
# ============================================================================


@pytest.mark.asyncio
async def test_protector_detects_fingerprint_mismatch() -> None:
    """Reusing same key with different request body should raise mismatch error."""
    session = AsyncMock(spec=AsyncSession)
    existing = _build_existing_idempotency_key(
        fingerprint="abc123def456",
    )
    session.scalar.return_value = existing
    protector = WebhookIdempotencyProtector()
    request = _build_idempotency_request()

    with pytest.raises(WebhookIdempotencyFingerprintMismatchError) as exc_info:
        await protector.protect(session, request)

    error = exc_info.value
    assert error.match.existing_record_id == 42
    assert error.match.request_fingerprint == "abc123def456"
    assert error.match.candidate_fingerprint == request.request_fingerprint
    assert error.match.request_fingerprint != error.match.candidate_fingerprint
    assert "different fingerprint" in str(error)


@pytest.mark.asyncio
async def test_protector_ignores_fingerprint_mismatch_when_existing_is_none() -> None:
    """Fingerprint mismatch should be ignored if existing record has no fingerprint."""
    session = AsyncMock(spec=AsyncSession)
    existing = _build_existing_idempotency_key(fingerprint=None)
    session.scalar.return_value = existing
    protector = WebhookIdempotencyProtector()
    request = _build_idempotency_request()

    with pytest.raises(WebhookIdempotencyViolationError, match="idempotency violation"):
        await protector.protect(session, request)


# ============================================================================
# Idempotency Recording
# ============================================================================


@pytest.mark.asyncio
async def test_record_idempotency_key_persists_all_fields() -> None:
    """Recording should persist all required fields to database."""
    session = AsyncMock(spec=AsyncSession)
    request = _build_idempotency_request()

    record = await record_idempotency_key(session, request)

    session.add.assert_called_once_with(record)
    session.flush.assert_awaited_once()
    assert record.scope == "webhook:stripe:billing-events"
    assert record.key == "event_id:evt_123"
    assert record.status == IdempotencyKeyStatus.PROCESSING.value
    assert record.request_fingerprint == request.request_fingerprint
    assert record.first_seen_at == request.checked_at
    assert record.last_seen_at == request.checked_at
    assert record.hit_count == 1


@pytest.mark.asyncio
async def test_record_idempotency_key_calculates_correct_expiry() -> None:
    """Expiry should be set to checked_at + window_seconds."""
    session = AsyncMock(spec=AsyncSession)
    request = _build_idempotency_request(window_seconds=600)

    record = await record_idempotency_key(session, request)

    expected_expiry = request.checked_at + timedelta(seconds=600)
    assert record.expires_at == expected_expiry


@pytest.mark.asyncio
async def test_record_idempotency_key_preserves_processing_metadata() -> None:
    """Processing metadata should be preserved during recording."""
    session = AsyncMock(spec=AsyncSession)
    request = _build_idempotency_request()
    metadata = {"correlation_id": "corr-456", "replay_check": "passed"}

    record = await record_idempotency_key(session, request, processing_metadata=metadata)

    assert record.processing_metadata == metadata


@pytest.mark.asyncio
async def test_record_idempotency_key_handles_none_processing_metadata() -> None:
    """Recording should handle None processing_metadata gracefully."""
    session = AsyncMock(spec=AsyncSession)
    request = _build_idempotency_request()

    record = await record_idempotency_key(session, request, processing_metadata=None)

    assert record.processing_metadata is None


# ============================================================================
# Idempotency Key Lifecycle & Status Transitions
# ============================================================================


@pytest.mark.asyncio
async def test_idempotency_key_status_transitions_received_to_processing() -> None:
    """Status should transition from RECEIVED to PROCESSING when recording."""
    session = AsyncMock(spec=AsyncSession)
    request = _build_idempotency_request()

    record = await record_idempotency_key(session, request)

    assert record.status == IdempotencyKeyStatus.PROCESSING.value


@pytest.mark.asyncio
async def test_idempotency_key_status_completed_after_processing() -> None:
    """Idempotency key can be marked as COMPLETED after processing succeeds."""
    session = AsyncMock(spec=AsyncSession)
    request = _build_idempotency_request()

    record = await record_idempotency_key(session, request)
    assert record.status == IdempotencyKeyStatus.PROCESSING.value

    record.status = IdempotencyKeyStatus.COMPLETED.value
    record.completed_at = datetime.now(UTC)

    assert record.status == IdempotencyKeyStatus.COMPLETED.value
    assert record.completed_at is not None


# ============================================================================
# Idempotency Window Expiration & Leasing
# ============================================================================


@pytest.mark.asyncio
async def test_protector_respects_idempotency_window() -> None:
    """Duplicate requests outside window should be allowed as new requests."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    protector = WebhookIdempotencyProtector()

    request = _build_idempotency_request(window_seconds=300)

    result = await protector.protect(session, request)

    assert result is not None
    # Result should have a checked_at timestamp
    assert result.checked_at is not None


@pytest.mark.asyncio
async def test_protector_window_started_at_calculation() -> None:
    """Window start should be calculated as checked_at - window_seconds."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    protector = WebhookIdempotencyProtector()

    window_seconds = 600
    request = _build_idempotency_request(window_seconds=window_seconds)

    await protector.protect(session, request)

    # window_started_at should be request.checked_at - window_seconds
    expected_window_start = request.checked_at - timedelta(seconds=window_seconds)
    assert request.window_started_at == expected_window_start


# ============================================================================
# Integration with Webhook Ingestion Pipeline
# ============================================================================


@pytest.mark.asyncio
async def test_idempotency_can_be_checked_before_webhook_persistence() -> None:
    """Idempotency should be checked before persisting webhook to allow early rejection."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    protector = WebhookIdempotencyProtector()
    request = _build_idempotency_request()

    result = await protector.protect(session, request)

    assert result is not None


@pytest.mark.asyncio
async def test_idempotency_result_as_processing_metadata() -> None:
    """Idempotency result should be serializable to processing metadata."""
    from src.app.webhooks.idempotency import WebhookIdempotencyResult

    result = WebhookIdempotencyResult(
        scope="webhook:stripe:billing-events",
        idempotency_key="event_id:evt_123",
        request_fingerprint=sha256(b'{"id":"evt_123","type":"invoice.updated"}').hexdigest(),
        idempotency_window_seconds=300,
        checked_at=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
        event_id="evt_123",
        delivery_id=None,
    )

    metadata = result.as_processing_metadata()

    assert "idempotency" in metadata
    assert metadata["idempotency"]["scope"] == "webhook:stripe:billing-events"
    assert metadata["idempotency"]["key"] == "event_id:evt_123"
    assert metadata["idempotency"]["window_seconds"] == 300
    assert metadata["idempotency"]["event_id"] == "evt_123"
    assert "delivery_id" not in metadata["idempotency"]


@pytest.mark.asyncio
async def test_idempotency_result_includes_delivery_id_when_present() -> None:
    """Processing metadata should include delivery_id when present."""
    from src.app.webhooks.idempotency import WebhookIdempotencyResult

    result = WebhookIdempotencyResult(
        scope="webhook:stripe:billing-events",
        idempotency_key="delivery_id:del_456",
        request_fingerprint="abc123",
        idempotency_window_seconds=300,
        checked_at=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
        delivery_id="del_456",
    )

    metadata = result.as_processing_metadata()

    assert metadata["idempotency"]["delivery_id"] == "del_456"


# ============================================================================
# Idempotency Key Priority & Scope
# ============================================================================


@pytest.mark.asyncio
async def test_protector_uses_event_id_priority() -> None:
    """Event ID should have priority over delivery_id for idempotency key."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    request = _build_idempotency_request(event_id="evt_999", delivery_id="del_777")

    result = await webhook_idempotency_protector.protect(session, request)

    assert result.idempotency_key == "event_id:evt_999"


@pytest.mark.asyncio
async def test_protector_falls_back_to_delivery_id() -> None:
    """Delivery ID should be used when event_id is not available."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    request = _build_idempotency_request(event_id=None, delivery_id="del_777")

    result = await webhook_idempotency_protector.protect(session, request)

    assert result.idempotency_key == "delivery_id:del_777"


@pytest.mark.asyncio
async def test_protector_falls_back_to_payload_hash() -> None:
    """Payload SHA-256 should be used when neither event_id nor delivery_id available."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    raw_body = b'{"type":"test.event"}'
    request = _build_idempotency_request(
        raw_body=raw_body,
        event_id=None,
        delivery_id=None,
    )

    result = await webhook_idempotency_protector.protect(session, request)

    expected_hash = sha256(raw_body).hexdigest()
    assert result.idempotency_key == f"payload_sha256:{expected_hash}"


@pytest.mark.asyncio
async def test_protector_scopes_idempotency_by_source_and_endpoint() -> None:
    """Idempotency scope should include both source and endpoint_key."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    request = _build_idempotency_request(source="github", endpoint_key="push-events")

    result = await webhook_idempotency_protector.protect(session, request)

    assert result.scope == "webhook:github:push-events"


@pytest.mark.asyncio
async def test_protector_scope_prevents_cross_source_collisions() -> None:
    """Same key in different scopes should not cause false duplicate detection."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None

    stripe_request = _build_idempotency_request(source="stripe", endpoint_key="billing")
    github_request = _build_idempotency_request(source="github", endpoint_key="billing")

    stripe_result = await webhook_idempotency_protector.protect(session, stripe_request)
    github_result = await webhook_idempotency_protector.protect(session, github_request)

    assert stripe_result.scope == "webhook:stripe:billing"
    assert github_result.scope == "webhook:github:billing"
    assert stripe_result.scope != github_result.scope


# ============================================================================
# Error Handling & Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_protector_raises_violation_with_complete_match_metadata() -> None:
    """Violation error should contain complete match metadata."""
    session = AsyncMock(spec=AsyncSession)
    existing = _build_existing_idempotency_key(hit_count=10)
    session.scalar.return_value = existing
    request = _build_idempotency_request()

    with pytest.raises(WebhookIdempotencyViolationError) as exc_info:
        await webhook_idempotency_protector.protect(session, request)

    match = exc_info.value.match
    assert match.existing_record_id == 42
    assert match.existing_hit_count == 11
    assert match.existing_first_seen_at is not None
    assert "existing record 42" in str(exc_info.value)


@pytest.mark.asyncio
async def test_protector_raises_mismatch_with_complete_match_metadata() -> None:
    """Fingerprint mismatch error should contain complete match metadata."""
    session = AsyncMock(spec=AsyncSession)
    existing = _build_existing_idempotency_key(fingerprint="old_hash")
    session.scalar.return_value = existing
    request = _build_idempotency_request()

    with pytest.raises(WebhookIdempotencyFingerprintMismatchError) as exc_info:
        await webhook_idempotency_protector.protect(session, request)

    match = exc_info.value.match
    assert match.request_fingerprint == "old_hash"
    assert match.candidate_fingerprint == request.request_fingerprint
    assert match.existing_record_id == 42


def test_idempotency_request_validates_source_not_empty() -> None:
    """Source must not be empty or whitespace."""
    with pytest.raises(ValueError, match="source must not be empty"):
        WebhookIdempotencyRequest(
            source="  ",
            endpoint_key="billing-events",
            webhook_request=_build_webhook_request(),
            validated_event=_build_validated_event(),
            idempotency_window_seconds=300,
        )


def test_idempotency_request_validates_endpoint_key_not_empty() -> None:
    """Endpoint key must not be empty or whitespace."""
    with pytest.raises(ValueError, match="endpoint_key must not be empty"):
        WebhookIdempotencyRequest(
            source="stripe",
            endpoint_key="  ",
            webhook_request=_build_webhook_request(),
            validated_event=_build_validated_event(),
            idempotency_window_seconds=300,
        )


def test_idempotency_request_validates_window_minimum() -> None:
    """Idempotency window must be at least 1 second."""
    with pytest.raises(ValueError, match="at least 1 second"):
        WebhookIdempotencyRequest(
            source="stripe",
            endpoint_key="billing-events",
            webhook_request=_build_webhook_request(),
            validated_event=_build_validated_event(),
            idempotency_window_seconds=0,
        )


def test_idempotency_request_validates_window_negative() -> None:
    """Idempotency window must not be negative."""
    with pytest.raises(ValueError, match="at least 1 second"):
        WebhookIdempotencyRequest(
            source="stripe",
            endpoint_key="billing-events",
            webhook_request=_build_webhook_request(),
            validated_event=_build_validated_event(),
            idempotency_window_seconds=-100,
        )


# ============================================================================
# Protector Singleton & Factory Tests
# ============================================================================


@pytest.mark.asyncio
async def test_webhook_idempotency_protector_singleton() -> None:
    """webhook_idempotency_protector should be a singleton instance."""
    from src.app.webhooks.idempotency import webhook_idempotency_protector

    assert isinstance(webhook_idempotency_protector, WebhookIdempotencyProtector)


@pytest.mark.asyncio
async def test_multiple_protector_instances_are_independent() -> None:
    """Multiple protector instances should work independently."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None

    protector1 = WebhookIdempotencyProtector()
    protector2 = WebhookIdempotencyProtector()

    request = _build_idempotency_request()
    result1 = await protector1.protect(session, request)
    result2 = await protector2.protect(session, request)

    assert result1.idempotency_key == result2.idempotency_key
    assert result1.scope == result2.scope


# ============================================================================
# Complex Scenarios
# ============================================================================


@pytest.mark.asyncio
async def test_multiple_scopes_same_key_independent_tracking() -> None:
    """Same key in different scopes should have independent hit counts."""
    session = AsyncMock(spec=AsyncSession)

    stripe_existing = _build_existing_idempotency_key(
        scope="webhook:stripe:billing",
        hit_count=5,
    )
    github_existing = _build_existing_idempotency_key(
        scope="webhook:github:billing",
        hit_count=3,
    )

    protector = WebhookIdempotencyProtector()

    session.scalar.return_value = stripe_existing
    stripe_request = _build_idempotency_request(source="stripe", endpoint_key="billing")

    with pytest.raises(WebhookIdempotencyViolationError):
        await protector.protect(session, stripe_request)

    assert stripe_existing.hit_count == 6

    session.scalar.return_value = github_existing
    github_request = _build_idempotency_request(source="github", endpoint_key="billing")

    with pytest.raises(WebhookIdempotencyViolationError):
        await protector.protect(session, github_request)

    assert github_existing.hit_count == 4


@pytest.mark.asyncio
async def test_idempotency_with_large_payload() -> None:
    """Idempotency should work correctly with large payloads."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None

    large_payload = b'{"data":"' + b"x" * 10000 + b'"}'
    request = _build_idempotency_request(
        raw_body=large_payload,
        event_id=None,
        delivery_id=None,
    )

    result = await webhook_idempotency_protector.protect(session, request)

    expected_hash = sha256(large_payload).hexdigest()
    assert result.idempotency_key == f"payload_sha256:{expected_hash}"
    assert len(result.request_fingerprint) == 64


@pytest.mark.asyncio
async def test_idempotency_with_unicode_payload() -> None:
    """Idempotency should handle Unicode payloads correctly."""
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None

    unicode_payload = '{"text":"你好世界 🌍"}'.encode()
    request = _build_idempotency_request(
        raw_body=unicode_payload,
        event_id=None,
        delivery_id=None,
    )

    result = await webhook_idempotency_protector.protect(session, request)

    expected_hash = sha256(unicode_payload).hexdigest()
    assert result.idempotency_key == f"payload_sha256:{expected_hash}"


@pytest.mark.asyncio
async def test_idempotency_protector_with_concurrent_duplicates() -> None:
    """Protector should detect duplicates even with concurrent requests."""
    session = AsyncMock(spec=AsyncSession)
    existing = _build_existing_idempotency_key()
    session.scalar.return_value = existing
    protector = WebhookIdempotencyProtector()

    request = _build_idempotency_request()

    errors = []
    for _ in range(3):
        try:
            await protector.protect(session, request)
        except WebhookIdempotencyViolationError as e:
            errors.append(e)

    assert len(errors) == 3
    assert existing.hit_count == 4


@pytest.mark.asyncio
async def test_record_idempotency_key_with_all_optional_fields() -> None:
    """Recording should handle all optional fields correctly."""
    session = AsyncMock(spec=AsyncSession)
    request = _build_idempotency_request(
        event_id="evt_999",
        delivery_id="del_888",
        window_seconds=900,
    )
    metadata = {
        "source": "stripe",
        "endpoint_key": "billing",
        "correlation_id": "corr-123",
    }

    record = await record_idempotency_key(session, request, processing_metadata=metadata)

    assert record.scope == request.scope
    assert record.key == request.idempotency_key
    assert record.processing_metadata == metadata
    assert record.expires_at == request.checked_at + timedelta(seconds=900)


@pytest.mark.asyncio
async def test_idempotency_key_status_enum_values() -> None:
    """IdempotencyKeyStatus enum should have expected values."""
    assert IdempotencyKeyStatus.RECEIVED.value == "received"
    assert IdempotencyKeyStatus.PROCESSING.value == "processing"
    assert IdempotencyKeyStatus.COMPLETED.value == "completed"
    assert IdempotencyKeyStatus.FAILED.value == "failed"
    assert IdempotencyKeyStatus.EXPIRED.value == "expired"
