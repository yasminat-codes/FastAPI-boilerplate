# Integration Runbooks

Operational guidance for diagnosing and resolving failures when third-party provider integrations degrade or become unavailable.

## Identifying a Degraded Provider

Before diving into resolution steps, confirm that the integration is actually degraded.

### Symptoms of a Degraded Provider

- **High error rates** in structured logs (look for `integration_request_error` events)
- **Circuit breaker tripping** (look for `circuit_breaker_open` log events)
- **Health check failures** on `/api/v1/internal/health` (if you expose integration health)
- **Rising dead-letter queue** — jobs failing and piling up in the dead-letter ledger
- **Rate limit exhaustion** — 429 responses in your logs

### Diagnostic Steps

1. **Check structured logs** for the affected provider:
   ```
   # Look for entries like:
   integration_request_error provider=stripe operation=create_charge
   circuit_breaker_open provider=slack
   http_error status=502 provider=github
   ```

2. **Check circuit breaker state** (if enabled):
   - In-process circuit breaker state is not persisted; restart will clear it
   - Look for `circuit_breaker_open` or `circuit_breaker_probe` logs
   - Check the HTTP client settings: `HTTP_CLIENT_CIRCUIT_BREAKER_ENABLED`

3. **Check the provider's status page**:
   - Stripe: https://status.stripe.com
   - GitHub: https://www.githubstatus.com
   - Slack: https://status.slack.com
   - AWS: https://status.aws.amazon.com
   - (Add your specific providers here)

4. **Review recent changes**:
   - Did credentials rotate recently?
   - Did API base URL change?
   - Did anyone deploy integration code changes?
   - Did you recently enable or disable sandboxing?

5. **Check if it's specific to one operation** or **all operations**:
   - One operation failing = bug in adapter code or provider API changed
   - All operations failing = authentication, connectivity, or availability issue

## Provider Unavailable (5xx / Connection Refused)

The provider is down or unreachable (5xx responses, connection timeouts, DNS failures).

### Immediate Actions

1. **Confirm the outage** on the provider's status page
2. **Check error details** in logs:
   ```
   integration_request_error provider=stripe detail="500 Internal Server Error"
   http_connection_error provider=github detail="connection refused"
   http_timeout_error provider=slack detail="30s timeout exceeded"
   ```

3. **Assess impact**:
   - Which operations are affected? (e.g., just payment processing, or all Stripe calls?)
   - Which user flows are blocked?
   - Are fallbacks available? (cached data, degraded modes?)

4. **Notify stakeholders** if user-facing operations are affected

5. **Enable fallback if available**:
   - If you have a fallback provider (cache, secondary API), activate it
   - Update integration settings if your system supports runtime toggles
   - Communicate to users that they're in degraded mode (if UI-visible)

6. **Slow down requests** to avoid piling on the provider:
   - Reduce retry attempts: set `HTTP_CLIENT_RETRY_MAX_ATTEMPTS=1`
   - Increase backoff delays: set `HTTP_CLIENT_RETRY_BACKOFF_BASE_SECONDS=10`
   - Stop new requests if possible (circuit breaker will help here)

### If the Outage Persists (30+ minutes)

1. **Defer failed operations to background queue**:
   - Build deferred retry requests for failed operations (see [Resilience Patterns](resilience.md#deferred-retries))
   - Enqueue them with a 5-10 minute initial delay
   - Exponential backoff: 1 min, 2 min, 4 min, 8 min, etc.

2. **Temporarily disable the integration** if it's optional:
   ```bash
   # In your settings or environment:
   STRIPE_ENABLED=false
   STRIPE_MODE=DRY_RUN  # Or equivalent
   ```
   - Dry-run mode logs what would execute without making HTTP calls
   - No outbound requests = no failures to retry

3. **Check dead-letter queue** for jobs that gave up:
   ```sql
   SELECT * FROM dead_letter_record 
   WHERE integration='stripe' 
   ORDER BY failed_at DESC 
   LIMIT 50;
   ```
   - Review the reasons they failed
   - Plan manual replay once provider recovers

### Recovery

Once the provider comes back online:

1. **Verify health** with a test call:
   ```bash
   # Manual test of the integration endpoint
   curl -H "Authorization: Bearer sk_live_xxx" https://api.stripe.com/v1/balance
   ```

2. **Restart circuit breaker** (if using in-process breaker):
   - Restart the application server to clear circuit breaker state
   - Or wait for the configured recovery timeout (default 30 seconds) for half-open probe

3. **Replay deferred retries**:
   - Check how many jobs are queued with the provider
   - Verify they're retrying with backoff (not immediately failing again)
   - Monitor error rates as they process

4. **Catch up on dead-letter items**:
   - Replay items from dead-letter queue in small batches
   - Monitor for success before reprocessing the next batch
   - Keep retries slow to avoid overwhelming the provider again

5. **Clear cache (if applicable)**:
   - If you cached failed responses, invalidate them so fresh data is fetched
   - Resume accepting new requests from users

## Rate Limit Exhaustion

The provider is rejecting requests with 429 (Too Many Requests) responses.

### Immediate Actions

1. **Check the `Retry-After` header** in the 429 response:
   ```
   HTTP/1.1 429 Too Many Requests
   Retry-After: 60
   ```
   - This tells you how long to wait before retrying (in seconds)
   - The template HTTP client respects this header automatically

2. **Check rate limit details** in logs:
   ```
   integration_request_error provider=stripe status=429
   http_rate_limit_error provider=github remaining=0 reset_at=2024-04-08T12:30:00Z
   ```

3. **Identify the cause**:
   - **Sudden spike** = traffic surge or bug causing repeated calls
   - **Gradual exhaustion** = normal usage approaching provider limit
   - **Unusual pattern** = recursive loop or duplicate logic (code bug)

4. **Reduce request rate immediately**:
   - Pause non-critical operations (e.g., background syncs)
   - Increase retry backoff: set `HTTP_CLIENT_RETRY_BACKOFF_BASE_SECONDS=30`
   - Implement client-side rate limiting with a queue
   - Batch requests where possible (e.g., bulk create instead of individual creates)

5. **Wait for limit reset**:
   - The `Retry-After` or `X-RateLimit-Reset` header tells you when you can resume
   - The template retries automatically; just monitor that retries are succeeding

### Prevention

1. **Understand provider limits**:
   - Stripe: varies by endpoint (typically 100 requests per second)
   - GitHub: 5,000 requests per hour for authenticated users
   - Slack: varies by method (typically 1 request per second for most APIs)
   - Document your provider's limits and where you use them

2. **Implement request batching**:
   - Create multiple resources in one call instead of N separate calls
   - Filter before syncing instead of syncing everything

3. **Use circuit breaker** to avoid piling on:
   - Enable: `HTTP_CLIENT_CIRCUIT_BREAKER_ENABLED=true`
   - Set failure threshold low: `HTTP_CLIENT_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5`
   - After 5 failures, circuit opens and rejects new requests immediately (no 429 spam)

4. **Cache frequently accessed data**:
   - Reduce redundant calls
   - Use TTLs appropriate to how often the data changes

## Authentication Failure

The provider rejected your request with 401 (Unauthorized) or 403 (Forbidden).

### Immediate Actions

1. **Check the error detail** in logs:
   ```
   integration_auth_error provider=stripe detail="invalid API key"
   http_auth_error status=401 detail="expired token"
   ```

2. **Verify credentials are set**:
   - Is `STRIPE_API_KEY` defined in your environment?
   - Is it the correct key for the environment (sandbox vs. production)?
   - Print the first/last few characters to confirm it's not empty or malformed

3. **Check credential format**:
   - Stripe: `sk_live_xxx` or `sk_test_xxx` (starts with `sk_`)
   - GitHub: Personal access token (40+ characters) or OAuth token
   - Slack: `xoxb-...` (bot token) or `xoxp-...` (user token)
   - Verify it matches the provider's expected format

4. **Test with provider's CLI or UI**:
   ```bash
   # Stripe CLI
   stripe login
   stripe balance
   
   # GitHub CLI
   gh auth login
   gh api /user
   
   # Slack
   curl -H "Authorization: Bearer xoxb-xxx" https://slack.com/api/auth.test
   ```
   - If the CLI works, the token is valid; issue is in your app
   - If the CLI fails, token needs rotation

### Resolution

1. **Rotate credentials** if they're expired or compromised:
   - Generate a new key/token in the provider's console
   - Update your environment variables
   - Restart the application (or hot-reload if you support it)

2. **For OAuth tokens**:
   - Check if the token has been revoked
   - Refresh the token using the refresh_token (if available)
   - Re-authenticate if refresh fails

3. **For API keys with rotation policies**:
   - Check when the key was last rotated
   - If it's older than your rotation interval (e.g., 90 days), rotate it proactively
   - See [Secret Management](contracts.md#secret-management) for rotation patterns

4. **Verify permission scopes**:
   - For OAuth, confirm the token has required scopes
   - For API keys, confirm the key has the right permissions in the provider console
   - Example: GitHub token may lack `repo` scope for private repos

## Partial Sync Failure

A batch operation succeeded for some items but failed for others. You're seeing a `PartialFailureResult` with a high failure ratio, or errors on a subset of items.

### Diagnosis

1. **Check structured logs** for patterns:
   ```
   partial_failure_result provider=stripe succeeded=95 failed=5 ratio=0.05
   integration_request_error provider=stripe operation=batch_create detail="invalid email: user5@"
   ```

2. **Classify the failures**:
   - **Validation errors** (400): Data issue in the failed items (bad email, missing field)
   - **Rate limit** (429): Provider rejected due to rate; should retry
   - **Server error** (5xx): Provider bug; should retry
   - **Auth error** (401/403): Credential issue; fix credentials then retry

3. **Identify which items failed**:
   - Are they all the same type (e.g., all non-ASCII names)?
   - Are they random (indicates transient issue)?
   - Are they at a boundary (last 5% of batch)?

### Resolution

1. **For validation errors**:
   - Fix the data in the failed items (trim whitespace, validate email, etc.)
   - Retry just the failed items
   - Example: If 5 customers have invalid emails, fix those 5 and re-enqueue

2. **For rate limit or server errors**:
   - Implement exponential backoff and retry
   - Defer to background queue with initial delay (see [Deferred Retries](resilience.md#deferred-retries))
   - Example: Wait 60 seconds, then retry with backoff

3. **For partial success when expecting all-or-nothing**:
   - Decide whether to roll back all (use [Compensation](resilience.md#compensating-actions))
   - Or accept partial success and manually reconcile later

4. **Manual reconciliation**:
   - Query your database for items that were synced
   - Compare against the provider's state
   - Identify gaps and manually sync missing items

## Dead-Letter Buildup

Jobs have failed all their retry attempts and accumulated in the dead-letter ledger. This is your last-chance queue for manual intervention.

### Monitoring

1. **Check dead-letter count**:
   ```sql
   SELECT COUNT(*), integration, operation 
   FROM dead_letter_record 
   WHERE created_at > NOW() - INTERVAL 1 HOUR 
   GROUP BY integration, operation
   ORDER BY COUNT(*) DESC;
   ```

2. **Query recent dead-letters**:
   ```sql
   SELECT job_id, integration, operation, error, failed_at 
   FROM dead_letter_record 
   WHERE created_at > NOW() - INTERVAL 1 HOUR 
   ORDER BY failed_at DESC 
   LIMIT 50;
   ```

3. **Alert on buildup**:
   - Set up monitoring alert: if dead-letter count grows by >100/hour, page on-call
   - Set a dashboard widget to track dead-letter volume by provider and operation

### Resolution

**Classify the failures** in the dead-letter queue:

1. **Transient failures that may now be resolved**:
   - Error: "503 Service Unavailable" (provider was down, likely recovered)
   - Action: Replay the job; it will likely succeed now

2. **Permanent failures that require code changes**:
   - Error: "404 Not Found" (resource was deleted, endpoints changed)
   - Action: Fix the adapter code and deploy; then replay
   - Example: Provider changed API endpoint format

3. **Data issues that require manual fixing**:
   - Error: "400 Bad Request - invalid email format"
   - Action: Manually fix the data in the database, then replay

**Replay dead-letters** in batches:

```sql
-- Step 1: Get the job IDs to replay
SELECT job_id FROM dead_letter_record 
WHERE integration = 'stripe' 
AND failed_at > NOW() - INTERVAL 2 HOURS 
LIMIT 20;

-- Step 2: Requeue them with a background job
INSERT INTO job_queue (job_id, payload, created_at)
SELECT job_id, payload, NOW() 
FROM dead_letter_record 
WHERE integration = 'stripe' AND failed_at > NOW() - INTERVAL 2 HOURS
LIMIT 20;

-- Step 3: Monitor the replayed jobs
SELECT status, COUNT(*) FROM job_queue WHERE job_id IN (...)
GROUP BY status;
```

**Discard dead-letters** if they're unrecoverable:

```sql
-- Only delete after confirming with stakeholders
DELETE FROM dead_letter_record 
WHERE integration = 'stripe' 
AND failed_at < NOW() - INTERVAL 30 DAYS;
```

### Prevention

1. **Fix root causes quickly**:
   - Don't let dead-letters pile up waiting for investigation
   - Set SLA: investigate dead-letter spike within 30 minutes

2. **Increase max attempts before dead-lettering**:
   - Default might be 3 attempts; increase to 5-10 for flaky providers
   - But set reasonable limits; don't retry forever

3. **Implement exponential backoff** with a ceiling:
   - Retry immediately, then 1s, 2s, 4s, 8s, 30s, 30s, 30s (cap at 30 seconds)
   - This gives transient issues time to recover without waiting hours

## Template Extension Points

When you clone this template for a specific project, add provider-specific runbook sections here.

### Adding a New Provider

For each integration you add, document:

1. **Provider status page URL**
2. **Common failure modes** and their indicators
3. **Rate limit specifics** (requests/second, requests/hour, burst limits)
4. **Authentication rotation schedule** and process
5. **Known issues or quirks** of their API (e.g., eventual consistency delays)

### Example: Custom Stripe Runbook Section

```markdown
## Stripe-Specific Issues

### Webhook Failures

Webhooks are failing with 5xx responses.

**Symptoms:**
- Logs show stripe_webhook_handler returning 500
- Stripe retries webhook deliveries (check Developers > Webhooks > Event deliveries)

**Diagnosis:**
1. Check the handler code: src/app/integrations/stripe/webhooks.py
2. Verify event parsing: is the event schema still valid?
3. Check database: can you write to events table?

**Resolution:**
- Fix the handler code (likely parsing issue)
- Deploy
- Manually replay failed events via Stripe dashboard

### Stripe Sandbox vs. Live Mode

Always verify you're using the right environment.

- Sandbox keys start with `sk_test_`
- Live keys start with `sk_live_`
- Never use live keys in development or staging
```

## Further Reading

- [Resilience Patterns](resilience.md) — Fallback, partial failure, compensation, and deferred retry patterns
- [Integration Contracts](contracts.md) — Full contract layer for building adapters
