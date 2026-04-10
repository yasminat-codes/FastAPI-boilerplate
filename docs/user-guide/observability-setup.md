# Observability Setup Guide

## Overview of the Observability Stack

This FastAPI template includes a complete observability platform designed for production workloads. The stack consists of four complementary systems that work together to provide visibility into your application's behavior, performance, and health.

**Structured Logging** is the foundation—always enabled and configured to output JSON in production environments for efficient parsing and storage. Every log entry includes correlation IDs that tie together related requests, background jobs, and outbound calls, making it easy to trace user actions through your entire system.

**Sentry Error Monitoring** catches and reports exceptions, performance issues, and errors that occur in production. It's opt-in but highly recommended for any production deployment, as it provides immediate alerting, error grouping, and the context needed to debug issues quickly.

**Prometheus Metrics** expose quantitative measurements of your application's behavior—request counts, response times, job durations, queue sizes, and failure rates. When combined with Grafana, metrics enable dashboards that show system health at a glance and support alerting on thresholds.

**OpenTelemetry Tracing** provides distributed tracing across your entire request lifecycle. A single user action might trigger an HTTP request, enqueue a background job, and make outbound calls to external services. Tracing connects all these pieces with a common trace ID, letting you see exactly where time is spent and where failures occur.

These systems are designed to integrate seamlessly. Trace IDs automatically propagate to logs and error reports. Application tags (environment, service name, release) are consistently applied everywhere. The configuration is centralized in environment variables, making it straightforward to adjust observability settings per deployment.


## Quick Setup

To get started with observability in your FastAPI application, you need minimal configuration.

### Install Dependencies

The template comes with structured logging always available. For metrics and tracing, you'll need optional dependencies:

```bash
# For metrics support
pip install -e ".[metrics]"

# For tracing support
pip install -e ".[tracing]"

# For both
pip install -e ".[metrics,tracing]"
```

### Minimal Configuration

In your `.env` file or environment, set these variables to enable observability:

```dotenv
# Always available - structured logging
LOG_LEVEL=INFO

# Optional - Sentry error monitoring
SENTRY_DSN=https://your-sentry-key@sentry.io/your-project-id

# Optional - Prometheus metrics
METRICS_ENABLED=true

# Optional - OpenTelemetry tracing
TRACING_ENABLED=true
TRACING_ENDPOINT=http://localhost:4317
TRACING_SERVICE_NAME=my-fastapi-app
```

The application will start with sensible defaults. Structured logs appear in JSON format in production and as pretty-printed console output locally. Sentry, metrics, and tracing are only active if enabled via their respective configuration variables.


## Structured Logging Setup and Customization

Structured logging is the foundation of your observability strategy. Unlike traditional text logs, structured logs are emitted as JSON, making them machine-readable and easy to search, filter, and aggregate in log aggregation platforms like ELK, Loki, or CloudWatch.

### How It Works

The application uses `structlog` to emit structured logs with the following features:

Each log entry includes a **correlation ID** that ties together all logs from a single HTTP request, background job execution, or trace. This ID comes from the `X-Request-ID` or `X-Correlation-ID` headers (if present), or a new UUID is generated. This single ID makes it trivial to reconstruct the entire flow of a user action across service boundaries.

**Log redaction** automatically removes sensitive values like passwords, tokens, API keys, and PII-like fields (email addresses, phone numbers) from log output. This prevents accidental exposure of secrets in logs that might be shipped to third-party log aggregators.

**Environment-aware formatting** means logs are JSON in production (for efficient parsing by log aggregators) and pretty-printed in local development (for human readability in the console).

**Contextual information** is automatically included in every log entry: timestamp, log level, logger name, service name, environment, and any contextual fields you've bound to the logger.

### Configuration

Set these environment variables to customize logging behavior:

```dotenv
# Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=INFO

# Service name included in every log
SERVICE_NAME=my-fastapi-app

# Environment name included in every log
ENVIRONMENT=production

# For local development, set to true to see pretty console logs even with JSON serialization
# (ignored in production)
LOG_PRETTY_CONSOLE=false
```

### Using the Logger in Your Code

The logger is available throughout your application via dependency injection:

```python
from fastapi import APIRouter, Depends
from app.core.logging import get_logger

router = APIRouter()

@router.get("/items/{item_id}")
async def get_item(item_id: int, logger=Depends(get_logger)):
    logger.info("fetching_item", item_id=item_id)
    # Your logic here
    return {"id": item_id}
```

The logger automatically includes the correlation ID from the current request context. You can add contextual fields by passing them as keyword arguments:

```python
logger.info(
    "payment_processed",
    user_id=user.id,
    amount=payment.amount,
    currency=payment.currency,
    status="success"
)
```

### Adding Custom Redaction Rules

If you have application-specific fields that should be redacted (custom secret field names, internal identifiers), extend the redaction configuration:

```python
from app.core.logging import configure_logging

# Add your custom redaction patterns
configure_logging(
    redaction_patterns={
        "api_key": "***REDACTED***",
        "internal_token": "***REDACTED***",
        "user_ssn": "***REDACTED***",
    }
)
```

The default redaction rules already cover common secrets (password, token, secret, key, auth) and PII patterns. Adding custom rules ensures your application-specific sensitive fields are protected.

### Using Correlation IDs for Debugging

Correlation IDs are the key to understanding request flows. When a user reports an issue, ask them for a timestamp. Find logs with that timestamp, grab the correlation ID from any of those log entries, then search your logs for all entries with that ID:

```bash
# If using Elasticsearch
GET /logs/_search
{
  "query": {
    "match": {
      "correlation_id": "550e8400-e29b-41d4-a716-446655440000"
    }
  }
}
```

You'll see the complete timeline of what happened—every database query, API call, cache lookup, and decision the application made for that user's request.

!!!tip
Ensure your log aggregation platform preserves and indexes the `correlation_id` field. Most platforms do this automatically for JSON logs.


## Sentry Error Monitoring Setup

Sentry captures exceptions, performance issues, and errors that occur in your application, providing real-time alerting and detailed debugging information. It's especially valuable for catching issues in production that never appeared during testing.

### Enabling Sentry

Sentry is opt-in. To enable it, set your Sentry DSN:

```dotenv
SENTRY_DSN=https://your-key@your-organization.ingest.sentry.io/your-project-id
```

You can find your DSN in the Sentry project settings. If `SENTRY_DSN` is not set or empty, Sentry is disabled and error reporting is limited to local logs.

### Configuration

Fine-tune Sentry's behavior with these settings:

```dotenv
# The Sentry Data Source Name (DSN)
SENTRY_DSN=https://your-key@your-organization.ingest.sentry.io/your-project-id

# Environment label (e.g., production, staging, development)
SENTRY_ENVIRONMENT=production

# Release version for tracking which versions have issues
SENTRY_RELEASE=1.0.0

# Fraction of transactions to trace (0.0 = none, 1.0 = all)
# For high-volume production, start with 0.1 (10%) and increase as needed
SENTRY_TRACES_SAMPLE_RATE=0.1

# Fraction of transactions to profile (requires extra performance monitoring subscription)
SENTRY_PROFILES_SAMPLE_RATE=0.01
```

!!!note
**Sampling rates are critical for production systems.** If you capture 100% of traces from a high-traffic API, you'll quickly hit Sentry's quota limits. Start conservative (10% for traces, 1% for profiles) and adjust based on your traffic volume and Sentry plan.

### Automatic Integration

Sentry initializes automatically during application startup through the lifespan event handler. No manual setup code is needed—exceptions are captured and reported instantly.

Background job workers (Celery, APScheduler, or similar) also report to Sentry automatically. Worker crashes and exceptions are caught and sent with the same context as web errors.

### Adding Context and Tags

Sentry is most useful when you can identify affected users and versions. The application automatically tags errors with:

- `environment`: The deployment environment (production, staging, etc.)
- `release`: Your application version (set via `SENTRY_RELEASE`)
- `request_id`: The correlation ID from the request, making it easy to correlate with logs
- `job_id`: For background jobs, the job's unique identifier
- `tenant_id` or `org_id`: If applicable, to identify which customer or organization was affected

You can add custom tags to provide additional context:

```python
from fastapi import Request
import sentry_sdk

@router.get("/orders/{order_id}")
async def process_order(order_id: int, request: Request):
    sentry_sdk.set_tag("order_id", order_id)
    sentry_sdk.set_tag("customer_tier", "premium")
    
    try:
        # Your logic
    except Exception as e:
        # Exception will be tagged with order_id and customer_tier
        raise
```

### Filtering and Scrubbing

Sentry automatically scrubs sensitive data from error reports (passwords, tokens, credit cards, etc.). The application includes additional configuration to filter out noisy exceptions and ensure only meaningful errors reach your Sentry dashboard.

You can configure ignored exceptions and URL patterns to prevent unimportant errors from cluttering your dashboard:

```python
# In your Sentry configuration
sentry_sdk.init(
    dsn=SENTRY_DSN,
    # Ignore specific exceptions
    ignore_errors=[
        HTTPException(status_code=404),  # Not Found errors
        ValidationError,  # Input validation failures
    ],
    # Ignore errors from specific paths
    before_send=lambda event, hint: None if event.get("request", {}).get("url", "").startswith("/health") else event,
)
```

### Production Recommendations

For production Sentry deployments:

Set `SENTRY_ENVIRONMENT` to `production` so you can filter production errors separately from staging and development. Always set `SENTRY_RELEASE` to match your actual release version (from your CI/CD pipeline), allowing you to track which releases introduced bugs and when they were fixed.

Use a conservative trace sample rate (10% is reasonable for most applications). You can increase it during incidents to capture more debugging information, then lower it again afterward. Profile sampling (1%) is recommended for most applications; increase it only if you have specific performance questions.

Set up Sentry alerts for critical issues in production. Most teams want immediate notification (email, Slack, PagerDuty) for error rate spikes, repeated exceptions, and crashes.

!!!warning
**Never commit your SENTRY_DSN to version control.** Store it as a secret in your CI/CD environment, Kubernetes secret management, or cloud secret manager. The DSN contains authentication information that allows anyone with it to report to your Sentry project.


## Prometheus Metrics Setup

Prometheus metrics provide quantitative insights into your application's performance and health. Unlike logs (which are high-cardinality, unstructured events) and errors (which are exceptions), metrics are time-series data that excel at answering questions like "How many requests per second?" and "What's the 95th percentile response time?"

### Enabling Metrics

Metrics are optional and require the `[metrics]` extra during installation. Enable them via environment variables:

```dotenv
# Enable Prometheus metrics endpoint
METRICS_ENABLED=true

# The HTTP path where metrics are exposed (default: /metrics)
METRICS_PATH=/metrics

# Prefix for all metric names (helps when aggregating multiple services)
METRICS_NAMESPACE=my_app
```

Once enabled, metrics are exposed at `http://your-app:port/metrics` in Prometheus text format.

### What Metrics Are Collected

The application automatically collects metrics across several dimensions without requiring any code changes.

**HTTP Request Metrics** track every incoming request:

- `http_request_total`: Total requests by method, path, and status code
- `http_request_duration_seconds`: Histogram of response times (with percentiles: 0.5, 0.9, 0.95, 0.99)
- `http_request_in_progress`: Gauge of currently-processing requests

These metrics let you track traffic volume, detect performance regressions, and identify slow endpoints.

**Background Job Metrics** measure job processing:

- `job_executions_total`: Total job executions by job name and status
- `job_duration_seconds`: Histogram of job execution time
- `job_queue_size`: Gauge of pending jobs in the queue

**Webhook Metrics** track webhook processing:

- `webhook_events_received_total`: Events received by event type and status
- `webhook_processing_duration_seconds`: Processing time per event

**Integration Metrics** capture outbound calls:

- `outbound_http_requests_total`: Calls to external APIs by host and status
- `outbound_http_request_duration_seconds`: Round-trip time for external calls

**Failure and Retry Metrics**:

- `request_failures_total`: Total failures by type and severity
- `job_retries_total`: Retry attempts by job name and reason

### Configuring Prometheus to Scrape Metrics

Set up Prometheus to collect metrics from your application. In your `prometheus.yml` configuration:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'fastapi-app'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

For Kubernetes deployments, use the ServiceMonitor CRD (if using the Prometheus Operator):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: fastapi-app
spec:
  selector:
    matchLabels:
      app: fastapi-app
  endpoints:
  - port: metrics
    path: /metrics
    interval: 15s
```

### Creating Dashboards in Grafana

Once Prometheus is collecting metrics, create Grafana dashboards to visualize them. A useful dashboard might include:

**Request Rate Panel**: Shows `rate(http_request_total[5m])` by status code, helping you see traffic volume and error rate trends.

**Latency Panel**: Shows histogram quantiles from `http_request_duration_seconds`, giving you P50, P95, and P99 latencies over time.

**In-Progress Requests**: Shows `http_request_in_progress` to visualize request queue buildup.

**Job Execution Health**: Shows `job_executions_total` by status, with separate panels for job duration and queue size.

Here's a sample Grafana query for request rate by status:

```
rate(http_request_total[5m]) by (status)
```

And for P95 latency:

```
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))
```

### Production Recommendations

For production, set up alerts on key metrics. Alert on error rate spikes (when the percentage of 5xx responses exceeds a threshold), high latency (when P95 latency exceeds your SLA), and job queue buildup (when pending jobs exceed a safe level). Most teams also alert on request rate anomalies using statistical methods to detect unusual traffic patterns.

Tune your scrape interval based on your needs. A 15-second interval provides good resolution and is suitable for most applications. Very high-traffic applications might use 30 seconds to reduce storage costs.

!!!tip
Consider using recording rules in Prometheus to pre-compute common queries (like rate calculations and quantiles). This reduces query load and dashboard latency during incidents.


## OpenTelemetry Tracing Setup

Distributed tracing tracks requests across multiple services and systems. In a microservices architecture, a single user request might traverse multiple services, databases, and external APIs. A trace connects all these operations with a common trace ID, showing you the complete path and where time is spent.

### Enabling Tracing

Tracing is optional and requires the `[tracing]` extra. Enable it via environment variables:

```dotenv
# Enable OpenTelemetry tracing
TRACING_ENABLED=true

# OTLP (OpenTelemetry Protocol) collector endpoint
# For Jaeger: http://jaeger-collector:4317
# For Tempo: http://tempo:4317
# For generic OTLP: http://otel-collector:4317
TRACING_ENDPOINT=http://localhost:4317

# Service name (appears in trace UI and all spans)
TRACING_SERVICE_NAME=my-fastapi-app

# Fraction of traces to collect (0.0 to 1.0)
# Start low in high-traffic systems to control storage costs
TRACING_SAMPLE_RATE=0.1
```

### How Tracing Works

When a request arrives, OpenTelemetry generates a unique trace ID and attaches it to all downstream operations. The trace includes:

- **Spans** for each operation: HTTP requests, database queries, external API calls, cache operations
- **Timing information**: When each operation started and how long it took
- **Status**: Whether the operation succeeded or failed
- **Attributes**: Context-specific data (user ID, database query, API endpoint)
- **Events**: Significant moments during the span (cache hit, retry attempt, etc.)

The trace ID propagates across service boundaries using standard headers (W3C Trace Context), so if your FastAPI app calls another service, that service can continue the same trace.

### Automatic Span Creation

The application automatically creates spans for:

**HTTP Requests**: Every incoming HTTP request gets a span showing total request duration, status code, and request attributes (method, path, query parameters).

**Background Jobs**: Each job execution gets a span with job name, status, duration, and retry information.

**Outbound HTTP Calls**: Calls to external APIs are wrapped in spans showing the target URL, method, status, and round-trip time.

**Database Operations**: If you integrate with SQLAlchemy or similar ORMs, queries are traced.

You don't need to instrument these manually—they're handled automatically by the integration layer.

### Manual Instrumentation

For custom operations, you can create spans manually:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

def process_payment(payment_id: int):
    with tracer.start_as_current_span("process_payment") as span:
        span.set_attribute("payment_id", payment_id)
        span.set_attribute("amount", payment.amount)
        
        try:
            # Your logic here
            span.set_status(trace.Status(trace.StatusCode.OK))
        except Exception as e:
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            span.record_exception(e)
            raise
```

### Configuring Jaeger for Local Development

Jaeger is the easiest way to explore traces locally. Start it with Docker:

```bash
docker run -d \
  -p 16686:16686 \
  -p 4317:4317/udp \
  -p 4317:4317 \
  jaegertracing/all-in-one:latest
```

Then set your tracing configuration:

```dotenv
TRACING_ENABLED=true
TRACING_ENDPOINT=http://localhost:4317
TRACING_SERVICE_NAME=my-fastapi-app
TRACING_SAMPLE_RATE=1.0  # 100% sampling for development
```

Open `http://localhost:16686` to view the Jaeger UI. Make a request to your application, then search for traces by service name or trace ID.

### Connecting to Tempo for Production

Tempo is Grafana's long-term tracing backend, designed for production use at scale. Configure it similarly:

```dotenv
TRACING_ENABLED=true
TRACING_ENDPOINT=http://tempo:4317
TRACING_SERVICE_NAME=my-fastapi-app
TRACING_SAMPLE_RATE=0.1
```

Tempo stores traces and integrates with Grafana, allowing you to correlate traces with metrics and logs—query Prometheus for high latency endpoints, then click through to Tempo to see detailed traces for those slow requests.

### Connecting to a Generic OTLP Collector

Many platforms support OTLP (OpenTelemetry Protocol) directly. Configure any OTLP-compatible collector:

```dotenv
TRACING_ENABLED=true
TRACING_ENDPOINT=https://api.otlp-provider.com:4317
TRACING_SERVICE_NAME=my-fastapi-app
TRACING_SAMPLE_RATE=0.05
```

### Sampling Strategy

The `TRACING_SAMPLE_RATE` controls what fraction of traces are collected. This is crucial for managing storage costs in high-traffic systems.

In development, use 100% sampling (`TRACING_SAMPLE_RATE=1.0`) to see complete traces. In production, start with 10% (`TRACING_SAMPLE_RATE=0.1`). If you have very high traffic (thousands of requests per second), drop to 5% or 1%.

For targeted sampling based on error status or latency, implement a custom sampler in your initialization code.

### Production Recommendations

For production tracing deployments:

Enable tracing for all critical services and APIs, but use conservative sampling (5-10% for most applications) to manage storage. Index traces by service name, status (success/error), and duration so you can quickly find slow or failing requests.

Set up alerts on trace-derived metrics: alert when error rate increases, when P95 latency exceeds your SLA, or when a critical downstream service is slow.

Store traces for at least 24 hours (ideally 7 days) to give on-call engineers time to investigate incidents. Longer retention for production incidents helps post-mortem analysis.

!!!note
**Trace sampling is applied per-trace.** If you set `TRACING_SAMPLE_RATE=0.1`, approximately 10% of all traces (and all their spans) are collected. Within the application, correlation IDs in logs will match trace IDs when the trace is sampled, making it easy to jump between logs and traces.


## Production Recommendations

Moving observability from development to production requires deliberate choices about sampling, cost, and alerting. This section covers best practices for robust observability at scale.

### What to Enable

In production, enable all four observability systems:

**Structured Logging** is always on and essential. It has minimal overhead and is your primary tool for debugging when issues occur. Ensure logs are shipped to a centralized platform (ELK, Loki, CloudWatch, Datadog) with sufficient retention (at least 7 days for thorough investigation, 30 days is ideal).

**Sentry** should be enabled for any production deployment. It provides real-time error alerting and automatic grouping that reduces noise. Most teams find Sentry's free tier sufficient unless they have very high error volumes. At minimum, set up alerts for new errors and error rate spikes.

**Prometheus Metrics** provide the quantitative view of application health. Metrics are cheap to store and provide excellent dashboards and alerting. Enable metrics for all production services. The default metrics are low-overhead—add custom metrics cautiously to avoid exploding cardinality.

**OpenTelemetry Tracing** is valuable for understanding performance bottlenecks and debugging complex interactions, but at high traffic volumes, storing 100% of traces becomes expensive. Use sampling to control costs while maintaining visibility into important requests.

### Sampling Rates

Set conservative sampling rates for high-traffic systems to manage costs:

**Sentry traces** (`SENTRY_TRACES_SAMPLE_RATE`): Start with 5-10% for normal production traffic. Increase to 50% during active incidents for richer debugging data. If your application is extremely high-volume (100k+ requests/second), start with 1%.

**Sentry profiles** (`SENTRY_PROFILES_SAMPLE_RATE`): CPU profiling has overhead. Use 1% for normal operations, increasing to 5% during performance investigations.

**OpenTelemetry traces** (`TRACING_SAMPLE_RATE`): Similar to Sentry—5-10% for normal operations, and you can increase sampling during incidents. If your tracing backend has a query API, implement adaptive sampling: sample all errors and slow requests (requests exceeding your SLA), and randomly sample the rest.

### Alert Thresholds

Set up production alerts on these metrics and conditions:

**Error Rate**: Alert if the percentage of 5xx responses exceeds 1% for more than 5 minutes. Most applications have 5xx rates below 0.1%, so 1% indicates a serious problem.

**Latency**: Alert if P95 latency exceeds your SLA (e.g., 500ms for an API that should respond in 200ms) for more than 10 minutes. Set a separate alert for P99 latency at a higher threshold.

**Sentry Error Spike**: Alert if new errors are reported more than 10 times in 5 minutes. Most new errors are development issues; a spike indicates a production bug.

**Sentry Crash Loop**: Alert if a single error is reported 50+ times in 5 minutes. This indicates a critical bug that's severely impacting users.

**Job Queue Backlog**: If you use background jobs, alert if pending jobs exceed 1000 or if the queue stops processing (no jobs completed in 5 minutes).

**Service Unhealthy**: Use Prometheus to alert if a dependency (database, external API) becomes unavailable, often indicated by connection errors or timeout spikes.

### Retention and Archiving

Production observability data should be retained for compliance and investigation:

**Logs**: Retain in hot storage (searchable, queryable) for 30 days; archive to cold storage (S3, GCS) for 1 year for compliance. Most regulations require audit trails for at least 1 year.

**Metrics**: Retain raw metrics for 15 days; aggregate to hourly/daily granularity for 1 year. This balances query performance with historical analysis.

**Traces**: Retain detailed traces for 7 days; sample and archive key traces for 90 days. Detailed trace retention can be expensive, so keep it short unless you have specific compliance requirements.

**Errors (Sentry)**: Retain errors in Sentry for at least 30 days. Use Sentry's integration with your issue tracker (GitHub, Jira) to capture production errors as tickets for follow-up.

### Cost Optimization

Observability platforms charge based on data volume. Reduce costs without sacrificing visibility:

**Adjust sampling strategically**: Reduce Sentry and trace sampling from 10% to 5% for non-critical services. Sample errors and slow requests at 100%, and random requests at 5%.

**Filter noisy endpoints**: Exclude health checks (`/health`, `/ping`) from metrics and tracing. These endpoints generate noise without actionable insights.

**Reduce cardinality**: Be careful when adding custom metric labels. A label with unbounded cardinality (like user IDs in HTTP metrics) can create millions of metric series, exploding your bill. Use metric aggregation or separate custom metrics for high-cardinality data.

**Archive old data**: Use your observability platform's archiving features to move old data to cheaper storage while maintaining query capability.

!!!warning
**Correlate costs with traffic patterns.** If your traffic doubled yesterday, your observability costs will approximately double. Set up cost alerts in your cloud platform or observability dashboard to catch unexpected cost spikes early.


## Environment Variable Reference

This table lists all observability-related environment variables, their purpose, and typical values.

| Variable | Purpose | Type | Default | Example |
|----------|---------|------|---------|---------|
| `LOG_LEVEL` | Minimum log level to output | DEBUG, INFO, WARNING, ERROR, CRITICAL | INFO | INFO |
| `SERVICE_NAME` | Service name included in logs and spans | string | fastapi-app | my-api-service |
| `ENVIRONMENT` | Environment label (production, staging, dev) | string | development | production |
| `LOG_PRETTY_CONSOLE` | Pretty-print logs to console in dev | boolean | false | false |
| `SENTRY_DSN` | Sentry Data Source Name (enables Sentry) | string | (disabled) | https://key@sentry.io/123456 |
| `SENTRY_ENVIRONMENT` | Environment label in Sentry | string | (matches ENVIRONMENT) | production |
| `SENTRY_RELEASE` | Release version for tracking | string | (auto-detected) | 1.0.0 |
| `SENTRY_TRACES_SAMPLE_RATE` | Fraction of Sentry transactions to trace (0-1) | float | 0.1 | 0.1 |
| `SENTRY_PROFILES_SAMPLE_RATE` | Fraction of traces to profile (0-1) | float | 0.01 | 0.01 |
| `METRICS_ENABLED` | Enable Prometheus metrics endpoint | boolean | false | true |
| `METRICS_PATH` | HTTP path for metrics endpoint | string | /metrics | /metrics |
| `METRICS_NAMESPACE` | Prefix for all metric names | string | app | my_app |
| `TRACING_ENABLED` | Enable OpenTelemetry tracing | boolean | false | true |
| `TRACING_ENDPOINT` | OTLP collector endpoint | URL | (disabled) | http://localhost:4317 |
| `TRACING_SERVICE_NAME` | Service name in tracing | string | fastapi-app | my-fastapi-app |
| `TRACING_SAMPLE_RATE` | Fraction of traces to collect (0-1) | float | 0.1 | 0.1 |

### Configuration Examples

**Minimal Local Development Setup** (structured logs only):

```dotenv
LOG_LEVEL=DEBUG
SERVICE_NAME=my-api
ENVIRONMENT=development
```

**Staging with Error Monitoring**:

```dotenv
LOG_LEVEL=INFO
SERVICE_NAME=my-api
ENVIRONMENT=staging
SENTRY_DSN=https://your-key@sentry.io/your-project
SENTRY_ENVIRONMENT=staging
SENTRY_TRACES_SAMPLE_RATE=0.5
METRICS_ENABLED=true
```

**Production with Full Observability**:

```dotenv
LOG_LEVEL=WARNING
SERVICE_NAME=my-api
ENVIRONMENT=production
SENTRY_DSN=https://your-key@sentry.io/your-project
SENTRY_ENVIRONMENT=production
SENTRY_RELEASE=1.2.3
SENTRY_TRACES_SAMPLE_RATE=0.05
SENTRY_PROFILES_SAMPLE_RATE=0.01
METRICS_ENABLED=true
METRICS_NAMESPACE=my_api_prod
TRACING_ENABLED=true
TRACING_ENDPOINT=http://tempo.monitoring:4317
TRACING_SERVICE_NAME=my-api
TRACING_SAMPLE_RATE=0.05
```

This configuration provides comprehensive observability while managing costs through conservative sampling rates appropriate for high-traffic production systems.
