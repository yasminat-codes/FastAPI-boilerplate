"""Regression tests for webhook provider extension points and example adapter."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.app.webhooks.ingestion import WebhookIngestionRequest, WebhookValidatedEvent
from src.app.webhooks.providers.base import (
    HmacWebhookVerifier,
    WebhookEventDispatchMap,
    WebhookEventNormalizer,
    WebhookProviderAdapter,
    WebhookProviderConfig,
    WebhookProviderVerifier,
    normalize_webhook_event,
)
from src.app.webhooks.providers.example import (
    EXAMPLE_PROVIDER_SOURCE,
    ExampleWebhookVerifier,
    build_example_dispatch_map,
    build_example_event_registry,
    build_example_provider_adapter,
    build_example_provider_config,
    normalize_example_event,
)
from src.app.webhooks.signatures import (
    InvalidWebhookSignatureError,
    MissingWebhookSignatureError,
    WebhookSignatureVerificationContext,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_request(
    raw_body: bytes = b'{"event": "order.created", "id": "evt_123", "data": {}}',
    content_type: str = "application/json",
    headers: dict[str, str] | None = None,
) -> WebhookIngestionRequest:
    """Build a minimal WebhookIngestionRequest for testing."""
    mock_request = MagicMock()
    all_headers = {"content-type": content_type}
    if headers:
        all_headers.update(headers)
    mock_request.headers = all_headers
    return WebhookIngestionRequest(
        request=mock_request,
        raw_body=raw_body,
        content_type=content_type,
    )


def _compute_hmac_sha256(secret: str, body: bytes) -> str:
    """Compute a hex HMAC-SHA256 digest."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# WebhookProviderConfig tests
# ---------------------------------------------------------------------------


class TestWebhookProviderConfig:
    def test_default_values(self) -> None:
        config = WebhookProviderConfig(source="test_provider")
        assert config.source == "test_provider"
        assert config.endpoint_key == "default"
        assert config.signing_secret is None
        assert config.signature_header is None
        assert config.signature_algorithm == "sha256"
        assert config.signature_encoding == "hex"
        assert config.signature_prefix == ""
        assert config.enabled is True

    def test_custom_values(self) -> None:
        config = WebhookProviderConfig(
            source="stripe",
            endpoint_key="payments",
            signing_secret="whsec_test123",
            signature_header="stripe-signature",
            signature_algorithm="sha256",
            signature_prefix="v1=",
            enabled=False,
        )
        assert config.source == "stripe"
        assert config.endpoint_key == "payments"
        assert config.signing_secret == "whsec_test123"
        assert config.enabled is False

    def test_frozen(self) -> None:
        config = WebhookProviderConfig(source="test")
        with pytest.raises(AttributeError):
            config.source = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# HmacWebhookVerifier tests
# ---------------------------------------------------------------------------


class TestHmacWebhookVerifier:
    def test_requires_signing_secret(self) -> None:
        config = WebhookProviderConfig(source="test", signature_header="x-sig")
        with pytest.raises(ValueError, match="signing_secret"):
            HmacWebhookVerifier(config)

    def test_requires_signature_header(self) -> None:
        config = WebhookProviderConfig(source="test", signing_secret="secret")
        with pytest.raises(ValueError, match="signature_header"):
            HmacWebhookVerifier(config)

    @pytest.mark.asyncio
    async def test_valid_signature(self) -> None:
        secret = "test-secret"
        body = b'{"event": "test"}'
        expected_sig = _compute_hmac_sha256(secret, body)

        config = WebhookProviderConfig(
            source="test",
            signing_secret=secret,
            signature_header="x-test-sig",
        )
        verifier = HmacWebhookVerifier(config)
        request = _make_mock_request(raw_body=body, headers={"x-test-sig": expected_sig})
        context = WebhookSignatureVerificationContext(
            provider="test",
            endpoint_key="default",
            request=request,
        )
        result = await verifier.verify(context)
        assert result.provider == "test"
        assert result.algorithm == "hmac-sha256"
        assert result.signature == expected_sig

    @pytest.mark.asyncio
    async def test_invalid_signature_raises(self) -> None:
        config = WebhookProviderConfig(
            source="test",
            signing_secret="real-secret",
            signature_header="x-test-sig",
        )
        verifier = HmacWebhookVerifier(config)
        request = _make_mock_request(headers={"x-test-sig": "bad-signature"})
        context = WebhookSignatureVerificationContext(
            provider="test",
            endpoint_key="default",
            request=request,
        )
        with pytest.raises(InvalidWebhookSignatureError):
            await verifier.verify(context)

    @pytest.mark.asyncio
    async def test_missing_signature_header_raises(self) -> None:
        config = WebhookProviderConfig(
            source="test",
            signing_secret="secret",
            signature_header="x-missing-header",
        )
        verifier = HmacWebhookVerifier(config)
        request = _make_mock_request()
        context = WebhookSignatureVerificationContext(
            provider="test",
            endpoint_key="default",
            request=request,
        )
        with pytest.raises(MissingWebhookSignatureError):
            await verifier.verify(context)

    @pytest.mark.asyncio
    async def test_signature_prefix_stripping(self) -> None:
        secret = "test-secret"
        body = b'{"event": "test"}'
        expected_sig = _compute_hmac_sha256(secret, body)

        config = WebhookProviderConfig(
            source="test",
            signing_secret=secret,
            signature_header="x-test-sig",
            signature_prefix="sha256=",
        )
        verifier = HmacWebhookVerifier(config)
        request = _make_mock_request(
            raw_body=body,
            headers={"x-test-sig": f"sha256={expected_sig}"},
        )
        context = WebhookSignatureVerificationContext(
            provider="test",
            endpoint_key="default",
            request=request,
        )
        result = await verifier.verify(context)
        assert result.signature == expected_sig

    def test_provider_property(self) -> None:
        config = WebhookProviderConfig(
            source="my_provider",
            signing_secret="s",
            signature_header="h",
        )
        verifier = HmacWebhookVerifier(config)
        assert verifier.provider == "my_provider"


# ---------------------------------------------------------------------------
# WebhookEventNormalizer / normalize_webhook_event tests
# ---------------------------------------------------------------------------


class TestNormalizeWebhookEvent:
    @pytest.mark.asyncio
    async def test_callable_normalizer(self) -> None:
        def my_normalizer(
            request: WebhookIngestionRequest,
            parsed: dict[str, Any],
        ) -> WebhookValidatedEvent:
            return WebhookValidatedEvent(
                event_type=parsed["type"],
                event_id=parsed.get("id"),
            )

        request = _make_mock_request()
        result = await normalize_webhook_event(
            my_normalizer,
            request=request,
            parsed_payload={"type": "test.event", "id": "123"},
        )
        assert result.event_type == "test.event"
        assert result.event_id == "123"

    @pytest.mark.asyncio
    async def test_async_callable_normalizer(self) -> None:
        async def my_normalizer(
            request: WebhookIngestionRequest,
            parsed: dict[str, Any],
        ) -> WebhookValidatedEvent:
            return WebhookValidatedEvent(event_type=parsed["type"])

        request = _make_mock_request()
        result = await normalize_webhook_event(
            my_normalizer,
            request=request,
            parsed_payload={"type": "async.event"},
        )
        assert result.event_type == "async.event"

    @pytest.mark.asyncio
    async def test_protocol_normalizer(self) -> None:
        class MyNormalizer:
            async def normalize(
                self,
                request: WebhookIngestionRequest,
                parsed_payload: dict[str, Any],
            ) -> WebhookValidatedEvent:
                return WebhookValidatedEvent(event_type=parsed_payload["type"])

        normalizer = MyNormalizer()
        assert isinstance(normalizer, WebhookEventNormalizer)
        request = _make_mock_request()
        result = await normalize_webhook_event(
            normalizer,
            request=request,
            parsed_payload={"type": "protocol.event"},
        )
        assert result.event_type == "protocol.event"


# ---------------------------------------------------------------------------
# WebhookEventDispatchMap tests
# ---------------------------------------------------------------------------


class TestWebhookEventDispatchMap:
    def test_register_and_get_handler(self) -> None:
        dispatch = WebhookEventDispatchMap(source="test")

        async def handler(**kwargs: Any) -> None:
            pass

        dispatch.register("order.created", handler, description="test handler")
        assert dispatch.has_handler("order.created")
        assert dispatch.get_handler("order.created") is handler

    def test_unregistered_returns_none(self) -> None:
        dispatch = WebhookEventDispatchMap(source="test")
        assert dispatch.get_handler("unknown.event") is None
        assert not dispatch.has_handler("unknown.event")

    def test_disabled_handler_returns_none(self) -> None:
        dispatch = WebhookEventDispatchMap(source="test")

        async def handler(**kwargs: Any) -> None:
            pass

        dispatch.register("order.created", handler, enabled=False)
        assert dispatch.get_handler("order.created") is None
        assert not dispatch.has_handler("order.created")

    def test_register_many(self) -> None:
        dispatch = WebhookEventDispatchMap(source="test")

        async def h1(**kwargs: Any) -> None:
            pass

        async def h2(**kwargs: Any) -> None:
            pass

        dispatch.register_many({"event.a": h1, "event.b": h2})
        assert dispatch.has_handler("event.a")
        assert dispatch.has_handler("event.b")

    def test_registered_types(self) -> None:
        dispatch = WebhookEventDispatchMap(source="test")

        async def handler(**kwargs: Any) -> None:
            pass

        dispatch.register("a", handler)
        dispatch.register("b", handler, enabled=False)
        dispatch.register("c", handler)

        assert dispatch.registered_types == frozenset({"a", "b", "c"})
        assert dispatch.enabled_types == frozenset({"a", "c"})

    def test_get_registration(self) -> None:
        dispatch = WebhookEventDispatchMap(source="test")

        async def handler(**kwargs: Any) -> None:
            pass

        dispatch.register("test.event", handler, description="my description")
        reg = dispatch.get_registration("test.event")
        assert reg is not None
        assert reg.event_type == "test.event"
        assert reg.description == "my description"
        assert reg.enabled is True

    def test_source_property(self) -> None:
        dispatch = WebhookEventDispatchMap(source="stripe")
        assert dispatch.source == "stripe"


# ---------------------------------------------------------------------------
# WebhookProviderAdapter tests
# ---------------------------------------------------------------------------


class TestWebhookProviderAdapter:
    def test_assembly(self) -> None:
        config = WebhookProviderConfig(source="test", endpoint_key="main")
        adapter = WebhookProviderAdapter(config=config)
        assert adapter.source == "test"
        assert adapter.endpoint_key == "main"
        assert adapter.enabled is True
        assert adapter.verifier is None
        assert adapter.normalizer is None
        assert adapter.dispatch is None

    def test_disabled(self) -> None:
        config = WebhookProviderConfig(source="test", enabled=False)
        adapter = WebhookProviderAdapter(config=config)
        assert adapter.enabled is False


# ---------------------------------------------------------------------------
# Example provider tests
# ---------------------------------------------------------------------------


class TestExampleProvider:
    def test_config_defaults(self) -> None:
        config = build_example_provider_config()
        assert config.source == EXAMPLE_PROVIDER_SOURCE
        assert config.signing_secret == "example-webhook-secret"
        assert config.signature_header == "x-example-signature"
        assert config.signature_prefix == "sha256="
        assert config.enabled is True

    def test_event_registry(self) -> None:
        registry = build_example_event_registry()
        assert registry.is_known("order.created")
        assert registry.is_known("order.updated")
        assert registry.is_known("order.cancelled")
        assert registry.is_known("customer.created")
        assert registry.is_known("customer.updated")
        assert not registry.is_known("unknown.event")
        assert registry.source == EXAMPLE_PROVIDER_SOURCE

    def test_dispatch_map(self) -> None:
        dispatch = build_example_dispatch_map()
        assert dispatch.source == EXAMPLE_PROVIDER_SOURCE
        assert dispatch.has_handler("order.created")
        assert dispatch.has_handler("order.updated")
        assert dispatch.has_handler("order.cancelled")
        assert dispatch.has_handler("customer.created")
        assert dispatch.has_handler("customer.updated")
        assert not dispatch.has_handler("unknown.event")

    def test_normalizer(self) -> None:
        request = _make_mock_request()
        payload = {
            "event": "order.created",
            "id": "evt_123",
            "delivery_id": "dlv_456",
            "data": {"amount": 100},
        }
        result = normalize_example_event(request, payload)
        assert result.event_type == "order.created"
        assert result.event_id == "evt_123"
        assert result.delivery_id == "dlv_456"
        assert result.normalized_payload is not None
        assert result.normalized_payload["data"]["amount"] == 100
        assert result.normalized_payload["provider"] == EXAMPLE_PROVIDER_SOURCE

    def test_normalizer_missing_event_raises(self) -> None:
        request = _make_mock_request()
        with pytest.raises(ValueError, match="event"):
            normalize_example_event(request, {"id": "123"})

    def test_normalizer_empty_event_raises(self) -> None:
        request = _make_mock_request()
        with pytest.raises(ValueError, match="event"):
            normalize_example_event(request, {"event": "   ", "id": "123"})

    def test_normalizer_optional_fields(self) -> None:
        request = _make_mock_request()
        result = normalize_example_event(request, {"event": "test.event"})
        assert result.event_type == "test.event"
        assert result.event_id is None
        assert result.delivery_id is None

    @pytest.mark.asyncio
    async def test_verifier_valid_signature(self) -> None:
        secret = "example-webhook-secret"
        body = b'{"event": "order.created"}'
        sig = _compute_hmac_sha256(secret, body)

        config = build_example_provider_config(signing_secret=secret)
        verifier = ExampleWebhookVerifier(config)
        request = _make_mock_request(
            raw_body=body,
            headers={"x-example-signature": f"sha256={sig}"},
        )
        context = WebhookSignatureVerificationContext(
            provider=EXAMPLE_PROVIDER_SOURCE,
            endpoint_key="default",
            request=request,
        )
        result = await verifier.verify(context)
        assert result.provider == EXAMPLE_PROVIDER_SOURCE
        assert result.algorithm == "hmac-sha256"

    @pytest.mark.asyncio
    async def test_verifier_invalid_signature(self) -> None:
        config = build_example_provider_config()
        verifier = ExampleWebhookVerifier(config)
        request = _make_mock_request(
            headers={"x-example-signature": "sha256=badhex"},
        )
        context = WebhookSignatureVerificationContext(
            provider=EXAMPLE_PROVIDER_SOURCE,
            endpoint_key="default",
            request=request,
        )
        with pytest.raises(InvalidWebhookSignatureError):
            await verifier.verify(context)

    def test_full_adapter_assembly(self) -> None:
        adapter = build_example_provider_adapter()
        assert adapter.source == EXAMPLE_PROVIDER_SOURCE
        assert adapter.endpoint_key == "default"
        assert adapter.enabled is True
        assert adapter.verifier is not None
        assert adapter.normalizer is not None
        assert adapter.dispatch is not None
        assert adapter.event_registry is not None

    def test_adapter_custom_secret(self) -> None:
        adapter = build_example_provider_adapter(
            signing_secret="custom-secret",
            endpoint_key="payments",
            enabled=False,
        )
        assert adapter.config.signing_secret == "custom-secret"
        assert adapter.endpoint_key == "payments"
        assert adapter.enabled is False


# ---------------------------------------------------------------------------
# Protocol conformance checks
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_hmac_verifier_is_provider_verifier(self) -> None:
        config = WebhookProviderConfig(
            source="test",
            signing_secret="s",
            signature_header="h",
        )
        verifier = HmacWebhookVerifier(config)
        assert isinstance(verifier, WebhookProviderVerifier)

    def test_example_verifier_is_provider_verifier(self) -> None:
        config = build_example_provider_config()
        verifier = ExampleWebhookVerifier(config)
        assert isinstance(verifier, WebhookProviderVerifier)


# ---------------------------------------------------------------------------
# Export surface tests
# ---------------------------------------------------------------------------


class TestExportSurface:
    def test_canonical_exports(self) -> None:
        from src.app.webhooks import (
            HmacWebhookVerifier as C1,
        )
        from src.app.webhooks import (
            WebhookEventDispatchMap as C2,
        )
        from src.app.webhooks import (
            WebhookEventNormalizer as C3,
        )
        from src.app.webhooks import (
            WebhookProviderAdapter as C4,
        )
        from src.app.webhooks import (
            WebhookProviderConfig as C5,
        )
        from src.app.webhooks import (
            WebhookProviderVerifier as C6,
        )
        from src.app.webhooks import (
            build_example_provider_adapter as C7,
        )
        from src.app.webhooks import (
            normalize_webhook_event as C8,
        )
        assert C1 is HmacWebhookVerifier
        assert C2 is WebhookEventDispatchMap
        assert C3 is WebhookEventNormalizer
        assert C4 is WebhookProviderAdapter
        assert C5 is WebhookProviderConfig
        assert C6 is WebhookProviderVerifier
        assert C7 is build_example_provider_adapter
        assert C8 is normalize_webhook_event

    def test_platform_exports(self) -> None:
        from src.app.platform.webhooks import (
            HmacWebhookVerifier as P1,
        )
        from src.app.platform.webhooks import (
            WebhookEventDispatchMap as P2,
        )
        from src.app.platform.webhooks import (
            WebhookProviderAdapter as P3,
        )
        from src.app.platform.webhooks import (
            WebhookProviderConfig as P4,
        )
        from src.app.platform.webhooks import (
            build_example_provider_adapter as P5,
        )
        assert P1 is HmacWebhookVerifier
        assert P2 is WebhookEventDispatchMap
        assert P3 is WebhookProviderAdapter
        assert P4 is WebhookProviderConfig
        assert P5 is build_example_provider_adapter

    def test_legacy_core_exports(self) -> None:
        from src.app.core.webhooks import (
            HmacWebhookVerifier as L1,
        )
        from src.app.core.webhooks import (
            WebhookEventDispatchMap as L2,
        )
        from src.app.core.webhooks import (
            WebhookProviderAdapter as L3,
        )
        from src.app.core.webhooks import (
            build_example_provider_adapter as L4,
        )
        assert L1 is HmacWebhookVerifier
        assert L2 is WebhookEventDispatchMap
        assert L3 is WebhookProviderAdapter
        assert L4 is build_example_provider_adapter
