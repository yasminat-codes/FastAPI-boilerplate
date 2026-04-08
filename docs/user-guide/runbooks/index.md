# Runbooks and Alerting

Operational runbooks and alerting guidance for teams running applications built on this template. These runbooks assume you have the template's observability stack configured: structured logging, Sentry error monitoring, and optionally Prometheus metrics and OpenTelemetry tracing.

## Minimum Production Alerts

Before diving into individual runbooks, every production deployment should have these baseline alerts configured. The alert rules below reference the template's Prometheus metrics (see [Metrics and Tracing](../metrics-and-tracing.md) for the full metrics reference).

All metric names below assume the default `METRICS_NAMESPACE=fastapi_template` prefix. Replace `fastapi_template` with your configured namespace.

### API Alerts

These alerts detect problems with inbound HTTP request handling.

**High Error Rate** — fires when more than 5% of requests return 5xx responses over a 5-minute window:

```yaml
# Prometheus alerting rule
- alert: HighApiErrorRate
  expr: |
    (
      sum(rate(fastapi_template_http_requests_total{status_code=~"5.."}[5m]))
      /
      sum(rate(fastapi_template_http_requests_total[5m]))
    ) > 0.05
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "API error rate above 5%"
    description: "{{ $value | humanizePercentage }} of requests are returning 5xx errors."
```

**High Latency** — fires when p99 request latency exceeds 2 seconds over a 5-minute window:

```yaml
- alert: HighApiLatency
  expr: |
    histogram_quantile(0.99,
      sum(rate(fastapi_template_http_request_duration_seconds_bucket[5m])) by (le)
    ) > 2.0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "API p99 latency above 2 seconds"
    description: "p99 latency is {{ $value }}s over the last 5 minutes."
```

**Readiness Probe Failing** — fires when the `/api/v1/ready` endpoint returns non-200 responses. This typically means a critical dependency (database, Redis) is unreachable:

```yaml
- alert: ReadinessCheckFailing
  expr: probe_success{job="fastapi-readiness"} == 0
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "Application readiness check is failing"
    description: "The /api/v1/ready endpoint has been returning failures for 2 minutes. Check database and Redis connectivity."
```

### Worker Alerts

These alerts detect problems with background job processing.

**High Job Failure Rate** — fires when more than 10% of jobs are failing over a 10-minute window:

```yaml
- alert: HighJobFailureRate
  expr: |
    (
      sum(rate(fastapi_template_job_executions_total{status="failed"}[10m]))
      /
      sum(rate(fastapi_template_job_executions_total[10m]))
    ) > 0.1
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Job failure rate above 10%"
    description: "{{ $value | humanizePercentage }} of background jobs are failing."
```

**Dead-Letter Buildup** — fires when more than 10 messages have been dead-lettered in the past hour. This means jobs are exhausting all their retry attempts:

```yaml
- alert: DeadLetterBuildup
  expr: |
    sum(increase(fastapi_template_dead_letter_events_total[1h])) > 10
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Dead-letter events accumulating"
    description: "{{ $value }} jobs have been dead-lettered in the past hour. Check the dead_letter_record table for details."
```

**Job Queue Backlog** — fires when the pending job queue has been growing for more than 15 minutes. This indicates workers cannot keep up with incoming work:

```yaml
- alert: JobQueueBacklog
  expr: |
    fastapi_template_job_queue_size > 100
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: "Job queue backlog growing"
    description: "{{ $value }} jobs are pending in the queue. Workers may be overloaded or stuck."
```

### Webhook Alerts

These alerts detect problems with inbound webhook processing.

**High Webhook Rejection Rate** — fires when more than 20% of incoming webhooks are being rejected (signature failures, replay duplicates, malformed payloads):

```yaml
- alert: HighWebhookRejectionRate
  expr: |
    (
      sum(rate(fastapi_template_webhook_events_received_total{status="rejected"}[10m]))
      /
      sum(rate(fastapi_template_webhook_events_received_total[10m]))
    ) > 0.2
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Webhook rejection rate above 20%"
    description: "{{ $value | humanizePercentage }} of incoming webhooks are being rejected."
```

**Webhook Signature Failures** — fires when any provider's webhooks are failing signature verification. This could indicate a rotated signing secret or a spoofing attempt:

```yaml
- alert: WebhookSignatureFailures
  expr: |
    sum(increase(fastapi_template_webhook_signature_failures_total[15m])) by (provider) > 5
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Webhook signature failures for {{ $labels.provider }}"
    description: "{{ $value }} signature verification failures in the last 15 minutes."
```

### Outbound Integration Alerts

These alerts detect problems with external API calls your application makes.

**Circuit Breaker Open** — fires when the circuit breaker has tripped for any provider, meaning that provider is being treated as unavailable:

```yaml
- alert: CircuitBreakerOpen
  expr: fastapi_template_outbound_circuit_breaker_state > 0
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Circuit breaker open for {{ $labels.provider }}"
    description: "Outbound calls to {{ $labels.provider }} are being rejected by the circuit breaker."
```

**High Outbound Error Rate** — fires when more than 25% of outbound calls to a provider are failing:

```yaml
- alert: HighOutboundErrorRate
  expr: |
    (
      sum(rate(fastapi_template_outbound_requests_total{status_code=~"5.."}[10m])) by (provider)
      /
      sum(rate(fastapi_template_outbound_requests_total[10m])) by (provider)
    ) > 0.25
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High error rate calling {{ $labels.provider }}"
    description: "{{ $value | humanizePercentage }} of outbound calls to {{ $labels.provider }} are failing."
```

### Infrastructure Alerts

**High Retry Rate** — fires when the template is retrying an unusual number of operations across any component. A spike usually points at a systemic problem rather than isolated transient failures:

```yaml
- alert: HighRetryRate
  expr: |
    sum(increase(fastapi_template_retries_total[10m])) > 50
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High retry rate across components"
    description: "{{ $value }} retries in the last 10 minutes. Check structured logs for the affected component."
```

### Sentry-Based Alerts

If you do not run Prometheus, Sentry provides built-in alerting that covers the most critical failure modes:

- **Issue alerts**: fire when a new unhandled exception appears or when an existing issue regresses. Configure these in Sentry under Project Settings > Alerts.
- **Metric alerts**: fire when error count, transaction count, or custom metrics cross a threshold. Use these for error-rate and latency-based alerting without Prometheus.
- **Crash-free session alerts**: track the percentage of sessions without unhandled errors. Useful as a high-level health indicator.

At minimum, configure Sentry alerts for:

1. **New issue in production** — immediate notification on first occurrence.
2. **Issue frequency spike** — alert when an issue fires more than 10 times in 5 minutes.
3. **Transaction p95 above threshold** — alert when response times degrade.

### Alert Routing Guidance

| Severity | Routing | Response Time |
|----------|---------|---------------|
| `critical` | Page on-call engineer | Acknowledge within 5 minutes |
| `warning` | Slack/Teams channel notification | Investigate within 30 minutes |
| `info` | Dashboard or daily digest | Review during business hours |

## Runbooks

Each runbook covers a specific failure category. They follow a consistent structure: symptoms, diagnosis steps, resolution, and prevention.

- [Webhook Failures](webhook-failures.md) — signature failures, replay storms, poison payloads, and processing backlogs.
- [Queue Backlog Incidents](queue-backlog.md) — worker saturation, stuck jobs, and queue depth growth.
- [Third-Party Outages](third-party-outages.md) — external provider unavailability and degraded mode operation. Also see the [Integration Runbooks](../integrations/runbooks.md) for provider-specific guidance.
- [Migration Failures](migration-failures.md) — failed Alembic upgrades, schema drift, and rollback decisions.
- [Secret Rotation](secret-rotation.md) — rotating JWT keys, provider credentials, database passwords, and Redis passwords.

## Further Reading

- [Metrics and Tracing](../metrics-and-tracing.md) — full metrics reference and tracing configuration.
- [Error Monitoring](../error-monitoring.md) — Sentry configuration, filtering, and scrubbing.
- [Logging](../logging.md) — structured logging shape and correlation context.
- [Integration Runbooks](../integrations/runbooks.md) — provider-specific operational guidance.
