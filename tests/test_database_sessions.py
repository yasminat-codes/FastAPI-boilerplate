from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.db import database as database_module
from src.app.core.db.sessions import (
    DatabaseSessionScope,
    database_transaction,
    get_database_session_policy,
    is_retryable_database_error,
    open_database_session,
    retry_database_operation,
)


@pytest.mark.parametrize(
    ("scope", "expected_boundary"),
    [
        (
            DatabaseSessionScope.API_REQUEST,
            "Use the request session for a single API call and wrap multi-step writes "
            "in a transaction helper.",
        ),
        (
            DatabaseSessionScope.BACKGROUND_JOB,
            "Use the job session for a single job execution and dispose it after the job settles.",
        ),
        (
            DatabaseSessionScope.SCRIPT,
            "Use the script session for one command or batch step and commit only when the batch is complete.",
        ),
    ],
)
def test_database_session_policies_define_scope_specific_boundaries(
    scope: DatabaseSessionScope,
    expected_boundary: str,
) -> None:
    policy = get_database_session_policy(scope)

    assert policy.scope is scope
    assert policy.recommended_boundary == expected_boundary
    assert policy.session_notes


@pytest.mark.asyncio
async def test_open_database_session_tags_scope_metadata() -> None:
    session = SimpleNamespace(info={})

    @asynccontextmanager
    async def session_factory():
        yield session

    async with open_database_session(session_factory, DatabaseSessionScope.BACKGROUND_JOB) as opened_session:
        assert opened_session is session

    assert session.info["database_session_scope"] == DatabaseSessionScope.BACKGROUND_JOB.value
    assert "background job" in session.info["database_session_policy"].lower()


@pytest.mark.asyncio
async def test_database_transaction_commits_on_success_and_rolls_back_on_error() -> None:
    session = AsyncMock(spec=AsyncSession)

    async with database_transaction(session):
        pass

    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()

    session.reset_mock()

    with pytest.raises(RuntimeError, match="boom"):
        async with database_transaction(session):
            raise RuntimeError("boom")

    session.rollback.assert_awaited_once_with()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_database_operation_retries_only_transient_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    transient_error = OperationalError("select 1", {}, Exception("temporary disconnect"), connection_invalidated=True)
    operation = AsyncMock(side_effect=[transient_error, "ok"])
    sleep = AsyncMock()

    monkeypatch.setattr("src.app.core.db.sessions.asyncio.sleep", sleep)

    result = await retry_database_operation(operation, attempts=2, initial_delay_seconds=0.25, max_delay_seconds=1.0)

    assert result == "ok"
    operation.assert_awaited()
    sleep.assert_awaited_once_with(0.25)
    assert is_retryable_database_error(transient_error) is True
    assert is_retryable_database_error(IntegrityError("select 1", {}, Exception("constraint"))) is False


@pytest.mark.asyncio
async def test_retry_database_operation_does_not_retry_permanent_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    operation = AsyncMock(side_effect=IntegrityError("select 1", {}, Exception("constraint")))
    sleep = AsyncMock()

    monkeypatch.setattr("src.app.core.db.sessions.asyncio.sleep", sleep)

    with pytest.raises(IntegrityError):
        await retry_database_operation(operation, attempts=3)

    operation.assert_awaited_once_with()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("getter_name", "expected_scope"),
    [
        ("async_get_db", DatabaseSessionScope.API_REQUEST),
        ("async_get_job_db", DatabaseSessionScope.BACKGROUND_JOB),
        ("async_get_script_db", DatabaseSessionScope.SCRIPT),
    ],
)
async def test_session_dependencies_route_through_the_expected_scope(
    getter_name: str,
    expected_scope: DatabaseSessionScope,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(info={})

    @asynccontextmanager
    async def open_session(session_factory_arg, scope):
        assert session_factory_arg is database_module.local_session
        assert scope is expected_scope
        yield session

    monkeypatch.setattr(database_module, "open_database_session", open_session)

    getter = getattr(database_module, getter_name)
    yielded_sessions: list[SimpleNamespace] = []

    async for opened_session in getter():
        yielded_sessions.append(opened_session)

    assert yielded_sessions == [session]
