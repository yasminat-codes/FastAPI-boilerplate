from asyncio import Event, Lock
from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, _AsyncGeneratorContextManager, asynccontextmanager
from typing import Any, cast

import anyio
import fastapi
import redis.asyncio as redis
from arq import create_pool
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from ..api.dependencies import get_current_superuser
from ..api.errors import register_api_exception_handlers
from ..core.logger import logging
from ..core.utils.rate_limit import rate_limiter
from ..middleware.client_cache_middleware import ClientCacheMiddleware
from ..middleware.logger_middleware import LoggerMiddleware
from ..middleware.security_headers_middleware import SecurityHeadersMiddleware, build_security_headers
from ..models import *  # noqa: F403
from .config import (
    AppSettings,
    ClientSideCacheSettings,
    CORSSettings,
    EnvironmentOption,
    EnvironmentSettings,
    FeatureFlagsSettings,
    PostgresSettings,
    ProxyHeadersSettings,
    RedisCacheSettings,
    RedisQueueSettings,
    RedisRateLimiterSettings,
    SecurityHeadersSettings,
    SentrySettings,
    TrustedHostSettings,
    settings,
)
from .db.database import async_engine
from .db.database import initialize_database_engine as initialize_runtime_database_engine
from .redis import build_arq_redis_settings, build_redis_pool_kwargs
from .utils import cache, queue

logger = logging.getLogger(__name__)

API_SHUTDOWN_WAIT_SECONDS = 30.0
API_SHUTDOWN_DETAIL = "The application is shutting down."


async def _aclose_if_supported(resource: Any) -> None:
    aclose = getattr(resource, "aclose", None)
    if callable(aclose):
        await aclose()


# -------------- api shutdown --------------
def initialize_api_lifecycle_state(app: FastAPI) -> None:
    """Attach reusable startup and shutdown state to the FastAPI app."""

    app.state.initialization_complete = Event()
    app.state.shutdown_in_progress = Event()
    app.state.active_request_lock = Lock()
    app.state.active_request_count = 0
    app.state.active_requests_drained = Event()
    app.state.active_requests_drained.set()


async def begin_api_request(app: FastAPI) -> None:
    """Track a new in-flight API request."""

    active_request_lock = getattr(app.state, "active_request_lock", None)
    active_requests_drained = getattr(app.state, "active_requests_drained", None)
    if active_request_lock is None or active_requests_drained is None:
        return

    async with active_request_lock:
        app.state.active_request_count += 1
        active_requests_drained.clear()


async def end_api_request(app: FastAPI) -> None:
    """Release a finished API request and signal when the app is drained."""

    active_request_lock = getattr(app.state, "active_request_lock", None)
    active_requests_drained = getattr(app.state, "active_requests_drained", None)
    if active_request_lock is None or active_requests_drained is None:
        return

    async with active_request_lock:
        app.state.active_request_count -= 1
        if app.state.active_request_count <= 0:
            app.state.active_request_count = 0
            active_requests_drained.set()


async def mark_api_shutdown_in_progress(app: FastAPI) -> None:
    """Signal that the API process is shutting down."""

    if getattr(app.state, "shutdown_in_progress", None) is not None:
        app.state.shutdown_in_progress.set()


async def wait_for_api_requests_to_drain(app: FastAPI, timeout: float = API_SHUTDOWN_WAIT_SECONDS) -> None:
    """Wait for all in-flight API requests to complete during shutdown."""

    shutdown_in_progress = getattr(app.state, "shutdown_in_progress", None)
    active_requests_drained = getattr(app.state, "active_requests_drained", None)
    if shutdown_in_progress is None or active_requests_drained is None:
        return

    if not shutdown_in_progress.is_set() or active_requests_drained.is_set():
        return

    with anyio.move_on_after(timeout) as scope:
        await active_requests_drained.wait()

    if scope.cancel_called:
        logger.warning("Timed out waiting for in-flight API requests to drain during shutdown")


class GracefulShutdownMiddleware(BaseHTTPMiddleware):
    """Reject new requests once shutdown begins and track in-flight requests."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        shutdown_in_progress = getattr(request.app.state, "shutdown_in_progress", None)
        if shutdown_in_progress is not None and shutdown_in_progress.is_set():
            return JSONResponse(status_code=503, content={"detail": API_SHUTDOWN_DETAIL})

        await begin_api_request(request.app)
        try:
            response = await call_next(request)
        finally:
            await end_api_request(request.app)

        return response


# -------------- database --------------
async def initialize_database_engine(db_settings: PostgresSettings | None = None) -> None:
    configured_settings = settings if db_settings is None else db_settings
    await initialize_runtime_database_engine(configured_settings)


async def close_database_engine() -> None:
    await async_engine.dispose()


# -------------- cache --------------
async def create_redis_cache_pool(cache_settings: RedisCacheSettings | None = None) -> None:
    cache_settings = settings if cache_settings is None else cache_settings

    cache_pool: Any = redis.ConnectionPool.from_url(
        cache_settings.REDIS_CACHE_URL,
        **build_redis_pool_kwargs(
            connect_timeout=cache_settings.REDIS_CACHE_CONNECT_TIMEOUT,
            socket_timeout=cache_settings.REDIS_CACHE_SOCKET_TIMEOUT,
            retry_attempts=cache_settings.REDIS_CACHE_RETRY_ATTEMPTS,
            retry_base_delay=cache_settings.REDIS_CACHE_RETRY_BASE_DELAY,
            retry_max_delay=cache_settings.REDIS_CACHE_RETRY_MAX_DELAY,
            retry_on_timeout=cache_settings.REDIS_CACHE_RETRY_ON_TIMEOUT,
            max_connections=cache_settings.REDIS_CACHE_MAX_CONNECTIONS,
            ssl_enabled=cache_settings.REDIS_CACHE_SSL,
            ssl_check_hostname=cache_settings.REDIS_CACHE_SSL_CHECK_HOSTNAME,
            ssl_cert_reqs=cache_settings.REDIS_CACHE_SSL_CERT_REQS.value,
            ssl_ca_certs=cache_settings.REDIS_CACHE_SSL_CA_CERTS,
            ssl_certfile=cache_settings.REDIS_CACHE_SSL_CERTFILE,
            ssl_keyfile=cache_settings.REDIS_CACHE_SSL_KEYFILE,
        ),
    )
    cache_client = redis.Redis.from_pool(cache_pool)  # type: ignore

    try:
        await cache_client.ping()
    except Exception:
        await _aclose_if_supported(cache_client)
        await _aclose_if_supported(cache_pool)
        raise

    cache.pool = cache_pool
    cache.client = cache_client


async def close_redis_cache_pool() -> None:
    cache_client = cache.client
    cache_pool = cache.pool
    cache.client = None
    cache.pool = None

    await _aclose_if_supported(cache_client)
    await _aclose_if_supported(cache_pool)


# -------------- queue --------------
async def create_redis_queue_pool(queue_settings: RedisQueueSettings | None = None) -> None:
    queue_settings = settings if queue_settings is None else queue_settings

    queue_pool = await create_pool(
        build_arq_redis_settings(
            host=queue_settings.REDIS_QUEUE_HOST,
            port=queue_settings.REDIS_QUEUE_PORT,
            database=queue_settings.REDIS_QUEUE_DB,
            username=queue_settings.REDIS_QUEUE_USERNAME,
            password=queue_settings.REDIS_QUEUE_PASSWORD,
            ssl_enabled=queue_settings.REDIS_QUEUE_SSL,
            ssl_keyfile=queue_settings.REDIS_QUEUE_SSL_KEYFILE,
            ssl_certfile=queue_settings.REDIS_QUEUE_SSL_CERTFILE,
            ssl_cert_reqs=queue_settings.REDIS_QUEUE_SSL_CERT_REQS.value,
            ssl_ca_certs=queue_settings.REDIS_QUEUE_SSL_CA_CERTS,
            ssl_check_hostname=queue_settings.REDIS_QUEUE_SSL_CHECK_HOSTNAME,
            connect_timeout=queue_settings.REDIS_QUEUE_CONNECT_TIMEOUT,
            connect_retries=queue_settings.REDIS_QUEUE_CONNECT_RETRIES,
            retry_delay=queue_settings.REDIS_QUEUE_RETRY_DELAY,
            max_connections=queue_settings.REDIS_QUEUE_MAX_CONNECTIONS,
            retry_on_timeout=queue_settings.REDIS_QUEUE_RETRY_ON_TIMEOUT,
        )
    )

    try:
        await queue_pool.ping()  # type: ignore[attr-defined]
    except Exception:
        await _aclose_if_supported(queue_pool)
        raise

    queue.pool = queue_pool


async def close_redis_queue_pool() -> None:
    queue_pool = queue.pool
    queue.pool = None

    await _aclose_if_supported(queue_pool)


# -------------- rate limit --------------
async def create_redis_rate_limit_pool(rate_limit_settings: RedisRateLimiterSettings | None = None) -> None:
    rate_limit_settings = settings if rate_limit_settings is None else rate_limit_settings

    rate_limiter.initialize(
        rate_limit_settings.REDIS_RATE_LIMIT_URL,
        **build_redis_pool_kwargs(
            connect_timeout=rate_limit_settings.REDIS_RATE_LIMIT_CONNECT_TIMEOUT,
            socket_timeout=rate_limit_settings.REDIS_RATE_LIMIT_SOCKET_TIMEOUT,
            retry_attempts=rate_limit_settings.REDIS_RATE_LIMIT_RETRY_ATTEMPTS,
            retry_base_delay=rate_limit_settings.REDIS_RATE_LIMIT_RETRY_BASE_DELAY,
            retry_max_delay=rate_limit_settings.REDIS_RATE_LIMIT_RETRY_MAX_DELAY,
            retry_on_timeout=rate_limit_settings.REDIS_RATE_LIMIT_RETRY_ON_TIMEOUT,
            max_connections=rate_limit_settings.REDIS_RATE_LIMIT_MAX_CONNECTIONS,
            ssl_enabled=rate_limit_settings.REDIS_RATE_LIMIT_SSL,
            ssl_check_hostname=rate_limit_settings.REDIS_RATE_LIMIT_SSL_CHECK_HOSTNAME,
            ssl_cert_reqs=rate_limit_settings.REDIS_RATE_LIMIT_SSL_CERT_REQS.value,
            ssl_ca_certs=rate_limit_settings.REDIS_RATE_LIMIT_SSL_CA_CERTS,
            ssl_certfile=rate_limit_settings.REDIS_RATE_LIMIT_SSL_CERTFILE,
            ssl_keyfile=rate_limit_settings.REDIS_RATE_LIMIT_SSL_KEYFILE,
        ),
    )  # type: ignore[arg-type]

    try:
        await rate_limiter.get_client().ping()
    except Exception:
        await rate_limiter.shutdown()
        raise


async def close_redis_rate_limit_pool() -> None:
    await rate_limiter.shutdown()


# -------------- sentry --------------
def init_sentry(sentry_settings: SentrySettings | None = None) -> None:
    sentry_settings = settings if sentry_settings is None else sentry_settings

    if not sentry_settings.SENTRY_ENABLE:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration

    sentry_sdk.init(
        dsn=sentry_settings.SENTRY_DSN.get_secret_value() if sentry_settings.SENTRY_DSN else None,
        environment=sentry_settings.SENTRY_ENVIRONMENT,
        release=sentry_settings.SENTRY_RELEASE,
        debug=sentry_settings.SENTRY_DEBUG,
        attach_stacktrace=sentry_settings.SENTRY_ATTACH_STACKTRACE,
        send_default_pii=sentry_settings.SENTRY_SEND_DEFAULT_PII,
        max_breadcrumbs=sentry_settings.SENTRY_MAX_BREADCRUMBS,
        traces_sample_rate=sentry_settings.SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=sentry_settings.SENTRY_PROFILES_SAMPLE_RATE,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
        ],
    )


async def shutdown_sentry(sentry_settings: SentrySettings | None = None) -> None:
    sentry_settings = settings if sentry_settings is None else sentry_settings

    if not sentry_settings.SENTRY_ENABLE:
        return
    import sentry_sdk

    sentry_sdk.flush()


# -------------- application --------------
async def set_threadpool_tokens(number_of_tokens: int = 100) -> None:
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = number_of_tokens


def lifespan_factory(
    settings: (
        PostgresSettings
        | RedisCacheSettings
        | AppSettings
        | ClientSideCacheSettings
        | FeatureFlagsSettings
        | CORSSettings
        | RedisQueueSettings
        | RedisRateLimiterSettings
        | EnvironmentSettings
        | SentrySettings
        | SecurityHeadersSettings
        | TrustedHostSettings
        | ProxyHeadersSettings
    ),
) -> Callable[[FastAPI], _AsyncGeneratorContextManager[Any]]:
    """Factory to create a lifespan async context manager for a FastAPI app."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator:
        initialize_api_lifecycle_state(app)

        await set_threadpool_tokens()

        async with AsyncExitStack() as resource_stack:
            if isinstance(settings, PostgresSettings):
                await initialize_database_engine(settings)
                resource_stack.push_async_callback(close_database_engine)

            if isinstance(settings, RedisCacheSettings):
                await create_redis_cache_pool(settings)
                resource_stack.push_async_callback(close_redis_cache_pool)

            if isinstance(settings, RedisQueueSettings):
                await create_redis_queue_pool(settings)
                resource_stack.push_async_callback(close_redis_queue_pool)

            if isinstance(settings, RedisRateLimiterSettings):
                await create_redis_rate_limit_pool(settings)
                resource_stack.push_async_callback(close_redis_rate_limit_pool)

            if isinstance(settings, SentrySettings):
                init_sentry(settings)
                resource_stack.push_async_callback(shutdown_sentry, settings)

            app.state.initialization_complete.set()

            try:
                yield
            except Exception:
                logger.exception("Application lifespan exited with an error; shared resources will be cleaned up")
                raise
            finally:
                await mark_api_shutdown_in_progress(app)
                await wait_for_api_requests_to_drain(app)

    return lifespan


# -------------- application --------------
def create_application(
    router: APIRouter,
    settings: (
        PostgresSettings
        | RedisCacheSettings
        | AppSettings
        | ClientSideCacheSettings
        | FeatureFlagsSettings
        | CORSSettings
        | RedisQueueSettings
        | RedisRateLimiterSettings
        | EnvironmentSettings
        | SentrySettings
        | SecurityHeadersSettings
        | TrustedHostSettings
        | ProxyHeadersSettings
    ),
    lifespan: Callable[[FastAPI], _AsyncGeneratorContextManager[Any]] | None = None,
    **kwargs: Any,
) -> FastAPI:
    """Creates and configures a FastAPI application based on the provided settings.

    This function initializes a FastAPI application and configures it with various settings
    and handlers based on the type of the `settings` object provided.

    Parameters
    ----------
    router : APIRouter
        The APIRouter object containing the routes to be included in the FastAPI application.

    settings
        An instance representing the settings for configuring the FastAPI application.
        It determines the configuration applied:

        - AppSettings: Configures basic app metadata like name, description, contact, and license info.
        - PostgresSettings: Primes and disposes the shared SQLAlchemy async engine through lifespan.
        - RedisCacheSettings: Sets up event handlers for creating and closing a Redis cache pool.
        - ClientSideCacheSettings: Integrates middleware for client-side caching.
        - FeatureFlagsSettings: Allows template-owned modules such as client cache to be toggled off.
        - CORSSettings: Integrates CORS middleware with specified origins.
        - SecurityHeadersSettings: Applies template-owned HTTP security headers through middleware.
        - TrustedHostSettings: Enables host-header allowlisting when trusted hosts are configured.
        - ProxyHeadersSettings: Honors forwarded client IP and scheme only from explicitly trusted proxies.
        - GracefulShutdownMiddleware: Tracks in-flight requests and rejects new work once shutdown begins.
        - RedisQueueSettings: Sets up event handlers for creating and closing a Redis queue pool.
        - RedisRateLimiterSettings: Sets up event handlers for creating and closing a Redis rate limiter pool.
        - EnvironmentSettings: Conditionally sets documentation URLs and integrates custom routes for API documentation
          based on the environment type.

    **kwargs
        Additional keyword arguments passed directly to the FastAPI constructor.

    Returns
    -------
    FastAPI
        A fully configured FastAPI application instance.

    The function configures the FastAPI application with different features and behaviors
    based on the provided settings. It includes setting up database connections, Redis pools
    for caching, queue, and rate limiting, client-side caching, and customizing the API documentation
    based on the environment settings.
    """
    # --- before creating application ---
    if isinstance(settings, AppSettings):
        to_update = {
            "title": settings.APP_NAME,
            "description": settings.APP_DESCRIPTION,
            "contact": {"name": settings.CONTACT_NAME, "email": settings.CONTACT_EMAIL},
            "license_info": {"name": settings.LICENSE_NAME},
        }
        kwargs.update(to_update)

    if isinstance(settings, EnvironmentSettings):
        kwargs.update({"docs_url": None, "redoc_url": None, "openapi_url": None})

    # Use custom lifespan if provided, otherwise use default factory
    if lifespan is None:
        lifespan = lifespan_factory(settings)

    application = FastAPI(lifespan=lifespan, **kwargs)
    register_api_exception_handlers(application)
    application.include_router(router)

    if isinstance(settings, ClientSideCacheSettings) and (
        not isinstance(settings, FeatureFlagsSettings) or settings.FEATURE_CLIENT_CACHE_ENABLED
    ):
        application.add_middleware(ClientCacheMiddleware, max_age=settings.CLIENT_CACHE_MAX_AGE)

    application.add_middleware(GracefulShutdownMiddleware)

    if isinstance(settings, CORSSettings) and settings.CORS_ORIGINS:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
            allow_methods=settings.CORS_METHODS,
            allow_headers=settings.CORS_HEADERS,
            expose_headers=settings.CORS_EXPOSE_HEADERS,
            max_age=settings.CORS_MAX_AGE,
        )

    if isinstance(settings, SecurityHeadersSettings):
        security_headers = build_security_headers(settings)
        if security_headers:
            application.add_middleware(SecurityHeadersMiddleware, headers=security_headers)

    if isinstance(settings, TrustedHostSettings) and settings.TRUSTED_HOSTS:
        application.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.TRUSTED_HOSTS,
            www_redirect=settings.TRUSTED_HOSTS_WWW_REDIRECT,
        )

    application.add_middleware(LoggerMiddleware)

    if isinstance(settings, ProxyHeadersSettings) and settings.PROXY_HEADERS_ENABLED:
        application.add_middleware(
            cast(Any, ProxyHeadersMiddleware),
            trusted_hosts=settings.PROXY_HEADERS_TRUSTED_PROXIES,
        )

    if isinstance(settings, EnvironmentSettings):
        if settings.ENVIRONMENT != EnvironmentOption.PRODUCTION:
            docs_router = APIRouter()
            if settings.ENVIRONMENT != EnvironmentOption.LOCAL:
                docs_router = APIRouter(dependencies=[Depends(get_current_superuser)])

            @docs_router.get("/docs", include_in_schema=False)
            async def get_swagger_documentation() -> fastapi.responses.HTMLResponse:
                return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")

            @docs_router.get("/redoc", include_in_schema=False)
            async def get_redoc_documentation() -> fastapi.responses.HTMLResponse:
                return get_redoc_html(openapi_url="/openapi.json", title="docs")

            @docs_router.get("/openapi.json", include_in_schema=False)
            async def openapi() -> dict[str, Any]:
                out: dict = get_openapi(title=application.title, version=application.version, routes=application.routes)
                return out

            application.include_router(docs_router)

    return application
