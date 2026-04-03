from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastcrud import PaginatedListResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.contracts import ApiMessageResponse
from ...api.dependencies import get_current_superuser, get_current_user
from ...api.query_params import PaginationParams, PostListFilters, SortParams, build_paginated_api_response
from ...domain.schemas import PostCreate, PostRead, PostUpdate
from ...domain.services import post_service
from ...platform.cache import cache
from ...platform.database import async_get_db

router = APIRouter(tags=["posts"])


@router.post("/{username}/post", response_model=PostRead, status_code=201)
async def write_post(
    request: Request,
    username: str,
    post: PostCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any]:
    return await post_service.create_post(username=username, post=post, current_user=current_user, db=db)


@router.get("/{username}/posts", response_model=PaginatedListResponse[PostRead])
@cache(
    key_prefix="{username}_posts:page_{page}:items_per_page:{items_per_page}",
    resource_id_name="username",
    expiration=60,
)
async def read_posts(
    request: Request,
    username: str,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    pagination: Annotated[PaginationParams, Depends()],
    filters: Annotated[PostListFilters, Depends()],
    sort: Annotated[SortParams, Depends()],
) -> dict[str, Any]:
    posts_data = await post_service.list_posts(
        username=username,
        db=db,
        offset=pagination.offset,
        limit=pagination.limit,
        filters=filters.to_repository_filters(),
        **sort.to_repository_kwargs(allowed_fields=post_service.allowed_sort_fields),
    )
    return build_paginated_api_response(crud_data=posts_data, pagination=pagination)


@router.get("/{username}/post/{id}", response_model=PostRead)
@cache(key_prefix="{username}_post_cache", resource_id_name="id")
async def read_post(
    request: Request, username: str, id: int, db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict[str, Any]:
    return await post_service.get_post(username=username, post_id=id, db=db)


@router.patch("/{username}/post/{id}", response_model=ApiMessageResponse)
@cache("{username}_post_cache", resource_id_name="id", pattern_to_invalidate_extra=["{username}_posts:*"])
async def patch_post(
    request: Request,
    username: str,
    id: int,
    values: PostUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    return await post_service.update_post(
        username=username,
        post_id=id,
        values=values,
        current_user=current_user,
        db=db,
    )


@router.delete("/{username}/post/{id}", response_model=ApiMessageResponse)
@cache("{username}_post_cache", resource_id_name="id", to_invalidate_extra={"{username}_posts": "{username}"})
async def erase_post(
    request: Request,
    username: str,
    id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    return await post_service.delete_post(username=username, post_id=id, current_user=current_user, db=db)


@router.delete(
    "/{username}/db_post/{id}",
    dependencies=[Depends(get_current_superuser)],
    response_model=ApiMessageResponse,
)
@cache("{username}_post_cache", resource_id_name="id", to_invalidate_extra={"{username}_posts": "{username}"})
async def erase_db_post(
    request: Request, username: str, id: int, db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict[str, str]:
    return await post_service.delete_db_post(username=username, post_id=id, db=db)
