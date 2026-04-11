"""OpenTelemetry distributed tracing integration.

This module provides:
- Tracer provider initialization with OTLP or console exporters
- Request, job, and webhook span helpers with context propagation
- W3C Trace Context and custom correlation ID injection for outbound headers
- OpenTelemetry span recording hook for outbound HTTP requests
- Graceful feature gating when OpenTelemetry is not installed

All tracing is opt-in and controlled by ``TRACING_ENABLED``. When disabled,
all functions become no-ops.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any

from .config import TracingSettings
from .request_context import get_current_correlation_id, get_current_request_id

logger = logging.getLogger(__name__)

# Sentinel for tracking whether OTel is available
_OTEL_AVAILABLE: bool | None = None
_tracer_provider: Any | None = None
_tracer_instance: Any | None = None


# ---------------------------------------------------------------------------
# OpenTelemetry availability check
# ---------------------------------------------------------------------------
def _check_otel_availability() -> bool:
    """Check whether the OpenTelemetry SDK is installed."""
    global _OTEL_AVAILABLE
    if _OTEL_AVAILABLE is not None:
        return _OTEL_AVAILABLE

    try:
        import opentelemetry.api  # noqa: F401
        import opentelemetry.sdk  # noqa: F401

        _OTEL_AVAILABLE = True
        return True
    except ImportError:
        _OTEL_AVAILABLE = False
        return False


# ---------------------------------------------------------------------------
# TemplateTracing — holder for tracer provider and tracer
# ---------------------------------------------------------------------------
class TemplateTracing:
    """Holds the OpenTelemetry tracer provider and active tracer instance.

    This class is instantiated by ``init_tracing()`` and provides access to
    the tracer for span creation throughout the application lifecycle.
    """

    def __init__(self, tracer_provider: Any, tracer: Any) -> None:
        """Initialize with a tracer provider and tracer instance."""
        self.tracer_provider = tracer_provider
        self.tracer = tracer


# ---------------------------------------------------------------------------
# State queries
# ---------------------------------------------------------------------------
def is_tracing_enabled() -> bool:
    """Return whether tracing is currently enabled and configured."""
    global _tracer_instance
    return _tracer_instance is not None


def get_tracer() -> Any | None:
    """Return the current OpenTelemetry tracer, or None if tracing is disabled.

    Returns:
        An OpenTelemetry Tracer instance if initialized, else None.
    """
    global _tracer_instance
    return _tracer_instance


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
def init_tracing(settings: TracingSettings | None = None) -> TemplateTracing | None:
    """Initialize OpenTelemetry tracing with the configured exporter.

    Configures a TracerProvider with a batch span processor, sets it as the
    global tracer provider, and returns a ``TemplateTracing`` holder for access
    throughout the application lifetime.

    Args:
        settings: TracingSettings. If None, uses the default settings instance.

    Returns:
        A TemplateTracing instance if tracing is enabled, else None.

    Raises:
        RuntimeError: If tracing is enabled but OpenTelemetry packages are not installed.
    """
    global _tracer_provider, _tracer_instance

    if settings is None:
        from .config import settings as default_settings

        settings = default_settings

    if not settings.TRACING_ENABLED:
        logger.debug("Tracing is disabled")
        return None

    if not _check_otel_availability():
        raise RuntimeError(
            "Tracing is enabled but OpenTelemetry packages are not installed. "
            "Install: opentelemetry-api, opentelemetry-sdk, "
            "opentelemetry-exporter-otlp-proto-grpc"
        )

    try:
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
    except ImportError as exc:
        raise RuntimeError(f"Failed to import OpenTelemetry SDK: {exc}") from exc

    service_name = settings.TRACING_SERVICE_NAME or "fastapi-template"

    resource = Resource.create({SERVICE_NAME: service_name})
    tracer_provider = TracerProvider(resource=resource)

    try:
        if settings.TRACING_EXPORTER.value == "otlp":
            _init_otlp_exporter(tracer_provider, settings)
        elif settings.TRACING_EXPORTER.value == "console":
            _init_console_exporter(tracer_provider)
        else:
            logger.warning(f"Unknown exporter: {settings.TRACING_EXPORTER}")
    except ImportError as exc:
        logger.warning(f"Failed to configure exporter: {exc}")

    from opentelemetry import trace

    trace.set_tracer_provider(tracer_provider)

    tracer = tracer_provider.get_tracer(__name__)
    _tracer_provider = tracer_provider
    _tracer_instance = tracer

    logger.info(
        "Tracing initialized",
        extra={
            "service_name": service_name,
            "exporter": settings.TRACING_EXPORTER.value,
            "sample_rate": settings.TRACING_SAMPLE_RATE,
        },
    )

    return TemplateTracing(tracer_provider=tracer_provider, tracer=tracer)


def _init_otlp_exporter(tracer_provider: Any, settings: TracingSettings) -> None:
    """Initialize OTLP exporter and attach to tracer provider."""
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        raise ImportError(
            "OTLP exporter requires: opentelemetry-exporter-otlp-proto-grpc"
        ) from exc

    exporter = OTLPSpanExporter()
    tracer_provider.add_span_processor(
        BatchSpanProcessor(exporter, schedule_delay_millis=5000)
    )


def _init_console_exporter(tracer_provider: Any) -> None:
    """Initialize console exporter for local development/debugging."""
    try:
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    except ImportError as exc:
        raise ImportError("Failed to import SimpleSpanProcessor") from exc

    try:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        exporter_cls = ConsoleSpanExporter
    except ImportError:
        # Fallback for older OpenTelemetry versions
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        class _FallbackConsoleExporter(InMemorySpanExporter):  # type: ignore[misc]
            def export(self, spans: Any) -> Any:
                for span in spans:
                    logger.info(f"SPAN: {span.name}", extra={"span": str(span)})
                return 0

        exporter_cls = _FallbackConsoleExporter  # type: ignore[assignment]

    exporter = exporter_cls()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------
async def shutdown_tracing(settings: TracingSettings | None = None) -> None:
    """Flush pending spans and shut down the tracer provider.

    Args:
        settings: TracingSettings. If None, uses the default settings instance.
    """
    global _tracer_provider, _tracer_instance

    if settings is None:
        from .config import settings as default_settings

        settings = default_settings

    if not settings.TRACING_ENABLED:
        return

    if _tracer_provider is None:
        return

    try:
        _tracer_provider.force_flush(timeout_millis=5000)
    except Exception as exc:
        logger.warning(f"Error flushing tracer provider: {exc}")

    try:
        _tracer_provider.shutdown()
    except Exception as exc:
        logger.warning(f"Error shutting down tracer provider: {exc}")

    _tracer_provider = None
    _tracer_instance = None
    logger.info("Tracing shutdown complete")


# ---------------------------------------------------------------------------
# Trace context propagation
# ---------------------------------------------------------------------------
def inject_trace_context(headers: dict[str, str]) -> dict[str, str]:
    """Inject W3C Trace Context into outbound request headers.

    Optionally injects X-Request-ID and X-Correlation-ID headers if
    ``TRACING_PROPAGATE_CORRELATION_IDS`` is enabled.

    Args:
        headers: Outbound request headers to modify.

    Returns:
        Headers with injected trace context and optional correlation IDs.
    """
    if not is_tracing_enabled():
        return headers

    try:
        from opentelemetry.trace.propagation.tracecontext import TraceContextPropagator
    except ImportError:
        return headers

    propagator = TraceContextPropagator()

    # Inject W3C Trace Context
    headers = dict(headers or {})
    propagator.inject(headers)

    # Also inject custom correlation headers if enabled
    from .config import settings as config_settings

    if config_settings.TRACING_PROPAGATE_CORRELATION_IDS:
        request_id = get_current_request_id()
        correlation_id = get_current_correlation_id()

        if request_id:
            headers.setdefault("X-Request-ID", request_id)
        if correlation_id:
            headers.setdefault("X-Correlation-ID", correlation_id)

    return headers


def extract_trace_context(headers: dict[str, str]) -> None:
    """Extract W3C Trace Context from inbound headers.

    This attaches the extracted trace context to the current span context
    for downstream propagation.

    Args:
        headers: Inbound request headers containing trace context.
    """
    if not is_tracing_enabled():
        return

    try:
        from opentelemetry.trace.propagation.tracecontext import TraceContextPropagator
    except ImportError:
        return

    propagator = TraceContextPropagator()
    propagator.extract(headers)


# ---------------------------------------------------------------------------
# Span helpers
# ---------------------------------------------------------------------------
def start_request_span(method: str, path: str, headers: dict[str, str] | None = None) -> Any:
    """Create a span for an incoming HTTP request.

    Includes request_id and correlation_id attributes from the current context.

    Args:
        method: HTTP method (GET, POST, etc.).
        path: Request path.
        headers: Request headers (used to extract trace context).

    Returns:
        An OpenTelemetry Span, or a no-op span if tracing is disabled.
    """
    tracer = get_tracer()
    if tracer is None:
        return None

    extract_trace_context(headers or {})

    span = tracer.start_span(f"{method} {path}")
    span.set_attribute("http.method", method)
    span.set_attribute("http.target", path)

    request_id = get_current_request_id()
    correlation_id = get_current_correlation_id()

    if request_id:
        span.set_attribute("http.request_id", request_id)
    if correlation_id:
        span.set_attribute("trace.correlation_id", correlation_id)

    return span


def start_job_span(job_name: str, job_id: str, correlation_id: str | None = None) -> Any:
    """Create a span for a background job execution.

    Args:
        job_name: Name of the background job.
        job_id: Unique identifier for this job execution.
        correlation_id: Optional correlation ID for tracing across services.

    Returns:
        An OpenTelemetry Span, or None if tracing is disabled.
    """
    tracer = get_tracer()
    if tracer is None:
        return None

    span = tracer.start_span(f"job/{job_name}")
    span.set_attribute("job.name", job_name)
    span.set_attribute("job.id", job_id)

    if correlation_id:
        span.set_attribute("trace.correlation_id", correlation_id)

    return span


def start_webhook_span(provider: str, event_type: str, delivery_id: str) -> Any:
    """Create a span for webhook processing.

    Args:
        provider: Name of the webhook provider (GitHub, Stripe, etc.).
        event_type: Type of webhook event.
        delivery_id: Unique delivery identifier from the provider.

    Returns:
        An OpenTelemetry Span, or None if tracing is disabled.
    """
    tracer = get_tracer()
    if tracer is None:
        return None

    span = tracer.start_span(f"webhook/{provider}/{event_type}")
    span.set_attribute("webhook.provider", provider)
    span.set_attribute("webhook.event_type", event_type)
    span.set_attribute("webhook.delivery_id", delivery_id)

    return span


def start_outbound_span(method: str, url: str) -> Any:
    """Create a span for an outbound HTTP request.

    Args:
        method: HTTP method (GET, POST, etc.).
        url: Request URL.

    Returns:
        An OpenTelemetry Span, or None if tracing is disabled.
    """
    tracer = get_tracer()
    if tracer is None:
        return None

    span = tracer.start_span(f"{method} {url}")
    span.set_attribute("http.method", method)
    span.set_attribute("http.url", url)

    return span


@contextmanager
def trace_span(name: str, attributes: dict[str, Any] | None = None):
    """Context manager for creating and managing a named span.

    Usage::

        with trace_span("my_operation", {"user_id": "123"}):
            # do work
            pass

    Args:
        name: Name of the span.
        attributes: Optional span attributes to set.

    Yields:
        The OpenTelemetry Span if tracing is enabled, else None.
    """
    tracer = get_tracer()
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield span


# ---------------------------------------------------------------------------
# OpenTelemetry TracingHook implementation
# ---------------------------------------------------------------------------
class OpenTelemetryTracingHook:
    """Implements TracingHook protocol for outbound HTTP request tracing.

    This class integrates OpenTelemetry span recording with the template's
    HTTP client instrumentation system.

    Usage::

        from src.app.integrations.http_client.instrumentation import InstrumentationRequestHook
        hook = InstrumentationRequestHook(tracing_hook=OpenTelemetryTracingHook())
        client = TemplateHttpClient(request_hooks=[hook])
    """

    async def inject_trace_headers(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
    ) -> dict[str, str]:
        """Inject W3C Trace Context and correlation IDs into outbound headers.

        Args:
            method: HTTP method.
            url: Request URL.
            headers: Outbound request headers.

        Returns:
            Headers with injected trace context.
        """
        return inject_trace_context(headers)

    async def record_span(
        self,
        *,
        method: str,
        url: str,
        status_code: int,
        duration_seconds: float,
        error: str | None,
    ) -> None:
        """Record a trace span for the outbound HTTP request.

        Args:
            method: HTTP method.
            url: Request URL.
            status_code: HTTP status code of the response.
            duration_seconds: Duration of the request in seconds.
            error: Error message if the request failed, else None.
        """
        with trace_span(
            f"{method} {url}",
            {
                "http.method": method,
                "http.url": url,
                "http.status_code": status_code,
                "http.duration_seconds": duration_seconds,
                **({"http.error": error} if error else {}),
            },
        ) as span:
            if span and error:
                span.record_exception(Exception(error))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
__all__ = [
    "TemplateTracing",
    "get_tracer",
    "init_tracing",
    "is_tracing_enabled",
    "shutdown_tracing",
    "inject_trace_context",
    "extract_trace_context",
    "start_request_span",
    "start_job_span",
    "start_webhook_span",
    "start_outbound_span",
    "trace_span",
    "OpenTelemetryTracingHook",
]
