"""Base classes and protocols for integration clients.

This module defines the standard interface that all integration adapters must
follow, enabling consistent health checks, lifecycle management, and request
context propagation across diverse provider integrations.

Integration adapters should subclass ``BaseIntegrationClient`` or implement
the ``IntegrationClient`` protocol to provide provider-specific logic while
inheriting template-owned defaults for HTTP transport, observability, and
error handling.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import structlog

from ..http_client import TemplateHttpClient
from .settings import IntegrationMode

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IntegrationHealthStatus:
    """Health status snapshot for an integration provider.

    Captures the current health of a provider connection with timing
    and diagnostic information for observability and circuit-breaker logic.
    """

    healthy: bool
    provider: str
    latency_ms: float | None = None
    detail: str | None = None
    checked_at: datetime = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        """Ensure checked_at is populated with current time if not provided."""
        if self.checked_at is None:
            object.__setattr__(self, "checked_at", datetime.utcnow())


@runtime_checkable
class IntegrationClient(Protocol):
    """Standard interface for integration adapters.

    All integration clients must follow this protocol to ensure consistent
    health checks, lifecycle management, and error handling across adapters.
    """

    @property
    def provider_name(self) -> str:
        """Return the canonical provider name (e.g., 'stripe', 'hubspot', 'github')."""
        ...

    async def health_check(self) -> IntegrationHealthStatus:
        """Check the health of the provider connection.

        Returns:
            IntegrationHealthStatus with the current health snapshot.
        """
        ...

    async def close(self) -> None:
        """Clean up resources and close the integration client.

        Called when the client is no longer needed or when the context manager exits.
        """
        ...

    async def __aenter__(self) -> IntegrationClient:
        """Enter async context manager."""
        ...

    async def __aexit__(self, *args: Any) -> None:
        """Exit async context manager."""
        ...


class BaseIntegrationClient:
    """Abstract base class for integration adapters.

    Provides common patterns for provider integrations:
    - HTTP client composition (TemplateHttpClient)
    - Provider name and mode management
    - Default health check implementation
    - Lifecycle management (context manager support)
    - Structured logging helpers

    Subclasses should override provider-specific methods and health check logic.

    Example::

        class StripeClient(BaseIntegrationClient):
            provider_name = "stripe"

            async def health_check(self) -> IntegrationHealthStatus:
                # Call parent to get default health status
                status = await super().health_check()
                if not status.healthy:
                    return status

                # Custom provider-specific health logic
                try:
                    await self._request(
                        "GET",
                        "/v1/balance",
                        operation="health_check",
                    )
                    return status
                except Exception as e:
                    return IntegrationHealthStatus(
                        healthy=False,
                        provider=self.provider_name,
                        detail=str(e),
                    )
    """

    def __init__(
        self,
        http_client: TemplateHttpClient,
        *,
        provider_name: str,
        mode: IntegrationMode = IntegrationMode.PRODUCTION,
        health_check_url: str = "",
    ) -> None:
        """Initialize the base integration client.

        Args:
            http_client: Shared TemplateHttpClient instance for HTTP transport.
            provider_name: Canonical provider name (e.g., 'stripe').
            mode: Operating mode (sandbox, production, dry_run).
            health_check_url: URL path for default health check (e.g., '/v1/health').
        """
        self._http_client = http_client
        self._provider_name = provider_name
        self._mode = mode
        self._health_check_url = health_check_url

    @property
    def provider_name(self) -> str:
        """Return the canonical provider name."""
        return self._provider_name

    @property
    def mode(self) -> IntegrationMode:
        """Return the operating mode."""
        return self._mode

    @property
    def http_client(self) -> TemplateHttpClient:
        """Return the underlying TemplateHttpClient for advanced usage."""
        return self._http_client

    async def _request(
        self,
        method: str,
        url: str,
        *,
        operation: str = "request",
        **kwargs: Any,
    ) -> Any:
        """Send an HTTP request with provider-scoped structured logging.

        Wraps TemplateHttpClient.request with provider context so logs include
        provider_name and operation fields automatically.

        Args:
            method: HTTP method (GET, POST, etc.).
            url: Relative or absolute URL.
            operation: Descriptive operation name for logs (e.g., 'get_customer').
            **kwargs: Additional arguments passed to TemplateHttpClient.request.

        Returns:
            httpx.Response object.

        Raises:
            HttpClientError: For non-2xx responses.
        """
        logger.debug(
            "integration_request_start",
            provider=self._provider_name,
            operation=operation,
            method=method,
            url=url,
        )
        try:
            response = await self._http_client.request(method, url, **kwargs)
            logger.debug(
                "integration_request_complete",
                provider=self._provider_name,
                operation=operation,
                status_code=response.status_code,
            )
            return response
        except Exception:
            logger.warning(
                "integration_request_error",
                provider=self._provider_name,
                operation=operation,
                exc_info=True,
            )
            raise

    async def health_check(self) -> IntegrationHealthStatus:
        """Check the health of the provider connection.

        Default implementation pings a configurable health URL. Subclasses can
        override this to implement provider-specific health logic.

        Returns:
            IntegrationHealthStatus with health snapshot.
        """
        start_time = time.monotonic()
        try:
            if not self._health_check_url:
                # No health check configured, assume healthy
                return IntegrationHealthStatus(
                    healthy=True,
                    provider=self._provider_name,
                    latency_ms=None,
                    detail="No health check configured",
                )

            response = await self._request(
                "GET",
                self._health_check_url,
                operation="health_check",
                raise_for_status_codes=False,
            )
            duration_ms = (time.monotonic() - start_time) * 1000
            healthy = response.is_success

            return IntegrationHealthStatus(
                healthy=healthy,
                provider=self._provider_name,
                latency_ms=duration_ms,
                detail=f"HTTP {response.status_code}" if not healthy else None,
            )

        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.warning(
                "health_check_error",
                provider=self._provider_name,
                exc_info=True,
            )
            return IntegrationHealthStatus(
                healthy=False,
                provider=self._provider_name,
                latency_ms=duration_ms,
                detail=str(e),
            )

    async def close(self) -> None:
        """Close the integration client and underlying HTTP client."""
        await self._http_client.close()

    async def __aenter__(self) -> BaseIntegrationClient:
        """Enter async context manager."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Exit async context manager and clean up resources."""
        await self.close()


__all__ = [
    "BaseIntegrationClient",
    "IntegrationClient",
    "IntegrationHealthStatus",
]
