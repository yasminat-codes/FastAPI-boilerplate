# Error Monitoring

The template provides hardened [Sentry](https://sentry.io) integration for capturing, filtering, and analyzing errors across your API and worker processes. Out-of-the-box features include intelligent event filtering, sensitive field scrubbing, automatic context tagging, and transaction sampling optimized for production workloads.

## Overview

The error monitoring system is built around a unified Sentry SDK configuration that works across both:

- **API processes** — FastAPI integration captures request context, exceptions, and performance transactions
- **Worker processes** — ARQ integration captures background job failures and performance

Key capabilities:

- Automatic scrubbing of sensitive fields (passwords, tokens, API keys, etc.) before events leave your process
- Context-aware transaction sampling that reduces noise from health checks and webhooks
- Request/correlation ID injection for tracing events across your system
- Environment-based initialization with sensible defaults for local, staging, and production
- User, request, and job context helpers for richer error context
- Before-send filtering to drop noisy exception types or loggers
- Performance profiling support with configurable sample rates

## Configuration

All error monitoring settings are namespaced under `SENTRY_*` environment variables. The complete set of configuration options:

### Core Settings

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `SENTRY_ENABLE` | `bool` | `false` | Master switch; Sentry SDK is initialized only when true |
| `SENTRY_DSN` | Secret string | `None` | Sentry project DSN; required when `SENTRY_ENABLE=true` |
| `SENTRY_ENVIRONMENT` | `str` | `"local"` | Environment name sent with events (local, staging, production) |
| `SENTRY_DEBUG` | `bool` | `false` | Enable verbose Sentry SDK debug logging |

### Release and Server Identification

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `SENTRY_RELEASE` | `str` | `None` | Version/commit hash to associate events with a specific release |
| `SENTRY_RELEASE_PREFIX` | `str` | `""` | Prefix for multi-service setups; release becomes `<prefix>@<version>` when set |
| `SENTRY_SERVER_NAME` | `str` | `None` | Server/hostname to tag events; helps distinguish events from different instances |

### Event Collection and Sampling

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `SENTRY_ERROR_SAMPLE_RATE` | `float` (0.0–1.0) | `1.0` | Fraction of exceptions to capture (1.0 = all errors) |
| `SENTRY_ATTACH_STACKTRACE` | `bool` | `true` | Include full stack trace on all error events |
| `SENTRY_SEND_DEFAULT_PII` | `bool` | `false` | Send PII like user email; override with caution |
| `SENTRY_MAX_BREADCRUMBS` | `int` | `100` | Maximum breadcrumb events to attach per error (0–max) |

### Transaction/Performance Sampling

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `SENTRY_TRACES_SAMPLE_RATE` | `float` (0.0–1.0) | `1.0` | Default transaction sample rate for all requests |
| `SENTRY_HEALTH_ENDPOINT_SAMPLE_RATE` | `float` (0.0–1.0) | `0.0` | Sample rate for health check endpoints (e.g., `/health`, `/ready`) |
| `SENTRY_WEBHOOK_SAMPLE_RATE` | `float` (0.0–1.0) | `None` | Sample rate for `/webhook` routes; uses default traces rate if unset |
| `SENTRY_WORKER_SAMPLE_RATE` | `float` (0.0–1.0) | `None` | Sample rate for worker job transactions; uses default traces rate if unset |
| `SENTRY_PROFILES_SAMPLE_RATE` | `float` (0.0–1.0) | `1.0` | Fraction of transactions to profile (requires Profiling tier) |

### Shutdown and Delivery

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `SENTRY_FLUSH_TIMEOUT_SECONDS` | `int` | `2` | Seconds to wait for pending events during graceful shutdown |

### Event Filtering

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `SENTRY_IGNORED_EXCEPTIONS` | `list[str]` | `[]` | Exception class names to ignore (e.g., `HTTPException`, `TimeoutError`) |
| `SENTRY_IGNORED_LOGGERS` | `list[str]` | `[]` | Logger names to ignore; events from these loggers are dropped |

### Field Scrubbing and Redaction

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `SENTRY_SCRUB_FIELDS` | `list[str]` | See below | Field names to redact from events |
| `SENTRY_SCRUB_REPLACEMENT` | `str` | `"[Filtered]"` | Replacement text for scrubbed fields |

**Default scrub fields** include: `password`, `secret`, `token`, `authorization`, `cookie`, `session`, `api_key`, `dsn`, `private_key`, `credit_card`, `ssn`. Additional substring matches apply to fields containing `password`, `secret`, `token`, `authorization`, `credential`, `cookie`, `bearer`, `private`.

## API Process Initialization

Initialize Sentry for your FastAPI application in the startup hook:

```python
from app.core.sentry import init_sentry, shutdown_sentry

app = FastAPI()

@app.on_event("startup")
async def startup():
    init_sentry()

@app.on_event("shutdown")
async def shutdown():
    await shutdown_sentry()
```

### What `init_sentry()` does

When called, it:

1. Reads the `SentrySettings` from your environment
2. Returns early if `SENTRY_ENABLE` is false
3. Imports the Sentry SDK and required integrations
4. Builds a `SentryConfig` object from settings
5. Initializes the SDK with:
   - **FastAPI integration** — tracks HTTP requests and exceptions
   - **Logging integration** — captures WARNING+ log entries as breadcrumbs
   - **ARQ integration** (if available) — optional support for job context
6. Sets up event filtering and field scrubbing
7. Configures context-aware transaction sampling
8. Tags all events with `process_type=api`
9. Logs a startup message to indicate Sentry is ready

The SDK is configured with sensible production defaults: full error capture (`error_sample_rate=1.0`), intelligent traces sampling (health checks at 0%, default routes at configured rate), and strict field scrubbing.

## Worker Process Initialization

Initialize Sentry for ARQ worker processes separately:

```python
from app.core.sentry import init_sentry_for_worker, shutdown_sentry

async def startup(ctx):
    await init_sentry_for_worker()

async def shutdown(ctx):
    await shutdown_sentry()
```

### What `init_sentry_for_worker()` does

Similar to API initialization but optimized for background job context:

1. Reads `SentrySettings` from environment
2. Returns early if `SENTRY_ENABLE` is false
3. Initializes the SDK with:
   - **ARQ integration** (primary) — captures job failures, retries, and execution time
   - **Logging integration** — captures WARNING+ log entries
4. Sets up the same event filtering and field scrubbing as the API
5. Uses `SENTRY_WORKER_SAMPLE_RATE` for transaction sampling (defaults to `SENTRY_TRACES_SAMPLE_RATE` if unset)
6. Tags all events with `process_type=worker`
7. Logs a startup message

Worker events are tagged separately so you can filter by `process_type:worker` in Sentry's UI to focus on background job issues.

## Event Filtering

### Ignoring Specific Exception Types

Drop events from noisy exception types by listing them in `SENTRY_IGNORED_EXCEPTIONS`:

```env
SENTRY_IGNORED_EXCEPTIONS=HTTPException,SkipSubprocessError,RequestCancelled
```

The filter matches exception class names exactly (no module path needed). Events from these exceptions are discarded before sending.

### Ignoring Specific Loggers

Drop events from verbose loggers by listing them in `SENTRY_IGNORED_LOGGERS`:

```env
SENTRY_IGNORED_LOGGERS=urllib3,httpx,openai
```

The filter matches logger names exactly. Any WARNING+ log entry from these loggers is ignored.

!!! note
    Ignored loggers affect error events only; breadcrumbs from these loggers are still captured.

## Field Scrubbing

Sensitive data is automatically scrubbed from all events before they leave your process. Scrubbing is recursive and applies to all nested dictionaries, lists, and tuples.

### Default Scrub Fields

The default list includes common sensitive field names:

- **Exact matches**: `password`, `secret`, `token`, `authorization`, `cookie`, `session`, `api_key`, `dsn`, `private_key`, `credit_card`, `ssn`
- **Substring matches**: fields containing `password`, `secret`, `token`, `authorization`, `credential`, `cookie`, `bearer`, `private`

Field names are normalized (lowercased, underscores normalized) before matching, so `X-API-Key`, `x_api_key`, and `API_KEY` all match.

### Customizing Scrub Fields

Add application-specific fields by extending `SENTRY_SCRUB_FIELDS`:

```env
SENTRY_SCRUB_FIELDS=password,secret,token,authorization,cookie,session,api_key,dsn,private_key,credit_card,ssn,stripe_key,openai_token,db_password
```

The list is comma-separated. Exact and substring matching both apply.

### Scrub Replacement Text

Control the replacement text for scrubbed values:

```env
SENTRY_SCRUB_REPLACEMENT="***REDACTED***"
```

Default is `[Filtered]`. The replacement appears in all scrubbed field values and breadcrumb entries.

## Context Tagging

The template automatically tags events with request and correlation IDs from the current execution context. These tags help you trace events across distributed systems.

### Automatic Context Injection

If a `request_id` or `correlation_id` is bound in the current execution context (via middleware or explicit binding), it is automatically added to every event as tags:

```python
# In a request handler
structlog.contextvars.bind_contextvars(
    request_id="req-12345",
    correlation_id="corr-67890",
)
# Any Sentry event captured during this request will include these tags
```

The automatic injection happens in the `before_send` and `before_send_transaction` callbacks, so you don't need to manually set tags on every error.

### Manual Context Tagging

Use the scope helpers to explicitly set tags, user info, and job context.

## Scope Helpers

The template provides typed helpers for setting context on the current Sentry scope. These are safe to call even if Sentry is not enabled (they check `is_sentry_enabled()` internally).

### `set_sentry_tags(tags: dict[str, str])`

Set custom tags on the current scope:

```python
from app.core.sentry import set_sentry_tags

set_sentry_tags({
    "feature_flag": "new_checkout",
    "deployment": "us-west-2",
    "team": "payments",
})
```

Tags are indexed by Sentry and available for filtering in the UI and API. Use tags for categorical metadata.

### `set_sentry_user(user_id: str, *, username: str | None = None, email: str | None = None, tenant_id: str | None = None, org_id: str | None = None)`

Set user context on the scope:

```python
from app.core.sentry import set_sentry_user

set_sentry_user(
    user_id="user-abc-123",
    username="alice@example.com",
    email="alice@example.com",
    tenant_id="tenant-xyz-789",
    org_id="org-def-456",
)
```

The `user_id` is stored in Sentry's user object. Optional fields like `username` and `email` are included in the user dict. The `tenant_id` and `org_id` are stored as tags (not in the user dict) so they can be indexed and filtered.

!!! note
    Set user context as early as possible in your request handler (e.g., after authentication) so all downstream errors are attributed correctly.

### `set_sentry_request_context(request_id: str | None = None, correlation_id: str | None = None)`

Explicitly set request/correlation IDs on the scope:

```python
from app.core.sentry import set_sentry_request_context

set_sentry_request_context(
    request_id="req-unique-123",
    correlation_id="corr-workflow-456",
)
```

This is rarely needed if your middleware already binds these to contextvars, but it's useful when capturing errors from non-request contexts.

### `set_sentry_job_context(job_id: str, *, job_name: str | None = None, queue_name: str | None = None, correlation_id: str | None = None, retry_count: int | None = None)`

Set background job context on the scope:

```python
from app.core.sentry import set_sentry_job_context

set_sentry_job_context(
    job_id="job-12345",
    job_name="send_email",
    queue_name="default",
    correlation_id="corr-workflow-789",
    retry_count=2,
)
```

This attaches a "job" context object to the Sentry scope. The `correlation_id` is also stored as a tag for filtering. Call this early in your worker job handler or in worker lifecycle hooks.

## Transaction Sampling

Transaction sampling reduces noise by selectively capturing HTTP request and background job transactions. High-volume endpoints like health checks are sampled at a lower rate (or not at all), while errors and important workflows are always captured.

### How `traces_sampler` Works

The template includes a context-aware sampler that routes transactions to different sample rates based on the endpoint:

1. **Health endpoints** (fragments: `/health`, `/ready`, `/readiness`, `/liveness`, `/status`) → `SENTRY_HEALTH_ENDPOINT_SAMPLE_RATE`
2. **Webhook endpoints** (path contains `/webhook`) → `SENTRY_WEBHOOK_SAMPLE_RATE` (if set)
3. **Everything else** → `SENTRY_TRACES_SAMPLE_RATE`

!!! tip
    Health check endpoints are sampled at 0% by default to prevent noisy transactions from cluttering your Sentry issues.

### Sampling Configuration Example

For a typical production setup:

```env
# Capture all errors
SENTRY_ERROR_SAMPLE_RATE=1.0

# Capture 10% of normal request transactions (performance data)
SENTRY_TRACES_SAMPLE_RATE=0.1

# Disable health check transaction capture
SENTRY_HEALTH_ENDPOINT_SAMPLE_RATE=0.0

# Capture 5% of webhook transactions (may be high-volume)
SENTRY_WEBHOOK_SAMPLE_RATE=0.05

# Capture 50% of worker job transactions
SENTRY_WORKER_SAMPLE_RATE=0.5
```

This ensures you capture all errors while being selective about performance data, reducing quota usage and noise.

## Release Tracking

Associating errors with specific releases helps you identify when issues were introduced and track fixes across deployments.

### Basic Release Configuration

Set the release version:

```env
SENTRY_RELEASE=1.2.3
```

Sentry will tag events with this version. In the UI, you can group issues by release and see which versions are affected.

### Multi-Service Release Namespacing

For deployments with multiple services reporting to the same Sentry project, use `SENTRY_RELEASE_PREFIX` to namespace releases:

```env
# Service A
SENTRY_RELEASE_PREFIX=service-a
SENTRY_RELEASE=1.2.3
# Events tagged with release="service-a@1.2.3"

# Service B
SENTRY_RELEASE_PREFIX=service-b
SENTRY_RELEASE=2.0.1
# Events tagged with release="service-b@2.0.1"
```

The release becomes `<prefix>@<version>` when the prefix is set. This keeps releases from different services distinct in Sentry's UI.

!!! note
    If `SENTRY_RELEASE` is not set, release tracking is disabled regardless of the prefix.

## Sampling Guidance

### Production Configuration

For production deployments, balance error detection against quota and noise:

```env
# Capture all errors — never sample exceptions
SENTRY_ERROR_SAMPLE_RATE=1.0

# Performance sampling
SENTRY_TRACES_SAMPLE_RATE=0.05          # 5% of normal requests
SENTRY_HEALTH_ENDPOINT_SAMPLE_RATE=0.0  # No health check transactions
SENTRY_WEBHOOK_SAMPLE_RATE=0.02         # 2% of webhooks (high-volume)
SENTRY_WORKER_SAMPLE_RATE=0.1           # 10% of job transactions

# Profiling (use only if you have a Profiling tier)
SENTRY_PROFILES_SAMPLE_RATE=0.1         # 10% of transactions

# Release tracking
SENTRY_RELEASE=v1.2.3-build.456
SENTRY_ENVIRONMENT=production
```

Rationale:

- **Always capture errors** — exceptions are typically low-volume and high-value
- **Sample normal requests lightly** — performance data is useful but not critical; 5% is usually sufficient
- **Skip health checks** — health endpoints generate noisy transactions that don't represent real user experience
- **Sample webhooks lower** — webhook endpoints may receive high-volume traffic; 1–5% is often adequate
- **Sample workers moderately** — background job failures are important; 10% captures a good sample without overload
- **Sample profiles conservatively** — profiling data is heavy; 10% or lower is recommended

### Staging Configuration

For staging environments, sample more aggressively to catch issues before production:

```env
SENTRY_ERROR_SAMPLE_RATE=1.0
SENTRY_TRACES_SAMPLE_RATE=0.5           # 50% of requests
SENTRY_HEALTH_ENDPOINT_SAMPLE_RATE=0.0
SENTRY_WEBHOOK_SAMPLE_RATE=0.1
SENTRY_WORKER_SAMPLE_RATE=0.5
SENTRY_PROFILES_SAMPLE_RATE=0.5
SENTRY_ENVIRONMENT=staging
```

### Local Development Configuration

For local development, capture everything:

```env
SENTRY_ENABLE=false  # Or enable with 100% sampling
SENTRY_ERROR_SAMPLE_RATE=1.0
SENTRY_TRACES_SAMPLE_RATE=1.0
SENTRY_HEALTH_ENDPOINT_SAMPLE_RATE=0.1
SENTRY_WEBHOOK_SAMPLE_RATE=1.0
SENTRY_WORKER_SAMPLE_RATE=1.0
SENTRY_PROFILES_SAMPLE_RATE=0.0         # Disable profiling locally
SENTRY_ENVIRONMENT=local
```

## Capture Helpers

The template provides convenience helpers for manually capturing exceptions and messages to Sentry.

### `capture_sentry_exception(error: Exception, extra_context: dict[str, Any] | None = None) -> str | None`

Capture an exception with optional extra context:

```python
from app.core.sentry import capture_sentry_exception

try:
    risky_operation()
except ValueError as e:
    event_id = capture_sentry_exception(
        e,
        extra_context={
            "operation": "risky_operation",
            "user_id": "user-123",
            "retry_count": 3,
        },
    )
    # event_id is the Sentry event ID or None if not enabled
```

The extra context is attached as a "extra" context object on the scope before capturing. Returns the Sentry event ID or `None` if Sentry is not enabled.

### `capture_sentry_message(message: str, level: str = "info", extra: dict[str, Any] | None = None) -> str | None`

Capture a message at a specified level:

```python
from app.core.sentry import capture_sentry_message

capture_sentry_message(
    "Batch job completed with warnings",
    level="warning",
    extra={
        "job_id": "job-abc-123",
        "records_processed": 1000,
        "warnings": 5,
    },
)
```

Valid levels are `debug`, `info`, `warning`, `error`, `fatal`. The `extra` dict is attached as context. Returns the event ID or `None` if Sentry is not enabled.

!!! note
    Use these helpers sparingly — structured logging is preferred for routine messages. Use Sentry capture for exceptional conditions that warrant investigation.

## Environment-Specific Settings

The template includes environment-aware defaults that apply automatically based on `ENVIRONMENT`:

### Local

```env
ENVIRONMENT=local
SENTRY_ENVIRONMENT=local
SENTRY_ENABLE=false           # Disabled by default; enable for testing
SENTRY_DEBUG=false
SENTRY_ATTACH_STACKTRACE=true
SENTRY_SEND_DEFAULT_PII=false
```

Development default: Sentry is disabled to reduce overhead. Enable it manually for testing integration.

### Staging

```env
ENVIRONMENT=staging
SENTRY_ENVIRONMENT=staging
SENTRY_ENABLE=true
SENTRY_DEBUG=false
SENTRY_ATTACH_STACKTRACE=true
SENTRY_SEND_DEFAULT_PII=false
```

Staging default: Sentry is enabled. Configure sampling as needed for your workflow.

### Production

```env
ENVIRONMENT=production
SENTRY_ENVIRONMENT=production
SENTRY_ENABLE=true
SENTRY_DEBUG=false
SENTRY_ATTACH_STACKTRACE=true
SENTRY_SEND_DEFAULT_PII=false
SENTRY_ERROR_SAMPLE_RATE=1.0
SENTRY_TRACES_SAMPLE_RATE=0.05
SENTRY_HEALTH_ENDPOINT_SAMPLE_RATE=0.0
```

Production default: Sentry is enabled with conservative sampling to balance coverage and quota.

## Shutdown and Graceful Degradation

The template includes a shutdown hook that flushes pending events:

```python
from app.core.sentry import shutdown_sentry

await shutdown_sentry()  # Flushes pending events with timeout
```

The shutdown function:

1. Returns early if Sentry is not enabled
2. Calls `sentry_sdk.flush(timeout=SENTRY_FLUSH_TIMEOUT_SECONDS)`
3. Logs completion

This ensures events captured late in the shutdown process are still delivered. The `SENTRY_FLUSH_TIMEOUT_SECONDS` setting (default 2) controls how long to wait; increase it for slow networks or set it lower for fast shutdown.

## Sentry SDK Check

To check whether Sentry is currently enabled at runtime:

```python
from app.core.sentry import is_sentry_enabled

if is_sentry_enabled():
    # Safe to use Sentry functions
    capture_sentry_message("System event")
```

This is useful when optional features depend on Sentry availability.

## Integration with Logging

Sentry integrates with Python's logging module. By default:

- **Logging integration** captures WARNING and ERROR level logs as Sentry events
- **Breadcrumbs** include INFO+ level logs, providing context for errors
- **Sensitive fields** are scrubbed from all log entries before sending

This means errors logged via structlog or the stdlib logger are automatically captured and scrubbed.

## Best Practices

1. **Set user context early** — Call `set_sentry_user()` after authentication so errors are attributed correctly
2. **Use tags for categories** — Tags are indexed; use them for categorical metadata (feature flags, team, deployment region)
3. **Ignore noisy exceptions** — Use `SENTRY_IGNORED_EXCEPTIONS` to filter out expected errors (e.g., HTTPException, RequestCancelled)
4. **Customize scrub fields** — Extend `SENTRY_SCRUB_FIELDS` with your application-specific sensitive field names
5. **Sample conservatively** — In production, sample traces (performance data) lightly; always capture errors
6. **Monitor quota** — Track your event usage in Sentry's settings; adjust sampling rates to stay within quota
7. **Test locally** — Enable Sentry locally with sampling to verify integration works before pushing to staging
8. **Review releases** — Use `SENTRY_RELEASE` to track versions; review release notes in Sentry's UI when investigating issues

## Troubleshooting

### Events Not Appearing

- Check that `SENTRY_ENABLE=true` and `SENTRY_DSN` is set
- Verify the DSN is valid in your Sentry project settings
- Confirm the error is not in `SENTRY_IGNORED_EXCEPTIONS` or `SENTRY_IGNORED_LOGGERS`
- Review Sentry SDK logs with `SENTRY_DEBUG=true`

### Missing Context Tags

- Ensure you're calling `set_sentry_*()` helpers before the error occurs
- Check that context middleware is binding `request_id` and `correlation_id` to contextvars
- Verify `SENTRY_SEND_DEFAULT_PII=false` is not blocking user information

### High Event Volume

- Lower `SENTRY_TRACES_SAMPLE_RATE` to reduce performance data capture
- Set `SENTRY_WEBHOOK_SAMPLE_RATE` lower for high-traffic endpoints
- Add noisy exception types to `SENTRY_IGNORED_EXCEPTIONS`
- Review quota usage in Sentry and consider a higher tier

## Further Reading

- [Runbooks and Alerting](runbooks/index.md) — minimum production alerts (including Sentry-based alerts) and operational runbooks.
- [Logging](logging.md) — structured logging shape and correlation context.
- [Metrics and Tracing](metrics-and-tracing.md) — Prometheus metrics and OpenTelemetry tracing.
