from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.app.core.utils import queue as shared_queue
from src.app.core.worker import functions as worker_functions_module
from src.app.core.worker.settings import build_worker_settings
from src.app.platform.config import load_settings


def test_worker_settings_enable_signal_handling_and_graceful_completion_wait() -> None:
    settings = load_settings(_env_file=None)

    worker_settings = build_worker_settings(settings)

    assert worker_settings.handle_signals is True
    assert worker_settings.job_completion_wait == 30
    assert worker_settings.ctx["settings"] is settings


@pytest.mark.asyncio
async def test_worker_startup_and_shutdown_manage_shared_resources() -> None:
    settings = load_settings(
        _env_file=None,
        SENTRY_ENABLE=True,
        SENTRY_DSN="https://public@example.ingest.sentry.io/1",
    )
    redis_pool = object()
    ctx = {"settings": settings, "redis": redis_pool}

    initialize_database_engine = AsyncMock()
    close_database_engine = AsyncMock()
    create_redis_cache_pool = AsyncMock()
    close_redis_cache_pool = AsyncMock()
    create_redis_rate_limit_pool = AsyncMock()
    close_redis_rate_limit_pool = AsyncMock()
    init_sentry_for_worker = Mock()
    shutdown_sentry = AsyncMock()

    with (
        patch.object(worker_functions_module, "initialize_database_engine", initialize_database_engine),
        patch.object(worker_functions_module, "close_database_engine", close_database_engine),
        patch.object(worker_functions_module, "create_redis_cache_pool", create_redis_cache_pool),
        patch.object(worker_functions_module, "close_redis_cache_pool", close_redis_cache_pool),
        patch.object(worker_functions_module, "create_redis_rate_limit_pool", create_redis_rate_limit_pool),
        patch.object(worker_functions_module, "close_redis_rate_limit_pool", close_redis_rate_limit_pool),
        patch.object(worker_functions_module, "init_sentry_for_worker", init_sentry_for_worker),
        patch.object(worker_functions_module, "shutdown_sentry", shutdown_sentry),
    ):
        await worker_functions_module.startup(ctx)

        assert shared_queue.pool is redis_pool
        assert worker_functions_module.WORKER_RESOURCE_STACK_CONTEXT_KEY in ctx

        await worker_functions_module.shutdown(ctx)

    initialize_database_engine.assert_awaited_once_with(settings)
    create_redis_cache_pool.assert_awaited_once_with(settings)
    create_redis_rate_limit_pool.assert_awaited_once_with(settings)
    init_sentry_for_worker.assert_called_once_with(settings)
    shutdown_sentry.assert_awaited_once_with(settings)
    close_redis_rate_limit_pool.assert_awaited_once_with()
    close_redis_cache_pool.assert_awaited_once_with()
    close_database_engine.assert_awaited_once_with()
    assert shared_queue.pool is None
    assert ctx.get(worker_functions_module.WORKER_RESOURCE_STACK_CONTEXT_KEY) is None


@pytest.mark.asyncio
async def test_worker_startup_cleans_up_already_initialized_resources_when_later_step_fails() -> None:
    settings = load_settings(
        _env_file=None,
        SENTRY_ENABLE=True,
        SENTRY_DSN="https://public@example.ingest.sentry.io/1",
    )
    redis_pool = object()
    ctx = {"settings": settings, "redis": redis_pool}

    initialize_database_engine = AsyncMock()
    close_database_engine = AsyncMock()
    create_redis_cache_pool = AsyncMock()
    close_redis_cache_pool = AsyncMock()
    create_redis_rate_limit_pool = AsyncMock(side_effect=RuntimeError("rate-limit startup failed"))
    close_redis_rate_limit_pool = AsyncMock()
    init_sentry_for_worker = Mock()
    shutdown_sentry = AsyncMock()

    with (
        patch.object(worker_functions_module, "initialize_database_engine", initialize_database_engine),
        patch.object(worker_functions_module, "close_database_engine", close_database_engine),
        patch.object(worker_functions_module, "create_redis_cache_pool", create_redis_cache_pool),
        patch.object(worker_functions_module, "close_redis_cache_pool", close_redis_cache_pool),
        patch.object(worker_functions_module, "create_redis_rate_limit_pool", create_redis_rate_limit_pool),
        patch.object(worker_functions_module, "close_redis_rate_limit_pool", close_redis_rate_limit_pool),
        patch.object(worker_functions_module, "init_sentry_for_worker", init_sentry_for_worker),
        patch.object(worker_functions_module, "shutdown_sentry", shutdown_sentry),
        pytest.raises(RuntimeError, match="rate-limit startup failed"),
    ):
        await worker_functions_module.startup(ctx)

    initialize_database_engine.assert_awaited_once_with(settings)
    create_redis_cache_pool.assert_awaited_once_with(settings)
    create_redis_rate_limit_pool.assert_awaited_once_with(settings)
    close_redis_cache_pool.assert_awaited_once_with()
    close_database_engine.assert_awaited_once_with()
    close_redis_rate_limit_pool.assert_not_awaited()
    shutdown_sentry.assert_not_awaited()
    assert shared_queue.pool is None
    assert ctx.get(worker_functions_module.WORKER_RESOURCE_STACK_CONTEXT_KEY) is None
