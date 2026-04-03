import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .schemas import ReadyCheck

LOGGER = logging.getLogger(__name__)
STATUS_HEALTHY = "healthy"
STATUS_UNHEALTHY = "unhealthy"

ReadinessCheck = Callable[[], Awaitable[bool]]


@dataclass(slots=True)
class ReadinessContract:
    """Reusable readiness evaluation contract for template-owned dependencies."""

    dependencies: dict[str, ReadinessCheck]

    async def evaluate(self, *, environment: str, version: str) -> ReadyCheck:
        dependency_statuses: dict[str, str] = {}

        for name, checker in self.dependencies.items():
            dependency_statuses[name] = STATUS_HEALTHY if await checker() else STATUS_UNHEALTHY

        dependencies_are_healthy = all(status == STATUS_HEALTHY for status in dependency_statuses.values())
        overall_status = STATUS_HEALTHY if dependencies_are_healthy else STATUS_UNHEALTHY

        return ReadyCheck(
            status=overall_status,
            environment=environment,
            version=version,
            app=STATUS_HEALTHY,
            dependencies=dependency_statuses,
            timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        )


def build_readiness_contract(*, database: AsyncSession, redis: Redis) -> ReadinessContract:
    return ReadinessContract(
        dependencies={
            "database": lambda: check_database_health(db=database),
            "redis": lambda: check_redis_health(redis=redis),
        }
    )


async def check_database_health(db: AsyncSession) -> bool:
    try:
        await db.execute(text("SELECT 1"))
        return True
    except Exception as e:
        LOGGER.exception(f"Database health check failed with error: {e}")
        return False


async def check_redis_health(redis: Redis) -> bool:
    try:
        await redis.ping()
        return True
    except Exception as e:
        LOGGER.exception(f"Redis health check failed with error: {e}")
        return False
