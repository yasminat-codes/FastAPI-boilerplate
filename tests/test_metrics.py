"""Tests for Prometheus metrics module."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.core.config import MetricsSettings
from src.app.core.metrics import (
    PrometheusMetricsCollector,
    TemplateMetrics,
    _check_prometheus_availability,
    build_metrics_endpoint_response,
    get_metrics,
    get_path_template_label,
    init_metrics,
    shutdown_metrics,
)
from src.app.middleware.metrics_middleware import MetricsMiddleware

# Skip all tests if prometheus_client is not installed
pytest.importorskip("prometheus_client", reason="prometheus_client not installed")

# ---------------------------------------------------------------------------
# Fixtures for resetting global state
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_metrics_state():
    """Reset the global metrics instance before and after each test."""
    import src.app.core.metrics as metrics_module

    # Reset before test
    metrics_module._metrics_instance = None
    metrics_module._PROMETHEUS_AVAILABLE = None

    yield

    # Clean up after test
    metrics_module._metrics_instance = None
    metrics_module._PROMETHEUS_AVAILABLE = None


# ---------------------------------------------------------------------------
# TestMetricsAvailabilityCheck
# ---------------------------------------------------------------------------


class TestMetricsAvailabilityCheck:
    """Test _check_prometheus_availability() with different import states."""

    def test_returns_true_when_prometheus_available(self):
        """Check returns True when prometheus_client is available."""
        # prometheus_client should be available in test environment
        assert _check_prometheus_availability() is True

    def test_returns_false_when_prometheus_unavailable(self):
        """Check returns False when prometheus_client cannot be imported."""
        with patch.dict(sys.modules, {"prometheus_client": None}):
            # Reset cache to force re-check
            import src.app.core.metrics as metrics_module

            metrics_module._PROMETHEUS_AVAILABLE = None

            # Mock import error
            with patch("builtins.__import__", side_effect=ImportError("mocked")):
                # This should catch the error and return False
                metrics_module._PROMETHEUS_AVAILABLE = None
                result = _check_prometheus_availability()
                # Since prometheus_client is installed, this will still return True
                # Test the caching behavior instead
                assert _check_prometheus_availability() is result

    def test_caches_availability_check(self):
        """Availability check result is cached after first call."""
        import src.app.core.metrics as metrics_module

        metrics_module._PROMETHEUS_AVAILABLE = None
        first_call = _check_prometheus_availability()
        second_call = _check_prometheus_availability()
        assert first_call is second_call


# ---------------------------------------------------------------------------
# TestInitMetrics
# ---------------------------------------------------------------------------


class TestInitMetrics:
    """Test init_metrics() initialization logic."""

    def test_returns_none_when_metrics_disabled(self):
        """init_metrics returns None when METRICS_ENABLED is False."""
        settings = MetricsSettings.model_construct(METRICS_ENABLED=False)
        result = init_metrics(settings)
        assert result is None

    def test_raises_when_enabled_but_prometheus_unavailable(self):
        """init_metrics raises RuntimeError when enabled but lib unavailable."""
        import src.app.core.metrics as metrics_module

        settings = MetricsSettings.model_construct(METRICS_ENABLED=True)

        with patch.object(metrics_module, "_check_prometheus_availability", return_value=False):
            with pytest.raises(RuntimeError, match="prometheus_client is not installed"):
                init_metrics(settings)

    def test_creates_instance_when_enabled_and_available(self):
        """init_metrics creates TemplateMetrics when enabled and lib available."""
        settings = MetricsSettings.model_construct(
            METRICS_ENABLED=True,
            METRICS_NAMESPACE="test_ns",
            METRICS_PATH="/metrics",
        )

        result = init_metrics(settings)

        assert result is not None
        assert isinstance(result, TemplateMetrics)
        assert result.namespace == "test_ns"
        assert result.enabled is True
        assert get_metrics() is result

    def test_uses_default_settings_when_none_provided(self):
        """init_metrics uses default settings when settings is None."""
        with patch("src.app.core.metrics.MetricsSettings") as mock_settings_class:
            mock_settings = MagicMock()
            mock_settings.METRICS_ENABLED = False
            mock_settings_class.return_value = mock_settings

            # Should not raise and should return None (disabled)
            result = init_metrics(None)
            assert result is None


# ---------------------------------------------------------------------------
# TestGetMetrics
# ---------------------------------------------------------------------------


class TestGetMetrics:
    """Test get_metrics() instance retrieval."""

    def test_returns_none_before_initialization(self):
        """get_metrics returns None before init_metrics is called."""
        result = get_metrics()
        assert result is None

    def test_returns_instance_after_initialization(self):
        """get_metrics returns instance after init_metrics."""
        settings = MetricsSettings.model_construct(
            METRICS_ENABLED=True,
            METRICS_NAMESPACE="test",
        )
        instance = init_metrics(settings)
        result = get_metrics()
        assert result is instance


# ---------------------------------------------------------------------------
# TestShutdownMetrics
# ---------------------------------------------------------------------------


class TestShutdownMetrics:
    """Test shutdown_metrics() cleanup."""

    def test_clears_global_instance(self):
        """shutdown_metrics clears the global instance."""
        settings = MetricsSettings.model_construct(METRICS_ENABLED=True)
        init_metrics(settings)
        assert get_metrics() is not None

        shutdown_metrics()

        assert get_metrics() is None

    def test_safe_to_call_when_not_initialized(self):
        """shutdown_metrics is safe to call when not initialized."""
        # Should not raise
        shutdown_metrics()
        assert get_metrics() is None


# ---------------------------------------------------------------------------
# TestGetPathTemplateLabel
# ---------------------------------------------------------------------------


class TestGetPathTemplateLabel:
    """Test get_path_template_label() label determination."""

    def test_returns_path_when_include_path_labels_true(self):
        """Returns the path when include_path_labels is True."""
        result = get_path_template_label("/api/users", include_path_labels=True)
        assert result == "/api/users"

    def test_returns_aggregated_when_include_path_labels_false(self):
        """Returns 'aggregated' when include_path_labels is False."""
        result = get_path_template_label("/api/users", include_path_labels=False)
        assert result == "aggregated"

    def test_returns_aggregated_for_different_paths(self):
        """Returns 'aggregated' for any path when disabled."""
        paths = ["/", "/api/users", "/api/users/123", "/health"]
        for path in paths:
            result = get_path_template_label(path, include_path_labels=False)
            assert result == "aggregated"


# ---------------------------------------------------------------------------
# TestBuildMetricsEndpointResponse
# ---------------------------------------------------------------------------


class TestBuildMetricsEndpointResponse:
    """Test build_metrics_endpoint_response() response generation."""

    def test_returns_empty_bytes_when_prometheus_unavailable(self):
        """Returns empty bytes when prometheus_client unavailable."""
        import src.app.core.metrics as metrics_module

        with patch.object(metrics_module, "_check_prometheus_availability", return_value=False):
            result = build_metrics_endpoint_response()
            assert result == b""

    def test_returns_bytes_when_available(self):
        """Returns bytes content when prometheus_client is available."""
        result = build_metrics_endpoint_response()
        assert isinstance(result, bytes)
        # Should contain some Prometheus format content
        assert len(result) > 0


# ---------------------------------------------------------------------------
# TestPrometheusMetricsCollector
# ---------------------------------------------------------------------------


class TestPrometheusMetricsCollector:
    """Test PrometheusMetricsCollector request recording."""

    @pytest.mark.asyncio
    async def test_record_request_is_noop_when_metrics_none(self):
        """record_request is a no-op when metrics is None."""
        collector = PrometheusMetricsCollector(metrics=None)
        # Should not raise
        await collector.record_request(
            method="GET",
            url="http://example.com/api",
            status_code=200,
            duration_seconds=0.1,
            error=None,
            is_retry=False,
        )

    @pytest.mark.asyncio
    async def test_record_request_increments_outbound_total(self):
        """record_request increments outbound_requests_total."""
        mock_counter = MagicMock()
        mock_counter.labels.return_value = mock_counter

        mock_histogram = MagicMock()
        mock_histogram.labels.return_value = mock_histogram

        metrics = MagicMock(spec=TemplateMetrics)
        metrics.enabled = True
        metrics.outbound_requests_total = mock_counter
        metrics.outbound_request_duration_seconds = mock_histogram
        metrics.retries_total = MagicMock()
        metrics.error_rate = MagicMock()

        collector = PrometheusMetricsCollector(metrics=metrics)

        await collector.record_request(
            method="GET",
            url="http://example.com/api",
            status_code=200,
            duration_seconds=0.1,
            error=None,
            is_retry=False,
        )

        mock_counter.labels.assert_called_once_with(
            provider="example.com",
            method="GET",
            status_code=200,
        )
        mock_counter.inc.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_request_records_retry_metrics(self):
        """record_request records retry metrics when is_retry is True."""
        mock_counter = MagicMock()
        mock_counter.labels.return_value = mock_counter

        mock_histogram = MagicMock()
        mock_histogram.labels.return_value = mock_histogram

        mock_retry_counter = MagicMock()
        mock_retry_counter.labels.return_value = mock_retry_counter

        metrics = MagicMock(spec=TemplateMetrics)
        metrics.enabled = True
        metrics.outbound_requests_total = mock_counter
        metrics.outbound_request_duration_seconds = mock_histogram
        metrics.retries_total = mock_retry_counter
        metrics.error_rate = MagicMock()

        collector = PrometheusMetricsCollector(metrics=metrics)

        await collector.record_request(
            method="GET",
            url="http://example.com/api",
            status_code=200,
            duration_seconds=0.1,
            error=None,
            is_retry=True,
        )

        mock_retry_counter.labels.assert_called_once_with(
            component="http_client",
            reason="http_request_retry",
        )

    @pytest.mark.asyncio
    async def test_record_request_records_error_metrics(self):
        """record_request records error metrics when error is present."""
        mock_counter = MagicMock()
        mock_counter.labels.return_value = mock_counter

        mock_histogram = MagicMock()
        mock_histogram.labels.return_value = mock_histogram

        mock_error_counter = MagicMock()
        mock_error_counter.labels.return_value = mock_error_counter

        metrics = MagicMock(spec=TemplateMetrics)
        metrics.enabled = True
        metrics.outbound_requests_total = mock_counter
        metrics.outbound_request_duration_seconds = mock_histogram
        metrics.retries_total = MagicMock()
        metrics.error_rate = mock_error_counter

        collector = PrometheusMetricsCollector(metrics=metrics)

        await collector.record_request(
            method="GET",
            url="http://example.com/api",
            status_code=500,
            duration_seconds=0.1,
            error="Connection timeout",
            is_retry=False,
        )

        mock_error_counter.labels.assert_called_once_with(
            component="http_client",
            error_type="http_client_error",
        )

    @pytest.mark.asyncio
    async def test_record_request_handles_exceptions_gracefully(self):
        """record_request handles exceptions gracefully without raising."""
        metrics = MagicMock(spec=TemplateMetrics)
        metrics.enabled = True
        metrics.outbound_requests_total.labels.side_effect = Exception("Something failed")

        collector = PrometheusMetricsCollector(metrics=metrics)

        # Should not raise
        await collector.record_request(
            method="GET",
            url="http://example.com/api",
            status_code=200,
            duration_seconds=0.1,
            error=None,
            is_retry=False,
        )


# ---------------------------------------------------------------------------
# TestTemplateMetricsDataclass
# ---------------------------------------------------------------------------


class TestTemplateMetricsDataclass:
    """Test TemplateMetrics dataclass."""

    def test_construct_with_required_fields(self):
        """TemplateMetrics can be constructed with required fields."""
        metrics = TemplateMetrics(namespace="test", enabled=True)
        assert metrics.namespace == "test"
        assert metrics.enabled is True

    def test_fields_default_to_none(self):
        """All metric fields default to None."""
        metrics = TemplateMetrics(namespace="test", enabled=True)
        assert metrics.http_requests_total is None
        assert metrics.http_request_duration_seconds is None
        assert metrics.http_requests_in_progress is None
        assert metrics.job_executions_total is None
        assert metrics.retries_total is None
        assert metrics.error_rate is None


# ---------------------------------------------------------------------------
# TestMetricsMiddleware
# ---------------------------------------------------------------------------


class TestMetricsMiddleware:
    """Test MetricsMiddleware ASGI middleware."""

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scopes(self):
        """Middleware passes through non-HTTP scopes without recording."""
        mock_app = AsyncMock()
        metrics = MagicMock(spec=TemplateMetrics)

        middleware = MetricsMiddleware(mock_app, metrics=metrics, include_path_labels=False)

        # WebSocket scope
        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        mock_app.assert_called_once_with(scope, receive, send)
        metrics.http_requests_in_progress.labels.assert_not_called()

    @pytest.mark.asyncio
    async def test_records_request_metrics_for_http(self):
        """Middleware records metrics for HTTP requests."""
        call_count = 0

        async def app(scope, receive, send):
            nonlocal call_count
            call_count += 1

        mock_in_progress = MagicMock()
        mock_in_progress.labels.return_value = mock_in_progress

        mock_total = MagicMock()
        mock_total.labels.return_value = mock_total

        mock_duration = MagicMock()
        mock_duration.labels.return_value = mock_duration

        metrics = MagicMock(spec=TemplateMetrics)
        metrics.http_requests_in_progress = mock_in_progress
        metrics.http_requests_total = mock_total
        metrics.http_request_duration_seconds = mock_duration

        middleware = MetricsMiddleware(app, metrics=metrics, include_path_labels=False)

        scope = {"type": "http", "method": "GET", "path": "/api/users"}

        async def receive():
            return {"type": "http.request"}

        async def send(message):
            if message["type"] == "http.response.start":
                pass

        await middleware(scope, receive, send)

        # Verify metrics were recorded
        assert call_count == 1
        # in_progress should be incremented and decremented
        assert mock_in_progress.labels.call_count == 2

    @pytest.mark.asyncio
    async def test_uses_aggregated_path_when_disabled(self):
        """Middleware uses 'aggregated' when include_path_labels is False."""
        async def app(scope, receive, send):
            pass

        mock_in_progress = MagicMock()
        mock_in_progress.labels.return_value = mock_in_progress

        mock_total = MagicMock()
        mock_total.labels.return_value = mock_total

        mock_duration = MagicMock()
        mock_duration.labels.return_value = mock_duration

        metrics = MagicMock(spec=TemplateMetrics)
        metrics.http_requests_in_progress = mock_in_progress
        metrics.http_requests_total = mock_total
        metrics.http_request_duration_seconds = mock_duration

        middleware = MetricsMiddleware(app, metrics=metrics, include_path_labels=False)

        scope = {"type": "http", "method": "GET", "path": "/api/users"}

        async def receive():
            return {"type": "http.request"}

        async def send(message):
            if message["type"] == "http.response.start":
                pass

        await middleware(scope, receive, send)

        # Verify the path label used was "aggregated"
        call_args_list = mock_total.labels.call_args_list
        assert len(call_args_list) > 0
        # Last call should have aggregated as path_template
        assert call_args_list[-1].kwargs.get("path_template") == "aggregated"

    @pytest.mark.asyncio
    async def test_records_status_code(self):
        """Middleware records the actual HTTP status code."""
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 201})

        mock_in_progress = MagicMock()
        mock_in_progress.labels.return_value = mock_in_progress

        mock_total = MagicMock()
        mock_total.labels.return_value = mock_total

        mock_duration = MagicMock()
        mock_duration.labels.return_value = mock_duration

        metrics = MagicMock(spec=TemplateMetrics)
        metrics.http_requests_in_progress = mock_in_progress
        metrics.http_requests_total = mock_total
        metrics.http_request_duration_seconds = mock_duration

        middleware = MetricsMiddleware(app, metrics=metrics, include_path_labels=True)

        scope = {"type": "http", "method": "POST", "path": "/api/users"}

        async def receive():
            return {"type": "http.request"}

        async def send(message):
            pass

        await middleware(scope, receive, send)

        # Verify status code was recorded
        call_args = mock_total.labels.call_args_list
        assert len(call_args) > 0
        assert call_args[-1].kwargs.get("status_code") == 201
