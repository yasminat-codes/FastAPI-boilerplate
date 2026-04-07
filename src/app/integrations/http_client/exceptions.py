"""Typed exceptions for the shared outbound HTTP client layer.

This module provides a structured exception hierarchy that maps outbound HTTP
failures into categories compatible with the worker retry system, enabling
intelligent retry decisions for integration adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class HttpResponseSummary:
    """Lightweight snapshot of an HTTP response for error context without holding references to the full response."""

    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    reason_phrase: str = ""
    url: str = ""
    method: str = ""


class HttpClientError(Exception):
    """Base exception for all outbound HTTP client errors."""

    def __init__(
        self,
        message: str,
        *,
        response_summary: HttpResponseSummary | None = None,
        is_retryable: bool = True,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.response_summary = response_summary
        self.is_retryable = is_retryable
        self.error_code = error_code


class HttpTimeoutError(HttpClientError):
    """Outbound request timed out (connect or read)."""

    def __init__(self, message: str = "Request timed out", **kwargs: Any) -> None:
        super().__init__(message, is_retryable=True, **kwargs)


class HttpConnectionError(HttpClientError):
    """Could not establish a connection to the remote host."""

    def __init__(self, message: str = "Connection failed", **kwargs: Any) -> None:
        super().__init__(message, is_retryable=True, **kwargs)


class HttpServerError(HttpClientError):
    """Remote server returned a 5xx status code."""

    def __init__(self, message: str = "Server error", **kwargs: Any) -> None:
        super().__init__(message, is_retryable=True, **kwargs)


class HttpRateLimitError(HttpClientError):
    """Remote server returned 429 Too Many Requests."""

    def __init__(
        self,
        message: str = "Rate limited",
        *,
        retry_after_seconds: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, is_retryable=True, **kwargs)
        self.retry_after_seconds = retry_after_seconds


class HttpAuthenticationError(HttpClientError):
    """Remote server returned 401 Unauthorized."""

    def __init__(self, message: str = "Authentication failed", **kwargs: Any) -> None:
        super().__init__(message, is_retryable=False, **kwargs)


class HttpAuthorizationError(HttpClientError):
    """Remote server returned 403 Forbidden."""

    def __init__(self, message: str = "Authorization denied", **kwargs: Any) -> None:
        super().__init__(message, is_retryable=False, **kwargs)


class HttpNotFoundError(HttpClientError):
    """Remote server returned 404 Not Found."""

    def __init__(self, message: str = "Resource not found", **kwargs: Any) -> None:
        super().__init__(message, is_retryable=False, **kwargs)


class HttpConflictError(HttpClientError):
    """Remote server returned 409 Conflict."""

    def __init__(self, message: str = "Resource conflict", **kwargs: Any) -> None:
        super().__init__(message, is_retryable=False, **kwargs)


class HttpClientBadRequestError(HttpClientError):
    """Remote server returned 400 Bad Request."""

    def __init__(self, message: str = "Bad request", **kwargs: Any) -> None:
        super().__init__(message, is_retryable=False, **kwargs)


class HttpCircuitOpenError(HttpClientError):
    """Request blocked because the circuit breaker is in the open state."""

    def __init__(self, message: str = "Circuit breaker is open", **kwargs: Any) -> None:
        super().__init__(message, is_retryable=True, **kwargs)


class NonRetryableHttpError(HttpClientError):
    """Explicit signal that this HTTP error should not be retried."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, is_retryable=False, **kwargs)


def classify_status_code(status_code: int) -> type[HttpClientError]:
    """Map an HTTP status code to the appropriate exception class.

    Returns the exception class (not an instance) for the given status code.
    """
    if status_code == 400:
        return HttpClientBadRequestError
    if status_code == 401:
        return HttpAuthenticationError
    if status_code == 403:
        return HttpAuthorizationError
    if status_code == 404:
        return HttpNotFoundError
    if status_code == 409:
        return HttpConflictError
    if status_code == 429:
        return HttpRateLimitError
    if 500 <= status_code < 600:
        return HttpServerError
    if 400 <= status_code < 500:
        return NonRetryableHttpError
    return HttpClientError


__all__ = [
    "HttpAuthenticationError",
    "HttpAuthorizationError",
    "HttpCircuitOpenError",
    "HttpClientBadRequestError",
    "HttpClientError",
    "HttpConflictError",
    "HttpConnectionError",
    "HttpNotFoundError",
    "HttpRateLimitError",
    "HttpResponseSummary",
    "HttpServerError",
    "HttpTimeoutError",
    "NonRetryableHttpError",
    "classify_status_code",
]
