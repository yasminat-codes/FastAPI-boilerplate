from datetime import UTC, datetime
from typing import Any, Optional

from redis.asyncio import ConnectionPool, Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.logger import logging
from ...schemas.rate_limit import sanitize_path

logger = logging.getLogger(__name__)


class RateLimiter:
    _instance: Optional["RateLimiter"] = None
    pool: ConnectionPool | None = None
    client: Redis | None = None

    def __new__(cls) -> "RateLimiter":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def initialize(cls, redis_url: str, **connection_pool_kwargs: Any) -> None:
        instance = cls()
        if instance.pool is None:
            instance.pool = ConnectionPool.from_url(redis_url, **connection_pool_kwargs)
            instance.client = Redis(connection_pool=instance.pool)

    @classmethod
    async def shutdown(cls) -> None:
        instance = cls()
        if instance.client is not None:
            await instance.client.aclose()  # type: ignore[attr-defined]

        if instance.pool is not None and hasattr(instance.pool, "aclose"):
            await instance.pool.aclose()  # type: ignore[attr-defined]

        instance.client = None
        instance.pool = None

    @classmethod
    def get_client(cls) -> Redis:
        instance = cls()
        if instance.client is None:
            logger.error("Redis client is not initialized.")
            raise Exception("Redis client is not initialized.")
        return instance.client

    async def is_rate_limited(
        self,
        db: AsyncSession,
        subject_id: str | int,
        path: str,
        limit: int,
        period: int,
    ) -> bool:
        client = self.get_client()
        current_timestamp = int(datetime.now(UTC).timestamp())
        window_start = current_timestamp - (current_timestamp % period)

        sanitized_path = sanitize_path(path)
        subject_key = str(subject_id)
        key = f"ratelimit:{subject_key}:{sanitized_path}:{window_start}"

        try:
            current_count = await client.incr(key)
            if current_count == 1:
                await client.expire(key, period)

            if current_count > limit:
                return True

        except Exception as e:
            logger.exception(f"Error checking rate limit for subject {subject_key} on path {path}: {e}")
            raise e

        return False


rate_limiter = RateLimiter()
