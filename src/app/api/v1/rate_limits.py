from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastcrud import PaginatedListResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.contracts import ApiMessageResponse
from ...api.dependencies import require_permissions
from ...api.query_params import PaginationParams, RateLimitListFilters, SortParams, build_paginated_api_response
from ...domain.schemas import RateLimitCreate, RateLimitRead, RateLimitUpdate
from ...domain.services import rate_limit_service
from ...platform.authorization import TemplatePermission
from ...platform.database import async_get_db

router = APIRouter(tags=["rate_limits"])


@router.post(
    "/tier/{tier_name}/rate_limit",
    dependencies=[Depends(require_permissions(TemplatePermission.MANAGE_RATE_LIMITS))],
    response_model=RateLimitRead,
    status_code=201,
)
async def write_rate_limit(
    request: Request, tier_name: str, rate_limit: RateLimitCreate, db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict[str, Any]:
    return await rate_limit_service.create_rate_limit(tier_name=tier_name, rate_limit=rate_limit, db=db)


@router.get("/tier/{tier_name}/rate_limits", response_model=PaginatedListResponse[RateLimitRead])
async def read_rate_limits(
    request: Request,
    tier_name: str,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    pagination: Annotated[PaginationParams, Depends()],
    filters: Annotated[RateLimitListFilters, Depends()],
    sort: Annotated[SortParams, Depends()],
) -> dict[str, Any]:
    rate_limits_data = await rate_limit_service.list_rate_limits(
        tier_name=tier_name,
        db=db,
        offset=pagination.offset,
        limit=pagination.limit,
        filters=filters.to_repository_filters(),
        **sort.to_repository_kwargs(allowed_fields=rate_limit_service.allowed_sort_fields),
    )
    return build_paginated_api_response(crud_data=rate_limits_data, pagination=pagination)


@router.get("/tier/{tier_name}/rate_limit/{id}", response_model=RateLimitRead)
async def read_rate_limit(
    request: Request, tier_name: str, id: int, db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict[str, Any]:
    return await rate_limit_service.get_rate_limit(tier_name=tier_name, rate_limit_id=id, db=db)


@router.patch(
    "/tier/{tier_name}/rate_limit/{id}",
    dependencies=[Depends(require_permissions(TemplatePermission.MANAGE_RATE_LIMITS))],
    response_model=ApiMessageResponse,
)
async def patch_rate_limit(
    request: Request,
    tier_name: str,
    id: int,
    values: RateLimitUpdate,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    return await rate_limit_service.update_rate_limit(tier_name=tier_name, rate_limit_id=id, values=values, db=db)


@router.delete(
    "/tier/{tier_name}/rate_limit/{id}",
    dependencies=[Depends(require_permissions(TemplatePermission.MANAGE_RATE_LIMITS))],
    response_model=ApiMessageResponse,
)
async def erase_rate_limit(
    request: Request, tier_name: str, id: int, db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict[str, str]:
    return await rate_limit_service.delete_rate_limit(tier_name=tier_name, rate_limit_id=id, db=db)
