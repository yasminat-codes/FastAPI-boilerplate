import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.db.database import async_get_db
from ...core.health import STATUS_HEALTHY, build_readiness_contract
from ...core.schemas import HealthCheck, ReadyCheck
from ...core.utils.cache import async_get_redis

router = APIRouter(tags=["health"])

LOGGER = logging.getLogger(__name__)
DEFAULT_APP_VERSION = "0.1.0"


def get_app_version() -> str:
    return settings.APP_VERSION or DEFAULT_APP_VERSION


@router.get("/health", response_model=HealthCheck)
async def health():
    http_status = status.HTTP_200_OK
    response = {
        "status": STATUS_HEALTHY,
        "environment": settings.ENVIRONMENT.value,
        "version": get_app_version(),
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
    }

    return JSONResponse(status_code=http_status, content=response)


@router.get("/ready", response_model=ReadyCheck)
async def ready(redis: Annotated[Redis, Depends(async_get_redis)], db: Annotated[AsyncSession, Depends(async_get_db)]):
    readiness_contract = build_readiness_contract(database=db, redis=redis)
    readiness = await readiness_contract.evaluate(environment=settings.ENVIRONMENT.value, version=get_app_version())
    http_status = status.HTTP_200_OK if readiness.status == STATUS_HEALTHY else status.HTTP_503_SERVICE_UNAVAILABLE

    LOGGER.debug("Readiness contract evaluated with status: %s", readiness.status)

    return JSONResponse(status_code=http_status, content=readiness.model_dump())
