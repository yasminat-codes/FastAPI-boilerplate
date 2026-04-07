# Adding a new webhook provider

This guide walks through the process of adding a new webhook integration
provider to the template.  The example uses a fictional "Acme" provider, but
the same pattern applies to any real service (Stripe, GitHub, Shopify, etc.).

## Overview

Every provider adapter needs up to four pieces, all in a single module under
`src/app/webhooks/providers/`:

1. **Configuration** — A `WebhookProviderConfig` with the provider's source
   name, signing secret, and signature header.
2. **Signature verifier** — A class that checks the provider's signature
   against the raw request body.
3. **Event normalizer** — A function or class that transforms the provider's
   payload into the template's `WebhookValidatedEvent`.
4. **Dispatch map** — A `WebhookEventDispatchMap` that routes event types to
   handler functions.

The template ships an example adapter in
`src/app/webhooks/providers/example.py` that demonstrates all four pieces.
Use it as a starting reference.

## Step 1: Create the provider module

Create `src/app/webhooks/providers/acme.py`:

```python
"""Acme webhook provider adapter."""

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

ACME_SOURCE = "acme"
```

## Step 2: Define the configuration

```python
def build_acme_config(
    *,
    signing_secret: str,
    endpoint_key: str = "default",
) -> WebhookProviderConfig:
    return WebhookProviderConfig(
        source=ACME_SOURCE,
        endpoint_key=endpoint_key,
        signing_secret=signing_secret,
        signature_header="x-acme-signature",
        signature_algorithm="sha256",
        signature_encoding="hex",
        signature_prefix="sha256=",
    )
```

The `signing_secret` should come from an environment variable or secret
manager in production.  Never hardcode it.

## Step 3: Implement signature verification

If the provider uses standard HMAC signing, subclass `HmacWebhookVerifier`:

```python
class AcmeWebhookVerifier(HmacWebhookVerifier):
    """Acme signs payloads with HMAC-SHA256 in the X-Acme-Signature header."""
    pass
```

The base class handles HMAC computation, prefix stripping, and constant-time
comparison automatically based on the configuration.

For non-standard signing (e.g. timestamp-prefixed input like Stripe), override
`_build_signing_input`:

```python
class AcmeWebhookVerifier(HmacWebhookVerifier):
    def _build_signing_input(self, context):
        timestamp = context.get_header("x-acme-timestamp", required=True)
        return f"{timestamp}.".encode() + context.raw_body
```

If the provider does not sign payloads at all, skip the verifier and pass
`verifier=None` when assembling the adapter.

## Step 4: Implement event normalization

Write a normalizer that extracts the event type, identifiers, and a
normalized payload from the provider's specific JSON structure:

```python
def normalize_acme_event(
    request: WebhookIngestionRequest,
    parsed_payload: dict[str, Any],
) -> WebhookValidatedEvent:
    # Acme sends: {"type": "invoice.paid", "id": "evt_...", "object": {...}}
    event_type = parsed_payload.get("type")
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("Acme payload must include a non-empty 'type' field")

    return WebhookValidatedEvent(
        event_type=event_type.strip(),
        event_id=parsed_payload.get("id"),
        normalized_payload={
            "event_type": event_type,
            "provider": ACME_SOURCE,
            "data": parsed_payload.get("object"),
        },
        processing_metadata={"provider": ACME_SOURCE},
    )
```

The normalizer can be a plain function (as above) or a class that implements
the `WebhookEventNormalizer` protocol.

## Step 5: Register known event types

```python
def build_acme_event_registry() -> WebhookEventTypeRegistry:
    registry = WebhookEventTypeRegistry(source=ACME_SOURCE, strict=True)
    registry.register_many({
        "invoice.paid": "Fired when an invoice is paid.",
        "invoice.created": "Fired when a new invoice is created.",
        "customer.created": "Fired when a customer account is created.",
    })
    return registry
```

When the registry runs in strict mode, event types not in the registry are
rejected during intake with a `422` response.  Set `strict=False` to allow
unknown types through.

## Step 6: Build the dispatch map

```python
async def handle_invoice_paid(**kwargs: Any) -> None:
    """Process a paid invoice from Acme."""
    # Your business logic here
    pass

def build_acme_dispatch() -> WebhookEventDispatchMap:
    dispatch = WebhookEventDispatchMap(source=ACME_SOURCE)
    dispatch.register("invoice.paid", handle_invoice_paid)
    dispatch.register("invoice.created", handle_invoice_created)
    return dispatch
```

Handler functions receive keyword arguments from the job payload.  The
dispatch map is used during background processing, not during intake.

## Step 7: Assemble the adapter

```python
def build_acme_adapter(
    *,
    signing_secret: str,
    endpoint_key: str = "default",
) -> WebhookProviderAdapter:
    config = build_acme_config(
        signing_secret=signing_secret,
        endpoint_key=endpoint_key,
    )
    return WebhookProviderAdapter(
        config=config,
        verifier=AcmeWebhookVerifier(config),
        normalizer=normalize_acme_event,
        dispatch=build_acme_dispatch(),
        event_registry=build_acme_event_registry(),
    )
```

## Step 8: Wire up the route

Create a webhook route that uses the adapter with the canonical ingestion
pipeline:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.webhooks import (
    build_webhook_ack_response,
    build_webhook_ingestion_request,
    ingest_webhook_event,
)

router = APIRouter(prefix="/webhooks/acme", tags=["webhooks"])

# Build the adapter at module level or during app startup
acme_adapter = build_acme_adapter(signing_secret=settings.ACME_WEBHOOK_SECRET)

@router.post("/")
async def receive_acme_webhook(
    webhook_request=Depends(build_webhook_ingestion_request),
    session: AsyncSession = Depends(get_db_session),
):
    result = await ingest_webhook_event(
        session=session,
        webhook_request=webhook_request,
        source=acme_adapter.source,
        endpoint_key=acme_adapter.endpoint_key,
        verifier=acme_adapter.verifier,
        event_validator=acme_adapter.normalizer,
        enqueuer=your_enqueuer,
    )
    ack = build_webhook_ack_response(
        result.persisted_event,
        correlation_id=result.correlation_id,
    )
    return ack.as_response_body()
```

## Step 9: Add tests

Add a test file at `tests/test_webhook_acme.py` covering:

- Configuration construction
- Signature verification (valid and invalid)
- Event normalization (valid payload, missing fields, edge cases)
- Dispatch map registration and lookup
- Full adapter assembly

See `tests/test_webhook_providers.py` for the pattern used by the example
provider.

## Step 10: Export from the providers package

Add your provider's public symbols to
`src/app/webhooks/providers/__init__.py` so they are available through the
canonical import path.

## Checklist

- [ ] Provider module created in `src/app/webhooks/providers/`
- [ ] Configuration dataclass with signing secret from env/settings
- [ ] Signature verifier (or documented skip if provider does not sign)
- [ ] Event normalizer extracting type, IDs, and normalized payload
- [ ] Event type registry with known types
- [ ] Dispatch map with handler registrations
- [ ] Adapter assembly function
- [ ] Route wired to the canonical ingestion pipeline
- [ ] Tests covering all provider-specific logic
- [ ] Exports added to `providers/__init__.py`
