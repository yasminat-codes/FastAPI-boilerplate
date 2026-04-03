import ssl
from collections.abc import AsyncGenerator
from typing import Any

import anyio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass

from ..config import DatabaseSSLMode, PostgresSettings, settings
from .sessions import (
    DatabaseSessionPolicy,
    DatabaseSessionScope,
    database_transaction,
    get_database_session_policy,
    is_retryable_database_error,
    open_database_session,
    retry_database_operation,
)


class Base(DeclarativeBase, MappedAsDataclass):
    pass


DATABASE_URI = settings.POSTGRES_URI
DATABASE_PREFIX = settings.POSTGRES_ASYNC_PREFIX
DATABASE_URL = settings.DATABASE_URL
DATABASE_SYNC_URL = settings.DATABASE_SYNC_URL


def build_database_ssl_context(db_settings: PostgresSettings) -> ssl.SSLContext | bool:
    if db_settings.DATABASE_SSL_MODE is DatabaseSSLMode.DISABLE:
        return False

    if db_settings.DATABASE_SSL_MODE is DatabaseSSLMode.REQUIRE:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
    else:
        ssl_context = ssl.create_default_context(cafile=db_settings.DATABASE_SSL_CA_FILE)
        ssl_context.check_hostname = db_settings.DATABASE_SSL_MODE is DatabaseSSLMode.VERIFY_FULL
        ssl_context.verify_mode = ssl.CERT_REQUIRED

    if db_settings.DATABASE_SSL_CERT_FILE is not None and db_settings.DATABASE_SSL_KEY_FILE is not None:
        ssl_context.load_cert_chain(
            certfile=db_settings.DATABASE_SSL_CERT_FILE,
            keyfile=db_settings.DATABASE_SSL_KEY_FILE,
        )

    return ssl_context


def build_database_server_settings(db_settings: PostgresSettings) -> dict[str, str]:
    server_settings: dict[str, str] = {}

    if db_settings.DATABASE_STATEMENT_TIMEOUT_MS is not None:
        server_settings["statement_timeout"] = str(db_settings.DATABASE_STATEMENT_TIMEOUT_MS)

    if db_settings.DATABASE_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS is not None:
        server_settings["idle_in_transaction_session_timeout"] = str(
            db_settings.DATABASE_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS
        )

    return server_settings


def build_database_connect_args(db_settings: PostgresSettings) -> dict[str, Any]:
    connect_args: dict[str, Any] = {
        "timeout": db_settings.DATABASE_CONNECT_TIMEOUT,
        "command_timeout": db_settings.DATABASE_COMMAND_TIMEOUT,
        "ssl": build_database_ssl_context(db_settings),
    }

    server_settings = build_database_server_settings(db_settings)
    if server_settings:
        connect_args["server_settings"] = server_settings

    return connect_args


def build_database_engine_kwargs(db_settings: PostgresSettings) -> dict[str, Any]:
    return {
        "pool_size": db_settings.DATABASE_POOL_SIZE,
        "max_overflow": db_settings.DATABASE_MAX_OVERFLOW,
        "pool_pre_ping": db_settings.DATABASE_POOL_PRE_PING,
        "pool_use_lifo": db_settings.DATABASE_POOL_USE_LIFO,
        "pool_recycle": db_settings.DATABASE_POOL_RECYCLE,
        "pool_timeout": db_settings.DATABASE_POOL_TIMEOUT,
        "pool_reset_on_return": "rollback",
        "connect_args": build_database_connect_args(db_settings),
    }


DATABASE_ENGINE_KWARGS = build_database_engine_kwargs(settings)


async_engine = create_async_engine(DATABASE_URL, echo=False, future=True, **DATABASE_ENGINE_KWARGS)

local_session = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


def build_database_startup_retry_delays(*, attempts: int, base_delay: float, max_delay: float) -> list[float]:
    delays: list[float] = []
    current_delay = base_delay

    for _ in range(attempts):
        delays.append(current_delay)
        current_delay = min(current_delay * 2, max_delay)

    return delays


async def initialize_database_engine(db_settings: PostgresSettings | None = None) -> None:
    configured_settings = settings if db_settings is None else db_settings
    retry_delays = build_database_startup_retry_delays(
        attempts=configured_settings.DATABASE_STARTUP_RETRY_ATTEMPTS,
        base_delay=configured_settings.DATABASE_STARTUP_RETRY_BASE_DELAY,
        max_delay=configured_settings.DATABASE_STARTUP_RETRY_MAX_DELAY,
    )

    for attempt, delay in enumerate([0.0, *retry_delays], start=1):
        if attempt > 1:
            await anyio.sleep(delay)

        try:
            async with async_engine.connect():
                return
        except Exception:
            if attempt == len(retry_delays) + 1:
                raise


async def async_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with open_database_session(local_session, DatabaseSessionScope.API_REQUEST) as db:
        yield db


async def async_get_job_db() -> AsyncGenerator[AsyncSession, None]:
    async with open_database_session(local_session, DatabaseSessionScope.BACKGROUND_JOB) as db:
        yield db


async def async_get_script_db() -> AsyncGenerator[AsyncSession, None]:
    async with open_database_session(local_session, DatabaseSessionScope.SCRIPT) as db:
        yield db


__all__ = [
    "AsyncSession",
    "Base",
    "DATABASE_ENGINE_KWARGS",
    "DATABASE_PREFIX",
    "DATABASE_SYNC_URL",
    "DATABASE_URI",
    "DATABASE_URL",
    "DatabaseSessionPolicy",
    "DatabaseSessionScope",
    "async_engine",
    "async_get_db",
    "async_get_job_db",
    "async_get_script_db",
    "build_database_connect_args",
    "build_database_engine_kwargs",
    "build_database_ssl_context",
    "build_database_startup_retry_delays",
    "database_transaction",
    "get_database_session_policy",
    "initialize_database_engine",
    "is_retryable_database_error",
    "local_session",
    "open_database_session",
    "retry_database_operation",
]
