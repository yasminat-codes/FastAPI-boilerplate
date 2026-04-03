# API Pagination

The template now exposes reusable list-endpoint helpers in `src/app/api/query_params.py` so cloned projects do not need to rebuild pagination, filtering, and sorting validation per router.

## Shared Query Models

Use these helpers for reusable resource lists:

- `PaginationParams`
- `SortParams`
- typed filter models such as `UserListFilters`, `PostListFilters`, `TierListFilters`, and `RateLimitListFilters`
- `build_paginated_api_response(...)`

## Canonical Pattern

```python
from typing import Annotated

from fastapi import APIRouter, Depends
from fastcrud import PaginatedListResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.api.query_params import (
    PaginationParams,
    SortParams,
    UserListFilters,
    build_paginated_api_response,
)
from src.app.domain.schemas import UserRead
from src.app.domain.services import user_service
from src.app.platform.database import async_get_db

router = APIRouter(tags=["users"])


@router.get("/users", response_model=PaginatedListResponse[UserRead])
async def read_users(
    db: Annotated[AsyncSession, Depends(async_get_db)],
    pagination: Annotated[PaginationParams, Depends()],
    filters: Annotated[UserListFilters, Depends()],
    sort: Annotated[SortParams, Depends()],
) -> dict:
    users_data = await user_service.list_users(
        db=db,
        offset=pagination.offset,
        limit=pagination.limit,
        filters=filters.to_repository_filters(),
        **sort.to_repository_kwargs(allowed_fields=user_service.allowed_sort_fields),
    )
    return build_paginated_api_response(crud_data=users_data, pagination=pagination)
```

## Conventions

### Pagination

- `page` starts at `1`
- `items_per_page` defaults to `10`
- `items_per_page` is capped at `100` by the shared model
- routers should use `pagination.offset` and `pagination.limit` instead of recomputing offsets manually

### Filtering

Filters should be typed and resource-specific. The shared filter models convert request parameters into repository kwargs such as:

- `name__icontains`
- `username__icontains`
- `email__icontains`
- `title__icontains`
- `path__icontains`

If a cloned project needs richer filtering, add another typed filter model instead of accepting an unstructured `dict` of query params directly from the router.

### Sorting

`SortParams` validates the requested sort field against the owning service's allowlist. Each service defines its own supported fields, for example:

```python
allowed_sort_fields = frozenset({"created_at", "email", "name", "updated_at"})
```

That keeps sorting explicit and prevents clients from probing arbitrary column names.

## What Stays In The Router

Pagination response shaping is still an API concern, so the router should call `build_paginated_api_response(...)` after the service returns its list result. That keeps FastCRUD's response format at the HTTP boundary while the service remains reusable outside FastAPI.
