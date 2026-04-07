"""Workflow orchestration abstraction for multi-step processes.

This module provides reusable workflow definitions and execution engines
that coordinate complex multi-step operations with built-in support for:

- Step-by-step execution with isolated error handling
- Conditional branching and step skipping
- Automatic retry and backoff at the step level
- Compensation (rollback) steps for saga-pattern transactions
- Delayed execution and resumable workflows (WAITING status)
- Durable progress tracking via WorkflowExecution database model
- Queue-based chaining for long-running workflows

Database vs Queue State
~~~~~~~~~~~~~~~~~~~~~~~~
- **Database (WorkflowExecution)**: Source of truth for durable state,
  crash recovery, operator visibility, and audit trails
- **Queue (ARQ)**: Transport mechanism for step-to-step chaining,
  delayed execution, and concurrency control

The database state is always authoritative. The queue is used to
trigger execution and manage timing.

Design Pattern: Workflow Registry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Workflows are registered in a module-level registry and retrieved by name
at runtime. This enables dynamic workflow discovery and late binding.

    workflow_definition = get_workflow("my_workflow")
    runner = WorkflowRunner(workflow_definition)
    execution = await runner.start(session, ...)

Step State Storage
~~~~~~~~~~~~~~~~~~~
Per-step execution state is tracked inside WorkflowExecution.execution_context
under the "_step_states" key:

    {
        "_step_states": {
            "step_name": {
                "status": "succeeded",
                "started_at": "2025-04-07T12:00:00Z",
                "completed_at": "2025-04-07T12:00:05Z",
                "attempt_count": 1,
                "output": {...},
                "error_message": None,
                "error_code": None,
                "wait_until": None
            }
        },
        "_completed_steps": ["validate_input"],
        "_compensation_log": [...]
    }
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, TypedDict, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.workflow_execution import WorkflowExecution, WorkflowExecutionStatus
from .logging import get_job_logger
from .retry import BackoffPolicy

__all__ = [
    "StepStatus",
    "StepResult",
    "StepRetryPolicy",
    "WorkflowContext",
    "WorkflowStep",
    "CompensatingStep",
    "WorkflowDefinition",
    "WorkflowRunner",
    "WorkflowStepJob",
    "WorkflowStepState",
    "register_workflow",
    "get_workflow",
]


class StepStatus(StrEnum):
    """Enum for possible step execution outcomes."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    WAITING = "waiting"
    SKIPPED = "skipped"


class WorkflowStepState(TypedDict, total=False):
    """Per-step execution state stored in execution_context._step_states.

    This TypedDict tracks the runtime state of each step including its
    status, timing, retry attempts, output, and any errors encountered.
    """

    status: str
    """StepStatus value (succeeded, failed, waiting, skipped)."""

    started_at: str
    """ISO 8601 datetime when step execution started."""

    completed_at: str | None
    """ISO 8601 datetime when step execution completed, or None if in progress."""

    attempt_count: int
    """Number of times this step has been attempted."""

    output: dict[str, Any] | None
    """Data returned by the step to merge into workflow context."""

    error_message: str | None
    """Human-readable error message from step failure."""

    error_code: str | None
    """Machine-readable error code from step failure."""

    wait_until: str | None
    """ISO 8601 datetime for delayed retry/waiting steps."""


@dataclass(frozen=True, slots=True)
class StepRetryPolicy:
    """Retry configuration for a single workflow step."""

    max_attempts: int = 3
    """Maximum number of attempts before step failure."""

    backoff: BackoffPolicy | None = None
    """Optional exponential backoff policy for retries."""

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("Step retry policy max_attempts must be at least 1")


@dataclass
class StepResult:
    """Typed result of a workflow step execution."""

    status: StepStatus
    """Overall outcome: succeeded, failed, waiting, or skipped."""

    output: dict[str, Any] | None = None
    """Data to merge into workflow context (for SUCCEEDED or WAITING steps)."""

    error_message: str | None = None
    """Human-readable error message (for FAILED steps)."""

    error_code: str | None = None
    """Machine-readable error code (for FAILED steps)."""

    wait_until: datetime | None = None
    """For WAITING steps: resume after this datetime."""

    next_step_override: str | None = None
    """For conditional branching: override the next step name."""


@dataclass
class WorkflowContext:
    """Shared context passed to each step during execution.

    This context is built from the WorkflowExecution record and includes
    all inputs, outputs from previous steps, and mutable shared state.
    """

    workflow_execution_id: int
    """Database ID of the WorkflowExecution record."""

    workflow_name: str
    """Name of the workflow being executed."""

    current_step: str
    """Name of the currently executing step."""

    input_payload: dict[str, Any]
    """Original workflow input data (immutable)."""

    step_outputs: dict[str, dict[str, Any]]
    """Outputs from previous steps keyed by step name."""

    execution_context: dict[str, Any]
    """Mutable shared state for step-to-step communication."""

    correlation_id: str | None = None
    """Optional correlation ID for tracing."""

    tenant_id: str | None = None
    """Optional tenant identifier."""

    organization_id: str | None = None
    """Optional organization identifier."""

    attempt_count: int = 0
    """Current attempt number for the workflow."""


@runtime_checkable
class WorkflowStep(Protocol):
    """Protocol defining a single step in a workflow.

    Any class implementing this protocol can be used as a workflow step.
    Steps are executed in the order they appear in the WorkflowDefinition.
    """

    step_name: str
    """Unique identifier for this step within the workflow."""

    timeout_seconds: float | None
    """Optional per-step timeout in seconds."""

    retry_policy: StepRetryPolicy | None
    """Optional per-step retry policy."""

    async def execute(self, context: WorkflowContext) -> StepResult:
        """Execute this step.

        Args:
            context: Workflow context with inputs and previous outputs.

        Returns:
            StepResult describing the outcome and any data to emit.

        Raises:
            Exception: Any exception is treated as a step failure.
        """
        ...


@runtime_checkable
class CompensatingStep(WorkflowStep, Protocol):
    """Extended WorkflowStep that supports rollback/compensation.

    Used for saga-pattern transactions where steps need to be
    compensated (rolled back) if a later step fails.
    """

    async def compensate(self, context: WorkflowContext) -> None:
        """Compensate (rollback) this step's side effects.

        Called when a later step fails and this step has already
        succeeded. Should undo the work done by execute().

        Args:
            context: Workflow context at the point of failure.

        Raises:
            Exception: Compensation failures are logged but do not
                      re-throw (best-effort cleanup).
        """
        ...


@dataclass
class WorkflowDefinition:
    """Definition of a complete workflow.

    Workflows are sequences of steps with optional retry policies,
    branching, and compensation logic. Definitions are registered
    globally and retrieved at runtime.
    """

    name: str
    """Unique name for this workflow."""

    steps: list[WorkflowStep]
    """Ordered list of steps to execute."""

    version: str = "1"
    """Optional semantic version for the workflow."""

    max_attempts: int = 3
    """Maximum retry attempts for the entire workflow."""

    def get_step(self, name: str) -> WorkflowStep | None:
        """Retrieve a step by name.

        Args:
            name: Step name to find.

        Returns:
            The WorkflowStep or None if not found.
        """
        for step in self.steps:
            if step.step_name == name:
                return step
        return None

    def get_step_index(self, name: str) -> int | None:
        """Get the index of a step by name.

        Args:
            name: Step name to find.

        Returns:
            The 0-based index or None if not found.
        """
        for idx, step in enumerate(self.steps):
            if step.step_name == name:
                return idx
        return None

    def get_next_step(self, current: str) -> WorkflowStep | None:
        """Get the step following the current step.

        Args:
            current: Name of the current step.

        Returns:
            The next WorkflowStep or None if current is the last step.
        """
        idx = self.get_step_index(current)
        if idx is None or idx >= len(self.steps) - 1:
            return None
        return self.steps[idx + 1]

    def get_steps_for_compensation(self, up_to: str) -> list[CompensatingStep]:
        """Get all compensating steps up to and including the named step.

        Returns steps in reverse order (last to first), filtering only
        those that implement the CompensatingStep protocol.

        Args:
            up_to: Name of the step to compensate up to (inclusive).

        Returns:
            List of CompensatingStep instances in reverse order.
        """
        idx = self.get_step_index(up_to)
        if idx is None:
            return []

        compensating = []
        for i in range(idx, -1, -1):
            step = self.steps[i]
            if isinstance(step, CompensatingStep):
                compensating.append(step)

        return compensating


class WorkflowRunner:
    """Engine for executing a workflow definition.

    The runner orchestrates step execution, handles retries and failures,
    manages the WAITING state for delayed steps, and runs compensation
    logic for distributed transactions.
    """

    def __init__(self, definition: WorkflowDefinition) -> None:
        """Initialize the runner with a workflow definition.

        Args:
            definition: WorkflowDefinition to execute.
        """
        self.definition = definition
        self.logger = get_job_logger(job_name="workflow_runner")

    async def start(
        self,
        session: AsyncSession,
        *,
        input_payload: dict[str, Any],
        trigger_source: str,
        correlation_id: str | None = None,
        tenant_id: str | None = None,
        organization_id: str | None = None,
        run_key: str | None = None,
    ) -> WorkflowExecution:
        """Create and start a new workflow execution.

        Creates a new WorkflowExecution record, initializes the execution
        context, sets status to RUNNING, and begins the first step.

        Args:
            session: AsyncSession for database operations.
            input_payload: Initial workflow input data.
            trigger_source: Source that triggered this workflow (e.g., "api", "event").
            correlation_id: Optional correlation ID for tracing.
            tenant_id: Optional tenant identifier.
            organization_id: Optional organization identifier.
            run_key: Optional idempotency key to prevent duplicate executions.

        Returns:
            The created WorkflowExecution record (not yet executed).

        Raises:
            ValueError: If workflow has no steps.
        """
        if not self.definition.steps:
            raise ValueError(f"Workflow {self.definition.name} has no steps")

        now = datetime.now(UTC)
        execution_context: dict[str, Any] = {
            "_step_states": {},
            "_completed_steps": [],
            "_compensation_log": [],
        }

        execution = WorkflowExecution(
            workflow_name=self.definition.name,
            workflow_version=self.definition.version,
            trigger_source=trigger_source,
            trigger_reference=run_key,
            run_key=run_key,
            correlation_id=correlation_id,
            status=WorkflowExecutionStatus.RUNNING.value,
            current_step=self.definition.steps[0].step_name,
            attempt_count=1,
            max_attempts=self.definition.max_attempts,
            scheduled_at=now,
            started_at=now,
            last_transition_at=now,
            input_payload=input_payload,
            execution_context=execution_context,
        )

        session.add(execution)
        await session.flush()

        self.logger.info(
            "Workflow started",
            workflow_name=self.definition.name,
            execution_id=execution.id,
            first_step=execution.current_step,
            correlation_id=correlation_id,
        )

        return execution

    async def execute_step(
        self,
        session: AsyncSession,
        execution: WorkflowExecution,
        step: WorkflowStep,
    ) -> StepResult:
        """Execute a single step.

        Builds the WorkflowContext, calls the step's execute method,
        captures output, and updates the execution_context with step state.

        Args:
            session: AsyncSession for database operations.
            execution: Current WorkflowExecution record.
            step: WorkflowStep to execute.

        Returns:
            StepResult from the step execution.
        """
        context = self._build_context(execution, step)
        step_states = self._get_step_states(execution)
        step_state = step_states.get(step.step_name, {})
        attempt_count = step_state.get("attempt_count", 0) + 1

        now = datetime.now(UTC)
        start_state: WorkflowStepState = {
            "status": StepStatus.SUCCEEDED.value,
            "started_at": now.isoformat(),
            "attempt_count": attempt_count,
        }
        self._update_step_state(execution, step.step_name, start_state)

        try:
            self.logger.info(
                "Executing step",
                workflow_name=self.definition.name,
                execution_id=execution.id,
                step_name=step.step_name,
                attempt=attempt_count,
            )

            result = await step.execute(context)

            completed_now = datetime.now(UTC)
            end_state: WorkflowStepState = {
                "status": result.status.value,
                "completed_at": completed_now.isoformat(),
                "attempt_count": attempt_count,
                "output": result.output,
                "error_message": result.error_message,
                "error_code": result.error_code,
                "wait_until": result.wait_until.isoformat() if result.wait_until else None,
            }
            self._update_step_state(execution, step.step_name, end_state)

            self.logger.info(
                "Step execution completed",
                workflow_name=self.definition.name,
                execution_id=execution.id,
                step_name=step.step_name,
                status=result.status.value,
            )

            return result

        except Exception as exc:
            completed_now = datetime.now(UTC)
            error_state: WorkflowStepState = {
                "status": StepStatus.FAILED.value,
                "completed_at": completed_now.isoformat(),
                "attempt_count": attempt_count,
                "error_message": str(exc),
                "error_code": getattr(exc, "error_code", None),
            }
            self._update_step_state(execution, step.step_name, error_state)

            self.logger.warning(
                "Step execution failed",
                workflow_name=self.definition.name,
                execution_id=execution.id,
                step_name=step.step_name,
                error=str(exc),
                exc_info=True,
            )

            return StepResult(
                status=StepStatus.FAILED,
                error_message=str(exc),
                error_code=getattr(exc, "error_code", None),
            )

    async def advance(
        self,
        session: AsyncSession,
        execution: WorkflowExecution,
    ) -> WorkflowExecution:
        """Advance the workflow by executing the current step and determining next.

        This is the primary orchestration method. It:
        1. Loads the current step from the definition
        2. Executes the step
        3. Handles failures with retry or compensation
        4. Determines and advances to the next step
        5. Updates the execution record

        Args:
            session: AsyncSession for database operations.
            execution: Current WorkflowExecution record.

        Returns:
            Updated WorkflowExecution record.

        Raises:
            ValueError: If current_step is not found in definition.
        """
        if execution.current_step is None:
            raise ValueError("Execution has no current_step set")

        current_step = self.definition.get_step(execution.current_step)
        if current_step is None:
            raise ValueError(f"Step {execution.current_step} not found in workflow definition")

        # Execute the current step
        result = await self.execute_step(session, execution, current_step)

        if result.status == StepStatus.SUCCEEDED:
            # Record completion and advance to next step
            step_states = self._get_step_states(execution)
            step_states[current_step.step_name]["status"] = StepStatus.SUCCEEDED.value
            if execution.execution_context is None:
                execution.execution_context = {}
            if "_completed_steps" not in execution.execution_context:
                execution.execution_context["_completed_steps"] = []
            execution.execution_context["_completed_steps"].append(current_step.step_name)

            # Merge step output into execution context
            if result.output:
                if "step_outputs" not in execution.execution_context:
                    execution.execution_context["step_outputs"] = {}
                execution.execution_context["step_outputs"][current_step.step_name] = result.output

            # Determine next step
            next_step = None
            if result.next_step_override:
                next_step = self.definition.get_step(result.next_step_override)
            else:
                next_step = self.definition.get_next_step(current_step.step_name)

            if next_step:
                execution.current_step = next_step.step_name
                execution.status = WorkflowExecutionStatus.RUNNING.value
            else:
                # Workflow completed
                execution.status = WorkflowExecutionStatus.SUCCEEDED.value
                execution.completed_at = datetime.now(UTC)

            execution.last_transition_at = datetime.now(UTC)

        elif result.status == StepStatus.WAITING:
            # Step is waiting for a scheduled retry
            execution.status = WorkflowExecutionStatus.WAITING.value
            execution.last_transition_at = datetime.now(UTC)

        elif result.status == StepStatus.SKIPPED:
            # Step was skipped, advance to next
            next_step = None
            if result.next_step_override:
                next_step = self.definition.get_step(result.next_step_override)
            else:
                next_step = self.definition.get_next_step(current_step.step_name)

            if next_step:
                execution.current_step = next_step.step_name
                execution.status = WorkflowExecutionStatus.RUNNING.value
            else:
                execution.status = WorkflowExecutionStatus.SUCCEEDED.value
                execution.completed_at = datetime.now(UTC)

            execution.last_transition_at = datetime.now(UTC)

        else:  # FAILED
            # Handle step failure
            execution = await self.handle_step_failure(
                session, execution, current_step, result
            )

        await session.flush()
        return execution

    async def handle_step_failure(
        self,
        session: AsyncSession,
        execution: WorkflowExecution,
        step: WorkflowStep,
        result: StepResult,
    ) -> WorkflowExecution:
        """Handle a failed step with retry or compensation.

        If the step has remaining retry attempts, it will be re-executed.
        If retries are exhausted, compensation steps are run and the
        workflow is marked as FAILED.

        Args:
            session: AsyncSession for database operations.
            execution: Current WorkflowExecution record.
            step: The WorkflowStep that failed.
            result: StepResult from the failure.

        Returns:
            Updated WorkflowExecution record.
        """
        step_states = self._get_step_states(execution)
        step_state = step_states.get(step.step_name, {})
        attempt_count = step_state.get("attempt_count", 0)

        retry_policy = step.retry_policy or StepRetryPolicy()
        max_attempts = retry_policy.max_attempts

        if attempt_count < max_attempts:
            # Retry the step
            defer_seconds = 5.0
            if retry_policy.backoff:
                defer_seconds = retry_policy.backoff.delay_for_attempt(attempt_count - 1)

            self.logger.info(
                "Step will be retried",
                workflow_name=self.definition.name,
                execution_id=execution.id,
                step_name=step.step_name,
                attempt=attempt_count,
                max_attempts=max_attempts,
                defer_seconds=defer_seconds,
            )

            # Mark step as waiting for retry
            if execution.execution_context is None:
                execution.execution_context = {}
            if "_step_states" not in execution.execution_context:
                execution.execution_context["_step_states"] = {}

            retry_time = datetime.now(UTC)
            wait_state: WorkflowStepState = {
                "wait_until": retry_time.isoformat(),
            }
            self._update_step_state(execution, step.step_name, wait_state)

            execution.status = WorkflowExecutionStatus.WAITING.value
            execution.last_transition_at = datetime.now(UTC)

        else:
            # Exhausted retries, run compensation
            self.logger.error(
                "Step exhausted retries, running compensation",
                workflow_name=self.definition.name,
                execution_id=execution.id,
                step_name=step.step_name,
                max_attempts=max_attempts,
            )

            await self.compensate(session, execution, step.step_name)

            execution.status = WorkflowExecutionStatus.FAILED.value
            execution.error_code = result.error_code
            execution.error_detail = result.error_message
            execution.completed_at = datetime.now(UTC)
            execution.last_transition_at = datetime.now(UTC)

        return execution

    async def compensate(
        self,
        session: AsyncSession,
        execution: WorkflowExecution,
        failed_step: str,
    ) -> None:
        """Run compensation steps in reverse order.

        Compensation is used for saga-pattern distributed transactions.
        When a step fails after others have succeeded, the succeeded steps'
        `compensate()` methods are called in reverse order to roll back
        their side effects.

        Args:
            session: AsyncSession for database operations.
            execution: Current WorkflowExecution record.
            failed_step: Name of the step that failed.
        """
        compensating_steps = self.definition.get_steps_for_compensation(failed_step)

        if not compensating_steps:
            self.logger.info(
                "No compensation steps to run",
                workflow_name=self.definition.name,
                execution_id=execution.id,
                failed_step=failed_step,
            )
            return

        failed_step_obj = self.definition.get_step(failed_step)
        if failed_step_obj is None:
            self.logger.warning(
                "Failed step not found in definition",
                workflow_name=self.definition.name,
                execution_id=execution.id,
                failed_step=failed_step,
            )
            return

        context = self._build_context(execution, failed_step_obj)

        if execution.execution_context is None:
            execution.execution_context = {}
        if "_compensation_log" not in execution.execution_context:
            execution.execution_context["_compensation_log"] = []

        for compensating_step in compensating_steps:
            try:
                self.logger.info(
                    "Running compensation step",
                    workflow_name=self.definition.name,
                    execution_id=execution.id,
                    compensation_step=compensating_step.step_name,
                )

                await compensating_step.compensate(context)

                execution.execution_context["_compensation_log"].append({
                    "step": compensating_step.step_name,
                    "status": "succeeded",
                    "timestamp": datetime.now(UTC).isoformat(),
                })

            except Exception as exc:
                self.logger.warning(
                    "Compensation step failed",
                    workflow_name=self.definition.name,
                    execution_id=execution.id,
                    compensation_step=compensating_step.step_name,
                    error=str(exc),
                    exc_info=True,
                )

                execution.execution_context["_compensation_log"].append({
                    "step": compensating_step.step_name,
                    "status": "failed",
                    "error": str(exc),
                    "timestamp": datetime.now(UTC).isoformat(),
                })

    async def resume(
        self,
        session: AsyncSession,
        execution: WorkflowExecution,
    ) -> WorkflowExecution:
        """Resume a WAITING or interrupted RUNNING workflow.

        Checks if a step was waiting and if its wait time has passed.
        If so, re-executes the step. Otherwise, continues normal execution.

        Args:
            session: AsyncSession for database operations.
            execution: Current WorkflowExecution record.

        Returns:
            Updated WorkflowExecution record.

        Raises:
            ValueError: If execution is not in RUNNING or WAITING status.
        """
        if execution.status not in (
            WorkflowExecutionStatus.RUNNING.value,
            WorkflowExecutionStatus.WAITING.value,
        ):
            raise ValueError(
                f"Cannot resume workflow in {execution.status} status; "
                "must be RUNNING or WAITING"
            )

        if execution.current_step is None:
            raise ValueError("Execution has no current_step set")

        current_step = self.definition.get_step(execution.current_step)
        if current_step is None:
            raise ValueError(f"Step {execution.current_step} not found in workflow definition")

        # Check if step was waiting and if wait time has passed
        step_states = self._get_step_states(execution)
        step_state = step_states.get(execution.current_step, {})
        wait_until_str = step_state.get("wait_until")

        if wait_until_str and execution.status == WorkflowExecutionStatus.WAITING.value:
            wait_until = datetime.fromisoformat(wait_until_str)
            if datetime.now(UTC) < wait_until:
                self.logger.info(
                    "Workflow still waiting",
                    workflow_name=self.definition.name,
                    execution_id=execution.id,
                    current_step=execution.current_step,
                    wait_until=wait_until_str,
                )
                return execution

            self.logger.info(
                "Wait time elapsed, resuming step",
                workflow_name=self.definition.name,
                execution_id=execution.id,
                current_step=execution.current_step,
            )

        # Advance normally
        return await self.advance(session, execution)

    def _build_context(self, execution: WorkflowExecution, step: WorkflowStep) -> WorkflowContext:
        """Build a WorkflowContext from an execution record.

        Args:
            execution: The WorkflowExecution record.
            step: The current WorkflowStep being executed.

        Returns:
            WorkflowContext with all inputs and previous outputs.
        """
        execution_context = execution.execution_context or {}
        step_outputs = execution_context.get("step_outputs", {})

        return WorkflowContext(
            workflow_execution_id=execution.id,
            workflow_name=self.definition.name,
            current_step=step.step_name,
            input_payload=execution.input_payload or {},
            step_outputs=step_outputs,
            execution_context=execution_context,
            correlation_id=execution.correlation_id,
            tenant_id=getattr(execution, "tenant_id", None),
            organization_id=getattr(execution, "organization_id", None),
            attempt_count=execution.attempt_count,
        )

    def _update_step_state(
        self,
        execution: WorkflowExecution,
        step_name: str,
        state: WorkflowStepState,
    ) -> None:
        """Update per-step state in execution_context._step_states.

        Merges the provided state dict into the step's existing state.

        Args:
            execution: WorkflowExecution to update.
            step_name: Name of the step.
            state: Partial or complete WorkflowStepState to merge.
        """
        if execution.execution_context is None:
            execution.execution_context = {}
        if "_step_states" not in execution.execution_context:
            execution.execution_context["_step_states"] = {}

        step_states = execution.execution_context["_step_states"]
        if step_name not in step_states:
            step_states[step_name] = {}

        step_states[step_name].update(state)

    def _get_step_states(self, execution: WorkflowExecution) -> dict[str, WorkflowStepState]:
        """Read all step states from execution_context._step_states.

        Args:
            execution: WorkflowExecution to read from.

        Returns:
            Dict mapping step names to their WorkflowStepState.
        """
        if execution.execution_context is None:
            return {}
        step_states: dict[str, WorkflowStepState] = execution.execution_context.get("_step_states", {})
        return step_states


from .jobs import JobEnvelope, RetryableJobError, WorkerContext, WorkerJob

# Type alias for the workflow registry
_WorkflowRegistry = dict[str, WorkflowDefinition]

# Module-level workflow registry
_workflow_registry: _WorkflowRegistry = {}


def register_workflow(definition: WorkflowDefinition) -> None:
    """Register a workflow definition for runtime lookup.

    Args:
        definition: WorkflowDefinition to register.

    Raises:
        ValueError: If a workflow with the same name is already registered.
    """
    if definition.name in _workflow_registry:
        raise ValueError(f"Workflow {definition.name} is already registered")
    _workflow_registry[definition.name] = definition
    get_job_logger(job_name="workflow_registry").info(
        "Workflow registered",
        workflow_name=definition.name,
        workflow_version=definition.version,
        step_count=len(definition.steps),
    )


def get_workflow(name: str) -> WorkflowDefinition | None:
    """Retrieve a registered workflow by name.

    Args:
        name: Name of the workflow to retrieve.

    Returns:
        The WorkflowDefinition or None if not registered.
    """
    return _workflow_registry.get(name)


class WorkflowStepJob(WorkerJob):
    """Worker job for chaining workflow steps via the queue.

    When a workflow has completed its current step and needs to execute
    the next one, WorkflowStepJob is enqueued to continue execution.
    This decouples step execution from the original request and enables
    long-running workflows, retry, and resumability.

    The job loads the WorkflowExecution from the database, determines the
    current step from the definition, and calls runner.advance() to
    execute and transition to the next step.
    """

    job_name = "workflow_step"

    @classmethod
    async def run(cls, ctx: WorkerContext, envelope: JobEnvelope) -> dict[str, Any]:
        """Execute a workflow step via the queue.

        Loads the execution from the database, retrieves the workflow
        definition, and calls the runner to advance the workflow.

        Args:
            ctx: ARQ worker context.
            envelope: JobEnvelope with workflow execution ID.

        Returns:
            Dict with execution status and result.

        Raises:
            RetryableJobError: If the execution cannot be loaded or advanced.
            Exception: Other exceptions are treated as non-retryable job failures.
        """
        from ..db.database import local_session
        from ..db.sessions import DatabaseSessionScope, open_database_session

        execution_id = envelope.payload.get("execution_id")
        if not execution_id:
            raise ValueError("WorkflowStepJob requires execution_id in payload")

        logger = cls.get_logger(ctx=ctx, envelope=envelope, execution_id=execution_id)

        async with open_database_session(local_session, DatabaseSessionScope.BACKGROUND_JOB) as session:
            try:
                # Load the execution from the database
                execution = await session.get(WorkflowExecution, execution_id)
                if not execution:
                    raise ValueError(f"WorkflowExecution {execution_id} not found")

                # Retrieve the workflow definition
                workflow = get_workflow(execution.workflow_name)
                if not workflow:
                    raise ValueError(
                        f"Workflow {execution.workflow_name} not registered"
                    )

                runner = WorkflowRunner(workflow)

                # Advance the workflow (execute current step, determine next)
                execution = await runner.advance(session, execution)
                await session.commit()

                logger.info(
                    "Workflow step job completed",
                    execution_id=execution.id,
                    current_status=execution.status,
                    current_step=execution.current_step,
                )

                return {
                    "status": "completed",
                    "execution_id": execution.id,
                    "workflow_status": execution.status,
                    "current_step": execution.current_step,
                }

            except Exception as exc:
                logger.error(
                    "Workflow step job failed",
                    execution_id=execution_id,
                    error=str(exc),
                    exc_info=True,
                )
                raise RetryableJobError(
                    f"Failed to advance workflow: {exc}"
                ) from exc

    @classmethod
    async def enqueue_step(
        cls,
        pool: Any,
        execution_id: int,
        correlation_id: str | None = None,
        tenant_id: str | None = None,
        organization_id: str | None = None,
    ) -> Any:
        """Enqueue a workflow step job for execution.

        This is a convenience method for enqueueing a step continuation.

        Args:
            pool: ARQ Redis pool.
            execution_id: ID of the WorkflowExecution to advance.
            correlation_id: Optional correlation ID for tracing.
            tenant_id: Optional tenant identifier.
            organization_id: Optional organization identifier.

        Returns:
            ARQ Job or None if enqueue fails.
        """
        return await cls.enqueue(
            pool,
            payload={"execution_id": execution_id},
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            organization_id=organization_id,
        )
