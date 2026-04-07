"""Normalized error taxonomy for integration client failures.

This module provides high-level integration errors that wrap HTTP-level errors
from ``TemplateHttpClient``, enabling consistent error handling and retry logic
across diverse provider adapters.

The error hierarchy maps HTTP status codes and connection failures to semantic
integration errors, allowing callers to make intelligent decisions about
retries, fallbacks, and user-facing error messages without inspecting raw
HTTP status codes.
"""

from __future__ import annotations

from ..http_client.exceptions import (
    HttpAuthenticationError,
    HttpAuthorizationError,
    HttpCircuitOpenError,
    HttpClientBadRequestError,
    HttpClientError,
    HttpConnectionError,
    HttpNotFoundError,
    HttpRateLimitError,
    HttpServerError,
    HttpTimeoutError,
)


class IntegrationError(Exception):
    """Base exception for all integration client errors.

    Wraps provider-specific and HTTP-level errors with semantic context
    (provider name, operation, detail) for structured logging and error handling.
    """

    def __init__(
        self,
        message: str,
        *,
        provider_name: str,
        operation: str = "unknown",
        detail: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        """Initialize an IntegrationError.

        Args:
            message: Human-readable error message.
            provider_name: Canonical provider name (e.g., 'stripe').
            operation: Descriptive operation name (e.g., 'create_customer').
            detail: Additional error detail or provider-returned message.
            cause: Underlying exception that triggered this error.
        """
        super().__init__(message)
        self.message = message
        self.provider_name = provider_name
        self.operation = operation
        self.detail = detail
        self.cause = cause


class IntegrationAuthError(IntegrationError):
    """Provider authentication failed (401 Unauthorized)."""

    pass


class IntegrationNotFoundError(IntegrationError):
    """Requested resource does not exist at provider (404 Not Found)."""

    pass


class IntegrationRateLimitError(IntegrationError):
    """Provider rate limit exceeded (429 Too Many Requests)."""

    def __init__(
        self,
        message: str,
        *,
        provider_name: str,
        operation: str = "unknown",
        detail: str | None = None,
        cause: Exception | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        """Initialize a rate limit error with optional retry guidance.

        Args:
            message: Human-readable error message.
            provider_name: Canonical provider name.
            operation: Descriptive operation name.
            detail: Additional error detail.
            cause: Underlying exception.
            retry_after_seconds: Seconds to wait before retrying (from provider).
        """
        super().__init__(
            message,
            provider_name=provider_name,
            operation=operation,
            detail=detail,
            cause=cause,
        )
        self.retry_after_seconds = retry_after_seconds


class IntegrationTimeoutError(IntegrationError):
    """Provider request timed out (connection or read timeout)."""

    pass


class IntegrationConnectionError(IntegrationError):
    """Cannot reach the provider (network, DNS, or connection failure)."""

    pass


class IntegrationValidationError(IntegrationError):
    """Provider rejected the request due to invalid data (400 Bad Request)."""

    pass


class IntegrationServerError(IntegrationError):
    """Provider returned a server-side error (5xx)."""

    pass


class IntegrationConfigError(IntegrationError):
    """Integration is misconfigured (bad credentials, invalid mode, etc.)."""

    pass


class IntegrationUnavailableError(IntegrationError):
    """Provider is known to be unavailable (circuit breaker open)."""

    pass


class IntegrationDisabledError(IntegrationError):
    """Integration is explicitly disabled in settings."""

    pass


class IntegrationModeError(IntegrationError):
    """Integration mode is invalid or unsupported for the requested operation."""

    pass


class IntegrationCredentialError(IntegrationError):
    """Credentials are missing, invalid, or insufficient for the integration."""

    pass


class IntegrationProductionValidationError(IntegrationError):
    """Production mode validation failed (missing credentials, sandbox URL, etc.)."""

    pass


def classify_http_error(
    provider_name: str,
    operation: str,
    error: HttpClientError,
) -> IntegrationError:
    """Map an HttpClientError to the appropriate IntegrationError.

    This function bridges the HTTP-level error taxonomy to the higher-level
    integration error taxonomy, preserving retry information and provider context.

    Args:
        provider_name: Canonical provider name.
        operation: Descriptive operation name.
        error: HttpClientError to classify.

    Returns:
        An IntegrationError subclass instance.
    """
    detail = error.message if hasattr(error, "message") else str(error)

    if isinstance(error, HttpAuthenticationError):
        return IntegrationAuthError(
            str(error),
            provider_name=provider_name,
            operation=operation,
            detail=detail,
            cause=error,
        )

    if isinstance(error, HttpAuthorizationError):
        return IntegrationAuthError(
            str(error),
            provider_name=provider_name,
            operation=operation,
            detail=detail,
            cause=error,
        )

    if isinstance(error, HttpNotFoundError):
        return IntegrationNotFoundError(
            str(error),
            provider_name=provider_name,
            operation=operation,
            detail=detail,
            cause=error,
        )

    if isinstance(error, HttpRateLimitError):
        retry_after = getattr(error, "retry_after_seconds", None)
        return IntegrationRateLimitError(
            str(error),
            provider_name=provider_name,
            operation=operation,
            detail=detail,
            cause=error,
            retry_after_seconds=retry_after,
        )

    if isinstance(error, HttpTimeoutError):
        return IntegrationTimeoutError(
            str(error),
            provider_name=provider_name,
            operation=operation,
            detail=detail,
            cause=error,
        )

    if isinstance(error, HttpConnectionError):
        return IntegrationConnectionError(
            str(error),
            provider_name=provider_name,
            operation=operation,
            detail=detail,
            cause=error,
        )

    if isinstance(error, HttpClientBadRequestError):
        return IntegrationValidationError(
            str(error),
            provider_name=provider_name,
            operation=operation,
            detail=detail,
            cause=error,
        )

    if isinstance(error, HttpServerError):
        return IntegrationServerError(
            str(error),
            provider_name=provider_name,
            operation=operation,
            detail=detail,
            cause=error,
        )

    if isinstance(error, HttpCircuitOpenError):
        return IntegrationUnavailableError(
            str(error),
            provider_name=provider_name,
            operation=operation,
            detail=detail,
            cause=error,
        )

    # Fallback for unmapped HTTP errors
    return IntegrationError(
        str(error),
        provider_name=provider_name,
        operation=operation,
        detail=detail,
        cause=error,
    )


def is_retryable_integration_error(error: IntegrationError) -> bool:
    """Determine if an IntegrationError should be retried.

    Errors from transient failures (connection, timeout, server error, rate limit)
    are retryable. Errors from permanent failures (auth, not found, validation)
    are not retryable.

    Args:
        error: IntegrationError to evaluate.

    Returns:
        True if the error is retryable, False otherwise.
    """
    non_retryable_types = (
        IntegrationAuthError,
        IntegrationNotFoundError,
        IntegrationValidationError,
        IntegrationConfigError,
    )

    if isinstance(error, non_retryable_types):
        return False

    # All other errors are retryable: timeout, connection, rate limit, server error
    return True


__all__ = [
    "IntegrationAuthError",
    "IntegrationConfigError",
    "IntegrationConnectionError",
    "IntegrationCredentialError",
    "IntegrationDisabledError",
    "IntegrationError",
    "IntegrationModeError",
    "IntegrationNotFoundError",
    "IntegrationProductionValidationError",
    "IntegrationRateLimitError",
    "IntegrationServerError",
    "IntegrationTimeoutError",
    "IntegrationUnavailableError",
    "IntegrationValidationError",
    "classify_http_error",
    "is_retryable_integration_error",
]
