from collections.abc import Iterable

from fastapi import APIRouter

from ..platform.config import FeatureFlagsSettings, settings
from .routing import SUPPORTED_API_VERSIONS, ApiVersion, build_api_root_router
from .v1 import build_v1_router

VERSION_BUILDERS = {
    ApiVersion.V1: build_v1_router,
}


def build_version_router(*, version: ApiVersion, feature_settings: FeatureFlagsSettings) -> APIRouter:
    try:
        version_builder = VERSION_BUILDERS[version]
    except KeyError as exc:
        raise ValueError(f"Unsupported API version: {version.value}") from exc

    return version_builder(feature_settings)


def build_api_router(
    feature_settings: FeatureFlagsSettings,
    *,
    versions: Iterable[ApiVersion] | None = None,
) -> APIRouter:
    router = build_api_root_router()
    for version in tuple(versions or SUPPORTED_API_VERSIONS):
        router.include_router(build_version_router(version=version, feature_settings=feature_settings))
    return router


router = build_api_router(settings)

__all__ = [
    "ApiVersion",
    "SUPPORTED_API_VERSIONS",
    "build_api_router",
    "build_version_router",
    "router",
]
