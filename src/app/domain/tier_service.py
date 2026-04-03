"""Canonical tier service patterns for thin routers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from ..platform.exceptions import DuplicateValueException, NotFoundException
from .repositories import tier_repository
from .schemas import TierCreate, TierCreateInternal, TierRead, TierUpdate


class TierService:
    """Own reusable tier orchestration outside the router layer."""

    allowed_sort_fields = frozenset({"created_at", "name", "updated_at"})

    async def create_tier(self, *, tier: TierCreate, db: AsyncSession) -> dict[str, Any]:
        tier_internal_dict = tier.model_dump()
        db_tier = await tier_repository.exists(db=db, name=tier_internal_dict["name"])
        if db_tier:
            raise DuplicateValueException("Tier Name not available")

        tier_internal = TierCreateInternal(**tier_internal_dict)
        created_tier = await tier_repository.create(db=db, object=tier_internal, schema_to_select=TierRead)
        if created_tier is None:
            raise NotFoundException("Failed to create tier")

        return created_tier

    async def list_tiers(
        self,
        *,
        db: AsyncSession,
        offset: int,
        limit: int,
        filters: Mapping[str, Any] | None = None,
        sort_columns: str | list[str] | None = None,
        sort_orders: str | list[str] | None = None,
    ) -> dict[str, Any]:
        repository_filters: dict[str, Any] = dict(filters or {})
        result = await tier_repository.get_multi(
            db=db,
            offset=offset,
            limit=limit,
            sort_columns=sort_columns,
            sort_orders=sort_orders,
            **repository_filters,
        )
        return cast(dict[str, Any], result)

    async def get_tier(self, *, name: str, db: AsyncSession) -> dict[str, Any]:
        db_tier = await tier_repository.get(db=db, name=name, schema_to_select=TierRead)
        if db_tier is None:
            raise NotFoundException("Tier not found")
        return db_tier

    async def update_tier(self, *, name: str, values: TierUpdate, db: AsyncSession) -> dict[str, str]:
        await self.get_tier(name=name, db=db)
        await tier_repository.update(db=db, object=values, name=name)
        return {"message": "Tier updated"}

    async def delete_tier(self, *, name: str, db: AsyncSession) -> dict[str, str]:
        await self.get_tier(name=name, db=db)
        await tier_repository.delete(db=db, name=name)
        return {"message": "Tier deleted"}


tier_service = TierService()

__all__ = ["TierService", "tier_service"]
