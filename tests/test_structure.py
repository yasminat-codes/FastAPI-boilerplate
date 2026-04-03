import importlib
import pkgutil

import src.app.core.utils.cache as legacy_cache_module
import src.app.core.utils.rate_limit as legacy_rate_limit_module
import src.app.integrations as integrations
import src.app.platform.cache as platform_cache_module
import src.app.platform.health as platform_health_module
import src.app.platform.queue as platform_queue_module
import src.app.platform.rate_limit as platform_rate_limit_module
import src.app.shared as shared
import src.app.workflows as workflows
from src.app.api import v1 as api_v1
from src.app.core.config import settings as legacy_settings
from src.app.domain.models import User
from src.app.domain.repositories import (
    crud_posts,
    crud_rate_limits,
    crud_tiers,
    crud_users,
    post_repository,
    rate_limit_repository,
    tier_repository,
    user_repository,
)
from src.app.domain.schemas import UserRead
from src.app.main import create_app
from src.app.platform import create_application, lifespan_factory, settings
from src.app.platform.database import Base, async_get_db
from src.app.platform.health import ReadinessContract, build_readiness_contract
from src.app.scheduler import SchedulerNotConfiguredError, start_scheduler
from src.app.workers.settings import WorkerSettings, start_arq_service, start_worker


def test_canonical_boundaries_expose_template_primitives() -> None:
    assert settings is legacy_settings
    assert User.__name__ == "User"
    assert UserRead.__name__ == "UserRead"
    assert crud_users is not None
    assert user_repository is crud_users
    assert callable(create_app)
    assert callable(create_application)
    assert callable(lifespan_factory)
    assert callable(build_readiness_contract)
    assert callable(async_get_db)
    assert Base.metadata is not None
    assert ReadinessContract.__name__ == "ReadinessContract"
    assert WorkerSettings.functions
    assert WorkerSettings.queue_name == settings.WORKER_QUEUE_NAME
    assert WorkerSettings.max_jobs == settings.WORKER_MAX_JOBS
    assert start_worker is start_arq_service


def test_extension_point_packages_exist() -> None:
    assert "provider adapters" in (integrations.__doc__ or "")
    assert "framework-agnostic helper code" in (shared.__doc__ or "")
    assert "workflow orchestration" in (workflows.__doc__ or "")


def test_canonical_repository_aliases_preserve_legacy_instances() -> None:
    assert post_repository is crud_posts
    assert rate_limit_repository is crud_rate_limits
    assert tier_repository is crud_tiers
    assert user_repository is crud_users


def test_api_route_modules_export_router_by_convention() -> None:
    package_paths = list(getattr(api_v1, "__path__", []))

    assert package_paths

    module_names = sorted(
        module_info.name
        for module_info in pkgutil.iter_modules(package_paths)
        if not module_info.name.startswith("_")
    )

    for module_name in module_names:
        module = importlib.import_module(f"{api_v1.__name__}.{module_name}")
        assert hasattr(module, "router"), f"{module_name} should export `router`"


def test_shared_utilities_are_separate_from_platform_runtime_primitives() -> None:
    assert platform_cache_module.cache is legacy_cache_module.cache
    assert platform_cache_module.async_get_redis is legacy_cache_module.async_get_redis
    assert platform_health_module.build_readiness_contract is build_readiness_contract
    assert platform_rate_limit_module.rate_limiter is legacy_rate_limit_module.rate_limiter
    assert hasattr(platform_queue_module, "__getattr__")


def test_scheduler_runtime_placeholder_is_explicit() -> None:
    try:
        start_scheduler()
    except SchedulerNotConfiguredError as exc:
        assert "not implemented yet" in str(exc)
    else:
        raise AssertionError("scheduler placeholder should raise a clear configuration error")
