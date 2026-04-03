from fastapi import APIRouter

from ...platform.config import FeatureFlagsSettings, settings
from ..routing import ApiRouteGroup, ApiVersion, build_route_group_router, build_version_prefix_router
from .health import router as health_router
from .login import router as login_router
from .logout import router as logout_router
from .posts import router as posts_router
from .rate_limits import router as rate_limits_router
from .tiers import router as tiers_router
from .users import router as users_router


def build_v1_public_router(feature_settings: FeatureFlagsSettings) -> APIRouter:
    router = build_route_group_router(ApiRouteGroup.PUBLIC)

    if feature_settings.FEATURE_API_AUTH_ROUTES_ENABLED:
        router.include_router(login_router)
        router.include_router(logout_router)

    if feature_settings.FEATURE_API_USERS_ENABLED:
        router.include_router(users_router)

    if feature_settings.FEATURE_API_POSTS_ENABLED:
        router.include_router(posts_router)

    if feature_settings.FEATURE_API_TIERS_ENABLED:
        router.include_router(tiers_router)

    if feature_settings.FEATURE_API_RATE_LIMITS_ENABLED:
        router.include_router(rate_limits_router)

    return router


def build_v1_ops_router() -> APIRouter:
    router = build_route_group_router(ApiRouteGroup.OPS)
    router.include_router(health_router)
    return router


def build_v1_admin_router() -> APIRouter:
    return build_route_group_router(ApiRouteGroup.ADMIN)


def build_v1_internal_router() -> APIRouter:
    return build_route_group_router(ApiRouteGroup.INTERNAL)


def build_v1_webhooks_router() -> APIRouter:
    return build_route_group_router(ApiRouteGroup.WEBHOOKS)


def build_v1_router(feature_settings: FeatureFlagsSettings) -> APIRouter:
    router = build_version_prefix_router(version=ApiVersion.V1)
    router.include_router(build_v1_ops_router())
    router.include_router(build_v1_public_router(feature_settings))
    router.include_router(build_v1_admin_router())
    router.include_router(build_v1_internal_router())
    router.include_router(build_v1_webhooks_router())
    return router


router = build_v1_router(settings)

__all__ = [
    "build_v1_admin_router",
    "build_v1_internal_router",
    "build_v1_ops_router",
    "build_v1_public_router",
    "build_v1_router",
    "build_v1_webhooks_router",
    "router",
]
