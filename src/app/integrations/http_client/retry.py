"""Retry and backoff behavior for outbound HTTP requests.

This module provides a retry-aware request hook and a standalone retry
wrapper that integration adapters can use to add intelligent retry
behavior to outbound calls.

The retry logic reuses the template's existing ``BackoffPolicy`` from
the worker retry system for consistency, and classifies HTTP responses
using the same failure taxonomy.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import structlog

from .exceptions import (
    HttpClientError,
    HttpConnectionError,
    HttpRateLimitError,
    HttpServerError,
    HttpTimeoutError,
)

logger = structlog.get_logger(__name__)


# Safe HTTP methods that can be retried without side effects
IDEMPOTENT_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


@dataclass(frozen=True, slots=True)
class HttpRetryPolicy:
    """Configuration for outbound HTTP request retry behavior.

    Attributes:
        max_attempts: Maximum total attempts (including the first try).
        backoff_base_seconds: Starting delay between retries.
        backoff_max_seconds: Maximum delay cap.
        backoff_multiplier: Exponential growth factor.
        jitter: Whether to apply full jitter to calculated delays.
        retry_on_timeout: Whether to retry on timeout errors.
        retry_on_connection_error: Whether to retry on connection errors.
        retry_on_server_error: Whether to retry on 5xx errors.
        retry_on_rate_limit: Whether to retry on 429 errors.
        idempotent_methods_only: Only retry idempotent HTTP methods.
    """

    max_attempts: int = 3
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 30.0
    backoff_multiplier: float = 2.0
    jitter: bool = True
    retry_on_timeout: bool = True
    retry_on_connection_error: bool = True
    retry_on_server_error: bool = True
    retry_on_rate_limit: bool = True
    idempotent_methods_only: bool = True

    def delay_for_attempt(self, attempt: int) -> float:
        """Calculate delay for a given retry attempt (0-indexed)."""
        exponential_delay = self.backoff_base_seconds * (self.backoff_multiplier ** attempt)
        capped_delay = min(exponential_delay, self.backoff_max_seconds)
        if self.jitter:
            return random.uniform(0, capped_delay)
        return capped_delay


def build_retry_policy_from_settings(settings: Any) -> HttpRetryPolicy:
    """Build an HttpRetryPolicy from the template settings object."""
    return HttpRetryPolicy(
        max_attempts=getattr(settings, "HTTP_CLIENT_RETRY_MAX_ATTEMPTS", 3),
        backoff_base_seconds=getattr(settings, "HTTP_CLIENT_RETRY_BACKOFF_BASE_SECONDS", 1.0),
        backoff_max_seconds=getattr(settings, "HTTP_CLIENT_RETRY_BACKOFF_MAX_SECONDS", 30.0),
        backoff_multiplier=getattr(settings, "HTTP_CLIENT_RETRY_BACKOFF_MULTIPLIER", 2.0),
        jitter=getattr(settings, "HTTP_CLIENT_RETRY_BACKOFF_JITTER", True),
    )


def is_retryable_error(error: HttpClientError, *, policy: HttpRetryPolicy) -> bool:
    """Determine whether an HTTP error should be retried based on the policy."""
    if not error.is_retryable:
        return False
    if isinstance(error, HttpTimeoutError) and policy.retry_on_timeout:
        return True
    if isinstance(error, HttpConnectionError) and policy.retry_on_connection_error:
        return True
    if isinstance(error, HttpServerError) and policy.retry_on_server_error:
        return True
    if isinstance(error, HttpRateLimitError) and policy.retry_on_rate_limit:
        return True
    return False


def should_retry_method(method: str, *, policy: HttpRetryPolicy) -> bool:
    """Check whether the HTTP method is eligible for retry."""
    if not policy.idempotent_methods_only:
        return True
    return method.upper() in IDEMPOTENT_METHODS


def resolve_retry_delay(
    error: HttpClientError,
    attempt: int,
    policy: HttpRetryPolicy,
) -> float:
    """Resolve the retry delay, respecting Retry-After headers for rate limits."""
    if isinstance(error, HttpRateLimitError) and error.retry_after_seconds is not None:
        return min(error.retry_after_seconds, policy.backoff_max_seconds)
    return policy.delay_for_attempt(attempt)


__all__ = [
    "HttpRetryPolicy",
    "IDEMPOTENT_METHODS",
    "build_retry_policy_from_settings",
    "is_retryable_error",
    "resolve_retry_delay",
    "should_retry_method",
]
