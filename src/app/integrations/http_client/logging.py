"""Request and response logging hooks for the outbound HTTP client.

Provides structured logging with automatic sensitive-field redaction
using the template's shared log-redaction utilities.
"""

from __future__ import annotations

from typing import Any

import structlog

from ...core.log_redaction import redact_log_data
from .exceptions import HttpClientError

logger = structlog.get_logger(__name__)

# Fields commonly found in headers that should be redacted
_HEADER_REDACT_EXACT: set[str] = {
    "authorization",
    "cookie",
    "setcookie",
    "xapikey",
    "apikey",
    "xcsrftoken",
    "xsecret",
}

_HEADER_REDACT_SUBSTRING: tuple[str, ...] = (
    "token",
    "secret",
    "password",
    "credential",
    "auth",
)


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Redact sensitive values from HTTP headers for safe logging."""
    result = redact_log_data(
        headers,
        exact_fields=_HEADER_REDACT_EXACT,
        substring_fields=_HEADER_REDACT_SUBSTRING,
        replacement="[REDACTED]",
    )
    return result if isinstance(result, dict) else {}


class LoggingRequestHook:
    """Request hook that logs outbound HTTP requests with redacted headers.

    Usage::

        hook = LoggingRequestHook()
        client = TemplateHttpClient(request_hooks=[hook])
    """

    def __init__(
        self,
        *,
        log_body: bool = False,
        logger_instance: Any = None,
    ) -> None:
        self._log_body = log_body
        self._logger = logger_instance or logger

    async def before_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        content: bytes | None,
    ) -> dict[str, str]:
        """Log the outbound request details."""
        log_data: dict[str, Any] = {
            "method": method,
            "url": url,
            "headers": _redact_headers(headers),
        }
        if self._log_body and content is not None:
            log_data["body_size"] = len(content)
        self._logger.info("http_client_request", **log_data)
        return headers


class LoggingResponseHook:
    """Response hook that logs outbound HTTP responses with duration and status.

    Usage::

        hook = LoggingResponseHook()
        client = TemplateHttpClient(response_hooks=[hook])
    """

    def __init__(
        self,
        *,
        log_body: bool = False,
        logger_instance: Any = None,
    ) -> None:
        self._log_body = log_body
        self._logger = logger_instance or logger

    async def after_response(
        self,
        *,
        method: str,
        url: str,
        status_code: int,
        headers: dict[str, str],
        duration_seconds: float,
        content: bytes | None,
        error: HttpClientError | None,
    ) -> None:
        """Log the outbound response details."""
        log_data: dict[str, Any] = {
            "method": method,
            "url": url,
            "status_code": status_code,
            "duration_seconds": round(duration_seconds, 4),
        }
        if self._log_body and content is not None:
            log_data["body_size"] = len(content)
        if error is not None:
            log_data["error"] = str(error)
            log_data["error_retryable"] = error.is_retryable
            self._logger.warning("http_client_response_error", **log_data)
        else:
            self._logger.info("http_client_response", **log_data)


__all__ = [
    "LoggingRequestHook",
    "LoggingResponseHook",
]
