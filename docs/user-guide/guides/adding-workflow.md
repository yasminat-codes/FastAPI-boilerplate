# Adding a Workflow

Workflows orchestrate multi-step processes with durable state, built-in retries, branching, and compensation logic. Use workflows when you need to track progress across multiple steps, handle partial failures, or implement saga-pattern distributed transactions.

## Overview

A workflow is a `WorkflowDefinition` containing an ordered list of `WorkflowStep` instances. Steps execute sequentially, with each step's output merged into the shared workflow context. If a step fails, the workflow retries or runs compensation steps in reverse order.

The workflow state is stored in the database (`WorkflowExecution` model), so workflows survive crashes and can be resumed.

## Step 1: Define Workflow Steps

Create a new file at `src/app/workflows/onboard_customer.py`:

```python
"""Customer onboarding workflow."""

from __future__ import annotations

from src.app.core.worker.workflow import (
    StepResult,
    StepRetryPolicy,
    WorkflowContext,
    WorkflowStep,
)


class ValidateCustomerStep(WorkflowStep):
    """Validate the customer input."""

    step_name = "validate_customer"
    timeout_seconds = 10.0
    retry_policy = StepRetryPolicy(max_attempts=1)  # No retries for validation

    async def execute(self, context: WorkflowContext) -> StepResult:
        """Validate customer data from workflow input.
        
        Args:
            context: Workflow context with input_payload.
        
        Returns:
            StepResult with output containing normalized customer data.
        """
        email = context.input_payload.get("email")
        name = context.input_payload.get("name")
        
        if not email or not name:
            return StepResult(
                status="failed",
                error_message="email and name are required",
                error_code="INVALID_INPUT",
            )
        
        # Normalize email
        normalized_email = email.lower().strip()
        
        # Output to pass to next steps
        return StepResult(
            status="succeeded",
            output={
                "normalized_email": normalized_email,
                "name": name,
            },
        )


class ProvisionCustomerStep(WorkflowStep):
    """Create customer record in the database."""

    step_name = "provision_customer"
    timeout_seconds = 30.0
    retry_policy = StepRetryPolicy(max_attempts=3)

    async def execute(self, context: WorkflowContext) -> StepResult:
        """Create a customer record.
        
        The output of the previous step is in context.step_outputs["validate_customer"].
        """
        previous_output = context.step_outputs.get("validate_customer", {})
        normalized_email = previous_output.get("normalized_email")
        name = previous_output.get("name")
        
        # Create customer in database (pseudo-code)
        customer = await create_customer(email=normalized_email, name=name)
        
        return StepResult(
            status="succeeded",
            output={
                "customer_id": customer.id,
                "customer_email": customer.email,
            },
        )


class NotifyCustomerStep(WorkflowStep):
    """Send a welcome email."""

    step_name = "notify_customer"
    timeout_seconds = 15.0
    retry_policy = StepRetryPolicy(max_attempts=2)

    async def execute(self, context: WorkflowContext) -> StepResult:
        """Send a welcome email to the newly created customer."""
        provision_output = context.step_outputs.get("provision_customer", {})
        customer_id = provision_output.get("customer_id")
        customer_email = provision_output.get("customer_email")
        
        # Enqueue welcome email job (pseudo-code)
        from src.app.workers.jobs import SendWelcomeEmailJob
        
        await SendWelcomeEmailJob.enqueue(
            context.execution_context.get("_redis_pool"),
            payload={
                "user_email": customer_email,
                "user_name": context.input_payload.get("name"),
            },
            correlation_id=context.correlation_id,
            tenant_id=context.tenant_id,
        )
        
        return StepResult(
            status="succeeded",
            output={
                "notification_sent": True,
                "customer_id": customer_id,
            },
        )
```

!!! tip
    Each step is a separate class that implements the `WorkflowStep` protocol: `step_name`, `timeout_seconds`, `retry_policy`, and `async def execute()`.

## Step 2: Create the Workflow Definition

Add to the same file:

```python
from src.app.core.worker.workflow import WorkflowDefinition, register_workflow


def create_onboard_customer_workflow() -> WorkflowDefinition:
    """Create the customer onboarding workflow."""
    return WorkflowDefinition(
        name="onboard_customer",
        version="1.0.0",
        steps=[
            ValidateCustomerStep(),
            ProvisionCustomerStep(),
            NotifyCustomerStep(),
        ],
        max_attempts=3,  # Retry entire workflow up to 3 times
    )


# Register the workflow at module level
onboard_customer_workflow = create_onboard_customer_workflow()
register_workflow(onboard_customer_workflow)
```

## Step 3: Start a Workflow from a Route

In a FastAPI route, create and start a workflow execution:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.db import get_db_session
from src.app.workflows.onboard_customer import onboard_customer_workflow
from src.app.core.worker.workflow import WorkflowRunner

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post("/onboard")
async def onboard_customer(
    email: str,
    name: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Start a customer onboarding workflow."""
    
    # Create and start the workflow
    runner = WorkflowRunner(onboard_customer_workflow)
    execution = await runner.start(
        session,
        input_payload={
            "email": email,
            "name": name,
        },
        trigger_source="api",
        correlation_id=request_context.correlation_id,
        tenant_id=request_context.tenant_id,
    )
    await session.commit()
    
    # Enqueue the first step to be executed by the worker
    from src.app.core.worker.workflow import WorkflowStepJob
    from src.app.core.config import get_redis_pool
    
    pool = get_redis_pool()
    await WorkflowStepJob.enqueue_step(
        pool,
        execution_id=execution.id,
        correlation_id=execution.correlation_id,
        tenant_id=execution.tenant_id,
    )
    
    return {
        "execution_id": execution.id,
        "workflow_name": execution.workflow_name,
        "status": execution.status,
    }
```

## Step 4 (Optional): Add Compensation Steps

For saga-pattern transactions, implement compensation (rollback) logic:

```python
from src.app.core.worker.workflow import CompensatingStep


class ProvisionCustomerStep(CompensatingStep):
    """Create customer record and support rollback."""

    step_name = "provision_customer"
    timeout_seconds = 30.0
    retry_policy = StepRetryPolicy(max_attempts=3)

    async def execute(self, context: WorkflowContext) -> StepResult:
        """Create a customer record."""
        ...
        return StepResult(status="succeeded", output={"customer_id": customer.id})

    async def compensate(self, context: WorkflowContext) -> None:
        """Compensate by deleting the customer if a later step fails.
        
        Args:
            context: Workflow context at the point of failure.
        
        Raises:
            Exceptions are logged but not re-raised (best-effort cleanup).
        """
        provision_output = context.step_outputs.get("provision_customer", {})
        customer_id = provision_output.get("customer_id")
        
        if customer_id:
            # Delete the customer (pseudo-code)
            await delete_customer(customer_id)
```

When a step fails, the workflow automatically calls `compensate()` on all completed steps in reverse order.

## Step 5 (Optional): Handle Branching

Return a `next_step_override` to skip or branch to a different step:

```python
class CheckPlanStep(WorkflowStep):
    """Check if customer has a plan and route accordingly."""
    
    step_name = "check_plan"
    timeout_seconds = 10.0
    retry_policy = StepRetryPolicy(max_attempts=1)
    
    async def execute(self, context: WorkflowContext) -> StepResult:
        plan = context.input_payload.get("plan", "free")
        
        if plan == "premium":
            # Skip to premium setup instead of standard setup
            return StepResult(
                status="succeeded",
                output={"plan": plan},
                next_step_override="setup_premium_features",
            )
        else:
            return StepResult(
                status="succeeded",
                output={"plan": plan},
            )
```

## Step 6 (Optional): Wait and Resume

Return a `WAITING` status to delay a step and resume later:

```python
from datetime import datetime, timedelta, UTC


class CheckReadinessStep(WorkflowStep):
    """Wait for external service to be ready."""
    
    step_name = "check_readiness"
    
    async def execute(self, context: WorkflowContext) -> StepResult:
        """Check if provisioning is ready. If not, wait and retry."""
        is_ready = await check_external_service_ready()
        
        if is_ready:
            return StepResult(status="succeeded", output={"ready": True})
        
        # Wait 5 minutes before retrying
        wait_until = datetime.now(UTC) + timedelta(minutes=5)
        return StepResult(
            status="waiting",
            output={"ready": False},
            wait_until=wait_until,
        )
```

The workflow will remain in `WAITING` status until the scheduled time, then automatically resume.

## Testing

Test the entire workflow:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.app.workflows.onboard_customer import onboard_customer_workflow
from src.app.core.worker.workflow import WorkflowRunner


@pytest.mark.asyncio
async def test_onboard_customer_workflow(db_session: AsyncSession):
    runner = WorkflowRunner(onboard_customer_workflow)
    
    execution = await runner.start(
        db_session,
        input_payload={
            "email": "alice@example.com",
            "name": "Alice",
        },
        trigger_source="test",
    )
    
    # Advance through each step
    execution = await runner.advance(db_session, execution)
    assert execution.current_step == "provision_customer"
    
    execution = await runner.advance(db_session, execution)
    assert execution.current_step == "notify_customer"
    
    execution = await runner.advance(db_session, execution)
    assert execution.status == "succeeded"
```

## Monitoring

Query workflow executions from the database:

```python
from src.app.db.workflow_execution import WorkflowExecution
from sqlalchemy import select

async with session() as db:
    stmt = select(WorkflowExecution).where(
        WorkflowExecution.workflow_name == "onboard_customer"
    ).order_by(WorkflowExecution.started_at.desc())
    
    result = await db.execute(stmt)
    executions = result.scalars().all()
    
    for execution in executions:
        print(f"Execution {execution.id}: {execution.status}")
        print(f"Current step: {execution.current_step}")
        print(f"Started: {execution.started_at}")
```

## Checklist

- [ ] Created step classes implementing `WorkflowStep` protocol
- [ ] Implemented `async def execute()` method for each step
- [ ] Created `WorkflowDefinition` with ordered steps
- [ ] Called `register_workflow()` at module level
- [ ] Called `WorkflowRunner.start()` from a route
- [ ] Enqueued `WorkflowStepJob` to begin execution
- [ ] (Optional) Implemented `CompensatingStep` for cleanup
- [ ] (Optional) Added branching with `next_step_override`
- [ ] (Optional) Added waiting and resumption with `WAITING` status
- [ ] Added tests covering all step outcomes
- [ ] Verified workflow runs in local worker

## Next Steps

See [Adding a Client Integration](adding-integration.md) if your workflow needs to call external APIs.
