"""Standard result models for integration client operations.

This module provides typed result wrappers for integration calls, enabling
consistent handling of success, failure, and partial-success scenarios across
diverse provider adapters.

Result types support:
- Single operation results with success/failure semantics
- Paginated result streams with cursor management
- Bulk operations with per-item success tracking

All results capture provider context, operation metadata, and timing information
for observability and retry coordination.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from .errors import IntegrationError, is_retryable_integration_error

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class IntegrationResult(Generic[T]):
    """Result of a single integration operation.

    Wraps either success data or a failure error with provider context
    and timing information for consistent result handling.

    Example::

        # Success result
        result = IntegrationResult.ok(
            data=customer_data,
            provider="stripe",
            operation="get_customer",
            duration_ms=125.5,
        )

        # Failure result
        result = IntegrationResult.fail(
            error=IntegrationAuthError(...),
            provider="stripe",
            operation="create_payment",
        )

        # Conditional handling
        if result.success:
            process_customer(result.data)
        elif result.is_retryable:
            schedule_retry(result)
        else:
            handle_permanent_failure(result.error)
    """

    success: bool
    data: T | None = None
    error: IntegrationError | None = None
    provider: str = ""
    operation: str = ""
    duration_ms: float | None = None
    request_id: str | None = None

    @classmethod
    def ok(
        cls,
        data: T,
        *,
        provider: str,
        operation: str = "unknown",
        duration_ms: float | None = None,
        request_id: str | None = None,
    ) -> IntegrationResult[T]:
        """Create a successful result.

        Args:
            data: The operation result data.
            provider: Canonical provider name.
            operation: Descriptive operation name.
            duration_ms: Operation duration in milliseconds.
            request_id: Request correlation ID.

        Returns:
            IntegrationResult with success=True and data populated.
        """
        return cls(
            success=True,
            data=data,
            error=None,
            provider=provider,
            operation=operation,
            duration_ms=duration_ms,
            request_id=request_id,
        )

    @classmethod
    def fail(
        cls,
        error: IntegrationError,
        *,
        provider: str | None = None,
        operation: str | None = None,
        duration_ms: float | None = None,
        request_id: str | None = None,
    ) -> IntegrationResult[T]:
        """Create a failed result.

        Args:
            error: The IntegrationError that occurred.
            provider: Canonical provider name (defaults to error.provider_name).
            operation: Descriptive operation name (defaults to error.operation).
            duration_ms: Operation duration in milliseconds.
            request_id: Request correlation ID.

        Returns:
            IntegrationResult with success=False and error populated.
        """
        return cls(
            success=False,
            data=None,
            error=error,
            provider=provider or error.provider_name,
            operation=operation or error.operation,
            duration_ms=duration_ms,
            request_id=request_id,
        )

    @property
    def is_retryable(self) -> bool:
        """Return True if this failed result can be safely retried.

        For successful results, always returns False (no retry needed).
        For failed results, delegates to is_retryable_integration_error.
        """
        if self.success:
            return False
        if self.error is None:
            return False
        return is_retryable_integration_error(self.error)


@dataclass(frozen=True, slots=True)
class PaginatedIntegrationResult(IntegrationResult[T]):
    """Result of a paginated integration operation.

    Extends IntegrationResult with cursor-based pagination support for
    streaming large result sets from providers.

    Example::

        # Fetch first page
        result = await client.list_customers(limit=100)
        process_items(result.data)

        # Fetch next page if available
        while result.has_more and result.cursor:
            result = await client.list_customers(limit=100, cursor=result.cursor)
            process_items(result.data)
    """

    cursor: str | None = None
    has_more: bool = False
    total_count: int | None = None

    @classmethod
    def ok(
        cls,
        data: T,
        *,
        provider: str,
        operation: str = "unknown",
        duration_ms: float | None = None,
        request_id: str | None = None,
        cursor: str | None = None,
        has_more: bool = False,
        total_count: int | None = None,
    ) -> PaginatedIntegrationResult[T]:
        """Create a successful paginated result.

        Args:
            data: The operation result data (typically a list).
            provider: Canonical provider name.
            operation: Descriptive operation name.
            duration_ms: Operation duration in milliseconds.
            request_id: Request correlation ID.
            cursor: Pagination cursor for the next page.
            has_more: Whether more results are available.
            total_count: Total count of items (if known).

        Returns:
            PaginatedIntegrationResult with pagination metadata.
        """
        return cls(
            success=True,
            data=data,
            error=None,
            provider=provider,
            operation=operation,
            duration_ms=duration_ms,
            request_id=request_id,
            cursor=cursor,
            has_more=has_more,
            total_count=total_count,
        )


@dataclass(frozen=True, slots=True)
class BulkIntegrationResult(Generic[T]):
    """Result of a bulk integration operation.

    Tracks per-item success and failures for batch operations, enabling
    partial success handling and targeted retry logic.

    Example::

        # Batch create customers
        result = await client.bulk_create_customers(customers)

        # Process successful items
        for item in result.succeeded:
            save_customer(item)

        # Retry failed items
        for item_result in result.failed:
            if item_result.is_retryable:
                schedule_retry(item_result)
            else:
                log_permanent_failure(item_result)
    """

    succeeded: list[T] = field(default_factory=list)
    failed: list[IntegrationResult[T]] = field(default_factory=list)
    total: int = 0

    @property
    def success_count(self) -> int:
        """Return the number of successful items."""
        return len(self.succeeded)

    @property
    def failure_count(self) -> int:
        """Return the number of failed items."""
        return len(self.failed)

    @property
    def partial_success(self) -> bool:
        """Return True if at least one item succeeded and one failed."""
        return self.success_count > 0 and self.failure_count > 0


__all__ = [
    "BulkIntegrationResult",
    "IntegrationResult",
    "PaginatedIntegrationResult",
]
