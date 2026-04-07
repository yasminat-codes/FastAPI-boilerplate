import importlib
import pkgutil
from pathlib import Path

import src.app.core.utils.cache as legacy_cache_module
import src.app.core.utils.rate_limit as legacy_rate_limit_module
import src.app.integrations as integrations
import src.app.platform.cache as platform_cache_module
import src.app.platform.health as platform_health_module
import src.app.platform.queue as platform_queue_module
import src.app.platform.rate_limit as platform_rate_limit_module
import src.app.platform.webhooks as platform_webhooks_module
import src.app.shared as shared
import src.app.webhooks as webhooks
import src.app.webhooks.providers as webhook_providers
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
from src.app.domain.services import auth_service, post_service, rate_limit_service, tier_service, user_service
from src.app.main import create_app
from src.app.platform import create_application, lifespan_factory, settings
from src.app.platform.database import Base, async_get_db
from src.app.platform.health import ReadinessContract, build_readiness_contract
from src.app.scheduler import SchedulerNotConfiguredError, start_scheduler
from src.app.workers.settings import WorkerSettings, start_arq_service, start_worker

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_canonical_boundaries_expose_template_primitives() -> None:
    assert settings is legacy_settings
    assert User.__name__ == "User"
    assert UserRead.__name__ == "UserRead"
    assert crud_users is not None
    assert user_repository is crud_users
    assert auth_service is not None
    assert user_service is not None
    assert post_service is not None
    assert tier_service is not None
    assert rate_limit_service is not None
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
    assert "inbound webhook ingestion" in (webhooks.__doc__ or "")
    assert "provider-specific webhook verifiers" in (webhook_providers.__doc__ or "")
    assert "workflow orchestration" in (workflows.__doc__ or "")


def test_canonical_repository_aliases_preserve_legacy_instances() -> None:
    assert post_repository is crud_posts
    assert rate_limit_repository is crud_rate_limits
    assert tier_repository is crud_tiers
    assert user_repository is crud_users


def test_canonical_service_aliases_are_available() -> None:
    assert auth_service.__class__.__name__ == "AuthService"
    assert post_service.__class__.__name__ == "PostService"
    assert rate_limit_service.__class__.__name__ == "RateLimitService"
    assert tier_service.__class__.__name__ == "TierService"
    assert user_service.__class__.__name__ == "UserService"


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


def test_platform_webhook_surface_preserves_canonical_boundary_imports() -> None:
    assert platform_webhooks_module.WebhookEventEnqueueRequest is webhooks.WebhookEventEnqueueRequest
    assert platform_webhooks_module.WebhookEventEnqueueResult is webhooks.WebhookEventEnqueueResult
    assert platform_webhooks_module.WebhookEventEnqueuer is webhooks.WebhookEventEnqueuer
    assert platform_webhooks_module.WebhookIngestionRequest is webhooks.WebhookIngestionRequest
    assert platform_webhooks_module.WebhookIngestionResult is webhooks.WebhookIngestionResult
    assert (
        platform_webhooks_module.WebhookSignatureVerificationContext
        is webhooks.WebhookSignatureVerificationContext
    )
    assert platform_webhooks_module.WebhookSignatureVerificationResult is webhooks.WebhookSignatureVerificationResult
    assert platform_webhooks_module.WebhookSignatureVerifier is webhooks.WebhookSignatureVerifier
    assert platform_webhooks_module.WebhookValidatedEvent is webhooks.WebhookValidatedEvent
    assert platform_webhooks_module.build_webhook_ingestion_request is webhooks.build_webhook_ingestion_request
    assert platform_webhooks_module.ingest_webhook_event is webhooks.ingest_webhook_event
    assert platform_webhooks_module.verify_webhook_signature is webhooks.verify_webhook_signature
    assert platform_webhooks_module.read_raw_request_body is webhooks.read_raw_request_body
    assert platform_webhooks_module.parse_raw_json_body is webhooks.parse_raw_json_body
    assert platform_webhooks_module.validate_json_webhook_event is webhooks.validate_json_webhook_event
    assert platform_webhooks_module.RAW_REQUEST_BODY_STATE_KEY == webhooks.RAW_REQUEST_BODY_STATE_KEY
    assert platform_webhooks_module.WebhookIdempotencyProtector is webhooks.WebhookIdempotencyProtector
    assert platform_webhooks_module.WebhookIdempotencyRequest is webhooks.WebhookIdempotencyRequest
    assert platform_webhooks_module.WebhookIdempotencyResult is webhooks.WebhookIdempotencyResult
    assert platform_webhooks_module.WebhookIdempotencyViolationError is webhooks.WebhookIdempotencyViolationError
    assert (
        platform_webhooks_module.WebhookIdempotencyFingerprintMismatchError
        is webhooks.WebhookIdempotencyFingerprintMismatchError
    )
    assert platform_webhooks_module.record_idempotency_key is webhooks.record_idempotency_key
    assert platform_webhooks_module.webhook_idempotency_protector is webhooks.webhook_idempotency_protector
    assert platform_webhooks_module.MalformedPayloadError is webhooks.MalformedPayloadError
    assert platform_webhooks_module.UnknownEventTypeError is webhooks.UnknownEventTypeError
    assert platform_webhooks_module.PoisonPayloadError is webhooks.PoisonPayloadError
    assert platform_webhooks_module.WebhookDuplicateEventError is webhooks.WebhookDuplicateEventError
    assert platform_webhooks_module.WebhookEventTypeRegistry is webhooks.WebhookEventTypeRegistry
    assert platform_webhooks_module.WebhookValidationErrorKind is webhooks.WebhookValidationErrorKind
    assert platform_webhooks_module.validate_webhook_content_type is webhooks.validate_webhook_content_type
    assert platform_webhooks_module.validate_webhook_event_type is webhooks.validate_webhook_event_type
    assert platform_webhooks_module.validate_webhook_payload_json is webhooks.validate_webhook_payload_json


def test_scheduler_runtime_placeholder_is_explicit() -> None:
    try:
        start_scheduler()
    except SchedulerNotConfiguredError as exc:
        assert "not implemented yet" in str(exc)
    else:
        raise AssertionError("scheduler placeholder should raise a clear configuration error")


def test_dependency_vulnerability_workflow_audits_locked_dependencies() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "dependency-vulnerability-scan.yml"

    assert workflow_path.exists()

    workflow_text = workflow_path.read_text(encoding="utf-8")

    assert "uv export --frozen --all-groups" in workflow_text
    assert "--no-emit-project" in workflow_text
    assert "python -m pip install pip-audit" in workflow_text
    assert "python -m pip_audit -r requirements-audit.txt" in workflow_text


def test_secret_scan_workflow_uses_template_gitleaks_config() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "secret-scan.yml"

    assert workflow_path.exists()

    workflow_text = workflow_path.read_text(encoding="utf-8")

    assert "docker://ghcr.io/gitleaks/gitleaks:v8.24.2" in workflow_text
    assert ".gitleaks.toml" in workflow_text
    assert "dir --config" in workflow_text


def test_pre_commit_config_registers_gitleaks_hook() -> None:
    pre_commit_path = REPO_ROOT / ".pre-commit-config.yaml"

    pre_commit_text = pre_commit_path.read_text(encoding="utf-8")

    assert "https://github.com/gitleaks/gitleaks" in pre_commit_text
    assert "- id: gitleaks" in pre_commit_text
    assert "--config=.gitleaks.toml" in pre_commit_text


def test_gitleaks_config_documents_template_safe_exclusions() -> None:
    config_path = REPO_ROOT / ".gitleaks.toml"

    assert config_path.exists()

    config_text = config_path.read_text(encoding="utf-8")

    assert "useDefault = true" in config_text
    assert "^docs/" in config_text
    assert "^tests/" in config_text
    assert "test-secret-key-for-testing-only" in config_text
