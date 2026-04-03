from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.app.core.config import load_settings
from src.app.core.db import database as database_module
from src.app.core.db.database import (
    build_database_connect_args,
    build_database_engine_kwargs,
    build_database_startup_retry_delays,
)


def test_database_engine_kwargs_make_pool_health_protections_explicit() -> None:
    settings = load_settings(
        _env_file=None,
        DATABASE_POOL_USE_LIFO=False,
    )

    engine_kwargs = build_database_engine_kwargs(settings)

    assert engine_kwargs["pool_pre_ping"] is True
    assert engine_kwargs["pool_use_lifo"] is False
    assert engine_kwargs["pool_reset_on_return"] == "rollback"


def test_database_connect_args_include_statement_and_idle_transaction_timeouts() -> None:
    settings = load_settings(
        _env_file=None,
        DATABASE_STATEMENT_TIMEOUT_MS=30000,
        DATABASE_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS=15000,
    )

    connect_args = build_database_connect_args(settings)

    assert connect_args["server_settings"] == {
        "statement_timeout": "30000",
        "idle_in_transaction_session_timeout": "15000",
    }


def test_database_startup_retry_delays_use_exponential_backoff_with_a_cap() -> None:
    assert build_database_startup_retry_delays(attempts=4, base_delay=0.5, max_delay=1.5) == [
        0.5,
        1.0,
        1.5,
        1.5,
    ]


@asynccontextmanager
async def _failing_database_connection() -> AsyncGenerator[None, None]:
    raise RuntimeError("temporary database failure")
    yield


@asynccontextmanager
async def _successful_database_connection() -> AsyncGenerator[None, None]:
    yield


@pytest.mark.asyncio
async def test_initialize_database_engine_retries_transient_connection_failures() -> None:
    settings = load_settings(
        _env_file=None,
        DATABASE_STARTUP_RETRY_ATTEMPTS=2,
        DATABASE_STARTUP_RETRY_BASE_DELAY=0.25,
        DATABASE_STARTUP_RETRY_MAX_DELAY=1.0,
    )
    fake_engine = Mock()
    fake_engine.connect = Mock(
        side_effect=[
            _failing_database_connection(),
            _successful_database_connection(),
        ]
    )
    sleep_mock = AsyncMock()

    with (
        patch.object(database_module, "async_engine", fake_engine),
        patch("src.app.core.db.database.anyio.sleep", new=sleep_mock),
    ):
        await database_module.initialize_database_engine(settings)

    assert fake_engine.connect.call_count == 2
    sleep_mock.assert_awaited_once_with(0.25)


@pytest.mark.asyncio
async def test_initialize_database_engine_raises_after_retry_budget_is_exhausted() -> None:
    settings = load_settings(
        _env_file=None,
        DATABASE_STARTUP_RETRY_ATTEMPTS=1,
        DATABASE_STARTUP_RETRY_BASE_DELAY=0.25,
        DATABASE_STARTUP_RETRY_MAX_DELAY=1.0,
    )
    fake_engine = Mock()
    fake_engine.connect = Mock(
        side_effect=[
            _failing_database_connection(),
            _failing_database_connection(),
        ]
    )
    sleep_mock = AsyncMock()

    with (
        patch.object(database_module, "async_engine", fake_engine),
        patch("src.app.core.db.database.anyio.sleep", new=sleep_mock),
        pytest.raises(RuntimeError, match="temporary database failure"),
    ):
        await database_module.initialize_database_engine(settings)

    assert fake_engine.connect.call_count == 2
    sleep_mock.assert_awaited_once_with(0.25)
