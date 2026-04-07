"""Instrumentation hooks for tracing and metrics on outbound HTTP requests.

Provides protocol-based extension points so template adopters can plug in
their own metrics and tracing implementations (Prometheus, OpenTelemetry,
Datadog, etc.) without modifying the HTTP client core.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import structlog

from .exceptions import HttpClientError

logger = structlog.get_logger(__name__)


@runtime_checkable
class MetricsCollector(Protocol):
    """Protocol for collecting outbound HTTP metrics.

    Implementations can push to Prometheus, StatsD, CloudWatch, etc.
    """

    async def record_request(
        self,
        *,
        method: str,
        url: str,
        status_code: int,
        duration_seconds: float,
        error: str | None,
        is_retry: bool,
    ) -> None:
        """Record metrics for an outbound HTTP request."""
        ...


@runtime_checkable
class TracingHook(Protocol):
    """Protocol for distributed trace propagation on outbound HTTP requests.

    Implementations can inject trace headers (W3C Trace Context,
    B3, X-Ray, etc.) into outbound requests and record spans.
    """

    async def inject_trace_headers(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
    ) -> dict[str, str]:
        """Inject trace context headers into outbound request headers."""
        ...

    async def record_span(
        self,
        *,
        method: str,
        url: str,
        status_code: int,
        duration_seconds: float,
        error: str | None,
    ) -> None:
        """Record a trace span for the outbound request."""
        ...


class InstrumentationRequestHook:
    """Request hook that injects trace headers via a TracingHook.

    Usage::

        tracing = MyOpenTelemetryHook()
        hook = InstrumentationRequestHook(tracing_hook=tracing)
        client = TemplateHttpClient(request_hooks=[hook])
    """

    def __init__(self, *, tracing_hook: TracingHook | None = None) -> None:
        self._tracing_hook = tracing_hook

    async def before_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        content: bytes | None,
    ) -> dict[str, str]:
        """Inject tracing headers if a tracing hook is configured."""
        if self._tracing_hook is not None:
            headers = await self._tracing_hook.inject_trace_headers(
                method=method,
                url=url,
                headers=headers,
            )
        return headers


class InstrumentationResponseHook:
    """Response hook that records metrics and trace spans.

    Usage::

        metrics = MyPrometheusCollector()
        tracing = MyOpenTelemetryHook()
        hook = InstrumentationResponseHook(
            metrics_collector=metrics,
            tracing_hook=tracing,
        )
        client = TemplateHttpClient(response_hooks=[hook])
    """

    def __init__(
        self,
        *,
        metrics_collector: MetricsCollector | None = None,
        tracing_hook: TracingHook | None = None,
    ) -> None:
        self._metrics_collector = metrics_collector
        self._tracing_hook = tracing_hook

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
        """Record metrics and trace spans for the outbound response."""
        error_str = str(error) if error else None

        if self._metrics_collector is not None:
            try:
                await self._metrics_collector.record_request(
                    method=method,
                    url=url,
                    status_code=status_code,
                    duration_seconds=duration_seconds,
                    error=error_str,
                    is_retry=False,
                )
            except Exception:
                logger.warning("metrics_collector_error", exc_info=True)

        if self._tracing_hook is not None:
            try:
                await self._tracing_hook.record_span(
                    method=method,
                    url=url,
                    status_code=status_code,
                    duration_seconds=duration_seconds,
                    error=error_str,
                )
            except Exception:
                logger.warning("tracing_hook_error", exc_info=True)


__all__ = [
    "InstrumentationRequestHook",
    "InstrumentationResponseHook",
    "MetricsCollector",
    "TracingHook",
]
