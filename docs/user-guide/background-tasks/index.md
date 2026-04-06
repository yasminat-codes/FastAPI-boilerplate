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
- Task retry mechanisms for failed jobs
- Dead letter queues for problematic tasks
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

## Next Steps

Check the [ARQ documentation](https://arq-docs.helpmanual.io/) for advanced usage patterns and refer to the template worker primitives in `src/app/workers/jobs.py` and `src/app/workers/settings.py`.
