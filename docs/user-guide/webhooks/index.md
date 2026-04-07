# Webhooks

The template includes a complete webhook ingestion platform that handles
signature verification, payload validation, replay protection, idempotency,
dead-letter handling, and retention out of the box.

## Architecture

Webhook processing follows a staged pipeline:

1. **Receive** — The route dependency reads the raw request body before any
   parsing so the exact bytes are available for signature verification.
2. **Verify** — A provider-specific signature verifier checks the request
   against the provider's signing secret.
3. **Validate** — The payload is parsed and the event type, event ID, and
   delivery ID are extracted through a provider-specific normalizer.
4. **Protect** — Replay protection and idempotency checks reject duplicate
   deliveries before they reach the ledger.
5. **Persist** — The event is written to the shared `webhook_event` ledger.
6. **Acknowledge** — The route returns a fast `202 Accepted` response so the
   provider does not time out.
7. **Enqueue** — The event is handed to the background job layer for
   business-logic processing.

## Provider extension points

The template separates *generic pipeline concerns* (steps 1, 4, 5, 6, 7)
from *provider-specific concerns* (steps 2, 3, and dispatch).  Provider
adapters plug into three interfaces:

| Interface | Purpose | Location |
|-----------|---------|----------|
| `WebhookProviderVerifier` | Verify the provider's signature against the raw body | `src/app/webhooks/providers/base.py` |
| `WebhookEventNormalizer` | Transform the provider payload into `WebhookValidatedEvent` | `src/app/webhooks/providers/base.py` |
| `WebhookEventDispatchMap` | Route event types to handler functions during job processing | `src/app/webhooks/providers/base.py` |

All three are optional.  A provider that does not sign its payloads can skip
the verifier.  A provider whose payload already matches the default JSON
validator can skip the normalizer.

## Included modules

| Module | Description |
|--------|-------------|
| `webhooks.ingestion` | Raw-body helpers, canonical intake pipeline |
| `webhooks.signatures` | Provider-agnostic signature verification contracts |
| `webhooks.validation` | Payload parsing, event-type registry, poison detection |
| `webhooks.persistence` | Webhook event ledger persistence |
| `webhooks.processing` | Acknowledgement, job offload, retry-safety contracts |
| `webhooks.replay` | Replay protection by delivery ID, event ID, or payload hash |
| `webhooks.idempotency` | Idempotency protection using the shared ledger |
| `webhooks.dead_letter` | Dead-letter storage for exhausted events |
| `webhooks.retention` | Payload scrubbing and event purging |
| `webhooks.correlation` | Webhook-to-workflow correlation tracking |
| `webhooks.replay_tooling` | Operator replay service for failed events |
| `webhooks.providers` | Provider-specific adapter base classes and example |

## Next steps

- [Adding a new webhook provider](adding-provider.md) walks through the
  full process of adding a provider adapter to the template.
