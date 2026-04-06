from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastcrud import PaginatedListResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.contracts import ApiMessageResponse
from ...api.dependencies import require_permissions
from ...api.query_params import PaginationParams, SortParams, TierListFilters, build_paginated_api_response
from ...domain.schemas import TierCreate, TierRead, TierUpdate
from ...domain.services import tier_service
from ...platform.authorization import TemplatePermission
from ...platform.database import async_get_db

router = APIRouter(tags=["tiers"])


@router.post(
    "/tier",
    dependencies=[Depends(require_permissions(TemplatePermission.MANAGE_TIERS))],
    response_model=TierRead,
    status_code=201,
)
async def write_tier(
    request: Request, tier: TierCreate, db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict[str, Any]:
    return await tier_service.create_tier(tier=tier, db=db)


@router.get("/tiers", response_model=PaginatedListResponse[TierRead])
async def read_tiers(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    pagination: Annotated[PaginationParams, Depends()],
    filters: Annotated[TierListFilters, Depends()],
    sort: Annotated[SortParams, Depends()],
) -> dict[str, Any]:
    tiers_data = await tier_service.list_tiers(
        db=db,
        offset=pagination.offset,
        limit=pagination.limit,
        filters=filters.to_repository_filters(),
        **sort.to_repository_kwargs(allowed_fields=tier_service.allowed_sort_fields),
    )
    return build_paginated_api_response(crud_data=tiers_data, pagination=pagination)


@router.get("/tier/{name}", response_model=TierRead)
async def read_tier(request: Request, name: str, db: Annotated[AsyncSession, Depends(async_get_db)]) -> dict[str, Any]:
    return await tier_service.get_tier(name=name, db=db)


@router.patch(
    "/tier/{name}",
    dependencies=[Depends(require_permissions(TemplatePermission.MANAGE_TIERS))],
    response_model=ApiMessageResponse,
)
async def patch_tier(
    request: Request, name: str, values: TierUpdate, db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict[str, str]:
    return await tier_service.update_tier(name=name, values=values, db=db)


@router.delete(
    "/tier/{name}",
    dependencies=[Depends(require_permissions(TemplatePermission.MANAGE_TIERS))],
    response_model=ApiMessageResponse,
)
async def erase_tier(request: Request, name: str, db: Annotated[AsyncSession, Depends(async_get_db)]) -> dict[str, str]:
    return await tier_service.delete_tier(name=name, db=db)
