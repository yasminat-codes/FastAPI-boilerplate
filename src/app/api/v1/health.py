import logging
from datetime import UTC, datetime
from typing import Annotated, cast

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.schemas import HealthCheck, ReadyCheck
from ...platform import queue as shared_queue
from ...platform.cache import async_get_redis
from ...platform.config import settings
from ...platform.database import async_get_db
from ...platform.health import ReadinessContract, build_readiness_contract
from ...platform.rate_limit import rate_limiter

STATUS_HEALTHY = "healthy"

router = APIRouter(tags=["ops"])

LOGGER = logging.getLogger(__name__)
DEFAULT_APP_VERSION = "0.1.0"


def get_app_version() -> str:
    return settings.APP_VERSION or DEFAULT_APP_VERSION


def resolve_rate_limiter_client() -> Redis | None:
    try:
        return rate_limiter.get_client()
    except Exception:
        LOGGER.debug("Rate limiter client is unavailable for readiness checks.")
        return None


def build_runtime_readiness_contract(*, db: AsyncSession, redis: Redis) -> ReadinessContract:
    return build_readiness_contract(
        database=db,
        redis=redis,
        queue_pool=cast("ArqRedis | None", shared_queue.pool),
        rate_limiter_client=resolve_rate_limiter_client(),
    )


@router.get("/health", response_model=HealthCheck)
async def health() -> JSONResponse:
    http_status = status.HTTP_200_OK
    response = {
        "status": STATUS_HEALTHY,
        "environment": settings.ENVIRONMENT.value,
        "version": get_app_version(),
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
    }

    return JSONResponse(status_code=http_status, content=response)


@router.get("/ready", response_model=ReadyCheck)
async def ready(
    redis: Annotated[Redis, Depends(async_get_redis)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> JSONResponse:
    readiness_contract = build_runtime_readiness_contract(db=db, redis=redis)
    readiness = await readiness_contract.evaluate(environment=settings.ENVIRONMENT.value, version=get_app_version())
    http_status = status.HTTP_200_OK if readiness.status == STATUS_HEALTHY else status.HTTP_503_SERVICE_UNAVAILABLE

    LOGGER.debug("Readiness contract evaluated with status: %s", readiness.status)

    return JSONResponse(status_code=http_status, content=readiness.model_dump())
