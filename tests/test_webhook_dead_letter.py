"""Tests for webhook dead-letter behavior (Wave 5.2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.webhooks.dead_letter import (
    WEBHOOK_DEAD_LETTER_NAMESPACE,
    WebhookDeadLetterRequest,
    WebhookDeadLetterResult,
    WebhookDeadLetterStore,
    build_dead_letter_request_from_outcome,
    webhook_dead_letter_store,
)
from src.app.webhooks.processing import (
    WebhookProcessingAttempt,
    WebhookProcessingOutcome,
    WebhookProcessingStatus,
    WebhookRetryDecision,
)


class TestWebhookDeadLetterRequest:
    def test_dead_letter_key_format(self) -> None:
        request = WebhookDeadLetterRequest(
            webhook_event_id=42,
            source="stripe",
            endpoint_key="default",
            event_type="invoice.paid",
        )
        assert request.dead_letter_key == "stripe:default:42"

    def test_message_type_format(self) -> None:
        request = WebhookDeadLetterRequest(
            webhook_event_id=1,
            source="github",
            endpoint_key="ep",
            event_type="push",
        )
        assert request.message_type == "webhook.github.push"


class TestBuildDeadLetterRequestFromOutcome:
    def test_builds_from_outcome(self) -> None:
        event = MagicMock()
        event.id = 55
        event.source = "stripe"
        event.endpoint_key = "default"
        event.event_type = "invoice.paid"
        event.normalized_payload = {"amount": 100}
        event.payload_sha256 = "abc"

        attempt = WebhookProcessingAttempt(
            webhook_event_id=55, attempt_number=3, max_attempts=3
        )
        outcome = WebhookProcessingOutcome(
            attempt=attempt,
            status=WebhookProcessingStatus.FAILED_RETRYABLE,
            retry_decision=WebhookRetryDecision.DEAD_LETTER,
            error_message="timeout",
            error_category="TimeoutError",
        )

        result = build_dead_letter_request_from_outcome(event, outcome, correlation_id="c-1")
        assert result.webhook_event_id == 55
        assert result.failure_category == "TimeoutError"
        assert result.correlation_id == "c-1"
        assert result.attempt_count == 3
        assert result.payload_snapshot is not None
        assert result.payload_snapshot["normalized_payload"]["amount"] == 100
        assert result.failure_context is not None
        assert result.failure_context["final_status"] == "failed_retryable"


class TestWebhookDeadLetterStore:
    @pytest.mark.asyncio
    async def test_dead_letter_creates_record(self) -> None:
        session = AsyncMock()
        session.flush = AsyncMock()

        mock_record = MagicMock()
        mock_record.id = 77

        with patch(
            "src.app.webhooks.dead_letter.DeadLetterRecord",
            return_value=mock_record,
        ):
            store = WebhookDeadLetterStore()
            request = WebhookDeadLetterRequest(
                webhook_event_id=42,
                source="stripe",
                endpoint_key="default",
                event_type="invoice.paid",
                failure_category="TimeoutError",
                error_detail="connection timed out",
            )
            result = await store.dead_letter(session, request)
            assert result.dead_letter_record_id == 77
            assert result.webhook_event_id == 42
            session.add.assert_called_once_with(mock_record)
            session.flush.assert_awaited_once()


class TestWebhookDeadLetterResult:
    def test_as_processing_metadata(self) -> None:
        result = WebhookDeadLetterResult(
            dead_letter_record_id=77,
            webhook_event_id=42,
            dead_letter_key="stripe:default:42",
        )
        metadata = result.as_processing_metadata()
        assert "dead_letter" in metadata
        assert metadata["dead_letter"]["record_id"] == 77

    def test_namespace_constant(self) -> None:
        assert WEBHOOK_DEAD_LETTER_NAMESPACE == "webhooks"

    def test_singleton_store(self) -> None:
        assert webhook_dead_letter_store is not None


class TestDeadLetterExports:
    def test_canonical_surface(self) -> None:
        from src.app.webhooks import (
            WEBHOOK_DEAD_LETTER_NAMESPACE,
        )
        assert WEBHOOK_DEAD_LETTER_NAMESPACE == "webhooks"

    def test_platform_surface(self) -> None:
        from src.app.platform.webhooks import (
            WebhookDeadLetterStore,
        )
        assert WebhookDeadLetterStore is not None

    def test_legacy_surface(self) -> None:
        from src.app.core.webhooks import (
            webhook_dead_letter_store,
        )
        assert webhook_dead_letter_store is not None
