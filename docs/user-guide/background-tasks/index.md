# Background Tasks

The boilerplate includes a robust background task system built on ARQ (Async Redis Queue) for handling long-running operations asynchronously. This enables your API to remain responsive while processing intensive tasks in the background.

## Overview

Background tasks are essential for operations that:

- **Take longer than 2 seconds** to complete
- **Don't block user interactions** in your frontend
- **Can be processed asynchronously** without immediate user feedback
- **Require intensive computation** or external API calls

## Quick Example

```python
from src.app.platform import queue
from src.app.workers.jobs import JobEnvelope, JobRetryPolicy, RetryableJobError, WorkerJob


class SendWelcomeEmailJob(WorkerJob):
    job_name = "client.jobs.send_welcome_email"
    retry_policy = JobRetryPolicy(max_tries=5, defer_seconds=30.0)

    @classmethod
    async def run(cls, ctx: dict[str, object], envelope: JobEnvelope) -> str:
        user_id = envelope.payload["user_id"]
        email = envelope.payload["email"]
        logger = cls.get_logger(ctx=ctx, envelope=envelope)

        logger.info("Sending welcome email", user_id=user_id)

        try:
            await send_email_service(email, "Welcome!")
        except TemporaryEmailProviderError as exc:
            raise RetryableJobError("email provider unavailable", defer_seconds=60.0) from exc

        return f"Welcome email sent to {email}"


@router.post("/users/", response_model=UserRead)
async def create_user(user_data: UserCreate):
    user = await crud_users.create(db=db, object=user_data)

    if queue.pool is not None:
        await SendWelcomeEmailJob.enqueue(
            queue.pool,
            payload={"user_id": user["id"], "email": user["email"]},
            tenant_id=current_tenant_id,
            organization_id=current_organization_id,
            metadata={"source": "api.users.create"},
        )

    return user
```

## Architecture

### ARQ Worker System
- **Redis-Based**: Uses Redis as the message broker for job queues
- **Async Processing**: Fully asynchronous task execution  
- **Worker Pool**: Multiple workers can process tasks concurrently
- **Job Persistence**: Tasks survive application restarts

### Task Lifecycle
1. **Enqueue**: Tasks are added to Redis queue from API endpoints
2. **Processing**: ARQ workers pick up and execute tasks
3. **Results**: Task results are stored and can be retrieved
4. **Monitoring**: Track task status and execution history

### Template Job Pattern

- Define jobs as subclasses of `WorkerJob` so queue names, retry policy, and runtime settings live with the job itself.
- Every worker job receives a `JobEnvelope` containing `payload`, `correlation_id`, `tenant_context`, `retry_count`, and free-form `metadata`.
- `WorkerJob.enqueue(...)` automatically adopts the currently bound `correlation_id` when the caller omits it, so request-triggered jobs preserve correlation context by default.
- Use `WorkerJob.get_logger(...)` or `src.app.workers.logging.get_job_logger(...)` for structured logs that automatically carry shared job context.
- Register worker jobs through `src.app.workers.settings.WorkerSettings`.
- Raise `RetryableJobError` for failures that should be retried with the job's configured retry policy.
- Use `JobRetryPolicy` to override per-job retry limits when a job should differ from the template-wide `WORKER_*` defaults.
- Worker startup and shutdown are wired through a shared resource stack so the template can prime the database engine, worker-side Redis aliases, optional cache and rate-limit clients, and Sentry without duplicating lifecycle logic in each project.
- If a cloned project needs a durable audit trail for worker executions, pair `WorkerJob` with the shared `Job State History` ledger from [Automation Persistence Patterns](../database/automation-patterns.md). Use `workflow_execution` for larger multi-step orchestration records and `job_state_history` for per-job run history, retry tracking, and operator visibility.
- The template does not expose a generic `/tasks` submission endpoint by default; queue-producing routes should belong to project-specific APIs.

## Key Features

**Scalable Processing**
- Multiple worker instances for high throughput
- Automatic load balancing across workers
- Configurable concurrency per worker

**Reliable Execution**
- Exponential backoff with jitter for retries — see [Retry and Backoff](retry-backoff.md)
- Non-retryable error classification and dead-letter storage
- Manual replay tooling for dead-lettered jobs
- Alerting hooks for repeated job failures
- Graceful shutdown and task cleanup

**Database Integration**
- Shared database sessions with main application
- CRUD operations available in background tasks
- Transaction management and error handling

## Common Use Cases

- **Email Processing**: Welcome emails, notifications, newsletters
- **File Operations**: Image processing, PDF generation, file uploads
- **External APIs**: Third-party integrations, webhooks, data sync
- **Data Processing**: Report generation, analytics, batch operations
- **ML/AI Tasks**: Model inference, data analysis, predictions

## Getting Started

The template provides a reusable worker job base out of the box. Define a job by subclassing `WorkerJob`, read runtime inputs from the `JobEnvelope`, register it in `WorkerSettings.functions`, and enqueue it from your API endpoints with `YourJob.enqueue(...)`.

The default registry also includes `WorkerProbeJob`, a minimal internal job that keeps the worker runtime bootable and available for smoke checks without shipping demo business behavior in the shared template.

The API now exposes `/api/v1/internal/health` as a safe operator-facing diagnostics surface. It reads the ARQ heartbeat sentinel from the configured queue so you can confirm that a worker has checked in recently without shipping a demo job endpoint in the shared template, and it now requires the template's internal-access permission instead of being a public endpoint.

## Configuration

Basic Redis queue configuration:

```bash
# Redis Queue Settings  
REDIS_QUEUE_HOST=localhost
REDIS_QUEUE_PORT=6379
REDIS_QUEUE_DB=0
REDIS_QUEUE_CONNECT_TIMEOUT=5
REDIS_QUEUE_CONNECT_RETRIES=5
REDIS_QUEUE_RETRY_DELAY=1
REDIS_QUEUE_RETRY_ON_TIMEOUT=true
REDIS_QUEUE_SSL=false

# Worker Runtime Settings
WORKER_QUEUE_NAME=arq:queue
WORKER_MAX_JOBS=10
WORKER_JOB_MAX_TRIES=3
WORKER_JOB_RETRY_DELAY_SECONDS=5.0
WORKER_KEEP_RESULT_SECONDS=3600
WORKER_KEEP_RESULT_FOREVER=false
WORKER_JOB_EXPIRES_EXTRA_MS=86400000
```

The worker runtime builds ARQ Redis connection settings from these values, including timeout, retry, and TLS options, so queue connectivity can be tuned per deployment without changing code. The `WORKER_*` settings also control the shared queue name, concurrency, default retry policy for `WorkerJob`, and how long job results remain available for inspection.

## Queue Naming Conventions

The template uses a hierarchical naming scheme for Redis-backed queues so that
operators can identify queue traffic at a glance in monitoring tools.

### Naming scheme

```
<prefix>:<scope>:<purpose>
```

- **prefix** – shared namespace prefix, defaults to `arq`.
- **scope** – logical boundary such as `platform`, `webhooks`, `client`, or a
  provider name.
- **purpose** – what kind of work the queue carries, e.g. `default`, `email`,
  `sync`, `ingest`.

### Examples

| Queue name               | Description                           |
|--------------------------|---------------------------------------|
| `arq:platform:default`   | Template-internal default queue       |
| `arq:webhooks:ingest`    | Webhook intake processing             |
| `arq:client:email`       | Client-specific email delivery        |
| `arq:client:reports`     | Client-specific report generation     |
| `arq:integrations:sync`  | Outbound integration sync jobs        |

### Rules

1. Only lowercase ASCII letters, digits, colons, and hyphens are allowed.
2. Names must have at least two colon-separated segments.
3. Names must not exceed 128 characters.
4. The `platform` scope is reserved for template-internal queues.

### Using the helpers

```python
from src.app.workers import client_queues, webhook_queues, QueueNamespace

# Pre-built namespaces
client_queues.queue("email")      # "arq:client:email"
webhook_queues.queue("ingest")    # "arq:webhooks:ingest"

# Custom namespace
billing = QueueNamespace(prefix="arq", scope="billing")
billing.queue("invoices")          # "arq:billing:invoices"
```

Validation is automatic—calling `.queue(...)` raises `QueueNameError` if the
resulting name violates the convention.

## Job Serialization Guidance

ARQ serializes job arguments with pickle by default.  The template
standardizes on **JSON-safe dictionaries** so that both the enqueuing
process and the worker process stay decoupled and queue contents remain
inspectable with external tools.

### What is safe in a job payload

- Strings, integers, floats, booleans, `None`
- Lists and dicts composed of the above types
- ISO-8601 date/time strings (serialize on enqueue, parse on execute)
- UUIDs serialized as strings
- Pydantic models serialized with `.model_dump(mode="json")`

### What is not safe

- Raw `datetime`, `date`, `Decimal`, `UUID`, `bytes`, or `Enum` objects
- SQLAlchemy model instances (pass the primary key and re-fetch in the job)
- File handles, sockets, or any non-serializable runtime handle
- Large binary blobs (store in object storage and pass a reference)

### Serialization helpers

```python
from src.app.workers import safe_payload, serialize_for_envelope

# Validate a plain dict before enqueuing
safe_payload({"user_id": "u1", "action": "welcome"})

# Serialize a Pydantic model into a validated dict
from pydantic import BaseModel
from datetime import datetime

class WelcomePayload(BaseModel):
    user_id: str
    created_at: datetime

await SendWelcomeEmailJob.enqueue(
    pool,
    payload=serialize_for_envelope(WelcomePayload(user_id="u1", created_at=now)),
)
```

`validate_json_safe(value)` checks arbitrary values, `safe_payload(d)` checks
and returns a dict, and `serialize_for_envelope(source)` handles both Pydantic
models and plain dicts.  All three raise `JobPayloadSerializationError` on
failure.

## Concurrency Guidance Per Queue Type

Different workloads need different concurrency settings.  ARQ controls
concurrency with the `max_jobs` setting on each worker process.  To run
different limits per queue, deploy **separate worker processes** each
configured for its own queue name and `max_jobs`.

### Recommended profiles

| Queue purpose      | max_jobs | Rationale                                    |
|--------------------|----------|----------------------------------------------|
| default            |    10    | Balanced starting point for mixed workloads  |
| webhook ingest     |    25    | Short I/O-bound jobs, high throughput needed |
| email / notify     |    15    | Moderate I/O, often rate-limited by provider |
| integration sync   |    10    | Mixed I/O with external API rate limits      |
| reports / export   |     3    | CPU/memory heavy, protect worker stability   |
| scheduled / cron   |     5    | Low volume, avoid starving other queues      |

### Deploying multiple workers

```bash
# default queue
WORKER_QUEUE_NAME=arq:platform:default WORKER_MAX_JOBS=10 uv run arq ...

# webhook ingest queue
WORKER_QUEUE_NAME=arq:webhooks:ingest WORKER_MAX_JOBS=25 uv run arq ...

# heavy reports queue
WORKER_QUEUE_NAME=arq:client:reports WORKER_MAX_JOBS=3 uv run arq ...
```

### Using profiles in code

```python
from src.app.workers import PROFILE_WEBHOOK_INGEST, ALL_PROFILES

# Inspect a profile
print(PROFILE_WEBHOOK_INGEST.max_jobs)            # 25
print(PROFILE_WEBHOOK_INGEST.job_timeout_seconds)  # 60

# Iterate all profiles
for profile in ALL_PROFILES:
    print(f"{profile.name}: max_jobs={profile.max_jobs}")
```

Pre-built profiles are starting recommendations.  Tune `max_jobs` and
`job_timeout_seconds` based on your workload characteristics, available
memory, and external rate limits.

## Next Steps

- **[Retry and Backoff](retry-backoff.md)** — exponential backoff, error classification, dead-letter storage, alerting hooks, replay, and idempotency guidance.
- **[Automation Persistence Patterns](../database/automation-patterns.md)** — shared ledgers for dead-letter records, idempotency keys, job state history, and workflow executions.
- **[ARQ documentation](https://arq-docs.helpmanual.io/)** — advanced usage patterns for the underlying queue library.
