"""Reusable pytest fixtures for isolated test database and Redis.

This module provides fixtures for integration tests that need real database
and Redis connections. These fixtures use separate test databases and Redis
DBs to avoid conflicts with development or other test runs.

Usage
-----
Import the fixtures you need in your test files or in conftest.py:

    from tests.fixtures.database import test_async_engine, async_db_session
    from tests.fixtures.redis import test_redis_cache, test_redis_queue

Fixture Categories
-------------------
Database Fixtures (tests/fixtures/database.py):
    - test_db_url: Test database URL (session-scoped, overridable)
    - test_async_engine: Async SQLAlchemy engine with metadata setup
    - test_sync_engine: Sync SQLAlchemy engine for helpers
    - async_db_session: Per-test async session with automatic rollback
    - sync_db_session: Per-test sync session with automatic rollback

Redis Fixtures (tests/fixtures/redis.py):
    - test_redis_url: Redis URL factory (session-scoped, overridable)
    - test_redis_cache: Per-test Redis connection for cache (DB 1)
    - test_redis_queue: Per-test Redis connection for queue (DB 2)
    - test_redis_rate_limiter: Per-test Redis connection for rate-limiter (DB 3)

Design Principles
-----------------
1. Isolation: Each test gets a clean database/Redis state
2. Test-specific databases: Uses separate database and DBs to avoid conflicts
3. Deterministic: Uses settings from tests/settings.py for consistency
4. Optional: These are patterns for integration tests, not auto-registered

Opting In
---------
These fixtures are NOT automatically registered. To use them in your tests:

Option 1: Import directly in test files
    def test_with_db(async_db_session):
        # async_db_session is now available

Option 2: Register in your conftest.py
    # In tests/conftest.py or a subdirectory conftest.py
    pytest_plugins = ["tests.fixtures.database", "tests.fixtures.redis"]

Option 3: Create a dedicated conftest.py for integration tests
    # In tests/integration/conftest.py
    pytest_plugins = ["tests.fixtures.database", "tests.fixtures.redis"]
"""

from __future__ import annotations

from tests.fixtures.database import (
    async_db_session,
    sync_db_session,
    test_async_engine,
    test_db_url,
    test_sync_engine,
)
from tests.fixtures.redis import (
    test_redis_cache,
    test_redis_queue,
    test_redis_rate_limiter,
    test_redis_url,
)

__all__ = [
    "async_db_session",
    "sync_db_session",
    "test_async_engine",
    "test_db_url",
    "test_sync_engine",
    "test_redis_cache",
    "test_redis_queue",
    "test_redis_rate_limiter",
    "test_redis_url",
]
