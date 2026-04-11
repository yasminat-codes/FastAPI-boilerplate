"""Prometheus-compatible metrics module for FastAPI template.

Provides opt-in metrics collection across HTTP requests, background jobs,
webhooks, outbound integrations, and error/retry scenarios. Metrics are
prefixed with the configured namespace and expose a Prometheus-compatible
text-format endpoint.

All ``prometheus_client`` imports are deferred so the module can be
imported safely even when the package is not installed. A clear
``RuntimeError`` is raised at ``init_metrics()`` time if the feature is
enabled but the package is missing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .config import MetricsSettings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# prometheus_client availability check
# ---------------------------------------------------------------------------
_PROMETHEUS_AVAILABLE: bool | None = None


def _check_prometheus_availability() -> bool:
    """Return True if prometheus_client is installed."""
    global _PROMETHEUS_AVAILABLE
    if _PROMETHEUS_AVAILABLE is not None:
        return _PROMETHEUS_AVAILABLE

    try:
        import prometheus_client  # noqa: F401

        _PROMETHEUS_AVAILABLE = True
    except ImportError:
        _PROMETHEUS_AVAILABLE = False

    return _PROMETHEUS_AVAILABLE

# Global metrics instance
_metrics_instance: TemplateMetrics | None = None


# ---------------------------------------------------------------------------
# Metrics container
# ---------------------------------------------------------------------------
@dataclass
class TemplateMetrics:
    """Container for all Prometheus metrics in the template.

    Each field holds a ``prometheus_client`` collector typed as ``Any``
    so the dataclass can be imported without requiring the package at
    module level.
    """

    namespace: str
    enabled: bool

    # Request metrics
    http_requests_total: Any = field(default=None)
    http_request_duration_seconds: Any = field(default=None)
    http_requests_in_progress: Any = field(default=None)

    # Job metrics
    job_executions_total: Any = field(default=None)
    job_duration_seconds: Any = field(default=None)
    jobs_in_progress: Any = field(default=None)
    job_queue_size: Any = field(default=None)

    # Webhook metrics
    webhook_events_received_total: Any = field(default=None)
    webhook_processing_duration_seconds: Any = field(default=None)
    webhook_signature_failures_total: Any = field(default=None)

    # Outbound integration metrics
    outbound_requests_total: Any = field(default=None)
    outbound_request_duration_seconds: Any = field(default=None)
    outbound_circuit_breaker_state: Any = field(default=None)

    # Failure/retry metrics
    retries_total: Any = field(default=None)
    dead_letter_events_total: Any = field(default=None)
    error_rate: Any = field(default=None)


# ---------------------------------------------------------------------------
# Internal factory
# ---------------------------------------------------------------------------
def _build_metrics(settings: MetricsSettings, registry: Any = None) -> TemplateMetrics:
    """Create and register all Prometheus collectors.

    Raises:
        RuntimeError: If prometheus_client is not installed.
    """
    from prometheus_client import REGISTRY, Counter, Gauge, Histogram

    if registry is None:
        registry = REGISTRY

    ns = settings.METRICS_NAMESPACE

    def _name(suffix: str) -> str:
        return f"{ns}_{suffix}"

    return TemplateMetrics(
        namespace=ns,
        enabled=True,
        # Request
        http_requests_total=Counter(
            _name("http_requests_total"),
            "Total HTTP requests",
            labelnames=["method", "path_template", "status_code"],
            registry=registry,
        ),
        http_request_duration_seconds=Histogram(
            _name("http_request_duration_seconds"),
            "HTTP request latency in seconds",
            labelnames=["method", "path_template"],
            registry=registry,
        ),
        http_requests_in_progress=Gauge(
            _name("http_requests_in_progress"),
            "HTTP requests currently being processed",
            labelnames=["method"],
            registry=registry,
        ),
        # Job
        job_executions_total=Counter(
            _name("job_executions_total"),
            "Total job executions",
            labelnames=["job_name", "status"],
            registry=registry,
        ),
        job_duration_seconds=Histogram(
            _name("job_duration_seconds"),
            "Job execution duration in seconds",
            labelnames=["job_name"],
            registry=registry,
        ),
        jobs_in_progress=Gauge(
            _name("jobs_in_progress"),
            "Jobs currently being executed",
            labelnames=["job_name"],
            registry=registry,
        ),
        job_queue_size=Gauge(
            _name("job_queue_size"),
            "Number of jobs waiting in the queue",
            registry=registry,
        ),
        # Webhook
        webhook_events_received_total=Counter(
            _name("webhook_events_received_total"),
            "Total webhook events received",
            labelnames=["provider", "event_type", "status"],
            registry=registry,
        ),
        webhook_processing_duration_seconds=Histogram(
            _name("webhook_processing_duration_seconds"),
            "Webhook processing latency in seconds",
            labelnames=["provider"],
            registry=registry,
        ),
        webhook_signature_failures_total=Counter(
            _name("webhook_signature_failures_total"),
            "Total webhook signature verification failures",
            labelnames=["provider"],
            registry=registry,
        ),
        # Outbound
        outbound_requests_total=Counter(
            _name("outbound_requests_total"),
            "Total outbound HTTP requests",
            labelnames=["provider", "method", "status_code"],
            registry=registry,
        ),
        outbound_request_duration_seconds=Histogram(
            _name("outbound_request_duration_seconds"),
            "Outbound HTTP request latency in seconds",
            labelnames=["provider", "method"],
            registry=registry,
        ),
        outbound_circuit_breaker_state=Gauge(
            _name("outbound_circuit_breaker_state"),
            "Circuit breaker state (0=closed, 1=open, 2=half-open)",
            labelnames=["provider"],
            registry=registry,
        ),
        # Failure/retry
        retries_total=Counter(
            _name("retries_total"),
            "Total retry attempts",
            labelnames=["component", "reason"],
            registry=registry,
        ),
        dead_letter_events_total=Counter(
            _name("dead_letter_events_total"),
            "Total events moved to dead letter queue",
            labelnames=["component"],
            registry=registry,
        ),
        error_rate=Counter(
            _name("error_rate"),
            "Error occurrence count",
            labelnames=["component", "error_type"],
            registry=registry,
        ),
    )


# ---------------------------------------------------------------------------
# PrometheusMetricsCollector — implements MetricsCollector protocol
# ---------------------------------------------------------------------------
class PrometheusMetricsCollector:
    """Prometheus-compatible metrics collector for outbound HTTP requests.

    Implements the MetricsCollector protocol from the HTTP client
    instrumentation layer and records metrics to the global TemplateMetrics
    instance if enabled.
    """

    def __init__(self, metrics: TemplateMetrics | None = None) -> None:
        self.metrics = metrics

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
        """Record metrics for an outbound HTTP request.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full request URL
            status_code: HTTP response status code
            duration_seconds: Request duration in seconds
            error: Error message if request failed, otherwise None
            is_retry: Whether this request is a retry attempt
        """
        if self.metrics is None or not self.metrics.enabled:
            return

        try:
            # Extract provider name from URL
            parsed_url = urlparse(url)
            provider = parsed_url.netloc or "unknown"

            # Record outbound request metrics
            self.metrics.outbound_requests_total.labels(
                provider=provider,
                method=method,
                status_code=status_code,
            ).inc()

            self.metrics.outbound_request_duration_seconds.labels(
                provider=provider,
                method=method,
            ).observe(duration_seconds)

            # Record retry if applicable
            if is_retry:
                self.metrics.retries_total.labels(
                    component="http_client",
                    reason="http_request_retry",
                ).inc()

            # Record error if present
            if error:
                self.metrics.error_rate.labels(
                    component="http_client",
                    error_type="http_client_error",
                ).inc()

        except Exception:
            logger.exception("Failed to record outbound HTTP metrics")


# ---------------------------------------------------------------------------
# Global instance management
# ---------------------------------------------------------------------------
def init_metrics(settings: MetricsSettings | None = None) -> TemplateMetrics | None:
    """Initialize and return the global TemplateMetrics instance.

    This function is opt-in: it only creates metrics if ``METRICS_ENABLED``
    is ``True``.  Should be called during application startup.

    Raises:
        RuntimeError: If metrics are enabled but ``prometheus_client`` is not installed.
    """
    global _metrics_instance

    if settings is None:
        from .config import settings as default_settings

        settings = default_settings

    if not settings.METRICS_ENABLED:
        logger.debug("Metrics disabled via configuration")
        return None

    if not _check_prometheus_availability():
        raise RuntimeError(
            "Metrics are enabled but prometheus_client is not installed. "
            "Install: pip install prometheus-client"
        )

    _metrics_instance = _build_metrics(settings)
    logger.info(
        "Metrics initialized",
        extra={
            "namespace": settings.METRICS_NAMESPACE,
            "path": settings.METRICS_PATH,
            "include_path_labels": settings.METRICS_INCLUDE_REQUEST_PATH_LABELS,
        },
    )
    return _metrics_instance


def get_metrics() -> TemplateMetrics | None:
    """Get the global TemplateMetrics instance, if initialized.

    Returns:
        TemplateMetrics instance or None if not initialized or disabled
    """
    return _metrics_instance


def shutdown_metrics() -> None:
    """Shut down and clean up the metrics system.

    Should be called during application shutdown. Clears the global instance
    so a fresh one can be created if the application restarts.
    """
    global _metrics_instance

    if _metrics_instance is None:
        return

    logger.info("Metrics shutdown complete")
    _metrics_instance = None


def build_metrics_endpoint_response() -> bytes:
    """Build the Prometheus text-format response for the ``/metrics`` endpoint.

    Returns:
        Prometheus text-format metrics as bytes, or empty bytes if the
        library is unavailable.
    """
    if not _check_prometheus_availability():
        return b""

    from prometheus_client import REGISTRY, generate_latest

    result: bytes = generate_latest(REGISTRY)
    return result


# ---------------------------------------------------------------------------
# Helper for determining path template (respects METRICS_INCLUDE_REQUEST_PATH_LABELS)
# ---------------------------------------------------------------------------
def get_path_template_label(
    path: str,
    *,
    include_path_labels: bool,
) -> str:
    """Determine the path_template label value for metrics.

    If include_path_labels is False, all requests are aggregated under
    "aggregated" to prevent cardinality explosion from unique paths.

    Args:
        path: The request path
        include_path_labels: Whether to include individual paths in metrics

    Returns:
        Either the path itself or "aggregated"
    """
    return path if include_path_labels else "aggregated"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
__all__ = [
    "PrometheusMetricsCollector",
    "TemplateMetrics",
    "build_metrics_endpoint_response",
    "get_metrics",
    "get_path_template_label",
    "init_metrics",
    "shutdown_metrics",
]
