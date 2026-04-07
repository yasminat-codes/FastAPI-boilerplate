"""Regression tests for resilience patterns (Phase 7 Wave 7.3).

Covers fallback behavior, partial failure handling, compensating actions,
and deferred retry patterns for external integration outages.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Import from the canonical integration export surface
# ---------------------------------------------------------------------------
from src.app.integrations import (
    CompensatingAction,
    CompensatingActionResult,
    CompensationContext,
    DeferredRetryRequest,
    FallbackProvider,
    IntegrationAuthError,
    IntegrationConnectionError,
    IntegrationError,
    IntegrationRateLimitError,
    IntegrationServerError,
    IntegrationTimeoutError,
    IntegrationValidationError,
    PartialFailureOutcome,
    PartialFailurePolicy,
    ResilientResult,
    ResultSource,
    build_deferred_retry_request,
    execute_with_partial_failure,
    should_defer_retry,
    with_compensation,
    with_fallback,
)
from src.app.integrations.contracts.resilience import (
    _is_auth_error,
    _is_config_error,
)

# ===================================================================
# ResilientResult tests
# ===================================================================


class TestResilientResult:
    """Test ResilientResult construction and properties."""

    def test_from_primary_creates_primary_result(self) -> None:
        """Test creating a result from successful primary operation."""
        data = {"id": "123", "name": "John"}

        result = ResilientResult.from_primary(data)

        assert result.data == data
        assert result.source == ResultSource.PRIMARY
        assert result.available is True
        assert result.degraded is False
        assert result.primary_error is None

    def test_from_fallback_creates_fallback_result(self) -> None:
        """Test creating a result from fallback after primary failed."""
        data = {"id": "123", "cached": True}
        error = IntegrationTimeoutError(
            "Primary timed out",
            provider_name="test",
            operation="get_data",
        )

        result = ResilientResult.from_fallback(data, primary_error=error)

        assert result.data == data
        assert result.source == ResultSource.FALLBACK
        assert result.available is True
        assert result.degraded is True
        assert result.primary_error is error

    def test_from_default_creates_default_result(self) -> None:
        """Test creating a result from default value after primary failed."""
        data = {"id": "unknown", "name": "Default"}
        error = IntegrationConnectionError(
            "Cannot reach provider",
            provider_name="test",
            operation="get_data",
        )

        result = ResilientResult.from_default(data, primary_error=error)

        assert result.data == data
        assert result.source == ResultSource.DEFAULT
        assert result.available is True
        assert result.degraded is True
        assert result.primary_error is error

    def test_unavailable_creates_none_result(self) -> None:
        """Test creating an unavailable result when all sources fail."""
        error = IntegrationServerError(
            "Provider error",
            provider_name="test",
            operation="get_data",
        )

        result = ResilientResult.unavailable(primary_error=error)

        assert result.data is None
        assert result.source == ResultSource.NONE
        assert result.available is False
        assert result.degraded is True
        assert result.primary_error is error


# ===================================================================
# with_fallback tests
# ===================================================================


class TestWithFallback:
    """Test with_fallback resilient operation helper."""

    @pytest.mark.asyncio
    async def test_primary_success_returns_primary_data(self) -> None:
        """Test primary operation success returns primary data."""
        expected = {"id": "123", "name": "John"}
        primary = AsyncMock(return_value=expected)

        result = await with_fallback(primary, operation="get_data")

        assert result.source == ResultSource.PRIMARY
        assert result.data == expected
        assert result.degraded is False
        primary.assert_called_once()

    @pytest.mark.asyncio
    async def test_primary_retryable_error_no_fallback_returns_unavailable(
        self,
    ) -> None:
        """Test retryable primary error with no fallback returns unavailable."""
        error = IntegrationTimeoutError(
            "Timeout",
            provider_name="test",
            operation="get_data",
        )
        primary = AsyncMock(side_effect=error)

        result = await with_fallback(primary, operation="get_data")

        assert result.source == ResultSource.NONE
        assert result.data is None
        assert result.degraded is True
        assert result.primary_error is error

    @pytest.mark.asyncio
    async def test_primary_retryable_error_with_fallback_returns_fallback(
        self,
    ) -> None:
        """Test retryable error falls back to fallback provider."""
        error = IntegrationConnectionError(
            "Connection failed",
            provider_name="test",
            operation="get_data",
        )
        primary = AsyncMock(side_effect=error)

        fallback_data = {"id": "cached"}
        fallback = MagicMock(spec=FallbackProvider)
        fallback.get_fallback = AsyncMock(return_value=fallback_data)

        result = await with_fallback(
            primary,
            fallback=fallback,
            operation="get_data",
        )

        assert result.source == ResultSource.FALLBACK
        assert result.data == fallback_data
        assert result.degraded is True
        fallback.get_fallback.assert_called_once()

    @pytest.mark.asyncio
    async def test_primary_error_fallback_unavailable_uses_default(
        self,
    ) -> None:
        """Test fallback unavailable falls back to default value."""
        error = IntegrationServerError(
            "Server error",
            provider_name="test",
            operation="get_data",
        )
        primary = AsyncMock(side_effect=error)

        fallback = MagicMock(spec=FallbackProvider)
        fallback.get_fallback = AsyncMock(return_value=None)

        default = {"id": "default", "fallback": True}

        result = await with_fallback(
            primary,
            fallback=fallback,
            default=default,
            operation="get_data",
        )

        assert result.source == ResultSource.DEFAULT
        assert result.data == default
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_non_retryable_error_no_fallback_attempt(self) -> None:
        """Test non-retryable error does not attempt fallback."""
        error = IntegrationAuthError(
            "Auth failed",
            provider_name="test",
            operation="get_data",
        )
        primary = AsyncMock(side_effect=error)

        fallback = MagicMock(spec=FallbackProvider)
        fallback.get_fallback = AsyncMock(return_value={"cached": True})

        result = await with_fallback(
            primary,
            fallback=fallback,
            operation="get_data",
        )

        assert result.source == ResultSource.NONE
        assert result.data is None
        # Fallback should not be called for non-retryable errors
        fallback.get_fallback.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_provider_error_falls_through_to_default(
        self,
    ) -> None:
        """Test fallback provider exception falls through to default."""
        error = IntegrationTimeoutError(
            "Timeout",
            provider_name="test",
            operation="get_data",
        )
        primary = AsyncMock(side_effect=error)

        fallback = MagicMock(spec=FallbackProvider)
        fallback.get_fallback = AsyncMock(
            side_effect=Exception("Fallback error")
        )

        default = {"id": "default"}

        result = await with_fallback(
            primary,
            fallback=fallback,
            default=default,
            operation="get_data",
        )

        assert result.source == ResultSource.DEFAULT
        assert result.data == default


# ===================================================================
# PartialFailurePolicy tests
# ===================================================================


class TestPartialFailurePolicy:
    """Test PartialFailurePolicy configuration."""

    def test_default_policy_values(self) -> None:
        """Test default policy values."""
        policy = PartialFailurePolicy()

        assert policy.max_failure_ratio == 0.5
        assert policy.fail_fast_on_auth is True
        assert policy.fail_fast_on_config is True
        assert policy.collect_errors is True

    def test_custom_policy_values(self) -> None:
        """Test custom policy values."""
        policy = PartialFailurePolicy(
            max_failure_ratio=0.1,
            fail_fast_on_auth=False,
            fail_fast_on_config=False,
            collect_errors=False,
        )

        assert policy.max_failure_ratio == 0.1
        assert policy.fail_fast_on_auth is False
        assert policy.fail_fast_on_config is False
        assert policy.collect_errors is False

    def test_invalid_failure_ratio_raises(self) -> None:
        """Test invalid failure ratio raises ValueError."""
        with pytest.raises(ValueError, match="max_failure_ratio"):
            PartialFailurePolicy(max_failure_ratio=1.5)

        with pytest.raises(ValueError, match="max_failure_ratio"):
            PartialFailurePolicy(max_failure_ratio=-0.1)


# ===================================================================
# execute_with_partial_failure tests
# ===================================================================


class TestExecuteWithPartialFailure:
    """Test execute_with_partial_failure operation."""

    @pytest.mark.asyncio
    async def test_all_items_succeed(self) -> None:
        """Test all items succeed returns ALL_SUCCEEDED."""
        items = [1, 2, 3]
        operation = AsyncMock(side_effect=lambda x: x * 10)

        result = await execute_with_partial_failure(
            items,
            operation,
            provider_name="test",
        )

        assert result.outcome == PartialFailureOutcome.ALL_SUCCEEDED
        assert len(result.succeeded) == 3
        assert len(result.failed) == 0
        assert result.aborted_at is None
        assert result.total == 3
        assert result.failure_ratio == 0.0

    @pytest.mark.asyncio
    async def test_all_items_fail(self) -> None:
        """Test all items fail returns ALL_FAILED."""
        items = ["a", "b", "c"]
        error = IntegrationError("Error", provider_name="test")
        operation = AsyncMock(side_effect=error)

        result = await execute_with_partial_failure(
            items,
            operation,
            provider_name="test",
        )

        assert result.outcome == PartialFailureOutcome.ALL_FAILED
        assert len(result.succeeded) == 0
        assert len(result.failed) == 3
        assert result.failure_ratio == 1.0

    @pytest.mark.asyncio
    async def test_partial_success_mixed_results(self) -> None:
        """Test partial success with mixed results."""

        async def mixed_op(x: int) -> int:
            if x == 2:
                raise IntegrationError(
                    "Error", provider_name="test"
                )
            return x

        items = [1, 2, 3]

        result = await execute_with_partial_failure(
            items,
            mixed_op,
            provider_name="test",
        )

        assert result.outcome == PartialFailureOutcome.PARTIAL_SUCCESS
        assert len(result.succeeded) == 2
        assert len(result.failed) == 1
        assert result.failure_ratio == pytest.approx(1 / 3)

    @pytest.mark.asyncio
    async def test_fail_fast_on_auth_error(self) -> None:
        """Test abort on auth error respects fail_fast_on_auth."""
        items = ["a", "b", "c"]
        auth_error = IntegrationAuthError(
            "Auth failed",
            provider_name="test",
        )

        async def op_with_auth_error(x: str) -> str:
            if x == "b":
                raise auth_error
            return x

        policy = PartialFailurePolicy(fail_fast_on_auth=True)

        result = await execute_with_partial_failure(
            items,
            op_with_auth_error,
            policy=policy,
            provider_name="test",
        )

        assert result.outcome == PartialFailureOutcome.ABORTED
        assert result.aborted_at == 1  # Failed at index 1
        assert len(result.succeeded) == 1
        assert len(result.failed) == 1

    @pytest.mark.asyncio
    async def test_failure_ratio_exceeded_aborts(self) -> None:
        """Test abort when failure ratio exceeded."""
        items = [1, 2, 3, 4]
        error = IntegrationError("Error", provider_name="test")

        async def fail_on_even(x: int) -> int:
            if x % 2 == 0:
                raise error
            return x

        policy = PartialFailurePolicy(max_failure_ratio=0.25)

        result = await execute_with_partial_failure(
            items,
            fail_on_even,
            policy=policy,
            provider_name="test",
        )

        assert result.outcome == PartialFailureOutcome.ABORTED
        assert len(result.failed) >= 1

    @pytest.mark.asyncio
    async def test_collect_errors_false_stops_at_first(self) -> None:
        """Test collect_errors=False stops at first error."""
        items = [1, 2, 3]
        error = IntegrationError("Error", provider_name="test")

        async def fail_on_two(x: int) -> int:
            if x == 2:
                raise error
            return x

        policy = PartialFailurePolicy(collect_errors=False)

        result = await execute_with_partial_failure(
            items,
            fail_on_two,
            policy=policy,
            provider_name="test",
        )

        assert result.outcome == PartialFailureOutcome.ABORTED
        assert result.aborted_at == 1
        assert len(result.succeeded) == 1
        assert len(result.failed) == 1

    @pytest.mark.asyncio
    async def test_retryable_failures_property(self) -> None:
        """Test retryable_failures filters for retryable errors."""
        items = ["a", "b", "c"]
        timeout_error = IntegrationTimeoutError(
            "Timeout",
            provider_name="test",
        )
        auth_error = IntegrationAuthError(
            "Auth", provider_name="test"
        )

        async def mixed_errors(x: str) -> str:
            if x == "a":
                raise timeout_error
            elif x == "b":
                raise auth_error
            return x

        result = await execute_with_partial_failure(
            items,
            mixed_errors,
            provider_name="test",
        )

        retryable = result.retryable_failures
        assert len(retryable) == 1  # Only timeout error is retryable
        assert retryable[0][0] == "a"


# ===================================================================
# CompensationContext tests
# ===================================================================


class TestCompensationContext:
    """Test CompensationContext for multi-step workflows."""

    @pytest.mark.asyncio
    async def test_register_stores_actions(self) -> None:
        """Test register stores compensating actions."""
        ctx = CompensationContext()
        action1 = MagicMock(spec=CompensatingAction)
        action2 = MagicMock(spec=CompensatingAction)

        ctx.register(action1)
        ctx.register(action2)

        assert len(ctx._actions) == 2

    @pytest.mark.asyncio
    async def test_compensate_all_executes_in_reverse(self) -> None:
        """Test compensate_all executes actions in reverse order."""
        order: list[str] = []

        async def make_action(name: str) -> CompensatingAction:
            action = MagicMock(spec=CompensatingAction)
            action.description = name
            action.can_compensate = AsyncMock(return_value=True)

            async def execute() -> CompensatingActionResult:
                order.append(name)
                return CompensatingActionResult(
                    success=True,
                    action_description=name,
                )

            action.execute = execute
            return action

        ctx = CompensationContext()
        ctx.register(await make_action("first"))
        ctx.register(await make_action("second"))
        ctx.register(await make_action("third"))

        results = await ctx.compensate_all()

        # Results are reversed to maintain forward order
        assert [r.action_description for r in results] == [
            "third",
            "second",
            "first",
        ]
        assert order == ["third", "second", "first"]

    @pytest.mark.asyncio
    async def test_compensate_skips_cannot_compensate(self) -> None:
        """Test compensate skips actions that cannot compensate."""
        action = MagicMock(spec=CompensatingAction)
        action.description = "test_action"
        action.can_compensate = AsyncMock(return_value=False)

        ctx = CompensationContext()
        ctx.register(action)

        results = await ctx.compensate_all()

        assert len(results) == 1
        assert results[0].success is False
        assert "cannot compensate" in results[0].detail


# ===================================================================
# with_compensation tests
# ===================================================================


class TestWithCompensation:
    """Test with_compensation workflow helper."""

    @pytest.mark.asyncio
    async def test_all_steps_succeed_returns_success(self) -> None:
        """Test all steps succeed returns success outcome."""
        steps = [
            AsyncMock(return_value="step1"),
            AsyncMock(return_value="step2"),
            AsyncMock(return_value="step3"),
        ]
        compensations = [
            MagicMock(spec=CompensatingAction),
            MagicMock(spec=CompensatingAction),
            MagicMock(spec=CompensatingAction),
        ]

        outcome = await with_compensation(
            steps,
            compensations,
            provider_name="test",
        )

        assert outcome.success is True
        assert outcome.completed_steps == 3
        assert outcome.total_steps == 3
        assert outcome.failure_error is None
        assert len(outcome.compensation_results) == 0

    @pytest.mark.asyncio
    async def test_step_failure_triggers_compensation(self) -> None:
        """Test step failure triggers compensation."""
        error = IntegrationError(
            "Step failed",
            provider_name="test",
        )
        steps = [
            AsyncMock(return_value="step1"),
            AsyncMock(side_effect=error),
            AsyncMock(return_value="step3"),
        ]

        comp1 = MagicMock(spec=CompensatingAction)
        comp1.description = "comp1"
        comp1.can_compensate = AsyncMock(return_value=True)
        comp1.execute = AsyncMock(
            return_value=CompensatingActionResult(
                success=True,
                action_description="comp1",
            )
        )

        comp2 = MagicMock(spec=CompensatingAction)
        comp2.description = "comp2"

        compensations = [comp1, comp2]

        outcome = await with_compensation(
            steps,
            compensations,
            provider_name="test",
        )

        assert outcome.success is False
        assert outcome.completed_steps == 1
        assert outcome.failure_error is error
        # Only comp1 should be executed (comp2 was never registered)
        assert len(outcome.compensation_results) == 1
        comp1.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_mismatched_steps_and_compensations_raises(
        self,
    ) -> None:
        """Test mismatched steps and compensations raises ValueError."""
        steps = [AsyncMock(), AsyncMock()]
        compensations = [MagicMock(spec=CompensatingAction)]

        with pytest.raises(ValueError, match="must have the same length"):
            await with_compensation(steps, compensations)


# ===================================================================
# DeferredRetryRequest tests
# ===================================================================


class TestDeferredRetryRequest:
    """Test DeferredRetryRequest configuration."""

    def test_construction_with_defaults(self) -> None:
        """Test DeferredRetryRequest construction with defaults."""
        payload = {"id": "123"}
        req = DeferredRetryRequest(
            provider_name="stripe",
            operation="create_customer",
            payload=payload,
            error_category="timeout",
        )

        assert req.provider_name == "stripe"
        assert req.operation == "create_customer"
        assert req.payload == payload
        assert req.error_category == "timeout"
        assert req.attempt == 0
        assert req.max_attempts == 5
        assert req.backoff_policy == "standard"
        assert req.correlation_id is None

    def test_next_attempt_property(self) -> None:
        """Test next_attempt property."""
        req = DeferredRetryRequest(
            provider_name="test",
            operation="test",
            payload={},
            error_category="test",
            attempt=2,
        )

        assert req.next_attempt == 3

    def test_has_attempts_remaining_property(self) -> None:
        """Test has_attempts_remaining property."""
        req = DeferredRetryRequest(
            provider_name="test",
            operation="test",
            payload={},
            error_category="test",
            attempt=3,
            max_attempts=5,
        )

        assert req.has_attempts_remaining is True

        req_exhausted = DeferredRetryRequest(
            provider_name="test",
            operation="test",
            payload={},
            error_category="test",
            attempt=4,
            max_attempts=5,
        )

        assert req_exhausted.has_attempts_remaining is False


# ===================================================================
# should_defer_retry tests
# ===================================================================


class TestShouldDeferRetry:
    """Test should_defer_retry decision logic."""

    def test_retryable_error_defers(self) -> None:
        """Test retryable error results in deferred retry."""
        error = IntegrationTimeoutError(
            "Timeout",
            provider_name="test",
        )

        assert (
            should_defer_retry(error, current_attempt=0, max_attempts=5)
            is True
        )

    def test_non_retryable_error_does_not_defer(self) -> None:
        """Test non-retryable error does not defer."""
        error = IntegrationAuthError(
            "Auth failed",
            provider_name="test",
        )

        assert (
            should_defer_retry(error, current_attempt=0, max_attempts=5)
            is False
        )

    def test_attempts_exhausted_does_not_defer(self) -> None:
        """Test exhausted attempts does not defer."""
        error = IntegrationTimeoutError(
            "Timeout",
            provider_name="test",
        )

        assert (
            should_defer_retry(error, current_attempt=4, max_attempts=5)
            is False
        )

    def test_rate_limit_error_defers(self) -> None:
        """Test rate limit error is retryable and defers."""
        error = IntegrationRateLimitError(
            "Rate limited",
            provider_name="test",
        )

        assert (
            should_defer_retry(error, current_attempt=0, max_attempts=5)
            is True
        )


# ===================================================================
# build_deferred_retry_request tests
# ===================================================================


class TestBuildDeferredRetryRequest:
    """Test build_deferred_retry_request factory."""

    def test_builds_from_timeout_error(self) -> None:
        """Test building retry request from timeout error."""
        error = IntegrationTimeoutError(
            "Timeout",
            provider_name="stripe",
            operation="create_customer",
        )
        payload = {"email": "test@example.com"}

        req = build_deferred_retry_request(
            provider_name="stripe",
            operation="create_customer",
            payload=payload,
            error=error,
            attempt=0,
            correlation_id="trace-123",
        )

        assert req.provider_name == "stripe"
        assert req.operation == "create_customer"
        assert req.payload == payload
        assert req.error_category == "timeout"
        assert req.attempt == 0
        assert req.correlation_id == "trace-123"

    def test_builds_from_rate_limit_error(self) -> None:
        """Test building retry request from rate limit error."""
        error = IntegrationRateLimitError(
            "Rate limited",
            provider_name="api",
        )

        req = build_deferred_retry_request(
            provider_name="api",
            operation="list_items",
            payload={"limit": 100},
            error=error,
            backoff_policy="slow",
        )

        assert req.error_category == "rate_limited"
        assert req.backoff_policy == "slow"

    def test_builds_from_connection_error(self) -> None:
        """Test building retry request from connection error."""
        error = IntegrationConnectionError(
            "Connection failed",
            provider_name="service",
        )

        req = build_deferred_retry_request(
            provider_name="service",
            operation="sync",
            payload={"scope": "full"},
            error=error,
        )

        assert req.error_category == "connection"

    def test_builds_from_server_error(self) -> None:
        """Test building retry request from server error."""
        error = IntegrationServerError(
            "Server error",
            provider_name="api",
        )

        req = build_deferred_retry_request(
            provider_name="api",
            operation="query",
            payload={"q": "test"},
            error=error,
        )

        assert req.error_category == "server_error"


# ===================================================================
# Helper function tests
# ===================================================================


class TestHelperFunctions:
    """Test internal helper functions."""

    def test_is_auth_error_true_for_auth_errors(self) -> None:
        """Test _is_auth_error identifies auth errors."""
        from src.app.integrations import IntegrationCredentialError

        auth_error = IntegrationAuthError(
            "Auth failed",
            provider_name="test",
        )
        assert _is_auth_error(auth_error) is True

        cred_error = IntegrationCredentialError(
            "Missing credentials",
            provider_name="test",
        )
        assert _is_auth_error(cred_error) is True

    def test_is_auth_error_false_for_other_errors(self) -> None:
        """Test _is_auth_error returns False for non-auth errors."""
        error = IntegrationTimeoutError(
            "Timeout",
            provider_name="test",
        )
        assert _is_auth_error(error) is False

    def test_is_config_error_true_for_config_errors(self) -> None:
        """Test _is_config_error identifies config errors."""
        from src.app.integrations import (
            IntegrationConfigError,
            IntegrationModeError,
        )

        config_error = IntegrationConfigError(
            "Bad config",
            provider_name="test",
        )
        assert _is_config_error(config_error) is True

        validation_error = IntegrationValidationError(
            "Invalid data",
            provider_name="test",
        )
        assert _is_config_error(validation_error) is True

        mode_error = IntegrationModeError(
            "Invalid mode",
            provider_name="test",
        )
        assert _is_config_error(mode_error) is True

    def test_is_config_error_false_for_other_errors(self) -> None:
        """Test _is_config_error returns False for non-config errors."""
        error = IntegrationTimeoutError(
            "Timeout",
            provider_name="test",
        )
        assert _is_config_error(error) is False


# ===================================================================
# Export surface completeness tests
# ===================================================================


class TestResilienceExportSurface:
    """Verify resilience symbols are exported correctly."""

    def test_resilience_exported_from_contracts(self) -> None:
        """Test resilience symbols exported from contracts package."""
        from src.app.integrations.contracts import (
            CompensatingAction,
            CompensatingActionResult,
            CompensationContext,
            CompensationOutcome,
            DeferredRetryEnqueuer,
            DeferredRetryRequest,
            FallbackProvider,
            PartialFailureOutcome,
            PartialFailurePolicy,
            PartialFailureResult,
            ResilientResult,
            ResultSource,
            build_deferred_retry_request,
            execute_with_partial_failure,
            should_defer_retry,
            with_compensation,
            with_fallback,
        )

        assert CompensatingAction is not None
        assert CompensatingActionResult is not None
        assert CompensationContext is not None
        assert CompensationOutcome is not None
        assert DeferredRetryEnqueuer is not None
        assert DeferredRetryRequest is not None
        assert FallbackProvider is not None
        assert PartialFailureOutcome is not None
        assert PartialFailurePolicy is not None
        assert PartialFailureResult is not None
        assert ResultSource is not None
        assert ResilientResult is not None
        assert callable(build_deferred_retry_request)
        assert callable(execute_with_partial_failure)
        assert callable(should_defer_retry)
        assert callable(with_compensation)
        assert callable(with_fallback)

    def test_resilience_exported_from_integrations(self) -> None:
        """Test resilience symbols exported from top-level integrations."""
        from src.app.integrations import (
            CompensatingAction,
            ResilientResult,
            with_fallback,
        )

        assert CompensatingAction is not None
        assert ResilientResult is not None
        assert callable(with_fallback)
