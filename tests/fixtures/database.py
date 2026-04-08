"""Pytest fixtures for isolated test database with async/sync support.

This module provides reusable fixtures for database testing with these guarantees:
- Session-scoped engines create and drop all tables for the test session
- Per-test sessions use transactional isolation with automatic rollback
- Supports both async (AsyncSession) and sync (Session) operations
- Uses test database URL from tests/settings.py with ENV override support

Design
------
Session-scoped fixtures (test_async_engine, test_sync_engine):
    - Created once per test session
    - Create all tables at session start using Base.metadata.create_all()
    - Drop all tables at session cleanup
    - For integration test suites where schema is stable

Per-test fixtures (async_db_session, sync_db_session):
    - Created fresh for each test
    - Wrap session in a transaction that's rolled back after the test
    - Each test sees a clean database state
    - No cross-test pollution even without manual cleanup

Transactional Rollback Pattern
-------------------------------
The per-test session fixtures use nested transactions:

    1. Begin a transaction on the engine connection
    2. Create a session bound to that transaction
    3. Yield the session to the test
    4. Rollback the transaction (undoing all changes)

This pattern ensures:
- Tests don't need manual cleanup
- Changes don't persist to disk/other tests
- Database schema remains intact for the next test
- Much faster than recreating tables for each test

Environment Overrides
---------------------
TEST_DATABASE_URL: Override the default test database URL
    export TEST_DATABASE_URL="postgresql://user:pass@host:5432/custom_test_db"

The default comes from tests/settings.get_test_settings().DATABASE_URL
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session

from src.app.core.db.database import Base
from tests.settings import get_test_settings


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """Deterministic test database URL, overridable via TEST_DATABASE_URL env var.

    This fixture provides the PostgreSQL URL for test database connections.
    By default, it uses the hardcoded test URL from get_test_settings().
    For CI environments, set TEST_DATABASE_URL to override.

    Returns
    -------
    str
        PostgreSQL connection URL pointing to the test database.

    Notes
    -----
    The test database URL should point to an isolated test database
    (e.g., "test_fastapi_template") to avoid conflicts with development.
    """
    env_url = os.getenv("TEST_DATABASE_URL")
    if env_url:
        return env_url

    test_settings = get_test_settings()
    return test_settings.DATABASE_URL


@pytest.fixture(scope="session")
async def test_async_engine(test_db_url: str):
    """Session-scoped async SQLAlchemy engine pointing at test database.

    Creates all tables at the start of the test session using Base.metadata.
    Drops all tables at the end of the test session for cleanup.

    This fixture is useful for:
    - Test suites with stable schema (metadata-based tests)
    - When you want schema to persist across multiple per-test fixtures
    - Integration tests that validate schema creation

    For per-test isolation, use the async_db_session fixture which wraps
    this engine in a transactional context that rolls back after each test.

    Parameters
    ----------
    test_db_url : str
        Test database URL from the test_db_url fixture.

    Yields
    ------
    AsyncEngine
        Async engine pointing to the test database.

    Notes
    -----
    - Tables are created once at session start via run_sync + create_all
    - Tables are dropped once at session end via run_sync + drop_all
    - The engine is disposed after session cleanup to release connections
    """
    engine = create_async_engine(test_db_url, echo=False, future=True)

    # Create all tables at the start of the test session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables at the end of the test session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture(scope="session")
def test_sync_engine(test_db_url: str):
    """Session-scoped sync SQLAlchemy engine for test helpers.

    Creates all tables at the start of the test session.
    Drops all tables at the end of the test session.

    This fixture is useful when you need sync database access in test helpers
    or setup/teardown code. Most tests should use async_db_session instead.

    Parameters
    ----------
    test_db_url : str
        Test database URL from the test_db_url fixture.

    Yields
    ------
    Engine
        Sync engine pointing to the test database.

    Notes
    -----
    - Tables are created once at session start via create_all
    - Tables are dropped once at session end via drop_all
    - The engine is disposed after session cleanup to release connections
    """
    # Convert async URL to sync URL if needed
    sync_url = test_db_url.replace("postgresql+asyncpg://", "postgresql://")

    engine = create_engine(sync_url, echo=False, future=True)

    # Create all tables at the start of the test session
    Base.metadata.create_all(bind=engine)

    yield engine

    # Drop all tables at the end of the test session
    Base.metadata.drop_all(bind=engine)

    engine.dispose()


@pytest.fixture
async def async_db_session(test_async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test async database session with automatic rollback.

    Each test gets a clean transactional scope. All changes made during the test
    are automatically rolled back after the test completes, ensuring no state
    leaks between tests.

    This fixture uses a nested transaction pattern:
    1. Begin a transaction on the connection
    2. Create a session bound to that transaction
    3. Yield the session to the test
    4. Rollback the transaction (undoing all changes)

    Yields
    ------
    AsyncSession
        Async session bound to a transaction that will be rolled back.

    Examples
    --------
    async def test_create_user(async_db_session):
        # Create a user
        user = User(name="test", email="test@example.com")
        async_db_session.add(user)
        await async_db_session.flush()

        # Changes exist within the test
        result = await async_db_session.execute(select(User))
        assert result.scalar_one_or_none() is not None

        # After the test, the transaction is rolled back
        # and the user is no longer in the database

    Notes
    -----
    - Each test gets a fresh, clean session
    - No manual cleanup needed - rollback is automatic
    - Perfect for unit-style integration tests
    - Foreign key constraints are respected
    - Use flush() to get IDs before assertions
    """
    async_session = sessionmaker(
        bind=test_async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with test_async_engine.connect() as conn:
        # Start a transaction
        trans = await conn.begin()

        # Create a session bound to this connection (which owns the transaction)
        session = async_session(bind=conn)

        try:
            yield session
        finally:
            # Rollback the transaction, undoing all test changes
            await trans.rollback()


@pytest.fixture
def sync_db_session(test_sync_engine) -> Generator[Session, None, None]:
    """Per-test sync database session with automatic rollback.

    Each test gets a clean transactional scope. All changes made during the test
    are automatically rolled back after the test completes.

    This fixture is useful for:
    - Sync helper functions that need database access
    - Tests that use sync ORM operations
    - Compatibility with sync-only libraries

    For most async FastAPI tests, use async_db_session instead.

    Yields
    ------
    Session
        Sync session bound to a transaction that will be rolled back.

    Notes
    -----
    - Each test gets a fresh, clean session
    - No manual cleanup needed - rollback is automatic
    - Transactions are rolled back after each test
    - Use flush() to get IDs before assertions
    """
    sync_session = sessionmaker(bind=test_sync_engine, autocommit=False, autoflush=False)

    with test_sync_engine.begin() as conn:
        trans = conn.begin_nested()

        session = sync_session(bind=conn)

        try:
            yield session
        finally:
            trans.rollback()


__all__ = [
    "test_db_url",
    "test_async_engine",
    "test_sync_engine",
    "async_db_session",
    "sync_db_session",
]
