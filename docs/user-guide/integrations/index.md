# External Integrations

The template provides a shared outbound HTTP client layer that integration adapters should build on instead of constructing raw httpx clients. This gives every outbound call the same production defaults: timeouts, connection pooling, correlation propagation, structured logging, retry, circuit breaking, rate-limit handling, and authentication hooks.

## Architecture

```
src/app/integrations/
├── __init__.py                  # Re-exports the full integration surface
├── contracts/
│   ├── __init__.py              # Package interface for all contracts
│   ├── client.py                # BaseIntegrationClient + IntegrationClient protocol
│   ├── errors.py                # Normalized integration error taxonomy
│   ├── results.py               # IntegrationResult, paginated + bulk results
│   ├── settings.py              # IntegrationSettings + registry + env factory
│   ├── sandbox.py               # Sandbox/dry-run mode patterns
│   ├── secrets.py               # SecretProvider protocol + credential health
│   ├── sync.py                  # SyncCursor, SyncPage, SyncOperation, SyncProgress
│   └── exceptions.py            # Backward-compat shim (re-exports from errors.py)
└── http_client/
    ├── __init__.py              # Package interface (45 public exports)
    ├── client.py                # TemplateHttpClient + config + raise_for_status
    ├── exceptions.py            # Typed HTTP exception hierarchy
    ├── retry.py                 # Retry policy + backoff + method eligibility
    ├── circuit_breaker.py       # In-process circuit breaker state machine
    ├── rate_limit.py            # Rate-limit header parsing and delay helpers
    ├── auth.py                  # Bearer, API key, Basic, custom auth hooks
    ├── logging.py               # Structured logging with header redaction
    └── instrumentation.py       # Metrics + tracing extension protocols
```

See [Integration Contracts](contracts.md) for the full contract layer that sits on top of the HTTP client.

## Quick Start

### Basic Usage

```python
from src.app.integrations.http_client import TemplateHttpClient

async with TemplateHttpClient(base_url="https://api.example.com") as client:
    response = await client.get("/users")
    data = response.json()
```

### From Settings

```python
from src.app.platform import settings
from src.app.integrations.http_client import TemplateHttpClient

client = TemplateHttpClient.from_settings(settings, base_url="https://api.stripe.com")
```

### With Authentication

```python
from src.app.integrations.http_client import (
    TemplateHttpClient,
    BearerTokenAuth,
    LoggingRequestHook,
    LoggingResponseHook,
)

auth = BearerTokenAuth(token="sk-live-xxx")
client = TemplateHttpClient(
    base_url="https://api.example.com",
    request_hooks=[auth, LoggingRequestHook()],
    response_hooks=[LoggingResponseHook()],
)
```

## Settings

All HTTP client defaults are configurable through environment variables or the `.env` file:

| Setting | Default | Description |
|---------|---------|-------------|
| `HTTP_CLIENT_TIMEOUT_SECONDS` | `30.0` | Overall request timeout |
| `HTTP_CLIENT_CONNECT_TIMEOUT_SECONDS` | `10.0` | TCP connection timeout |
| `HTTP_CLIENT_READ_TIMEOUT_SECONDS` | `30.0` | Response read timeout |
| `HTTP_CLIENT_WRITE_TIMEOUT_SECONDS` | `30.0` | Request write timeout |
| `HTTP_CLIENT_POOL_MAX_CONNECTIONS` | `100` | Maximum connection pool size |
| `HTTP_CLIENT_POOL_MAX_KEEPALIVE` | `20` | Maximum keepalive connections |
| `HTTP_CLIENT_RETRY_ENABLED` | `true` | Enable automatic retries |
| `HTTP_CLIENT_RETRY_MAX_ATTEMPTS` | `3` | Maximum retry attempts |
| `HTTP_CLIENT_RETRY_BACKOFF_BASE_SECONDS` | `1.0` | Base delay for exponential backoff |
| `HTTP_CLIENT_RETRY_BACKOFF_MAX_SECONDS` | `30.0` | Maximum backoff delay cap |
| `HTTP_CLIENT_RETRY_BACKOFF_MULTIPLIER` | `2.0` | Exponential growth factor |
| `HTTP_CLIENT_RETRY_BACKOFF_JITTER` | `true` | Apply full jitter to delays |
| `HTTP_CLIENT_CIRCUIT_BREAKER_ENABLED` | `false` | Enable circuit breaker |
| `HTTP_CLIENT_CIRCUIT_BREAKER_FAILURE_THRESHOLD` | `5` | Failures before circuit opens |
| `HTTP_CLIENT_CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS` | `30.0` | Seconds before half-open probe |
| `HTTP_CLIENT_LOG_REQUEST_BODY` | `false` | Log outbound request body size |
| `HTTP_CLIENT_LOG_RESPONSE_BODY` | `false` | Log inbound response body size |

## Features

### Typed Exception Hierarchy

Every non-2xx response is mapped to a typed exception so callers can make intelligent retry decisions without inspecting raw status codes:

| Status Code | Exception | Retryable |
|-------------|-----------|-----------|
| 400 | `HttpClientBadRequestError` | No |
| 401 | `HttpAuthenticationError` | No |
| 403 | `HttpAuthorizationError` | No |
| 404 | `HttpNotFoundError` | No |
| 409 | `HttpConflictError` | No |
| 429 | `HttpRateLimitError` | Yes |
| 5xx | `HttpServerError` | Yes |
| Timeout | `HttpTimeoutError` | Yes |
| Connection | `HttpConnectionError` | Yes |

### Correlation Propagation

When `propagate_correlation=True` (the default), outbound requests automatically carry `X-Request-ID` and `X-Correlation-ID` headers from the active structured-log context. This connects inbound API requests to their downstream integration calls for end-to-end tracing.

### Retry Policy

The retry module provides `HttpRetryPolicy` with exponential backoff and jitter, consistent with the worker retry system. By default, only idempotent HTTP methods (GET, HEAD, OPTIONS, PUT, DELETE) are retried automatically. POST retries require explicit opt-in via `idempotent_methods_only=False`.

Rate-limited responses (429) respect the `Retry-After` header when present.

### Circuit Breaker

The in-process circuit breaker follows the standard three-state model:

- **CLOSED**: Requests flow normally; consecutive failures are counted.
- **OPEN**: Requests are rejected immediately with `HttpCircuitOpenError`.
- **HALF_OPEN**: One probe request is allowed; success closes the circuit, failure reopens it.

### Authentication Hooks

Four reusable auth hooks are included:

- `BearerTokenAuth` — static token or dynamic `TokenProvider` protocol
- `ApiKeyAuth` — header-based API key injection with configurable header name
- `BasicAuth` — HTTP Basic authentication
- `CustomAuth` — delegate to any sync or async callable

### Logging with Redaction

`LoggingRequestHook` and `LoggingResponseHook` produce structured log events with automatic redaction of sensitive headers (Authorization, Cookie, API keys, tokens, secrets).

### Instrumentation Protocols

`MetricsCollector` and `TracingHook` are runtime-checkable protocols that template adopters can implement for Prometheus, OpenTelemetry, Datadog, or any other observability backend. The template does not ship a concrete implementation to avoid coupling to a specific vendor.

## Adding a Provider Adapter

To add a new external integration:

1. Create a module under `src/app/integrations/` (e.g., `src/app/integrations/stripe/`).
2. Subclass `BaseIntegrationClient` with provider-specific auth and base URL.
3. Register provider-specific settings using `build_integration_settings()` or a custom `IntegrationSettings` subclass.
4. Return `IntegrationResult` from operations for consistent error and retry handling.
5. See [Integration Contracts](contracts.md) for the full contract layer.

```python
from src.app.integrations import (
    BaseIntegrationClient,
    IntegrationMode,
    IntegrationResult,
    IntegrationSettings,
    build_integration_settings,
    classify_http_error,
)
from src.app.integrations.http_client import (
    BearerTokenAuth,
    HttpClientError,
    TemplateHttpClient,
)


class StripeClient(BaseIntegrationClient):
    def __init__(self, settings: IntegrationSettings) -> None:
        auth = BearerTokenAuth(token=settings.api_key or "")
        http_client = TemplateHttpClient(
            base_url=settings.effective_base_url(),
            request_hooks=[auth],
        )
        super().__init__(
            http_client=http_client,
            provider_name="stripe",
            mode=settings.mode,
        )

    async def get_customer(self, customer_id: str) -> IntegrationResult[dict]:
        try:
            response = await self._request("GET", f"/v1/customers/{customer_id}", operation="get_customer")
            return IntegrationResult.ok(data=response.json(), provider="stripe", operation="get_customer")
        except HttpClientError as exc:
            return IntegrationResult.fail(error=classify_http_error("stripe", "get_customer", exc))
```
