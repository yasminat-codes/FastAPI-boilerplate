# Runbook: Queue Backlog Incidents

This runbook covers situations where background job queues are growing faster than workers can process them. Backlogs can affect webhook processing, integration syncs, scheduled maintenance, and any other work that runs through the template's ARQ worker layer.

## Symptoms

- The `{namespace}_job_queue_size` metric is increasing over time instead of fluctuating near zero.
- The `JobQueueBacklog` alert fires (queue depth above threshold for 15+ minutes).
- Webhook providers report unacknowledged deliveries because processing jobs are delayed.
- Users report delayed processing of actions that depend on background jobs (email sends, sync operations, report generation).
- Structured logs show long gaps between `job_started` events for the same queue.

## Diagnosis

### Step 1: Confirm the backlog is real

Check current queue depth:

```sql
-- If you track job state in the database:
SELECT queue_name, status, COUNT(*)
FROM job_state_history
WHERE status IN ('pending', 'running')
GROUP BY queue_name, status
ORDER BY COUNT(*) DESC;
```

Check the Prometheus metric directly:

```
fastapi_template_job_queue_size
```

If the metric is flat at zero but users report delays, the issue may be job processing time rather than queue depth.

### Step 2: Identify which queue is affected

Not all queues are equal. The template supports multiple queue namespaces:

- `platform:webhook:ingest` — webhook event processing
- `platform:default:general` — general-purpose background work
- `client:integration:sync` — integration synchronization
- `platform:scheduled:maintenance` — scheduled maintenance jobs

Check if the backlog is concentrated on one queue or spread across all of them. A single-queue backlog usually points at a specific problem with that workload; a cross-queue backlog points at worker infrastructure.

### Step 3: Check worker health

1. **Are workers running?** Check `/api/v1/internal/health` for worker heartbeat data, or check your container orchestrator for worker process status.

2. **Are workers processing anything?** Check `{namespace}_job_executions_total` to see if the completion rate dropped.

3. **Are workers stuck on one job?** Check `{namespace}_jobs_in_progress` — if it stays at max concurrency for a long time, workers may be stuck on slow or hanging jobs.

4. **Check worker logs** for errors:
   ```
   job_execution_error job_name=process_webhook_event detail="database connection timeout"
   job_execution_error job_name=sync_contacts detail="429 rate limit exceeded"
   ```

### Step 4: Check for upstream causes

- **Database slow?** Workers that cannot get database connections will stall. Check database connection pool metrics and query latency.
- **Redis slow or full?** ARQ uses Redis as its queue backend. If Redis is under memory pressure, enqueue and dequeue operations slow down. Check Redis memory usage and latency.
- **External provider down?** If jobs call external APIs, a provider outage can cause jobs to hang on HTTP timeouts. Check [Third-Party Outages](third-party-outages.md).
- **Sudden traffic spike?** A burst of incoming webhooks or user actions can flood the queue faster than workers drain it.

## Resolution

### Immediate: Scale workers

The fastest way to drain a backlog is to add more worker capacity.

If you run workers as separate containers or pods, scale them up:

```bash
# Docker Compose
docker compose up --scale worker=4

# Kubernetes
kubectl scale deployment fastapi-worker --replicas=4
```

If workers run on a single machine, adjust the `WORKER_MAX_JOBS` setting to increase concurrency per process (but be careful about database and Redis connection limits).

### Immediate: Reduce inbound rate

If the queue is growing because of a traffic spike, slow down the source:

- **Webhook queues**: ask the provider to reduce delivery rate, or add a rate limiter on your webhook endpoint.
- **Integration sync queues**: pause non-critical sync schedules until the backlog drains.
- **User-triggered queues**: add API-level rate limiting to the endpoints that enqueue work.

### Investigate: Stuck or slow jobs

If workers are running but not completing jobs:

1. Check the `{namespace}_job_duration_seconds` histogram for jobs taking longer than expected.
2. Look for jobs stuck waiting on external resources (database, Redis, HTTP calls).
3. If a specific job type is slow, consider moving it to its own dedicated queue with its own concurrency profile so it does not block other work.

### Investigate: Job failure loops

If jobs are failing and being retried, each retry adds load without making progress:

1. Check `{namespace}_job_executions_total{status="failed"}` for a spike in failures.
2. Check dead-letter buildup — if many jobs are exhausting retries, the root cause needs fixing first.
3. If the failures are transient (e.g., provider returning 503), wait for recovery and let backoff handle it.
4. If the failures are permanent (e.g., bad data), stop retrying those jobs by fixing the data or marking them as non-retryable.

### Recovery: Drain the backlog

Once the root cause is addressed:

1. Keep extra workers running until the backlog is fully drained.
2. Monitor `{namespace}_job_queue_size` — it should trend toward zero.
3. Check that job success rate returns to normal.
4. Scale workers back down once the backlog is cleared and inbound rate has stabilized.
5. Replay any dead-lettered jobs that failed during the incident.

## Prevention

1. **Set queue-specific concurrency profiles**: use the template's `QueueConcurrencyProfile` to give webhook processing and integration sync queues dedicated worker capacity. See [Background Tasks](../background-tasks/index.md) for concurrency guidance.

2. **Monitor queue depth continuously**: the `JobQueueBacklog` alert catches sustained growth before it becomes a user-visible problem.

3. **Set job timeouts**: configure `job_timeout_seconds` per concurrency profile so a single hung job does not block a worker slot indefinitely.

4. **Right-size retry policies**: aggressive retries on a failing job amplify the load. Use the template's exponential backoff with jitter, and set `max_attempts` to a reasonable ceiling.

5. **Separate critical and bulk queues**: if your application has both latency-sensitive work (webhook processing) and bulk work (nightly data syncs), run them on separate queues with separate worker pools.

6. **Capacity plan for peak load**: know your normal queue throughput and set alerts at a level that gives you time to respond before users are affected.

## Further Reading

- [Background Tasks](../background-tasks/index.md) — queue naming, concurrency, and serialization guidance.
- [Retry and Backoff](../background-tasks/retry-backoff.md) — retry policies, dead-letter handling, and replay tooling.
- [Webhook Failures](webhook-failures.md) — when the backlog is specifically in the webhook processing queue.
- [Third-Party Outages](third-party-outages.md) — when slow external calls are causing jobs to stall.
