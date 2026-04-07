"""Extension point for provider-specific webhook verifiers, normalizers, and dispatch adapters.

This package contains:

* ``base`` — Reusable base classes and Protocols for building provider adapters.
* ``example`` — A placeholder provider that demonstrates the full adapter pattern
  without coupling to any real external service.

Template adopters add new providers by creating a module in this package
(e.g. ``stripe.py``, ``github.py``) that follows the same structure as
the ``example`` module.
"""

from .base import (
    HmacWebhookVerifier,
    WebhookEventDispatchMap,
    WebhookEventHandler,
    WebhookEventHandlerRegistration,
    WebhookEventNormalizer,
    WebhookEventNormalizerCallable,
    WebhookEventNormalizerLike,
    WebhookProviderAdapter,
    WebhookProviderConfig,
    WebhookProviderVerifier,
    normalize_webhook_event,
)
from .example import (
    EXAMPLE_PROVIDER_SOURCE,
    ExampleWebhookVerifier,
    build_example_dispatch_map,
    build_example_event_registry,
    build_example_provider_adapter,
    build_example_provider_config,
    normalize_example_event,
)

__all__ = [
    "EXAMPLE_PROVIDER_SOURCE",
    "ExampleWebhookVerifier",
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
    "build_example_dispatch_map",
    "build_example_event_registry",
    "build_example_provider_adapter",
    "build_example_provider_config",
    "normalize_example_event",
    "normalize_webhook_event",
]
