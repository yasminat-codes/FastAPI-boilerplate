# Workflow Orchestration

The template includes a complete workflow orchestration system for coordinating complex multi-step processes. Workflows provide durable state tracking, automatic retry with backoff, compensation (rollback) support, and resumable execution after interruptions.

## Overview

Workflow orchestration is essential for operations that:

- **Span multiple steps** where each step depends on previous results
- **Require distributed transaction semantics** (all-or-nothing or rollback)
- **May be interrupted** and need to resume from the last completed step
- **Need durable state** for audit trails and operator visibility
- **Should survive application restarts** with automatic recovery
- **Benefit from delayed execution** or scheduled retry

Common use cases include order processing, data migration pipelines, multi-stage approvals, API integration chains, and saga-pattern distributed transactions.

## Quick Example

```python
from src.app.core.worker.workflow import (
    WorkflowDefinition,
    WorkflowRunner,
    WorkflowStep,
    StepResult,
    StepStatus,
    StepRetryPolicy,
    WorkflowContext,
    register_workflow,
)
from datetime import datetime, UTC, timedelta

class ValidateOrderStep:
    step_name = "validate_order"
    timeout_seconds = None
    retry_policy = StepRetryPolicy(max_attempts=3)

    async def execute(self, context: WorkflowContext) -> StepResult:
        order_id = context.input_payload["order_id"]
        # Validation logic...
        if order_valid:
            return StepResult(
                status=StepStatus.SUCCEEDED,
                output={"order_id": order_id, "validated_at": datetime.now(UTC).isoformat()},
            )
        else:
            return StepResult(
                status=StepStatus.FAILED,
                error_message="Invalid order",
                error_code="INVALID_ORDER",
            )

class ChargePaymentStep:
    step_name = "charge_payment"
    timeout_seconds = 30.0
    retry_policy = StepRetryPolicy(max_attempts=5)

    async def execute(self, context: WorkflowContext) -> StepResult:
        order_data = context.step_outputs.get("validate_order", {})
        # Payment processing...
        return StepResult(
            status=StepStatus.SUCCEEDED,
            output={"charge_id": charge_id},
        )

# Define the workflow
order_workflow = WorkflowDefinition(
    name="process_order",
    steps=[
        ValidateOrderStep(),
        ChargePaymentStep(),
    ],
    version="1.0.0",
    max_attempts=3,
)

# Register for runtime lookup
register_workflow(order_workflow)

# In your API endpoint:
@router.post("/orders")
async def create_order(order: OrderCreate, session: AsyncSession):
    runner = WorkflowRunner(order_workflow)
    execution = await runner.start(
        session,
        input_payload=order.dict(),
        trigger_source="api",
        correlation_id=request_context.correlation_id,
    )

    # Enqueue the first step
    if queue.pool is not None:
        await WorkflowStepJob.enqueue_step(
            queue.pool,
            execution_id=execution.id,
            correlation_id=execution.correlation_id,
        )

    return {"execution_id": execution.id}
```

## Core Concepts

### WorkflowDefinition

A workflow is a sequence of steps with metadata and control parameters.

```python
from src.app.core.worker.workflow import WorkflowDefinition

definition = WorkflowDefinition(
    name="my_workflow",
    steps=[step1, step2, step3],
    version="1.0.0",
    max_attempts=3,  # Retry limit for entire workflow
)
```

- **name**: Unique identifier for runtime lookup
- **steps**: Ordered list of WorkflowStep instances
- **version**: Semantic version (for migrations/upgrades)
- **max_attempts**: How many times to retry the entire workflow if interrupted

### WorkflowStep (Protocol)

A step is any class that implements the WorkflowStep protocol:

```python
class MyStep:
    step_name: str  # Unique within the workflow
    timeout_seconds: float | None
    retry_policy: StepRetryPolicy | None

    async def execute(self, context: WorkflowContext) -> StepResult:
        """Execute the step's logic."""
        ...
```

Steps are executed sequentially. The output of one step is available to all subsequent steps via `context.step_outputs`.

### WorkflowContext

Passed to each step during execution, containing all inputs and previous outputs:

```python
@dataclass
class WorkflowContext:
    workflow_execution_id: int          # Database ID
    workflow_name: str
    current_step: str
    input_payload: dict                 # Original workflow input (immutable)
    step_outputs: dict[str, dict]       # Outputs from previous steps
    execution_context: dict             # Mutable shared state
    correlation_id: str | None
    tenant_id: str | None
    organization_id: str | None
    attempt_count: int
```

Use `context.step_outputs` to access data from previous steps:

```python
async def execute(self, context: WorkflowContext) -> StepResult:
    # Access previous step output
    previous_output = context.step_outputs.get("previous_step_name", {})
    previous_id = previous_output.get("id")

    # Access original input
    original_value = context.input_payload.get("key")

    # Modify shared state
    context.execution_context["shared_counter"] = 42
```

### WorkflowRunner

The engine that executes a workflow definition:

```python
from src.app.core.worker.workflow import WorkflowRunner

runner = WorkflowRunner(workflow_definition)

# Start a new execution
execution = await runner.start(
    session,
    input_payload={"order_id": 123},
    trigger_source="api",
)

# Execute a step
result = await runner.execute_step(session, execution, step)

# Advance to the next step
execution = await runner.advance(session, execution)

# Resume a waiting workflow
execution = await runner.resume(session, execution)
```

### StepResult

Returned by step.execute() to communicate the outcome:

```python
@dataclass
class StepResult:
    status: StepStatus                    # SUCCEEDED, FAILED, WAITING, SKIPPED
    output: dict[str, Any] | None = None # Data to merge into step_outputs
    error_message: str | None = None      # For FAILED steps
    error_code: str | None = None         # For FAILED steps
    wait_until: datetime | None = None    # For WAITING steps
    next_step_override: str | None = None # For conditional branching
```

### StepStatus

Each step execution concludes with one of four statuses:

- **SUCCEEDED**: Step completed successfully. Output is merged into `step_outputs`. Workflow advances to the next step.
- **FAILED**: Step encountered an unrecoverable error. If retry attempts remain, the step is retried after a backoff delay. Otherwise, compensation is triggered.
- **WAITING**: Step is paused and will resume after `wait_until` datetime. Used for delayed execution or external event waiting.
- **SKIPPED**: Step was bypassed (e.g., due to a condition). Workflow advances to the next step without executing the step's logic.

## Defining a Workflow

### Step 1: Define Step Classes

Each step must implement the WorkflowStep protocol:

```python
from src.app.core.worker.workflow import (
    WorkflowStep,
    StepResult,
    StepStatus,
    StepRetryPolicy,
    WorkflowContext,
)
from src.app.core.worker.retry import BackoffPolicy, BACKOFF_STANDARD

class ReserveInventoryStep:
    step_name = "reserve_inventory"
    timeout_seconds = 10.0
    retry_policy = StepRetryPolicy(
        max_attempts=3,
        backoff=BACKOFF_STANDARD,
    )

    async def execute(self, context: WorkflowContext) -> StepResult:
        order_id = context.input_payload["order_id"]
        items = context.input_payload["items"]

        try:
            # Reserve inventory
            reservation_id = await inventory_service.reserve(order_id, items)

            return StepResult(
                status=StepStatus.SUCCEEDED,
                output={"reservation_id": reservation_id},
            )
        except OutOfStockError as exc:
            return StepResult(
                status=StepStatus.FAILED,
                error_message=f"Insufficient stock for item {exc.item_id}",
                error_code="OUT_OF_STOCK",
            )
        except TemporaryServiceError as exc:
            # Don't return FAILED; let the exception propagate and retry
            raise
```

### Step 2: Wire Steps into a Definition

```python
from src.app.core.worker.workflow import WorkflowDefinition, register_workflow

order_workflow = WorkflowDefinition(
    name="order_workflow",
    steps=[
        ValidateOrderStep(),
        ReserveInventoryStep(),
        ChargePaymentStep(),
        CreateShipmentStep(),
    ],
    version="1.0.0",
    max_attempts=3,
)

# Register for runtime lookup
register_workflow(order_workflow)
```

### Step 3: Start and Enqueue

```python
from src.app.core.worker.workflow import WorkflowRunner, get_workflow, WorkflowStepJob
from src.app.platform import queue

workflow = get_workflow("order_workflow")
runner = WorkflowRunner(workflow)

# Create a new execution record in the database
execution = await runner.start(
    session,
    input_payload=order_data,
    trigger_source="api.orders.create",
    correlation_id=correlation_id,
)

# Enqueue the first step for async execution
if queue.pool is not None:
    await WorkflowStepJob.enqueue_step(
        queue.pool,
        execution_id=execution.id,
        correlation_id=execution.correlation_id,
        tenant_id=tenant_id,
        organization_id=organization_id,
    )
```

## Step Results

### SUCCEEDED

The step completed successfully. Output is merged into `context.step_outputs` for downstream steps.

```python
return StepResult(
    status=StepStatus.SUCCEEDED,
    output={
        "user_id": user.id,
        "email_verified": True,
        "created_at": datetime.now(UTC).isoformat(),
    },
)
```

### FAILED

The step encountered an error that cannot be recovered immediately. The error is logged, and the step state is updated. Retry behavior depends on the step's `retry_policy`.

```python
return StepResult(
    status=StepStatus.FAILED,
    error_message="Payment gateway returned 500 Internal Server Error",
    error_code="PAYMENT_GATEWAY_ERROR",
)
```

Alternatively, raise an exception (it will be caught and converted to a FAILED result):

```python
async def execute(self, context: WorkflowContext) -> StepResult:
    try:
        result = await risky_operation()
    except Exception as exc:
        # Exception is caught, converted to FAILED status
        raise
```

### WAITING

The step is paused and will be resumed after `wait_until` datetime. Use this for delayed execution or waiting for external events.

```python
from datetime import timedelta, UTC, datetime

return StepResult(
    status=StepStatus.WAITING,
    output={"retry_scheduled": True},
    wait_until=datetime.now(UTC) + timedelta(hours=1),
)
```

The workflow execution status becomes WAITING. A background job (WorkflowStepJob) will check the wait time and resume execution when ready.

### SKIPPED

The step was skipped (e.g., based on a condition). The workflow advances to the next step without executing any logic.

```python
if not context.input_payload.get("require_approval"):
    return StepResult(
        status=StepStatus.SKIPPED,
        output={},
    )

# Otherwise, execute approval logic...
```

## Step Retry

Each step has an optional `retry_policy` that controls retry behavior on failure:

```python
@dataclass(frozen=True)
class StepRetryPolicy:
    max_attempts: int = 3
    backoff: BackoffPolicy | None = None
```

### Basic Retry

```python
class MyStep:
    retry_policy = StepRetryPolicy(max_attempts=5)

    async def execute(self, context: WorkflowContext) -> StepResult:
        try:
            result = await api_call()
            return StepResult(status=StepStatus.SUCCEEDED, output=result)
        except TemporaryError as exc:
            # Return FAILED; will be retried
            raise
```

When a step fails (either by returning FAILED or raising an exception):
1. The runner checks if `attempt_count < max_attempts`
2. If true, marks the step as WAITING and schedules a retry after a backoff delay
3. If false, triggers compensation and marks the workflow as FAILED

### Backoff Policy

Use exponential backoff to spread retries:

```python
from src.app.core.worker.retry import (
    BackoffPolicy,
    BACKOFF_FAST,
    BACKOFF_STANDARD,
    BACKOFF_SLOW,
)

class MyStep:
    retry_policy = StepRetryPolicy(
        max_attempts=5,
        backoff=BACKOFF_STANDARD,  # base=5s, max=300s
    )
```

Predefined policies:

| Policy | Base | Max | Use case |
|--------|------|-----|----------|
| `BACKOFF_FAST` | 1s | 30s | Short-lived transient errors |
| `BACKOFF_STANDARD` | 5s | 300s | General-purpose retries |
| `BACKOFF_SLOW` | 30s | 1800s | Rate-limited or heavy API calls |

Custom backoff:

```python
class MyStep:
    retry_policy = StepRetryPolicy(
        max_attempts=5,
        backoff=BackoffPolicy(
            base_delay_seconds=2.0,
            max_delay_seconds=120.0,
            multiplier=2.0,
            jitter=True,
        ),
    )
```

## Compensation (Saga Pattern)

For workflows that modify external state (databases, third-party APIs), use compensation steps to roll back changes if a later step fails.

### Defining a Compensating Step

A compensating step implements both `execute()` and `compensate()`:

```python
from src.app.core.worker.workflow import CompensatingStep, WorkflowContext, StepResult, StepStatus

class ChargePaymentStep:
    step_name = "charge_payment"
    timeout_seconds = 30.0
    retry_policy = StepRetryPolicy(max_attempts=3)

    async def execute(self, context: WorkflowContext) -> StepResult:
        order_id = context.input_payload["order_id"]
        amount = context.input_payload["amount"]

        charge_id = await payment_provider.charge(order_id, amount)

        return StepResult(
            status=StepStatus.SUCCEEDED,
            output={"charge_id": charge_id},
        )

    async def compensate(self, context: WorkflowContext) -> None:
        """Refund the charge if a later step fails."""
        step_output = context.step_outputs.get("charge_payment", {})
        charge_id = step_output.get("charge_id")

        if charge_id:
            await payment_provider.refund(charge_id)
```

### How Compensation Works

When a step fails and retries are exhausted:

1. The runner retrieves all compensating steps up to and including the failed step, **in reverse order**
2. For each compensating step that executed successfully, `compensate()` is called
3. Compensation failures are logged but do not re-throw (best-effort cleanup)
4. The workflow status is set to FAILED

Example workflow:

```
Step 1: Reserve Inventory    [SUCCEEDED]  ← compensate() called
Step 2: Charge Payment       [SUCCEEDED]  ← compensate() called
Step 3: Create Shipment      [FAILED]     ← no compensation (didn't execute)
```

When Step 3 fails, compensations run in this order:
1. Charge Payment (refund)
2. Reserve Inventory (release reservation)

!!! note
    Only steps that implement CompensatingStep and have succeeded are compensated. Steps that failed or were skipped are not compensated.

## Delayed Execution and Waiting Steps

Steps can pause execution and resume after a delay or at a scheduled time.

### Returning WAITING Status

```python
from datetime import datetime, UTC, timedelta

async def execute(self, context: WorkflowContext) -> StepResult:
    # Check if user email is verified
    user = await get_user(context.input_payload["user_id"])

    if not user.email_verified:
        # Wait for verification email to be sent; check again in 24 hours
        return StepResult(
            status=StepStatus.WAITING,
            output={"reason": "awaiting_email_verification"},
            wait_until=datetime.now(UTC) + timedelta(hours=24),
        )

    # Email is verified, continue
    return StepResult(status=StepStatus.SUCCEEDED, output={})
```

### Automatic Resume

When a workflow execution reaches WAITING status:

1. The WorkflowExecution record is updated with status WAITING
2. The step's `wait_until` time is stored in the step state
3. A background job (or scheduled resumption) checks the wait time
4. When `wait_until` has passed, the runner calls `resume()`
5. The step is re-executed (this counts as a new attempt)

### Resume Implementation

To resume a waiting workflow, call `runner.resume()`:

```python
from src.app.core.worker.workflow import get_workflow, WorkflowRunner, WorkflowStepJob
from src.app.db.workflow_execution import WorkflowExecution

# Load the execution
execution = await session.get(WorkflowExecution, execution_id)

if execution.status == "waiting":
    # Check if wait time has elapsed
    workflow = get_workflow(execution.workflow_name)
    runner = WorkflowRunner(workflow)

    # Resume will check wait time and advance if ready
    execution = await runner.resume(session, execution)
    await session.commit()
```

## Chaining Steps via Queue

Workflows are not executed synchronously in the request. Instead, each step is enqueued as a background job for asynchronous execution.

### WorkflowStepJob

The template provides a worker job class for executing workflow steps:

```python
from src.app.core.worker.workflow import WorkflowStepJob

class WorkflowStepJob(WorkerJob):
    """Executes a single workflow step via the queue."""

    job_name = "workflow_step"

    @classmethod
    async def run(cls, ctx: WorkerContext, envelope: JobEnvelope) -> dict:
        # Load the execution from the database
        execution = await session.get(WorkflowExecution, execution_id)

        # Retrieve the workflow definition
        workflow = get_workflow(execution.workflow_name)
        runner = WorkflowRunner(workflow)

        # Execute current step and advance to next
        execution = await runner.advance(session, execution)
        await session.commit()

        return {"status": "completed", "execution_id": execution.id}
```

### Enqueue the First Step

After creating a workflow execution, enqueue the first step:

```python
execution = await runner.start(
    session,
    input_payload=data,
    trigger_source="api",
)

if queue.pool is not None:
    await WorkflowStepJob.enqueue_step(
        queue.pool,
        execution_id=execution.id,
    )
```

### Automatic Chaining

When a step succeeds and there's a next step, the execution status remains RUNNING but does not automatically enqueue the next step. You must enqueue it manually or trigger resumption via a scheduled job.

```python
# After runner.advance() completes
if execution.status == "running":
    # Enqueue the next step
    await WorkflowStepJob.enqueue_step(
        queue.pool,
        execution_id=execution.id,
    )
```

!!! tip
    Use a background task or scheduler to periodically check for RUNNING executions and enqueue the next step. Or enqueue immediately after step completion in the WorkflowStepJob itself.

## Resuming Workflows

Workflows can be interrupted (e.g., application restart, scheduler downtime) and resumed automatically.

### Resume on Startup

Implement a startup task to resume interrupted workflows:

```python
from src.app.db.workflow_execution import WorkflowExecutionStatus
from sqlalchemy import select

async def resume_interrupted_workflows(session: AsyncSession):
    """Resume workflows that were interrupted."""

    # Find all RUNNING or WAITING executions
    stmt = select(WorkflowExecution).filter(
        WorkflowExecution.status.in_([
            WorkflowExecutionStatus.RUNNING.value,
            WorkflowExecutionStatus.WAITING.value,
        ])
    )

    executions = (await session.execute(stmt)).scalars().all()

    for execution in executions:
        workflow = get_workflow(execution.workflow_name)
        if not workflow:
            logger.warning(f"Workflow {execution.workflow_name} not found")
            continue

        runner = WorkflowRunner(workflow)

        # Resume the workflow
        execution = await runner.resume(session, execution)
        await session.commit()

        # Enqueue the next step if still running
        if execution.status == "running" and queue.pool is not None:
            await WorkflowStepJob.enqueue_step(
                queue.pool,
                execution_id=execution.id,
            )
```

Call this on application startup:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    async with get_async_session_maker() as session:
        await resume_interrupted_workflows(session)

    yield

    # Shutdown
    ...

app = FastAPI(lifespan=lifespan)
```

## Workflow Registry

Workflows are registered at module load time and retrieved by name at runtime.

### Register a Workflow

```python
from src.app.core.worker.workflow import register_workflow, WorkflowDefinition

definition = WorkflowDefinition(
    name="my_workflow",
    steps=[...],
)

register_workflow(definition)
```

### Retrieve a Workflow

```python
from src.app.core.worker.workflow import get_workflow

workflow = get_workflow("my_workflow")
if workflow:
    runner = WorkflowRunner(workflow)
    # ...
else:
    logger.error("Workflow not found")
```

### Multiple Workflows

Register multiple workflows in a module:

```python
# src/app/workflows/__init__.py

from .order_workflow import order_workflow
from .user_workflow import user_workflow

register_workflow(order_workflow)
register_workflow(user_workflow)
```

Then import in your application to trigger registration:

```python
# src/app/main.py
from src.app import workflows  # Triggers registration

app = FastAPI()
```

!!! warning
    Workflows must be registered before they're used. If a workflow is not found at runtime, the WorkflowStepJob will fail with a ValueError.

## Step State Tracking

Per-step execution state is stored in `WorkflowExecution.execution_context` under the `_step_states` key.

### Structure

```json
{
    "_step_states": {
        "validate_order": {
            "status": "succeeded",
            "started_at": "2025-04-07T12:00:00Z",
            "completed_at": "2025-04-07T12:00:05Z",
            "attempt_count": 1,
            "output": {
                "order_id": 123,
                "validated_at": "2025-04-07T12:00:05Z"
            },
            "error_message": null,
            "error_code": null,
            "wait_until": null
        },
        "charge_payment": {
            "status": "waiting",
            "started_at": "2025-04-07T12:00:10Z",
            "completed_at": null,
            "attempt_count": 1,
            "output": null,
            "error_message": "Payment gateway timeout",
            "error_code": "PAYMENT_TIMEOUT",
            "wait_until": "2025-04-07T12:05:10Z"
        }
    },
    "_completed_steps": ["validate_order"],
    "_compensation_log": []
}
```

### Accessing Step State

```python
from src.app.db.workflow_execution import WorkflowExecution

execution = await session.get(WorkflowExecution, execution_id)

# Get step states
step_states = execution.execution_context.get("_step_states", {})

# Get a specific step state
validate_step = step_states.get("validate_order", {})
status = validate_step.get("status")
output = validate_step.get("output")
attempt_count = validate_step.get("attempt_count")
error = validate_step.get("error_message")
```

### Completed Steps

The `_completed_steps` list tracks which steps have succeeded:

```python
completed = execution.execution_context.get("_completed_steps", [])
if "validate_order" in completed:
    print("Order was validated")
```

### Compensation Log

When compensation runs, each step's result is recorded:

```python
compensation_log = execution.execution_context.get("_compensation_log", [])
for entry in compensation_log:
    step_name = entry["step"]
    status = entry["status"]  # "succeeded" or "failed"
    if status == "failed":
        error = entry.get("error")
        print(f"Compensation failed for {step_name}: {error}")
```

## Database vs Queue State

The template uses two complementary state stores:

### Database State (WorkflowExecution)

The **source of truth** for workflow progress:

```python
execution = WorkflowExecution(
    workflow_name="order_workflow",
    workflow_version="1.0.0",
    status="running",              # Current execution state
    current_step="validate_order", # Which step to execute next
    execution_context={            # Step state and shared data
        "_step_states": {...},
        "_completed_steps": [...],
        "_compensation_log": [...]
    },
    execution_context={...},
    correlation_id="req-123",
    tenant_id="tenant-456",
)
```

Use the database for:
- **Durability**: Survives application restarts
- **Operator visibility**: View execution history and state
- **Audit trails**: Track what happened and when
- **Complex queries**: Join with other tables, build reports
- **State inspection**: Check current execution at any time

### Queue State (ARQ)

The **transport mechanism** for step chaining:

```python
# Enqueue a step job
await WorkflowStepJob.enqueue_step(
    pool=redis_pool,
    execution_id=execution.id,
)
```

Use the queue for:
- **Asynchronous execution**: Don't block the request
- **Delayed execution**: Use ARQ's delay/schedule features
- **Concurrency control**: Process steps in parallel or serially
- **Load balancing**: Distribute work across worker processes
- **Timing**: Schedule retries after a backoff delay

### State Consistency

The database is always authoritative. Here's the flow:

1. **Request arrives** → Start a new workflow execution in the database
2. **Enqueue step job** → Add WorkflowStepJob to the queue with execution_id
3. **Worker picks up job** → Load execution from database (use execution_id)
4. **Worker executes step** → Update execution_context._step_states in memory
5. **Worker updates database** → Persist the updated execution record
6. **Check for next step** → Read execution.status from database
7. **If RUNNING** → Enqueue the next step (or schedule resumption)
8. **If WAITING** → Wait for wait_until time, then resume
9. **If FAILED/SUCCEEDED** → Cleanup and notify

!!! tip
    If a job fails and is retried, it reads the latest database state. This ensures correct behavior even if the queue job is processed multiple times or out of order.

### Best Practices

- **Always use database for state decisions**: Read `execution.status` and `execution.current_step` from the database, never cache them in the job process
- **Persist after every state change**: Call `session.commit()` after `runner.advance()` or `runner.resume()`
- **Use correlation_id**: Link workflow executions to requests for debugging
- **Archive old executions**: Periodically archive completed executions to keep the database lean
- **Monitor queue depth**: High queue depth indicates slow workers or bottlenecks

## Full Example: Order Processing Workflow

Here's a complete example of an order processing workflow with all features:

```python
from datetime import UTC, datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from src.app.core.worker.workflow import (
    WorkflowDefinition,
    WorkflowRunner,
    WorkflowContext,
    StepResult,
    StepStatus,
    StepRetryPolicy,
    register_workflow,
    get_workflow,
)
from src.app.core.worker.retry import BACKOFF_STANDARD

class ValidateOrderStep:
    step_name = "validate_order"
    timeout_seconds = 5.0
    retry_policy = StepRetryPolicy(max_attempts=2)

    async def execute(self, context: WorkflowContext) -> StepResult:
        order_id = context.input_payload.get("order_id")
        items = context.input_payload.get("items", [])

        if not order_id or not items:
            return StepResult(
                status=StepStatus.FAILED,
                error_message="Missing order_id or items",
                error_code="INVALID_INPUT",
            )

        return StepResult(
            status=StepStatus.SUCCEEDED,
            output={"order_id": order_id, "item_count": len(items)},
        )

class ReserveInventoryStep:
    step_name = "reserve_inventory"
    timeout_seconds = 10.0
    retry_policy = StepRetryPolicy(
        max_attempts=3,
        backoff=BACKOFF_STANDARD,
    )

    async def execute(self, context: WorkflowContext) -> StepResult:
        order_id = context.input_payload["order_id"]
        items = context.input_payload["items"]

        reservation_id = await inventory_service.reserve(order_id, items)

        return StepResult(
            status=StepStatus.SUCCEEDED,
            output={"reservation_id": reservation_id},
        )

    async def compensate(self, context: WorkflowContext) -> None:
        """Release inventory reservation if payment fails."""
        output = context.step_outputs.get("reserve_inventory", {})
        reservation_id = output.get("reservation_id")

        if reservation_id:
            await inventory_service.release(reservation_id)

class ChargePaymentStep:
    step_name = "charge_payment"
    timeout_seconds = 30.0
    retry_policy = StepRetryPolicy(
        max_attempts=5,
        backoff=BACKOFF_STANDARD,
    )

    async def execute(self, context: WorkflowContext) -> StepResult:
        order_id = context.input_payload["order_id"]
        amount = context.input_payload["amount"]

        charge_id = await payment_gateway.charge(
            customer_id=order_id,
            amount=amount,
        )

        return StepResult(
            status=StepStatus.SUCCEEDED,
            output={"charge_id": charge_id},
        )

    async def compensate(self, context: WorkflowContext) -> None:
        """Refund if shipment fails."""
        output = context.step_outputs.get("charge_payment", {})
        charge_id = output.get("charge_id")

        if charge_id:
            await payment_gateway.refund(charge_id)

class CreateShipmentStep:
    step_name = "create_shipment"
    timeout_seconds = 15.0
    retry_policy = StepRetryPolicy(
        max_attempts=3,
        backoff=BACKOFF_STANDARD,
    )

    async def execute(self, context: WorkflowContext) -> StepResult:
        order_id = context.input_payload["order_id"]
        reservation = context.step_outputs.get("reserve_inventory", {})
        reservation_id = reservation.get("reservation_id")

        shipment_id = await shipping_service.create(
            order_id=order_id,
            reservation_id=reservation_id,
        )

        return StepResult(
            status=StepStatus.SUCCEEDED,
            output={"shipment_id": shipment_id},
        )

    async def compensate(self, context: WorkflowContext) -> None:
        """Cancel shipment if something fails downstream."""
        output = context.step_outputs.get("create_shipment", {})
        shipment_id = output.get("shipment_id")

        if shipment_id:
            await shipping_service.cancel(shipment_id)

# Define the workflow
order_workflow = WorkflowDefinition(
    name="order_processing",
    steps=[
        ValidateOrderStep(),
        ReserveInventoryStep(),
        ChargePaymentStep(),
        CreateShipmentStep(),
    ],
    version="1.0.0",
    max_attempts=3,
)

# Register for runtime lookup
register_workflow(order_workflow)

# In your API:
from fastapi import FastAPI, Depends
from src.app.platform import queue, get_correlation_id
from src.app.core.worker.workflow import WorkflowStepJob

app = FastAPI()

@app.post("/orders")
async def create_order(
    order: OrderCreate,
    session: AsyncSession = Depends(get_db_session),
    correlation_id: str = Depends(get_correlation_id),
):
    """Create an order and start the processing workflow."""

    workflow = get_workflow("order_processing")
    runner = WorkflowRunner(workflow)

    # Create the execution record
    execution = await runner.start(
        session,
        input_payload=order.dict(),
        trigger_source="api.orders.create",
        correlation_id=correlation_id,
        tenant_id=get_tenant_id(),
    )
    await session.commit()

    # Enqueue the first step
    if queue.pool is not None:
        await WorkflowStepJob.enqueue_step(
            queue.pool,
            execution_id=execution.id,
            correlation_id=correlation_id,
        )

    return {"execution_id": execution.id, "status": "processing"}

@app.get("/orders/{execution_id}/status")
async def get_order_status(
    execution_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Get the current status of an order workflow."""

    execution = await session.get(WorkflowExecution, execution_id)
    if not execution:
        raise HTTPException(status_code=404)

    return {
        "execution_id": execution.id,
        "status": execution.status,
        "current_step": execution.current_step,
        "completed_steps": execution.execution_context.get("_completed_steps", []),
        "error": execution.error_detail,
    }
```

This example demonstrates:
- Multi-step workflow definition
- Compensation (rollback) on failure
- Retry policies with backoff
- Data flow between steps
- API integration with workflow orchestration
