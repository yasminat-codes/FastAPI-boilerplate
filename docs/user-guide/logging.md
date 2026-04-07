# Logging

The template uses [structlog](https://www.structlog.org/) on top of the Python stdlib `logging` module to produce structured, machine-readable logs that carry correlation context automatically.

## Production default: stdout/stderr only

Container-native deployments expect processes to emit logs to standard output. The template follows this convention by default: **console logging is always enabled and file logging is off**.

Enable file logging only when your deployment explicitly needs on-disk log files:

```env
FILE_LOG_ENABLED=true
FILE_LOG_MAX_BYTES=10485760
FILE_LOG_BACKUP_COUNT=5
```

When enabled, logs are written to a rotating file at `src/app/logs/app.log`.

## Standard log shape

Every log entry passes through the same shared processor chain regardless of whether it comes from an API request, a background job, or an outbound integration call. The processors run in this order:

1. **Merge contextvars** -- pulls bound context from the current execution scope.
2. **Add logger name** and **log level**.
3. **Format positional arguments** and **merge extra fields**.
4. **Redact sensitive fields** -- scrubs secrets, tokens, PII using the configurable redaction rules.
5. **Drop color_message** -- removes the duplicate key Uvicorn adds.
6. **Timestamp** -- ISO 8601 timestamp.
7. **Stack info** -- renders stack traces when present.

### API request context

The `RequestContextMiddleware` binds these keys for every HTTP request:

| Key | Source | Description |
| --- | --- | --- |
| `request_id` | `X-Request-ID` header or generated UUID | Unique per request |
| `correlation_id` | `X-Correlation-ID` header or falls back to request_id | Tracks a logical operation across services |
| `client_host` | ASGI scope client | Remote IP address |
| `path` | ASGI scope | Request path |
| `method` | ASGI scope | HTTP method |
| `status_code` | Response start | HTTP response status |

Route handlers and downstream code that need to add cross-cutting context (for example, linking a request to a workflow) can bind additional keys at any time:

```python
import structlog

structlog.contextvars.bind_contextvars(
    workflow_id="wf-abc-123",
    provider_event_id="evt-stripe-456",
)
```

### Worker job context

The worker lifecycle hooks bind these keys for every background job:

| Key | Source | Description |
| --- | --- | --- |
| `job_id` | ARQ context | Unique job identifier |
| `job_name` | Job registration | Registered function name |
| `correlation_id` | Job envelope | Propagated from the originating request |
| `tenant_id` | Job envelope tenant context | Tenant scope |
| `organization_id` | Job envelope tenant context | Organization scope |
| `retry_count` | Job envelope or ARQ job_try | Current attempt number |
| `job_metadata` | Job envelope | Arbitrary metadata dict |
| `workflow_id` | Job envelope | Links the job to a workflow execution |
| `provider_event_id` | Job envelope | Links the job to a provider webhook event |

### Cross-cutting context keys

These keys are not bound automatically but are part of the standard vocabulary. Bind them when the context is available:

| Key | When to bind | Description |
| --- | --- | --- |
| `workflow_id` | Webhook handlers, workflow steps, job processors | Links a log entry to a `WorkflowExecution` record |
| `provider_event_id` | Webhook handlers, provider adapter calls | Links a log entry to a provider delivery or `WebhookEvent` record |

## Console and file handler configuration

Each handler has independent settings for log level, output format, and which context keys to include.

### Console handler

| Setting | Default | Description |
| --- | --- | --- |
| `CONSOLE_LOG_LEVEL` | `INFO` | Minimum level for console output |
| `CONSOLE_LOG_FORMAT_JSON` | `false` | `true` for JSON lines, `false` for human-readable |
| `CONSOLE_LOG_INCLUDE_REQUEST_ID` | `false` | Include `request_id` in console output |
| `CONSOLE_LOG_INCLUDE_CORRELATION_ID` | `false` | Include `correlation_id` in console output |
| `CONSOLE_LOG_INCLUDE_PATH` | `false` | Include `path` in console output |
| `CONSOLE_LOG_INCLUDE_METHOD` | `false` | Include `method` in console output |
| `CONSOLE_LOG_INCLUDE_CLIENT_HOST` | `false` | Include `client_host` in console output |
| `CONSOLE_LOG_INCLUDE_STATUS_CODE` | `false` | Include `status_code` in console output |

For production container deployments, set `CONSOLE_LOG_FORMAT_JSON=true` so log aggregators can parse each line as structured JSON.

### File handler

| Setting | Default | Description |
| --- | --- | --- |
| `FILE_LOG_ENABLED` | `false` | Enable the rotating file handler |
| `FILE_LOG_LEVEL` | `INFO` | Minimum level for file output |
| `FILE_LOG_FORMAT_JSON` | `true` | JSON by default for machine parsing |
| `FILE_LOG_MAX_BYTES` | `10485760` | Max file size before rotation (10 MB) |
| `FILE_LOG_BACKUP_COUNT` | `5` | Number of rotated backup files to keep |
| `FILE_LOG_INCLUDE_REQUEST_ID` | `true` | Include `request_id` in file output |
| `FILE_LOG_INCLUDE_CORRELATION_ID` | `true` | Include `correlation_id` in file output |
| `FILE_LOG_INCLUDE_PATH` | `true` | Include `path` in file output |
| `FILE_LOG_INCLUDE_METHOD` | `true` | Include `method` in file output |
| `FILE_LOG_INCLUDE_CLIENT_HOST` | `true` | Include `client_host` in file output |
| `FILE_LOG_INCLUDE_STATUS_CODE` | `true` | Include `status_code` in file output |

## Log levels by environment

| Setting | `local` | `staging` | `production` |
| --- | --- | --- | --- |
| `LOG_LEVEL` | `DEBUG` | `INFO` | `INFO` or `WARNING` |
| `UVICORN_LOG_LEVEL` | `INFO` | `WARNING` | `WARNING` |
| `WORKER_LOG_LEVEL` | `DEBUG` | `INFO` | `INFO` or `WARNING` |
| `CONSOLE_LOG_LEVEL` | `DEBUG` | `INFO` | `INFO` |
| `CONSOLE_LOG_FORMAT_JSON` | `false` | `true` | `true` |
| `FILE_LOG_ENABLED` | `false` | `false` | `false` (prefer log aggregator) |

Use `DEBUG` locally for maximum visibility during development. In staging and production, `INFO` is a reasonable baseline. Increase to `WARNING` for high-throughput services where log volume matters.

## Log redaction

Sensitive fields are scrubbed before any handler writes a log entry. Redaction runs as a structlog processor in the shared chain, so it applies consistently to both console and file output.

| Setting | Default | Description |
| --- | --- | --- |
| `LOG_REDACTION_ENABLED` | `true` | Master switch for log redaction |
| `LOG_REDACTION_EXACT_FIELDS` | `authorization`, `cookie`, `set-cookie`, `x-api-key`, `api_key`, `apikey`, `password`, `refresh_token`, `access_token`, `client_secret`, `email`, `phone`, `ssn` | Fields matched by exact normalized name |
| `LOG_REDACTION_SUBSTRING_FIELDS` | `token`, `secret`, `password`, `passwd`, `authorization`, `cookie`, `api_key`, `apikey`, `session`, `email`, `phone`, `ssn` | Fields matched when the normalized name contains the substring |
| `LOG_REDACTION_REPLACEMENT` | `[REDACTED]` | Replacement text for scrubbed values |

Redaction is recursive: nested dicts, lists, and tuples are walked and scrubbed at every level.

## Correlation propagation

Correlation context flows automatically through the template:

1. An inbound HTTP request arrives. The middleware generates or extracts `request_id` and `correlation_id`, then binds them to structlog contextvars.
2. If the request enqueues a background job, the `JobEnvelope` carries `correlation_id` (and optionally `workflow_id` and `provider_event_id`) into the job payload.
3. The worker lifecycle hooks bind the envelope fields to structlog contextvars before the job function runs.
4. Outbound HTTP calls made through the shared integration client propagate `X-Request-ID` and `X-Correlation-ID` headers automatically.

This means every log entry in a request-to-job-to-integration chain shares the same `correlation_id`, making distributed tracing straightforward even without a dedicated tracing backend.
