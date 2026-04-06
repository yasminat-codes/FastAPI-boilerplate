"""Canonical API versioning and route-group helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fastapi import APIRouter


class ApiVersion(StrEnum):
    V1 = "v1"


DEFAULT_API_VERSION = ApiVersion.V1
SUPPORTED_API_VERSIONS = (ApiVersion.V1,)


class ApiRouteGroup(StrEnum):
    PUBLIC = "public"
    OPS = "ops"
    ADMIN = "admin"
    INTERNAL = "internal"
    WEBHOOKS = "webhooks"


@dataclass(frozen=True)
class ApiRouteGroupDefinition:
    prefix: str


ROUTE_GROUP_DEFINITIONS = {
    ApiRouteGroup.PUBLIC: ApiRouteGroupDefinition(prefix=""),
    ApiRouteGroup.OPS: ApiRouteGroupDefinition(prefix=""),
    ApiRouteGroup.ADMIN: ApiRouteGroupDefinition(prefix="/admin"),
    ApiRouteGroup.INTERNAL: ApiRouteGroupDefinition(prefix="/internal"),
    ApiRouteGroup.WEBHOOKS: ApiRouteGroupDefinition(prefix="/webhooks"),
}


def build_api_root_router() -> APIRouter:
    return APIRouter(prefix="/api")


def build_version_prefix_router(*, version: ApiVersion) -> APIRouter:
    return APIRouter(prefix=f"/{version.value}")


def build_route_group_router(group: ApiRouteGroup, *, dependencies: list[Any] | None = None) -> APIRouter:
    definition = ROUTE_GROUP_DEFINITIONS[group]
    return APIRouter(prefix=definition.prefix, dependencies=dependencies or [])


__all__ = [
    "ApiRouteGroup",
    "ApiRouteGroupDefinition",
    "ApiVersion",
    "DEFAULT_API_VERSION",
    "ROUTE_GROUP_DEFINITIONS",
    "SUPPORTED_API_VERSIONS",
    "build_api_root_router",
    "build_route_group_router",
    "build_version_prefix_router",
]
