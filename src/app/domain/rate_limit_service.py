"""Canonical rate-limit service patterns for thin routers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from ..platform.exceptions import DuplicateValueException, NotFoundException
from .repositories import rate_limit_repository, tier_repository
from .schemas import RateLimitCreate, RateLimitCreateInternal, RateLimitRead, RateLimitUpdate, TierRead


class RateLimitService:
    """Own reusable rate-limit orchestration outside the router layer."""

    allowed_sort_fields = frozenset({"created_at", "limit", "name", "path", "period", "updated_at"})

    async def _get_tier(self, *, db: AsyncSession, tier_name: str) -> dict[str, Any]:
        db_tier = await tier_repository.get(db=db, name=tier_name, schema_to_select=TierRead)
        if not db_tier:
            raise NotFoundException("Tier not found")
        return db_tier

    async def create_rate_limit(
        self,
        *,
        tier_name: str,
        rate_limit: RateLimitCreate,
        db: AsyncSession,
    ) -> dict[str, Any]:
        db_tier = await self._get_tier(db=db, tier_name=tier_name)
        rate_limit_internal_dict = rate_limit.model_dump()
        rate_limit_internal_dict["tier_id"] = db_tier["id"]

        db_rate_limit = await rate_limit_repository.exists(db=db, name=rate_limit_internal_dict["name"])
        if db_rate_limit:
            raise DuplicateValueException("Rate Limit Name not available")

        rate_limit_internal = RateLimitCreateInternal(**rate_limit_internal_dict)
        created_rate_limit = await rate_limit_repository.create(
            db=db,
            object=rate_limit_internal,
            schema_to_select=RateLimitRead,
        )

        if created_rate_limit is None:
            raise NotFoundException("Failed to create rate limit")

        return created_rate_limit

    async def list_rate_limits(
        self,
        *,
        tier_name: str,
        db: AsyncSession,
        offset: int,
        limit: int,
        filters: Mapping[str, Any] | None = None,
        sort_columns: str | list[str] | None = None,
        sort_orders: str | list[str] | None = None,
    ) -> dict[str, Any]:
        db_tier = await self._get_tier(db=db, tier_name=tier_name)
        repository_filters: dict[str, Any] = {"tier_id": db_tier["id"]}
        if filters:
            repository_filters.update(filters)

        result = await rate_limit_repository.get_multi(
            db=db,
            offset=offset,
            limit=limit,
            sort_columns=sort_columns,
            sort_orders=sort_orders,
            **repository_filters,
        )
        return cast(dict[str, Any], result)

    async def get_rate_limit(self, *, tier_name: str, rate_limit_id: int, db: AsyncSession) -> dict[str, Any]:
        db_tier = await self._get_tier(db=db, tier_name=tier_name)
        db_rate_limit = await rate_limit_repository.get(
            db=db,
            tier_id=db_tier["id"],
            id=rate_limit_id,
            schema_to_select=RateLimitRead,
        )
        if db_rate_limit is None:
            raise NotFoundException("Rate Limit not found")
        return db_rate_limit

    async def update_rate_limit(
        self,
        *,
        tier_name: str,
        rate_limit_id: int,
        values: RateLimitUpdate,
        db: AsyncSession,
    ) -> dict[str, str]:
        db_tier = await self._get_tier(db=db, tier_name=tier_name)
        db_rate_limit = await rate_limit_repository.get(
            db=db,
            tier_id=db_tier["id"],
            id=rate_limit_id,
            schema_to_select=RateLimitRead,
        )
        if db_rate_limit is None:
            raise NotFoundException("Rate Limit not found")

        await rate_limit_repository.update(db=db, object=values, id=rate_limit_id)
        return {"message": "Rate Limit updated"}

    async def delete_rate_limit(self, *, tier_name: str, rate_limit_id: int, db: AsyncSession) -> dict[str, str]:
        db_tier = await self._get_tier(db=db, tier_name=tier_name)
        db_rate_limit = await rate_limit_repository.get(
            db=db,
            tier_id=db_tier["id"],
            id=rate_limit_id,
            schema_to_select=RateLimitRead,
        )
        if db_rate_limit is None:
            raise NotFoundException("Rate Limit not found")

        await rate_limit_repository.delete(db=db, id=rate_limit_id)
        return {"message": "Rate Limit deleted"}


rate_limit_service = RateLimitService()

__all__ = ["RateLimitService", "rate_limit_service"]
