"""Comprehensive regression tests for the Sentry integration module.

Tests cover:
- SentryConfig initialization and release resolution
- SentryEventFilter for events and transactions
- Event scrubbing of sensitive fields
- Traces sampler for different endpoint types
- SDK initialization and shutdown
- Scope helpers for tagging and context
- Capture helpers
- Settings validation
- Public API exports
"""

from __future__ import annotations

from types import ModuleType
from unittest.mock import MagicMock, Mock, patch

import pytest
from pydantic import SecretStr, ValidationError

from src.app.core.config import SentrySettings
from src.app.core.sentry import (
    DEFAULT_SENTRY_SCRUB_FIELDS,
    DEFAULT_SENTRY_SCRUB_SUBSTRINGS,
    SentryConfig,
    SentryEventFilter,
    _build_scrub_field_sets,
    _scrub_event_data,
    capture_sentry_exception,
    capture_sentry_message,
    init_sentry,
    init_sentry_for_worker,
    is_sentry_enabled,
    resolve_sentry_release,
    set_sentry_job_context,
    set_sentry_request_context,
    set_sentry_tags,
    set_sentry_user,
    shutdown_sentry,
    traces_sampler,
)

# ============================================================================
# SentryConfig Tests
# ============================================================================


class TestSentryConfig:
    """Tests for SentryConfig dataclass."""

    def test_from_settings_builds_config_with_correct_values(self) -> None:
        """Test that from_settings() builds config with values from
        SentrySettings."""
        settings = SentrySettings.model_construct(
            SENTRY_ENABLE=True,
            SENTRY_DSN=SecretStr("https://key@sentry.io/project"),
            SENTRY_ENVIRONMENT="production",
            SENTRY_RELEASE="1.2.3",
            SENTRY_DEBUG=True,
            SENTRY_ATTACH_STACKTRACE=False,
            SENTRY_SEND_DEFAULT_PII=True,
            SENTRY_MAX_BREADCRUMBS=50,
            SENTRY_TRACES_SAMPLE_RATE=0.5,
            SENTRY_PROFILES_SAMPLE_RATE=0.1,
            SENTRY_FLUSH_TIMEOUT_SECONDS=5,
            SENTRY_SERVER_NAME="server-01",
            SENTRY_ERROR_SAMPLE_RATE=0.8,
            SENTRY_IGNORED_EXCEPTIONS=["ValueError", "KeyError"],
            SENTRY_IGNORED_LOGGERS=["urllib3", "requests"],
            SENTRY_SCRUB_FIELDS=["custom_field"],
            SENTRY_SCRUB_REPLACEMENT="***REDACTED***",
        )

        config = SentryConfig.from_settings(settings)

        assert config.enabled is True
        assert config.dsn == "https://key@sentry.io/project"
        assert config.environment == "production"
        assert config.release == "1.2.3"
        assert config.debug is True
        assert config.attach_stacktrace is False
        assert config.send_default_pii is True
        assert config.max_breadcrumbs == 50
        assert config.traces_sample_rate == 0.5
        assert config.profiles_sample_rate == 0.1
        assert config.flush_timeout_seconds == 5
        assert config.server_name == "server-01"
        assert config.error_sample_rate == 0.8
        assert config.ignored_exceptions == ["ValueError", "KeyError"]
        assert config.ignored_loggers == ["urllib3", "requests"]
        assert "custom_field" in config.scrub_fields
        assert config.scrub_replacement == "***REDACTED***"

    def test_from_settings_with_none_dsn(self) -> None:
        """Test that from_settings() handles None DSN."""
        settings = SentrySettings.model_construct(
            SENTRY_ENABLE=False,
            SENTRY_DSN=None,
        )

        config = SentryConfig.from_settings(settings)

        assert config.dsn is None
        assert config.enabled is False

    def test_resolve_sentry_release_without_prefix(self) -> None:
        """Test release resolution without prefix."""
        settings = SentrySettings.model_construct(
            SENTRY_RELEASE="1.0.0",
            SENTRY_RELEASE_PREFIX="",
        )

        release = resolve_sentry_release(settings)

        assert release == "1.0.0"

    def test_resolve_sentry_release_with_prefix(self) -> None:
        """Test release resolution with prefix namespacing."""
        settings = SentrySettings.model_construct(
            SENTRY_RELEASE="1.0.0",
            SENTRY_RELEASE_PREFIX="my-service",
        )

        release = resolve_sentry_release(settings)

        assert release == "my-service@1.0.0"

    def test_resolve_sentry_release_when_none(self) -> None:
        """Test release resolution when release is None."""
        settings = SentrySettings.model_construct(
            SENTRY_RELEASE=None,
            SENTRY_RELEASE_PREFIX="my-service",
        )

        release = resolve_sentry_release(settings)

        assert release is None


# ============================================================================
# SentryEventFilter Tests
# ============================================================================


class TestSentryEventFilter:
    """Tests for SentryEventFilter class."""

    @pytest.fixture
    def config(self) -> SentryConfig:
        """Provide a basic SentryConfig for testing."""
        return SentryConfig(
            enabled=True,
            dsn="https://key@sentry.io/project",
            environment="test",
            release="1.0.0",
            debug=False,
            attach_stacktrace=True,
            send_default_pii=False,
            max_breadcrumbs=100,
            traces_sample_rate=1.0,
            profiles_sample_rate=0.0,
            flush_timeout_seconds=2,
            server_name=None,
            error_sample_rate=1.0,
            health_endpoint_sample_rate=0.0,
            webhook_sample_rate=None,
            worker_sample_rate=None,
            ignored_exceptions=["ValueError"],
            ignored_loggers=["test_logger"],
            scrub_fields={"password", "secret"},
        )

    def test_before_send_drops_events_for_ignored_exception_types(
        self, config: SentryConfig
    ) -> None:
        """Test that before_send() drops events for ignored exception types."""
        event_filter = SentryEventFilter(config)

        event = {"message": "test error"}
        hint = {"exc_info": (ValueError, ValueError("test"), None)}

        result = event_filter.before_send(event, hint)

        assert result is None

    def test_before_send_passes_non_ignored_exceptions(
        self, config: SentryConfig
    ) -> None:
        """Test that before_send() passes through non-ignored exceptions."""
        event_filter = SentryEventFilter(config)

        event = {"message": "test error"}
        hint = {"exc_info": (TypeError, TypeError("test"), None)}

        result = event_filter.before_send(event, hint)

        assert result is not None
        assert result["message"] == "test error"

    def test_before_send_drops_events_for_ignored_loggers(
        self, config: SentryConfig
    ) -> None:
        """Test that before_send() drops events for ignored loggers."""
        event_filter = SentryEventFilter(config)

        event = {"logger": "test_logger", "message": "test"}
        hint = {}

        result = event_filter.before_send(event, hint)

        assert result is None

    def test_before_send_passes_non_ignored_loggers(
        self, config: SentryConfig
    ) -> None:
        """Test that before_send() passes through non-ignored loggers."""
        event_filter = SentryEventFilter(config)

        event = {"logger": "app.logger", "message": "test"}
        hint = {}

        result = event_filter.before_send(event, hint)

        assert result is not None

    @patch("src.app.core.sentry.get_current_request_id")
    @patch("src.app.core.sentry.get_current_correlation_id")
    def test_before_send_injects_request_id_and_correlation_id_tags(
        self,
        mock_corr_id: MagicMock,
        mock_req_id: MagicMock,
        config: SentryConfig,
    ) -> None:
        """Test that before_send() injects request_id and correlation_id
        tags."""
        mock_req_id.return_value = "req-123"
        mock_corr_id.return_value = "corr-456"

        event_filter = SentryEventFilter(config)
        event = {"message": "test"}
        hint = {}

        result = event_filter.before_send(event, hint)

        assert result is not None
        assert result["tags"]["request_id"] == "req-123"
        assert result["tags"]["correlation_id"] == "corr-456"

    @patch("src.app.core.sentry.get_current_request_id")
    @patch("src.app.core.sentry.get_current_correlation_id")
    def test_before_send_transaction_injects_context_tags(
        self,
        mock_corr_id: MagicMock,
        mock_req_id: MagicMock,
        config: SentryConfig,
    ) -> None:
        """Test that before_send_transaction() injects context tags."""
        mock_req_id.return_value = "req-789"
        mock_corr_id.return_value = "corr-789"

        event_filter = SentryEventFilter(config)
        event = {"contexts": {"trace": {}}}
        hint = {}

        result = event_filter.before_send_transaction(event, hint)

        assert result is not None
        assert result["tags"]["request_id"] == "req-789"
        assert result["tags"]["correlation_id"] == "corr-789"

    def test_before_send_scrubs_sensitive_fields(self, config: SentryConfig) -> None:
        """Test that before_send() scrubs sensitive fields."""
        event_filter = SentryEventFilter(config)

        event = {
            "request": {
                "headers": {
                    "password": "secret123",
                    "username": "john_doe",
                }
            }
        }
        hint = {}

        result = event_filter.before_send(event, hint)

        assert result is not None
        assert result["request"]["headers"]["password"] == "[Filtered]"
        assert result["request"]["headers"]["username"] == "john_doe"


# ============================================================================
# Event Scrubbing Tests
# ============================================================================


class TestEventScrubbing:
    """Tests for event scrubbing functions."""

    def test_scrub_event_data_replaces_sensitive_field_values(self) -> None:
        """Test that _scrub_event_data() replaces sensitive field values."""
        exact_fields = {"password"}
        substring_fields = ("secret",)

        data = {"password": "my_secret", "username": "john"}

        result = _scrub_event_data(
            data,
            exact_fields=exact_fields,
            substring_fields=substring_fields,
            replacement="[REDACTED]",
        )

        assert result["password"] == "[REDACTED]"
        assert result["username"] == "john"

    def test_scrub_event_data_leaves_non_sensitive_fields_alone(self) -> None:
        """Test that _scrub_event_data() leaves non-sensitive fields alone."""
        exact_fields = {"password"}
        substring_fields = ()

        data = {"username": "john", "email": "john@example.com"}

        result = _scrub_event_data(
            data,
            exact_fields=exact_fields,
            substring_fields=substring_fields,
            replacement="[REDACTED]",
        )

        assert result["username"] == "john"
        assert result["email"] == "john@example.com"

    def test_scrub_event_data_recurses_into_nested_dicts(self) -> None:
        """Test that _scrub_event_data() recursively scrubs nested dicts."""
        exact_fields = {"apikey"}  # normalized form (underscores stripped)
        substring_fields = ()

        data = {
            "user": {"api_key": "secret123", "name": "John"},
            "metadata": {"api_key": "secret456"},
        }

        result = _scrub_event_data(
            data,
            exact_fields=exact_fields,
            substring_fields=substring_fields,
            replacement="[X]",
        )

        assert result["user"]["api_key"] == "[X]"
        assert result["user"]["name"] == "John"
        assert result["metadata"]["api_key"] == "[X]"

    def test_scrub_event_data_recurses_into_lists(self) -> None:
        """Test that _scrub_event_data() recursively scrubs lists."""
        exact_fields = {"token"}
        substring_fields = ()

        data = {
            "items": [
                {"token": "tok1", "id": 1},
                {"token": "tok2", "id": 2},
            ]
        }

        result = _scrub_event_data(
            data,
            exact_fields=exact_fields,
            substring_fields=substring_fields,
            replacement="***",
        )

        assert result["items"][0]["token"] == "***"
        assert result["items"][0]["id"] == 1
        assert result["items"][1]["token"] == "***"

    def test_scrub_event_data_recurses_into_tuples(self) -> None:
        """Test that _scrub_event_data() recursively scrubs tuples."""
        exact_fields = {"secret"}
        substring_fields = ()

        data = {
            "values": (
                {"secret": "val1", "id": 1},
                {"secret": "val2", "id": 2},
            )
        }

        result = _scrub_event_data(
            data,
            exact_fields=exact_fields,
            substring_fields=substring_fields,
            replacement="---",
        )

        assert isinstance(result["values"], tuple)
        assert result["values"][0]["secret"] == "---"
        assert result["values"][1]["secret"] == "---"

    def test_scrub_event_data_case_insensitive_field_matching(self) -> None:
        """Test that _scrub_event_data() does case-insensitive matching."""
        exact_fields = {"password"}
        substring_fields = ()

        data = {
            "PASSWORD": "secret1",
            "PaSsWoRd": "secret2",
            "password": "secret3",
        }

        result = _scrub_event_data(
            data,
            exact_fields=exact_fields,
            substring_fields=substring_fields,
            replacement="[X]",
        )

        assert result["PASSWORD"] == "[X]"
        assert result["PaSsWoRd"] == "[X]"
        assert result["password"] == "[X]"

    def test_scrub_event_data_substring_matching(self) -> None:
        """Test that _scrub_event_data() matches substring patterns."""
        exact_fields = set()
        substring_fields = ("password", "token")

        data = {
            "user_password": "secret1",
            "password_hash": "secret2",
            "api_token": "secret3",
            "token_value": "secret4",
            "username": "john",
        }

        result = _scrub_event_data(
            data,
            exact_fields=exact_fields,
            substring_fields=substring_fields,
            replacement="[X]",
        )

        assert result["user_password"] == "[X]"
        assert result["password_hash"] == "[X]"
        assert result["api_token"] == "[X]"
        assert result["token_value"] == "[X]"
        assert result["username"] == "john"

    def test_build_scrub_field_sets_returns_normalised_fields(self) -> None:
        """Test that _build_scrub_field_sets() returns normalised field
        sets."""
        scrub_fields = {"password", "API_KEY", "private-key"}

        exact_fields, substring_fields = _build_scrub_field_sets(scrub_fields)

        assert "password" in exact_fields
        assert "apikey" in exact_fields
        assert "privatekey" in exact_fields
        assert substring_fields == DEFAULT_SENTRY_SCRUB_SUBSTRINGS


# ============================================================================
# Traces Sampler Tests
# ============================================================================


class TestTracesSampler:
    """Tests for traces_sampler function."""

    @pytest.fixture
    def config(self) -> SentryConfig:
        """Provide a SentryConfig for sampler testing."""
        return SentryConfig(
            enabled=True,
            dsn="https://key@sentry.io/project",
            environment="test",
            release="1.0.0",
            debug=False,
            attach_stacktrace=True,
            send_default_pii=False,
            max_breadcrumbs=100,
            traces_sample_rate=0.5,
            profiles_sample_rate=0.0,
            flush_timeout_seconds=2,
            server_name=None,
            error_sample_rate=1.0,
            health_endpoint_sample_rate=0.1,
            webhook_sample_rate=0.8,
            worker_sample_rate=None,
        )

    def test_health_endpoints_get_health_sample_rate(
        self, config: SentryConfig
    ) -> None:
        """Test that health endpoints use health sample rate."""
        context = {
            "transaction_context": {"name": "GET /health"},
        }

        rate = traces_sampler(context, config)

        assert rate == config.health_endpoint_sample_rate

    def test_readiness_endpoints_get_health_sample_rate(
        self, config: SentryConfig
    ) -> None:
        """Test that readiness endpoints use health sample rate."""
        for endpoint in ["/ready", "/readiness", "/liveness", "/status"]:
            context = {
                "transaction_context": {"name": f"GET {endpoint}"},
            }

            rate = traces_sampler(context, config)

            assert rate == config.health_endpoint_sample_rate

    def test_webhook_endpoints_get_webhook_sample_rate(
        self, config: SentryConfig
    ) -> None:
        """Test that webhook endpoints use webhook sample rate when
        configured."""
        context = {
            "transaction_context": {"name": "POST /webhook/stripe"},
        }

        rate = traces_sampler(context, config)

        assert rate == config.webhook_sample_rate

    def test_webhook_endpoints_get_default_rate_when_none(
        self, config: SentryConfig
    ) -> None:
        """Test that webhook endpoints use default rate when webhook_sample_rate
        is None."""
        config.webhook_sample_rate = None
        context = {
            "transaction_context": {"name": "POST /webhook/stripe"},
        }

        rate = traces_sampler(context, config)

        assert rate == config.traces_sample_rate

    def test_other_endpoints_get_default_rate(self, config: SentryConfig) -> None:
        """Test that other endpoints use default traces sample rate."""
        context = {
            "transaction_context": {"name": "GET /api/users"},
        }

        rate = traces_sampler(context, config)

        assert rate == config.traces_sample_rate

    def test_empty_transaction_context(self, config: SentryConfig) -> None:
        """Test sampler with missing transaction context."""
        context = {}

        rate = traces_sampler(context, config)

        assert rate == config.traces_sample_rate


# ============================================================================
# Init Function Tests
# ============================================================================


class TestInitFunctions:
    """Tests for SDK initialization functions."""

    def test_init_sentry_disabled_when_false(self) -> None:
        """Test that init_sentry() does nothing when SENTRY_ENABLE is
        False."""
        settings = SentrySettings.model_construct(SENTRY_ENABLE=False)

        init_sentry(settings)

    def test_init_sentry_calls_sdk_init_when_enabled(self) -> None:
        """Test that init_sentry() calls sentry_sdk.init when enabled."""
        sentry_sdk_module = ModuleType("sentry_sdk")
        sentry_sdk_module.init = Mock()
        mock_scope = Mock()
        sentry_sdk_module.get_current_scope = Mock(return_value=mock_scope)

        fastapi_integration_factory = Mock(return_value=object())
        logging_integration_factory = Mock(return_value=object())
        arq_integration_factory = Mock(return_value=object())

        sentry_integrations_module = ModuleType("sentry_sdk.integrations")
        sentry_fastapi_module = ModuleType("sentry_sdk.integrations.fastapi")
        sentry_fastapi_module.FastApiIntegration = fastapi_integration_factory
        sentry_logging_module = ModuleType("sentry_sdk.integrations.logging")
        sentry_logging_module.LoggingIntegration = logging_integration_factory
        sentry_arq_module = ModuleType("sentry_sdk.integrations.arq")
        sentry_arq_module.ArqIntegration = arq_integration_factory

        settings = SentrySettings.model_construct(
            SENTRY_ENABLE=True,
            SENTRY_DSN=SecretStr("https://key@sentry.io/project"),
            SENTRY_ENVIRONMENT="production",
            SENTRY_RELEASE="1.0.0",
        )

        with patch.dict(
            "sys.modules",
            {
                "sentry_sdk": sentry_sdk_module,
                "sentry_sdk.integrations": sentry_integrations_module,
                "sentry_sdk.integrations.fastapi": sentry_fastapi_module,
                "sentry_sdk.integrations.logging": sentry_logging_module,
                "sentry_sdk.integrations.arq": sentry_arq_module,
            },
        ):
            init_sentry(settings)

        sentry_sdk_module.init.assert_called_once()
        call_kwargs = sentry_sdk_module.init.call_args[1]
        assert call_kwargs["dsn"] == "https://key@sentry.io/project"
        assert call_kwargs["environment"] == "production"

    def test_init_sentry_handles_missing_sentry_sdk(self) -> None:
        """Test that init_sentry() handles missing sentry_sdk gracefully."""
        settings = SentrySettings.model_construct(SENTRY_ENABLE=True)

        with patch("src.app.core.sentry.logger"):
            with patch.dict("sys.modules", {"sentry_sdk": None}):
                init_sentry(settings)

    def test_init_sentry_sets_api_process_type_tag(self) -> None:
        """Test that init_sentry() sets process_type tag to 'api'."""
        sentry_sdk_module = ModuleType("sentry_sdk")
        sentry_sdk_module.init = Mock()
        mock_scope = Mock()
        sentry_sdk_module.get_current_scope = Mock(return_value=mock_scope)

        fastapi_integration_factory = Mock(return_value=object())
        logging_integration_factory = Mock(return_value=object())

        sentry_integrations_module = ModuleType("sentry_sdk.integrations")
        sentry_fastapi_module = ModuleType("sentry_sdk.integrations.fastapi")
        sentry_fastapi_module.FastApiIntegration = fastapi_integration_factory
        sentry_logging_module = ModuleType("sentry_sdk.integrations.logging")
        sentry_logging_module.LoggingIntegration = logging_integration_factory
        sentry_arq_module = ModuleType("sentry_sdk.integrations.arq")
        sentry_arq_module.ArqIntegration = Mock(return_value=object())

        settings = SentrySettings.model_construct(
            SENTRY_ENABLE=True,
            SENTRY_DSN=SecretStr("https://key@sentry.io/project"),
        )

        with patch.dict(
            "sys.modules",
            {
                "sentry_sdk": sentry_sdk_module,
                "sentry_sdk.integrations": sentry_integrations_module,
                "sentry_sdk.integrations.fastapi": sentry_fastapi_module,
                "sentry_sdk.integrations.logging": sentry_logging_module,
                "sentry_sdk.integrations.arq": sentry_arq_module,
            },
        ):
            init_sentry(settings)

        mock_scope.set_tag.assert_called_with("process_type", "api")

    def test_init_sentry_for_worker_disabled_when_false(self) -> None:
        """Test that init_sentry_for_worker() does nothing when disabled."""
        settings = SentrySettings.model_construct(SENTRY_ENABLE=False)

        init_sentry_for_worker(settings)

    def test_init_sentry_for_worker_sets_worker_process_type_tag(self) -> None:
        """Test that init_sentry_for_worker() sets process_type to 'worker'."""
        sentry_sdk_module = ModuleType("sentry_sdk")
        sentry_sdk_module.init = Mock()
        mock_scope = Mock()
        sentry_sdk_module.get_current_scope = Mock(return_value=mock_scope)

        logging_integration_factory = Mock(return_value=object())
        arq_integration_factory = Mock(return_value=object())

        sentry_integrations_module = ModuleType("sentry_sdk.integrations")
        sentry_logging_module = ModuleType("sentry_sdk.integrations.logging")
        sentry_logging_module.LoggingIntegration = logging_integration_factory
        sentry_arq_module = ModuleType("sentry_sdk.integrations.arq")
        sentry_arq_module.ArqIntegration = arq_integration_factory

        settings = SentrySettings.model_construct(
            SENTRY_ENABLE=True,
            SENTRY_DSN=SecretStr("https://key@sentry.io/project"),
        )

        with patch.dict(
            "sys.modules",
            {
                "sentry_sdk": sentry_sdk_module,
                "sentry_sdk.integrations": sentry_integrations_module,
                "sentry_sdk.integrations.logging": sentry_logging_module,
                "sentry_sdk.integrations.arq": sentry_arq_module,
            },
        ):
            init_sentry_for_worker(settings)

        mock_scope.set_tag.assert_called_with("process_type", "worker")

    def test_init_sentry_for_worker_uses_worker_sample_rate(self) -> None:
        """Test that init_sentry_for_worker() uses worker_sample_rate."""
        sentry_sdk_module = ModuleType("sentry_sdk")
        sentry_sdk_module.init = Mock()
        mock_scope = Mock()
        sentry_sdk_module.get_current_scope = Mock(return_value=mock_scope)

        logging_integration_factory = Mock(return_value=object())
        arq_integration_factory = Mock(return_value=object())

        sentry_integrations_module = ModuleType("sentry_sdk.integrations")
        sentry_logging_module = ModuleType("sentry_sdk.integrations.logging")
        sentry_logging_module.LoggingIntegration = logging_integration_factory
        sentry_arq_module = ModuleType("sentry_sdk.integrations.arq")
        sentry_arq_module.ArqIntegration = arq_integration_factory

        settings = SentrySettings.model_construct(
            SENTRY_ENABLE=True,
            SENTRY_DSN=SecretStr("https://key@sentry.io/project"),
            SENTRY_TRACES_SAMPLE_RATE=0.5,
            SENTRY_WORKER_SAMPLE_RATE=0.1,
        )

        with patch.dict(
            "sys.modules",
            {
                "sentry_sdk": sentry_sdk_module,
                "sentry_sdk.integrations": sentry_integrations_module,
                "sentry_sdk.integrations.logging": sentry_logging_module,
                "sentry_sdk.integrations.arq": sentry_arq_module,
            },
        ):
            init_sentry_for_worker(settings)

        call_kwargs = sentry_sdk_module.init.call_args[1]
        assert call_kwargs["traces_sample_rate"] == 0.1

    def test_init_sentry_for_worker_falls_back_to_traces_sample_rate(
        self,
    ) -> None:
        """Test that init_sentry_for_worker() falls back to default rate
        when None."""
        sentry_sdk_module = ModuleType("sentry_sdk")
        sentry_sdk_module.init = Mock()
        mock_scope = Mock()
        sentry_sdk_module.get_current_scope = Mock(return_value=mock_scope)

        logging_integration_factory = Mock(return_value=object())
        arq_integration_factory = Mock(return_value=object())

        sentry_integrations_module = ModuleType("sentry_sdk.integrations")
        sentry_logging_module = ModuleType("sentry_sdk.integrations.logging")
        sentry_logging_module.LoggingIntegration = logging_integration_factory
        sentry_arq_module = ModuleType("sentry_sdk.integrations.arq")
        sentry_arq_module.ArqIntegration = arq_integration_factory

        settings = SentrySettings.model_construct(
            SENTRY_ENABLE=True,
            SENTRY_DSN=SecretStr("https://key@sentry.io/project"),
            SENTRY_TRACES_SAMPLE_RATE=0.5,
            SENTRY_WORKER_SAMPLE_RATE=None,
        )

        with patch.dict(
            "sys.modules",
            {
                "sentry_sdk": sentry_sdk_module,
                "sentry_sdk.integrations": sentry_integrations_module,
                "sentry_sdk.integrations.logging": sentry_logging_module,
                "sentry_sdk.integrations.arq": sentry_arq_module,
            },
        ):
            init_sentry_for_worker(settings)

        call_kwargs = sentry_sdk_module.init.call_args[1]
        assert call_kwargs["traces_sample_rate"] == 0.5


# ============================================================================
# Shutdown Tests
# ============================================================================


class TestShutdown:
    """Tests for shutdown functions."""

    @pytest.mark.asyncio
    async def test_shutdown_sentry_calls_flush(self) -> None:
        """Test that shutdown_sentry() calls flush with correct timeout."""
        sentry_sdk_module = ModuleType("sentry_sdk")
        sentry_sdk_module.flush = Mock()

        settings = SentrySettings.model_construct(
            SENTRY_ENABLE=True,
            SENTRY_FLUSH_TIMEOUT_SECONDS=5,
        )

        with patch.dict("sys.modules", {"sentry_sdk": sentry_sdk_module}):
            await shutdown_sentry(settings)

        sentry_sdk_module.flush.assert_called_once_with(timeout=5)

    @pytest.mark.asyncio
    async def test_shutdown_sentry_disabled_does_nothing(self) -> None:
        """Test that shutdown_sentry() does nothing when disabled."""
        settings = SentrySettings.model_construct(SENTRY_ENABLE=False)

        await shutdown_sentry(settings)

    @pytest.mark.asyncio
    async def test_shutdown_sentry_handles_missing_sentry_sdk(self) -> None:
        """Test that shutdown_sentry() handles missing sentry_sdk
        gracefully."""
        settings = SentrySettings.model_construct(SENTRY_ENABLE=True)

        with patch.dict("sys.modules", {"sentry_sdk": None}):
            await shutdown_sentry(settings)


# ============================================================================
# Scope Helper Tests
# ============================================================================


class TestScopeHelpers:
    """Tests for scope context helper functions."""

    def test_set_sentry_tags_sets_tags_on_scope(self) -> None:
        """Test that set_sentry_tags() sets tags on scope."""
        sentry_sdk_module = ModuleType("sentry_sdk")
        mock_scope = Mock()
        sentry_sdk_module.get_current_scope = Mock(return_value=mock_scope)
        mock_client = Mock()
        mock_client.is_active = Mock(return_value=True)
        sentry_sdk_module.get_client = Mock(return_value=mock_client)

        tags = {"env": "prod", "service": "api"}

        with patch.dict("sys.modules", {"sentry_sdk": sentry_sdk_module}):
            set_sentry_tags(tags)

        assert mock_scope.set_tag.call_count == 2
        mock_scope.set_tag.assert_any_call("env", "prod")
        mock_scope.set_tag.assert_any_call("service", "api")

    def test_set_sentry_tags_noop_when_disabled(self) -> None:
        """Test that set_sentry_tags() is a no-op when disabled."""
        with patch(
            "src.app.core.sentry.is_sentry_enabled", return_value=False
        ):
            set_sentry_tags({"key": "value"})

    def test_set_sentry_user_sets_user_data(self) -> None:
        """Test that set_sentry_user() sets user data and tenant tags."""
        sentry_sdk_module = ModuleType("sentry_sdk")
        mock_scope = Mock()
        sentry_sdk_module.get_current_scope = Mock(return_value=mock_scope)
        mock_client = Mock()
        mock_client.is_active = Mock(return_value=True)
        sentry_sdk_module.get_client = Mock(return_value=mock_client)

        with patch.dict("sys.modules", {"sentry_sdk": sentry_sdk_module}):
            set_sentry_user(
                user_id="user-123",
                username="john_doe",
                email="john@example.com",
                tenant_id="tenant-456",
                org_id="org-789",
            )

        mock_scope.set_user.assert_called_once()
        user_data = mock_scope.set_user.call_args[0][0]
        assert user_data["id"] == "user-123"
        assert user_data["username"] == "john_doe"
        assert user_data["email"] == "john@example.com"

        assert mock_scope.set_tag.call_count == 2
        mock_scope.set_tag.assert_any_call("tenant_id", "tenant-456")
        mock_scope.set_tag.assert_any_call("org_id", "org-789")

    def test_set_sentry_user_optional_fields(self) -> None:
        """Test that set_sentry_user() handles optional fields."""
        sentry_sdk_module = ModuleType("sentry_sdk")
        mock_scope = Mock()
        sentry_sdk_module.get_current_scope = Mock(return_value=mock_scope)
        mock_client = Mock()
        mock_client.is_active = Mock(return_value=True)
        sentry_sdk_module.get_client = Mock(return_value=mock_client)

        with patch.dict("sys.modules", {"sentry_sdk": sentry_sdk_module}):
            set_sentry_user(user_id="user-123")

        user_data = mock_scope.set_user.call_args[0][0]
        assert user_data == {"id": "user-123"}
        assert "username" not in user_data
        assert "email" not in user_data

    def test_set_sentry_user_noop_when_disabled(self) -> None:
        """Test that set_sentry_user() is a no-op when disabled."""
        with patch(
            "src.app.core.sentry.is_sentry_enabled", return_value=False
        ):
            set_sentry_user(user_id="user-123")

    def test_set_sentry_request_context_sets_tags(self) -> None:
        """Test that set_sentry_request_context() sets request tags."""
        sentry_sdk_module = ModuleType("sentry_sdk")
        mock_scope = Mock()
        sentry_sdk_module.get_current_scope = Mock(return_value=mock_scope)
        mock_client = Mock()
        mock_client.is_active = Mock(return_value=True)
        sentry_sdk_module.get_client = Mock(return_value=mock_client)

        with patch.dict("sys.modules", {"sentry_sdk": sentry_sdk_module}):
            set_sentry_request_context(
                request_id="req-123",
                correlation_id="corr-456",
            )

        assert mock_scope.set_tag.call_count == 2
        mock_scope.set_tag.assert_any_call("request_id", "req-123")
        mock_scope.set_tag.assert_any_call("correlation_id", "corr-456")

    def test_set_sentry_request_context_noop_when_disabled(self) -> None:
        """Test that set_sentry_request_context() is a no-op when
        disabled."""
        with patch(
            "src.app.core.sentry.is_sentry_enabled", return_value=False
        ):
            set_sentry_request_context(request_id="req-123")

    def test_set_sentry_job_context_sets_job_data(self) -> None:
        """Test that set_sentry_job_context() sets job context and tags."""
        sentry_sdk_module = ModuleType("sentry_sdk")
        mock_scope = Mock()
        sentry_sdk_module.get_current_scope = Mock(return_value=mock_scope)
        mock_client = Mock()
        mock_client.is_active = Mock(return_value=True)
        sentry_sdk_module.get_client = Mock(return_value=mock_client)

        with patch.dict("sys.modules", {"sentry_sdk": sentry_sdk_module}):
            set_sentry_job_context(
                job_id="job-123",
                job_name="send_email",
                queue_name="default",
                correlation_id="corr-789",
                retry_count=2,
            )

        mock_scope.set_context.assert_called_once()
        context_name, context_data = mock_scope.set_context.call_args[0]
        assert context_name == "job"
        assert context_data["id"] == "job-123"
        assert context_data["name"] == "send_email"
        assert context_data["queue"] == "default"
        assert context_data["retry_count"] == 2

        mock_scope.set_tag.assert_called_once_with("correlation_id", "corr-789")

    def test_set_sentry_job_context_noop_when_disabled(self) -> None:
        """Test that set_sentry_job_context() is a no-op when disabled."""
        with patch(
            "src.app.core.sentry.is_sentry_enabled", return_value=False
        ):
            set_sentry_job_context(job_id="job-123")


# ============================================================================
# Capture Helper Tests
# ============================================================================


class TestCaptureHelpers:
    """Tests for event capture helper functions."""

    def test_capture_sentry_exception_captures_with_context(self) -> None:
        """Test that capture_sentry_exception() captures with extra
        context."""
        sentry_sdk_module = ModuleType("sentry_sdk")
        mock_scope = Mock()
        sentry_sdk_module.get_current_scope = Mock(return_value=mock_scope)
        sentry_sdk_module.capture_exception = Mock(return_value="event-id-123")
        mock_client = Mock()
        mock_client.is_active = Mock(return_value=True)
        sentry_sdk_module.get_client = Mock(return_value=mock_client)

        error = ValueError("test error")
        extra = {"key": "value"}

        with patch.dict("sys.modules", {"sentry_sdk": sentry_sdk_module}):
            event_id = capture_sentry_exception(error, extra_context=extra)

        assert event_id == "event-id-123"
        mock_scope.set_context.assert_called_once_with("extra", extra)
        sentry_sdk_module.capture_exception.assert_called_once_with(error)

    def test_capture_sentry_exception_without_context(self) -> None:
        """Test that capture_sentry_exception() works without extra
        context."""
        sentry_sdk_module = ModuleType("sentry_sdk")
        mock_scope = Mock()
        sentry_sdk_module.get_current_scope = Mock(return_value=mock_scope)
        sentry_sdk_module.capture_exception = Mock(return_value="event-id-456")
        mock_client = Mock()
        mock_client.is_active = Mock(return_value=True)
        sentry_sdk_module.get_client = Mock(return_value=mock_client)

        error = ValueError("test error")

        with patch.dict("sys.modules", {"sentry_sdk": sentry_sdk_module}):
            event_id = capture_sentry_exception(error)

        assert event_id == "event-id-456"
        mock_scope.set_context.assert_not_called()

    def test_capture_sentry_exception_returns_none_when_disabled(
        self,
    ) -> None:
        """Test that capture_sentry_exception() returns None when
        disabled."""
        with patch(
            "src.app.core.sentry.is_sentry_enabled", return_value=False
        ):
            error = ValueError("test error")

            event_id = capture_sentry_exception(error)

            assert event_id is None

    def test_capture_sentry_message_captures_with_level(self) -> None:
        """Test that capture_sentry_message() captures with level and
        extra."""
        sentry_sdk_module = ModuleType("sentry_sdk")
        mock_scope = Mock()
        sentry_sdk_module.get_current_scope = Mock(return_value=mock_scope)
        sentry_sdk_module.capture_message = Mock(return_value="event-id-789")
        mock_client = Mock()
        mock_client.is_active = Mock(return_value=True)
        sentry_sdk_module.get_client = Mock(return_value=mock_client)

        extra = {"context": "data"}

        with patch.dict("sys.modules", {"sentry_sdk": sentry_sdk_module}):
            event_id = capture_sentry_message(
                "test message", level="warning", extra=extra
            )

        assert event_id == "event-id-789"
        mock_scope.set_context.assert_called_once_with("extra", extra)
        sentry_sdk_module.capture_message.assert_called_once_with(
            "test message", level="warning"
        )

    def test_capture_sentry_message_returns_none_when_disabled(
        self,
    ) -> None:
        """Test that capture_sentry_message() returns None when disabled."""
        with patch(
            "src.app.core.sentry.is_sentry_enabled", return_value=False
        ):
            event_id = capture_sentry_message("test message")

            assert event_id is None


# ============================================================================
# SentrySettings Validation Tests
# ============================================================================


class TestSentrySettingsValidation:
    """Tests for SentrySettings validation."""

    def test_sentry_settings_default_values(self) -> None:
        """Test that SentrySettings has correct defaults."""
        settings = SentrySettings()

        assert settings.SENTRY_ENABLE is False
        assert settings.SENTRY_DSN is None
        assert settings.SENTRY_ENVIRONMENT == "local"
        assert settings.SENTRY_RELEASE is None
        assert settings.SENTRY_DEBUG is False
        assert settings.SENTRY_ATTACH_STACKTRACE is True
        assert settings.SENTRY_SEND_DEFAULT_PII is False
        assert settings.SENTRY_MAX_BREADCRUMBS == 100
        assert settings.SENTRY_TRACES_SAMPLE_RATE == 1.0
        assert settings.SENTRY_PROFILES_SAMPLE_RATE == 1.0
        assert settings.SENTRY_FLUSH_TIMEOUT_SECONDS == 2
        assert settings.SENTRY_HEALTH_ENDPOINT_SAMPLE_RATE == 0.0

    def test_sentry_settings_requires_dsn_when_enabled(self) -> None:
        """Test that DSN is required when SENTRY_ENABLE is true."""
        with pytest.raises(
            ValidationError,
            match="SENTRY_DSN must be set when SENTRY_ENABLE is true",
        ):
            SentrySettings(
                SENTRY_ENABLE=True,
                SENTRY_DSN=None,
            )

    def test_sentry_settings_allows_none_dsn_when_disabled(self) -> None:
        """Test that DSN can be None when SENTRY_ENABLE is false."""
        settings = SentrySettings.model_construct(
            SENTRY_ENABLE=False,
            SENTRY_DSN=None,
        )

        assert settings.SENTRY_ENABLE is False
        assert settings.SENTRY_DSN is None


# ============================================================================
# Exports and API Surface Tests
# ============================================================================


class TestPublicAPI:
    """Tests for public API exports."""

    def test_all_exports_are_importable(self) -> None:
        """Test that all __all__ names are importable."""
        from src.app.core.sentry import (
            DEFAULT_SENTRY_SCRUB_FIELDS,
            DEFAULT_SENTRY_SCRUB_SUBSTRINGS,
            SentryConfig,
            SentryEventFilter,
            capture_sentry_exception,
            capture_sentry_message,
            init_sentry,
            init_sentry_for_worker,
            resolve_sentry_release,
            set_sentry_job_context,
            set_sentry_request_context,
            set_sentry_tags,
            set_sentry_user,
            shutdown_sentry,
            traces_sampler,
        )

        assert DEFAULT_SENTRY_SCRUB_FIELDS is not None
        assert DEFAULT_SENTRY_SCRUB_SUBSTRINGS is not None
        assert SentryConfig is not None
        assert SentryEventFilter is not None
        assert capture_sentry_exception is not None
        assert capture_sentry_message is not None
        assert init_sentry is not None
        assert init_sentry_for_worker is not None
        assert is_sentry_enabled is not None
        assert resolve_sentry_release is not None
        assert set_sentry_job_context is not None
        assert set_sentry_request_context is not None
        assert set_sentry_tags is not None
        assert set_sentry_user is not None
        assert shutdown_sentry is not None
        assert traces_sampler is not None

    def test_constants_have_correct_values(self) -> None:
        """Test that exported constants have correct values."""
        assert "password" in DEFAULT_SENTRY_SCRUB_FIELDS
        assert "secret" in DEFAULT_SENTRY_SCRUB_FIELDS
        assert "token" in DEFAULT_SENTRY_SCRUB_FIELDS

        assert "password" in DEFAULT_SENTRY_SCRUB_SUBSTRINGS
        assert "secret" in DEFAULT_SENTRY_SCRUB_SUBSTRINGS
        assert "token" in DEFAULT_SENTRY_SCRUB_SUBSTRINGS
