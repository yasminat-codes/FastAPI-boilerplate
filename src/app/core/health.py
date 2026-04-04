import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from arq.connections import ArqRedis
from arq.worker import health_check_key_suffix
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .schemas import DependencyHealthDetail, InternalHealthCheck, ReadyCheck, WorkerHealthCheck

LOGGER = logging.getLogger(__name__)
STATUS_HEALTHY = "healthy"
STATUS_UNHEALTHY = "unhealthy"

ReadinessCheck = Callable[[], Awaitable["DependencyHealthResult"]]


@dataclass(slots=True)
class DependencyHealthResult:
    status: str
    summary: str


@dataclass(slots=True)
class ReadinessSnapshot:
    status: str
    dependency_statuses: dict[str, str]
    dependency_details: dict[str, DependencyHealthDetail]


def _healthy_result(summary: str) -> DependencyHealthResult:
    return DependencyHealthResult(status=STATUS_HEALTHY, summary=summary)


def _unhealthy_result(summary: str) -> DependencyHealthResult:
    return DependencyHealthResult(status=STATUS_UNHEALTHY, summary=summary)


@dataclass(slots=True)
class ReadinessContract:
    """Reusable readiness evaluation contract for template-owned dependencies."""

    dependencies: dict[str, ReadinessCheck]

    async def snapshot(self) -> ReadinessSnapshot:
        dependency_statuses: dict[str, str] = {}
        dependency_details: dict[str, DependencyHealthDetail] = {}

        for name, checker in self.dependencies.items():
            result = await checker()
            dependency_statuses[name] = result.status
            dependency_details[name] = DependencyHealthDetail(status=result.status, summary=result.summary)

        dependencies_are_healthy = all(status == STATUS_HEALTHY for status in dependency_statuses.values())
        overall_status = STATUS_HEALTHY if dependencies_are_healthy else STATUS_UNHEALTHY

        return ReadinessSnapshot(
            status=overall_status,
            dependency_statuses=dependency_statuses,
            dependency_details=dependency_details,
        )

    async def evaluate(self, *, environment: str, version: str) -> ReadyCheck:
        snapshot = await self.snapshot()

        return ReadyCheck(
            status=snapshot.status,
            environment=environment,
            version=version,
            app=STATUS_HEALTHY,
            dependencies=snapshot.dependency_statuses,
            timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    async def evaluate_internal(
        self,
        *,
        environment: str,
        version: str,
        worker: WorkerHealthCheck,
    ) -> InternalHealthCheck:
        snapshot = await self.snapshot()
        statuses = [*snapshot.dependency_statuses.values(), worker.status]
        overall_status = STATUS_HEALTHY if all(status == STATUS_HEALTHY for status in statuses) else STATUS_UNHEALTHY

        return InternalHealthCheck(
            status=overall_status,
            environment=environment,
            version=version,
            app=STATUS_HEALTHY,
            dependencies=snapshot.dependency_statuses,
            dependency_details=snapshot.dependency_details,
            worker=worker,
            timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        )


def build_readiness_contract(
    *,
    database: AsyncSession,
    redis: Redis,
    queue_pool: ArqRedis | None,
    rate_limiter_client: Redis | None,
) -> ReadinessContract:
    return ReadinessContract(
        dependencies={
            "database": lambda: check_database_health(db=database),
            "redis": lambda: check_redis_health(redis=redis),
            "queue": lambda: check_queue_health(queue_pool=queue_pool),
            "rate_limiter": lambda: check_rate_limiter_health(redis=rate_limiter_client),
        }
    )


async def check_database_health(db: AsyncSession) -> DependencyHealthResult:
    try:
        await db.execute(text("SELECT 1"))
        return _healthy_result("Database probe succeeded.")
    except Exception as exc:
        LOGGER.exception("Database health check failed with error: %s", exc)
        return _unhealthy_result("Database probe failed.")


async def check_redis_health(redis: Redis) -> DependencyHealthResult:
    try:
        await redis.ping()
        return _healthy_result("Cache Redis ping succeeded.")
    except Exception as exc:
        LOGGER.exception("Redis health check failed with error: %s", exc)
        return _unhealthy_result("Cache Redis ping failed.")


async def check_queue_health(queue_pool: ArqRedis | None) -> DependencyHealthResult:
    if queue_pool is None:
        return _unhealthy_result("Shared queue pool is not initialized.")

    try:
        await queue_pool.ping()  # type: ignore[attr-defined]
        return _healthy_result("Queue Redis ping succeeded.")
    except Exception as exc:
        LOGGER.exception("Queue health check failed with error: %s", exc)
        return _unhealthy_result("Queue Redis ping failed.")


async def check_rate_limiter_health(redis: Redis | None) -> DependencyHealthResult:
    if redis is None:
        return _unhealthy_result("Rate limiter Redis client is not initialized.")

    try:
        await redis.ping()
        return _healthy_result("Rate limiter Redis ping succeeded.")
    except Exception as exc:
        LOGGER.exception("Rate limiter health check failed with error: %s", exc)
        return _unhealthy_result("Rate limiter Redis ping failed.")


async def check_worker_health(
    *,
    queue_pool: ArqRedis | None,
    queue_name: str,
    health_check_key: str | None = None,
) -> WorkerHealthCheck:
    if queue_pool is None:
        return WorkerHealthCheck(
            status=STATUS_UNHEALTHY,
            summary="Queue pool is not initialized; worker heartbeat cannot be checked.",
            queue_name=queue_name,
        )

    resolved_health_check_key = health_check_key or f"{queue_name}{health_check_key_suffix}"

    try:
        heartbeat = await queue_pool.get(resolved_health_check_key)  # type: ignore[attr-defined]
    except Exception as exc:
        LOGGER.exception("Worker health check failed with error: %s", exc)
        return WorkerHealthCheck(
            status=STATUS_UNHEALTHY,
            summary="Worker heartbeat lookup failed.",
            queue_name=queue_name,
        )

    if not heartbeat:
        return WorkerHealthCheck(
            status=STATUS_UNHEALTHY,
            summary="No recent worker heartbeat was observed on the configured queue.",
            queue_name=queue_name,
        )

    return WorkerHealthCheck(
        status=STATUS_HEALTHY,
        summary="Recent worker heartbeat observed on the configured queue.",
        queue_name=queue_name,
    )
