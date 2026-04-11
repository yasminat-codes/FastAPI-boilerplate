# Metrics and Tracing

This guide covers the observability features built into FastAPI Template: Prometheus metrics for monitoring and OpenTelemetry tracing for debugging request flows across your system.

Both metrics and tracing are **opt-in and disabled by default**. They're designed to add minimal overhead when enabled and zero overhead when disabled.

## Installation

Metrics and tracing are available as optional dependencies:

```bash
# Metrics only (Prometheus)
pip install fastapi-template[metrics]

# Tracing only (OpenTelemetry)
pip install fastapi-template[tracing]

# Both (recommended for production)
pip install fastapi-template[observability]
```

## Metrics

Prometheus metrics give you real-time visibility into what your application is doing: request rates, latencies, error rates, and custom business metrics.

### Configuration

Enable metrics by setting environment variables:

```env
METRICS_ENABLED=true
METRICS_PATH=/metrics
METRICS_NAMESPACE=fastapi_template
METRICS_INCLUDE_REQUEST_PATH_LABELS=false
```

| Setting | Default | Description |
|---------|---------|-------------|
| `METRICS_ENABLED` | `false` | Enable/disable metrics collection |
| `METRICS_PATH` | `/metrics` | HTTP endpoint where Prometheus scrapes metrics |
| `METRICS_NAMESPACE` | `fastapi_template` | Prefix for all metric names (e.g., `fastapi_template_http_requests_total`) |
| `METRICS_INCLUDE_REQUEST_PATH_LABELS` | `false` | If `true`, creates separate metrics for each route (can cause cardinality explosion with many paths). If `false`, aggregates all paths into a single metric |

### Available Metrics

#### HTTP Requests

These metrics track incoming HTTP requests to your API:

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `{namespace}_http_requests_total` | Counter | `method`, `path_template`, `status_code` | Total HTTP requests received |
| `{namespace}_http_request_duration_seconds` | Histogram | `method`, `path_template` | Request latency distribution |
| `{namespace}_http_requests_in_progress` | Gauge | `method` | Number of requests currently being processed |

**Example:** When a GET request to `/api/users/123` returns 200, these metrics increment:
```
fastapi_template_http_requests_total{method="GET",path_template="/api/users/{id}",status_code="200"} 1
fastapi_template_http_request_duration_seconds_bucket{method="GET",path_template="/api/users/{id}",le="0.005"} 1
```

#### Jobs/Queue Processing

Track background job execution:

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `{namespace}_job_executions_total` | Counter | `job_name`, `status` | Total job executions (success/failure) |
| `{namespace}_job_duration_seconds` | Histogram | `job_name` | Job execution time distribution |
| `{namespace}_jobs_in_progress` | Gauge | `job_name` | Jobs currently running |
| `{namespace}_job_queue_size` | Gauge | — | Number of pending jobs |

#### Webhooks

Monitor incoming webhook events:

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `{namespace}_webhook_events_received_total` | Counter | `provider`, `event_type`, `status` | Webhooks received (accepted/rejected) |
| `{namespace}_webhook_processing_duration_seconds` | Histogram | `provider` | Time to process webhooks |
| `{namespace}_webhook_signature_failures_total` | Counter | `provider` | Signature validation failures |

#### Outbound HTTP Calls

Track API calls your application makes to external services:

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `{namespace}_outbound_requests_total` | Counter | `provider`, `method`, `status_code` | External API calls made |
| `{namespace}_outbound_request_duration_seconds` | Histogram | `provider`, `method` | External API latency |
| `{namespace}_outbound_circuit_breaker_state` | Gauge | `provider` | Circuit breaker status (0=closed, 1=open, 2=half-open) |

#### Failures and Retries

Monitor errors and recovery attempts:

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `{namespace}_retries_total` | Counter | `component`, `reason` | Total retry attempts |
| `{namespace}_dead_letter_events_total` | Counter | `component` | Messages that failed permanently |
| `{namespace}_error_rate` | Counter | `component`, `error_type` | Errors by type and component |

### How Request Metrics Work

The `MetricsMiddleware` automatically wraps every HTTP request:

1. When a request arrives, the in-progress gauge increments
2. Request processing happens normally
3. When the response is sent, the counter and histogram update
4. The in-progress gauge decrements

By default, all paths are aggregated into `path_template` labels to keep cardinality low. Set `METRICS_INCLUDE_REQUEST_PATH_LABELS=true` only if you have a small, fixed set of routes and need per-path breakdowns.

### Using Metrics in Custom Code

Import the metrics registry and record custom metrics:

```python
from src.app.core.metrics import get_metrics

metrics = get_metrics()

if metrics:
    # Record a webhook event
    metrics.webhook_events_received_total.labels(
        provider="stripe",
        event_type="payment.completed",
        status="accepted"
    ).inc()
    
    # Increment a custom counter
    metrics.error_rate.labels(
        component="payment_processor",
        error_type="timeout"
    ).inc()
```

The `get_metrics()` function returns `None` if metrics are disabled, so the `if metrics:` check is safe and handles the opt-in behavior gracefully.

### Outbound HTTP Client Integration

The `PrometheusMetricsCollector` class implements the `MetricsCollector` protocol used by the HTTP client layer. When you make outbound requests through the client, metrics are automatically recorded:

```python
from src.app.integrations.http_client import get_http_client

client = get_http_client()

# This call is automatically tracked by PrometheusMetricsCollector
response = await client.post(
    "https://api.external.com/events",
    json={"event": "user_signup"}
)
```

The collector automatically labels metrics by provider name (derived from the URL) and tracks circuit breaker state.

### Prometheus Endpoint

When enabled, metrics are available at the configured `METRICS_PATH` (default `/metrics`):

```bash
curl http://localhost:8000/metrics
```

The response is in standard Prometheus text format, ready for scraping:

```
# HELP fastapi_template_http_requests_total Total HTTP requests
# TYPE fastapi_template_http_requests_total counter
fastapi_template_http_requests_total{method="GET",path_template="/api/health",status_code="200"} 42
fastapi_template_http_request_duration_seconds_bucket{method="GET",path_template="/api/health",le="0.005"} 40
fastapi_template_http_request_duration_seconds_bucket{method="GET",path_template="/api/health",le="0.01"} 42
...
```

Add this endpoint to your Prometheus, Grafana Agent, or monitoring stack to start collecting metrics.

## Tracing

OpenTelemetry tracing helps you understand request flows: which services handle the request, where time is spent, what errors occurred, and how components interact.

### Configuration

Enable tracing with environment variables:

```env
TRACING_ENABLED=true
TRACING_EXPORTER=otlp
TRACING_SAMPLE_RATE=1.0
TRACING_SERVICE_NAME=my-api
TRACING_PROPAGATE_CORRELATION_IDS=true
```

| Setting | Default | Description |
|---------|---------|-------------|
| `TRACING_ENABLED` | `false` | Enable/disable tracing |
| `TRACING_EXPORTER` | `otlp` | Exporter type: `otlp` (OpenTelemetry), `console` (stdout, for development) |
| `TRACING_SAMPLE_RATE` | `1.0` | Fraction of traces to record (0.0-1.0). Use 0.1 to sample 10% of requests |
| `TRACING_SERVICE_NAME` | `fastapi-template` | Name of this service in the trace UI |
| `TRACING_PROPAGATE_CORRELATION_IDS` | `true` | Inject X-Request-ID and X-Correlation-ID into outbound requests |

### Span Lifecycle

Spans represent discrete units of work. The template provides helpers for common patterns:

```python
from src.app.core.tracing import (
    start_request_span,
    start_job_span,
    start_webhook_span,
    start_outbound_span,
    trace_span
)

# In a request handler
async def process_order(order_id: int):
    with start_request_span("process_order") as span:
        span.set_attribute("order_id", order_id)
        # ... your code ...

# In a background job
async def send_daily_report():
    with start_job_span("send_daily_report"):
        # ... your code ...

# For custom spans
async def complex_operation():
    with trace_span("complex_operation") as span:
        span.set_attribute("operation_type", "multi_step")
        # ... your code ...
```

### Trace Context Propagation

When your service calls external APIs, trace context is automatically propagated in request headers:

**W3C Trace Context** (standard, always included):
```
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
tracestate: vendor_data=0xa02f5a9e
```

**Custom headers** (when `TRACING_PROPAGATE_CORRELATION_IDS=true`):
```
X-Request-ID: 4bf92f3577b34da6a3ce929d0e0e4736
X-Correlation-ID: external-parent-trace-id
```

This allows external services to participate in your trace and connect their spans back to your application.

The `OpenTelemetryTracingHook` automatically implements the `TracingHook` protocol used by the HTTP client, so propagation happens without additional code:

```python
from src.app.integrations.http_client import get_http_client

client = get_http_client()
response = await client.post("https://api.external.com/webhook")
# Trace context is automatically injected into the request headers
```

### Using Tracing in Custom Code

Record custom work with minimal code:

```python
from src.app.core.tracing import trace_span

async def calculate_report(user_id: int):
    with trace_span("calculate_report") as span:
        span.set_attribute("user_id", user_id)
        span.set_attribute("calculation_type", "monthly")
        
        # Nested spans are supported
        with trace_span("fetch_data") as fetch_span:
            data = await fetch_user_data(user_id)
            fetch_span.set_attribute("records_fetched", len(data))
        
        report = await process_data(data)
        span.set_attribute("report_size", len(report))
        return report
```

Attributes become queryable in your tracing UI (Jaeger, Grafana Tempo, Datadog, etc.).

### Viewing Traces

If using the `otlp` exporter, traces are sent to an OpenTelemetry collector:

```bash
# Example: local Jaeger for development
docker run -p 6831:6831/udp -p 16686:16686 jaegertracing/all-in-one
```

Then access the Jaeger UI at `http://localhost:16686` to see your traces.

For development, use the `console` exporter to print traces to stdout:

```env
TRACING_EXPORTER=console
TRACING_ENABLED=true
```

## Environment-Specific Guidance

### Local Development

**Metrics:** Disabled by default. Enable if you're testing the metrics endpoint or Grafana integration.

**Tracing:** Disabled by default. Enable with:

```env
TRACING_ENABLED=true
TRACING_EXPORTER=console
```

This prints traces to your logs. Useful for understanding request flows during development.

### Staging

**Metrics:** Enable to validate the metrics pipeline before production:

```env
METRICS_ENABLED=true
METRICS_PATH=/metrics
```

**Tracing:** Enable with sampling to catch issues without overwhelming your tracing backend:

```env
TRACING_ENABLED=true
TRACING_EXPORTER=otlp
TRACING_SAMPLE_RATE=0.5
```

### Production

**Metrics:** Enable with cardinality controls:

```env
METRICS_ENABLED=true
METRICS_INCLUDE_REQUEST_PATH_LABELS=false
```

The `false` value prevents metric explosion from dynamic path parameters.

**Tracing:** Enable with appropriate sampling based on traffic:

```env
TRACING_ENABLED=true
TRACING_EXPORTER=otlp
TRACING_SAMPLE_RATE=0.1
TRACING_SERVICE_NAME=my-api-prod
```

A sample rate of 0.1 (10%) balances observability with cost. Adjust based on your traffic volume and tracing backend capacity.

## Troubleshooting

**Metrics not appearing:** Check that `METRICS_ENABLED=true` and the `/metrics` endpoint returns a 200. Verify your Prometheus config is scraping the correct URL.

**Traces not reaching my backend:** Verify `TRACING_ENABLED=true`, the exporter endpoint is reachable, and firewall rules allow outbound traffic.

**High cardinality warnings:** If using Prometheus, you'll see warnings in the logs if path labels create too many unique metric series. Set `METRICS_INCLUDE_REQUEST_PATH_LABELS=false`.

**Performance impact:** With metrics and tracing enabled, expect a 2-5% overhead on latency-sensitive endpoints. Disable in performance tests and benchmark with both on and off.

## Further Reading

- [Runbooks and Alerting](runbooks/index.md) — Prometheus alert rules for all template metrics and operational runbooks.
- [Error Monitoring](error-monitoring.md) — Sentry configuration, filtering, and scrubbing.
- [Logging](logging.md) — structured logging shape and correlation context.
