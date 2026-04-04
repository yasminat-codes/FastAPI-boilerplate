from typing import Annotated, cast

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.schemas import InternalHealthCheck
from ...platform import queue as shared_queue
from ...platform.cache import async_get_redis
from ...platform.config import settings
from ...platform.database import async_get_db
from ...platform.health import check_worker_health
from .health import build_runtime_readiness_contract, get_app_version

STATUS_HEALTHY = "healthy"

router = APIRouter(tags=["internal"])


@router.get("/health", response_model=InternalHealthCheck)
async def internal_health(
    redis: Annotated[Redis, Depends(async_get_redis)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> JSONResponse:
    readiness_contract = build_runtime_readiness_contract(db=db, redis=redis)
    worker = await check_worker_health(
        queue_pool=cast("ArqRedis | None", shared_queue.pool),
        queue_name=settings.WORKER_QUEUE_NAME,
    )
    diagnostics = await readiness_contract.evaluate_internal(
        environment=settings.ENVIRONMENT.value,
        version=get_app_version(),
        worker=worker,
    )
    http_status = status.HTTP_200_OK if diagnostics.status == STATUS_HEALTHY else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=http_status, content=diagnostics.model_dump())
