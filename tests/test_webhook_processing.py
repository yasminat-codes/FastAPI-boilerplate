"""Tests for webhook operational processing contracts (Wave 5.2)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.app.webhooks.processing import (
    WebhookAcknowledgementPolicy,
    WebhookAcknowledgementResult,
    WebhookProcessingAttempt,
    WebhookProcessingJobRequest,
    WebhookProcessingStatus,
    WebhookRetryDecision,
    build_payload_snapshot,
    build_processing_job_request,
    build_success_outcome,
    build_webhook_ack_response,
    decide_retry,
)

# ---------------------------------------------------------------------------
# Acknowledgement strategy tests
# ---------------------------------------------------------------------------


class TestWebhookAcknowledgementPolicy:
    def test_immediate_is_default(self) -> None:
        result = WebhookAcknowledgementResult()
        assert result.policy is WebhookAcknowledgementPolicy.IMMEDIATE

    def test_response_body_includes_status(self) -> None:
        result = WebhookAcknowledgementResult(status="accepted", event_id=42, correlation_id="corr-1")
        body = result.as_response_body()
        assert body["status"] == "accepted"
        assert body["event_id"] == 42
        assert body["correlation_id"] == "corr-1"

    def test_response_body_omits_none_fields(self) -> None:
        result = WebhookAcknowledgementResult(status="accepted")
        body = result.as_response_body()
        assert "event_id" not in body
        assert "correlation_id" not in body

    def test_build_ack_response_from_event(self) -> None:
        event = MagicMock()
        event.id = 99
        result = build_webhook_ack_response(event, correlation_id="c-1")
        assert result.event_id == 99
        assert result.correlation_id == "c-1"
        assert result.status == "accepted"


# ---------------------------------------------------------------------------
# Payload snapshot tests
# ---------------------------------------------------------------------------


class TestWebhookPayloadSnapshot:
    def test_snapshot_from_event(self) -> None:
        event = MagicMock()
        event.raw_payload = '{"type":"test"}'
        event.normalized_payload = {"type": "test"}
        event.payload_content_type = "application/json"
        event.payload_sha256 = "abc123"
        event.payload_size_bytes = 15
        snapshot = build_payload_snapshot(event)
        assert snapshot.has_raw_payload is True
        assert snapshot.has_normalized_payload is True
        assert snapshot.raw_payload == '{"type":"test"}'
        assert snapshot.content_type == "application/json"

    def test_snapshot_without_raw_payload(self) -> None:
        event = MagicMock()
        event.raw_payload = None
        event.normalized_payload = None
        event.payload_content_type = None
        event.payload_sha256 = None
        event.payload_size_bytes = None
        snapshot = build_payload_snapshot(event)
        assert snapshot.has_raw_payload is False
        assert snapshot.has_normalized_payload is False


# ---------------------------------------------------------------------------
# Job offload tests
# ---------------------------------------------------------------------------


class TestWebhookProcessingJobRequest:
    def test_as_job_payload_roundtrip(self) -> None:
        request = WebhookProcessingJobRequest(
            webhook_event_id=42,
            source="stripe",
            endpoint_key="default",
            event_type="invoice.paid",
            correlation_id="corr-1",
            delivery_id="del-1",
            event_id="evt-1",
            payload_sha256="abc",
            processing_metadata={"key": "val"},
        )
        payload = request.as_job_payload()
        restored = WebhookProcessingJobRequest.from_job_payload(payload)
        assert restored.webhook_event_id == 42
        assert restored.source == "stripe"
        assert restored.event_type == "invoice.paid"
        assert restored.correlation_id == "corr-1"
        assert restored.processing_metadata == {"key": "val"}

    def test_as_job_payload_omits_none(self) -> None:
        request = WebhookProcessingJobRequest(
            webhook_event_id=1,
            source="test",
            endpoint_key="default",
            event_type="event.type",
        )
        payload = request.as_job_payload()
        assert "correlation_id" not in payload
        assert "delivery_id" not in payload

    def test_build_from_event(self) -> None:
        event = MagicMock()
        event.id = 55
        event.source = "provider"
        event.endpoint_key = "ep"
        event.event_type = "type.a"
        event.delivery_id = "d-1"
        event.event_id = "e-1"
        event.payload_sha256 = "sha"
        result = build_processing_job_request(event, correlation_id="c-1")
        assert result.webhook_event_id == 55
        assert result.correlation_id == "c-1"


# ---------------------------------------------------------------------------
# Retry-safe processing tests
# ---------------------------------------------------------------------------


class TestWebhookProcessingAttempt:
    def test_valid_attempt(self) -> None:
        attempt = WebhookProcessingAttempt(
            webhook_event_id=1, attempt_number=1, max_attempts=3
        )
        assert attempt.is_final_attempt is False
        assert attempt.remaining_attempts == 2

    def test_final_attempt(self) -> None:
        attempt = WebhookProcessingAttempt(
            webhook_event_id=1, attempt_number=3, max_attempts=3
        )
        assert attempt.is_final_attempt is True
        assert attempt.remaining_attempts == 0

    def test_invalid_attempt_number(self) -> None:
        with pytest.raises(ValueError, match="attempt_number"):
            WebhookProcessingAttempt(webhook_event_id=1, attempt_number=0, max_attempts=3)

    def test_invalid_max_attempts(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            WebhookProcessingAttempt(webhook_event_id=1, attempt_number=1, max_attempts=0)


class TestDecideRetry:
    def _attempt(self, *, number: int = 1, max_attempts: int = 3) -> WebhookProcessingAttempt:
        return WebhookProcessingAttempt(
            webhook_event_id=1, attempt_number=number, max_attempts=max_attempts
        )

    def test_retryable_error_on_non_final_attempt(self) -> None:
        outcome = decide_retry(self._attempt(number=1), ValueError("transient"))
        assert outcome.status is WebhookProcessingStatus.FAILED_RETRYABLE
        assert outcome.retry_decision is WebhookRetryDecision.RETRY
        assert outcome.should_retry is True

    def test_retryable_error_on_final_attempt_dead_letters(self) -> None:
        outcome = decide_retry(self._attempt(number=3), ValueError("transient"))
        assert outcome.retry_decision is WebhookRetryDecision.DEAD_LETTER
        assert outcome.should_dead_letter is True

    def test_permanent_error_dead_letters_immediately(self) -> None:
        outcome = decide_retry(
            self._attempt(number=1),
            TypeError("permanent"),
            permanent_errors=(TypeError,),
        )
        assert outcome.status is WebhookProcessingStatus.FAILED_PERMANENT
        assert outcome.retry_decision is WebhookRetryDecision.DEAD_LETTER

    def test_unknown_error_dead_letters_when_retryable_specified(self) -> None:
        outcome = decide_retry(
            self._attempt(number=1),
            RuntimeError("unknown"),
            retryable_errors=(ValueError,),
        )
        assert outcome.retry_decision is WebhookRetryDecision.DEAD_LETTER

    def test_success_outcome(self) -> None:
        attempt = self._attempt(number=1)
        outcome = build_success_outcome(attempt)
        assert outcome.succeeded is True
        assert outcome.retry_decision is None

    def test_outcome_as_processing_metadata(self) -> None:
        attempt = self._attempt(number=2, max_attempts=3)
        outcome = decide_retry(attempt, ValueError("fail"))
        metadata = outcome.as_processing_metadata()
        assert "processing" in metadata
        assert metadata["processing"]["attempt_number"] == 2
        assert metadata["processing"]["max_attempts"] == 3


# ---------------------------------------------------------------------------
# Export surface verification
# ---------------------------------------------------------------------------


class TestProcessingExports:
    def test_canonical_surface_exports(self) -> None:
        from src.app.webhooks import (
            WebhookAcknowledgementPolicy,
            decide_retry,
        )
        assert WebhookAcknowledgementPolicy is not None
        assert decide_retry is not None

    def test_platform_surface_exports(self) -> None:
        from src.app.platform.webhooks import (
            WebhookProcessingStatus,
        )
        assert WebhookProcessingStatus is not None

    def test_legacy_surface_exports(self) -> None:
        from src.app.core.webhooks import (
            WebhookRetryDecision,
        )
        assert WebhookRetryDecision is not None
