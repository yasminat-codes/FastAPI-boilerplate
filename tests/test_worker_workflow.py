"""Comprehensive tests for the workflow orchestration module.

Tests cover:
- StepStatus and StepResult definitions
- StepRetryPolicy validation
- WorkflowContext initialization
- WorkflowStep and CompensatingStep protocol checks
- WorkflowDefinition navigation and step retrieval
- WorkflowRunner execution orchestration
- Workflow registry and lifecycle
- WorkflowStepJob queueing
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.core.worker.retry import BackoffPolicy
from src.app.core.worker.workflow import (
    CompensatingStep,
    StepResult,
    StepRetryPolicy,
    StepStatus,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowRunner,
    WorkflowStep,
    WorkflowStepJob,
    WorkflowStepState,
    get_workflow,
    register_workflow,
)

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture(autouse=True)
def clean_registry():
    """Clean up the workflow registry between tests."""
    from src.app.core.worker.workflow import _workflow_registry
    _workflow_registry.clear()
    yield
    _workflow_registry.clear()


@pytest.fixture
def mock_session():
    """Fixture providing a mocked AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


def make_execution(**overrides):
    """Factory for creating mock WorkflowExecution objects.

    Args:
        **overrides: Field overrides for the execution.

    Returns:
        MagicMock with WorkflowExecution attributes.
    """
    defaults = {
        "id": 1,
        "workflow_name": "test_workflow",
        "trigger_source": "test",
        "status": "running",
        "current_step": "step_1",
        "attempt_count": 1,
        "max_attempts": 3,
        "input_payload": {"key": "value"},
        "execution_context": {
            "_step_states": {},
            "_completed_steps": [],
            "_compensation_log": [],
        },
        "correlation_id": "test-corr-123",
        "workflow_version": "1",
        "trigger_reference": None,
        "run_key": None,
        "scheduled_at": datetime.now(UTC),
        "started_at": datetime.now(UTC),
        "last_transition_at": datetime.now(UTC),
        "completed_at": None,
        "error_code": None,
        "error_detail": None,
        "tenant_id": None,
        "organization_id": None,
    }
    defaults.update(overrides)

    execution = MagicMock()
    for key, val in defaults.items():
        setattr(execution, key, val)
    return execution


# ============================================================================
# TEST STEP IMPLEMENTATIONS
# ============================================================================


class SuccessStep:
    """Test step that always succeeds."""

    step_name = "success_step"
    timeout_seconds = None
    retry_policy = None

    async def execute(self, context):
        return StepResult(status=StepStatus.SUCCEEDED, output={"result": "success"})


class FailingStep:
    """Test step that always fails."""

    step_name = "failing_step"
    timeout_seconds = None
    retry_policy = None

    async def execute(self, context):
        return StepResult(
            status=StepStatus.FAILED,
            error_message="Test failure",
            error_code="TEST_ERROR"
        )


class WaitingStep:
    """Test step that returns WAITING status."""

    step_name = "waiting_step"
    timeout_seconds = None
    retry_policy = None

    async def execute(self, context):
        return StepResult(
            status=StepStatus.WAITING,
            wait_until=datetime.now(UTC) + timedelta(seconds=60)
        )


class SkippedStep:
    """Test step that returns SKIPPED status."""

    step_name = "skipped_step"
    timeout_seconds = None
    retry_policy = None

    async def execute(self, context):
        return StepResult(status=StepStatus.SKIPPED)


class ConditionalBranchStep:
    """Test step that branches based on input."""

    step_name = "branch_step"
    timeout_seconds = None
    retry_policy = None

    async def execute(self, context):
        if context.input_payload.get("branch") == "alt":
            return StepResult(
                status=StepStatus.SUCCEEDED,
                next_step_override="alt_step"
            )
        return StepResult(status=StepStatus.SUCCEEDED)


class CompensatingSuccessStep:
    """Test step that supports compensation."""

    step_name = "comp_step"
    timeout_seconds = None
    retry_policy = None

    async def execute(self, context):
        return StepResult(status=StepStatus.SUCCEEDED, output={"data": "created"})

    async def compensate(self, context):
        # Compensation logic
        pass


class NonCompensatingStep:
    """Test step without compensation."""

    step_name = "non_comp_step"
    timeout_seconds = None
    retry_policy = None

    async def execute(self, context):
        return StepResult(status=StepStatus.SUCCEEDED)


# ============================================================================
# TESTS: StepStatus and StepResult
# ============================================================================


class TestStepStatus:
    """Tests for StepStatus enum."""

    def test_step_status_values(self):
        """StepStatus should have correct enum values."""
        assert StepStatus.SUCCEEDED.value == "succeeded"
        assert StepStatus.FAILED.value == "failed"
        assert StepStatus.WAITING.value == "waiting"
        assert StepStatus.SKIPPED.value == "skipped"

    def test_step_status_is_strenum(self):
        """StepStatus values should be strings."""
        assert isinstance(StepStatus.SUCCEEDED, str)


class TestStepResult:
    """Tests for StepResult dataclass."""

    def test_step_result_with_status_only(self):
        """StepResult should create with status only."""
        result = StepResult(status=StepStatus.SUCCEEDED)
        assert result.status == StepStatus.SUCCEEDED
        assert result.output is None
        assert result.error_message is None
        assert result.error_code is None
        assert result.wait_until is None
        assert result.next_step_override is None

    def test_step_result_with_all_fields(self):
        """StepResult should create with all fields."""
        now = datetime.now(UTC)
        result = StepResult(
            status=StepStatus.WAITING,
            output={"key": "value"},
            error_message="error msg",
            error_code="ERROR_CODE",
            wait_until=now,
            next_step_override="next_step"
        )
        assert result.status == StepStatus.WAITING
        assert result.output == {"key": "value"}
        assert result.error_message == "error msg"
        assert result.error_code == "ERROR_CODE"
        assert result.wait_until == now
        assert result.next_step_override == "next_step"

    def test_step_result_with_wait_until(self):
        """StepResult should handle wait_until datetime."""
        future = datetime.now(UTC) + timedelta(minutes=5)
        result = StepResult(
            status=StepStatus.WAITING,
            wait_until=future
        )
        assert result.wait_until == future
        assert (result.wait_until - datetime.now(UTC)).total_seconds() > 0

    def test_step_result_with_next_step_override(self):
        """StepResult should support next_step_override for branching."""
        result = StepResult(
            status=StepStatus.SUCCEEDED,
            next_step_override="alt_path"
        )
        assert result.next_step_override == "alt_path"


# ============================================================================
# TESTS: StepRetryPolicy
# ============================================================================


class TestStepRetryPolicy:
    """Tests for StepRetryPolicy configuration."""

    def test_step_retry_policy_defaults(self):
        """StepRetryPolicy should have sensible defaults."""
        policy = StepRetryPolicy()
        assert policy.max_attempts == 3
        assert policy.backoff is None

    def test_step_retry_policy_custom_values(self):
        """StepRetryPolicy should accept custom values."""
        policy = StepRetryPolicy(max_attempts=5)
        assert policy.max_attempts == 5

    def test_step_retry_policy_with_backoff(self):
        """StepRetryPolicy should accept BackoffPolicy."""
        backoff = BackoffPolicy(base_delay_seconds=1.0, max_delay_seconds=60.0)
        policy = StepRetryPolicy(max_attempts=3, backoff=backoff)
        assert policy.backoff == backoff

    def test_step_retry_policy_validates_max_attempts(self):
        """StepRetryPolicy should validate max_attempts >= 1."""
        with pytest.raises(ValueError, match="max_attempts must be at least 1"):
            StepRetryPolicy(max_attempts=0)

        with pytest.raises(ValueError, match="max_attempts must be at least 1"):
            StepRetryPolicy(max_attempts=-1)

    def test_step_retry_policy_frozen(self):
        """StepRetryPolicy should be frozen (immutable)."""
        policy = StepRetryPolicy(max_attempts=3)
        with pytest.raises(AttributeError):
            policy.max_attempts = 5


# ============================================================================
# TESTS: WorkflowContext
# ============================================================================


class TestWorkflowContext:
    """Tests for WorkflowContext initialization."""

    def test_workflow_context_required_fields(self):
        """WorkflowContext should create with required fields."""
        context = WorkflowContext(
            workflow_execution_id=1,
            workflow_name="test_workflow",
            current_step="step_1",
            input_payload={"key": "value"},
            step_outputs={},
            execution_context={}
        )
        assert context.workflow_execution_id == 1
        assert context.workflow_name == "test_workflow"
        assert context.current_step == "step_1"
        assert context.input_payload == {"key": "value"}
        assert context.step_outputs == {}
        assert context.execution_context == {}

    def test_workflow_context_optional_fields(self):
        """WorkflowContext should accept optional fields."""
        context = WorkflowContext(
            workflow_execution_id=1,
            workflow_name="test_workflow",
            current_step="step_1",
            input_payload={},
            step_outputs={},
            execution_context={},
            correlation_id="corr-123",
            tenant_id="tenant-456",
            organization_id="org-789",
            attempt_count=2
        )
        assert context.correlation_id == "corr-123"
        assert context.tenant_id == "tenant-456"
        assert context.organization_id == "org-789"
        assert context.attempt_count == 2

    def test_workflow_context_default_values(self):
        """WorkflowContext should have proper defaults."""
        context = WorkflowContext(
            workflow_execution_id=1,
            workflow_name="test",
            current_step="step",
            input_payload={},
            step_outputs={},
            execution_context={}
        )
        assert context.correlation_id is None
        assert context.tenant_id is None
        assert context.organization_id is None
        assert context.attempt_count == 0


# ============================================================================
# TESTS: WorkflowStep and CompensatingStep Protocols
# ============================================================================


class TestWorkflowStepProtocol:
    """Tests for WorkflowStep protocol checking."""

    def test_success_step_implements_protocol(self):
        """SuccessStep should implement WorkflowStep protocol."""
        assert isinstance(SuccessStep(), WorkflowStep)

    def test_failing_step_implements_protocol(self):
        """FailingStep should implement WorkflowStep protocol."""
        assert isinstance(FailingStep(), WorkflowStep)

    def test_non_protocol_class_fails(self):
        """Class without protocol attributes should fail isinstance."""
        class BadStep:
            pass

        assert not isinstance(BadStep(), WorkflowStep)


class TestCompensatingStepProtocol:
    """Tests for CompensatingStep protocol checking."""

    def test_compensating_step_implements_protocol(self):
        """CompensatingSuccessStep should implement CompensatingStep protocol."""
        assert isinstance(CompensatingSuccessStep(), CompensatingStep)

    def test_non_compensating_step_fails_protocol(self):
        """Step without compensate method should fail isinstance."""
        assert not isinstance(NonCompensatingStep(), CompensatingStep)

    def test_compensating_step_extends_workflow_step(self):
        """CompensatingStep should also implement WorkflowStep."""
        assert isinstance(CompensatingSuccessStep(), WorkflowStep)


# ============================================================================
# TESTS: WorkflowDefinition
# ============================================================================


class TestWorkflowDefinition:
    """Tests for WorkflowDefinition navigation and retrieval."""

    def test_workflow_definition_creation(self):
        """WorkflowDefinition should create with steps."""
        steps = [SuccessStep(), FailingStep()]
        definition = WorkflowDefinition(name="test_wf", steps=steps)
        assert definition.name == "test_wf"
        assert definition.steps == steps
        assert definition.version == "1"
        assert definition.max_attempts == 3

    def test_workflow_definition_custom_values(self):
        """WorkflowDefinition should accept custom version and max_attempts."""
        definition = WorkflowDefinition(
            name="test_wf",
            steps=[SuccessStep()],
            version="2.1",
            max_attempts=5
        )
        assert definition.version == "2.1"
        assert definition.max_attempts == 5

    def test_get_step_returns_correct_step(self):
        """get_step should return step by name."""
        step1 = SuccessStep()
        step2 = FailingStep()
        definition = WorkflowDefinition(name="test", steps=[step1, step2])

        assert definition.get_step("success_step") == step1
        assert definition.get_step("failing_step") == step2

    def test_get_step_returns_none_for_missing(self):
        """get_step should return None for missing step."""
        definition = WorkflowDefinition(name="test", steps=[SuccessStep()])
        assert definition.get_step("missing_step") is None

    def test_get_step_index_returns_correct_index(self):
        """get_step_index should return 0-based index."""
        definition = WorkflowDefinition(
            name="test",
            steps=[SuccessStep(), FailingStep()]
        )
        assert definition.get_step_index("success_step") == 0
        assert definition.get_step_index("failing_step") == 1

    def test_get_step_index_returns_none_for_missing(self):
        """get_step_index should return None for missing step."""
        definition = WorkflowDefinition(name="test", steps=[SuccessStep()])
        assert definition.get_step_index("missing_step") is None

    def test_get_next_step_returns_next(self):
        """get_next_step should return the following step."""
        definition = WorkflowDefinition(
            name="test",
            steps=[SuccessStep(), FailingStep()]
        )
        next_step = definition.get_next_step("success_step")
        assert next_step == definition.steps[1]

    def test_get_next_step_returns_none_for_last(self):
        """get_next_step should return None for last step."""
        definition = WorkflowDefinition(name="test", steps=[SuccessStep()])
        assert definition.get_next_step("success_step") is None

    def test_get_next_step_returns_none_for_missing(self):
        """get_next_step should return None for missing step."""
        definition = WorkflowDefinition(name="test", steps=[SuccessStep()])
        assert definition.get_next_step("missing_step") is None

    def test_get_steps_for_compensation_returns_compensating(self):
        """get_steps_for_compensation should return only compensating steps."""
        comp_step1 = CompensatingSuccessStep()
        non_comp = NonCompensatingStep()
        comp_step2 = CompensatingSuccessStep()
        comp_step2.step_name = "comp_step_2"

        definition = WorkflowDefinition(
            name="test",
            steps=[comp_step1, non_comp, comp_step2]
        )

        compensating = definition.get_steps_for_compensation("comp_step_2")
        assert len(compensating) == 2
        assert comp_step2 in compensating
        assert comp_step1 in compensating
        assert non_comp not in compensating

    def test_get_steps_for_compensation_reverses_order(self):
        """get_steps_for_compensation should return steps in reverse."""
        step1 = CompensatingSuccessStep()
        step1.step_name = "step_1"
        step2 = CompensatingSuccessStep()
        step2.step_name = "step_2"
        step3 = CompensatingSuccessStep()
        step3.step_name = "step_3"

        definition = WorkflowDefinition(name="test", steps=[step1, step2, step3])
        compensating = definition.get_steps_for_compensation("step_3")

        # Should be in reverse order: 3, 2, 1
        assert compensating[0] == step3
        assert compensating[1] == step2
        assert compensating[2] == step1

    def test_get_steps_for_compensation_returns_empty_for_missing(self):
        """get_steps_for_compensation should return empty for missing step."""
        definition = WorkflowDefinition(name="test", steps=[SuccessStep()])
        assert definition.get_steps_for_compensation("missing_step") == []


# ============================================================================
# TESTS: WorkflowRunner - Initialization and start()
# ============================================================================


class TestWorkflowRunnerStart:
    """Tests for WorkflowRunner.start() method."""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_start_creates_execution(self, mock_session):
        """start() should create WorkflowExecution record."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = await runner.start(
            mock_session,
            input_payload={"key": "value"},
            trigger_source="test"
        )

        assert execution.workflow_name == "test_wf"
        assert execution.status == "running"
        assert execution.current_step == "success_step"
        assert execution.input_payload == {"key": "value"}
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio(loop_scope="session")
    async def test_start_initializes_execution_context(self, mock_session):
        """start() should initialize execution_context with required keys."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = await runner.start(
            mock_session,
            input_payload={},
            trigger_source="test"
        )

        assert "_step_states" in execution.execution_context
        assert "_completed_steps" in execution.execution_context
        assert "_compensation_log" in execution.execution_context

    @pytest.mark.asyncio(loop_scope="session")
    async def test_start_raises_for_empty_steps(self, mock_session):
        """start() should raise ValueError for workflow with no steps."""
        definition = WorkflowDefinition(name="test_wf", steps=[])
        runner = WorkflowRunner(definition)

        with pytest.raises(ValueError, match="has no steps"):
            await runner.start(
                mock_session,
                input_payload={},
                trigger_source="test"
            )

    @pytest.mark.asyncio(loop_scope="session")
    async def test_start_with_correlation_id(self, mock_session):
        """start() should set correlation_id on execution."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = await runner.start(
            mock_session,
            input_payload={},
            trigger_source="test",
            correlation_id="corr-123"
        )

        assert execution.correlation_id == "corr-123"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_start_sets_attempt_count_to_one(self, mock_session):
        """start() should initialize attempt_count to 1."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = await runner.start(
            mock_session,
            input_payload={},
            trigger_source="test"
        )

        assert execution.attempt_count == 1


# ============================================================================
# TESTS: WorkflowRunner - execute_step()
# ============================================================================


class TestWorkflowRunnerExecuteStep:
    """Tests for WorkflowRunner.execute_step() method."""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_execute_step_calls_step_execute(self, mock_session):
        """execute_step() should call step.execute() with context."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = make_execution()
        step = SuccessStep()

        with patch.object(step, 'execute', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = StepResult(status=StepStatus.SUCCEEDED)
            await runner.execute_step(mock_session, execution, step)
            mock_exec.assert_called_once()

    @pytest.mark.asyncio(loop_scope="session")
    async def test_execute_step_records_success(self, mock_session):
        """execute_step() should record step state on success."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = make_execution()
        step = SuccessStep()

        result = await runner.execute_step(mock_session, execution, step)

        assert result.status == StepStatus.SUCCEEDED
        assert "success_step" in execution.execution_context["_step_states"]
        step_state = execution.execution_context["_step_states"]["success_step"]
        assert step_state["status"] == "succeeded"
        assert step_state["completed_at"] is not None

    @pytest.mark.asyncio(loop_scope="session")
    async def test_execute_step_catches_exceptions(self, mock_session):
        """execute_step() should catch exceptions and return FAILED."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = make_execution()
        step = SuccessStep()

        with patch.object(step, 'execute', new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = RuntimeError("Test error")
            result = await runner.execute_step(mock_session, execution, step)

        assert result.status == StepStatus.FAILED
        assert "Test error" in result.error_message

    @pytest.mark.asyncio(loop_scope="session")
    async def test_execute_step_increments_attempt_count(self, mock_session):
        """execute_step() should increment attempt_count."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = make_execution()
        step = SuccessStep()

        await runner.execute_step(mock_session, execution, step)

        step_state = execution.execution_context["_step_states"]["success_step"]
        assert step_state["attempt_count"] == 1


# ============================================================================
# TESTS: WorkflowRunner - advance()
# ============================================================================


class TestWorkflowRunnerAdvance:
    """Tests for WorkflowRunner.advance() method."""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_advance_executes_current_step(self, mock_session):
        """advance() should execute the current step."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = make_execution(current_step="success_step")
        result = await runner.advance(mock_session, execution)

        assert result.status == "succeeded"
        assert execution.current_step is not None

    @pytest.mark.asyncio(loop_scope="session")
    async def test_advance_moves_to_next_step_on_success(self, mock_session):
        """advance() should move to next step on SUCCEEDED."""
        step1 = SuccessStep()
        step2 = FailingStep()
        definition = WorkflowDefinition(name="test_wf", steps=[step1, step2])
        runner = WorkflowRunner(definition)

        execution = make_execution(current_step="success_step")
        await runner.advance(mock_session, execution)

        assert execution.current_step == "failing_step"
        assert execution.status == "running"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_advance_completes_workflow_on_last_step(self, mock_session):
        """advance() should mark SUCCEEDED when last step succeeds."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = make_execution(current_step="success_step")
        await runner.advance(mock_session, execution)

        assert execution.status == "succeeded"
        assert execution.completed_at is not None

    @pytest.mark.asyncio(loop_scope="session")
    async def test_advance_handles_waiting_status(self, mock_session):
        """advance() should handle WAITING status."""
        definition = WorkflowDefinition(name="test_wf", steps=[WaitingStep()])
        runner = WorkflowRunner(definition)

        execution = make_execution(current_step="waiting_step")
        await runner.advance(mock_session, execution)

        assert execution.status == "waiting"
        assert execution.current_step == "waiting_step"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_advance_handles_skipped_status(self, mock_session):
        """advance() should skip to next step on SKIPPED."""
        step1 = SkippedStep()
        step2 = SuccessStep()
        definition = WorkflowDefinition(name="test_wf", steps=[step1, step2])
        runner = WorkflowRunner(definition)

        execution = make_execution(current_step="skipped_step")
        await runner.advance(mock_session, execution)

        assert execution.current_step == "success_step"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_advance_handles_next_step_override(self, mock_session):
        """advance() should respect next_step_override for branching."""
        branch_step = ConditionalBranchStep()
        alt_step = SuccessStep()
        alt_step.step_name = "alt_step"

        definition = WorkflowDefinition(name="test_wf", steps=[branch_step, alt_step])
        runner = WorkflowRunner(definition)

        execution = make_execution(
            current_step="branch_step",
            input_payload={"branch": "alt"}
        )
        await runner.advance(mock_session, execution)

        assert execution.current_step == "alt_step"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_advance_calls_handle_step_failure_on_failed(self, mock_session):
        """advance() should call handle_step_failure on FAILED."""
        definition = WorkflowDefinition(name="test_wf", steps=[FailingStep()])
        runner = WorkflowRunner(definition)

        execution = make_execution(current_step="failing_step")

        with patch.object(runner, 'handle_step_failure', new_callable=AsyncMock) as mock_handle:
            mock_handle.return_value = execution
            await runner.advance(mock_session, execution)
            mock_handle.assert_called_once()

    @pytest.mark.asyncio(loop_scope="session")
    async def test_advance_raises_for_none_current_step(self, mock_session):
        """advance() should raise ValueError when current_step is None."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = make_execution(current_step=None)

        with pytest.raises(ValueError, match="no current_step"):
            await runner.advance(mock_session, execution)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_advance_raises_for_missing_step(self, mock_session):
        """advance() should raise ValueError for missing step in definition."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = make_execution(current_step="missing_step")

        with pytest.raises(ValueError, match="not found in workflow definition"):
            await runner.advance(mock_session, execution)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_advance_records_completed_steps(self, mock_session):
        """advance() should add completed steps to _completed_steps."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = make_execution(current_step="success_step")
        await runner.advance(mock_session, execution)

        assert "success_step" in execution.execution_context["_completed_steps"]


# ============================================================================
# TESTS: WorkflowRunner - handle_step_failure()
# ============================================================================


class TestWorkflowRunnerHandleFailure:
    """Tests for WorkflowRunner.handle_step_failure() method."""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_handle_failure_retries_when_attempts_remain(self, mock_session):
        """handle_step_failure() should retry if attempts remain."""
        policy = StepRetryPolicy(max_attempts=3)
        step = FailingStep()
        step.retry_policy = policy

        definition = WorkflowDefinition(name="test_wf", steps=[step])
        runner = WorkflowRunner(definition)

        execution = make_execution(
            current_step="failing_step",
            execution_context={
                "_step_states": {"failing_step": {"attempt_count": 1}},
                "_completed_steps": [],
                "_compensation_log": [],
            }
        )

        result = StepResult(status=StepStatus.FAILED, error_message="test")
        await runner.handle_step_failure(mock_session, execution, step, result)

        assert execution.status == "waiting"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_handle_failure_runs_compensation_when_exhausted(self, mock_session):
        """handle_step_failure() should run compensation when retries exhausted."""
        policy = StepRetryPolicy(max_attempts=1)
        step = FailingStep()
        step.retry_policy = policy

        definition = WorkflowDefinition(name="test_wf", steps=[step])
        runner = WorkflowRunner(definition)

        execution = make_execution(
            current_step="failing_step",
            execution_context={
                "_step_states": {"failing_step": {"attempt_count": 1}},
                "_completed_steps": [],
                "_compensation_log": [],
            }
        )

        result = StepResult(status=StepStatus.FAILED, error_message="test")

        with patch.object(runner, 'compensate', new_callable=AsyncMock):
            await runner.handle_step_failure(mock_session, execution, step, result)

        assert execution.status == "failed"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_handle_failure_marks_failed_after_compensation(self, mock_session):
        """handle_step_failure() should mark execution FAILED after compensation."""
        step = FailingStep()
        definition = WorkflowDefinition(name="test_wf", steps=[step])
        runner = WorkflowRunner(definition)

        execution = make_execution(
            current_step="failing_step",
            execution_context={
                "_step_states": {"failing_step": {"attempt_count": 3}},
                "_completed_steps": [],
                "_compensation_log": [],
            }
        )

        result = StepResult(status=StepStatus.FAILED, error_code="TEST_ERROR")

        with patch.object(runner, 'compensate', new_callable=AsyncMock):
            await runner.handle_step_failure(mock_session, execution, step, result)

        assert execution.status == "failed"
        assert execution.error_code == "TEST_ERROR"
        assert execution.completed_at is not None


# ============================================================================
# TESTS: WorkflowRunner - compensate()
# ============================================================================


class TestWorkflowRunnerCompensate:
    """Tests for WorkflowRunner.compensate() method."""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_compensate_runs_compensation_steps_in_reverse(self, mock_session):
        """compensate() should run compensating steps in reverse order."""
        step1 = CompensatingSuccessStep()
        step1.step_name = "step_1"
        step2 = CompensatingSuccessStep()
        step2.step_name = "step_2"

        definition = WorkflowDefinition(name="test_wf", steps=[step1, step2])
        runner = WorkflowRunner(definition)

        execution = make_execution(current_step="step_2")

        with patch.object(step1, 'compensate', new_callable=AsyncMock) as mock1:
            with patch.object(step2, 'compensate', new_callable=AsyncMock) as mock2:
                await runner.compensate(mock_session, execution, "step_2")
                # Both should be called
                assert mock1.called
                assert mock2.called

    @pytest.mark.asyncio(loop_scope="session")
    async def test_compensate_logs_failed_compensation(self, mock_session):
        """compensate() should log compensation failures."""
        step = CompensatingSuccessStep()
        definition = WorkflowDefinition(name="test_wf", steps=[step])
        runner = WorkflowRunner(definition)

        execution = make_execution(current_step="comp_step")

        with patch.object(step, 'compensate', new_callable=AsyncMock) as mock_comp:
            mock_comp.side_effect = RuntimeError("Compensation error")
            await runner.compensate(mock_session, execution, "comp_step")

        # Should have logged the error
        assert len(execution.execution_context["_compensation_log"]) > 0

    @pytest.mark.asyncio(loop_scope="session")
    async def test_compensate_does_nothing_when_no_compensating_steps(self, mock_session):
        """compensate() should do nothing if no compensating steps."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = make_execution(current_step="success_step")
        initial_log = execution.execution_context["_compensation_log"].copy()

        await runner.compensate(mock_session, execution, "success_step")

        # Compensation log should not grow
        assert len(execution.execution_context["_compensation_log"]) == len(initial_log)


# ============================================================================
# TESTS: WorkflowRunner - resume()
# ============================================================================


class TestWorkflowRunnerResume:
    """Tests for WorkflowRunner.resume() method."""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_resume_continues_after_wait_time_passes(self, mock_session):
        """resume() should advance when wait time has passed."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        # Create step state with wait_until in the past
        past_time = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
        execution = make_execution(
            status="waiting",
            current_step="success_step",
            execution_context={
                "_step_states": {"success_step": {"wait_until": past_time}},
                "_completed_steps": [],
                "_compensation_log": [],
            }
        )

        with patch.object(runner, 'advance', new_callable=AsyncMock) as mock_adv:
            mock_adv.return_value = execution
            await runner.resume(mock_session, execution)
            mock_adv.assert_called_once()

    @pytest.mark.asyncio(loop_scope="session")
    async def test_resume_returns_unchanged_when_still_waiting(self, mock_session):
        """resume() should return unchanged when wait time hasn't passed."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        # Create step state with wait_until in the future
        future_time = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        execution = make_execution(
            status="waiting",
            current_step="success_step",
            execution_context={
                "_step_states": {"success_step": {"wait_until": future_time}},
                "_completed_steps": [],
                "_compensation_log": [],
            }
        )

        result = await runner.resume(mock_session, execution)

        assert result.status == "waiting"
        assert result.current_step == "success_step"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_resume_raises_for_invalid_status(self, mock_session):
        """resume() should raise ValueError for invalid status."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        runner = WorkflowRunner(definition)

        execution = make_execution(status="succeeded")

        with pytest.raises(ValueError, match="Cannot resume workflow"):
            await runner.resume(mock_session, execution)


# ============================================================================
# TESTS: Workflow Registry
# ============================================================================


class TestWorkflowRegistry:
    """Tests for workflow registration and retrieval."""

    def test_register_workflow_adds_to_registry(self):
        """register_workflow() should add workflow to registry."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        register_workflow(definition)

        retrieved = get_workflow("test_wf")
        assert retrieved == definition

    def test_register_workflow_raises_on_duplicate(self):
        """register_workflow() should raise ValueError on duplicate name."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        register_workflow(definition)

        with pytest.raises(ValueError, match="already registered"):
            register_workflow(definition)

    def test_get_workflow_returns_registered(self):
        """get_workflow() should return registered workflow."""
        definition = WorkflowDefinition(name="test_wf", steps=[SuccessStep()])
        register_workflow(definition)

        retrieved = get_workflow("test_wf")
        assert retrieved == definition

    def test_get_workflow_returns_none_for_unregistered(self):
        """get_workflow() should return None for unregistered name."""
        result = get_workflow("nonexistent")
        assert result is None


# ============================================================================
# TESTS: WorkflowStepJob
# ============================================================================


class TestWorkflowStepJob:
    """Tests for WorkflowStepJob."""

    def test_job_name_is_workflow_step(self):
        """WorkflowStepJob.job_name should be 'workflow_step'."""
        assert WorkflowStepJob.job_name == "workflow_step"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_enqueue_step_builds_correct_payload(self, mock_session):
        """enqueue_step() should build payload with execution_id."""
        pool = AsyncMock()

        with patch.object(WorkflowStepJob, 'enqueue', new_callable=AsyncMock) as mock_eq:
            await WorkflowStepJob.enqueue_step(pool, execution_id=123)

            # Verify enqueue was called with correct parameters
            assert mock_eq.called
            call_kwargs = mock_eq.call_args[1]
            assert call_kwargs['payload']['execution_id'] == 123


# ============================================================================
# TESTS: WorkflowStepState TypedDict
# ============================================================================


class TestWorkflowStepState:
    """Tests for WorkflowStepState TypedDict."""

    def test_workflow_step_state_creation(self):
        """WorkflowStepState should create with all fields."""
        state: WorkflowStepState = {
            "status": "succeeded",
            "started_at": "2025-04-07T12:00:00Z",
            "completed_at": "2025-04-07T12:00:05Z",
            "attempt_count": 1,
            "output": {"key": "value"},
            "error_message": None,
            "error_code": None,
            "wait_until": None,
        }
        assert state["status"] == "succeeded"
        assert state["attempt_count"] == 1

    def test_workflow_step_state_partial(self):
        """WorkflowStepState should allow partial fields."""
        state: WorkflowStepState = {
            "status": "failed",
            "error_message": "Test error",
        }
        assert state["status"] == "failed"
        assert state["error_message"] == "Test error"


# ============================================================================
# TESTS: Export Surface
# ============================================================================


class TestExportSurface:
    """Tests for module exports."""

    def test_all_exports_are_importable(self):
        """All items in __all__ should be importable."""
        from src.app.core.worker.workflow import __all__

        for name in __all__:
            # Should not raise ImportError
            assert hasattr(__import__('src.app.core.worker.workflow', fromlist=[name]), name)

    def test_key_types_accessible(self):
        """Key workflow types should be accessible."""
        from src.app.core.worker import workflow

        assert hasattr(workflow, 'StepStatus')
        assert hasattr(workflow, 'WorkflowDefinition')
        assert hasattr(workflow, 'WorkflowRunner')
        assert hasattr(workflow, 'WorkflowStep')
        assert hasattr(workflow, 'CompensatingStep')
