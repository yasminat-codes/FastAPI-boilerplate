"""Placeholder example webhook provider adapter.

This module demonstrates how to wire a provider-specific webhook integration
into the template without coupling to any real external service.  Template
adopters should use this as a reference when adding a new provider.

The example provider:

* Verifies HMAC-SHA256 signatures using a shared secret and the
  ``X-Example-Signature`` header.
* Normalizes payloads that follow a ``{"event": "<type>", "id": "<id>",
  "data": {...}}`` structure into the template's ``WebhookValidatedEvent``.
* Dispatches events through a simple type-to-handler map.

Copy this file, rename the ``example`` references to your provider, and
replace the placeholder logic with real provider contracts.
"""

from __future__ import annotations

from typing import Any

from ..ingestion import WebhookIngestionRequest, WebhookValidatedEvent
from ..validation import WebhookEventTypeRegistry
from .base import (
    HmacWebhookVerifier,
    WebhookEventDispatchMap,
    WebhookProviderAdapter,
    WebhookProviderConfig,
)

# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

EXAMPLE_PROVIDER_SOURCE = "example_provider"
"""Canonical source identifier for the example webhook provider."""


def build_example_provider_config(
    *,
    signing_secret: str = "example-webhook-secret",
    endpoint_key: str = "default",
    enabled: bool = True,
) -> WebhookProviderConfig:
    """Build a ``WebhookProviderConfig`` for the example provider.

    In a real provider, the signing secret would come from environment
    variables or a secret manager — never from a hardcoded default.
    """

    return WebhookProviderConfig(
        source=EXAMPLE_PROVIDER_SOURCE,
        endpoint_key=endpoint_key,
        signing_secret=signing_secret,
        signature_header="x-example-signature",
        signature_algorithm="sha256",
        signature_encoding="hex",
        signature_prefix="sha256=",
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# Signature verifier
# ---------------------------------------------------------------------------


class ExampleWebhookVerifier(HmacWebhookVerifier):
    """HMAC-SHA256 signature verifier for the example provider.

    The example provider signs the raw request body with HMAC-SHA256 and
    sends the hex digest in the ``X-Example-Signature`` header prefixed with
    ``sha256=``.  The ``HmacWebhookVerifier`` base handles the comparison
    automatically given the configuration above.

    For providers with non-standard signing (e.g. timestamp-prefixed input),
    override ``_build_signing_input`` or ``_extract_signature``.
    """

    pass


# ---------------------------------------------------------------------------
# Event normalizer
# ---------------------------------------------------------------------------


def normalize_example_event(
    request: WebhookIngestionRequest,
    parsed_payload: dict[str, Any],
) -> WebhookValidatedEvent:
    """Normalize an example provider payload into the template event contract.

    Expected payload shape::

        {
            "event": "order.created",
            "id": "evt_abc123",
            "delivery_id": "dlv_xyz789",
            "data": { ... }
        }

    Real provider normalizers should validate required fields, handle
    version differences, and extract provider-specific metadata into the
    ``processing_metadata`` field.
    """

    event_type = parsed_payload.get("event")
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("Example provider payload must include a non-empty 'event' field")

    raw_event_id = parsed_payload.get("id")
    event_id = str(raw_event_id).strip() if raw_event_id is not None else None

    raw_delivery_id = parsed_payload.get("delivery_id")
    delivery_id = str(raw_delivery_id).strip() if raw_delivery_id is not None else None

    data = parsed_payload.get("data")
    normalized_payload: dict[str, Any] = {
        "event_type": event_type.strip(),
        "provider": EXAMPLE_PROVIDER_SOURCE,
    }
    if data is not None:
        normalized_payload["data"] = data

    return WebhookValidatedEvent(
        event_type=event_type.strip(),
        event_id=event_id or None,
        delivery_id=delivery_id or None,
        normalized_payload=normalized_payload,
        processing_metadata={"provider": EXAMPLE_PROVIDER_SOURCE},
    )


# ---------------------------------------------------------------------------
# Event type registry
# ---------------------------------------------------------------------------


def build_example_event_registry() -> WebhookEventTypeRegistry:
    """Build a ``WebhookEventTypeRegistry`` for the example provider.

    The registry defines which event types this provider can send.  Unknown
    event types are rejected during intake when the registry runs in strict
    mode.
    """

    registry = WebhookEventTypeRegistry(source=EXAMPLE_PROVIDER_SOURCE, strict=True)
    registry.register_many(
        {
            "order.created": "Fired when a new order is placed.",
            "order.updated": "Fired when an existing order changes.",
            "order.cancelled": "Fired when an order is cancelled.",
            "customer.created": "Fired when a new customer account is created.",
            "customer.updated": "Fired when a customer profile changes.",
        }
    )
    return registry


# ---------------------------------------------------------------------------
# Event dispatch map
# ---------------------------------------------------------------------------


async def _handle_example_order_created(**kwargs: Any) -> None:
    """Placeholder handler for order.created events."""


async def _handle_example_order_updated(**kwargs: Any) -> None:
    """Placeholder handler for order.updated events."""


async def _handle_example_order_cancelled(**kwargs: Any) -> None:
    """Placeholder handler for order.cancelled events."""


async def _handle_example_customer_created(**kwargs: Any) -> None:
    """Placeholder handler for customer.created events."""


async def _handle_example_customer_updated(**kwargs: Any) -> None:
    """Placeholder handler for customer.updated events."""


def build_example_dispatch_map() -> WebhookEventDispatchMap:
    """Build a ``WebhookEventDispatchMap`` for the example provider.

    The dispatch map routes validated events to handler functions during
    background processing.  Handlers are registered by event type string.
    """

    dispatch = WebhookEventDispatchMap(source=EXAMPLE_PROVIDER_SOURCE)
    dispatch.register(
        "order.created",
        _handle_example_order_created,
        description="Process new orders.",
    )
    dispatch.register(
        "order.updated",
        _handle_example_order_updated,
        description="Process order changes.",
    )
    dispatch.register(
        "order.cancelled",
        _handle_example_order_cancelled,
        description="Process order cancellations.",
    )
    dispatch.register(
        "customer.created",
        _handle_example_customer_created,
        description="Process new customer accounts.",
    )
    dispatch.register(
        "customer.updated",
        _handle_example_customer_updated,
        description="Process customer profile changes.",
    )
    return dispatch


# ---------------------------------------------------------------------------
# Full adapter assembly
# ---------------------------------------------------------------------------


def build_example_provider_adapter(
    *,
    signing_secret: str = "example-webhook-secret",
    endpoint_key: str = "default",
    enabled: bool = True,
) -> WebhookProviderAdapter:
    """Build a fully assembled ``WebhookProviderAdapter`` for the example provider.

    This is the single entry point that wires together the verifier, normalizer,
    event registry, and dispatch map for the example provider.  Real provider
    modules should expose a similar ``build_<provider>_adapter`` function.
    """

    config = build_example_provider_config(
        signing_secret=signing_secret,
        endpoint_key=endpoint_key,
        enabled=enabled,
    )
    verifier = ExampleWebhookVerifier(config)
    event_registry = build_example_event_registry()
    dispatch = build_example_dispatch_map()

    return WebhookProviderAdapter(
        config=config,
        verifier=verifier,
        normalizer=normalize_example_event,
        dispatch=dispatch,
        event_registry=event_registry,
    )


__all__ = [
    "EXAMPLE_PROVIDER_SOURCE",
    "ExampleWebhookVerifier",
    "build_example_dispatch_map",
    "build_example_event_registry",
    "build_example_provider_adapter",
    "build_example_provider_config",
    "normalize_example_event",
]
