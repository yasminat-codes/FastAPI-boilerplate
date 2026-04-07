from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.app.webhooks import (
    MalformedPayloadError,
    PoisonPayloadError,
    UnknownEventTypeError,
    WebhookDuplicateEventError,
    WebhookEventTypeRegistry,
    WebhookPoisonDetectionRequest,
    WebhookPoisonDetectionResult,
    WebhookValidationErrorKind,
    validate_webhook_content_type,
    validate_webhook_event_type,
    validate_webhook_payload_json,
)


class TestValidateWebhookContentType:
    def test_allows_application_json(self) -> None:
        result = validate_webhook_content_type("application/json")
        assert result == "application/json"

    def test_allows_application_json_with_charset(self) -> None:
        result = validate_webhook_content_type("application/json; charset=utf-8")
        assert result == "application/json"

    def test_rejects_unsupported_content_type(self) -> None:
        with pytest.raises(MalformedPayloadError, match="Unsupported webhook content type"):
            validate_webhook_content_type("text/xml")

    def test_returns_none_when_content_type_is_none(self) -> None:
        assert validate_webhook_content_type(None) is None

    def test_returns_none_when_content_type_is_empty(self) -> None:
        assert validate_webhook_content_type("") is None

    def test_accepts_custom_allowed_types(self) -> None:
        result = validate_webhook_content_type(
            "text/xml",
            allowed_media_types={"text/xml", "application/json"},
        )
        assert result == "text/xml"

    def test_error_includes_details(self) -> None:
        with pytest.raises(MalformedPayloadError) as exc_info:
            validate_webhook_content_type("text/html")
        assert exc_info.value.kind == WebhookValidationErrorKind.MALFORMED_CONTENT_TYPE
        assert exc_info.value.details["media_type"] == "text/html"


class TestValidateWebhookPayloadJson:
    def test_parses_valid_json_object(self) -> None:
        result = validate_webhook_payload_json(b'{"type":"test.event"}')
        assert result == {"type": "test.event"}

    def test_rejects_empty_body(self) -> None:
        with pytest.raises(MalformedPayloadError) as exc_info:
            validate_webhook_payload_json(b"")
        assert exc_info.value.kind == WebhookValidationErrorKind.EMPTY_PAYLOAD

    def test_rejects_invalid_json(self) -> None:
        with pytest.raises(MalformedPayloadError) as exc_info:
            validate_webhook_payload_json(b"not json at all")
        assert exc_info.value.kind == WebhookValidationErrorKind.INVALID_JSON

    def test_rejects_non_object_json_when_required(self) -> None:
        with pytest.raises(MalformedPayloadError) as exc_info:
            validate_webhook_payload_json(b'["an", "array"]')
        assert exc_info.value.kind == WebhookValidationErrorKind.INVALID_JSON_STRUCTURE

    def test_allows_non_object_json_when_not_required(self) -> None:
        result = validate_webhook_payload_json(
            b'["an", "array"]',
            require_object=False,
        )
        assert result == ["an", "array"]

    def test_includes_payload_size_in_error_details(self) -> None:
        with pytest.raises(MalformedPayloadError) as exc_info:
            validate_webhook_payload_json(b"invalid")
        assert exc_info.value.details["payload_size_bytes"] == 7


class TestValidateWebhookEventType:
    def test_accepts_valid_event_type(self) -> None:
        result = validate_webhook_event_type("invoice.updated")
        assert result == "invoice.updated"

    def test_strips_whitespace(self) -> None:
        result = validate_webhook_event_type("  invoice.updated  ")
        assert result == "invoice.updated"

    def test_rejects_none(self) -> None:
        with pytest.raises(MalformedPayloadError) as exc_info:
            validate_webhook_event_type(None)
        assert exc_info.value.kind == WebhookValidationErrorKind.MISSING_EVENT_TYPE

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(MalformedPayloadError):
            validate_webhook_event_type("")

    def test_rejects_whitespace_only(self) -> None:
        with pytest.raises(MalformedPayloadError):
            validate_webhook_event_type("   ")

    def test_rejects_unknown_type_when_allowlist_provided(self) -> None:
        with pytest.raises(UnknownEventTypeError) as exc_info:
            validate_webhook_event_type(
                "unknown.event",
                allowed_event_types={"invoice.created", "invoice.updated"},
            )
        assert exc_info.value.event_type == "unknown.event"
        assert exc_info.value.kind == WebhookValidationErrorKind.UNKNOWN_EVENT_TYPE

    def test_accepts_known_type_from_allowlist(self) -> None:
        result = validate_webhook_event_type(
            "invoice.created",
            allowed_event_types={"invoice.created", "invoice.updated"},
        )
        assert result == "invoice.created"

    def test_passes_source_and_endpoint_to_error(self) -> None:
        with pytest.raises(UnknownEventTypeError) as exc_info:
            validate_webhook_event_type(
                "bad.type",
                allowed_event_types={"good.type"},
                source="stripe",
                endpoint_key="billing",
            )
        assert exc_info.value.source == "stripe"
        assert exc_info.value.endpoint_key == "billing"


class TestWebhookEventTypeRegistry:
    def test_register_and_lookup(self) -> None:
        registry = WebhookEventTypeRegistry(source="stripe")
        registry.register("invoice.created", description="Invoice created")
        assert registry.is_known("invoice.created")
        assert not registry.is_known("invoice.deleted")

    def test_register_many_from_set(self) -> None:
        registry = WebhookEventTypeRegistry(source="stripe")
        registry.register_many({"invoice.created", "invoice.updated"})
        assert registry.is_known("invoice.created")
        assert registry.is_known("invoice.updated")

    def test_register_many_from_mapping(self) -> None:
        registry = WebhookEventTypeRegistry(source="stripe")
        registry.register_many({
            "invoice.created": "Invoice created",
            "invoice.updated": "Invoice updated",
        })
        reg = registry.get("invoice.created")
        assert reg is not None
        assert reg.description == "Invoice created"

    def test_strict_mode_rejects_unknown(self) -> None:
        registry = WebhookEventTypeRegistry(source="stripe", strict=True)
        registry.register("invoice.created")
        with pytest.raises(UnknownEventTypeError):
            registry.validate("unknown.type")

    def test_non_strict_mode_passes_unknown(self) -> None:
        registry = WebhookEventTypeRegistry(source="stripe", strict=False)
        registry.register("invoice.created")
        result = registry.validate("unknown.type")
        assert result == "unknown.type"

    def test_validate_rejects_empty_event_type(self) -> None:
        registry = WebhookEventTypeRegistry(source="stripe")
        with pytest.raises(MalformedPayloadError):
            registry.validate("")

    def test_enabled_types_excludes_disabled(self) -> None:
        registry = WebhookEventTypeRegistry(source="stripe")
        registry.register("invoice.created", enabled=True)
        registry.register("invoice.deleted", enabled=False)
        assert "invoice.created" in registry.enabled_types
        assert "invoice.deleted" not in registry.enabled_types

    def test_is_enabled(self) -> None:
        registry = WebhookEventTypeRegistry(source="stripe")
        registry.register("invoice.created", enabled=True)
        registry.register("invoice.deleted", enabled=False)
        assert registry.is_enabled("invoice.created")
        assert not registry.is_enabled("invoice.deleted")
        assert not registry.is_enabled("nonexistent")

    def test_known_types_returns_frozenset(self) -> None:
        registry = WebhookEventTypeRegistry(source="stripe")
        registry.register("a")
        registry.register("b")
        assert registry.known_types == frozenset({"a", "b"})


class TestWebhookDuplicateEventError:
    def test_error_message_format(self) -> None:
        error = WebhookDuplicateEventError(
            source="stripe",
            endpoint_key="billing",
            event_id="evt_123",
            existing_event_id=42,
            existing_status="processed",
        )
        assert "stripe/billing" in str(error)
        assert "evt_123" in str(error)

    def test_metadata_includes_all_fields(self) -> None:
        error = WebhookDuplicateEventError(
            source="stripe",
            endpoint_key="billing",
            event_id="evt_123",
            delivery_id="del_456",
            existing_event_id=42,
            existing_status="processed",
        )
        metadata = error.as_processing_metadata()
        assert "duplicate_detection" in metadata
        dup = metadata["duplicate_detection"]
        assert dup["source"] == "stripe"
        assert dup["event_id"] == "evt_123"
        assert dup["delivery_id"] == "del_456"
        assert dup["existing_event_id"] == 42


class TestPoisonPayloadError:
    def test_error_includes_failure_details(self) -> None:
        error = PoisonPayloadError(
            failure_count=5,
            max_failures=5,
            source="stripe",
            event_type="invoice.updated",
        )
        assert error.failure_count == 5
        assert error.max_failures == 5
        assert error.kind == WebhookValidationErrorKind.POISON_PAYLOAD


class TestWebhookPoisonDetectionResult:
    def test_metadata_format(self) -> None:
        result = WebhookPoisonDetectionResult(
            is_poison=True,
            failure_count=6,
            max_failures=5,
            source="stripe",
            endpoint_key="billing",
            event_type="invoice.updated",
            payload_sha256="abc123",
            checked_at=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
        )
        metadata = result.as_processing_metadata()
        assert metadata["poison_detection"]["is_poison"] is True
        assert metadata["poison_detection"]["failure_count"] == 6
        assert metadata["poison_detection"]["max_failures"] == 5


class TestWebhookPoisonDetectionRequest:
    def test_default_max_failures(self) -> None:
        request = WebhookPoisonDetectionRequest(
            source="stripe",
            endpoint_key="billing",
            event_type="invoice.updated",
            payload_sha256="abc123",
        )
        assert request.max_failures == 5

    def test_custom_max_failures(self) -> None:
        request = WebhookPoisonDetectionRequest(
            source="stripe",
            endpoint_key="billing",
            event_type="invoice.updated",
            payload_sha256="abc123",
            max_failures=10,
        )
        assert request.max_failures == 10


class TestWebhookPayloadValidationError:
    def test_base_error_metadata(self) -> None:
        from src.app.webhooks.validation import WebhookPayloadValidationError

        error = WebhookPayloadValidationError(
            WebhookValidationErrorKind.INVALID_JSON,
            "bad payload",
            source="stripe",
            endpoint_key="billing",
            details={"extra": "info"},
        )
        metadata = error.as_processing_metadata()
        assert metadata["validation_error"]["kind"] == "invalid_json"
        assert metadata["validation_error"]["source"] == "stripe"
        assert metadata["validation_error"]["details"]["extra"] == "info"
