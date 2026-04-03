from fastapi import FastAPI

from src.app.api import build_api_router
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
    assert "/api/v1/login" not in paths
    assert "/api/v1/logout" not in paths
    assert "/api/v1/user" not in paths
    assert "/api/v1/users" not in paths
    assert "/api/v1/tiers" not in paths
