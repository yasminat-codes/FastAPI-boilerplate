from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.api import SUPPORTED_API_VERSIONS, ApiVersion, build_api_router, build_version_router
from src.app.api.dependencies import get_current_principal
from src.app.api.routing import ApiRouteGroup, build_route_group_router
from src.app.api.v1 import build_v1_internal_router, build_v1_public_router, build_v1_webhooks_router
from src.app.core.schemas import DependencyHealthDetail, InternalHealthCheck, WorkerHealthCheck
from src.app.main import app, create_app
from src.app.platform.authorization import TemplatePermission
from src.app.platform.cache import async_get_redis
from src.app.platform.config import load_settings
from src.app.platform.database import async_get_db


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


def test_public_router_applies_rate_limit_strategy_to_auth_and_public_api_routes() -> None:
    router = build_v1_public_router(load_settings(_env_file=None))
    route_dependencies = {
        route.path: {
            getattr(dependency.call, "__name__", dependency.call.__class__.__name__)
            for dependency in route.dependant.dependencies
        }
        for route in router.routes
        if hasattr(route, "dependant")
    }

    assert "auth_login_rate_limiter_dependency" in route_dependencies["/login"]
    assert "auth_refresh_rate_limiter_dependency" in route_dependencies["/refresh"]
    assert "auth_logout_rate_limiter_dependency" in route_dependencies["/logout"]
    assert "rate_limiter_dependency" in route_dependencies["/user"]
    assert "rate_limiter_dependency" in route_dependencies["/users"]
    assert "rate_limiter_dependency" in route_dependencies["/{username}/posts"]


def test_webhook_router_reserves_a_dedicated_rate_limit_dependency() -> None:
    router = build_v1_webhooks_router()

    assert len(router.dependencies) == 1
    assert router.dependencies[0].dependency is not None
    assert router.dependencies[0].dependency.__name__ == "webhook_rate_limiter_dependency"


def test_internal_health_route_rejects_requests_without_internal_access() -> None:
    application = FastAPI()
    application.include_router(build_v1_internal_router())

    async def override_db() -> object:
        return object()

    async def override_redis() -> object:
        return object()

    application.dependency_overrides[async_get_db] = override_db
    application.dependency_overrides[async_get_redis] = override_redis

    with TestClient(application) as client:
        response = client.get("/internal/health")

    assert response.status_code == 401


def test_internal_health_route_allows_authenticated_internal_access() -> None:
    application = FastAPI()
    application.include_router(build_v1_internal_router())

    async def override_db() -> object:
        return object()

    async def override_redis() -> object:
        return object()

    async def override_current_principal() -> dict[str, object]:
        return {
            "id": 1,
            "permissions": [TemplatePermission.INTERNAL_ACCESS.value],
        }

    application.dependency_overrides[async_get_db] = override_db
    application.dependency_overrides[async_get_redis] = override_redis
    application.dependency_overrides[get_current_principal] = override_current_principal

    diagnostics = InternalHealthCheck(
        status="healthy",
        environment="local",
        version="0.1.0",
        app="healthy",
        dependencies={"database": "healthy"},
        dependency_details={
            "database": DependencyHealthDetail(status="healthy", summary="Database probe succeeded."),
        },
        worker=WorkerHealthCheck(
            status="healthy",
            summary="Recent worker heartbeat observed on the configured queue.",
            queue_name="arq:queue",
        ),
        timestamp="2026-04-06T12:00:00+00:00",
    )
    contract = Mock()
    contract.evaluate_internal = AsyncMock(return_value=diagnostics)

    with (
        patch("src.app.api.v1.internal_health.build_runtime_readiness_contract", return_value=contract),
        patch("src.app.api.v1.internal_health.check_worker_health", new=AsyncMock(return_value=diagnostics.worker)),
        TestClient(application) as client,
    ):
        response = client.get("/internal/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_internal_health_route_allows_machine_api_key_access() -> None:
    application = FastAPI()
    application.include_router(build_v1_internal_router())

    async def override_db() -> object:
        return object()

    async def override_redis() -> object:
        return object()

    application.dependency_overrides[async_get_db] = override_db
    application.dependency_overrides[async_get_redis] = override_redis

    custom_settings = load_settings(
        _env_file=None,
        API_KEY_ENABLED=True,
        API_KEY_PRINCIPALS={
            "internal-worker": {
                "key": "machine-secret-value",
                "permissions": [TemplatePermission.INTERNAL_ACCESS.value],
            }
        },
    )
    diagnostics = InternalHealthCheck(
        status="healthy",
        environment="local",
        version="0.1.0",
        app="healthy",
        dependencies={"database": "healthy"},
        dependency_details={
            "database": DependencyHealthDetail(status="healthy", summary="Database probe succeeded."),
        },
        worker=WorkerHealthCheck(
            status="healthy",
            summary="Recent worker heartbeat observed on the configured queue.",
            queue_name="arq:queue",
        ),
        timestamp="2026-04-06T12:00:00+00:00",
    )
    contract = Mock()
    contract.evaluate_internal = AsyncMock(return_value=diagnostics)

    with (
        patch("src.app.api.dependencies.settings", custom_settings),
        patch("src.app.core.security.settings", custom_settings),
        patch("src.app.api.v1.internal_health.build_runtime_readiness_contract", return_value=contract),
        patch("src.app.api.v1.internal_health.check_worker_health", new=AsyncMock(return_value=diagnostics.worker)),
        TestClient(application) as client,
    ):
        response = client.get(
            "/internal/health",
            headers={custom_settings.API_KEY_HEADER_NAME: "machine-secret-value"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
