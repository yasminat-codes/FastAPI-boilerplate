"""Reusable API query-parameter models and list helpers."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from fastcrud import compute_offset, paginated_response
from pydantic import BaseModel, ConfigDict, Field

from ..platform.exceptions import BadRequestException

MAX_ITEMS_PER_PAGE = 100


class PaginationParams(BaseModel):
    """Canonical page-based pagination contract."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    items_per_page: int = Field(default=10, ge=1, le=MAX_ITEMS_PER_PAGE)

    @property
    def offset(self) -> int:
        return compute_offset(self.page, self.items_per_page)

    @property
    def limit(self) -> int:
        return self.items_per_page


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class SortParams(BaseModel):
    """Canonical sorting contract for list endpoints."""

    model_config = ConfigDict(extra="forbid")

    sort_by: str | None = Field(default=None, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    sort_order: SortDirection = SortDirection.DESC

    def to_repository_kwargs(self, *, allowed_fields: set[str] | frozenset[str]) -> dict[str, str]:
        if self.sort_by is None:
            return {}

        if self.sort_by not in allowed_fields:
            allowed = ", ".join(sorted(allowed_fields))
            raise BadRequestException(
                f"Unsupported sort field '{self.sort_by}'. Allowed values: {allowed}."
            )

        return {
            "sort_columns": self.sort_by,
            "sort_orders": self.sort_order.value,
        }


class FilterParams(BaseModel):
    """Base class for typed resource filters."""

    model_config = ConfigDict(extra="forbid")

    def to_repository_filters(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class UserListFilters(FilterParams):
    name: str | None = Field(default=None, max_length=30)
    username: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=50)
    is_superuser: bool | None = None
    tier_id: int | None = Field(default=None, ge=1)

    def to_repository_filters(self) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if self.name is not None:
            filters["name__icontains"] = self.name
        if self.username is not None:
            filters["username__icontains"] = self.username
        if self.email is not None:
            filters["email__icontains"] = self.email
        if self.is_superuser is not None:
            filters["is_superuser"] = self.is_superuser
        if self.tier_id is not None:
            filters["tier_id"] = self.tier_id
        return filters


class PostListFilters(FilterParams):
    title: str | None = Field(default=None, max_length=30)

    def to_repository_filters(self) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if self.title is not None:
            filters["title__icontains"] = self.title
        return filters


class TierListFilters(FilterParams):
    name: str | None = None

    def to_repository_filters(self) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if self.name is not None:
            filters["name__icontains"] = self.name
        return filters


class RateLimitListFilters(FilterParams):
    name: str | None = None
    path: str | None = None

    def to_repository_filters(self) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if self.name is not None:
            filters["name__icontains"] = self.name
        if self.path is not None:
            filters["path__icontains"] = self.path
        return filters


def build_paginated_api_response(*, crud_data: Mapping[str, Any], pagination: PaginationParams) -> dict[str, Any]:
    """Build the canonical paginated response shape from FastCRUD data."""

    normalized_crud_data = dict(crud_data)
    if "total_count" not in normalized_crud_data and "count" in normalized_crud_data:
        normalized_crud_data["total_count"] = normalized_crud_data["count"]

    return paginated_response(
        crud_data=normalized_crud_data,
        page=pagination.page,
        items_per_page=pagination.items_per_page,
    )


__all__ = [
    "MAX_ITEMS_PER_PAGE",
    "PaginationParams",
    "PostListFilters",
    "RateLimitListFilters",
    "SortDirection",
    "SortParams",
    "TierListFilters",
    "UserListFilters",
    "build_paginated_api_response",
]
