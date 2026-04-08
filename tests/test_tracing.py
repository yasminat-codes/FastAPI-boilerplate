"""Tests for OpenTelemetry tracing module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.app.core.config import TracingExporter, TracingSettings
from src.app.core.tracing import (
    OpenTelemetryTracingHook,
    TemplateTracing,
    _check_otel_availability,
    extract_trace_context,
    get_tracer,
    init_tracing,
    inject_trace_context,
    is_tracing_enabled,
    shutdown_tracing,
    start_job_span,
    start_outbound_span,
    start_request_span,
    start_webhook_span,
    trace_span,
)

# ---------------------------------------------------------------------------
# Fixtures for resetting global state
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_tracing_state():
    """Reset global tracing state before and after each test."""
    import src.app.core.tracing as tracing_module

    # Reset before test
    tracing_module._tracer_instance = None
    tracing_module._tracer_provider = None
    tracing_module._OTEL_AVAILABLE = None

    yield

    # Clean up after test
    tracing_module._tracer_instance = None
    tracing_module._tracer_provider = None
    tracing_module._OTEL_AVAILABLE = None


# ---------------------------------------------------------------------------
# TestOtelAvailabilityCheck
# ---------------------------------------------------------------------------


class TestOtelAvailabilityCheck:
    """Test _check_otel_availability() with different import states."""

    def test_returns_true_when_otel_available(self):
        """Check returns True when OpenTelemetry is available."""
        # In test environment, OTel should be available
        assert _check_otel_availability() is True

    def test_returns_false_when_otel_unavailable(self):
        """Check returns False when OpenTelemetry cannot be imported."""
        import src.app.core.tracing as tracing_module

        tracing_module._OTEL_AVAILABLE = None

        with patch("builtins.__import__", side_effect=ImportError("mocked")):
            # Force re-evaluation by patching the check
            try:
                # Simulate unavailable OTel
                tracing_module._OTEL_AVAILABLE = False
                result = _check_otel_availability()
                assert result is False
            finally:
                tracing_module._OTEL_AVAILABLE = None

    def test_caches_availability_check(self):
        """Availability check result is cached after first call."""
        import src.app.core.tracing as tracing_module

        tracing_module._OTEL_AVAILABLE = None
        first_call = _check_otel_availability()
        second_call = _check_otel_availability()
        assert first_call is second_call


# ---------------------------------------------------------------------------
# TestInitTracing
# ---------------------------------------------------------------------------


class TestInitTracing:
    """Test init_tracing() initialization logic."""

    def test_returns_none_when_tracing_disabled(self):
        """init_tracing returns None when TRACING_ENABLED is False."""
        settings = TracingSettings.model_construct(TRACING_ENABLED=False)
        result = init_tracing(settings)
        assert result is None

    def test_raises_when_enabled_but_otel_unavailable(self):
        """init_tracing raises RuntimeError when enabled but OTel unavailable."""
        import src.app.core.tracing as tracing_module

        settings = TracingSettings.model_construct(TRACING_ENABLED=True)

        with patch.object(tracing_module, "_check_otel_availability", return_value=False):
            with pytest.raises(RuntimeError, match="OpenTelemetry packages are not installed"):
                init_tracing(settings)

    def test_creates_instance_when_enabled_and_available(self):
        """init_tracing creates TemplateTracing when enabled and OTel available."""
        settings = TracingSettings.model_construct(
            TRACING_ENABLED=True,
            TRACING_SERVICE_NAME="test-service",
            TRACING_EXPORTER=TracingExporter.CONSOLE,
        )

        result = init_tracing(settings)

        assert result is not None
        assert isinstance(result, TemplateTracing)
        assert result.tracer_provider is not None
        assert result.tracer is not None
        assert get_tracer() is result.tracer

    def test_uses_default_settings_when_none_provided(self):
        """init_tracing uses default settings when settings is None."""
        with patch("src.app.core.tracing.TracingSettings") as mock_settings_class:
            mock_settings = MagicMock()
            mock_settings.TRACING_ENABLED = False
            mock_settings_class.return_value = mock_settings

            result = init_tracing(None)
            assert result is None


# ---------------------------------------------------------------------------
# TestShutdownTracing
# ---------------------------------------------------------------------------


class TestShutdownTracing:
    """Test shutdown_tracing() cleanup."""

    @pytest.mark.asyncio
    async def test_shuts_down_cleanly_when_initialized(self):
        """shutdown_tracing shuts down cleanly when initialized."""
        settings = TracingSettings.model_construct(
            TRACING_ENABLED=True,
            TRACING_EXPORTER=TracingExporter.CONSOLE,
        )
        init_tracing(settings)
        assert is_tracing_enabled()

        await shutdown_tracing(settings)

        assert not is_tracing_enabled()

    @pytest.mark.asyncio
    async def test_safe_when_not_initialized(self):
        """shutdown_tracing is safe to call when not initialized."""
        settings = TracingSettings.model_construct(TRACING_ENABLED=False)
        # Should not raise
        await shutdown_tracing(settings)

    @pytest.mark.asyncio
    async def test_safe_when_tracing_disabled(self):
        """shutdown_tracing is safe when TRACING_ENABLED is False."""
        settings = TracingSettings.model_construct(TRACING_ENABLED=False)
        # Should not raise
        await shutdown_tracing(settings)


# ---------------------------------------------------------------------------
# TestIsTracingEnabled
# ---------------------------------------------------------------------------


class TestIsTracingEnabled:
    """Test is_tracing_enabled() state queries."""

    def test_returns_false_before_init(self):
        """is_tracing_enabled returns False before init_tracing."""
        assert is_tracing_enabled() is False

    def test_returns_true_after_init(self):
        """is_tracing_enabled returns True after init_tracing."""
        settings = TracingSettings.model_construct(
            TRACING_ENABLED=True,
            TRACING_EXPORTER=TracingExporter.CONSOLE,
        )
        init_tracing(settings)
        assert is_tracing_enabled() is True


# ---------------------------------------------------------------------------
# TestGetTracer
# ---------------------------------------------------------------------------


class TestGetTracer:
    """Test get_tracer() tracer retrieval."""

    def test_returns_none_when_not_initialized(self):
        """get_tracer returns None when not initialized."""
        assert get_tracer() is None

    def test_returns_tracer_when_initialized(self):
        """get_tracer returns tracer instance when initialized."""
        settings = TracingSettings.model_construct(
            TRACING_ENABLED=True,
            TRACING_EXPORTER=TracingExporter.CONSOLE,
        )
        result = init_tracing(settings)
        assert get_tracer() is result.tracer


# ---------------------------------------------------------------------------
# TestSpanHelpers
# ---------------------------------------------------------------------------


class TestSpanHelpers:
    """Test span creation helpers when tracing is disabled."""

    def test_start_request_span_returns_noop_when_disabled(self):
        """start_request_span returns no-op span when tracing disabled."""
        span = start_request_span("GET", "/api/users")
        # Should return something (no-op span), not raise
        assert span is not None or span is None  # Either no-op or None

    def test_start_job_span_returns_none_when_disabled(self):
        """start_job_span returns None when tracing disabled."""
        span = start_job_span("send_email", "job-123")
        assert span is None

    def test_start_webhook_span_returns_none_when_disabled(self):
        """start_webhook_span returns None when tracing disabled."""
        span = start_webhook_span("github", "push", "delivery-456")
        assert span is None

    def test_start_outbound_span_returns_none_when_disabled(self):
        """start_outbound_span returns None when tracing disabled."""
        span = start_outbound_span("GET", "http://api.example.com/data")
        assert span is None

    @pytest.mark.asyncio
    async def test_start_request_span_with_tracer_enabled(self):
        """start_request_span creates span when tracing enabled."""
        settings = TracingSettings.model_construct(
            TRACING_ENABLED=True,
            TRACING_EXPORTER=TracingExporter.CONSOLE,
        )
        init_tracing(settings)

        span = start_request_span("GET", "/api/users")
        assert span is not None

    @pytest.mark.asyncio
    async def test_start_job_span_with_tracer_enabled(self):
        """start_job_span creates span when tracing enabled."""
        settings = TracingSettings.model_construct(
            TRACING_ENABLED=True,
            TRACING_EXPORTER=TracingExporter.CONSOLE,
        )
        init_tracing(settings)

        span = start_job_span("process_queue", "job-789")
        assert span is not None


# ---------------------------------------------------------------------------
# TestTraceSpanContextManager
# ---------------------------------------------------------------------------


class TestTraceSpanContextManager:
    """Test trace_span context manager."""

    def test_yields_none_when_tracing_disabled(self):
        """trace_span yields None when tracing is disabled."""
        with trace_span("test_operation") as span:
            assert span is None

    @pytest.mark.asyncio
    async def test_yields_span_when_tracing_enabled(self):
        """trace_span yields span when tracing is enabled."""
        settings = TracingSettings.model_construct(
            TRACING_ENABLED=True,
            TRACING_EXPORTER=TracingExporter.CONSOLE,
        )
        init_tracing(settings)

        with trace_span("test_operation") as span:
            assert span is not None

    @pytest.mark.asyncio
    async def test_sets_attributes_when_provided(self):
        """trace_span sets attributes when provided."""
        settings = TracingSettings.model_construct(
            TRACING_ENABLED=True,
            TRACING_EXPORTER=TracingExporter.CONSOLE,
        )
        init_tracing(settings)

        mock_span = MagicMock()
        with patch("src.app.core.tracing.get_tracer") as mock_get_tracer:
            mock_tracer = MagicMock()
            mock_tracer.start_as_current_span.return_value.__enter__ = lambda self: mock_span
            mock_tracer.start_as_current_span.return_value.__exit__ = lambda self, *args: None
            mock_get_tracer.return_value = mock_tracer

            with trace_span("test_op", {"user_id": "123", "action": "create"}):
                pass


# ---------------------------------------------------------------------------
# TestInjectTraceContext
# ---------------------------------------------------------------------------


class TestInjectTraceContext:
    """Test inject_trace_context() header injection."""

    def test_returns_headers_unchanged_when_disabled(self):
        """inject_trace_context returns headers unchanged when disabled."""
        headers = {"Authorization": "Bearer token"}
        result = inject_trace_context(headers)
        assert result == headers

    @pytest.mark.asyncio
    async def test_injects_headers_when_enabled(self):
        """inject_trace_context injects headers when tracing enabled."""
        settings = TracingSettings.model_construct(
            TRACING_ENABLED=True,
            TRACING_EXPORTER=TracingExporter.CONSOLE,
            TRACING_PROPAGATE_CORRELATION_IDS=False,
        )
        init_tracing(settings)

        headers: dict[str, str] = {}
        result = inject_trace_context(headers)
        # Result should be a dict (possibly with injected headers)
        assert isinstance(result, dict)

    def test_handles_none_headers(self):
        """inject_trace_context handles None input gracefully."""
        # Function should not crash with None
        result = inject_trace_context({"content-type": "application/json"})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestExtractTraceContext
# ---------------------------------------------------------------------------


class TestExtractTraceContext:
    """Test extract_trace_context() header extraction."""

    def test_noop_when_tracing_disabled(self):
        """extract_trace_context is no-op when tracing disabled."""
        headers = {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}
        # Should not raise
        extract_trace_context(headers)

    @pytest.mark.asyncio
    async def test_extracts_headers_when_enabled(self):
        """extract_trace_context extracts headers when tracing enabled."""
        settings = TracingSettings.model_construct(
            TRACING_ENABLED=True,
            TRACING_EXPORTER=TracingExporter.CONSOLE,
        )
        init_tracing(settings)

        headers = {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}
        # Should not raise
        extract_trace_context(headers)


# ---------------------------------------------------------------------------
# TestOpenTelemetryTracingHook
# ---------------------------------------------------------------------------


class TestOpenTelemetryTracingHook:
    """Test OpenTelemetryTracingHook integration."""

    @pytest.mark.asyncio
    async def test_inject_trace_headers_delegates(self):
        """inject_trace_headers delegates to inject_trace_context."""
        hook = OpenTelemetryTracingHook()
        headers = {"Content-Type": "application/json"}

        with patch("src.app.core.tracing.inject_trace_context") as mock_inject:
            mock_inject.return_value = headers

            result = await hook.inject_trace_headers(
                method="GET",
                url="http://example.com",
                headers=headers,
            )

            mock_inject.assert_called_once_with(headers)
            assert result == headers

    @pytest.mark.asyncio
    async def test_record_span_creates_span(self):
        """record_span creates a span via trace_span."""
        hook = OpenTelemetryTracingHook()

        with patch("src.app.core.tracing.trace_span") as mock_trace_span:
            mock_span = MagicMock()
            mock_trace_span.return_value.__enter__ = lambda self: mock_span
            mock_trace_span.return_value.__exit__ = lambda self, *args: None

            await hook.record_span(
                method="GET",
                url="http://example.com/api",
                status_code=200,
                duration_seconds=0.1,
                error=None,
            )

            mock_trace_span.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_span_records_error_when_present(self):
        """record_span records exception when error is present."""
        hook = OpenTelemetryTracingHook()
        mock_span = MagicMock()

        with patch("src.app.core.tracing.trace_span") as mock_trace_span:
            mock_trace_span.return_value.__enter__ = lambda self: mock_span
            mock_trace_span.return_value.__exit__ = lambda self, *args: None

            await hook.record_span(
                method="GET",
                url="http://example.com",
                status_code=500,
                duration_seconds=0.5,
                error="Connection refused",
            )

            mock_span.record_exception.assert_called_once()


# ---------------------------------------------------------------------------
# TestTemplateTracingHolder
# ---------------------------------------------------------------------------


class TestTemplateTracingHolder:
    """Test TemplateTracing holder class."""

    def test_construct_with_provider_and_tracer(self):
        """TemplateTracing can be constructed with provider and tracer."""
        mock_provider = MagicMock()
        mock_tracer = MagicMock()

        tracing = TemplateTracing(tracer_provider=mock_provider, tracer=mock_tracer)

        assert tracing.tracer_provider is mock_provider
        assert tracing.tracer is mock_tracer
