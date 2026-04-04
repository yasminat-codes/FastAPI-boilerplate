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

Signature-based webhooks should verify the exact inbound bytes before any JSON model parsing changes whitespace or key order. The template now exposes a small helper surface through `src.app.platform.webhooks`:

```python
from fastapi import APIRouter, Request

from src.app.platform.webhooks import parse_raw_json_body, read_raw_request_body

router = APIRouter()


@router.post("/api/v1/webhooks/provider")
async def receive_provider_webhook(request: Request) -> dict[str, str]:
    raw_body = await read_raw_request_body(request)
    signature = request.headers.get("X-Provider-Signature", "")

    verify_provider_signature(signature=signature, raw_body=raw_body)
    payload = parse_raw_json_body(raw_body)

    return {"event_type": payload["type"]}
```

Guidance:

- Read the raw body first when signature verification depends on exact bytes.
- Verify the provider signature against `raw_body` and headers before parsing JSON.
- Parse into JSON or Pydantic models only after verification succeeds.
- If a webhook legitimately needs a larger body budget than the rest of the API, exempt its route prefix from the global body-limit middleware instead of raising the limit for every route.

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
