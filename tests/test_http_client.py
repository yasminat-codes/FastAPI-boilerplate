"""Regression tests for the shared outbound HTTP client platform."""

from __future__ import annotations

import base64
import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from src.app.integrations.http_client import (
    IDEMPOTENT_METHODS,
    ApiKeyAuth,
    BasicAuth,
    BearerTokenAuth,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    CustomAuth,
    HttpAuthenticationError,
    HttpAuthorizationError,
    HttpCircuitOpenError,
    HttpClientBadRequestError,
    HttpClientConfig,
    HttpClientError,
    HttpConflictError,
    HttpConnectionError,
    HttpNotFoundError,
    HttpRateLimitError,
    HttpResponseSummary,
    HttpServerError,
    HttpTimeoutError,
    InstrumentationRequestHook,
    InstrumentationResponseHook,
    LoggingRequestHook,
    LoggingResponseHook,
    NonRetryableHttpError,
    RateLimitInfo,
    TemplateHttpClient,
    build_circuit_breaker_config_from_settings,
    build_config_from_settings,
    build_retry_policy_from_settings,
    classify_status_code,
    compute_rate_limit_delay,
    is_retryable_error,
    parse_rate_limit_headers,
    raise_for_status,
    resolve_retry_delay,
    should_retry_method,
)
from src.app.integrations.http_client.client import (
    _build_response_summary,
    _parse_retry_after,
)
from src.app.integrations.http_client.instrumentation import (
    MetricsCollector,
    TracingHook,
)
from src.app.integrations.http_client.retry import HttpRetryPolicy


class TestHttpResponseSummary:
    """Test HttpResponseSummary dataclass."""

    def test_create_with_all_fields(self) -> None:
        summary = HttpResponseSummary(
            status_code=404,
            headers={"content-type": "application/json"},
            reason_phrase="Not Found",
            url="https://api.example.com/users/123",
            method="GET",
        )
        assert summary.status_code == 404
        assert summary.headers == {"content-type": "application/json"}
        assert summary.reason_phrase == "Not Found"
        assert summary.url == "https://api.example.com/users/123"
        assert summary.method == "GET"

    def test_default_values(self) -> None:
        summary = HttpResponseSummary(status_code=200)
        assert summary.status_code == 200
        assert summary.headers == {}
        assert summary.reason_phrase == ""
        assert summary.url == ""
        assert summary.method == ""

    def test_frozen_immutable(self) -> None:
        summary = HttpResponseSummary(status_code=500)
        with pytest.raises(AttributeError):
            summary.status_code = 400  # type: ignore[misc]


class TestExceptionHierarchy:
    """Test exception types and their properties."""

    def test_all_exceptions_inherit_from_http_client_error(self) -> None:
        assert issubclass(HttpTimeoutError, HttpClientError)
        assert issubclass(HttpConnectionError, HttpClientError)
        assert issubclass(HttpServerError, HttpClientError)
        assert issubclass(HttpRateLimitError, HttpClientError)
        assert issubclass(HttpAuthenticationError, HttpClientError)
        assert issubclass(HttpAuthorizationError, HttpClientError)
        assert issubclass(HttpNotFoundError, HttpClientError)
        assert issubclass(HttpConflictError, HttpClientError)
        assert issubclass(HttpClientBadRequestError, HttpClientError)
        assert issubclass(HttpCircuitOpenError, HttpClientError)
        assert issubclass(NonRetryableHttpError, HttpClientError)

    def test_timeout_error_is_retryable(self) -> None:
        error = HttpTimeoutError()
        assert error.is_retryable is True

    def test_connection_error_is_retryable(self) -> None:
        error = HttpConnectionError()
        assert error.is_retryable is True

    def test_server_error_is_retryable(self) -> None:
        error = HttpServerError()
        assert error.is_retryable is True

    def test_rate_limit_error_is_retryable(self) -> None:
        error = HttpRateLimitError()
        assert error.is_retryable is True

    def test_authentication_error_is_not_retryable(self) -> None:
        error = HttpAuthenticationError()
        assert error.is_retryable is False

    def test_authorization_error_is_not_retryable(self) -> None:
        error = HttpAuthorizationError()
        assert error.is_retryable is False

    def test_not_found_error_is_not_retryable(self) -> None:
        error = HttpNotFoundError()
        assert error.is_retryable is False

    def test_conflict_error_is_not_retryable(self) -> None:
        error = HttpConflictError()
        assert error.is_retryable is False

    def test_bad_request_error_is_not_retryable(self) -> None:
        error = HttpClientBadRequestError()
        assert error.is_retryable is False

    def test_rate_limit_error_stores_retry_after(self) -> None:
        error = HttpRateLimitError(retry_after_seconds=60.0)
        assert error.retry_after_seconds == 60.0

    def test_rate_limit_error_retry_after_can_be_none(self) -> None:
        error = HttpRateLimitError()
        assert error.retry_after_seconds is None

    def test_circuit_open_error_is_retryable(self) -> None:
        error = HttpCircuitOpenError()
        assert error.is_retryable is True

    def test_non_retryable_error_is_not_retryable(self) -> None:
        error = NonRetryableHttpError("Test")
        assert error.is_retryable is False

    def test_exception_stores_message(self) -> None:
        error = HttpClientError("Custom error message")
        assert error.message == "Custom error message"

    def test_exception_stores_response_summary(self) -> None:
        summary = HttpResponseSummary(status_code=404)
        error = HttpClientError("Not found", response_summary=summary)
        assert error.response_summary == summary

    def test_exception_stores_error_code(self) -> None:
        error = HttpClientError("Error", error_code="ERR_001")
        assert error.error_code == "ERR_001"


class TestClassifyStatusCode:
    """Test status code to exception mapping."""

    def test_400_maps_to_bad_request(self) -> None:
        exc_class = classify_status_code(400)
        assert exc_class is HttpClientBadRequestError

    def test_401_maps_to_authentication_error(self) -> None:
        exc_class = classify_status_code(401)
        assert exc_class is HttpAuthenticationError

    def test_403_maps_to_authorization_error(self) -> None:
        exc_class = classify_status_code(403)
        assert exc_class is HttpAuthorizationError

    def test_404_maps_to_not_found(self) -> None:
        exc_class = classify_status_code(404)
        assert exc_class is HttpNotFoundError

    def test_409_maps_to_conflict(self) -> None:
        exc_class = classify_status_code(409)
        assert exc_class is HttpConflictError

    def test_429_maps_to_rate_limit(self) -> None:
        exc_class = classify_status_code(429)
        assert exc_class is HttpRateLimitError

    def test_500_maps_to_server_error(self) -> None:
        exc_class = classify_status_code(500)
        assert exc_class is HttpServerError

    def test_502_maps_to_server_error(self) -> None:
        exc_class = classify_status_code(502)
        assert exc_class is HttpServerError

    def test_503_maps_to_server_error(self) -> None:
        exc_class = classify_status_code(503)
        assert exc_class is HttpServerError

    def test_504_maps_to_server_error(self) -> None:
        exc_class = classify_status_code(504)
        assert exc_class is HttpServerError

    def test_422_maps_to_non_retryable_error(self) -> None:
        exc_class = classify_status_code(422)
        assert exc_class is NonRetryableHttpError

    def test_200_maps_to_http_client_error(self) -> None:
        exc_class = classify_status_code(200)
        assert exc_class is HttpClientError

    def test_3xx_codes_map_to_base_error(self) -> None:
        exc_class = classify_status_code(301)
        assert exc_class is HttpClientError

    def test_4xx_non_specific_maps_to_non_retryable(self) -> None:
        exc_class = classify_status_code(418)
        assert exc_class is NonRetryableHttpError


class TestRaiseForStatus:
    """Test raise_for_status helper function."""

    def test_successful_response_does_not_raise(self) -> None:
        response = httpx.Response(200)
        raise_for_status(response)

    def test_not_found_raises_correct_exception(self) -> None:
        response = httpx.Response(404, request=httpx.Request("GET", "https://api.example.com/users/123"))
        with pytest.raises(HttpNotFoundError) as exc_info:
            raise_for_status(response)
        assert "404" in str(exc_info.value)

    def test_rate_limit_raises_with_retry_after(self) -> None:
        response = httpx.Response(
            429,
            headers={"Retry-After": "60"},
            request=httpx.Request("GET", "https://api.example.com/quota"),
        )
        with pytest.raises(HttpRateLimitError) as exc_info:
            raise_for_status(response)
        assert exc_info.value.retry_after_seconds == 60.0

    def test_server_error_raises_correct_exception(self) -> None:
        response = httpx.Response(500, request=httpx.Request("GET", "https://api.example.com/status"))
        with pytest.raises(HttpServerError) as exc_info:
            raise_for_status(response)
        assert "500" in str(exc_info.value)

    def test_authentication_error_raises_correct_exception(self) -> None:
        response = httpx.Response(401, request=httpx.Request("GET", "https://api.example.com/auth"))
        with pytest.raises(HttpAuthenticationError) as exc_info:
            raise_for_status(response)
        assert "401" in str(exc_info.value)

    def test_authorization_error_raises_correct_exception(self) -> None:
        response = httpx.Response(403, request=httpx.Request("GET", "https://api.example.com/admin"))
        with pytest.raises(HttpAuthorizationError) as exc_info:
            raise_for_status(response)
        assert "403" in str(exc_info.value)

    def test_response_summary_includes_url(self) -> None:
        response = httpx.Response(404, request=httpx.Request("GET", "https://api.example.com/users/123"))
        with pytest.raises(HttpNotFoundError) as exc_info:
            raise_for_status(response)
        assert exc_info.value.response_summary is not None
        assert "users/123" in exc_info.value.response_summary.url


class TestBuildResponseSummary:
    """Test _build_response_summary helper."""

    def test_builds_summary_from_response(self) -> None:
        response = httpx.Response(
            404,
            headers={"Content-Type": "application/json"},
            request=httpx.Request("GET", "https://api.example.com/users/123"),
        )
        summary = _build_response_summary(response)
        assert summary.status_code == 404
        assert "content-type" in summary.headers
        assert summary.method == "GET"

    def test_handles_various_status_codes(self) -> None:
        response = httpx.Response(
            500,
            request=httpx.Request("POST", "https://api.example.com/data"),
        )
        summary = _build_response_summary(response)
        assert summary.status_code == 500
        assert summary.method == "POST"


class TestParseRetryAfter:
    """Test _parse_retry_after helper."""

    def test_parses_numeric_retry_after(self) -> None:
        response = httpx.Response(429, headers={"Retry-After": "60"})
        delay = _parse_retry_after(response)
        assert delay == 60.0

    def test_parses_float_retry_after(self) -> None:
        response = httpx.Response(429, headers={"Retry-After": "30.5"})
        delay = _parse_retry_after(response)
        assert delay == 30.5

    def test_returns_none_when_missing(self) -> None:
        response = httpx.Response(429)
        delay = _parse_retry_after(response)
        assert delay is None

    def test_returns_none_on_invalid_format(self) -> None:
        response = httpx.Response(429, headers={"Retry-After": "invalid"})
        delay = _parse_retry_after(response)
        assert delay is None


class TestHttpClientConfig:
    """Test HttpClientConfig dataclass."""

    def test_default_values(self) -> None:
        config = HttpClientConfig()
        assert config.base_url == ""
        assert config.timeout_seconds == 30.0
        assert config.connect_timeout_seconds == 10.0
        assert config.read_timeout_seconds == 30.0
        assert config.write_timeout_seconds == 30.0
        assert config.pool_max_connections == 100
        assert config.pool_max_keepalive == 20
        assert config.default_headers == {}
        assert config.propagate_correlation is True
        assert config.follow_redirects is True
        assert config.retry_enabled is True
        assert config.retry_max_attempts == 3
        assert config.circuit_breaker_enabled is False

    def test_custom_values(self) -> None:
        config = HttpClientConfig(
            base_url="https://api.example.com",
            timeout_seconds=60.0,
            pool_max_connections=200,
            default_headers={"User-Agent": "MyClient/1.0"},
        )
        assert config.base_url == "https://api.example.com"
        assert config.timeout_seconds == 60.0
        assert config.pool_max_connections == 200
        assert config.default_headers == {"User-Agent": "MyClient/1.0"}

    def test_frozen_immutable(self) -> None:
        config = HttpClientConfig()
        with pytest.raises(AttributeError):
            config.timeout_seconds = 60.0  # type: ignore[misc]


class TestBuildConfigFromSettings:
    """Test build_config_from_settings function."""

    def test_reads_from_settings_object(self) -> None:
        settings = Mock()
        settings.HTTP_CLIENT_TIMEOUT_SECONDS = 45.0
        settings.HTTP_CLIENT_RETRY_MAX_ATTEMPTS = 5

        config = build_config_from_settings(settings)
        assert config.timeout_seconds == 45.0
        assert config.retry_max_attempts == 5

    def test_respects_overrides(self) -> None:
        settings = Mock()
        settings.HTTP_CLIENT_TIMEOUT_SECONDS = 30.0
        settings.HTTP_CLIENT_RETRY_MAX_ATTEMPTS = 3

        config = build_config_from_settings(settings, timeout_seconds=60.0, base_url="https://api.example.com")
        assert config.timeout_seconds == 60.0
        assert config.base_url == "https://api.example.com"
        assert config.retry_max_attempts == 3

    def test_defaults_when_settings_missing(self) -> None:
        settings = Mock(spec=[])  # No attributes
        config = build_config_from_settings(settings)
        assert config.timeout_seconds == 30.0
        assert config.retry_max_attempts == 3


class TestBuildCircuitBreakerConfigFromSettings:
    """Test build_circuit_breaker_config_from_settings function."""

    def test_reads_from_settings_object(self) -> None:
        settings = Mock()
        settings.HTTP_CLIENT_CIRCUIT_BREAKER_FAILURE_THRESHOLD = 10
        settings.HTTP_CLIENT_CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS = 60.0

        config = build_circuit_breaker_config_from_settings(settings, name="test-breaker")
        assert config.failure_threshold == 10
        assert config.recovery_timeout_seconds == 60.0
        assert config.name == "test-breaker"

    def test_defaults_when_settings_missing(self) -> None:
        settings = Mock(spec=[])
        config = build_circuit_breaker_config_from_settings(settings)
        assert config.failure_threshold == 5
        assert config.recovery_timeout_seconds == 30.0


class TestTemplateHttpClient:
    """Test TemplateHttpClient core functionality."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        async with TemplateHttpClient(base_url="https://api.example.com") as client:
            assert client is not None
            assert isinstance(client, TemplateHttpClient)

    @pytest.mark.asyncio
    async def test_get_request_sends_correct_method(self) -> None:
        def get_mock_transport() -> httpx.MockTransport:
            def handler(request: httpx.Request) -> httpx.Response:
                assert request.method == "GET"
                return httpx.Response(200, json={"users": []}, request=request)
            return httpx.MockTransport(handler)

        transport = get_mock_transport()
        httpx_client = httpx.AsyncClient(transport=transport, base_url="https://api.example.com")
        client = TemplateHttpClient(
            config=HttpClientConfig(base_url="https://api.example.com"),
            httpx_client=httpx_client,
        )

        response = await client.get("/users")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_post_request_sends_correct_method(self) -> None:
        def get_mock_transport() -> httpx.MockTransport:
            def handler(request: httpx.Request) -> httpx.Response:
                assert request.method == "POST"
                return httpx.Response(201, json={"id": "123"}, request=request)
            return httpx.MockTransport(handler)

        transport = get_mock_transport()
        httpx_client = httpx.AsyncClient(transport=transport, base_url="https://api.example.com")
        client = TemplateHttpClient(
            config=HttpClientConfig(base_url="https://api.example.com"),
            httpx_client=httpx_client,
        )

        response = await client.post("/users", json={"name": "Alice"})
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_request_hooks_called(self) -> None:
        call_log: list[str] = []

        class TestHook:
            async def before_request(
                self,
                *,
                method: str,
                url: str,
                headers: dict[str, str],
                content: bytes | None,
            ) -> dict[str, str]:
                call_log.append("hook_called")
                headers["X-Custom"] = "test"
                return headers

        def get_mock_transport() -> httpx.MockTransport:
            def handler(request: httpx.Request) -> httpx.Response:
                assert "X-Custom" in request.headers
                return httpx.Response(200, request=request)
            return httpx.MockTransport(handler)

        transport = get_mock_transport()
        httpx_client = httpx.AsyncClient(transport=transport, base_url="https://api.example.com")
        hook = TestHook()  # type: ignore[assignment]
        client = TemplateHttpClient(
            config=HttpClientConfig(base_url="https://api.example.com"),
            request_hooks=[hook],
            httpx_client=httpx_client,
        )

        await client.get("/test")
        assert "hook_called" in call_log

    @pytest.mark.asyncio
    async def test_response_hooks_called(self) -> None:
        call_log: list[str] = []

        class TestHook:
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
                call_log.append("hook_called")

        def get_mock_transport() -> httpx.MockTransport:
            def handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, request=request)
            return httpx.MockTransport(handler)

        transport = get_mock_transport()
        httpx_client = httpx.AsyncClient(transport=transport, base_url="https://api.example.com")
        hook = TestHook()  # type: ignore[assignment]
        client = TemplateHttpClient(
            config=HttpClientConfig(base_url="https://api.example.com"),
            response_hooks=[hook],
            httpx_client=httpx_client,
        )

        await client.get("/test")
        assert "hook_called" in call_log

    @pytest.mark.asyncio
    async def test_timeout_error_maps_to_http_timeout_error(self) -> None:
        def timeout_transport(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("Request timed out")

        httpx_client = httpx.AsyncClient(transport=httpx.MockTransport(timeout_transport))
        client = TemplateHttpClient(
            config=HttpClientConfig(base_url="https://api.example.com"),
            httpx_client=httpx_client,
        )

        with pytest.raises(HttpTimeoutError):
            await client.get("/test")

    @pytest.mark.asyncio
    async def test_connection_error_maps_to_http_connection_error(self) -> None:
        def connection_transport(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        httpx_client = httpx.AsyncClient(transport=httpx.MockTransport(connection_transport))
        client = TemplateHttpClient(
            config=HttpClientConfig(base_url="https://api.example.com"),
            httpx_client=httpx_client,
        )

        with pytest.raises(HttpConnectionError):
            await client.get("/test")

    @pytest.mark.asyncio
    async def test_raise_for_status_codes_true_raises_on_non_2xx(self) -> None:
        def not_found_transport(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, request=request)

        httpx_client = httpx.AsyncClient(
            transport=httpx.MockTransport(not_found_transport),
            base_url="https://api.example.com",
        )
        client = TemplateHttpClient(
            config=HttpClientConfig(base_url="https://api.example.com"),
            httpx_client=httpx_client,
        )

        with pytest.raises(HttpNotFoundError):
            await client.get("/test", raise_for_status_codes=True)

    @pytest.mark.asyncio
    async def test_raise_for_status_codes_false_returns_response(self) -> None:
        def not_found_transport(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, request=request)

        httpx_client = httpx.AsyncClient(
            transport=httpx.MockTransport(not_found_transport),
            base_url="https://api.example.com",
        )
        client = TemplateHttpClient(
            config=HttpClientConfig(base_url="https://api.example.com"),
            httpx_client=httpx_client,
        )

        response = await client.get("/test", raise_for_status_codes=False)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_correlation_headers_propagated(self) -> None:
        correlation_headers: dict[str, str] | None = None

        def capture_transport(request: httpx.Request) -> httpx.Response:
            nonlocal correlation_headers
            correlation_headers = dict(request.headers)
            return httpx.Response(200, request=request)

        httpx_client = httpx.AsyncClient(
            transport=httpx.MockTransport(capture_transport),
            base_url="https://api.example.com",
        )
        client = TemplateHttpClient(
            config=HttpClientConfig(
                base_url="https://api.example.com",
                propagate_correlation=True,
            ),
            httpx_client=httpx_client,
        )

        with patch("src.app.integrations.http_client.client.build_correlation_headers") as mock_correlation:
            mock_correlation.return_value = {"X-Correlation-ID": "test-123"}
            await client.get("/test")

        assert correlation_headers is not None
        assert "x-correlation-id" in correlation_headers
        assert correlation_headers["x-correlation-id"] == "test-123"

    @pytest.mark.asyncio
    async def test_default_headers_merged(self) -> None:
        sent_headers: dict[str, str] | None = None

        def capture_transport(request: httpx.Request) -> httpx.Response:
            nonlocal sent_headers
            sent_headers = dict(request.headers)
            return httpx.Response(200, request=request)

        httpx_client = httpx.AsyncClient(
            transport=httpx.MockTransport(capture_transport),
            base_url="https://api.example.com",
        )
        client = TemplateHttpClient(
            config=HttpClientConfig(
                base_url="https://api.example.com",
                default_headers={"User-Agent": "TestClient/1.0"},
            ),
            httpx_client=httpx_client,
        )

        await client.get("/test", headers={"Authorization": "Bearer token"})
        assert sent_headers is not None
        assert sent_headers["user-agent"] == "TestClient/1.0"
        assert sent_headers["authorization"] == "Bearer token"


class TestHttpRetryPolicy:
    """Test HttpRetryPolicy configuration."""

    def test_default_values(self) -> None:
        policy = HttpRetryPolicy()
        assert policy.max_attempts == 3
        assert policy.backoff_base_seconds == 1.0
        assert policy.backoff_max_seconds == 30.0
        assert policy.backoff_multiplier == 2.0
        assert policy.jitter is True

    def test_delay_for_attempt_without_jitter(self) -> None:
        policy = HttpRetryPolicy(
            backoff_base_seconds=1.0,
            backoff_max_seconds=30.0,
            backoff_multiplier=2.0,
            jitter=False,
        )
        assert policy.delay_for_attempt(0) == 1.0
        assert policy.delay_for_attempt(1) == 2.0
        assert policy.delay_for_attempt(2) == 4.0

    def test_delay_for_attempt_respects_max(self) -> None:
        policy = HttpRetryPolicy(
            backoff_base_seconds=1.0,
            backoff_max_seconds=10.0,
            backoff_multiplier=2.0,
            jitter=False,
        )
        assert policy.delay_for_attempt(5) == 10.0

    def test_delay_for_attempt_with_jitter(self) -> None:
        policy = HttpRetryPolicy(
            backoff_base_seconds=1.0,
            backoff_max_seconds=10.0,
            jitter=True,
        )
        delay = policy.delay_for_attempt(0)
        assert 0 <= delay <= 1.0


class TestBuildRetryPolicyFromSettings:
    """Test build_retry_policy_from_settings function."""

    def test_reads_from_settings(self) -> None:
        settings = Mock()
        settings.HTTP_CLIENT_RETRY_MAX_ATTEMPTS = 5
        settings.HTTP_CLIENT_RETRY_BACKOFF_BASE_SECONDS = 2.0
        settings.HTTP_CLIENT_RETRY_BACKOFF_MAX_SECONDS = 60.0
        settings.HTTP_CLIENT_RETRY_BACKOFF_MULTIPLIER = 3.0
        settings.HTTP_CLIENT_RETRY_BACKOFF_JITTER = False

        policy = build_retry_policy_from_settings(settings)
        assert policy.max_attempts == 5
        assert policy.backoff_base_seconds == 2.0
        assert policy.backoff_max_seconds == 60.0
        assert policy.backoff_multiplier == 3.0
        assert policy.jitter is False


class TestIsRetryableError:
    """Test is_retryable_error function."""

    def test_timeout_error_is_retryable_when_enabled(self) -> None:
        error = HttpTimeoutError()
        policy = HttpRetryPolicy(retry_on_timeout=True)
        assert is_retryable_error(error, policy=policy)

    def test_timeout_error_not_retryable_when_disabled(self) -> None:
        error = HttpTimeoutError()
        policy = HttpRetryPolicy(retry_on_timeout=False)
        assert not is_retryable_error(error, policy=policy)

    def test_connection_error_is_retryable(self) -> None:
        error = HttpConnectionError()
        policy = HttpRetryPolicy(retry_on_connection_error=True)
        assert is_retryable_error(error, policy=policy)

    def test_server_error_is_retryable(self) -> None:
        error = HttpServerError()
        policy = HttpRetryPolicy(retry_on_server_error=True)
        assert is_retryable_error(error, policy=policy)

    def test_rate_limit_error_is_retryable(self) -> None:
        error = HttpRateLimitError()
        policy = HttpRetryPolicy(retry_on_rate_limit=True)
        assert is_retryable_error(error, policy=policy)

    def test_authentication_error_not_retryable(self) -> None:
        error = HttpAuthenticationError()
        policy = HttpRetryPolicy()
        assert not is_retryable_error(error, policy=policy)

    def test_not_found_error_not_retryable(self) -> None:
        error = HttpNotFoundError()
        policy = HttpRetryPolicy()
        assert not is_retryable_error(error, policy=policy)

    def test_respects_error_is_retryable_flag(self) -> None:
        error = HttpServerError()
        error.is_retryable = False
        policy = HttpRetryPolicy()
        assert not is_retryable_error(error, policy=policy)


class TestShouldRetryMethod:
    """Test should_retry_method function."""

    def test_get_retryable_with_idempotent_only(self) -> None:
        policy = HttpRetryPolicy(idempotent_methods_only=True)
        assert should_retry_method("GET", policy=policy)

    def test_post_not_retryable_with_idempotent_only(self) -> None:
        policy = HttpRetryPolicy(idempotent_methods_only=True)
        assert not should_retry_method("POST", policy=policy)

    def test_post_retryable_without_idempotent_only(self) -> None:
        policy = HttpRetryPolicy(idempotent_methods_only=False)
        assert should_retry_method("POST", policy=policy)

    def test_all_idempotent_methods_retryable(self) -> None:
        policy = HttpRetryPolicy(idempotent_methods_only=True)
        for method in IDEMPOTENT_METHODS:
            assert should_retry_method(method, policy=policy)

    def test_method_comparison_case_insensitive(self) -> None:
        policy = HttpRetryPolicy(idempotent_methods_only=True)
        assert should_retry_method("get", policy=policy)
        assert should_retry_method("GeT", policy=policy)


class TestResolveRetryDelay:
    """Test resolve_retry_delay function."""

    def test_uses_retry_after_for_rate_limit(self) -> None:
        error = HttpRateLimitError(retry_after_seconds=90.0)
        policy = HttpRetryPolicy(backoff_base_seconds=1.0, backoff_max_seconds=30.0)
        delay = resolve_retry_delay(error, attempt=0, policy=policy)
        assert delay == 30.0  # Capped at backoff_max_seconds

    def test_uses_policy_delay_when_no_retry_after(self) -> None:
        error = HttpRateLimitError()
        policy = HttpRetryPolicy(backoff_base_seconds=1.0, jitter=False)
        delay = resolve_retry_delay(error, attempt=0, policy=policy)
        assert delay == 1.0

    def test_uses_policy_delay_for_non_rate_limit_errors(self) -> None:
        error = HttpServerError()
        policy = HttpRetryPolicy(backoff_base_seconds=2.0, jitter=False)
        delay = resolve_retry_delay(error, attempt=0, policy=policy)
        assert delay == 2.0


class TestCircuitBreaker:
    """Test CircuitBreaker state machine."""

    def test_starts_in_closed_state(self) -> None:
        breaker = CircuitBreaker()
        assert breaker.state == CircuitState.CLOSED

    def test_opens_after_failure_threshold(self) -> None:
        breaker = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=3))
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_check_raises_when_open(self) -> None:
        breaker = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=1))
        breaker.record_failure()
        with pytest.raises(HttpCircuitOpenError):
            breaker.check()

    def test_transitions_to_half_open_after_recovery_timeout(self) -> None:
        breaker = CircuitBreaker(
            config=CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout_seconds=0.1,
            )
        )
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        time.sleep(0.15)
        assert breaker.state == CircuitState.HALF_OPEN

    def test_closes_on_success_from_half_open(self) -> None:
        breaker = CircuitBreaker(
            config=CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout_seconds=0.1,
            )
        )
        breaker.record_failure()
        time.sleep(0.15)
        assert breaker.state == CircuitState.HALF_OPEN
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

    def test_reopens_on_failure_from_half_open(self) -> None:
        breaker = CircuitBreaker(
            config=CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout_seconds=0.1,
            )
        )
        breaker.record_failure()
        time.sleep(0.15)
        assert breaker.state == CircuitState.HALF_OPEN
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_reset_forces_closed(self) -> None:
        breaker = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=1))
        breaker.record_failure()
        breaker.reset()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_failure_count_incremented(self) -> None:
        breaker = CircuitBreaker()
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.failure_count == 2

    def test_failure_count_reset_on_success(self) -> None:
        breaker = CircuitBreaker()
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        assert breaker.failure_count == 0


class TestRateLimitInfo:
    """Test RateLimitInfo dataclass."""

    def test_is_exhausted_when_remaining_zero(self) -> None:
        info = RateLimitInfo(limit=100, remaining=0)
        assert info.is_exhausted is True

    def test_is_exhausted_when_remaining_negative(self) -> None:
        info = RateLimitInfo(limit=100, remaining=-1)
        assert info.is_exhausted is True

    def test_not_exhausted_when_remaining_positive(self) -> None:
        info = RateLimitInfo(limit=100, remaining=50)
        assert info.is_exhausted is False

    def test_not_exhausted_when_remaining_none(self) -> None:
        info = RateLimitInfo(limit=100, remaining=None)
        assert info.is_exhausted is False

    def test_is_approaching_limit_below_10_percent(self) -> None:
        info = RateLimitInfo(limit=100, remaining=5)
        assert info.is_approaching_limit is True

    def test_is_approaching_limit_exactly_10_percent(self) -> None:
        info = RateLimitInfo(limit=100, remaining=10)
        assert info.is_approaching_limit is False

    def test_is_approaching_limit_above_10_percent(self) -> None:
        info = RateLimitInfo(limit=100, remaining=50)
        assert info.is_approaching_limit is False

    def test_is_approaching_limit_when_limit_none(self) -> None:
        info = RateLimitInfo(limit=None, remaining=5)
        assert info.is_approaching_limit is False


class TestParseRateLimitHeaders:
    """Test parse_rate_limit_headers function."""

    def test_parses_x_ratelimit_headers(self) -> None:
        headers = {
            "X-RateLimit-Limit": "100",
            "X-RateLimit-Remaining": "50",
            "X-RateLimit-Reset": "1234567890",
        }
        info = parse_rate_limit_headers(headers)
        assert info.limit == 100
        assert info.remaining == 50
        assert info.reset_seconds == 1234567890.0

    def test_parses_ietf_ratelimit_headers(self) -> None:
        headers = {
            "RateLimit-Limit": "200",
            "RateLimit-Remaining": "100",
            "RateLimit-Reset": "1234567890",
        }
        info = parse_rate_limit_headers(headers)
        assert info.limit == 200
        assert info.remaining == 100
        assert info.reset_seconds == 1234567890.0

    def test_parses_retry_after_header(self) -> None:
        headers = {"Retry-After": "60"}
        info = parse_rate_limit_headers(headers)
        assert info.retry_after_seconds == 60.0

    def test_handles_missing_headers(self) -> None:
        info = parse_rate_limit_headers({})
        assert info.limit is None
        assert info.remaining is None
        assert info.reset_seconds is None

    def test_case_insensitive_header_parsing(self) -> None:
        headers = {
            "x-ratelimit-limit": "100",
            "X-RATELIMIT-REMAINING": "50",
        }
        info = parse_rate_limit_headers(headers)
        assert info.limit == 100
        assert info.remaining == 50

    def test_prefers_x_ratelimit_over_ietf(self) -> None:
        headers = {
            "X-RateLimit-Limit": "100",
            "RateLimit-Limit": "200",
        }
        info = parse_rate_limit_headers(headers)
        assert info.limit == 100


class TestComputeRateLimitDelay:
    """Test compute_rate_limit_delay function."""

    def test_uses_retry_after_when_available(self) -> None:
        info = RateLimitInfo(retry_after_seconds=60.0, reset_seconds=120.0)
        delay = compute_rate_limit_delay(info)
        assert delay == 60.0

    def test_uses_reset_as_fallback(self) -> None:
        info = RateLimitInfo(reset_seconds=45.0)
        delay = compute_rate_limit_delay(info)
        assert delay == 45.0

    def test_uses_default_when_nothing_available(self) -> None:
        info = RateLimitInfo()
        delay = compute_rate_limit_delay(info, default_delay=5.0)
        assert delay == 5.0

    def test_ignores_zero_retry_after(self) -> None:
        info = RateLimitInfo(retry_after_seconds=0.0, reset_seconds=30.0)
        delay = compute_rate_limit_delay(info)
        assert delay == 30.0

    def test_ignores_negative_values(self) -> None:
        info = RateLimitInfo(retry_after_seconds=-1.0, reset_seconds=-1.0)
        delay = compute_rate_limit_delay(info, default_delay=5.0)
        assert delay == 5.0


class TestBearerTokenAuth:
    """Test BearerTokenAuth request hook."""

    @pytest.mark.asyncio
    async def test_adds_static_bearer_token(self) -> None:
        auth = BearerTokenAuth(token="sk-live-xxx")
        headers = await auth.before_request(
            method="GET",
            url="https://api.example.com/users",
            headers={},
            content=None,
        )
        assert headers["Authorization"] == "Bearer sk-live-xxx"

    @pytest.mark.asyncio
    async def test_adds_dynamic_bearer_token(self) -> None:
        class MockTokenProvider:
            async def get_token(self) -> str:
                return "dynamic-token-123"

        provider = MockTokenProvider()  # type: ignore[assignment]
        auth = BearerTokenAuth(token_provider=provider)
        headers = await auth.before_request(
            method="GET",
            url="https://api.example.com/users",
            headers={},
            content=None,
        )
        assert headers["Authorization"] == "Bearer dynamic-token-123"

    def test_requires_token_or_provider(self) -> None:
        with pytest.raises(ValueError):
            BearerTokenAuth()


class TestApiKeyAuth:
    """Test ApiKeyAuth request hook."""

    @pytest.mark.asyncio
    async def test_adds_api_key_header_default_name(self) -> None:
        auth = ApiKeyAuth(key="sk-xxx")
        headers = await auth.before_request(
            method="GET",
            url="https://api.example.com/resources",
            headers={},
            content=None,
        )
        assert headers["X-Api-Key"] == "sk-xxx"

    @pytest.mark.asyncio
    async def test_adds_api_key_custom_header_name(self) -> None:
        auth = ApiKeyAuth(key="sk-xxx", header_name="Authorization")
        headers = await auth.before_request(
            method="GET",
            url="https://api.example.com/resources",
            headers={},
            content=None,
        )
        assert headers["Authorization"] == "sk-xxx"


class TestBasicAuth:
    """Test BasicAuth request hook."""

    @pytest.mark.asyncio
    async def test_adds_basic_auth_header(self) -> None:
        auth = BasicAuth(username="user", password="pass")
        headers = await auth.before_request(
            method="GET",
            url="https://api.example.com/secure",
            headers={},
            content=None,
        )
        expected_value = f"Basic {base64.b64encode(b'user:pass').decode()}"
        assert headers["Authorization"] == expected_value


class TestCustomAuth:
    """Test CustomAuth request hook."""

    @pytest.mark.asyncio
    async def test_delegates_to_sync_handler(self) -> None:
        def handler(method: str, url: str, headers: dict[str, str], content: bytes | None) -> dict[str, str]:
            headers["X-Custom"] = "sync-value"
            return headers

        auth = CustomAuth(handler=handler)
        headers = await auth.before_request(
            method="GET",
            url="https://api.example.com/test",
            headers={},
            content=None,
        )
        assert headers["X-Custom"] == "sync-value"

    @pytest.mark.asyncio
    async def test_delegates_to_async_handler(self) -> None:
        async def handler(method: str, url: str, headers: dict[str, str], content: bytes | None) -> dict[str, str]:
            headers["X-Custom"] = "async-value"
            return headers

        auth = CustomAuth(handler=handler)
        headers = await auth.before_request(
            method="GET",
            url="https://api.example.com/test",
            headers={},
            content=None,
        )
        assert headers["X-Custom"] == "async-value"


class TestLoggingRequestHook:
    """Test LoggingRequestHook."""

    @pytest.mark.asyncio
    async def test_logs_request_details(self) -> None:
        mock_logger = Mock()
        hook = LoggingRequestHook(logger_instance=mock_logger)

        await hook.before_request(
            method="POST",
            url="https://api.example.com/users",
            headers={"Authorization": "Bearer token"},
            content=None,
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "http_client_request"
        assert "method" in call_args[1]
        assert "url" in call_args[1]

    @pytest.mark.asyncio
    async def test_redacts_authorization_header(self) -> None:
        mock_logger = Mock()
        hook = LoggingRequestHook(logger_instance=mock_logger)

        await hook.before_request(
            method="GET",
            url="https://api.example.com/data",
            headers={"Authorization": "Bearer secret-token"},
            content=None,
        )

        call_args = mock_logger.info.call_args
        logged_headers = call_args[1]["headers"]
        # Check that Authorization header is redacted (preserves original case)
        auth_value = logged_headers.get("Authorization") or logged_headers.get("authorization")
        assert "[REDACTED]" in str(auth_value)


class TestLoggingResponseHook:
    """Test LoggingResponseHook."""

    @pytest.mark.asyncio
    async def test_logs_successful_response(self) -> None:
        mock_logger = Mock()
        hook = LoggingResponseHook(logger_instance=mock_logger)

        await hook.after_response(
            method="GET",
            url="https://api.example.com/users",
            status_code=200,
            headers={},
            duration_seconds=0.5,
            content=None,
            error=None,
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "http_client_response"
        assert call_args[1]["status_code"] == 200

    @pytest.mark.asyncio
    async def test_logs_error_response(self) -> None:
        mock_logger = Mock()
        hook = LoggingResponseHook(logger_instance=mock_logger)
        error = HttpNotFoundError("Resource not found")

        await hook.after_response(
            method="GET",
            url="https://api.example.com/users/999",
            status_code=404,
            headers={},
            duration_seconds=0.2,
            content=None,
            error=error,
        )

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert call_args[0][0] == "http_client_response_error"


class TestInstrumentationHooks:
    """Test instrumentation hooks for metrics and tracing."""

    @pytest.mark.asyncio
    async def test_request_hook_injects_trace_headers(self) -> None:
        mock_tracing = Mock(spec=TracingHook)
        mock_tracing.inject_trace_headers = AsyncMock(
            return_value={"X-Trace-ID": "trace-123"}
        )

        hook = InstrumentationRequestHook(tracing_hook=mock_tracing)
        headers = await hook.before_request(
            method="GET",
            url="https://api.example.com/test",
            headers={},
            content=None,
        )

        mock_tracing.inject_trace_headers.assert_called_once()
        assert headers["X-Trace-ID"] == "trace-123"

    @pytest.mark.asyncio
    async def test_response_hook_records_metrics(self) -> None:
        mock_metrics = Mock(spec=MetricsCollector)
        mock_metrics.record_request = AsyncMock()

        hook = InstrumentationResponseHook(metrics_collector=mock_metrics)
        await hook.after_response(
            method="GET",
            url="https://api.example.com/test",
            status_code=200,
            headers={},
            duration_seconds=0.1,
            content=None,
            error=None,
        )

        mock_metrics.record_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_response_hook_records_trace_span(self) -> None:
        mock_tracing = Mock(spec=TracingHook)
        mock_tracing.record_span = AsyncMock()

        hook = InstrumentationResponseHook(tracing_hook=mock_tracing)
        await hook.after_response(
            method="POST",
            url="https://api.example.com/create",
            status_code=201,
            headers={},
            duration_seconds=0.2,
            content=None,
            error=None,
        )

        mock_tracing.record_span.assert_called_once()


class TestExportSurface:
    """Test that all expected exports exist."""

    def test_all_expected_exports_in_init(self) -> None:
        from src.app.integrations.http_client import __all__

        expected = {
            "ApiKeyAuth",
            "BasicAuth",
            "BearerTokenAuth",
            "CircuitBreaker",
            "CircuitBreakerConfig",
            "CircuitState",
            "CustomAuth",
            "HttpAuthenticationError",
            "HttpAuthorizationError",
            "HttpCircuitOpenError",
            "HttpClientBadRequestError",
            "HttpClientConfig",
            "HttpClientError",
            "HttpConflictError",
            "HttpConnectionError",
            "HttpNotFoundError",
            "HttpRateLimitError",
            "HttpResponseSummary",
            "HttpServerError",
            "HttpTimeoutError",
            "IDEMPOTENT_METHODS",
            "InstrumentationRequestHook",
            "InstrumentationResponseHook",
            "LoggingRequestHook",
            "LoggingResponseHook",
            "MetricsCollector",
            "NonRetryableHttpError",
            "RateLimitInfo",
            "RequestHook",
            "ResponseHook",
            "TemplateHttpClient",
            "TokenProvider",
            "TracingHook",
            "build_circuit_breaker_config_from_settings",
            "build_config_from_settings",
            "build_retry_policy_from_settings",
            "classify_status_code",
            "compute_rate_limit_delay",
            "is_retryable_error",
            "parse_rate_limit_headers",
            "raise_for_status",
            "resolve_retry_delay",
            "should_retry_method",
        }
        for export in expected:
            assert export in __all__, f"Missing export: {export}"
