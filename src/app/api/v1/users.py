from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastcrud import PaginatedListResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.contracts import ApiMessageResponse
from ...api.dependencies import get_current_user, require_permissions
from ...api.query_params import PaginationParams, SortParams, UserListFilters, build_paginated_api_response
from ...domain.schemas import UserCreate, UserRead, UserTierUpdate, UserUpdate
from ...domain.services import user_service
from ...platform.authorization import TemplatePermission
from ...platform.database import async_get_db
from ...platform.security import oauth2_scheme

router = APIRouter(tags=["users"])


@router.post("/user", response_model=UserRead, status_code=201)
async def write_user(
    request: Request, user: UserCreate, db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict[str, Any]:
    return await user_service.create_user(user=user, db=db)


@router.get("/users", response_model=PaginatedListResponse[UserRead])
async def read_users(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    pagination: Annotated[PaginationParams, Depends()],
    filters: Annotated[UserListFilters, Depends()],
    sort: Annotated[SortParams, Depends()],
) -> dict[str, Any]:
    users_data = await user_service.list_users(
        db=db,
        offset=pagination.offset,
        limit=pagination.limit,
        filters=filters.to_repository_filters(),
        **sort.to_repository_kwargs(allowed_fields=user_service.allowed_sort_fields),
    )
    return build_paginated_api_response(crud_data=users_data, pagination=pagination)


@router.get("/user/me/", response_model=UserRead)
async def read_users_me(request: Request, current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
    return await user_service.read_current_user(current_user=current_user)


@router.get("/user/{username}", response_model=UserRead)
async def read_user(
    request: Request, username: str, db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict[str, Any]:
    return await user_service.get_user(username=username, db=db)


@router.patch("/user/{username}", response_model=ApiMessageResponse)
async def patch_user(
    request: Request,
    values: UserUpdate,
    username: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    return await user_service.update_user(username=username, values=values, current_user=current_user, db=db)


@router.delete("/user/{username}", response_model=ApiMessageResponse)
async def erase_user(
    request: Request,
    username: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
    token: str = Depends(oauth2_scheme),
) -> dict[str, str]:
    return await user_service.delete_user(username=username, current_user=current_user, db=db, token=token)


@router.delete(
    "/db_user/{username}",
    dependencies=[Depends(require_permissions(TemplatePermission.MANAGE_USERS))],
    response_model=ApiMessageResponse,
)
async def erase_db_user(
    request: Request,
    username: str,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    token: str = Depends(oauth2_scheme),
) -> dict[str, str]:
    return await user_service.delete_db_user(username=username, db=db, token=token)


@router.get(
    "/user/{username}/rate_limits",
    dependencies=[Depends(require_permissions(TemplatePermission.MANAGE_RATE_LIMITS))],
)
async def read_user_rate_limits(
    request: Request, username: str, db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict[str, Any]:
    return await user_service.get_user_rate_limits(username=username, db=db)


@router.get("/user/{username}/tier")
async def read_user_tier(
    request: Request, username: str, db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict | None:
    return await user_service.get_user_tier(username=username, db=db)


@router.patch(
    "/user/{username}/tier",
    dependencies=[
        Depends(require_permissions(TemplatePermission.MANAGE_USERS, TemplatePermission.MANAGE_TIERS)),
    ],
    response_model=ApiMessageResponse,
)
async def patch_user_tier(
    request: Request, username: str, values: UserTierUpdate, db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict[str, str]:
    return await user_service.update_user_tier(username=username, values=values, db=db)
