# Runbook: Third-Party Outages

This runbook covers what to do when an external provider your application depends on becomes unavailable or degraded. For detailed provider-specific diagnosis and resolution, also see the [Integration Runbooks](../integrations/runbooks.md).

## Symptoms

- The `{namespace}_outbound_circuit_breaker_state` metric shows a value greater than 0 (circuit breaker open or half-open) for one or more providers.
- Structured logs show `circuit_breaker_open`, `http_connection_error`, `http_timeout_error`, or `integration_request_error` events for a specific provider.
- The `{namespace}_outbound_requests_total{status_code=~"5.."}` counter is spiking for a provider.
- Background jobs that call the affected provider are failing and retrying or dead-lettering.
- Users report failures in features that depend on the external service.

## Diagnosis

### Step 1: Confirm the outage

1. **Check the provider's status page**. Most providers publish incident status:
   - Stripe: https://status.stripe.com
   - GitHub: https://www.githubstatus.com
   - Slack: https://status.slack.com
   - AWS: https://status.aws.amazon.com
   - Add your providers here when you clone the template.

2. **Check whether it is a full outage or partial degradation**:
   - Full outage: all operations fail (connection refused, DNS failure, all endpoints returning 503).
   - Partial degradation: some endpoints or regions work, others do not.
   - Rate limiting: the provider is up but rejecting your requests due to rate limits (see [Integration Runbooks — Rate Limit Exhaustion](../integrations/runbooks.md#rate-limit-exhaustion)).

3. **Check whether it is on your side**:
   - Can you reach the provider from a different network or machine?
   - Did your DNS, firewall, or egress proxy change recently?
   - Did you deploy code changes that broke the integration?

### Step 2: Assess impact

1. **Which features are affected?** Map the provider to the user-facing features that depend on it.
2. **Is the feature critical or optional?** Payment processing being down is critical. Social media post scheduling being down is not.
3. **Are there fallbacks available?** The template's resilience layer supports cached fallbacks and degraded mode operation (see [Resilience Patterns](../integrations/resilience.md)).
4. **How many jobs are queued or failing?** Check the `{namespace}_job_queue_size` and `{namespace}_dead_letter_events_total` metrics.

### Step 3: Check your circuit breaker state

The template's HTTP client includes an in-process circuit breaker. When it trips, new requests to the provider are rejected immediately without making HTTP calls:

- **Closed** (value 0): normal operation.
- **Open** (value 1): provider is considered down, requests are rejected immediately.
- **Half-open** (value 2): circuit breaker is probing the provider with a test request to see if it has recovered.

The circuit breaker resets automatically after the configured recovery timeout (default 30 seconds). You do not need to manually reset it unless you restart the application.

## Resolution

### Immediate: Enable degraded mode

If the affected feature has a fallback path:

1. **Cache fallback**: if your adapter uses the template's `with_fallback()` helper, cached data will be served automatically when the primary provider fails.
2. **Dry-run mode**: set the provider to dry-run mode so operations are logged but not executed:
   ```bash
   STRIPE_MODE=DRY_RUN
   ```
3. **Feature flag**: if the integration is behind a feature toggle, disable it:
   ```bash
   STRIPE_ENABLED=false
   ```

### Immediate: Slow down outbound calls

Continuing to hammer a degraded provider makes things worse for everyone:

1. **Reduce retry attempts**: set `HTTP_CLIENT_RETRY_MAX_ATTEMPTS=1` temporarily.
2. **Increase backoff**: set `HTTP_CLIENT_RETRY_BACKOFF_BASE_SECONDS=30` temporarily.
3. **Let the circuit breaker do its job**: if configured, it will reject requests without making HTTP calls.
4. **Pause non-critical background syncs**: stop scheduled jobs that call the provider.

### If the outage persists (30+ minutes)

1. **Defer failed operations**: build deferred retry requests for failed operations and enqueue them with long delays (see [Resilience Patterns — Deferred Retries](../integrations/resilience.md#deferred-retries)).
2. **Communicate to stakeholders**: let your team and users know that the affected feature is degraded and when you expect recovery.
3. **Monitor the dead-letter queue**: jobs that exhaust their retries during the outage will land in the dead-letter table. Plan to replay them after recovery.

### Recovery

Once the provider comes back online:

1. **Verify connectivity**: make a test call to the provider's API and confirm it succeeds.
2. **Wait for circuit breaker recovery**: the circuit breaker will automatically probe the provider after its timeout. Once the probe succeeds, the circuit closes and normal traffic resumes.
3. **Replay deferred retries**: check the background queue for jobs that were deferred during the outage. Monitor their success rate as they process.
4. **Replay dead-lettered jobs**: process dead-letter items in small batches. Do not replay everything at once — the provider may still be recovering and could rate-limit you.
5. **Clear stale caches**: if you served cached fallback data during the outage, invalidate those caches so fresh data is fetched.
6. **Restore normal settings**: revert any temporary setting changes (retry attempts, backoff, feature flags).

## Prevention

1. **Use the template's resilience patterns**: configure fallback providers, circuit breakers, and deferred retries for every external integration. See [Resilience Patterns](../integrations/resilience.md).
2. **Monitor outbound error rates**: the `HighOutboundErrorRate` and `CircuitBreakerOpen` alerts from the [alerting guide](index.md#outbound-integration-alerts) catch problems before users report them.
3. **Design for provider unavailability**: treat every external call as potentially failing. Keep user-facing request paths independent of synchronous external calls where possible.
4. **Test degraded mode**: periodically verify that your fallback paths work by simulating a provider outage (e.g., set the provider URL to a non-routable address and confirm fallbacks engage).
5. **Document provider SLAs**: know the uptime guarantees and incident communication channels for each provider you depend on.

## Further Reading

- [Integration Runbooks](../integrations/runbooks.md) — detailed provider-specific guidance including rate limits, authentication failures, and partial sync failures.
- [Resilience Patterns](../integrations/resilience.md) — fallback, partial failure, compensation, and deferred retry patterns.
- [Queue Backlog Incidents](queue-backlog.md) — when provider outages cause job queues to back up.
- [Webhook Failures](webhook-failures.md) — when the provider's webhook deliveries are affected by the outage.
