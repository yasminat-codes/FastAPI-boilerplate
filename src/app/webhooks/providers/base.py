"""Reusable base classes and contracts for provider-specific webhook adapters.

Template adopters subclass these bases when adding a new webhook integration
provider.  The interfaces cover the three provider-specific concerns that sit
on top of the template-owned generic pipeline:

* **Signature verification** — ``WebhookProviderVerifier`` provides an HMAC
  helper and a structured configuration contract so providers that use
  HMAC-SHA256 (or similar) only need to supply header names and the secret.
* **Event normalization** — ``WebhookEventNormalizer`` transforms a
  provider-specific payload into the template's ``WebhookValidatedEvent``
  contract so downstream processing is provider-agnostic.
* **Event dispatch** — ``WebhookEventDispatchMap`` routes validated events to
  handler callables keyed by event type so each provider can define its own
  dispatch table without touching the core pipeline.

All three interfaces are Protocol-based so they can be implemented as plain
classes, dataclasses, or even module-level functions where the full class is
overkill.
"""

from __future__ import annotations

import hashlib
import hmac
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, cast, runtime_checkable

from ..ingestion import WebhookIngestionRequest, WebhookValidatedEvent
from ..signatures import (
    InvalidWebhookSignatureError,
    WebhookSignatureVerificationContext,
    WebhookSignatureVerificationResult,
)

# ---------------------------------------------------------------------------
# Provider configuration contract
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class WebhookProviderConfig:
    """Shared configuration contract for a webhook integration provider.

    Every provider adapter needs at least a ``source`` identifier and an
    ``endpoint_key`` for scoping.  Fields like ``signing_secret`` and
    ``signature_header`` are used by the HMAC verification base when the
    provider uses a standard HMAC-based signing scheme.

    Template adopters extend this with provider-specific fields (API version,
    account ID, etc.) by creating a provider-specific dataclass that includes
    a ``WebhookProviderConfig`` or duplicates the relevant fields.
    """

    source: str
    endpoint_key: str = "default"
    signing_secret: str | None = None
    signature_header: str | None = None
    signature_algorithm: str = "sha256"
    signature_encoding: str = "hex"
    signature_prefix: str = ""
    timestamp_header: str | None = None
    max_age_seconds: int | None = None
    enabled: bool = True


# ---------------------------------------------------------------------------
# Signature verification base
# ---------------------------------------------------------------------------


@runtime_checkable
class WebhookProviderVerifier(Protocol):
    """Protocol for provider-specific webhook signature verifiers.

    This extends the template's ``WebhookSignatureVerifier`` contract with an
    explicit ``provider`` property so the adapter can be identified at runtime
    without inspecting the verification context.
    """

    @property
    def provider(self) -> str: ...

    async def verify(
        self,
        context: WebhookSignatureVerificationContext,
    ) -> WebhookSignatureVerificationResult: ...


class HmacWebhookVerifier:
    """Reusable HMAC-based webhook signature verifier.

    Many webhook providers (Stripe, GitHub, Shopify, etc.) sign payloads with
    HMAC-SHA256 and send the signature in a single header.  This base class
    provides the boilerplate so a provider adapter only needs to supply the
    header name, secret, and optional prefix/encoding overrides.

    Subclass and override ``_extract_signature`` or ``_build_signing_input``
    when a provider has a non-standard signing scheme (e.g. Stripe's
    timestamp-prefixed payload format).
    """

    def __init__(self, config: WebhookProviderConfig) -> None:
        if config.signing_secret is None:
            raise ValueError(
                f"WebhookProviderConfig for {config.source!r} must include a signing_secret "
                "when using HmacWebhookVerifier"
            )
        if config.signature_header is None:
            raise ValueError(
                f"WebhookProviderConfig for {config.source!r} must include a signature_header "
                "when using HmacWebhookVerifier"
            )
        self._config = config

    @property
    def provider(self) -> str:
        return self._config.source

    async def verify(
        self,
        context: WebhookSignatureVerificationContext,
    ) -> WebhookSignatureVerificationResult:
        """Verify an HMAC signature against the raw request body."""

        received_signature = self._extract_signature(context)
        signing_input = self._build_signing_input(context)
        expected_signature = self._compute_signature(signing_input)

        if not hmac.compare_digest(received_signature, expected_signature):
            raise InvalidWebhookSignatureError(
                f"Webhook signature mismatch for provider {self._config.source!r}"
            )

        return WebhookSignatureVerificationResult(
            provider=self._config.source,
            endpoint_key=self._config.endpoint_key,
            signature=received_signature,
            algorithm=f"hmac-{self._config.signature_algorithm}",
        )

    def _extract_signature(
        self,
        context: WebhookSignatureVerificationContext,
    ) -> str:
        """Extract the provider signature from the request headers.

        Override this method when the provider sends the signature in a
        non-standard location or format.
        """

        assert self._config.signature_header is not None
        raw_value = context.get_header(self._config.signature_header, required=True)
        assert raw_value is not None

        signature = raw_value.strip()
        if self._config.signature_prefix and signature.startswith(self._config.signature_prefix):
            signature = signature[len(self._config.signature_prefix) :]

        return signature.strip()

    def _build_signing_input(
        self,
        context: WebhookSignatureVerificationContext,
    ) -> bytes:
        """Build the byte string that was signed by the provider.

        Override this method when the provider prepends a timestamp or other
        data to the raw body before signing.
        """

        return context.raw_body

    def _compute_signature(self, signing_input: bytes) -> str:
        """Compute the expected HMAC signature for the given input."""

        assert self._config.signing_secret is not None
        digest = hmac.new(
            self._config.signing_secret.encode("utf-8"),
            signing_input,
            getattr(hashlib, self._config.signature_algorithm),
        )

        if self._config.signature_encoding == "hex":
            return digest.hexdigest()
        if self._config.signature_encoding == "base64":
            import base64

            return base64.b64encode(digest.digest()).decode("ascii")

        return digest.hexdigest()


# ---------------------------------------------------------------------------
# Event normalization
# ---------------------------------------------------------------------------


@runtime_checkable
class WebhookEventNormalizer(Protocol):
    """Transform a provider-specific webhook payload into a normalized event.

    The normalizer sits between raw payload parsing and the template's
    ``WebhookValidatedEvent`` contract.  It is responsible for:

    * Extracting the provider's event type string.
    * Extracting event and delivery identifiers.
    * Producing a ``normalized_payload`` dict that downstream processing can
      consume without knowing the provider's wire format.

    Implement this as a class with a ``normalize`` method or as a plain
    callable that accepts the same arguments.
    """

    async def normalize(
        self,
        request: WebhookIngestionRequest,
        parsed_payload: dict[str, Any],
    ) -> WebhookValidatedEvent: ...


WebhookEventNormalizerCallable = Callable[
    [WebhookIngestionRequest, dict[str, Any]],
    WebhookValidatedEvent | Awaitable[WebhookValidatedEvent],
]
WebhookEventNormalizerLike = WebhookEventNormalizer | WebhookEventNormalizerCallable


async def normalize_webhook_event(
    normalizer: WebhookEventNormalizerLike,
    *,
    request: WebhookIngestionRequest,
    parsed_payload: dict[str, Any],
) -> WebhookValidatedEvent:
    """Run a provider-specific normalizer to produce a validated event."""

    raw_result: Any
    if isinstance(normalizer, WebhookEventNormalizer):
        raw_result = normalizer.normalize(request, parsed_payload)
    else:
        raw_result = normalizer(request, parsed_payload)

    if inspect.isawaitable(raw_result):
        return cast(WebhookValidatedEvent, await raw_result)

    return cast(WebhookValidatedEvent, raw_result)


# ---------------------------------------------------------------------------
# Event dispatch map
# ---------------------------------------------------------------------------

WebhookEventHandler = Callable[..., Any]


@dataclass(slots=True, frozen=True)
class WebhookEventHandlerRegistration:
    """Registration entry in a provider's dispatch map."""

    event_type: str
    handler: WebhookEventHandler
    description: str = ""
    enabled: bool = True


class WebhookEventDispatchMap:
    """Provider-specific dispatch table mapping event types to handler callables.

    Template adopters create one dispatch map per provider and use it to route
    validated webhook events to the correct business-logic handler after the
    canonical intake pipeline has persisted and enqueued the event.

    The dispatch map works alongside ``WebhookEventTypeRegistry`` from the
    validation module: the registry controls which event types are accepted
    during intake, while the dispatch map controls which handler runs during
    background processing.

    Usage::

        dispatch = WebhookEventDispatchMap(source="stripe")
        dispatch.register("invoice.paid", handle_invoice_paid)
        dispatch.register("customer.created", handle_customer_created)

        handler = dispatch.get_handler("invoice.paid")
        if handler is not None:
            await handler(job_request)
    """

    def __init__(self, *, source: str) -> None:
        self.source = source
        self._handlers: dict[str, WebhookEventHandlerRegistration] = {}

    def register(
        self,
        event_type: str,
        handler: WebhookEventHandler,
        *,
        description: str = "",
        enabled: bool = True,
    ) -> WebhookEventHandlerRegistration:
        """Register a handler for a specific event type."""

        registration = WebhookEventHandlerRegistration(
            event_type=event_type,
            handler=handler,
            description=description,
            enabled=enabled,
        )
        self._handlers[event_type] = registration
        return registration

    def register_many(
        self,
        handlers: Mapping[str, WebhookEventHandler],
    ) -> None:
        """Register multiple event type handlers at once."""

        for event_type, handler in handlers.items():
            self.register(event_type, handler)

    def get_handler(self, event_type: str) -> WebhookEventHandler | None:
        """Look up the handler for an event type, or None if unregistered."""

        registration = self._handlers.get(event_type)
        if registration is None or not registration.enabled:
            return None
        return registration.handler

    def get_registration(self, event_type: str) -> WebhookEventHandlerRegistration | None:
        """Look up the full registration entry for an event type."""

        return self._handlers.get(event_type)

    @property
    def registered_types(self) -> frozenset[str]:
        """Return all registered event type strings."""

        return frozenset(self._handlers)

    @property
    def enabled_types(self) -> frozenset[str]:
        """Return event types that have an enabled handler."""

        return frozenset(
            event_type for event_type, reg in self._handlers.items() if reg.enabled
        )

    def has_handler(self, event_type: str) -> bool:
        """Return True if an enabled handler is registered for this event type."""

        registration = self._handlers.get(event_type)
        return registration is not None and registration.enabled


# ---------------------------------------------------------------------------
# Provider adapter assembly
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WebhookProviderAdapter:
    """Assembly point for a complete provider webhook integration.

    This groups the provider's verifier, normalizer, event registry, and
    dispatch map into a single object so route setup and worker dispatch can
    access all provider-specific concerns through one handle.

    Template adopters create one adapter per provider and register it with
    the application's webhook configuration.

    Usage::

        adapter = WebhookProviderAdapter(
            config=WebhookProviderConfig(source="stripe", ...),
            verifier=StripeWebhookVerifier(config),
            normalizer=stripe_normalize_event,
            dispatch=stripe_dispatch,
            event_registry=stripe_event_registry,
        )
    """

    config: WebhookProviderConfig
    verifier: WebhookProviderVerifier | None = None
    normalizer: WebhookEventNormalizerLike | None = None
    dispatch: WebhookEventDispatchMap | None = None
    event_registry: Any | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def source(self) -> str:
        return self.config.source

    @property
    def endpoint_key(self) -> str:
        return self.config.endpoint_key

    @property
    def enabled(self) -> bool:
        return self.config.enabled


__all__ = [
    "HmacWebhookVerifier",
    "WebhookEventDispatchMap",
    "WebhookEventHandler",
    "WebhookEventHandlerRegistration",
    "WebhookEventNormalizer",
    "WebhookEventNormalizerCallable",
    "WebhookEventNormalizerLike",
    "WebhookProviderAdapter",
    "WebhookProviderConfig",
    "WebhookProviderVerifier",
    "normalize_webhook_event",
]
