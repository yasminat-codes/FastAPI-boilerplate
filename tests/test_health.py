import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.v1.health import ready
from src.app.core.config import settings
from src.app.core.health import build_readiness_contract
from src.app.core.schemas import ReadyCheck


@pytest.mark.asyncio
async def test_build_readiness_contract_evaluates_template_owned_dependencies() -> None:
    database = Mock(spec=AsyncSession)
    redis = Mock(spec=Redis)

    with (
        patch("src.app.core.health.check_database_health", new=AsyncMock(return_value=True)) as database_check,
        patch("src.app.core.health.check_redis_health", new=AsyncMock(return_value=False)) as redis_check,
    ):
        contract = build_readiness_contract(database=database, redis=redis)
        readiness = await contract.evaluate(environment="local", version="0.1.0")

    database_check.assert_awaited_once_with(db=database)
    redis_check.assert_awaited_once_with(redis=redis)
    assert readiness.status == "unhealthy"
    assert readiness.app == "healthy"
    assert readiness.dependencies == {"database": "healthy", "redis": "unhealthy"}


@pytest.mark.asyncio
async def test_ready_endpoint_consumes_the_readiness_contract() -> None:
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

    with patch("src.app.api.v1.health.build_readiness_contract", return_value=contract) as build_contract:
        response = await ready(redis=redis, db=database)

    build_contract.assert_called_once_with(database=database, redis=redis)
    contract.evaluate.assert_awaited_once_with(environment=settings.ENVIRONMENT.value, version="0.1.0")
    assert response.status_code == 503
    assert json.loads(response.body) == readiness.model_dump()
