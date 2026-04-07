# Retry, Backoff, and Failure Handling

The template includes a complete retry, backoff, and failure handling system for background worker jobs. It covers exponential backoff with jitter, error classification, dead-letter storage, alerting hooks, manual replay, and idempotency guidance.

## Retry Overview

When a background job fails, the template distinguishes between retryable and non-retryable failures:

- **Retryable failures** (network timeouts, transient provider errors) trigger automatic retry with configurable backoff.
- **Non-retryable failures** (invalid payloads, authentication errors) skip retry entirely and fail immediately.

The `WorkerJob` base class handles this classification automatically when jobs raise the appropriate exception types.

## Exponential Backoff with Jitter

Retries use exponential backoff with full jitter by default to prevent thundering herds when multiple jobs fail at the same time.

### How backoff works

Each retry delay is calculated as:

```
delay = random(0, min(base * multiplier^attempt, max_delay))
```

The jitter component randomizes the actual delay between zero and the calculated ceiling, which spreads retries out in time instead of having them all fire at the same moment.

### BackoffPolicy

Configure backoff per job using `BackoffPolicy`:

```python
from src.app.workers import BackoffPolicy, WorkerJob, RetryableJobError, JobRetryPolicy

class SyncExternalDataJob(WorkerJob):
    job_name = "client.jobs.sync_external_data"
    retry_policy = JobRetryPolicy(max_tries=5, defer_seconds=10.0)
    backoff_policy = BackoffPolicy(
        base_delay_seconds=2.0,
        max_delay_seconds=120.0,
        multiplier=2.0,
        jitter=True,
    )

    @classmethod
    async def run(cls, ctx, envelope):
        try:
            await call_external_api(envelope.payload)
        except TimeoutError as exc:
            raise RetryableJobError("API timeout") from exc
```

When `backoff_policy` is set on a job, retryable errors use the backoff curve instead of the flat `defer_seconds` from `JobRetryPolicy`. If `backoff_policy` is `None` (the default), the template falls back to the existing flat-delay behavior.

### Predefined policies

The template includes three ready-made policies for common workload shapes:

| Policy | Base | Max | Use case |
|--------|------|-----|----------|
| `BACKOFF_FAST` | 1s | 30s | Short-lived transient network blips |
| `BACKOFF_STANDARD` | 5s | 300s | General-purpose retries |
| `BACKOFF_SLOW` | 30s | 1800s | Rate-limited or heavy external API calls |

```python
from src.app.workers import BACKOFF_STANDARD

class MyJob(WorkerJob):
    job_name = "client.jobs.my_job"
    backoff_policy = BACKOFF_STANDARD
    # ...
```

### Deterministic backoff for testing

Use `calculate_backoff_delay_deterministic` to get predictable delays in tests:

```python
from src.app.core.worker.retry import calculate_backoff_delay_deterministic

delay = calculate_backoff_delay_deterministic(base_delay=5.0, attempt=2, max_delay=300.0)
# Returns exactly 20.0 (5 * 2^2)
```

## Error Classification

### Failure categories

The `JobFailureCategory` enum defines standard categories for classifying why a job failed:

| Category | Retryable | Typical cause |
|----------|-----------|---------------|
| `TRANSIENT` | Yes | Network timeout, temporary unavailability |
| `RATE_LIMITED` | Yes | Provider rate limit exceeded |
| `PROVIDER_ERROR` | Yes | Upstream provider returned an error |
| `INTERNAL` | Yes | Unexpected internal error |
| `UNKNOWN` | Yes | Unclassified failure |
| `INVALID_PAYLOAD` | No | Bad input data, will never succeed |
| `AUTHENTICATION` | No | Credential or token failure |
| `AUTHORIZATION` | No | Permission denied |
| `NOT_FOUND` | No | Target resource does not exist |
| `CONFLICT` | No | State conflict, duplicate key, etc. |

Non-retryable categories are defined in `NON_RETRYABLE_CATEGORIES`. Use `is_retryable_category(category)` to check programmatically.

### Non-retryable errors

Raise `NonRetryableJobError` to signal that a job should fail immediately without consuming remaining retries:

```python
from src.app.workers import NonRetryableJobError, WorkerJob, JobFailureCategory

class ProcessOrderJob(WorkerJob):
    job_name = "client.jobs.process_order"

    @classmethod
    async def run(cls, ctx, envelope):
        order_id = envelope.payload["order_id"]
        order = await fetch_order(order_id)

        if order is None:
            raise NonRetryableJobError(
                f"Order {order_id} not found",
                error_category=JobFailureCategory.NOT_FOUND,
                error_code="ORDER_NOT_FOUND",
            )

        await process(order)
```

When `NonRetryableJobError` is raised, the template:

1. Fires all alert hooks with `is_final_attempt=True`.
2. Logs the failure at ERROR level.
3. Lets the exception propagate (ARQ marks the job as failed).

### Retryable errors

Raise `RetryableJobError` for failures that should be retried. If the job has a `backoff_policy`, the retry delay follows the backoff curve. Otherwise it uses the explicit `defer_seconds` or falls back to the policy default:

```python
from src.app.workers import RetryableJobError

# Use backoff curve (if backoff_policy is set on the job)
raise RetryableJobError("provider temporarily unavailable")

# Override defer for this specific retry
raise RetryableJobError("rate limited", defer_seconds=60.0)
```

## Dead-Letter Storage

When a job exhausts all retries, it can be dead-lettered into the shared `dead_letter_record` table for operator triage.

### Writing dead-letter records

```python
from src.app.workers import build_dead_letter_request_from_job, job_dead_letter_store

# Build a dead-letter request from a failed job
request = build_dead_letter_request_from_job(
    job_name="client.jobs.send_email",
    queue_name="arq:client:email",
    envelope=envelope_dict,
    error=caught_exception,
    attempt=3,
    max_attempts=3,
    error_category="transient",
)

# Persist into the shared dead-letter ledger
async with get_session() as session:
    result = await job_dead_letter_store.dead_letter(session, request)
    await session.commit()
```

### Triaging dead-letter records

```python
from src.app.workers import job_dead_letter_store

# After investigating and fixing the root cause
await job_dead_letter_store.mark_resolved(session, record)

# Or archive records that do not need further action
await job_dead_letter_store.mark_archived(session, record)

# Or mark as retrying before replay
await job_dead_letter_store.mark_retrying(session, record, next_retry_at=some_datetime)
```

The dead-letter store uses the `jobs` namespace in the shared `dead_letter_record` table, keeping job failures separate from webhook dead letters (`webhooks` namespace).

## Alerting Hooks

Every `WorkerJob` calls configured alert hooks on failure so operators can be notified about degraded job processing.

### Default behavior

By default, `WorkerJob` uses `LoggingAlertHook`, which logs failures using structlog:

- Non-final attempts log at WARNING level.
- Final attempts (and `NonRetryableJobError`) log at ERROR level.

### Custom alert hooks

Implement the `JobAlertHook` protocol to add custom alerting:

```python
from src.app.workers import JobAlertHook, WorkerJob

class SlackAlertHook:
    async def on_job_failure(
        self,
        *,
        job_name: str,
        envelope_data: dict,
        attempt: int,
        max_attempts: int,
        error_category: str | None,
        error_message: str,
        is_final_attempt: bool,
    ) -> None:
        if is_final_attempt:
            await send_slack_alert(
                f"Job {job_name} failed permanently after {attempt}/{max_attempts} attempts: {error_message}"
            )

class CriticalSyncJob(WorkerJob):
    job_name = "client.jobs.critical_sync"
    alert_hooks = [LoggingAlertHook(), SlackAlertHook()]
    # ...
```

Alert hooks are called for every failure. If a hook raises an exception, the error is logged but does not interrupt the job or other hooks.

## Manual Job Replay

Dead-lettered jobs can be replayed by re-enqueueing them from the stored payload.

### Building a replay request

```python
from src.app.workers import build_replay_request_from_dead_letter, replay_dead_lettered_job

# Build a replay request from a dead-letter record
replay_request = build_replay_request_from_dead_letter(dead_letter_record)

# Optionally override the target queue
replay_request = ReplayRequest(
    dead_letter_record_id=record.id,
    job_name="client.jobs.send_email",
    payload={"user_id": "u1"},
    override_queue="arq:client:email-retry",
)
```

### Executing the replay

```python
result = await replay_dead_lettered_job(arq_pool, replay_request)

if result.enqueued:
    # Mark the dead-letter record as resolved after confirming success
    await job_dead_letter_store.mark_resolved(session, record)
else:
    logger.error("Replay failed", error=result.error_message)
```

The replay function does not automatically mark the dead-letter record as resolved. The caller must confirm the replay succeeded before updating the record status.

## Idempotent Job Execution

Jobs that may be retried should be designed to produce the same result when executed multiple times with the same input. Here is guidance for making jobs idempotent:

### Use the idempotency key ledger

The template includes a shared `idempotency_key` table. For operations that must not be duplicated (sending an email, charging a payment, creating a record), check the idempotency ledger before executing:

```python
class SendInvoiceJob(WorkerJob):
    job_name = "client.jobs.send_invoice"

    @classmethod
    async def run(cls, ctx, envelope):
        invoice_id = envelope.payload["invoice_id"]
        idempotency_key = f"send_invoice:{invoice_id}"

        # Check if this operation was already completed
        existing = await lookup_idempotency_key(session, idempotency_key)
        if existing is not None:
            return {"status": "already_sent", "key": idempotency_key}

        await send_invoice(invoice_id)
        await record_idempotency_key(session, idempotency_key)
        return {"status": "sent"}
```

### Design principles

1. **Prefer upserts over inserts** for state changes that might be retried.
2. **Use the correlation ID** from the job envelope as part of the idempotency key for request-scoped deduplication.
3. **Store the operation result** alongside the idempotency key so retried jobs can return the cached result without re-executing.
4. **Set appropriate expiry windows** on idempotency keys to balance deduplication coverage against storage growth.
5. **Separate side effects from computation**: compute the result first, then apply side effects (database writes, API calls) inside a narrow idempotency guard.
6. **Log idempotent skips** so operators can distinguish genuine re-executions from duplicate noise.

### What to guard

Guard operations that have external side effects: sending emails, charging payments, creating records in third-party systems, publishing events. Pure reads and local computations do not need idempotency protection.

### What not to guard

Do not wrap the entire job in an idempotency check if only a subset of its work has side effects. Guard the specific side-effect step instead, so partial progress from a previous attempt is preserved.

## Next Steps

For the shared persistence ledgers (dead-letter records, idempotency keys, job state history), see [Automation Persistence Patterns](../database/automation-patterns.md). For worker configuration and queue setup, see the [Background Tasks overview](index.md).
