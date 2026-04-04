from fastapi import FastAPI

from src.app.api import SUPPORTED_API_VERSIONS, ApiVersion, build_api_router, build_version_router
from src.app.api.routing import ApiRouteGroup, build_route_group_router
from src.app.main import app, create_app
from src.app.platform.config import load_settings


def test_default_template_api_does_not_mount_demo_task_routes() -> None:
    paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert "/api/v1/tasks/task" not in paths
    assert "/api/v1/tasks/task/{task_id}" not in paths


def test_create_app_returns_configured_fastapi_application() -> None:
    application = create_app()
    paths = {route.path for route in application.routes if hasattr(route, "path")}

    assert isinstance(application, FastAPI)
    assert "/api/v1/health" in paths
    assert "/api/v1/internal/health" in paths


def test_build_api_router_can_disable_optional_route_groups() -> None:
    custom_settings = load_settings(
        _env_file=None,
        FEATURE_API_AUTH_ROUTES_ENABLED=False,
        FEATURE_API_USERS_ENABLED=False,
        FEATURE_API_POSTS_ENABLED=False,
        FEATURE_API_TIERS_ENABLED=False,
        FEATURE_API_RATE_LIMITS_ENABLED=False,
    )

    router = build_api_router(custom_settings)
    paths = {route.path for route in router.routes if hasattr(route, "path")}

    assert "/api/v1/health" in paths
    assert "/api/v1/internal/health" in paths
    assert "/api/v1/login" not in paths
    assert "/api/v1/logout" not in paths
    assert "/api/v1/user" not in paths
    assert "/api/v1/users" not in paths
    assert "/api/v1/tiers" not in paths


def test_supported_api_versions_default_to_v1() -> None:
    assert SUPPORTED_API_VERSIONS == (ApiVersion.V1,)


def test_build_version_router_uses_the_expected_prefix() -> None:
    custom_settings = load_settings(_env_file=None)

    router = build_version_router(version=ApiVersion.V1, feature_settings=custom_settings)

    assert router.prefix == "/v1"


def test_route_group_builders_use_expected_prefixes() -> None:
    assert build_route_group_router(ApiRouteGroup.PUBLIC).prefix == ""
    assert build_route_group_router(ApiRouteGroup.OPS).prefix == ""
    assert build_route_group_router(ApiRouteGroup.ADMIN).prefix == "/admin"
    assert build_route_group_router(ApiRouteGroup.INTERNAL).prefix == "/internal"
    assert build_route_group_router(ApiRouteGroup.WEBHOOKS).prefix == "/webhooks"
