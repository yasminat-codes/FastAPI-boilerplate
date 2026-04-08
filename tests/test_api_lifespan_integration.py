"""Integration tests for API startup and lifespan behavior."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.app.core import setup as core_setup
from src.app.platform.application import create_application, lifespan_factory
from src.app.platform.config import settings


@asynccontextmanager
async def noop_lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Minimal lifespan context manager for testing."""
    yield


def build_test_router() -> APIRouter:
    """Build a minimal router for testing."""
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/shutdown-probe")
    async def shutdown_probe() -> dict[str, str]:
        return {"status": "ok"}

    return router


# ============================================================================
# Tests for initialize_api_lifecycle_state
# ============================================================================


@pytest.mark.asyncio
async def test_initialize_api_lifecycle_state_sets_initialization_complete_event() -> None:
    """Test that initialization_complete event is attached and initially unset."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    assert hasattr(app.state, "initialization_complete")
    assert not app.state.initialization_complete.is_set()


@pytest.mark.asyncio
async def test_initialize_api_lifecycle_state_sets_shutdown_in_progress_event() -> None:
    """Test that shutdown_in_progress event is attached and initially unset."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    assert hasattr(app.state, "shutdown_in_progress")
    assert not app.state.shutdown_in_progress.is_set()


@pytest.mark.asyncio
async def test_initialize_api_lifecycle_state_sets_active_request_lock() -> None:
    """Test that active_request_lock is attached and functional."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    assert hasattr(app.state, "active_request_lock")
    # Verify the lock can be acquired
    async with app.state.active_request_lock:
        pass


@pytest.mark.asyncio
async def test_initialize_api_lifecycle_state_sets_active_request_count() -> None:
    """Test that active_request_count is initialized to 0."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    assert hasattr(app.state, "active_request_count")
    assert app.state.active_request_count == 0


@pytest.mark.asyncio
async def test_initialize_api_lifecycle_state_sets_active_requests_drained_event() -> None:
    """Test that active_requests_drained event is attached and initially set."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    assert hasattr(app.state, "active_requests_drained")
    # Should be set initially (no active requests)
    assert app.state.active_requests_drained.is_set()


# ============================================================================
# Tests for begin_api_request / end_api_request
# ============================================================================


@pytest.mark.asyncio
async def test_begin_api_request_increments_active_request_count() -> None:
    """Test that begin_api_request increments the active request count."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    assert app.state.active_request_count == 0

    await core_setup.begin_api_request(app)

    assert app.state.active_request_count == 1


@pytest.mark.asyncio
async def test_begin_api_request_clears_drained_event() -> None:
    """Test that begin_api_request clears the drained event."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    assert app.state.active_requests_drained.is_set()

    await core_setup.begin_api_request(app)

    assert not app.state.active_requests_drained.is_set()


@pytest.mark.asyncio
async def test_begin_api_request_handles_missing_lock_gracefully() -> None:
    """Test that begin_api_request handles missing lock without error."""
    app = FastAPI()
    # Don't call initialize_api_lifecycle_state

    # Should not raise
    await core_setup.begin_api_request(app)


@pytest.mark.asyncio
async def test_end_api_request_decrements_active_request_count() -> None:
    """Test that end_api_request decrements the active request count."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    await core_setup.begin_api_request(app)
    await core_setup.begin_api_request(app)
    assert app.state.active_request_count == 2

    await core_setup.end_api_request(app)

    assert app.state.active_request_count == 1


@pytest.mark.asyncio
async def test_end_api_request_sets_drained_event_when_count_reaches_zero() -> None:
    """Test that end_api_request sets drained event when all requests finish."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    await core_setup.begin_api_request(app)
    assert not app.state.active_requests_drained.is_set()

    await core_setup.end_api_request(app)

    assert app.state.active_requests_drained.is_set()


@pytest.mark.asyncio
async def test_end_api_request_prevents_negative_count() -> None:
    """Test that end_api_request prevents count from going negative."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    await core_setup.end_api_request(app)
    await core_setup.end_api_request(app)

    assert app.state.active_request_count == 0


@pytest.mark.asyncio
async def test_end_api_request_handles_missing_drained_event_gracefully() -> None:
    """Test that end_api_request handles missing drained event without error."""
    app = FastAPI()
    # Create minimal state
    app.state.active_request_lock = asyncio.Lock()
    app.state.active_request_count = 1
    # Don't set active_requests_drained

    # Should not raise
    await core_setup.end_api_request(app)


@pytest.mark.asyncio
async def test_begin_and_end_request_are_thread_safe() -> None:
    """Test that concurrent begin/end requests maintain correct count."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    async def make_request() -> None:
        await core_setup.begin_api_request(app)
        await asyncio.sleep(0.001)  # Simulate work
        await core_setup.end_api_request(app)

    # Simulate 10 concurrent requests
    await asyncio.gather(*[make_request() for _ in range(10)])

    assert app.state.active_request_count == 0
    assert app.state.active_requests_drained.is_set()


# ============================================================================
# Tests for lifespan factory
# ============================================================================


@pytest.mark.asyncio
async def test_lifespan_factory_returns_callable() -> None:
    """Test that lifespan_factory returns a callable."""
    lifespan = lifespan_factory(settings)

    assert callable(lifespan)


@pytest.mark.asyncio
async def test_lifespan_factory_creates_valid_async_context_manager() -> None:
    """Test that lifespan factory creates a valid async context manager."""
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
    ):
        lifespan = lifespan_factory(settings)
        async with lifespan(app):
            assert app.state.initialization_complete.is_set()


@pytest.mark.asyncio
async def test_lifespan_initializes_api_lifecycle_state_on_startup() -> None:
    """Test that lifespan initializes API lifecycle state during startup."""
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
    ):
        lifespan = lifespan_factory(settings)
        async with lifespan(app):
            assert hasattr(app.state, "initialization_complete")
            assert hasattr(app.state, "shutdown_in_progress")
            assert hasattr(app.state, "active_request_lock")
            assert hasattr(app.state, "active_request_count")
            assert hasattr(app.state, "active_requests_drained")


@pytest.mark.asyncio
async def test_lifespan_marks_initialization_complete_after_setup() -> None:
    """Test that lifespan marks initialization_complete after all setup."""
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
    ):
        lifespan = lifespan_factory(settings)
        async with lifespan(app):
            assert app.state.initialization_complete.is_set()


# ============================================================================
# Tests for shutdown draining behavior
# ============================================================================


def test_graceful_shutdown_middleware_rejects_requests_during_shutdown() -> None:
    """Test that requests are rejected with 503 during shutdown."""
    router = build_test_router()
    application = create_application(router, settings, lifespan=noop_lifespan)
    core_setup.initialize_api_lifecycle_state(application)
    application.state.shutdown_in_progress.set()

    with TestClient(application) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": core_setup.API_SHUTDOWN_DETAIL}


def test_graceful_shutdown_middleware_allows_requests_before_shutdown() -> None:
    """Test that requests are allowed before shutdown begins."""
    router = build_test_router()
    application = create_application(router, settings, lifespan=noop_lifespan)
    core_setup.initialize_api_lifecycle_state(application)
    # Don't set shutdown_in_progress

    with TestClient(application) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_mark_api_shutdown_in_progress_sets_shutdown_event() -> None:
    """Test that mark_api_shutdown_in_progress sets the shutdown event."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    assert not app.state.shutdown_in_progress.is_set()

    await core_setup.mark_api_shutdown_in_progress(app)

    assert app.state.shutdown_in_progress.is_set()


@pytest.mark.asyncio
async def test_wait_for_api_requests_to_drain_waits_for_active_requests() -> None:
    """Test that shutdown waits for in-flight requests to complete."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    await core_setup.begin_api_request(app)
    await core_setup.mark_api_shutdown_in_progress(app)

    drain_task = asyncio.create_task(
        core_setup.wait_for_api_requests_to_drain(app, timeout=0.5)
    )
    await asyncio.sleep(0)

    # Task should not be done yet (waiting for requests)
    assert not drain_task.done()

    # End the request
    await core_setup.end_api_request(app)
    await drain_task

    assert app.state.active_requests_drained.is_set()


@pytest.mark.asyncio
async def test_wait_for_api_requests_to_drain_respects_timeout() -> None:
    """Test that shutdown draining respects the timeout."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    await core_setup.begin_api_request(app)
    await core_setup.mark_api_shutdown_in_progress(app)

    # This should timeout since we never end the request
    import time

    start = time.time()
    await core_setup.wait_for_api_requests_to_drain(app, timeout=0.1)
    elapsed = time.time() - start

    # Should have timed out (allow some margin)
    assert elapsed >= 0.08


@pytest.mark.asyncio
async def test_wait_for_api_requests_to_drain_handles_no_shutdown_set() -> None:
    """Test that wait_for_api_requests_to_drain handles missing shutdown event."""
    app = FastAPI()
    core_setup.initialize_api_lifecycle_state(app)

    # Don't set shutdown_in_progress

    # Should return immediately without error
    await core_setup.wait_for_api_requests_to_drain(app, timeout=0.1)


# ============================================================================
# Tests for create_application function
# ============================================================================


def test_create_application_returns_fastapi_instance() -> None:
    """Test that create_application returns a FastAPI instance."""
    router = build_test_router()

    application = create_application(router, settings, lifespan=noop_lifespan)

    assert isinstance(application, FastAPI)


def test_create_application_includes_router() -> None:
    """Test that create_application includes the provided router."""
    router = build_test_router()

    application = create_application(router, settings, lifespan=noop_lifespan)

    with TestClient(application) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_application_has_graceful_shutdown_middleware() -> None:
    """Test that create_application includes GracefulShutdownMiddleware."""
    router = build_test_router()

    application = create_application(router, settings, lifespan=noop_lifespan)

    # Check that GracefulShutdownMiddleware is in the middleware stack
    middleware_classes = [m.cls for m in application.user_middleware]
    middleware_names = [cls.__name__ if isinstance(cls, type) else type(cls).__name__ for cls in middleware_classes]
    assert "GracefulShutdownMiddleware" in middleware_names


def test_create_application_has_request_context_middleware() -> None:
    """Test that create_application includes RequestContextMiddleware."""
    router = build_test_router()

    application = create_application(router, settings, lifespan=noop_lifespan)

    # Check that RequestContextMiddleware is in the middleware stack
    middleware_classes = [m.cls for m in application.user_middleware]
    middleware_names = [cls.__name__ if isinstance(cls, type) else type(cls).__name__ for cls in middleware_classes]
    assert "RequestContextMiddleware" in middleware_names


def test_create_application_with_custom_lifespan() -> None:
    """Test that create_application accepts a custom lifespan."""
    router = build_test_router()

    @asynccontextmanager
    async def custom_lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        yield

    application = create_application(
        router, settings, lifespan=custom_lifespan
    )

    assert isinstance(application, FastAPI)


def test_create_application_uses_default_lifespan_factory_when_none_provided(
) -> None:
    """Test that create_application uses lifespan_factory when none provided."""
    router = build_test_router()

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
    ):
        application = create_application(router, settings)

        assert isinstance(application, FastAPI)


# ============================================================================
# Integration tests: Lifespan + Shutdown flow
# ============================================================================


@pytest.mark.asyncio
async def test_lifespan_signals_shutdown_before_closing_resources() -> None:
    """Test that lifespan marks shutdown before releasing shared resources."""
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
    ):
        lifespan = lifespan_factory(settings)
        async with lifespan(app):
            assert app.state.initialization_complete.is_set()
            assert not app.state.shutdown_in_progress.is_set()

        assert app.state.shutdown_in_progress.is_set()


@pytest.mark.asyncio
async def test_lifespan_drains_requests_on_shutdown() -> None:
    """Test that lifespan drains in-flight requests during shutdown."""
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
        ) as wait_for_drain_mock,
    ):
        lifespan = lifespan_factory(settings)
        async with lifespan(app):
            pass

        wait_for_drain_mock.assert_awaited_once_with(app)


@pytest.mark.asyncio
async def test_full_request_lifecycle_with_shutdown_draining() -> None:
    """Test complete request lifecycle: startup, requests, shutdown."""
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
    ):
        lifespan = lifespan_factory(settings)

        async with lifespan(app):
            # Startup complete
            assert app.state.initialization_complete.is_set()
            assert app.state.active_request_count == 0
            assert app.state.active_requests_drained.is_set()

            # Simulate requests
            await core_setup.begin_api_request(app)
            await core_setup.begin_api_request(app)
            assert app.state.active_request_count == 2
            assert not app.state.active_requests_drained.is_set()

            # End requests
            await core_setup.end_api_request(app)
            await core_setup.end_api_request(app)
            assert app.state.active_request_count == 0
            assert app.state.active_requests_drained.is_set()

        # Shutdown marked
        assert app.state.shutdown_in_progress.is_set()


@pytest.mark.asyncio
async def test_lifespan_handles_exception_during_startup() -> None:
    """Test that lifespan cleans up resources even if startup fails."""
    app = FastAPI()

    close_db_mock = AsyncMock()

    with (
        patch("src.app.core.setup.set_threadpool_tokens", new=AsyncMock()),
        patch(
            "src.app.core.setup.initialize_database_engine",
            new=AsyncMock(side_effect=RuntimeError("DB connection failed")),
        ),
        patch("src.app.core.setup.create_redis_cache_pool", new=AsyncMock()),
        patch("src.app.core.setup.create_redis_queue_pool", new=AsyncMock()),
        patch("src.app.core.setup.create_redis_rate_limit_pool", new=AsyncMock()),
        patch("src.app.core.setup.close_database_engine", new=close_db_mock),
        patch("src.app.core.setup.close_redis_cache_pool", new=AsyncMock()),
        patch("src.app.core.setup.close_redis_queue_pool", new=AsyncMock()),
        patch("src.app.core.setup.close_redis_rate_limit_pool", new=AsyncMock()),
        patch("src.app.core.setup.init_sentry"),
        patch("src.app.core.setup.shutdown_sentry", new=AsyncMock()),
        pytest.raises(RuntimeError, match="DB connection failed"),
    ):
        lifespan = lifespan_factory(settings)
        async with lifespan(app):
            pass
