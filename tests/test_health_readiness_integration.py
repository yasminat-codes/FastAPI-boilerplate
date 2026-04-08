"""Integration tests for health and readiness endpoints.

Tests the interactions between health check endpoints, readiness contracts,
and dependency health checkers. Includes full endpoint testing and contract
evaluation with mocked dependencies.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.v1.health import health, ready
from src.app.api.v1.internal_health import internal_health
from src.app.core.health import (
    DependencyHealthResult,
    ReadinessContract,
    build_readiness_contract,
    check_database_health,
    check_queue_health,
    check_rate_limiter_health,
    check_redis_health,
    check_worker_health,
)
from src.app.core.schemas import (
    DependencyHealthDetail,
    InternalHealthCheck,
    ReadyCheck,
    WorkerHealthCheck,
)
from src.app.platform.config import settings

# =============================================================================
# Health Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
async def test_health_endpoint_returns_correct_fields() -> None:
    """Health endpoint returns 200 with correct fields and structure."""
    response = await health()
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "healthy"
    assert payload["environment"] == settings.ENVIRONMENT.value
    assert payload["version"] == "0.1.0"
    # Ensure timestamp is ISO format (can be parsed without error)
    datetime.fromisoformat(payload["timestamp"])
    # Exactly these fields, no extras
    assert set(payload.keys()) == {"status", "environment", "version", "timestamp"}


# =============================================================================
# Readiness Endpoint Tests - Success Path
# =============================================================================


@pytest.mark.asyncio
async def test_readiness_endpoint_returns_200_when_all_dependencies_healthy() -> None:
    """Readiness endpoint returns 200 with healthy status when all dependencies
    are healthy."""
    database = Mock(spec=AsyncSession)
    redis = Mock(spec=Redis)

    with (
        patch(
            "src.app.core.health.check_database_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Database probe succeeded.")
            ),
        ) as db_check,
        patch(
            "src.app.core.health.check_redis_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Cache Redis ping succeeded.")
            ),
        ) as redis_check,
        patch(
            "src.app.core.health.check_queue_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Queue Redis ping succeeded.")
            ),
        ) as queue_check,
        patch(
            "src.app.core.health.check_rate_limiter_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Rate limiter Redis ping succeeded.")
            ),
        ) as rate_limiter_check,
    ):
        response = await ready(redis=redis, db=database)
        payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "healthy"
    assert payload["app"] == "healthy"
    assert payload["environment"] == settings.ENVIRONMENT.value
    assert payload["version"] == "0.1.0"
    assert payload["dependencies"] == {
        "database": "healthy",
        "redis": "healthy",
        "queue": "healthy",
        "rate_limiter": "healthy",
    }
    datetime.fromisoformat(payload["timestamp"])
    db_check.assert_awaited_once()
    redis_check.assert_awaited_once()
    queue_check.assert_awaited_once()
    rate_limiter_check.assert_awaited_once()


# =============================================================================
# Readiness Endpoint Tests - Unhealthy Dependencies
# =============================================================================


@pytest.mark.asyncio
async def test_readiness_endpoint_returns_503_when_database_unhealthy() -> None:
    """Readiness endpoint returns 503 when database health check fails."""
    database = Mock(spec=AsyncSession)
    redis = Mock(spec=Redis)

    with (
        patch(
            "src.app.core.health.check_database_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="unhealthy", summary="Database probe failed.")
            ),
        ),
        patch(
            "src.app.core.health.check_redis_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Cache Redis ping succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_queue_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Queue Redis ping succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_rate_limiter_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Rate limiter Redis ping succeeded.")
            ),
        ),
    ):
        response = await ready(redis=redis, db=database)
        payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["status"] == "unhealthy"
    assert payload["dependencies"]["database"] == "unhealthy"


@pytest.mark.asyncio
async def test_readiness_endpoint_returns_503_when_redis_unhealthy() -> None:
    """Readiness endpoint returns 503 when Redis health check fails."""
    database = Mock(spec=AsyncSession)
    redis = Mock(spec=Redis)

    with (
        patch(
            "src.app.core.health.check_database_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Database probe succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_redis_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="unhealthy", summary="Cache Redis ping failed.")
            ),
        ),
        patch(
            "src.app.core.health.check_queue_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Queue Redis ping succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_rate_limiter_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Rate limiter Redis ping succeeded.")
            ),
        ),
    ):
        response = await ready(redis=redis, db=database)
        payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["status"] == "unhealthy"
    assert payload["dependencies"]["redis"] == "unhealthy"


@pytest.mark.asyncio
async def test_readiness_endpoint_returns_503_when_queue_unhealthy() -> None:
    """Readiness endpoint returns 503 when queue health check fails."""
    database = Mock(spec=AsyncSession)
    redis = Mock(spec=Redis)

    with (
        patch(
            "src.app.core.health.check_database_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Database probe succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_redis_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Cache Redis ping succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_queue_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="unhealthy", summary="Queue Redis ping failed.")
            ),
        ),
        patch(
            "src.app.core.health.check_rate_limiter_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Rate limiter Redis ping succeeded.")
            ),
        ),
    ):
        response = await ready(redis=redis, db=database)
        payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["status"] == "unhealthy"
    assert payload["dependencies"]["queue"] == "unhealthy"


@pytest.mark.asyncio
async def test_readiness_endpoint_returns_503_when_rate_limiter_unhealthy() -> None:
    """Readiness endpoint returns 503 when rate limiter health check fails."""
    database = Mock(spec=AsyncSession)
    redis = Mock(spec=Redis)

    with (
        patch(
            "src.app.core.health.check_database_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Database probe succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_redis_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Cache Redis ping succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_queue_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Queue Redis ping succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_rate_limiter_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="unhealthy", summary="Rate limiter Redis ping failed.")
            ),
        ),
    ):
        response = await ready(redis=redis, db=database)
        payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["status"] == "unhealthy"
    assert payload["dependencies"]["rate_limiter"] == "unhealthy"


# =============================================================================
# Internal Health Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
async def test_internal_health_returns_dependency_details_and_worker_health() -> None:
    """Internal health endpoint includes worker heartbeat info and dependency
    details."""
    database = Mock(spec=AsyncSession)
    redis = Mock(spec=Redis)

    with (
        patch(
            "src.app.core.health.check_database_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Database probe succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_redis_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Cache Redis ping succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_queue_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Queue Redis ping succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_rate_limiter_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Rate limiter Redis ping succeeded.")
            ),
        ),
        patch(
            "src.app.api.v1.internal_health.check_worker_health",
            new=AsyncMock(
                return_value=WorkerHealthCheck(
                    status="healthy",
                    summary="Recent worker heartbeat observed on the configured queue.",
                    queue_name=settings.WORKER_QUEUE_NAME,
                )
            ),
        ) as worker_check,
    ):
        response = await internal_health(redis=redis, db=database)
        payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "healthy"
    assert payload["app"] == "healthy"
    assert payload["environment"] == settings.ENVIRONMENT.value
    assert payload["version"] == "0.1.0"
    assert payload["dependencies"] == {
        "database": "healthy",
        "redis": "healthy",
        "queue": "healthy",
        "rate_limiter": "healthy",
    }
    assert payload["dependency_details"] == {
        "database": {"status": "healthy", "summary": "Database probe succeeded."},
        "redis": {"status": "healthy", "summary": "Cache Redis ping succeeded."},
        "queue": {"status": "healthy", "summary": "Queue Redis ping succeeded."},
        "rate_limiter": {"status": "healthy", "summary": "Rate limiter Redis ping succeeded."},
    }
    assert payload["worker"]["status"] == "healthy"
    assert payload["worker"]["queue_name"] == settings.WORKER_QUEUE_NAME
    datetime.fromisoformat(payload["timestamp"])
    worker_check.assert_awaited_once()


@pytest.mark.asyncio
async def test_internal_health_returns_503_when_worker_unhealthy() -> None:
    """Internal health endpoint returns 503 when worker health check fails."""
    database = Mock(spec=AsyncSession)
    redis = Mock(spec=Redis)

    with (
        patch(
            "src.app.core.health.check_database_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Database probe succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_redis_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Cache Redis ping succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_queue_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Queue Redis ping succeeded.")
            ),
        ),
        patch(
            "src.app.core.health.check_rate_limiter_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Rate limiter Redis ping succeeded.")
            ),
        ),
        patch(
            "src.app.api.v1.internal_health.check_worker_health",
            new=AsyncMock(
                return_value=WorkerHealthCheck(
                    status="unhealthy",
                    summary="No recent worker heartbeat was observed on the configured queue.",
                    queue_name=settings.WORKER_QUEUE_NAME,
                )
            ),
        ),
    ):
        response = await internal_health(redis=redis, db=database)
        payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["status"] == "unhealthy"
    assert payload["worker"]["status"] == "unhealthy"


# =============================================================================
# Individual Health Check Function Tests
# =============================================================================


@pytest.mark.asyncio
async def test_check_database_health_success() -> None:
    """Database health check returns healthy when probe succeeds."""
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(return_value=None)

    result = await check_database_health(db=db)

    assert result.status == "healthy"
    assert result.summary == "Database probe succeeded."
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_database_health_failure() -> None:
    """Database health check returns unhealthy when probe fails."""
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(side_effect=Exception("Connection refused"))

    result = await check_database_health(db=db)

    assert result.status == "unhealthy"
    assert result.summary == "Database probe failed."
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_redis_health_success() -> None:
    """Redis health check returns healthy when ping succeeds."""
    redis = AsyncMock(spec=Redis)
    redis.ping = AsyncMock(return_value=True)

    result = await check_redis_health(redis=redis)

    assert result.status == "healthy"
    assert result.summary == "Cache Redis ping succeeded."
    redis.ping.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_redis_health_failure() -> None:
    """Redis health check returns unhealthy when ping fails."""
    redis = AsyncMock(spec=Redis)
    redis.ping = AsyncMock(side_effect=Exception("Connection timeout"))

    result = await check_redis_health(redis=redis)

    assert result.status == "unhealthy"
    assert result.summary == "Cache Redis ping failed."
    redis.ping.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_queue_health_with_null_pool() -> None:
    """Queue health check returns unhealthy when queue pool is None."""
    result = await check_queue_health(queue_pool=None)

    assert result.status == "unhealthy"
    assert result.summary == "Shared queue pool is not initialized."


@pytest.mark.asyncio
async def test_check_queue_health_success() -> None:
    """Queue health check returns healthy when ping succeeds."""
    queue_pool = AsyncMock()
    queue_pool.ping = AsyncMock(return_value=True)

    result = await check_queue_health(queue_pool=queue_pool)

    assert result.status == "healthy"
    assert result.summary == "Queue Redis ping succeeded."
    queue_pool.ping.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_queue_health_failure() -> None:
    """Queue health check returns unhealthy when ping fails."""
    queue_pool = AsyncMock()
    queue_pool.ping = AsyncMock(side_effect=Exception("Connection refused"))

    result = await check_queue_health(queue_pool=queue_pool)

    assert result.status == "unhealthy"
    assert result.summary == "Queue Redis ping failed."
    queue_pool.ping.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_rate_limiter_health_with_null_client() -> None:
    """Rate limiter health check returns unhealthy when client is None."""
    result = await check_rate_limiter_health(redis=None)

    assert result.status == "unhealthy"
    assert result.summary == "Rate limiter Redis client is not initialized."


@pytest.mark.asyncio
async def test_check_rate_limiter_health_success() -> None:
    """Rate limiter health check returns healthy when ping succeeds."""
    redis = AsyncMock(spec=Redis)
    redis.ping = AsyncMock(return_value=True)

    result = await check_rate_limiter_health(redis=redis)

    assert result.status == "healthy"
    assert result.summary == "Rate limiter Redis ping succeeded."
    redis.ping.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_rate_limiter_health_failure() -> None:
    """Rate limiter health check returns unhealthy when ping fails."""
    redis = AsyncMock(spec=Redis)
    redis.ping = AsyncMock(side_effect=Exception("Connection timeout"))

    result = await check_rate_limiter_health(redis=redis)

    assert result.status == "unhealthy"
    assert result.summary == "Rate limiter Redis ping failed."
    redis.ping.assert_awaited_once()


# =============================================================================
# ReadinessContract.snapshot() Tests
# =============================================================================


@pytest.mark.asyncio
async def test_readiness_snapshot_aggregates_multiple_dependency_checks() -> None:
    """ReadinessContract.snapshot() correctly aggregates multiple dependency
    health checks."""
    db_result = DependencyHealthResult(status="healthy", summary="Database OK")
    redis_result = DependencyHealthResult(status="healthy", summary="Redis OK")
    queue_result = DependencyHealthResult(status="unhealthy", summary="Queue down")

    contract = ReadinessContract(
        dependencies={
            "database": AsyncMock(return_value=db_result),
            "redis": AsyncMock(return_value=redis_result),
            "queue": AsyncMock(return_value=queue_result),
        }
    )

    snapshot = await contract.snapshot()

    assert snapshot.status == "unhealthy"  # One unhealthy dependency makes overall status unhealthy
    assert snapshot.dependency_statuses == {
        "database": "healthy",
        "redis": "healthy",
        "queue": "unhealthy",
    }
    assert snapshot.dependency_details == {
        "database": DependencyHealthDetail(status="healthy", summary="Database OK"),
        "redis": DependencyHealthDetail(status="healthy", summary="Redis OK"),
        "queue": DependencyHealthDetail(status="unhealthy", summary="Queue down"),
    }


@pytest.mark.asyncio
async def test_readiness_snapshot_all_healthy() -> None:
    """ReadinessContract.snapshot() returns healthy status when all
    dependencies are healthy."""
    db_result = DependencyHealthResult(status="healthy", summary="Database OK")
    redis_result = DependencyHealthResult(status="healthy", summary="Redis OK")

    contract = ReadinessContract(
        dependencies={
            "database": AsyncMock(return_value=db_result),
            "redis": AsyncMock(return_value=redis_result),
        }
    )

    snapshot = await contract.snapshot()

    assert snapshot.status == "healthy"
    assert all(status == "healthy" for status in snapshot.dependency_statuses.values())


# =============================================================================
# ReadinessContract.evaluate() Tests
# =============================================================================


@pytest.mark.asyncio
async def test_readiness_evaluate_returns_ready_check() -> None:
    """ReadinessContract.evaluate() returns ReadyCheck with correct fields."""
    db_result = DependencyHealthResult(status="healthy", summary="Database OK")
    redis_result = DependencyHealthResult(status="healthy", summary="Redis OK")

    contract = ReadinessContract(
        dependencies={
            "database": AsyncMock(return_value=db_result),
            "redis": AsyncMock(return_value=redis_result),
        }
    )

    ready_check = await contract.evaluate(environment="test", version="1.0.0")

    assert isinstance(ready_check, ReadyCheck)
    assert ready_check.status == "healthy"
    assert ready_check.environment == "test"
    assert ready_check.version == "1.0.0"
    assert ready_check.app == "healthy"
    assert ready_check.dependencies == {
        "database": "healthy",
        "redis": "healthy",
    }
    datetime.fromisoformat(ready_check.timestamp)


# =============================================================================
# ReadinessContract.evaluate_internal() Tests
# =============================================================================


@pytest.mark.asyncio
async def test_readiness_evaluate_internal_merges_worker_health_with_dependencies() -> None:
    """ReadinessContract.evaluate_internal() correctly merges worker health
    with dependency health checks."""
    db_result = DependencyHealthResult(status="healthy", summary="Database OK")
    redis_result = DependencyHealthResult(status="healthy", summary="Redis OK")
    queue_result = DependencyHealthResult(status="healthy", summary="Queue OK")

    contract = ReadinessContract(
        dependencies={
            "database": AsyncMock(return_value=db_result),
            "redis": AsyncMock(return_value=redis_result),
            "queue": AsyncMock(return_value=queue_result),
        }
    )

    worker = WorkerHealthCheck(
        status="healthy",
        summary="Worker heartbeat OK",
        queue_name="test_queue",
    )

    internal_check = await contract.evaluate_internal(
        environment="test",
        version="1.0.0",
        worker=worker,
    )

    assert isinstance(internal_check, InternalHealthCheck)
    assert internal_check.status == "healthy"
    assert internal_check.worker == worker
    assert internal_check.dependencies == {
        "database": "healthy",
        "redis": "healthy",
        "queue": "healthy",
    }
    assert internal_check.dependency_details == {
        "database": DependencyHealthDetail(status="healthy", summary="Database OK"),
        "redis": DependencyHealthDetail(status="healthy", summary="Redis OK"),
        "queue": DependencyHealthDetail(status="healthy", summary="Queue OK"),
    }


@pytest.mark.asyncio
async def test_readiness_evaluate_internal_returns_unhealthy_when_worker_unhealthy() -> None:
    """ReadinessContract.evaluate_internal() returns unhealthy overall status
    when worker is unhealthy."""
    db_result = DependencyHealthResult(status="healthy", summary="Database OK")
    redis_result = DependencyHealthResult(status="healthy", summary="Redis OK")

    contract = ReadinessContract(
        dependencies={
            "database": AsyncMock(return_value=db_result),
            "redis": AsyncMock(return_value=redis_result),
        }
    )

    worker = WorkerHealthCheck(
        status="unhealthy",
        summary="No worker heartbeat",
        queue_name="test_queue",
    )

    internal_check = await contract.evaluate_internal(
        environment="test",
        version="1.0.0",
        worker=worker,
    )

    assert internal_check.status == "unhealthy"
    assert internal_check.worker.status == "unhealthy"


@pytest.mark.asyncio
async def test_readiness_evaluate_internal_returns_unhealthy_when_dependency_unhealthy() -> None:
    """ReadinessContract.evaluate_internal() returns unhealthy overall status
    when a dependency is unhealthy."""
    db_result = DependencyHealthResult(status="unhealthy", summary="Database down")
    redis_result = DependencyHealthResult(status="healthy", summary="Redis OK")

    contract = ReadinessContract(
        dependencies={
            "database": AsyncMock(return_value=db_result),
            "redis": AsyncMock(return_value=redis_result),
        }
    )

    worker = WorkerHealthCheck(
        status="healthy",
        summary="Worker heartbeat OK",
        queue_name="test_queue",
    )

    internal_check = await contract.evaluate_internal(
        environment="test",
        version="1.0.0",
        worker=worker,
    )

    assert internal_check.status == "unhealthy"
    assert internal_check.dependencies["database"] == "unhealthy"


# =============================================================================
# Worker Health Check Tests
# =============================================================================


@pytest.mark.asyncio
async def test_check_worker_health_with_null_queue_pool() -> None:
    """Worker health check returns unhealthy when queue pool is None."""
    worker_check = await check_worker_health(queue_pool=None, queue_name="test_queue")

    assert worker_check.status == "unhealthy"
    assert worker_check.queue_name == "test_queue"
    assert worker_check.summary == "Queue pool is not initialized; worker heartbeat cannot be checked."


@pytest.mark.asyncio
async def test_check_worker_health_missing_heartbeat() -> None:
    """Worker health check returns unhealthy when heartbeat is missing."""
    queue_pool = AsyncMock()
    queue_pool.get = AsyncMock(return_value=None)

    worker_check = await check_worker_health(queue_pool=queue_pool, queue_name="test_queue")

    assert worker_check.status == "unhealthy"
    assert worker_check.queue_name == "test_queue"
    assert worker_check.summary == "No recent worker heartbeat was observed on the configured queue."
    queue_pool.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_worker_health_with_valid_heartbeat() -> None:
    """Worker health check returns healthy when heartbeat is present."""
    queue_pool = AsyncMock()
    queue_pool.get = AsyncMock(return_value=b"2026-04-03 12:00:00 j_complete=5")

    worker_check = await check_worker_health(queue_pool=queue_pool, queue_name="test_queue")

    assert worker_check.status == "healthy"
    assert worker_check.queue_name == "test_queue"
    assert worker_check.summary == "Recent worker heartbeat observed on the configured queue."
    queue_pool.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_worker_health_with_custom_health_check_key() -> None:
    """Worker health check uses custom key when provided."""
    queue_pool = AsyncMock()
    queue_pool.get = AsyncMock(return_value=b"2026-04-03 12:00:00")

    custom_key = "custom:health:check:key"
    worker_check = await check_worker_health(
        queue_pool=queue_pool,
        queue_name="test_queue",
        health_check_key=custom_key,
    )

    assert worker_check.status == "healthy"
    queue_pool.get.assert_awaited_once_with(custom_key)


@pytest.mark.asyncio
async def test_check_worker_health_handles_get_failure() -> None:
    """Worker health check returns unhealthy when heartbeat lookup fails."""
    queue_pool = AsyncMock()
    queue_pool.get = AsyncMock(side_effect=Exception("Redis connection failed"))

    worker_check = await check_worker_health(queue_pool=queue_pool, queue_name="test_queue")

    assert worker_check.status == "unhealthy"
    assert worker_check.queue_name == "test_queue"
    assert worker_check.summary == "Worker heartbeat lookup failed."
    queue_pool.get.assert_awaited_once()


# =============================================================================
# Build Readiness Contract Tests
# =============================================================================


@pytest.mark.asyncio
async def test_build_readiness_contract_creates_contract_with_four_dependencies() -> None:
    """build_readiness_contract creates contract with database, redis, queue,
    and rate_limiter dependency checks."""
    database = AsyncMock(spec=AsyncSession)
    redis = AsyncMock(spec=Redis)
    queue_pool = AsyncMock()
    rate_limiter_client = AsyncMock(spec=Redis)

    contract = build_readiness_contract(
        database=database,
        redis=redis,
        queue_pool=queue_pool,
        rate_limiter_client=rate_limiter_client,
    )

    assert isinstance(contract, ReadinessContract)
    assert set(contract.dependencies.keys()) == {"database", "redis", "queue", "rate_limiter"}


@pytest.mark.asyncio
async def test_build_readiness_contract_with_null_queue_pool_and_rate_limiter() -> None:
    """build_readiness_contract handles None queue_pool and rate_limiter
    client."""
    database = AsyncMock(spec=AsyncSession)
    redis = AsyncMock(spec=Redis)

    contract = build_readiness_contract(
        database=database,
        redis=redis,
        queue_pool=None,
        rate_limiter_client=None,
    )

    assert isinstance(contract, ReadinessContract)
    # Verify the checkers are created even with None values
    assert "queue" in contract.dependencies
    assert "rate_limiter" in contract.dependencies

    # Run the snapshot and verify unhealthy results
    snapshot = await contract.snapshot()
    assert snapshot.dependency_statuses["queue"] == "unhealthy"
    assert snapshot.dependency_statuses["rate_limiter"] == "unhealthy"
