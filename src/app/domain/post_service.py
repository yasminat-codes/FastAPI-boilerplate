"""Canonical post service patterns for thin routers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from ..platform.exceptions import ForbiddenException, NotFoundException
from .repositories import post_repository, user_repository
from .schemas import PostCreate, PostCreateInternal, PostRead, PostUpdate, UserRead


class PostService:
    """Own reusable post orchestration that routers delegate to."""

    allowed_sort_fields = frozenset({"created_at", "title", "updated_at"})

    async def _get_user(self, *, db: AsyncSession, username: str) -> dict[str, Any]:
        db_user = await user_repository.get(db=db, username=username, is_deleted=False, schema_to_select=UserRead)
        if db_user is None:
            raise NotFoundException("User not found")
        return db_user

    async def create_post(
        self,
        *,
        username: str,
        post: PostCreate,
        current_user: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        db_user = await self._get_user(db=db, username=username)
        if current_user["id"] != db_user["id"]:
            raise ForbiddenException()

        post_internal_dict = post.model_dump()
        post_internal_dict["created_by_user_id"] = db_user["id"]
        post_internal = PostCreateInternal(**post_internal_dict)
        created_post = await post_repository.create(db=db, object=post_internal, schema_to_select=PostRead)

        if created_post is None:
            raise NotFoundException("Failed to create post")

        return created_post

    async def list_posts(
        self,
        *,
        username: str,
        db: AsyncSession,
        offset: int,
        limit: int,
        filters: Mapping[str, Any] | None = None,
        sort_columns: str | list[str] | None = None,
        sort_orders: str | list[str] | None = None,
    ) -> dict[str, Any]:
        db_user = await self._get_user(db=db, username=username)
        repository_filters: dict[str, Any] = {
            "created_by_user_id": db_user["id"],
            "is_deleted": False,
        }
        if filters:
            repository_filters.update(filters)

        result = await post_repository.get_multi(
            db=db,
            offset=offset,
            limit=limit,
            sort_columns=sort_columns,
            sort_orders=sort_orders,
            **repository_filters,
        )
        return cast(dict[str, Any], result)

    async def get_post(self, *, username: str, post_id: int, db: AsyncSession) -> dict[str, Any]:
        db_user = await self._get_user(db=db, username=username)
        db_post = await post_repository.get(
            db=db,
            id=post_id,
            created_by_user_id=db_user["id"],
            is_deleted=False,
            schema_to_select=PostRead,
        )
        if db_post is None:
            raise NotFoundException("Post not found")
        return db_post

    async def update_post(
        self,
        *,
        username: str,
        post_id: int,
        values: PostUpdate,
        current_user: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, str]:
        db_user = await self._get_user(db=db, username=username)
        if current_user["id"] != db_user["id"]:
            raise ForbiddenException()

        db_post = await post_repository.get(db=db, id=post_id, is_deleted=False, schema_to_select=PostRead)
        if db_post is None:
            raise NotFoundException("Post not found")

        await post_repository.update(db=db, object=values, id=post_id)
        return {"message": "Post updated"}

    async def delete_post(
        self,
        *,
        username: str,
        post_id: int,
        current_user: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, str]:
        db_user = await self._get_user(db=db, username=username)
        if current_user["id"] != db_user["id"]:
            raise ForbiddenException()

        db_post = await post_repository.get(db=db, id=post_id, is_deleted=False, schema_to_select=PostRead)
        if db_post is None:
            raise NotFoundException("Post not found")

        await post_repository.delete(db=db, id=post_id)
        return {"message": "Post deleted"}

    async def delete_db_post(self, *, username: str, post_id: int, db: AsyncSession) -> dict[str, str]:
        await self._get_user(db=db, username=username)

        db_post = await post_repository.get(db=db, id=post_id, is_deleted=False, schema_to_select=PostRead)
        if db_post is None:
            raise NotFoundException("Post not found")

        await post_repository.db_delete(db=db, id=post_id)
        return {"message": "Post deleted from the database"}


post_service = PostService()

__all__ = ["PostService", "post_service"]
