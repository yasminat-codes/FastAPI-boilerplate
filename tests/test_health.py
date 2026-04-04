import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.v1.health import health, ready
from src.app.api.v1.internal_health import internal_health
from src.app.core.config import settings
from src.app.core.health import DependencyHealthResult, build_readiness_contract, check_worker_health
from src.app.core.schemas import InternalHealthCheck, ReadyCheck, WorkerHealthCheck


@pytest.mark.asyncio
async def test_health_endpoint_returns_lightweight_liveness_payload() -> None:
    response = await health()
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "healthy"
    assert payload["environment"] == settings.ENVIRONMENT.value
    assert payload["version"] == "0.1.0"
    assert set(payload) == {"status", "environment", "version", "timestamp"}


@pytest.mark.asyncio
async def test_build_readiness_contract_evaluates_template_owned_runtime_dependencies() -> None:
    database = Mock(spec=AsyncSession)
    redis = Mock(spec=Redis)
    queue_pool = Mock()
    rate_limiter_client = Mock(spec=Redis)

    with (
        patch(
            "src.app.core.health.check_database_health",
            new=AsyncMock(return_value=DependencyHealthResult(status="healthy", summary="Database probe succeeded.")),
        ) as database_check,
        patch(
            "src.app.core.health.check_redis_health",
            new=AsyncMock(return_value=DependencyHealthResult(status="healthy", summary="Cache Redis ping succeeded.")),
        ) as redis_check,
        patch(
            "src.app.core.health.check_queue_health",
            new=AsyncMock(return_value=DependencyHealthResult(status="unhealthy", summary="Queue Redis ping failed.")),
        ) as queue_check,
        patch(
            "src.app.core.health.check_rate_limiter_health",
            new=AsyncMock(
                return_value=DependencyHealthResult(status="healthy", summary="Rate limiter Redis ping succeeded.")
            ),
        ) as rate_limiter_check,
    ):
        contract = build_readiness_contract(
            database=database,
            redis=redis,
            queue_pool=queue_pool,
            rate_limiter_client=rate_limiter_client,
        )
        readiness = await contract.evaluate(environment="local", version="0.1.0")

    database_check.assert_awaited_once_with(db=database)
    redis_check.assert_awaited_once_with(redis=redis)
    queue_check.assert_awaited_once_with(queue_pool=queue_pool)
    rate_limiter_check.assert_awaited_once_with(redis=rate_limiter_client)
    assert readiness.status == "unhealthy"
    assert readiness.app == "healthy"
    assert readiness.dependencies == {
        "database": "healthy",
        "redis": "healthy",
        "queue": "unhealthy",
        "rate_limiter": "healthy",
    }


@pytest.mark.asyncio
async def test_check_worker_health_reports_missing_heartbeat() -> None:
    queue_pool = AsyncMock()
    queue_pool.get = AsyncMock(return_value=None)

    health_check = await check_worker_health(queue_pool=queue_pool, queue_name="arq:queue")

    queue_pool.get.assert_awaited_once_with("arq:queue:health-check")
    assert health_check.status == "unhealthy"
    assert health_check.queue_name == "arq:queue"
    assert health_check.summary == "No recent worker heartbeat was observed on the configured queue."


@pytest.mark.asyncio
async def test_check_worker_health_reports_recent_heartbeat() -> None:
    queue_pool = AsyncMock()
    queue_pool.get = AsyncMock(return_value=b"Apr-03 12:00:00 j_complete=1")

    health_check = await check_worker_health(queue_pool=queue_pool, queue_name="arq:queue")

    queue_pool.get.assert_awaited_once_with("arq:queue:health-check")
    assert health_check.status == "healthy"
    assert health_check.queue_name == "arq:queue"
    assert health_check.summary == "Recent worker heartbeat observed on the configured queue."


@pytest.mark.asyncio
async def test_ready_endpoint_consumes_the_runtime_readiness_contract() -> None:
    database = Mock(spec=AsyncSession)
    redis = Mock(spec=Redis)
    readiness = ReadyCheck(
        status="unhealthy",
        environment=settings.ENVIRONMENT.value,
        version="0.1.0",
        app="healthy",
        dependencies={"database": "healthy", "redis": "unhealthy"},
        timestamp="2026-04-01T12:00:00+00:00",
    )
    contract = Mock()
    contract.evaluate = AsyncMock(return_value=readiness)

    with patch("src.app.api.v1.health.build_runtime_readiness_contract", return_value=contract) as build_contract:
        response = await ready(redis=redis, db=database)

    build_contract.assert_called_once_with(db=database, redis=redis)
    contract.evaluate.assert_awaited_once_with(environment=settings.ENVIRONMENT.value, version="0.1.0")
    assert response.status_code == 503
    assert json.loads(response.body) == readiness.model_dump()


@pytest.mark.asyncio
async def test_internal_health_endpoint_returns_dependency_details_and_worker_visibility() -> None:
    database = Mock(spec=AsyncSession)
    redis = Mock(spec=Redis)
    worker = WorkerHealthCheck(
        status="healthy",
        summary="Recent worker heartbeat observed on the configured queue.",
        queue_name=settings.WORKER_QUEUE_NAME,
    )
    diagnostics = InternalHealthCheck(
        status="healthy",
        environment=settings.ENVIRONMENT.value,
        version="0.1.0",
        app="healthy",
        dependencies={
            "database": "healthy",
            "redis": "healthy",
            "queue": "healthy",
            "rate_limiter": "healthy",
        },
        dependency_details={
            "database": {"status": "healthy", "summary": "Database probe succeeded."},
            "redis": {"status": "healthy", "summary": "Cache Redis ping succeeded."},
            "queue": {"status": "healthy", "summary": "Queue Redis ping succeeded."},
            "rate_limiter": {"status": "healthy", "summary": "Rate limiter Redis ping succeeded."},
        },
        worker=worker,
        timestamp="2026-04-03T12:00:00+00:00",
    )
    contract = Mock()
    contract.evaluate_internal = AsyncMock(return_value=diagnostics)

    with (
        patch(
            "src.app.api.v1.internal_health.build_runtime_readiness_contract",
            return_value=contract,
        ) as build_contract,
        patch(
            "src.app.api.v1.internal_health.check_worker_health",
            new=AsyncMock(return_value=worker),
        ) as worker_check,
    ):
        response = await internal_health(redis=redis, db=database)

    build_contract.assert_called_once_with(db=database, redis=redis)
    worker_check.assert_awaited_once()
    assert worker_check.await_args.kwargs["queue_name"] == settings.WORKER_QUEUE_NAME
    contract.evaluate_internal.assert_awaited_once_with(
        environment=settings.ENVIRONMENT.value,
        version="0.1.0",
        worker=worker,
    )
    assert response.status_code == 200
    assert json.loads(response.body) == diagnostics.model_dump()
