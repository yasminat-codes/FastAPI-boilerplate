import pytest

from src.app.api.query_params import (
    PaginationParams,
    RateLimitListFilters,
    SortParams,
    UserListFilters,
    build_paginated_api_response,
)
from src.app.platform.exceptions import BadRequestException


def test_pagination_params_compute_offset_and_limit() -> None:
    pagination = PaginationParams(page=3, items_per_page=25)

    assert pagination.offset == 50
    assert pagination.limit == 25


def test_build_paginated_api_response_uses_the_pagination_contract() -> None:
    response = build_paginated_api_response(
        crud_data={"data": [{"id": 1}], "count": 3},
        pagination=PaginationParams(page=2, items_per_page=1),
    )

    assert response["data"] == [{"id": 1}]
    assert response["page"] == 2
    assert response["items_per_page"] == 1
    assert response["total_count"] == 3


def test_sort_params_build_repository_kwargs_for_allowed_fields() -> None:
    sort = SortParams(sort_by="created_at", sort_order="desc")

    assert sort.to_repository_kwargs(allowed_fields={"created_at", "name"}) == {
        "sort_columns": "created_at",
        "sort_orders": "desc",
    }


def test_sort_params_reject_unknown_fields() -> None:
    sort = SortParams(sort_by="secret_field")

    with pytest.raises(BadRequestException, match="Unsupported sort field"):
        sort.to_repository_kwargs(allowed_fields={"created_at", "name"})


def test_user_list_filters_build_searchable_repository_filters() -> None:
    filters = UserListFilters(name="Ada", username="ada", email="ada@example.com", is_superuser=True, tier_id=2)

    assert filters.to_repository_filters() == {
        "name__icontains": "Ada",
        "username__icontains": "ada",
        "email__icontains": "ada@example.com",
        "is_superuser": True,
        "tier_id": 2,
    }


def test_rate_limit_filters_build_searchable_repository_filters() -> None:
    filters = RateLimitListFilters(name="burst", path="/api/v1/users")

    assert filters.to_repository_filters() == {
        "name__icontains": "burst",
        "path__icontains": "/api/v1/users",
    }
