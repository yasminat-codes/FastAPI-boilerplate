"""Shared outbound HTTP client layer for integration adapters.

This module provides a reusable async HTTP client built on httpx with
template-owned defaults for timeouts, connection pooling, correlation
propagation, logging, retry, circuit breaking, and authentication.

Integration adapters should build on ``TemplateHttpClient`` rather than
constructing raw httpx clients, so they inherit the template's production
defaults and observability contract.

Usage
-----
Standalone (simplest)::

    from src.app.integrations.http_client import TemplateHttpClient

    async with TemplateHttpClient(base_url="https://api.example.com") as client:
        response = await client.request("GET", "/users")

With settings::

    from src.app.platform import settings
    client = TemplateHttpClient.from_settings(settings, base_url="https://api.example.com")

Database vs queue state guidance
--------------------------------
The HTTP client is stateless: it does not persist request/response data.
Callers that need durable delivery tracking should combine this client with
the worker retry system and the integration sync checkpoint table.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx
import structlog

from ...core.request_context import build_correlation_headers
from .exceptions import (
    HttpClientError,
    HttpConnectionError,
    HttpRateLimitError,
    HttpResponseSummary,
    HttpTimeoutError,
    classify_status_code,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class HttpClientConfig:
    """Immutable configuration snapshot for a TemplateHttpClient instance.

    This separates configuration from the client object so callers can build
    configs from settings, override individual fields, or compose configs
    across multiple adapters without mutating a shared client.
    """

    base_url: str = ""
    timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 30.0
    write_timeout_seconds: float = 30.0
    pool_max_connections: int = 100
    pool_max_keepalive: int = 20
    default_headers: dict[str, str] = field(default_factory=dict)
    propagate_correlation: bool = True
    follow_redirects: bool = True
    # Retry settings
    retry_enabled: bool = True
    retry_max_attempts: int = 3
    retry_backoff_base_seconds: float = 1.0
    retry_backoff_max_seconds: float = 30.0
    retry_backoff_multiplier: float = 2.0
    retry_backoff_jitter: bool = True
    # Circuit breaker settings
    circuit_breaker_enabled: bool = False
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout_seconds: float = 30.0
    # Logging settings
    log_request_body: bool = False
    log_response_body: bool = False


@runtime_checkable
class RequestHook(Protocol):
    """Protocol for pre-request hooks (logging, auth, instrumentation)."""

    async def before_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        content: bytes | None,
    ) -> dict[str, str]:
        """Called before each outbound request. Returns updated headers."""
        ...


@runtime_checkable
class ResponseHook(Protocol):
    """Protocol for post-response hooks (logging, metrics, instrumentation)."""

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
        """Called after each outbound response (or error)."""
        ...


def _build_response_summary(response: httpx.Response) -> HttpResponseSummary:
    """Build a lightweight response snapshot for error context."""
    return HttpResponseSummary(
        status_code=response.status_code,
        headers=dict(response.headers),
        reason_phrase=response.reason_phrase or "",
        url=str(response.url),
        method=response.request.method if response.request else "",
    )


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Parse the Retry-After header value if present."""
    retry_after = response.headers.get("retry-after")
    if retry_after is None:
        return None
    try:
        return float(retry_after)
    except (ValueError, TypeError):
        return None


def raise_for_status(response: httpx.Response) -> None:
    """Raise a typed HttpClientError for non-2xx responses.

    Maps HTTP status codes to specific exception types so callers and
    the retry layer can make intelligent decisions without inspecting
    raw status codes.
    """
    if response.is_success:
        return

    summary = _build_response_summary(response)
    error_class = classify_status_code(response.status_code)

    if error_class is HttpRateLimitError:
        retry_after = _parse_retry_after(response)
        raise HttpRateLimitError(
            f"Rate limited: {response.status_code}",
            response_summary=summary,
            retry_after_seconds=retry_after,
        )

    raise error_class(
        f"HTTP {response.status_code}: {response.reason_phrase or 'error'}",
        response_summary=summary,
    )


def build_config_from_settings(settings: Any, **overrides: Any) -> HttpClientConfig:
    """Build an HttpClientConfig from the template settings object.

    Reads HTTP_CLIENT_* fields from the settings object and allows
    per-client overrides for any config field.
    """
    defaults = {
        "timeout_seconds": getattr(settings, "HTTP_CLIENT_TIMEOUT_SECONDS", 30.0),
        "connect_timeout_seconds": getattr(settings, "HTTP_CLIENT_CONNECT_TIMEOUT_SECONDS", 10.0),
        "read_timeout_seconds": getattr(settings, "HTTP_CLIENT_READ_TIMEOUT_SECONDS", 30.0),
        "write_timeout_seconds": getattr(settings, "HTTP_CLIENT_WRITE_TIMEOUT_SECONDS", 30.0),
        "pool_max_connections": getattr(settings, "HTTP_CLIENT_POOL_MAX_CONNECTIONS", 100),
        "pool_max_keepalive": getattr(settings, "HTTP_CLIENT_POOL_MAX_KEEPALIVE", 20),
        "retry_enabled": getattr(settings, "HTTP_CLIENT_RETRY_ENABLED", True),
        "retry_max_attempts": getattr(settings, "HTTP_CLIENT_RETRY_MAX_ATTEMPTS", 3),
        "retry_backoff_base_seconds": getattr(settings, "HTTP_CLIENT_RETRY_BACKOFF_BASE_SECONDS", 1.0),
        "retry_backoff_max_seconds": getattr(settings, "HTTP_CLIENT_RETRY_BACKOFF_MAX_SECONDS", 30.0),
        "retry_backoff_multiplier": getattr(settings, "HTTP_CLIENT_RETRY_BACKOFF_MULTIPLIER", 2.0),
        "retry_backoff_jitter": getattr(settings, "HTTP_CLIENT_RETRY_BACKOFF_JITTER", True),
        "circuit_breaker_enabled": getattr(settings, "HTTP_CLIENT_CIRCUIT_BREAKER_ENABLED", False),
        "circuit_breaker_failure_threshold": getattr(
            settings, "HTTP_CLIENT_CIRCUIT_BREAKER_FAILURE_THRESHOLD", 5
        ),
        "circuit_breaker_recovery_timeout_seconds": getattr(
            settings, "HTTP_CLIENT_CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS", 30.0
        ),
        "log_request_body": getattr(settings, "HTTP_CLIENT_LOG_REQUEST_BODY", False),
        "log_response_body": getattr(settings, "HTTP_CLIENT_LOG_RESPONSE_BODY", False),
    }
    defaults.update(overrides)
    return HttpClientConfig(**defaults)  # type: ignore[arg-type]


class TemplateHttpClient:
    """Shared async HTTP client with template-owned production defaults.

    Wraps httpx.AsyncClient with:
    - Configurable timeouts and connection pooling
    - Automatic correlation header propagation
    - Typed exception mapping for all HTTP error responses
    - Pluggable request and response hooks for auth, logging, metrics
    - Optional retry and circuit breaker (via hooks)

    Integration adapters should subclass or compose this client rather
    than constructing httpx clients directly.
    """

    def __init__(
        self,
        config: HttpClientConfig | None = None,
        *,
        base_url: str = "",
        request_hooks: list[RequestHook] | None = None,
        response_hooks: list[ResponseHook] | None = None,
        httpx_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config or HttpClientConfig(base_url=base_url)
        if base_url and not config:
            # Override base_url from convenience parameter
            pass
        elif base_url and config:
            object.__setattr__(self.config, "base_url", base_url)

        self._request_hooks: list[RequestHook] = list(request_hooks or [])
        self._response_hooks: list[ResponseHook] = list(response_hooks or [])
        self._external_client = httpx_client
        self._owned_client: httpx.AsyncClient | None = None

    @classmethod
    def from_settings(
        cls,
        settings: Any,
        *,
        base_url: str = "",
        request_hooks: list[RequestHook] | None = None,
        response_hooks: list[ResponseHook] | None = None,
        **config_overrides: Any,
    ) -> TemplateHttpClient:
        """Create a client from the template settings object."""
        config = build_config_from_settings(settings, base_url=base_url, **config_overrides)
        return cls(config=config, request_hooks=request_hooks, response_hooks=response_hooks)

    def _build_httpx_client(self) -> httpx.AsyncClient:
        """Build the underlying httpx.AsyncClient from config."""
        timeout = httpx.Timeout(
            timeout=self.config.timeout_seconds,
            connect=self.config.connect_timeout_seconds,
            read=self.config.read_timeout_seconds,
            write=self.config.write_timeout_seconds,
        )
        limits = httpx.Limits(
            max_connections=self.config.pool_max_connections,
            max_keepalive_connections=self.config.pool_max_keepalive,
        )
        return httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=timeout,
            limits=limits,
            follow_redirects=self.config.follow_redirects,
            headers=self.config.default_headers,
        )

    @property
    def client(self) -> httpx.AsyncClient:
        """Return the underlying httpx client, creating it lazily if needed."""
        if self._external_client is not None:
            return self._external_client
        if self._owned_client is None:
            self._owned_client = self._build_httpx_client()
        return self._owned_client

    async def close(self) -> None:
        """Close the underlying httpx client if owned by this instance."""
        if self._owned_client is not None:
            await self._owned_client.aclose()
            self._owned_client = None

    async def __aenter__(self) -> TemplateHttpClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: Any = None,
        content: bytes | None = None,
        data: dict[str, Any] | None = None,
        raise_for_status_codes: bool = True,
    ) -> httpx.Response:
        """Send an outbound HTTP request with template-owned defaults.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE).
            url: Relative or absolute URL.
            headers: Additional request headers (merged with defaults).
            params: Query parameters.
            json: JSON-serializable body.
            content: Raw bytes body.
            data: Form-encoded body.
            raise_for_status_codes: Whether to raise typed exceptions for non-2xx responses.

        Returns:
            The httpx.Response object.

        Raises:
            HttpClientError: For non-2xx responses when raise_for_status_codes is True.
            HttpTimeoutError: When the request times out.
            HttpConnectionError: When the connection fails.
        """
        merged_headers = dict(self.config.default_headers)
        if headers:
            merged_headers.update(headers)

        # Propagate correlation context
        if self.config.propagate_correlation:
            correlation_headers = build_correlation_headers()
            for key, value in correlation_headers.items():
                merged_headers.setdefault(key, value)

        # Resolve content for hooks
        request_content = content
        if json is not None:
            # Let httpx handle JSON serialization; hooks see None for content
            request_content = None

        # Run pre-request hooks
        for hook in self._request_hooks:
            merged_headers = await hook.before_request(
                method=method,
                url=url,
                headers=merged_headers,
                content=request_content,
            )

        start_time = time.monotonic()
        error: HttpClientError | None = None
        response: httpx.Response | None = None

        try:
            response = await self.client.request(
                method=method,
                url=url,
                headers=merged_headers,
                params=params,
                json=json,
                content=content,
                data=data,
            )
            if raise_for_status_codes:
                raise_for_status(response)

        except httpx.TimeoutException as exc:
            error = HttpTimeoutError(str(exc))
            raise error from exc
        except httpx.ConnectError as exc:
            error = HttpConnectionError(str(exc))
            raise error from exc
        except httpx.HTTPStatusError as exc:
            summary = _build_response_summary(exc.response)
            error = HttpClientError(str(exc), response_summary=summary)
            raise error from exc
        except HttpClientError:
            raise
        except httpx.HTTPError as exc:
            error = HttpClientError(str(exc))
            raise error from exc
        finally:
            duration = time.monotonic() - start_time
            response_content: bytes | None = None
            status_code = response.status_code if response is not None else 0
            response_headers = dict(response.headers) if response is not None else {}

            if response is not None and self.config.log_response_body:
                try:
                    response_content = response.content
                except Exception:
                    pass

            for response_hook in self._response_hooks:
                try:
                    await response_hook.after_response(
                        method=method,
                        url=url,
                        status_code=status_code,
                        headers=response_headers,
                        duration_seconds=duration,
                        content=response_content,
                        error=error,
                    )
                except Exception:
                    logger.warning(
                        "response_hook_error",
                        hook=type(response_hook).__name__,
                        exc_info=True,
                    )

        return response

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a GET request."""
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a POST request."""
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a PUT request."""
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a PATCH request."""
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a DELETE request."""
        return await self.request("DELETE", url, **kwargs)


__all__ = [
    "HttpClientConfig",
    "RequestHook",
    "ResponseHook",
    "TemplateHttpClient",
    "build_config_from_settings",
    "raise_for_status",
]
