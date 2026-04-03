from fastapi import APIRouter

from ..platform.config import FeatureFlagsSettings, settings
from .v1 import build_v1_router


def build_api_router(feature_settings: FeatureFlagsSettings) -> APIRouter:
    router = APIRouter(prefix="/api")
    router.include_router(build_v1_router(feature_settings))
    return router


router = build_api_router(settings)

__all__ = ["build_api_router", "router"]
