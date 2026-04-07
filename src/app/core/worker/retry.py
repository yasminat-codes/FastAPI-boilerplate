"""Retry, backoff, and error classification primitives for ARQ worker system.

This module provides:
- Exponential backoff strategies with jitter support
- BackoffPolicy configuration and delay calculation
- Error categorization for intelligent retry decisions
- Non-retryable error signaling
- Job failure alerting hooks
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import structlog

__all__ = [
    "calculate_backoff_delay",
    "calculate_backoff_delay_deterministic",
    "BackoffPolicy",
    "BACKOFF_FAST",
    "BACKOFF_STANDARD",
    "BACKOFF_SLOW",
    "NonRetryableJobError",
    "JobFailureCategory",
    "NON_RETRYABLE_CATEGORIES",
    "is_retryable_category",
    "JobAlertHook",
    "LoggingAlertHook",
]


def calculate_backoff_delay(
    base_delay: float, attempt: int, max_delay: float
) -> float:
    """Calculate exponential backoff delay with full jitter.

    Args:
        base_delay: Base delay in seconds (>= 0).
        attempt: Current attempt number (0-indexed).
        max_delay: Maximum delay cap in seconds (>= base_delay).

    Returns:
        Delay in seconds, randomly sampled between 0 and the calculated
        exponential delay, capped at max_delay.

    Raises:
        ValueError: If base_delay < 0, max_delay < base_delay, or attempt < 0.
    """
    if base_delay < 0:
        raise ValueError(f"base_delay must be >= 0, got {base_delay}")
    if max_delay < base_delay:
        raise ValueError(
            f"max_delay ({max_delay}) must be >= base_delay ({base_delay})"
        )
    if attempt < 0:
        raise ValueError(f"attempt must be >= 0, got {attempt}")

    # Calculate exponential delay: base * multiplier^attempt
    exponential_delay = base_delay * (2 ** attempt)
    capped_delay = min(exponential_delay, max_delay)

    # Full jitter: random between 0 and capped_delay
    return random.uniform(0, capped_delay)


def calculate_backoff_delay_deterministic(
    base_delay: float, attempt: int, max_delay: float
) -> float:
    """Calculate exponential backoff delay without jitter (deterministic).

    Useful for testing and scenarios where predictable timing is required.

    Args:
        base_delay: Base delay in seconds (>= 0).
        attempt: Current attempt number (0-indexed).
        max_delay: Maximum delay cap in seconds (>= base_delay).

    Returns:
        Delay in seconds, following exponential growth, capped at max_delay.

    Raises:
        ValueError: If base_delay < 0, max_delay < base_delay, or attempt < 0.
    """
    if base_delay < 0:
        raise ValueError(f"base_delay must be >= 0, got {base_delay}")
    if max_delay < base_delay:
        raise ValueError(
            f"max_delay ({max_delay}) must be >= base_delay ({base_delay})"
        )
    if attempt < 0:
        raise ValueError(f"attempt must be >= 0, got {attempt}")

    # Calculate exponential delay: base * multiplier^attempt
    exponential_delay = base_delay * (2 ** attempt)
    return float(min(exponential_delay, max_delay))


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    """Configuration for exponential backoff retry delays.

    Attributes:
        base_delay_seconds: Starting delay in seconds (>= 0).
        max_delay_seconds: Maximum delay cap in seconds (>= base_delay_seconds).
        multiplier: Exponential growth factor (> 0).
        jitter: Whether to apply full jitter to calculated delays.
    """

    base_delay_seconds: float = 5.0
    max_delay_seconds: float = 300.0
    multiplier: float = 2.0
    jitter: bool = True

    def __post_init__(self) -> None:
        """Validate policy parameters after initialization."""
        if self.base_delay_seconds < 0:
            raise ValueError(
                f"base_delay_seconds must be >= 0, got {self.base_delay_seconds}"
            )
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError(
                f"max_delay_seconds ({self.max_delay_seconds}) must be >= "
                f"base_delay_seconds ({self.base_delay_seconds})"
            )
        if self.multiplier <= 0:
            raise ValueError(
                f"multiplier must be > 0, got {self.multiplier}"
            )

    def delay_for_attempt(self, attempt: int) -> float:
        """Calculate delay for a given attempt number.

        Args:
            attempt: Current attempt number (0-indexed).

        Returns:
            Delay in seconds.
        """
        if self.jitter:
            # Use exponential growth with multiplier and full jitter
            exponential_delay = self.base_delay_seconds * (
                self.multiplier ** attempt
            )
            capped_delay = min(exponential_delay, self.max_delay_seconds)
            return random.uniform(0, capped_delay)
        else:
            # Deterministic exponential growth
            exponential_delay = self.base_delay_seconds * (
                self.multiplier ** attempt
            )
            return min(exponential_delay, self.max_delay_seconds)


# Predefined backoff policies
BACKOFF_FAST = BackoffPolicy(
    base_delay_seconds=1.0,
    max_delay_seconds=30.0,
    multiplier=2.0,
    jitter=True,
)
"""Quick retries for transient network blips and momentary unavailability."""

BACKOFF_STANDARD = BackoffPolicy(
    base_delay_seconds=5.0,
    max_delay_seconds=300.0,
    multiplier=2.0,
    jitter=True,
)
"""General-purpose backoff policy for most job types."""

BACKOFF_SLOW = BackoffPolicy(
    base_delay_seconds=30.0,
    max_delay_seconds=1800.0,
    multiplier=2.0,
    jitter=True,
)
"""Conservative retries for rate-limited or heavy external API interactions."""


class JobFailureCategory(StrEnum):
    """Categories for job failure classification and retry decisions.

    Attributes:
        TRANSIENT: Network timeouts, temporary unavailability (retryable).
        RATE_LIMITED: Provider rate limit hit (retryable).
        INVALID_PAYLOAD: Bad input, will never succeed (not retryable).
        AUTHENTICATION: Credential or auth failure (not retryable).
        AUTHORIZATION: Permission denied (not retryable).
        NOT_FOUND: Target resource doesn't exist (not retryable).
        CONFLICT: State conflict (not retryable).
        PROVIDER_ERROR: Upstream provider error (retryable).
        INTERNAL: Unexpected internal error (retryable).
        UNKNOWN: Unclassified failure (retryable).
    """

    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    INVALID_PAYLOAD = "invalid_payload"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PROVIDER_ERROR = "provider_error"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


# Categories that should never be retried
NON_RETRYABLE_CATEGORIES: frozenset[str] = frozenset([
    JobFailureCategory.INVALID_PAYLOAD,
    JobFailureCategory.AUTHENTICATION,
    JobFailureCategory.AUTHORIZATION,
    JobFailureCategory.NOT_FOUND,
    JobFailureCategory.CONFLICT,
])
"""Error categories that should fail immediately without retry."""


def is_retryable_category(category: str) -> bool:
    """Check whether a failure category is retryable.

    Args:
        category: The failure category to check.

    Returns:
        True if the category is retryable, False otherwise.
    """
    return category not in NON_RETRYABLE_CATEGORIES


class NonRetryableJobError(Exception):
    """Exception signaling that a job should not be retried.

    Raised within a job to indicate immediate failure without retry.
    ARQ job handlers should catch this and mark the job as permanently failed.

    Attributes:
        message: Human-readable error message.
        error_category: JobFailureCategory or custom category string.
        error_code: Optional error code for programmatic handling.
    """

    def __init__(
        self,
        message: str,
        error_category: str | None = None,
        error_code: str | None = None,
    ) -> None:
        """Initialize NonRetryableJobError.

        Args:
            message: Human-readable error message.
            error_category: Category from JobFailureCategory or custom string.
            error_code: Optional error code for programmatic handling.
        """
        super().__init__(message)
        self.message = message
        self.error_category = error_category or JobFailureCategory.UNKNOWN
        self.error_code = error_code


@runtime_checkable
class JobAlertHook(Protocol):
    """Protocol for job failure alerting hooks.

    Implementations receive notifications when a job fails, allowing
    custom alerting, metrics collection, or remediation workflows.
    """

    async def on_job_failure(
        self,
        *,
        job_name: str,
        envelope_data: dict[str, Any],
        attempt: int,
        max_attempts: int,
        error_category: str | None,
        error_message: str,
        is_final_attempt: bool,
    ) -> None:
        """Handle job failure notification.

        Args:
            job_name: Name of the failed job.
            envelope_data: Job input data dictionary.
            attempt: Current attempt number (1-indexed).
            max_attempts: Maximum retry attempts configured.
            error_category: JobFailureCategory or custom category string.
            error_message: Human-readable error message.
            is_final_attempt: True if this is the last retry attempt.
        """
        ...


class LoggingAlertHook:
    """Production alerting hook using structlog for failure logging.

    Logs job failures with full context for monitoring and debugging.
    """

    def __init__(self, logger: structlog.BoundLogger | None = None) -> None:
        """Initialize logging alert hook.

        Args:
            logger: Optional structlog BoundLogger instance. If not provided,
                   uses structlog.get_logger().
        """
        self.logger = logger or structlog.get_logger()

    async def on_job_failure(
        self,
        *,
        job_name: str,
        envelope_data: dict[str, Any],
        attempt: int,
        max_attempts: int,
        error_category: str | None,
        error_message: str,
        is_final_attempt: bool,
    ) -> None:
        """Log job failure with structured context.

        Args:
            job_name: Name of the failed job.
            envelope_data: Job input data dictionary.
            attempt: Current attempt number (1-indexed).
            max_attempts: Maximum retry attempts configured.
            error_category: JobFailureCategory or custom category string.
            error_message: Human-readable error message.
            is_final_attempt: True if this is the last retry attempt.
        """
        log_method = self.logger.error if is_final_attempt else self.logger.warning

        log_method(
            "job_failure",
            job_name=job_name,
            attempt=attempt,
            max_attempts=max_attempts,
            error_category=error_category,
            error_message=error_message,
            is_final_attempt=is_final_attempt,
            envelope_data=envelope_data,
        )
