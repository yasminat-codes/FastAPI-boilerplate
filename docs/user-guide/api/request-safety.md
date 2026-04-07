# Request Safety

Phase 3.2 hardens the inbound request pipeline with reusable template controls instead of leaving every cloned project to invent them from scratch.

## Request Body Limits

The template now includes `RequestBodyLimitMiddleware`, which enforces a configurable maximum request size before route logic runs.

Relevant settings:

```env
REQUEST_BODY_LIMIT_ENABLED=true
REQUEST_BODY_MAX_BYTES=1048576
REQUEST_BODY_LIMIT_EXEMPT_PATH_PREFIXES=["/api/v1/webhooks/provider"]
```

Behavior:

- Requests with `Content-Length` larger than the configured limit are rejected immediately.
- Streaming bodies without a trustworthy `Content-Length` are counted as they are read and still fail once they cross the limit.
- Rejections return a standardized `413` API payload with `error.code="payload_too_large"`.
- Exempt path prefixes let cloned projects carve out larger upload or ingest routes without disabling the guardrail globally.

Use this as an application-layer backstop, not as a replacement for reverse-proxy or ingress limits.

## Inbound Request Timeouts

The template also includes an optional `RequestTimeoutMiddleware` for fail-fast inbound time budgets:

```env
REQUEST_TIMEOUT_ENABLED=false
REQUEST_TIMEOUT_SECONDS=30
REQUEST_TIMEOUT_EXEMPT_PATH_PREFIXES=["/api/v1/ops"]
```

Behavior:

- When enabled, requests that exceed the configured runtime budget return `504` with `error.code="request_timeout"`.
- Timeout exemptions let cloned projects leave room for trusted long-running routes while keeping a default ceiling elsewhere.
- The timeout is disabled by default because production budgets often need to align with reverse proxies, load balancers, and background-job offloading patterns.

Use the middleware as a coordination tool with upstream timeouts, not as the only timeout control in the stack.

## Raw-Body Webhook Verification

Signature-based webhooks should verify the exact inbound bytes before any JSON model parsing changes whitespace or key order. The canonical helper surface now lives under `src.app.webhooks`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.webhooks import (
    WebhookEventEnqueueRequest,
    WebhookEventEnqueueResult,
    WebhookIngestionRequest,
    WebhookSignatureVerificationContext,
    WebhookSignatureVerificationResult,
    WebhookSignatureVerifier,
    build_webhook_ingestion_request,
    ingest_webhook_event,
)
from src.app.platform.database import async_get_db, database_transaction

router = APIRouter()

class ProviderWebhookVerifier(WebhookSignatureVerifier):
    async def verify(
        self,
        context: WebhookSignatureVerificationContext,
    ) -> WebhookSignatureVerificationResult:
        signature = context.headers.get("X-Provider-Signature", "")
        verify_provider_signature(signature=signature, raw_body=context.raw_body)
        return WebhookSignatureVerificationResult(
            provider="provider",
            endpoint_key="provider-events",
            signature=signature,
        )


async def enqueue_provider_event(request: WebhookEventEnqueueRequest) -> WebhookEventEnqueueResult:
    payload = request.validated_event.normalized_payload or {}
    return WebhookEventEnqueueResult(
        job_name="project.webhooks.process_provider_event",
        queue_name="arq:webhooks",
        processing_metadata={"provider_event_id": payload.get("id")},
    )


@router.post("/api/v1/webhooks/provider")
async def receive_provider_webhook(
    webhook_request: WebhookIngestionRequest = Depends(build_webhook_ingestion_request),
    db: AsyncSession = Depends(async_get_db),
) -> dict[str, str]:
    async with database_transaction(db):
        ingestion = await ingest_webhook_event(
            session=db,
            webhook_request=webhook_request,
            source="provider",
            endpoint_key="provider-events",
            verifier=ProviderWebhookVerifier(),
            enqueuer=enqueue_provider_event,
        )

    return {"event_type": ingestion.validated_event.event_type}
```

Guidance:

- Prefer `WebhookIngestionRequest` via `build_webhook_ingestion_request` so the route contract stays explicit and the raw bytes are cached once.
- Keep provider-specific signature logic behind `WebhookSignatureVerifier` implementations so webhook routes stay thin and reusable.
- Use `ingest_webhook_event(...)` when a route should follow the template-owned happy path of receive, validate, replay-check, persist, acknowledge, and enqueue without reassembling those steps manually.
- The canonical ingestion flow now runs replay-window checks against the shared `webhook_event` ledger before a new inbox row is inserted. Catch `WebhookReplayDetectedError` or `WebhookReplayFingerprintMismatchError` when a provider needs custom duplicate-response semantics.
- Persist accepted or rejected deliveries with `WebhookEventPersistenceRequest` and `webhook_event_store` when a cloned project needs to diverge from the standard pipeline for custom intake or rejection handling.
- Verify the provider signature against `webhook_request.raw_body` and headers before parsing JSON.
- Parse into JSON or Pydantic models only after verification succeeds, either through `ingest_webhook_event(...)` or your own validated model layer.
- Use `webhook_request.content_type`, `media_type`, `charset`, and `payload_size_bytes` when you need to persist or inspect transport metadata alongside the payload.
- If a webhook legitimately needs a larger body budget than the rest of the API, exempt its route prefix from the global body-limit middleware instead of raising the limit for every route.

The older `src.app.platform.webhooks` import remains available as a compatibility alias, but new template code should import from `src.app.webhooks`.

## Safe Logging Redaction

Structured logging now redacts common secrets, tokens, cookie values, and PII-like fields before console or file rendering.

Relevant settings:

```env
LOG_REDACTION_ENABLED=true
LOG_REDACTION_EXACT_FIELDS=["authorization","cookie","set-cookie","x-api-key","password","email"]
LOG_REDACTION_SUBSTRING_FIELDS=["token","secret","password","authorization","cookie","session","email","phone","ssn"]
LOG_REDACTION_REPLACEMENT="[REDACTED]"
```

Behavior:

- Nested dictionaries and lists are redacted recursively.
- Request context fields like `request_id`, `correlation_id`, path, method, and status remain intact unless a cloned project explicitly adds them to the redaction lists.
- The defaults are intentionally conservative. Template adopters should tune the exact and substring lists to match their domain payloads.

Redaction protects logs from accidental leakage, but it does not replace careful decisions about what to log in the first place.
