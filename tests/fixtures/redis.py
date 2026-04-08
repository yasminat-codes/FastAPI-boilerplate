"""Pytest fixtures for isolated test Redis connections.

This module provides reusable fixtures for testing Redis operations with these guarantees:
- Separate Redis DBs (1, 2, 3) avoid conflicts with development (DB 0)
- Per-test flushes ensure clean state at the start of each test
- Automatic connection cleanup after each test
- Deterministic configuration from tests/settings.py with ENV override support

Redis DB Allocation
-------------------
The test Redis fixtures use different database numbers to provide isolation:
    - DB 0: Development/production (not used by test fixtures)
    - DB 1: test_redis_cache (cache operations)
    - DB 2: test_redis_queue (job queue operations)
    - DB 3: test_redis_rate_limiter (rate limiting counters)

This prevents test data from polluting production data even if tests connect
to the same Redis instance.

Design
------
Session-scoped fixtures (test_redis_url):
    - Created once per test session
    - Provides the Redis URL factory
    - Used by per-test connection fixtures

Per-test fixtures (test_redis_cache, test_redis_queue, test_redis_rate_limiter):
    - Created fresh for each test
    - Flush their specific Redis DB at the start
    - Close the connection after the test
    - Each test sees a clean Redis state

Isolation Strategy
------------------
Tests are isolated via:
    1. Separate database numbers (DB 1, 2, 3)
    2. Flush at test start ensures no leftover data
    3. Connection closed after test to free resources
    4. New connection created for next test

Environment Overrides
---------------------
TEST_REDIS_URL: Override the default Redis URL
    export TEST_REDIS_URL="redis://localhost:6379"

TEST_REDIS_HOST: Override the Redis host for all fixtures
    export TEST_REDIS_HOST="redis.test.internal"

The defaults come from tests/settings.get_test_settings() Redis settings.

Example Usage
-------------
async def test_cache_operations(test_redis_cache):
    # Cache DB is already flushed, connection ready
    await test_redis_cache.set("key", "value")
    value = await test_redis_cache.get("key")
    assert value == b"value"
    # Connection is closed automatically after test

async def test_queue_operations(test_redis_queue):
    # Queue DB is already flushed, connection ready
    await test_redis_queue.lpush("jobs", "job_id_123")
    count = await test_redis_queue.llen("jobs")
    assert count == 1
    # Connection is closed automatically after test
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import redis.asyncio as redis

from tests.settings import get_test_settings


def _build_redis_url(host: str, port: int, db: int) -> str:
    """Build a Redis URL from components."""
    return f"redis://{host}:{port}/{db}"


@pytest.fixture(scope="session")
def test_redis_url() -> str:
    """Deterministic test Redis URL, overridable via TEST_REDIS_URL env var.

    This fixture provides the base Redis URL for test connections.
    By default, it uses the connection from get_test_settings().
    For CI environments, set TEST_REDIS_URL or TEST_REDIS_HOST to override.

    Returns
    -------
    str
        Redis connection URL base (without database number).

    Notes
    -----
    The per-test fixtures (test_redis_cache, test_redis_queue, etc.)
    append their specific database numbers to this URL.
    """
    # Check for full URL override
    if env_url := os.getenv("TEST_REDIS_URL"):
        return env_url

    # Check for host override
    if env_host := os.getenv("TEST_REDIS_HOST"):
        test_settings = get_test_settings()
        return _build_redis_url(env_host, test_settings.REDIS_CACHE_PORT, 0)

    # Use settings defaults
    test_settings = get_test_settings()
    return _build_redis_url(test_settings.REDIS_CACHE_HOST, test_settings.REDIS_CACHE_PORT, 0)


@pytest.fixture
async def test_redis_cache(test_redis_url: str) -> AsyncGenerator[redis.Redis, None]:
    """Per-test Redis connection for cache operations. Uses DB 1.

    Flushes the DB before each test for isolation. Connection is closed
    after the test completes.

    This fixture is suitable for testing cache operations such as:
    - Storing computed results
    - Session data caching
    - Feature flag caching
    - Any time-limited data

    Parameters
    ----------
    test_redis_url : str
        Base Redis URL from the test_redis_url fixture.

    Yields
    ------
    redis.Redis
        Async Redis connection bound to DB 1.

    Examples
    --------
    async def test_cache_set_get(test_redis_cache):
        # DB 1 is already flushed
        await test_redis_cache.set("user:123", '{"name": "Alice"}')
        value = await test_redis_cache.get("user:123")
        assert b"Alice" in value

    async def test_cache_ttl(test_redis_cache):
        # Set a value with 1 hour TTL
        await test_redis_cache.setex("temp", 3600, "value")
        ttl = await test_redis_cache.ttl("temp")
        assert ttl > 0

    Notes
    -----
    - DB 1 is used to avoid conflicts with development (DB 0)
    - Flush ensures no data from previous tests
    - Perfect for integration tests of cache layers
    - Close is automatic; no cleanup needed
    """
    # Build connection URL for cache DB (DB 1)
    url = test_redis_url.rstrip("/") + "/1"

    # Create connection
    client = await redis.from_url(url, decode_responses=False)

    try:
        # Flush the DB at the start of the test for isolation
        await client.flushdb()
        yield client
    finally:
        # Close the connection after the test
        await client.close()


@pytest.fixture
async def test_redis_queue(test_redis_url: str) -> AsyncGenerator[redis.Redis, None]:
    """Per-test Redis connection for queue operations. Uses DB 2.

    Flushes the DB before each test for isolation. Connection is closed
    after the test completes.

    This fixture is suitable for testing job queue operations such as:
    - Pushing jobs to queues
    - Popping jobs from queues
    - Dead letter queue handling
    - Queue length checks

    Parameters
    ----------
    test_redis_url : str
        Base Redis URL from the test_redis_url fixture.

    Yields
    ------
    redis.Redis
        Async Redis connection bound to DB 2.

    Examples
    --------
    async def test_queue_operations(test_redis_queue):
        # DB 2 is already flushed
        await test_redis_queue.rpush("jobs", "job_1", "job_2")
        length = await test_redis_queue.llen("jobs")
        assert length == 2

        job = await test_redis_queue.lpop("jobs")
        assert job == b"job_1"

    async def test_dead_letter_queue(test_redis_queue):
        # Test DLQ handling
        await test_redis_queue.rpush("dlq", "failed_job_123")
        dlq_items = await test_redis_queue.lrange("dlq", 0, -1)
        assert len(dlq_items) == 1

    Notes
    -----
    - DB 2 is used to avoid conflicts with development (DB 0) and cache (DB 1)
    - Flush ensures no data from previous tests
    - Perfect for integration tests of queue layers
    - Close is automatic; no cleanup needed
    """
    # Build connection URL for queue DB (DB 2)
    url = test_redis_url.rstrip("/") + "/2"

    # Create connection
    client = await redis.from_url(url, decode_responses=False)

    try:
        # Flush the DB at the start of the test for isolation
        await client.flushdb()
        yield client
    finally:
        # Close the connection after the test
        await client.close()


@pytest.fixture
async def test_redis_rate_limiter(test_redis_url: str) -> AsyncGenerator[redis.Redis, None]:
    """Per-test Redis connection for rate limiter. Uses DB 3.

    Flushes the DB before each test for isolation. Connection is closed
    after the test completes.

    This fixture is suitable for testing rate limiting operations such as:
    - Incrementing request counters
    - Setting sliding window windows
    - Checking rate limit status
    - TTL expiration of limits

    Parameters
    ----------
    test_redis_url : str
        Base Redis URL from the test_redis_url fixture.

    Yields
    ------
    redis.Redis
        Async Redis connection bound to DB 3.

    Examples
    --------
    async def test_rate_limit_counter(test_redis_rate_limiter):
        # DB 3 is already flushed
        key = "rate_limit:user:123:hour"

        # Increment counter 3 times
        for _ in range(3):
            await test_redis_rate_limiter.incr(key)

        count = await test_redis_rate_limiter.get(key)
        assert int(count) == 3

    async def test_rate_limit_ttl(test_redis_rate_limiter):
        # Set limit key with 1 hour TTL
        key = "rate_limit:api:key456"
        await test_redis_rate_limiter.setex(key, 3600, 10)

        # Check TTL
        ttl = await test_redis_rate_limiter.ttl(key)
        assert ttl > 0
        assert ttl <= 3600

    Notes
    -----
    - DB 3 is used to avoid conflicts with development and other test DBs
    - Flush ensures no data from previous tests
    - Perfect for integration tests of rate limiting logic
    - Close is automatic; no cleanup needed
    """
    # Build connection URL for rate limiter DB (DB 3)
    url = test_redis_url.rstrip("/") + "/3"

    # Create connection
    client = await redis.from_url(url, decode_responses=False)

    try:
        # Flush the DB at the start of the test for isolation
        await client.flushdb()
        yield client
    finally:
        # Close the connection after the test
        await client.close()


__all__ = [
    "test_redis_url",
    "test_redis_cache",
    "test_redis_queue",
    "test_redis_rate_limiter",
]
