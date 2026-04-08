"""
Test factories for generating domain and platform model instances.

Provides factory functions for creating both dict representations (_data versions)
and ORM instances for all domain and platform models. Useful for tests that need
realistic test data without hitting the database, or for building fixtures.

Each factory has two forms:
- build_<model>_data(**overrides): Returns a dict of valid field values
- build_<model>(**overrides): Returns an ORM instance
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from faker import Faker
from uuid6 import uuid7

from src.app.core.db.audit_log_event import AuditLogEvent, AuditLogEventSeverity, AuditLogEventStatus
from src.app.core.db.dead_letter_record import DeadLetterRecord, DeadLetterRecordStatus
from src.app.core.db.idempotency_key import IdempotencyKey, IdempotencyKeyStatus
from src.app.core.db.integration_sync_checkpoint import IntegrationSyncCheckpoint, IntegrationSyncCheckpointStatus
from src.app.core.db.job_state_history import JobStateHistory, JobStateHistoryStatus
from src.app.core.db.token_blacklist import TokenBlacklist
from src.app.core.db.webhook_event import WebhookEvent, WebhookEventStatus
from src.app.core.db.workflow_execution import WorkflowExecution, WorkflowExecutionStatus
from src.app.models.post import Post
from src.app.models.rate_limit import RateLimit
from src.app.models.tier import Tier
from src.app.models.user import User

# Module-level Faker instance (isolated from conftest to avoid circular imports)
fake = Faker()


# ============================================================================
# DOMAIN MODELS
# ============================================================================


def build_user_data(**overrides: Any) -> dict[str, Any]:
    """
    Build valid User field data as a dict.

    Provides sensible defaults for all User fields. Override any field via kwargs.
    Note: Does not set auto-increment id or default created_at (let DB/model handle it).
    """
    defaults = {
        "name": fake.name()[:30],
        "username": fake.user_name()[:20],
        "email": fake.email()[:50],
        "hashed_password": "$2b$12$abcdefghijklmnopqrstuvwxyz1234567890abcdefghij",  # placeholder hash
        "profile_image_url": "https://example.com/avatars/default.jpg",
        "uuid": uuid7(),
        "is_superuser": False,
        "tier_id": None,
    }
    defaults.update(overrides)
    return defaults


def build_user(**overrides: Any) -> User:
    """
    Build a User ORM instance.

    Creates an in-memory User instance with valid defaults. Override any field via kwargs.
    This instance is not persisted to the database.
    """
    data = build_user_data(**overrides)
    return User(**data)


def build_post_data(created_by_user_id: int | None = None, **overrides: Any) -> dict[str, Any]:
    """
    Build valid Post field data as a dict.

    Requires created_by_user_id (or provide via overrides). Returns all other fields
    with sensible defaults.
    """
    defaults = {
        "created_by_user_id": created_by_user_id or 1,
        "title": fake.sentence(nb_words=5)[:30],
        "text": fake.paragraph(nb_sentences=10)[:63206],
        "uuid": uuid7(),
        "media_url": None,
    }
    defaults.update(overrides)
    return defaults


def build_post(created_by_user_id: int | None = None, **overrides: Any) -> Post:
    """
    Build a Post ORM instance.

    Requires created_by_user_id (or provide via overrides).
    This instance is not persisted to the database.
    """
    data = build_post_data(created_by_user_id, **overrides)
    return Post(**data)


def build_tier_data(**overrides: Any) -> dict[str, Any]:
    """
    Build valid Tier field data as a dict.

    Provides sensible tier names (free, pro, enterprise, etc.).
    """
    tier_names = ["free", "pro", "enterprise", "business", "starter"]
    defaults = {
        "name": fake.random_element(tier_names) + "_" + fake.word(),
    }
    defaults.update(overrides)
    return defaults


def build_tier(**overrides: Any) -> Tier:
    """
    Build a Tier ORM instance.

    This instance is not persisted to the database.
    """
    data = build_tier_data(**overrides)
    return Tier(**data)


def build_rate_limit_data(tier_id: int | None = None, **overrides: Any) -> dict[str, Any]:
    """
    Build valid RateLimit field data as a dict.

    Requires tier_id (or provide via overrides).
    """
    defaults = {
        "tier_id": tier_id or 1,
        "name": f"rate_limit_{fake.word()}",
        "path": f"/api/v1/{fake.word()}/{fake.word()}",
        "limit": fake.random_int(min=10, max=1000),
        "period": fake.random_int(min=60, max=3600),
    }
    defaults.update(overrides)
    return defaults


def build_rate_limit(tier_id: int | None = None, **overrides: Any) -> RateLimit:
    """
    Build a RateLimit ORM instance.

    Requires tier_id (or provide via overrides).
    This instance is not persisted to the database.
    """
    data = build_rate_limit_data(tier_id, **overrides)
    return RateLimit(**data)


# ============================================================================
# PLATFORM MODELS
# ============================================================================


def build_webhook_event_data(**overrides: Any) -> dict[str, Any]:
    """
    Build valid WebhookEvent field data as a dict.

    Covers webhook reception, validation, and processing fields.
    """
    defaults = {
        "source": fake.word(),
        "endpoint_key": fake.sha256()[:100],
        "event_type": f"{fake.word()}.{fake.word()}",
        "status": WebhookEventStatus.RECEIVED.value,
        "delivery_id": fake.sha256()[:255],
        "event_id": fake.sha256()[:255],
        "signature_verified": fake.boolean(),
        "payload_content_type": fake.random_element(["application/json", "application/xml"]),
        "payload_sha256": fake.sha256(),
        "payload_size_bytes": fake.random_int(min=100, max=1000000),
        "raw_payload": fake.json(),
        "normalized_payload": {"event": "test", "timestamp": datetime.now(UTC).isoformat()},
        "processing_metadata": {"retries": 0},
    }
    defaults.update(overrides)
    return defaults


def build_webhook_event(**overrides: Any) -> WebhookEvent:
    """
    Build a WebhookEvent ORM instance.

    This instance is not persisted to the database.
    """
    data = build_webhook_event_data(**overrides)
    return WebhookEvent(**data)


def build_idempotency_key_data(**overrides: Any) -> dict[str, Any]:
    """
    Build valid IdempotencyKey field data as a dict.

    For testing idempotent request handling and deduplication.
    """
    defaults = {
        "scope": fake.word(),
        "key": fake.sha256()[:255],
        "status": IdempotencyKeyStatus.RECEIVED.value,
        "request_fingerprint": fake.sha256(),
        "recovery_point": None,
        "hit_count": 1,
        "processing_metadata": {},
    }
    defaults.update(overrides)
    return defaults


def build_idempotency_key(**overrides: Any) -> IdempotencyKey:
    """
    Build an IdempotencyKey ORM instance.

    This instance is not persisted to the database.
    """
    data = build_idempotency_key_data(**overrides)
    return IdempotencyKey(**data)


def build_workflow_execution_data(**overrides: Any) -> dict[str, Any]:
    """
    Build valid WorkflowExecution field data as a dict.

    For testing workflow orchestration and execution tracking.
    """
    defaults = {
        "workflow_name": f"workflow_{fake.word()}",
        "trigger_source": fake.random_element(["api", "webhook", "scheduled", "manual"]),
        "workflow_version": f"v{fake.random_int(min=1, max=10)}",
        "status": WorkflowExecutionStatus.PENDING.value,
        "trigger_reference": fake.uuid4(),
        "run_key": fake.uuid4(),
        "correlation_id": fake.uuid4(),
        "current_step": None,
        "attempt_count": 0,
        "max_attempts": 3,
        "input_payload": {"input": "test"},
        "execution_context": {},
        "output_payload": None,
        "status_metadata": {},
    }
    defaults.update(overrides)
    return defaults


def build_workflow_execution(**overrides: Any) -> WorkflowExecution:
    """
    Build a WorkflowExecution ORM instance.

    This instance is not persisted to the database.
    """
    data = build_workflow_execution_data(**overrides)
    return WorkflowExecution(**data)


def build_job_state_history_data(**overrides: Any) -> dict[str, Any]:
    """
    Build valid JobStateHistory field data as a dict.

    For testing job queue state transitions and execution history.
    """
    defaults = {
        "job_name": f"job_{fake.word()}",
        "queue_name": fake.word(),
        "job_version": f"v{fake.random_int(min=1, max=10)}",
        "queue_backend": fake.random_element(["celery", "rq", "asyncio", "custom"]),
        "queue_job_id": fake.sha256()[:255],
        "worker_name": f"worker_{fake.word()}",
        "worker_version": f"v{fake.random_int(min=1, max=10)}",
        "trigger_source": fake.random_element(["api", "webhook", "scheduled"]),
        "trigger_reference": fake.uuid4(),
        "run_key": fake.uuid4(),
        "correlation_id": fake.uuid4(),
        "status": JobStateHistoryStatus.PENDING.value,
        "current_step": None,
        "attempt_count": 0,
        "max_attempts": 3,
        "input_payload": {"input": "test"},
        "execution_context": {},
        "output_payload": None,
        "status_metadata": {},
    }
    defaults.update(overrides)
    return defaults


def build_job_state_history(**overrides: Any) -> JobStateHistory:
    """
    Build a JobStateHistory ORM instance.

    This instance is not persisted to the database.
    """
    data = build_job_state_history_data(**overrides)
    return JobStateHistory(**data)


def build_integration_sync_checkpoint_data(**overrides: Any) -> dict[str, Any]:
    """
    Build valid IntegrationSyncCheckpoint field data as a dict.

    For testing third-party integration sync tracking and resumption.
    """
    defaults = {
        "integration_name": f"integration_{fake.word()}",
        "sync_scope": fake.word(),
        "checkpoint_key": "default",
        "status": IntegrationSyncCheckpointStatus.PENDING.value,
        "cursor_state": {"cursor": fake.sha256()[:255]},
        "checkpoint_metadata": {"last_page": 1},
        "lease_owner": None,
        "lease_expires_at": None,
        "next_sync_after": None,
        "last_synced_at": None,
        "cursor_updated_at": None,
        "failure_count": 0,
    }
    defaults.update(overrides)
    return defaults


def build_integration_sync_checkpoint(**overrides: Any) -> IntegrationSyncCheckpoint:
    """
    Build an IntegrationSyncCheckpoint ORM instance.

    This instance is not persisted to the database.
    """
    data = build_integration_sync_checkpoint_data(**overrides)
    return IntegrationSyncCheckpoint(**data)


def build_audit_log_event_data(**overrides: Any) -> dict[str, Any]:
    """
    Build valid AuditLogEvent field data as a dict.

    For testing audit trail recording and compliance event tracking.
    """
    defaults = {
        "event_source": fake.word(),
        "event_type": f"{fake.word()}.{fake.word()}",
        "severity": AuditLogEventSeverity.INFO.value,
        "category": fake.word(),
        "status": AuditLogEventStatus.RECORDED.value,
        "actor_type": fake.random_element(["user", "system", "api", "service"]),
        "actor_reference": fake.uuid4(),
        "subject_type": fake.word(),
        "subject_reference": fake.uuid4(),
        "correlation_id": fake.uuid4(),
        "request_id": fake.uuid4(),
        "event_payload": {"action": "test"},
        "event_context": {"ip": fake.ipv4()},
        "summary": fake.sentence(),
    }
    defaults.update(overrides)
    return defaults


def build_audit_log_event(**overrides: Any) -> AuditLogEvent:
    """
    Build an AuditLogEvent ORM instance.

    This instance is not persisted to the database.
    """
    data = build_audit_log_event_data(**overrides)
    return AuditLogEvent(**data)


def build_dead_letter_record_data(**overrides: Any) -> dict[str, Any]:
    """
    Build valid DeadLetterRecord field data as a dict.

    For testing failed message/job handling and recovery.
    """
    defaults = {
        "dead_letter_namespace": fake.word(),
        "dead_letter_key": fake.sha256()[:255],
        "message_type": f"{fake.word()}.{fake.word()}",
        "status": DeadLetterRecordStatus.PENDING.value,
        "source_system": fake.word(),
        "source_reference": fake.uuid4(),
        "correlation_id": fake.uuid4(),
        "failure_category": fake.random_element(["validation", "timeout", "forbidden", "unknown"]),
        "attempt_count": 1,
        "payload_snapshot": {"message": "test"},
        "failure_context": {"error": "test error"},
    }
    defaults.update(overrides)
    return defaults


def build_dead_letter_record(**overrides: Any) -> DeadLetterRecord:
    """
    Build a DeadLetterRecord ORM instance.

    This instance is not persisted to the database.
    """
    data = build_dead_letter_record_data(**overrides)
    return DeadLetterRecord(**data)


def build_token_blacklist_data(**overrides: Any) -> dict[str, Any]:
    """
    Build valid TokenBlacklist field data as a dict.

    For testing token revocation and JWT blacklisting.
    """
    defaults = {
        "token": fake.sha256(),
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
    }
    defaults.update(overrides)
    return defaults


def build_token_blacklist(**overrides: Any) -> TokenBlacklist:
    """
    Build a TokenBlacklist ORM instance.

    This instance is not persisted to the database.
    """
    data = build_token_blacklist_data(**overrides)
    return TokenBlacklist(**data)


# ============================================================================
# CONVENIENCE HELPERS
# ============================================================================


def build_auth_headers(user_id: int, is_superuser: bool = False) -> dict[str, str]:
    """
    Build Authorization header dict for test requests.

    Returns a dict with an 'Authorization' key containing a Bearer token.
    The token is a test JWT (not cryptographically signed) suitable for mocking.

    Args:
        user_id: The user ID to embed in the token
        is_superuser: Whether the token should have superuser privileges

    Returns:
        Dict with 'Authorization' header for use in test request headers
    """
    # Generate a test JWT-like token string (not cryptographically signed)
    # Format: base64(header).base64(payload).base64(signature)
    # For testing/mocking purposes, we just create a plausible token string
    import base64
    import json

    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).decode().rstrip("=")

    payload = base64.urlsafe_b64encode(
        json.dumps({
            "sub": str(user_id),
            "is_superuser": is_superuser,
            "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
            "iat": datetime.now(UTC).timestamp(),
        }).encode()
    ).decode().rstrip("=")

    signature = fake.sha256()[:43]  # Truncate to valid base64 length

    token = f"{header}.{payload}.{signature}"

    return {"Authorization": f"Bearer {token}"}
