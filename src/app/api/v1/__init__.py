from fastapi import APIRouter

from ...platform.config import FeatureFlagsSettings, settings
from .health import router as health_router
from .login import router as login_router
from .logout import router as logout_router
from .posts import router as posts_router
from .rate_limits import router as rate_limits_router
from .tiers import router as tiers_router
from .users import router as users_router


def build_v1_router(feature_settings: FeatureFlagsSettings) -> APIRouter:
    router = APIRouter(prefix="/v1")
    router.include_router(health_router)

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


router = build_v1_router(settings)

__all__ = ["build_v1_router", "router"]
