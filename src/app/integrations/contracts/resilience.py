"""Resilience patterns for handling external integration outages and partial failures.

This module provides reusable patterns for:
- Fallback behavior when primary providers are unavailable
- Partial failure handling in bulk operations
- Compensating actions for multi-step workflows
- Deferred retries via job queue for unavailable providers

All patterns integrate with the existing error taxonomy and backoff policies
to provide consistent, observable resilience across diverse integrations.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import (
    Any,
    Generic,
    Protocol,
    TypeVar,
    runtime_checkable,
)

import structlog

from .errors import IntegrationError, is_retryable_integration_error

logger = structlog.get_logger(__name__)

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)


# ===================================================================
# Fallback behavior patterns
# ===================================================================


class ResultSource(StrEnum):
    """Source of data in a resilient operation result."""

    PRIMARY = "primary"
    FALLBACK = "fallback"
    DEFAULT = "default"
    NONE = "none"


@runtime_checkable
class FallbackProvider(Protocol[T_co]):
    """Provides cached or default data when the primary provider is unavailable.

    Implementations should retrieve cached/stale data or serve a sensible default
    when the primary provider fails.
    """

    async def get_fallback(
        self,
        *,
        operation: str,
        context: dict[str, Any],
    ) -> T_co | None:
        """Get fallback data for a failed operation.

        Args:
            operation: The operation that failed (e.g. 'list_customers').
            context: Contextual info about the failure (provider, error type, etc).

        Returns:
            Fallback data if available, None if no fallback can be provided.
        """
        ...


@dataclass(frozen=True, slots=True)
class ResilientResult(Generic[T]):
    """Result from a resilient operation that may have used a fallback.

    Tracks whether the result came from the primary provider, a fallback,
    a default, or could not be obtained at all.

    Example::

        result = await with_fallback(
            primary=lambda: client.get_customer(id),
            fallback=cache,
            default=Customer(name="Unknown"),
        )

        if result.available:
            process_customer(result.data)
        elif result.degraded:
            log_fallback_used(result)
        else:
            handle_unavailable()
    """

    data: T | None
    source: ResultSource
    primary_error: IntegrationError | None
    degraded: bool

    @property
    def available(self) -> bool:
        """Return True if data is available from any source."""
        return self.data is not None

    @classmethod
    def from_primary(
        cls,
        data: T,
        *,
        primary_error: IntegrationError | None = None,
    ) -> ResilientResult[T]:
        """Create a result from successful primary operation.

        Args:
            data: The primary result data.
            primary_error: None (primary succeeded).

        Returns:
            ResilientResult with source=PRIMARY and degraded=False.
        """
        return cls(
            data=data,
            source=ResultSource.PRIMARY,
            primary_error=primary_error,
            degraded=False,
        )

    @classmethod
    def from_fallback(
        cls,
        data: T,
        *,
        primary_error: IntegrationError,
    ) -> ResilientResult[T]:
        """Create a result from fallback after primary failed.

        Args:
            data: The fallback data.
            primary_error: The error from the primary operation.

        Returns:
            ResilientResult with source=FALLBACK and degraded=True.
        """
        return cls(
            data=data,
            source=ResultSource.FALLBACK,
            primary_error=primary_error,
            degraded=True,
        )

    @classmethod
    def from_default(
        cls,
        data: T,
        *,
        primary_error: IntegrationError,
    ) -> ResilientResult[T]:
        """Create a result from default value after primary failed.

        Args:
            data: The default value.
            primary_error: The error from the primary operation.

        Returns:
            ResilientResult with source=DEFAULT and degraded=True.
        """
        return cls(
            data=data,
            source=ResultSource.DEFAULT,
            primary_error=primary_error,
            degraded=True,
        )

    @classmethod
    def unavailable(
        cls,
        *,
        primary_error: IntegrationError,
    ) -> ResilientResult[T]:
        """Create a result when data is unavailable from all sources.

        Args:
            primary_error: The error from the primary operation.

        Returns:
            ResilientResult with source=NONE, data=None, and degraded=True.
        """
        return cls(
            data=None,
            source=ResultSource.NONE,
            primary_error=primary_error,
            degraded=True,
        )


async def with_fallback(
    primary: Callable[..., Awaitable[T]],
    *,
    fallback: FallbackProvider[T] | None = None,
    default: T | None = None,
    operation: str = "unknown",
    context: dict[str, Any] | None = None,
) -> ResilientResult[T]:
    """Execute primary call, falling back to cached/default data on retryable errors.

    Attempts to execute the primary operation. If it fails with a retryable error,
    tries the fallback provider. If fallback is unavailable, uses the default value.
    If all sources are exhausted, returns an unavailable result.

    Args:
        primary: Async callable that performs the primary operation.
        fallback: Optional fallback provider for cached/default data.
        default: Optional default value to use if fallback is unavailable.
        operation: Name of the operation for logging (e.g. 'list_customers').
        context: Additional context dict passed to fallback provider.

    Returns:
        ResilientResult with data from primary, fallback, default, or None.

    Example::

        result = await with_fallback(
            primary=lambda: client.get_customer(customer_id),
            fallback=cache_provider,
            default=Customer(name="Unknown"),
            operation="get_customer",
        )

        if result.degraded:
            logger.info("using fallback", source=result.source)

        if result.available:
            return result.data
    """
    ctx = context or {}

    # Attempt primary operation
    try:
        data = await primary()
        logger.debug(
            "primary_operation_succeeded",
            operation=operation,
        )
        return ResilientResult.from_primary(data)
    except IntegrationError as e:
        # Log the error for diagnostics
        logger.warning(
            "primary_operation_failed",
            operation=operation,
            error_type=type(e).__name__,
            retryable=is_retryable_integration_error(e),
        )

        # Only attempt fallback/default if error is retryable
        if not is_retryable_integration_error(e):
            logger.error(
                "primary_error_not_retryable_no_fallback",
                operation=operation,
                error_type=type(e).__name__,
            )
            return ResilientResult.unavailable(primary_error=e)

        # Try fallback provider
        if fallback is not None:
            try:
                fallback_data = await fallback.get_fallback(
                    operation=operation,
                    context=ctx,
                )
                if fallback_data is not None:
                    logger.info(
                        "fallback_provider_used",
                        operation=operation,
                    )
                    return ResilientResult.from_fallback(
                        fallback_data,
                        primary_error=e,
                    )
            except Exception as fb_err:
                logger.warning(
                    "fallback_provider_error",
                    operation=operation,
                    error=str(fb_err),
                )

        # Try default value
        if default is not None:
            logger.info(
                "default_value_used",
                operation=operation,
            )
            return ResilientResult.from_default(default, primary_error=e)

        # No fallback or default available
        logger.error(
            "primary_failed_no_fallback_available",
            operation=operation,
        )
        return ResilientResult.unavailable(primary_error=e)


# ===================================================================
# Partial failure handling patterns
# ===================================================================


@dataclass(frozen=True, slots=True)
class PartialFailurePolicy:
    """Policy controlling how bulk operations handle per-item failures.

    Attributes:
        max_failure_ratio: Abort if failure rate exceeds this (0.0 to 1.0).
        fail_fast_on_auth: Stop immediately on authentication errors.
        fail_fast_on_config: Stop on configuration/validation errors.
        collect_errors: Collect all errors vs stop at first error.
    """

    max_failure_ratio: float = 0.5
    fail_fast_on_auth: bool = True
    fail_fast_on_config: bool = True
    collect_errors: bool = True

    def __post_init__(self) -> None:
        """Validate policy parameters."""
        if not 0.0 <= self.max_failure_ratio <= 1.0:
            raise ValueError(
                f"max_failure_ratio must be 0.0-1.0, got {self.max_failure_ratio}"
            )


class PartialFailureOutcome(StrEnum):
    """Outcome of a bulk operation with partial failure handling."""

    ALL_SUCCEEDED = "all_succeeded"
    PARTIAL_SUCCESS = "partial_success"
    ALL_FAILED = "all_failed"
    ABORTED = "aborted"


@dataclass(frozen=True, slots=True)
class PartialFailureResult(Generic[T]):
    """Aggregated result of a bulk operation with per-item tracking.

    Attributes:
        outcome: Overall outcome of the operation.
        succeeded: List of items that succeeded.
        failed: List of (input_item, error) tuples for failed items.
        aborted_at: Index where abort triggered, or None.
        total: Total number of items processed.
    """

    outcome: PartialFailureOutcome
    succeeded: list[T] = field(default_factory=list)
    failed: list[tuple[Any, IntegrationError]] = field(default_factory=list)
    aborted_at: int | None = None
    total: int = 0

    @property
    def failure_ratio(self) -> float:
        """Return the ratio of failed items (0.0 to 1.0)."""
        if self.total == 0:
            return 0.0
        return len(self.failed) / self.total

    @property
    def retryable_failures(self) -> list[tuple[Any, IntegrationError]]:
        """Return only failures that are retryable."""
        return [
            (item, err)
            for item, err in self.failed
            if is_retryable_integration_error(err)
        ]


async def execute_with_partial_failure(
    items: Sequence[Any],
    operation: Callable[[Any], Awaitable[T]],
    *,
    policy: PartialFailurePolicy | None = None,
    provider_name: str = "unknown",
) -> PartialFailureResult[T]:
    """Execute an operation across items with partial failure handling.

    Processes items sequentially, tracking successes and failures. Respects
    the policy's failure thresholds and abort conditions. Suitable for bulk
    operations where some items may fail but others should still be processed.

    Args:
        items: Sequence of items to process.
        operation: Async callable that processes one item, raising IntegrationError.
        policy: PartialFailurePolicy to control handling. Defaults to standard policy.
        provider_name: Provider name for logging context.

    Returns:
        PartialFailureResult with outcome and per-item tracking.

    Example::

        items = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        result = await execute_with_partial_failure(
            items,
            operation=client.create_customer,
            policy=PartialFailurePolicy(max_failure_ratio=0.3),
        )

        if result.outcome == PartialFailureOutcome.ALL_SUCCEEDED:
            save_all(result.succeeded)
        elif result.outcome == PartialFailureOutcome.PARTIAL_SUCCESS:
            save_succeeded(result.succeeded)
            retry_later(result.retryable_failures)
        elif result.outcome == PartialFailureOutcome.ABORTED:
            log_abort(result.aborted_at)
    """
    pol = policy or PartialFailurePolicy()
    succeeded: list[T] = []
    failed: list[tuple[Any, IntegrationError]] = []
    aborted_at: int | None = None

    for idx, item in enumerate(items):
        try:
            result = await operation(item)
            succeeded.append(result)
        except IntegrationError as err:
            failed.append((item, err))

            # Check fail-fast conditions
            if pol.fail_fast_on_auth and _is_auth_error(err):
                logger.error(
                    "partial_failure_auth_error_aborting",
                    provider=provider_name,
                    item_index=idx,
                )
                aborted_at = idx
                break

            if pol.fail_fast_on_config and _is_config_error(err):
                logger.error(
                    "partial_failure_config_error_aborting",
                    provider=provider_name,
                    item_index=idx,
                )
                aborted_at = idx
                break

            # Check failure ratio
            current_ratio = len(failed) / (idx + 1)
            if current_ratio > pol.max_failure_ratio:
                logger.error(
                    "partial_failure_ratio_exceeded_aborting",
                    provider=provider_name,
                    failure_ratio=current_ratio,
                    max_ratio=pol.max_failure_ratio,
                    item_index=idx,
                )
                aborted_at = idx
                break

            if not pol.collect_errors:
                # Stop at first error if not collecting
                aborted_at = idx
                break

    total = len(items)
    all_succeeded = len(failed) == 0
    all_failed = len(succeeded) == 0

    if aborted_at is not None:
        outcome = PartialFailureOutcome.ABORTED
    elif all_succeeded:
        outcome = PartialFailureOutcome.ALL_SUCCEEDED
    elif all_failed:
        outcome = PartialFailureOutcome.ALL_FAILED
    else:
        outcome = PartialFailureOutcome.PARTIAL_SUCCESS

    logger.info(
        "partial_failure_operation_complete",
        provider=provider_name,
        outcome=outcome.value,
        succeeded_count=len(succeeded),
        failed_count=len(failed),
        total=total,
        aborted_at=aborted_at,
    )

    return PartialFailureResult(
        outcome=outcome,
        succeeded=succeeded,
        failed=failed,
        aborted_at=aborted_at,
        total=total,
    )


def _is_auth_error(error: IntegrationError) -> bool:
    """Check if error is authentication-related."""
    from .errors import IntegrationAuthError, IntegrationCredentialError

    return isinstance(error, IntegrationAuthError | IntegrationCredentialError)


def _is_config_error(error: IntegrationError) -> bool:
    """Check if error is configuration-related."""
    from .errors import (
        IntegrationConfigError,
        IntegrationModeError,
        IntegrationValidationError,
    )

    return isinstance(
        error, IntegrationConfigError | IntegrationValidationError | IntegrationModeError
    )


# ===================================================================
# Compensating action guidance
# ===================================================================


@runtime_checkable
class CompensatingAction(Protocol):
    """Protocol for undo/cleanup logic when a multi-step operation partially fails.

    Implementations should handle idempotency and partial state rollback.
    """

    @property
    def description(self) -> str:
        """Return a human-readable description of the compensating action."""
        ...

    async def execute(self) -> CompensatingActionResult:
        """Execute the compensating action (undo/cleanup).

        Should be idempotent: safe to call multiple times without side effects.

        Returns:
            CompensatingActionResult with success/failure info.
        """
        ...

    async def can_compensate(self) -> bool:
        """Check if this compensating action can be executed.

        Returns:
            True if the action can be executed, False otherwise.
        """
        ...


@dataclass(frozen=True, slots=True)
class CompensatingActionResult:
    """Result of executing a compensating action.

    Attributes:
        success: True if the compensating action succeeded.
        action_description: Description of the action that was attempted.
        detail: Additional detail about the result.
        error: Exception if the compensation failed, None otherwise.
    """

    success: bool
    action_description: str
    detail: str | None = None
    error: Exception | None = None


@dataclass
class CompensationContext:
    """Tracks compensating actions registered during a multi-step flow.

    Maintains a stack of compensating actions and executes them in reverse
    order (LIFO) when compensate_all is called.

    Example::

        async with CompensationContext() as ctx:
            # Step 1: Create resource
            result = await client.create_customer(...)
            ctx.register(DeleteCustomer(result.id))

            # Step 2: Configure billing
            await client.setup_billing(...)
            ctx.register(RemoveBilling())

            # If step 3 fails, compensations run in reverse order
            await client.setup_email(...)  # may raise
    """

    _actions: list[CompensatingAction] = field(default_factory=list)

    def register(self, action: CompensatingAction) -> None:
        """Register a compensating action to be executed on failure.

        Actions are stored in LIFO order for reverse execution.

        Args:
            action: The compensating action to register.
        """
        self._actions.append(action)
        logger.debug(
            "compensating_action_registered",
            action=action.description,
        )

    async def compensate_all(self) -> list[CompensatingActionResult]:
        """Execute all registered compensating actions in reverse order.

        Executes actions from most recent to oldest (LIFO), collecting
        results even if individual actions fail.

        Returns:
            List of CompensatingActionResult for each action executed.
        """
        results: list[CompensatingActionResult] = []

        # Execute in reverse order (LIFO)
        for action in reversed(self._actions):
            try:
                if not await action.can_compensate():
                    logger.info(
                        "compensating_action_skipped_cannot_compensate",
                        action=action.description,
                    )
                    results.append(
                        CompensatingActionResult(
                            success=False,
                            action_description=action.description,
                            detail="action cannot compensate",
                        )
                    )
                    continue

                result = await action.execute()
                results.append(result)

                if result.success:
                    logger.info(
                        "compensating_action_executed",
                        action=action.description,
                    )
                else:
                    logger.error(
                        "compensating_action_failed",
                        action=action.description,
                        detail=result.detail,
                    )
            except Exception as e:
                logger.exception(
                    "compensating_action_error",
                    action=action.description,
                )
                results.append(
                    CompensatingActionResult(
                        success=False,
                        action_description=action.description,
                        detail=f"unexpected error: {str(e)}",
                        error=e,
                    )
                )

        return results

    async def __aenter__(self) -> CompensationContext:
        """Enter async context manager."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Exit async context manager."""
        pass


@dataclass(frozen=True, slots=True)
class CompensationOutcome:
    """Outcome of a step-based workflow with compensation on failure.

    Attributes:
        completed_steps: Number of steps that completed successfully.
        total_steps: Total number of steps in the workflow.
        success: True if all steps succeeded without compensation.
        failure_error: The IntegrationError that triggered compensation.
        compensation_results: Results of each compensating action.
    """

    completed_steps: int
    total_steps: int
    success: bool
    failure_error: IntegrationError | None = None
    compensation_results: list[CompensatingActionResult] = field(
        default_factory=list
    )


async def with_compensation(
    steps: Sequence[Callable[..., Awaitable[Any]]],
    compensations: Sequence[CompensatingAction],
    *,
    provider_name: str = "unknown",
    operation: str = "unknown",
) -> CompensationOutcome:
    """Execute steps with automatic compensation on failure.

    Executes steps sequentially. If any step raises IntegrationError,
    immediately executes compensations in reverse order and returns
    the outcome with compensation results.

    Args:
        steps: Sequence of async callables representing workflow steps.
        compensations: Sequence of compensating actions for each step.
        provider_name: Provider name for logging.
        operation: Operation name for logging.

    Returns:
        CompensationOutcome with step count and compensation results.

    Example::

        outcome = await with_compensation(
            steps=[
                lambda: client.create_order(order_data),
                lambda: client.reserve_inventory(items),
                lambda: client.charge_payment(payment_data),
            ],
            compensations=[
                CancelOrder(order_id),
                ReleaseInventory(item_ids),
                RefundPayment(transaction_id),
            ],
            provider_name="ecommerce",
            operation="place_order",
        )

        if not outcome.success:
            log_order_rollback(outcome.compensation_results)
    """
    if len(steps) != len(compensations):
        raise ValueError(
            f"steps ({len(steps)}) and compensations ({len(compensations)}) "
            f"must have the same length"
        )

    completed = 0
    failure_error: IntegrationError | None = None
    compensation_results: list[CompensatingActionResult] = []

    try:
        for idx, step in enumerate(steps):
            try:
                await step()
                completed += 1
            except IntegrationError as err:
                logger.error(
                    "workflow_step_failed",
                    provider=provider_name,
                    operation=operation,
                    step_index=idx,
                    error_type=type(err).__name__,
                )
                failure_error = err
                break
    except Exception as err:
        logger.exception(
            "unexpected_step_error",
            provider=provider_name,
            operation=operation,
        )
        failure_error = IntegrationError(
            str(err),
            provider_name=provider_name,
            operation=operation,
            cause=err,
        )

    # Execute compensations if any step failed
    if failure_error is not None:
        logger.info(
            "executing_compensating_actions",
            provider=provider_name,
            operation=operation,
            completed_steps=completed,
            total_steps=len(steps),
        )

        # Execute compensations in reverse order
        for idx in range(completed - 1, -1, -1):
            action = compensations[idx]
            try:
                if not await action.can_compensate():
                    logger.warning(
                        "compensation_skipped",
                        action=action.description,
                        step_index=idx,
                    )
                    compensation_results.append(
                        CompensatingActionResult(
                            success=False,
                            action_description=action.description,
                            detail="cannot compensate",
                        )
                    )
                    continue

                result = await action.execute()
                compensation_results.append(result)

                if result.success:
                    logger.info(
                        "compensation_executed",
                        action=action.description,
                        step_index=idx,
                    )
                else:
                    logger.error(
                        "compensation_failed",
                        action=action.description,
                        step_index=idx,
                        detail=result.detail,
                    )
            except Exception as e:
                logger.exception(
                    "compensation_error",
                    action=action.description,
                    step_index=idx,
                )
                compensation_results.append(
                    CompensatingActionResult(
                        success=False,
                        action_description=action.description,
                        detail=f"error: {str(e)}",
                        error=e,
                    )
                )

        # Reverse the results to maintain forward order
        compensation_results.reverse()

    return CompensationOutcome(
        completed_steps=completed,
        total_steps=len(steps),
        success=failure_error is None,
        failure_error=failure_error,
        compensation_results=compensation_results,
    )


# ===================================================================
# Deferred retries for unavailable providers
# ===================================================================


@dataclass(frozen=True, slots=True)
class DeferredRetryRequest:
    """Describes a failed integration call that should be retried later via queue.

    Used to defer failed operations to the job queue when the provider is
    temporarily unavailable but retryable. Integrates with BackoffPolicy
    from core.worker.retry.

    Attributes:
        provider_name: Canonical provider name (e.g., 'stripe').
        operation: Operation name (e.g., 'create_customer').
        payload: Operation payload/arguments as dict.
        error_category: Error classification (from JobFailureCategory or custom).
        attempt: Current attempt number (0-indexed).
        max_attempts: Maximum number of retry attempts.
        backoff_policy: Backoff policy name ('fast', 'standard', 'slow').
        correlation_id: Optional request correlation ID for tracing.
    """

    provider_name: str
    operation: str
    payload: dict[str, Any]
    error_category: str
    attempt: int = 0
    max_attempts: int = 5
    backoff_policy: str = "standard"
    correlation_id: str | None = None

    @property
    def next_attempt(self) -> int:
        """Return the next attempt number."""
        return self.attempt + 1

    @property
    def has_attempts_remaining(self) -> bool:
        """Return True if attempts remain."""
        return self.next_attempt < self.max_attempts


@runtime_checkable
class DeferredRetryEnqueuer(Protocol):
    """Protocol for enqueuing deferred retries to a job queue.

    Implementations should persist the retry request to a durable queue
    (e.g., ARQ, Celery, RabbitMQ) for later processing.
    """

    async def enqueue_retry(self, request: DeferredRetryRequest) -> bool:
        """Enqueue a deferred retry request.

        Args:
            request: The DeferredRetryRequest to enqueue.

        Returns:
            True if enqueued successfully, False otherwise.
        """
        ...


def should_defer_retry(
    error: IntegrationError,
    *,
    current_attempt: int = 0,
    max_attempts: int = 5,
) -> bool:
    """Determine whether a failed integration call should be deferred to queue.

    Defers only retryable errors and only if attempts remain.

    Args:
        error: The IntegrationError from the failed operation.
        current_attempt: Current attempt number (0-indexed).
        max_attempts: Maximum retry attempts allowed.

    Returns:
        True if the operation should be deferred to the job queue.
    """
    # Only defer retryable errors
    if not is_retryable_integration_error(error):
        return False

    # Only defer if attempts remain
    if current_attempt + 1 >= max_attempts:
        return False

    return True


def build_deferred_retry_request(
    *,
    provider_name: str,
    operation: str,
    payload: dict[str, Any],
    error: IntegrationError,
    attempt: int = 0,
    max_attempts: int = 5,
    backoff_policy: str = "standard",
    correlation_id: str | None = None,
) -> DeferredRetryRequest:
    """Build a DeferredRetryRequest from a failed integration call.

    Converts integration error context into a retry request suitable for
    enqueuing to a job queue.

    Args:
        provider_name: Provider name.
        operation: Operation name.
        payload: Operation payload/arguments.
        error: The IntegrationError that occurred.
        attempt: Current attempt number (default 0).
        max_attempts: Maximum attempts (default 5).
        backoff_policy: Backoff policy name (default 'standard').
        correlation_id: Optional correlation ID for tracing.

    Returns:
        DeferredRetryRequest configured from the error and parameters.

    Example::

        try:
            result = await client.create_customer(data)
        except IntegrationError as err:
            if should_defer_retry(err, current_attempt=0):
                req = build_deferred_retry_request(
                    provider_name="stripe",
                    operation="create_customer",
                    payload=data,
                    error=err,
                    correlation_id=request_id,
                )
                await job_queue.enqueue_retry(req)
    """
    # Map IntegrationError types to retry categories
    error_category = _classify_error_for_deferred_retry(error)

    return DeferredRetryRequest(
        provider_name=provider_name,
        operation=operation,
        payload=payload,
        error_category=error_category,
        attempt=attempt,
        max_attempts=max_attempts,
        backoff_policy=backoff_policy,
        correlation_id=correlation_id,
    )


def _classify_error_for_deferred_retry(error: IntegrationError) -> str:
    """Map IntegrationError type to deferred retry category."""
    from .errors import (
        IntegrationConnectionError,
        IntegrationRateLimitError,
        IntegrationServerError,
        IntegrationTimeoutError,
        IntegrationUnavailableError,
    )

    if isinstance(error, IntegrationTimeoutError):
        return "timeout"
    if isinstance(error, IntegrationConnectionError):
        return "connection"
    if isinstance(error, IntegrationServerError):
        return "server_error"
    if isinstance(error, IntegrationRateLimitError):
        return "rate_limited"
    if isinstance(error, IntegrationUnavailableError):
        return "unavailable"
    return "unknown"


__all__ = [
    # Fallback patterns
    "FallbackProvider",
    "ResultSource",
    "ResilientResult",
    "with_fallback",
    # Partial failure patterns
    "PartialFailurePolicy",
    "PartialFailureOutcome",
    "PartialFailureResult",
    "execute_with_partial_failure",
    # Compensating actions
    "CompensatingAction",
    "CompensatingActionResult",
    "CompensationContext",
    "CompensationOutcome",
    "with_compensation",
    # Deferred retries
    "DeferredRetryRequest",
    "DeferredRetryEnqueuer",
    "should_defer_retry",
    "build_deferred_retry_request",
]
