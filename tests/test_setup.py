import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import ModuleType
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from src.app.core import setup as core_setup
from src.app.core.utils import cache, queue
from src.app.platform.application import create_application, lifespan_factory
from src.app.platform.config import load_settings, settings
from src.app.platform.database import Base
from src.app.platform.middleware import ClientCacheMiddleware, SecurityHeadersMiddleware


@asynccontextmanager
async def noop_lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    yield


@pytest.mark.asyncio
async def test_lifespan_does_not_create_tables_on_startup() -> None:
    app = FastAPI()

    with (
        patch("src.app.core.setup.set_threadpool_tokens", new=AsyncMock()),
        patch("src.app.core.setup.initialize_database_engine", new=AsyncMock()),
        patch("src.app.core.setup.create_redis_cache_pool", new=AsyncMock()),
        patch("src.app.core.setup.create_redis_queue_pool", new=AsyncMock()),
        patch("src.app.core.setup.create_redis_rate_limit_pool", new=AsyncMock()),
        patch("src.app.core.setup.close_database_engine", new=AsyncMock()),
        patch("src.app.core.setup.close_redis_cache_pool", new=AsyncMock()),
        patch("src.app.core.setup.close_redis_queue_pool", new=AsyncMock()),
        patch("src.app.core.setup.close_redis_rate_limit_pool", new=AsyncMock()),
        patch("src.app.core.setup.init_sentry"),
        patch("src.app.core.setup.shutdown_sentry", new=AsyncMock()),
        patch.object(Base.metadata, "create_all") as create_all_mock,
    ):
        async with lifespan_factory(settings)(app):
            assert app.state.initialization_complete.is_set()

    create_all_mock.assert_not_called()


@pytest.mark.asyncio
async def test_wait_for_api_requests_to_drain_waits_for_active_requests_to_finish() -> None:
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    await core_setup.begin_api_request(app)
    await core_setup.mark_api_shutdown_in_progress(app)

    drain_task = asyncio.create_task(core_setup.wait_for_api_requests_to_drain(app, timeout=0.1))
    await asyncio.sleep(0)

    assert not drain_task.done()

    await core_setup.end_api_request(app)
    await drain_task

    assert app.state.active_requests_drained.is_set()


@pytest.mark.asyncio
async def test_lifespan_marks_shutdown_before_releasing_shared_resources() -> None:
    app = FastAPI()

    with (
        patch("src.app.core.setup.set_threadpool_tokens", new=AsyncMock()),
        patch("src.app.core.setup.initialize_database_engine", new=AsyncMock()),
        patch("src.app.core.setup.create_redis_cache_pool", new=AsyncMock()),
        patch("src.app.core.setup.create_redis_queue_pool", new=AsyncMock()),
        patch("src.app.core.setup.create_redis_rate_limit_pool", new=AsyncMock()),
        patch("src.app.core.setup.close_database_engine", new=AsyncMock()),
        patch("src.app.core.setup.close_redis_cache_pool", new=AsyncMock()),
        patch("src.app.core.setup.close_redis_queue_pool", new=AsyncMock()),
        patch("src.app.core.setup.close_redis_rate_limit_pool", new=AsyncMock()),
        patch("src.app.core.setup.init_sentry"),
        patch("src.app.core.setup.shutdown_sentry", new=AsyncMock()),
        patch(
            "src.app.core.setup.wait_for_api_requests_to_drain",
            new=AsyncMock(),
        ) as wait_for_api_requests_to_drain_mock,
    ):
        async with lifespan_factory(settings)(app):
            assert app.state.initialization_complete.is_set()
            assert not app.state.shutdown_in_progress.is_set()

    wait_for_api_requests_to_drain_mock.assert_awaited_once_with(app)
    assert app.state.shutdown_in_progress.is_set()


@pytest.mark.asyncio
async def test_initialize_database_engine_opens_a_connection_during_startup() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def fake_connect() -> AsyncGenerator[object, None]:
        events.append("entered")
        yield object()

    fake_engine = Mock()
    fake_engine.connect.return_value = fake_connect()

    with patch("src.app.core.db.database.async_engine", fake_engine):
        await core_setup.initialize_database_engine()

    fake_engine.connect.assert_called_once_with()
    assert events == ["entered"]


def test_graceful_shutdown_middleware_rejects_new_requests_once_shutdown_begins() -> None:
    router = APIRouter()

    @router.get("/shutdown-probe")
    async def shutdown_probe() -> dict[str, str]:
        return {"status": "ok"}

    application = create_application(router, settings, lifespan=noop_lifespan)
    core_setup.initialize_api_lifecycle_state(application)
    application.state.shutdown_in_progress.set()

    with TestClient(application) as client:
        response = client.get("/shutdown-probe")

    assert response.status_code == 503
    assert response.json() == {"detail": core_setup.API_SHUTDOWN_DETAIL}


@pytest.mark.asyncio
async def test_close_database_engine_disposes_the_shared_async_engine() -> None:
    fake_engine = Mock()
    fake_engine.dispose = AsyncMock()

    with patch.object(core_setup, "async_engine", fake_engine):
        await core_setup.close_database_engine()

    fake_engine.dispose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_create_redis_cache_pool_uses_runtime_settings() -> None:
    custom_settings = load_settings(
        _env_file=None,
        REDIS_CACHE_HOST="cache.internal",
        REDIS_CACHE_PORT=6380,
        REDIS_CACHE_DB=3,
        REDIS_CACHE_USERNAME="cache-user",
        REDIS_CACHE_PASSWORD="cache-password",
        REDIS_CACHE_CONNECT_TIMEOUT=7.5,
        REDIS_CACHE_SOCKET_TIMEOUT=9.0,
        REDIS_CACHE_RETRY_ATTEMPTS=4,
        REDIS_CACHE_RETRY_BASE_DELAY=0.2,
        REDIS_CACHE_RETRY_MAX_DELAY=1.5,
        REDIS_CACHE_RETRY_ON_TIMEOUT=False,
        REDIS_CACHE_MAX_CONNECTIONS=25,
        REDIS_CACHE_SSL=True,
        REDIS_CACHE_SSL_CHECK_HOSTNAME=True,
        REDIS_CACHE_SSL_CA_CERTS="/tmp/cache-ca.pem",
    )

    cache.pool = None
    cache.client = None
    cache_pool = AsyncMock()
    cache_client = AsyncMock()

    with (
        patch("src.app.core.setup.redis.ConnectionPool.from_url", return_value=cache_pool) as from_url,
        patch("src.app.core.setup.redis.Redis.from_pool", return_value=cache_client),
    ):
        await core_setup.create_redis_cache_pool(custom_settings)

    args, kwargs = from_url.call_args
    assert args[0] == custom_settings.REDIS_CACHE_URL
    assert kwargs["socket_connect_timeout"] == 7.5
    assert kwargs["socket_timeout"] == 9.0
    assert kwargs["retry_on_timeout"] is False
    assert kwargs["max_connections"] == 25
    assert kwargs["ssl_check_hostname"] is True
    assert kwargs["ssl_ca_certs"] == "/tmp/cache-ca.pem"
    assert kwargs["ssl_cert_reqs"] == "required"
    assert "retry" in kwargs
    cache_client.ping.assert_awaited_once_with()
    assert cache.pool is cache_pool
    assert cache.client is cache_client

    cache.pool = None
    cache.client = None


@pytest.mark.asyncio
async def test_create_redis_cache_pool_cleans_up_when_ping_fails() -> None:
    custom_settings = load_settings(_env_file=None)
    cache.pool = None
    cache.client = None
    cache_pool = AsyncMock()
    cache_client = AsyncMock()
    cache_client.ping.side_effect = RuntimeError("cache ping failed")

    with (
        patch("src.app.core.setup.redis.ConnectionPool.from_url", return_value=cache_pool),
        patch("src.app.core.setup.redis.Redis.from_pool", return_value=cache_client),
        pytest.raises(RuntimeError, match="cache ping failed"),
    ):
        await core_setup.create_redis_cache_pool(custom_settings)

    cache_client.aclose.assert_awaited_once()
    cache_pool.aclose.assert_awaited_once()
    assert cache.pool is None
    assert cache.client is None


@pytest.mark.asyncio
async def test_create_redis_queue_pool_uses_runtime_settings() -> None:
    custom_settings = load_settings(
        _env_file=None,
        REDIS_QUEUE_HOST="queue.internal",
        REDIS_QUEUE_PORT=6381,
        REDIS_QUEUE_DB=4,
        REDIS_QUEUE_USERNAME="queue-user",
        REDIS_QUEUE_PASSWORD="queue-password",
        REDIS_QUEUE_CONNECT_TIMEOUT=8,
        REDIS_QUEUE_CONNECT_RETRIES=6,
        REDIS_QUEUE_RETRY_DELAY=2,
        REDIS_QUEUE_RETRY_ON_TIMEOUT=False,
        REDIS_QUEUE_MAX_CONNECTIONS=30,
        REDIS_QUEUE_SSL=True,
        REDIS_QUEUE_SSL_CA_CERTS="/tmp/queue-ca.pem",
    )

    queue.pool = None
    queue_pool = AsyncMock()

    with (
        patch("src.app.core.setup.create_pool", new=AsyncMock(return_value=queue_pool)) as create_pool_mock,
    ):
        await core_setup.create_redis_queue_pool(custom_settings)

    redis_settings = create_pool_mock.await_args.args[0]
    assert redis_settings.host == "queue.internal"
    assert redis_settings.port == 6381
    assert redis_settings.database == 4
    assert redis_settings.username == "queue-user"
    assert redis_settings.password == "queue-password"
    assert redis_settings.conn_timeout == 8
    assert redis_settings.conn_retries == 6
    assert redis_settings.conn_retry_delay == 2
    assert redis_settings.retry_on_timeout is False
    assert redis_settings.max_connections == 30
    assert redis_settings.ssl is True
    assert redis_settings.ssl_ca_certs == "/tmp/queue-ca.pem"
    queue_pool.ping.assert_awaited_once_with()
    assert queue.pool is queue_pool

    queue.pool = None


@pytest.mark.asyncio
async def test_create_redis_queue_pool_closes_pool_when_ping_fails() -> None:
    custom_settings = load_settings(_env_file=None)
    queue.pool = None
    queue_pool = AsyncMock()
    queue_pool.ping.side_effect = RuntimeError("queue ping failed")

    with (
        patch("src.app.core.setup.create_pool", new=AsyncMock(return_value=queue_pool)),
        pytest.raises(RuntimeError, match="queue ping failed"),
    ):
        await core_setup.create_redis_queue_pool(custom_settings)

    queue_pool.aclose.assert_awaited_once()
    assert queue.pool is None


@pytest.mark.asyncio
async def test_create_redis_rate_limit_pool_uses_runtime_settings() -> None:
    custom_settings = load_settings(
        _env_file=None,
        REDIS_RATE_LIMIT_HOST="limit.internal",
        REDIS_RATE_LIMIT_PORT=6382,
        REDIS_RATE_LIMIT_DB=5,
        REDIS_RATE_LIMIT_PASSWORD="limit-password",
        REDIS_RATE_LIMIT_CONNECT_TIMEOUT=6.0,
        REDIS_RATE_LIMIT_SOCKET_TIMEOUT=7.0,
        REDIS_RATE_LIMIT_RETRY_ATTEMPTS=2,
        REDIS_RATE_LIMIT_RETRY_BASE_DELAY=0.3,
        REDIS_RATE_LIMIT_RETRY_MAX_DELAY=1.2,
        REDIS_RATE_LIMIT_RETRY_ON_TIMEOUT=False,
        REDIS_RATE_LIMIT_MAX_CONNECTIONS=18,
        REDIS_RATE_LIMIT_SSL=True,
        REDIS_RATE_LIMIT_SSL_CA_CERTS="/tmp/limit-ca.pem",
    )

    rate_limit_client = AsyncMock()
    with (
        patch("src.app.core.setup.rate_limiter.initialize") as initialize,
        patch("src.app.core.setup.rate_limiter.get_client", return_value=rate_limit_client),
    ):
        await core_setup.create_redis_rate_limit_pool(custom_settings)

    args, kwargs = initialize.call_args
    assert args[0] == custom_settings.REDIS_RATE_LIMIT_URL
    assert kwargs["socket_connect_timeout"] == 6.0
    assert kwargs["socket_timeout"] == 7.0
    assert kwargs["retry_on_timeout"] is False
    assert kwargs["max_connections"] == 18
    assert kwargs["ssl_ca_certs"] == "/tmp/limit-ca.pem"
    assert kwargs["ssl_cert_reqs"] == "required"
    assert "retry" in kwargs
    rate_limit_client.ping.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_create_redis_rate_limit_pool_resets_state_when_ping_fails() -> None:
    custom_settings = load_settings(_env_file=None)
    rate_limit_client = AsyncMock()
    rate_limit_client.ping.side_effect = RuntimeError("rate limit ping failed")

    with (
        patch("src.app.core.setup.rate_limiter.initialize"),
        patch("src.app.core.setup.rate_limiter.get_client", return_value=rate_limit_client),
        patch("src.app.core.setup.rate_limiter.shutdown", new=AsyncMock()) as shutdown_mock,
        pytest.raises(RuntimeError, match="rate limit ping failed"),
    ):
        await core_setup.create_redis_rate_limit_pool(custom_settings)

    shutdown_mock.assert_awaited_once_with()


def test_init_sentry_uses_runtime_observability_settings() -> None:
    custom_settings = load_settings(
        _env_file=None,
        SENTRY_ENABLE=True,
        SENTRY_DSN="https://public@example.ingest.sentry.io/1",
        SENTRY_ENVIRONMENT="staging",
        SENTRY_RELEASE="template@1.2.3",
        SENTRY_DEBUG=True,
        SENTRY_ATTACH_STACKTRACE=False,
        SENTRY_SEND_DEFAULT_PII=True,
        SENTRY_MAX_BREADCRUMBS=55,
        SENTRY_TRACES_SAMPLE_RATE=0.2,
        SENTRY_PROFILES_SAMPLE_RATE=0.05,
    )

    sentry_sdk_module = ModuleType("sentry_sdk")
    sentry_sdk_module.init = Mock()
    fastapi_integration_factory = Mock(return_value=object())
    sentry_integrations_module = ModuleType("sentry_sdk.integrations")
    sentry_fastapi_module = ModuleType("sentry_sdk.integrations.fastapi")
    sentry_fastapi_module.FastApiIntegration = fastapi_integration_factory

    with (
        patch.dict(
            "sys.modules",
            {
                "sentry_sdk": sentry_sdk_module,
                "sentry_sdk.integrations": sentry_integrations_module,
                "sentry_sdk.integrations.fastapi": sentry_fastapi_module,
            },
        ),
    ):
        core_setup.init_sentry(custom_settings)

    fastapi_integration_factory.assert_called_once_with(transaction_style="endpoint")
    sentry_sdk_module.init.assert_called_once()
    kwargs = sentry_sdk_module.init.call_args.kwargs
    assert kwargs["dsn"] == custom_settings.SENTRY_DSN.get_secret_value()
    assert kwargs["environment"] == "staging"
    assert kwargs["release"] == "template@1.2.3"
    assert kwargs["debug"] is True
    assert kwargs["attach_stacktrace"] is False
    assert kwargs["send_default_pii"] is True
    assert kwargs["max_breadcrumbs"] == 55
    assert kwargs["traces_sample_rate"] == 0.2
    assert kwargs["profiles_sample_rate"] == 0.05


@pytest.mark.asyncio
async def test_close_shared_resource_handles_are_cleared_after_shutdown() -> None:
    cache_client = AsyncMock()
    cache_pool = AsyncMock()
    cache.pool = cache_pool
    cache.client = cache_client

    queue_pool = AsyncMock()
    queue.pool = queue_pool

    rate_limit_client = AsyncMock()
    rate_limit_pool = AsyncMock()
    core_setup.rate_limiter.pool = rate_limit_pool
    core_setup.rate_limiter.client = rate_limit_client

    await core_setup.close_redis_cache_pool()
    await core_setup.close_redis_queue_pool()
    await core_setup.close_redis_rate_limit_pool()

    cache_client.aclose.assert_awaited_once()
    cache_pool.aclose.assert_awaited_once()
    queue_pool.aclose.assert_awaited_once()
    rate_limit_client.aclose.assert_awaited_once()
    rate_limit_pool.aclose.assert_awaited_once()
    assert cache.pool is None
    assert cache.client is None
    assert queue.pool is None
    assert core_setup.rate_limiter.pool is None
    assert core_setup.rate_limiter.client is None


@pytest.mark.asyncio
async def test_lifespan_uses_passed_settings_for_shared_resource_wiring() -> None:
    custom_settings = load_settings(
        _env_file=None,
        SENTRY_ENABLE=True,
        SENTRY_DSN="https://public@example.ingest.sentry.io/1",
    )
    app = FastAPI()

    with (
        patch("src.app.core.setup.set_threadpool_tokens", new=AsyncMock()) as set_threadpool_tokens_mock,
        patch("src.app.core.setup.initialize_database_engine", new=AsyncMock()) as initialize_database_engine_mock,
        patch("src.app.core.setup.create_redis_cache_pool", new=AsyncMock()) as create_redis_cache_pool_mock,
        patch("src.app.core.setup.create_redis_queue_pool", new=AsyncMock()) as create_redis_queue_pool_mock,
        patch("src.app.core.setup.create_redis_rate_limit_pool", new=AsyncMock()) as create_redis_rate_limit_pool_mock,
        patch("src.app.core.setup.close_database_engine", new=AsyncMock()) as close_database_engine_mock,
        patch("src.app.core.setup.close_redis_cache_pool", new=AsyncMock()) as close_redis_cache_pool_mock,
        patch("src.app.core.setup.close_redis_queue_pool", new=AsyncMock()) as close_redis_queue_pool_mock,
        patch("src.app.core.setup.close_redis_rate_limit_pool", new=AsyncMock()) as close_redis_rate_limit_pool_mock,
        patch("src.app.core.setup.init_sentry") as init_sentry_mock,
        patch("src.app.core.setup.shutdown_sentry", new=AsyncMock()) as shutdown_sentry_mock,
    ):
        async with lifespan_factory(custom_settings)(app):
            assert app.state.initialization_complete.is_set()

    set_threadpool_tokens_mock.assert_awaited_once_with()
    initialize_database_engine_mock.assert_awaited_once_with(custom_settings)
    create_redis_cache_pool_mock.assert_awaited_once_with(custom_settings)
    create_redis_queue_pool_mock.assert_awaited_once_with(custom_settings)
    create_redis_rate_limit_pool_mock.assert_awaited_once_with(custom_settings)
    init_sentry_mock.assert_called_once_with(custom_settings)
    shutdown_sentry_mock.assert_awaited_once_with(custom_settings)
    close_redis_rate_limit_pool_mock.assert_awaited_once_with()
    close_redis_queue_pool_mock.assert_awaited_once_with()
    close_redis_cache_pool_mock.assert_awaited_once_with()
    close_database_engine_mock.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_lifespan_cleans_up_initialized_resources_when_startup_fails() -> None:
    app = FastAPI()

    with (
        patch("src.app.core.setup.set_threadpool_tokens", new=AsyncMock()),
        patch("src.app.core.setup.initialize_database_engine", new=AsyncMock()) as initialize_database_engine_mock,
        patch("src.app.core.setup.create_redis_cache_pool", new=AsyncMock()) as create_redis_cache_pool_mock,
        patch(
            "src.app.core.setup.create_redis_queue_pool",
            new=AsyncMock(side_effect=RuntimeError("queue startup failed")),
        ) as create_redis_queue_pool_mock,
        patch("src.app.core.setup.close_database_engine", new=AsyncMock()) as close_database_engine_mock,
        patch("src.app.core.setup.close_redis_cache_pool", new=AsyncMock()) as close_redis_cache_pool_mock,
        patch("src.app.core.setup.close_redis_queue_pool", new=AsyncMock()) as close_redis_queue_pool_mock,
        patch("src.app.core.setup.close_redis_rate_limit_pool", new=AsyncMock()) as close_redis_rate_limit_pool_mock,
        patch("src.app.core.setup.shutdown_sentry", new=AsyncMock()) as shutdown_sentry_mock,
        patch("src.app.core.setup.init_sentry") as init_sentry_mock,
    ):
        with pytest.raises(RuntimeError, match="queue startup failed"):
            async with lifespan_factory(settings)(app):
                raise AssertionError("lifespan should fail before yielding")

    initialize_database_engine_mock.assert_awaited_once_with(settings)
    create_redis_cache_pool_mock.assert_awaited_once_with(settings)
    create_redis_queue_pool_mock.assert_awaited_once_with(settings)
    close_redis_cache_pool_mock.assert_awaited_once_with()
    close_database_engine_mock.assert_awaited_once_with()
    close_redis_queue_pool_mock.assert_not_awaited()
    close_redis_rate_limit_pool_mock.assert_not_awaited()
    shutdown_sentry_mock.assert_not_awaited()
    init_sentry_mock.assert_not_called()
    assert not app.state.initialization_complete.is_set()


@pytest.mark.asyncio
async def test_lifespan_continues_cleanup_when_one_shutdown_step_fails() -> None:
    custom_settings = load_settings(
        _env_file=None,
        SENTRY_ENABLE=True,
        SENTRY_DSN="https://public@example.ingest.sentry.io/1",
    )
    app = FastAPI()

    with (
        patch("src.app.core.setup.set_threadpool_tokens", new=AsyncMock()),
        patch("src.app.core.setup.initialize_database_engine", new=AsyncMock()),
        patch("src.app.core.setup.create_redis_cache_pool", new=AsyncMock()),
        patch("src.app.core.setup.create_redis_queue_pool", new=AsyncMock()),
        patch("src.app.core.setup.create_redis_rate_limit_pool", new=AsyncMock()),
        patch("src.app.core.setup.close_database_engine", new=AsyncMock()) as close_database_engine_mock,
        patch("src.app.core.setup.close_redis_cache_pool", new=AsyncMock()) as close_redis_cache_pool_mock,
        patch("src.app.core.setup.close_redis_queue_pool", new=AsyncMock()) as close_redis_queue_pool_mock,
        patch("src.app.core.setup.close_redis_rate_limit_pool", new=AsyncMock()) as close_redis_rate_limit_pool_mock,
        patch("src.app.core.setup.init_sentry"),
        patch(
            "src.app.core.setup.shutdown_sentry",
            new=AsyncMock(side_effect=RuntimeError("sentry cleanup failed")),
        ) as shutdown_sentry_mock,
    ):
        with pytest.raises(RuntimeError, match="sentry cleanup failed"):
            async with lifespan_factory(custom_settings)(app):
                assert app.state.initialization_complete.is_set()

    shutdown_sentry_mock.assert_awaited_once_with(custom_settings)
    close_redis_rate_limit_pool_mock.assert_awaited_once_with()
    close_redis_queue_pool_mock.assert_awaited_once_with()
    close_redis_cache_pool_mock.assert_awaited_once_with()
    close_database_engine_mock.assert_awaited_once_with()


def test_create_application_uses_cors_runtime_settings() -> None:
    custom_settings = load_settings(
        _env_file=None,
        CORS_ORIGINS=["https://app.example.com"],
        CORS_ALLOW_CREDENTIALS=False,
        CORS_METHODS=["GET", "POST"],
        CORS_HEADERS=["Authorization", "Content-Type"],
        CORS_EXPOSE_HEADERS=["X-Request-ID"],
        CORS_MAX_AGE=900,
    )

    app = create_application(APIRouter(), custom_settings)
    cors_middleware = next(mw for mw in app.user_middleware if mw.cls is CORSMiddleware)

    assert cors_middleware.kwargs["allow_origins"] == ["https://app.example.com"]
    assert cors_middleware.kwargs["allow_credentials"] is False
    assert cors_middleware.kwargs["allow_methods"] == ["GET", "POST"]
    assert cors_middleware.kwargs["allow_headers"] == ["Authorization", "Content-Type"]
    assert cors_middleware.kwargs["expose_headers"] == ["X-Request-ID"]
    assert cors_middleware.kwargs["max_age"] == 900


def test_create_application_skips_client_cache_when_feature_toggle_is_disabled() -> None:
    custom_settings = load_settings(
        _env_file=None,
        FEATURE_CLIENT_CACHE_ENABLED=False,
        CLIENT_CACHE_MAX_AGE=900,
    )

    app = create_application(APIRouter(), custom_settings)

    assert not any(mw.cls is ClientCacheMiddleware for mw in app.user_middleware)


def test_create_application_uses_security_header_runtime_settings() -> None:
    custom_settings = load_settings(
        _env_file=None,
        SECURITY_HEADERS_CONTENT_SECURITY_POLICY="default-src 'self'",
        SECURITY_HEADERS_PERMISSIONS_POLICY="geolocation=()",
        SECURITY_HEADERS_HSTS_ENABLED=True,
        SECURITY_HEADERS_HSTS_MAX_AGE_SECONDS=600,
    )

    app = create_application(APIRouter(), custom_settings)
    security_headers_middleware = next(mw for mw in app.user_middleware if mw.cls is SecurityHeadersMiddleware)

    assert security_headers_middleware.kwargs["headers"]["X-Frame-Options"] == "DENY"
    assert security_headers_middleware.kwargs["headers"]["X-Content-Type-Options"] == "nosniff"
    assert (
        security_headers_middleware.kwargs["headers"]["Referrer-Policy"] == "strict-origin-when-cross-origin"
    )
    assert security_headers_middleware.kwargs["headers"]["Content-Security-Policy"] == "default-src 'self'"
    assert security_headers_middleware.kwargs["headers"]["Permissions-Policy"] == "geolocation=()"
    assert (
        security_headers_middleware.kwargs["headers"]["Strict-Transport-Security"] == "max-age=600; includeSubDomains"
    )


def test_security_headers_middleware_applies_runtime_headers_to_responses() -> None:
    router = APIRouter()

    @router.get("/security-probe")
    async def security_probe() -> dict[str, bool]:
        return {"ok": True}

    custom_settings = load_settings(
        _env_file=None,
        SECURITY_HEADERS_CONTENT_SECURITY_POLICY="default-src 'self'",
        SECURITY_HEADERS_PERMISSIONS_POLICY="geolocation=()",
        SECURITY_HEADERS_HSTS_ENABLED=True,
        SECURITY_HEADERS_HSTS_MAX_AGE_SECONDS=600,
        SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS=False,
    )

    app = create_application(router, custom_settings, lifespan=noop_lifespan)

    with TestClient(app) as client:
        response = client.get("/security-probe")

    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["content-security-policy"] == "default-src 'self'"
    assert response.headers["permissions-policy"] == "geolocation=()"
    assert response.headers["strict-transport-security"] == "max-age=600"


def test_create_application_uses_trusted_host_runtime_settings() -> None:
    custom_settings = load_settings(
        _env_file=None,
        TRUSTED_HOSTS=["api.example.com", "*.example.com"],
        TRUSTED_HOSTS_WWW_REDIRECT=False,
    )

    app = create_application(APIRouter(), custom_settings)
    trusted_host_middleware = next(mw for mw in app.user_middleware if mw.cls is TrustedHostMiddleware)

    assert trusted_host_middleware.kwargs["allowed_hosts"] == ["api.example.com", "*.example.com"]
    assert trusted_host_middleware.kwargs["www_redirect"] is False


def test_create_application_uses_proxy_header_runtime_settings() -> None:
    custom_settings = load_settings(
        _env_file=None,
        PROXY_HEADERS_ENABLED=True,
        PROXY_HEADERS_TRUSTED_PROXIES=["127.0.0.1", "10.0.0.0/8"],
    )

    app = create_application(APIRouter(), custom_settings)
    proxy_headers_middleware = next(mw for mw in app.user_middleware if mw.cls is ProxyHeadersMiddleware)

    assert proxy_headers_middleware.kwargs["trusted_hosts"] == ["127.0.0.1", "10.0.0.0/8"]
