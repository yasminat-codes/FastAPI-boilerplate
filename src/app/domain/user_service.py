"""Canonical user service patterns for thin routers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from ..platform.authorization import TemplatePermission, authorize_owner_or_permission
from ..platform.exceptions import DuplicateValueException, NotFoundException
from ..platform.security import blacklist_token, get_password_hash
from .repositories import rate_limit_repository, tier_repository, user_repository
from .schemas import TierRead, UserCreate, UserCreateInternal, UserRead, UserTierUpdate, UserUpdate


class UserService:
    """Own reusable user orchestration outside the router layer."""

    allowed_sort_fields = frozenset({"created_at", "email", "name", "tier_id", "updated_at", "username"})

    async def create_user(self, *, user: UserCreate, db: AsyncSession) -> dict[str, Any]:
        email_row = await user_repository.exists(db=db, email=user.email)
        if email_row:
            raise DuplicateValueException("Email is already registered")

        username_row = await user_repository.exists(db=db, username=user.username)
        if username_row:
            raise DuplicateValueException("Username not available")

        user_internal_dict = user.model_dump()
        user_internal_dict["hashed_password"] = get_password_hash(password=user_internal_dict["password"])
        del user_internal_dict["password"]

        user_internal = UserCreateInternal(**user_internal_dict)
        created_user = await user_repository.create(db=db, object=user_internal, schema_to_select=UserRead)
        if created_user is None:
            raise NotFoundException("Failed to create user")

        return created_user

    async def list_users(
        self,
        *,
        db: AsyncSession,
        offset: int,
        limit: int,
        filters: Mapping[str, Any] | None = None,
        sort_columns: str | list[str] | None = None,
        sort_orders: str | list[str] | None = None,
    ) -> dict[str, Any]:
        repository_filters: dict[str, Any] = {"is_deleted": False}
        if filters:
            repository_filters.update(filters)

        result = await user_repository.get_multi(
            db=db,
            offset=offset,
            limit=limit,
            sort_columns=sort_columns,
            sort_orders=sort_orders,
            **repository_filters,
        )
        return cast(dict[str, Any], result)

    async def read_current_user(self, *, current_user: dict[str, Any]) -> dict[str, Any]:
        return current_user

    async def get_user(self, *, username: str, db: AsyncSession) -> dict[str, Any]:
        db_user = await user_repository.get(db=db, username=username, is_deleted=False, schema_to_select=UserRead)
        if db_user is None:
            raise NotFoundException("User not found")
        return db_user

    async def update_user(
        self,
        *,
        username: str,
        values: UserUpdate,
        current_user: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, str]:
        db_user = await user_repository.get(db=db, username=username)
        if db_user is None:
            raise NotFoundException("User not found")

        authorize_owner_or_permission(
            current_user,
            permission=TemplatePermission.MANAGE_USERS,
            owner_username=db_user["username"],
        )

        if values.email is not None and values.email != db_user["email"]:
            if await user_repository.exists(db=db, email=values.email):
                raise DuplicateValueException("Email is already registered")

        if values.username is not None and values.username != db_user["username"]:
            if await user_repository.exists(db=db, username=values.username):
                raise DuplicateValueException("Username not available")

        await user_repository.update(db=db, object=values, username=username)
        return {"message": "User updated"}

    async def delete_user(
        self,
        *,
        username: str,
        current_user: dict[str, Any],
        db: AsyncSession,
        token: str,
    ) -> dict[str, str]:
        db_user = await user_repository.get(db=db, username=username, schema_to_select=UserRead)
        if not db_user:
            raise NotFoundException("User not found")

        authorize_owner_or_permission(
            current_user,
            permission="users:self:delete:override",
            owner_username=username,
        )

        await user_repository.delete(db=db, username=username)
        await blacklist_token(token=token, db=db)
        return {"message": "User deleted"}

    async def delete_db_user(self, *, username: str, db: AsyncSession, token: str) -> dict[str, str]:
        db_user = await user_repository.exists(db=db, username=username)
        if not db_user:
            raise NotFoundException("User not found")

        await user_repository.db_delete(db=db, username=username)
        await blacklist_token(token=token, db=db)
        return {"message": "User deleted from the database"}

    async def get_user_rate_limits(self, *, username: str, db: AsyncSession) -> dict[str, Any]:
        db_user = await self.get_user(username=username, db=db)
        user_dict = dict(db_user)

        if db_user["tier_id"] is None:
            user_dict["tier_rate_limits"] = []
            return user_dict

        db_tier = await tier_repository.get(db=db, id=db_user["tier_id"], schema_to_select=TierRead)
        if db_tier is None:
            raise NotFoundException("Tier not found")

        db_rate_limits = await rate_limit_repository.get_multi(db=db, tier_id=db_tier["id"])
        user_dict["tier_rate_limits"] = db_rate_limits["data"]
        return user_dict

    async def get_user_tier(self, *, username: str, db: AsyncSession) -> dict[str, Any] | None:
        db_user = await self.get_user(username=username, db=db)
        if db_user["tier_id"] is None:
            return None

        db_tier = await tier_repository.get(db=db, id=db_user["tier_id"], schema_to_select=TierRead)
        if not db_tier:
            raise NotFoundException("Tier not found")

        user_dict = dict(db_user)
        tier_dict = dict(db_tier)
        for key, value in tier_dict.items():
            user_dict[f"tier_{key}"] = value

        return user_dict

    async def update_user_tier(
        self,
        *,
        username: str,
        values: UserTierUpdate,
        db: AsyncSession,
    ) -> dict[str, str]:
        db_user = await self.get_user(username=username, db=db)
        db_tier = await tier_repository.get(db=db, id=values.tier_id, schema_to_select=TierRead)
        if db_tier is None:
            raise NotFoundException("Tier not found")

        await user_repository.update(db=db, object=values.model_dump(), username=username)
        return {"message": f"User {db_user['name']} Tier updated"}


user_service = UserService()

__all__ = ["UserService", "user_service"]
