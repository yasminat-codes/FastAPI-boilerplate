# Adding a Background Job

Background jobs handle asynchronous work in the template. They are durable (stored in Redis), retryable, and automatically monitored. This guide walks through creating and registering a custom job.

## Overview

A background job is a class that subclasses `WorkerJob` and implements the `run()` method. The job receives a `JobEnvelope` containing the payload, correlation ID, and optional tenant context. The template handles enqueuing, retry logic, timeout, and failure alerts.

## Step 1: Create the Job Class

Create a new file at `src/app/workers/jobs/send_email.py`:

```python
"""Send transactional emails via a background job."""

from __future__ import annotations

from src.app.core.worker.jobs import JobEnvelope, JobRetryPolicy, WorkerContext, WorkerJob


class SendWelcomeEmailJob(WorkerJob):
    """Send a welcome email to a new user."""

    job_name = "myproject.jobs.send_welcome_email"
    retry_policy = JobRetryPolicy(max_tries=3, defer_seconds=10.0)
    timeout_seconds = 30.0
    keep_result_seconds = 3600.0  # Retain result for 1 hour

    @classmethod
    async def run(cls, ctx: WorkerContext, envelope: JobEnvelope) -> dict:
        """Send the welcome email.
        
        Args:
            ctx: ARQ worker context containing runtime info.
            envelope: Job payload envelope with user_email and user_name.
        
        Returns:
            Dict with sent email ID.
        """
        logger = cls.get_logger(ctx=ctx, envelope=envelope)
        
        # Extract payload
        user_email = envelope.payload.get("user_email")
        user_name = envelope.payload.get("user_name")
        
        if not user_email:
            raise ValueError("Job requires user_email in payload")
        
        logger.info("Sending welcome email", user_email=user_email, user_name=user_name)
        
        # Call email service (pseudo-code)
        result = await send_email_service.send(
            to=user_email,
            subject="Welcome!",
            template="welcome",
            context={"name": user_name},
        )
        
        logger.info("Welcome email sent", message_id=result["id"])
        
        return {
            "status": "sent",
            "message_id": result["id"],
            "recipient": user_email,
        }
```

!!! tip
    The `job_name` should be a dotted string like `"myproject.jobs.send_welcome_email"` to avoid collisions with other jobs. It becomes the canonical name in Redis.

## Step 2: Register the Job

Edit `src/app/workers/jobs/__init__.py` to import and register your job:

```python
"""Canonical worker job surface."""

from .send_email import SendWelcomeEmailJob

# Build the job definition
send_welcome_email_job = SendWelcomeEmailJob.definition()

# Add to worker functions list
worker_functions = [send_welcome_email_job.function]
```

If you have multiple jobs, append each to `worker_functions`:

```python
from .send_email import SendWelcomeEmailJob
from .export_report import GenerateReportJob

# Build definitions
send_welcome_email_job = SendWelcomeEmailJob.definition()
generate_report_job = GenerateReportJob.definition()

# Combine into worker functions
worker_functions = [
    send_welcome_email_job.function,
    generate_report_job.function,
]
```

## Step 3: Enqueue the Job from a Route

In a FastAPI route, import the job class and call `enqueue()`:

```python
from fastapi import APIRouter, Depends
from arq.connections import ArqRedis

from src.app.core.config import get_redis_pool
from src.app.workers.jobs import SendWelcomeEmailJob

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/register")
async def register_user(
    email: str,
    name: str,
    pool: ArqRedis = Depends(get_redis_pool),
):
    """Register a new user and queue a welcome email."""
    
    # Save user to database (pseudo-code)
    user = await create_user(email=email, name=name)
    
    # Enqueue the welcome email job
    job = await SendWelcomeEmailJob.enqueue(
        pool,
        payload={
            "user_email": email,
            "user_name": name,
        },
        correlation_id=request_context.correlation_id,
        tenant_id=request_context.tenant_id,
    )
    
    return {
        "user_id": user.id,
        "email": email,
        "job_id": job.job_id if job else None,
    }
```

## Step 4 (Optional): Customize Retry Behavior

Override the class variables to customize retry and timeout behavior:

```python
from src.app.workers import BACKOFF_STANDARD


class SendWelcomeEmailJob(WorkerJob):
    job_name = "myproject.jobs.send_welcome_email"
    
    # Custom retry: 5 attempts with exponential backoff
    retry_policy = JobRetryPolicy(max_tries=5, defer_seconds=5.0)
    
    # Use exponential backoff curve: 5s, 25s, 125s, ...
    backoff_policy = BACKOFF_STANDARD
    
    # Timeout each attempt at 30 seconds
    timeout_seconds = 30.0
    
    # Keep results for 24 hours
    keep_result_seconds = 86400.0
    
    @classmethod
    async def run(cls, ctx: WorkerContext, envelope: JobEnvelope) -> dict:
        ...
```

!!! warning
    If you set both `backoff_policy` and raise `RetryableJobError` with a custom `defer_seconds`, the backoff policy takes precedence.

## Step 5 (Optional): Add Alert Hooks

Add hooks to notify on job failure:

```python
from src.app.workers import JobAlertHook, LoggingAlertHook


class SlackAlertHook(JobAlertHook):
    """Send job failures to Slack."""
    
    async def on_job_failure(
        self,
        job_name: str,
        envelope_data: dict,
        attempt: int,
        max_attempts: int,
        error_category: str | None,
        error_message: str,
        is_final_attempt: bool,
    ) -> None:
        if is_final_attempt:
            await slack_client.send(
                channel="#alerts",
                text=f"Job {job_name} failed permanently: {error_message}",
            )


class SendWelcomeEmailJob(WorkerJob):
    job_name = "myproject.jobs.send_welcome_email"
    alert_hooks = [
        LoggingAlertHook(),
        SlackAlertHook(),
    ]
    
    @classmethod
    async def run(cls, ctx: WorkerContext, envelope: JobEnvelope) -> dict:
        ...
```

## Enqueueing from Another Job

Jobs can enqueue other jobs:

```python
class OnboardNewUserJob(WorkerJob):
    job_name = "myproject.jobs.onboard_user"

    @classmethod
    async def run(cls, ctx: WorkerContext, envelope: JobEnvelope) -> dict:
        user_id = envelope.payload.get("user_id")
        
        # Get the user
        user = await get_user(user_id)
        
        # Chain: send welcome email
        await SendWelcomeEmailJob.enqueue(
            ctx["redis"],  # Redis pool is in the worker context
            payload={
                "user_email": user.email,
                "user_name": user.name,
            },
            correlation_id=envelope.correlation_id,
            tenant_id=envelope.tenant_context.tenant_id,
        )
        
        return {"status": "user_onboarded"}
```

## Testing

Test the job synchronously without the worker:

```python
import pytest
from src.app.workers.jobs import SendWelcomeEmailJob


@pytest.mark.asyncio
async def test_send_welcome_email():
    envelope = SendWelcomeEmailJob.build_envelope(
        payload={
            "user_email": "alice@example.com",
            "user_name": "Alice",
        }
    )
    
    ctx = {}  # Empty worker context for testing
    result = await SendWelcomeEmailJob.run(ctx, envelope)
    
    assert result["status"] == "sent"
    assert result["recipient"] == "alice@example.com"
```

## Checklist

- [ ] Created job class subclassing `WorkerJob`
- [ ] Set `job_name` to a unique dotted string
- [ ] Implemented `async def run()` method
- [ ] Registered job in `src/app/workers/jobs/__init__.py`
- [ ] Added job function to `worker_functions` list
- [ ] Called `enqueue()` from a route or another job
- [ ] (Optional) Customized retry policy and timeout
- [ ] (Optional) Added alert hooks for critical jobs
- [ ] Added unit tests for the job logic
- [ ] Verified job runs in local worker: `uv run python -m src.app.workers.start_worker`

## Next Steps

See [Adding a Workflow](adding-workflow.md) if your job is part of a multi-step orchestration that needs state tracking and compensation logic.
