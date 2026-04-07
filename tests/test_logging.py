"""Tests for the template logging configuration (Phase 8 Wave 8.1)."""

from __future__ import annotations

import logging

from src.app.core import logger as logger_module
from src.app.core.worker import logging as worker_logging_module
from src.app.middleware.logger_middleware import REQUEST_LOG_CONTEXT_KEYS

# ---------------------------------------------------------------------------
# Standard log shape vocabulary
# ---------------------------------------------------------------------------


class TestRequestLogContextKeys:
    """REQUEST_LOG_CONTEXT_KEYS includes standard API context keys."""

    def test_contains_request_id(self) -> None:
        assert "request_id" in REQUEST_LOG_CONTEXT_KEYS

    def test_contains_correlation_id(self) -> None:
        assert "correlation_id" in REQUEST_LOG_CONTEXT_KEYS

    def test_contains_client_host(self) -> None:
        assert "client_host" in REQUEST_LOG_CONTEXT_KEYS

    def test_contains_status_code(self) -> None:
        assert "status_code" in REQUEST_LOG_CONTEXT_KEYS

    def test_contains_path(self) -> None:
        assert "path" in REQUEST_LOG_CONTEXT_KEYS

    def test_contains_method(self) -> None:
        assert "method" in REQUEST_LOG_CONTEXT_KEYS

    def test_contains_workflow_id(self) -> None:
        assert "workflow_id" in REQUEST_LOG_CONTEXT_KEYS

    def test_contains_provider_event_id(self) -> None:
        assert "provider_event_id" in REQUEST_LOG_CONTEXT_KEYS


class TestJobLogContextKeys:
    """JOB_LOG_CONTEXT_KEYS includes standard worker context keys."""

    def test_contains_job_id(self) -> None:
        assert "job_id" in worker_logging_module.JOB_LOG_CONTEXT_KEYS

    def test_contains_job_name(self) -> None:
        assert "job_name" in worker_logging_module.JOB_LOG_CONTEXT_KEYS

    def test_contains_correlation_id(self) -> None:
        assert "correlation_id" in worker_logging_module.JOB_LOG_CONTEXT_KEYS

    def test_contains_tenant_id(self) -> None:
        assert "tenant_id" in worker_logging_module.JOB_LOG_CONTEXT_KEYS

    def test_contains_workflow_id(self) -> None:
        assert "workflow_id" in worker_logging_module.JOB_LOG_CONTEXT_KEYS

    def test_contains_provider_event_id(self) -> None:
        assert "provider_event_id" in worker_logging_module.JOB_LOG_CONTEXT_KEYS


# ---------------------------------------------------------------------------
# File logging opt-in behavior
# ---------------------------------------------------------------------------


class TestFileLoggingOptIn:
    """File handler is only attached when FILE_LOG_ENABLED is true."""

    def test_file_handler_is_none_by_default(self) -> None:
        """Default FILE_LOG_ENABLED is False, so file_handler should be None."""
        assert logger_module.settings.FILE_LOG_ENABLED is False
        assert logger_module.file_handler is None

    def test_console_handler_always_present(self) -> None:
        assert logger_module.console_handler is not None
        assert isinstance(logger_module.console_handler, logging.StreamHandler)

    def test_root_logger_has_console_handler(self) -> None:
        root = logging.getLogger()
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "StreamHandler" in handler_types

    def test_root_logger_does_not_have_file_handler_by_default(self) -> None:
        root = logging.getLogger()
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "RotatingFileHandler" not in handler_types


# ---------------------------------------------------------------------------
# Handler filter processor factory
# ---------------------------------------------------------------------------


class TestHandlerFilterProcessor:
    """_build_handler_filter returns a processor that strips excluded keys."""

    def test_strips_excluded_keys(self) -> None:
        proc = logger_module._build_handler_filter(
            include_request_id=False,
            include_correlation_id=True,
            include_path=False,
            include_method=True,
            include_client_host=False,
            include_status_code=False,
        )
        event_dict = {
            "event": "test",
            "request_id": "req-1",
            "correlation_id": "corr-1",
            "path": "/api/v1/test",
            "method": "GET",
            "client_host": "127.0.0.1",
            "status_code": 200,
        }
        result = proc(None, None, event_dict)
        assert "request_id" not in result
        assert result["correlation_id"] == "corr-1"
        assert "path" not in result
        assert result["method"] == "GET"
        assert "client_host" not in result
        assert "status_code" not in result

    def test_keeps_all_when_all_included(self) -> None:
        proc = logger_module._build_handler_filter(
            include_request_id=True,
            include_correlation_id=True,
            include_path=True,
            include_method=True,
            include_client_host=True,
            include_status_code=True,
        )
        event_dict = {
            "event": "test",
            "request_id": "req-1",
            "correlation_id": "corr-1",
            "path": "/test",
            "method": "POST",
            "client_host": "10.0.0.1",
            "status_code": 201,
        }
        result = proc(None, None, event_dict)
        assert result["request_id"] == "req-1"
        assert result["correlation_id"] == "corr-1"
        assert result["path"] == "/test"
        assert result["method"] == "POST"
        assert result["client_host"] == "10.0.0.1"
        assert result["status_code"] == 201

    def test_preserves_non_filterable_keys(self) -> None:
        proc = logger_module._build_handler_filter(
            include_request_id=False,
            include_correlation_id=False,
            include_path=False,
            include_method=False,
            include_client_host=False,
            include_status_code=False,
        )
        event_dict = {
            "event": "test",
            "custom_key": "custom_value",
            "request_id": "req-1",
        }
        result = proc(None, None, event_dict)
        assert result["event"] == "test"
        assert result["custom_key"] == "custom_value"
        assert "request_id" not in result


# ---------------------------------------------------------------------------
# Worker job context: workflow_id and provider_event_id
# ---------------------------------------------------------------------------


class TestBuildJobLogContextNewKeys:
    """build_job_log_context extracts workflow_id and provider_event_id."""

    def test_extracts_workflow_id_from_envelope(self) -> None:
        class FakeEnvelope:
            workflow_id = "wf-123"
            provider_event_id = None
            correlation_id = None
            retry_count = None
            tenant_context = None
            metadata = None

        ctx = worker_logging_module.build_job_log_context(envelope=FakeEnvelope())
        assert ctx["workflow_id"] == "wf-123"

    def test_extracts_provider_event_id_from_envelope(self) -> None:
        class FakeEnvelope:
            workflow_id = None
            provider_event_id = "evt-456"
            correlation_id = None
            retry_count = None
            tenant_context = None
            metadata = None

        ctx = worker_logging_module.build_job_log_context(envelope=FakeEnvelope())
        assert ctx["provider_event_id"] == "evt-456"

    def test_omits_none_values(self) -> None:
        ctx = worker_logging_module.build_job_log_context()
        assert "workflow_id" not in ctx
        assert "provider_event_id" not in ctx


# ---------------------------------------------------------------------------
# Shared processor chain
# ---------------------------------------------------------------------------


class TestSharedProcessors:
    """SHARED_PROCESSORS contains the expected processors."""

    def test_includes_redaction(self) -> None:
        assert logger_module.redact_sensitive_log_fields in logger_module.SHARED_PROCESSORS

    def test_includes_contextvars_merge(self) -> None:
        import structlog

        assert structlog.contextvars.merge_contextvars in logger_module.SHARED_PROCESSORS

    def test_includes_timestamper(self) -> None:
        assert logger_module.timestamper in logger_module.SHARED_PROCESSORS

    def test_includes_drop_color_message(self) -> None:
        assert logger_module.drop_color_message_key in logger_module.SHARED_PROCESSORS


# ---------------------------------------------------------------------------
# FILTERABLE_CONTEXT_KEYS constant
# ---------------------------------------------------------------------------


class TestFilterableContextKeys:
    """FILTERABLE_CONTEXT_KEYS lists the keys managed by filter processors."""

    def test_contains_expected_keys(self) -> None:
        expected = {"request_id", "correlation_id", "path", "method", "client_host", "status_code"}
        assert set(logger_module.FILTERABLE_CONTEXT_KEYS) == expected


# ---------------------------------------------------------------------------
# Config settings: new fields
# ---------------------------------------------------------------------------


class TestLoggingConfigSettings:
    """New logging settings are present with expected defaults."""

    def test_file_log_enabled_default_false(self) -> None:
        assert logger_module.settings.FILE_LOG_ENABLED is False

    def test_file_log_include_correlation_id_default_true(self) -> None:
        assert logger_module.settings.FILE_LOG_INCLUDE_CORRELATION_ID is True

    def test_console_log_include_correlation_id_default_false(self) -> None:
        assert logger_module.settings.CONSOLE_LOG_INCLUDE_CORRELATION_ID is False

    def test_worker_log_level_default_info(self) -> None:
        from src.app.core.config import LogLevel

        assert logger_module.settings.WORKER_LOG_LEVEL is LogLevel.INFO
