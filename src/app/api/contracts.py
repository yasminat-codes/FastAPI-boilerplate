"""Reusable API response contracts."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

PayloadT = TypeVar("PayloadT")


class ApiDataResponse(BaseModel, Generic[PayloadT]):
    """Canonical success envelope for responses that need data plus metadata."""

    data: PayloadT
    meta: dict[str, Any] | None = None


class ApiMessageResponse(BaseModel):
    """Canonical success envelope for command-style responses."""

    message: str
    meta: dict[str, Any] | None = None


class ApiErrorDetail(BaseModel):
    """Machine-readable API error details."""

    code: str
    message: str
    details: list[dict[str, Any]] | None = None


class ApiErrorResponse(BaseModel):
    """Canonical error response envelope."""

    error: ApiErrorDetail


__all__ = [
    "ApiDataResponse",
    "ApiErrorDetail",
    "ApiErrorResponse",
    "ApiMessageResponse",
]
