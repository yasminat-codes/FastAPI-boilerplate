"""Reusable database session scoping, transaction, and retry helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from sqlalchemy.exc import (
    DBAPIError,
    DisconnectionError,
    IntegrityError,
    InterfaceError,
    OperationalError,
    TimeoutError,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SessionFactory = async_sessionmaker[AsyncSession]
DatabaseOperationResult = TypeVar("DatabaseOperationResult")
DatabaseOperation = Callable[[], Awaitable[DatabaseOperationResult]]


class DatabaseSessionScope(str, Enum):
    """Canonical session scopes used by template-owned code paths."""

    API_REQUEST = "api_request"
    BACKGROUND_JOB = "background_job"
    SCRIPT = "script"


@dataclass(frozen=True, slots=True)
class DatabaseSessionPolicy:
    """Describes the intended lifetime and usage pattern for a session scope."""

    scope: DatabaseSessionScope
    description: str
    recommended_boundary: str
    session_notes: tuple[str, ...]


DATABASE_SESSION_POLICIES: dict[DatabaseSessionScope, DatabaseSessionPolicy] = {
    DatabaseSessionScope.API_REQUEST: DatabaseSessionPolicy(
        scope=DatabaseSessionScope.API_REQUEST,
        description="One session per inbound request so request work stays isolated and easy to reason about.",
        recommended_boundary=(
            "Use the request session for a single API call and wrap multi-step writes in a transaction helper."
        ),
        session_notes=(
            "Keep the session request-scoped.",
            "Prefer explicit transaction blocks for writes that span multiple repository calls.",
        ),
    ),
    DatabaseSessionScope.BACKGROUND_JOB: DatabaseSessionPolicy(
        scope=DatabaseSessionScope.BACKGROUND_JOB,
        description="One session per background job so retries do not leak state across jobs.",
        recommended_boundary="Use the job session for a single job execution and dispose it after the job settles.",
        session_notes=(
            "Keep each job isolated.",
            "Retry the job, not the session state, when the work is transiently interrupted.",
        ),
    ),
    DatabaseSessionScope.SCRIPT: DatabaseSessionPolicy(
        scope=DatabaseSessionScope.SCRIPT,
        description="One session per CLI or maintenance script so the script owns the full unit of work.",
        recommended_boundary=(
            "Use the script session for one command or batch step and commit only when the batch is complete."
        ),
        session_notes=(
            "Keep the session script-scoped.",
            "Use explicit transaction helpers around each batch or maintenance step.",
        ),
    ),
}


def get_database_session_policy(scope: DatabaseSessionScope) -> DatabaseSessionPolicy:
    """Return the template's recommended session policy for a given scope."""

    return DATABASE_SESSION_POLICIES[scope]


@asynccontextmanager
async def open_database_session(
    session_factory: SessionFactory,
    scope: DatabaseSessionScope,
) -> AsyncIterator[AsyncSession]:
    """Open a session with scope metadata attached for observability and future hooks."""

    async with session_factory() as session:
        session.info["database_session_scope"] = scope.value
        session.info["database_session_policy"] = get_database_session_policy(scope).description
        yield session


@asynccontextmanager
async def database_transaction(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Wrap a session in an explicit transaction boundary.

    The helper commits on success and rolls back on any exception. It is meant for
    multi-step units of work such as API writes, worker jobs, and maintenance scripts.
    """

    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise


def is_retryable_database_error(exc: BaseException) -> bool:
    """Return ``True`` when a database failure is likely transient."""

    if isinstance(exc, IntegrityError):
        return False

    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return True

    return isinstance(exc, DisconnectionError | InterfaceError | OperationalError | TimeoutError)


async def retry_database_operation(
    operation: Callable[[], Awaitable[DatabaseOperationResult]],
    *,
    attempts: int = 3,
    initial_delay_seconds: float = 0.1,
    max_delay_seconds: float = 1.0,
) -> DatabaseOperationResult:
    """Retry a transient database operation with bounded exponential backoff."""

    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    if initial_delay_seconds < 0:
        raise ValueError("initial_delay_seconds must not be negative")
    if max_delay_seconds < initial_delay_seconds:
        raise ValueError("max_delay_seconds must be greater than or equal to initial_delay_seconds")

    delay_seconds = initial_delay_seconds
    last_error: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= attempts or not is_retryable_database_error(exc):
                raise

            await asyncio.sleep(delay_seconds)
            delay_seconds = min(delay_seconds * 2, max_delay_seconds)

    assert last_error is not None  # pragma: no cover - the loop always sets this on failure
    raise last_error


__all__ = [
    "DATABASE_SESSION_POLICIES",
    "DatabaseSessionPolicy",
    "DatabaseSessionScope",
    "database_transaction",
    "get_database_session_policy",
    "is_retryable_database_error",
    "open_database_session",
    "retry_database_operation",
]
