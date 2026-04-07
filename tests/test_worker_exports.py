"""Tests verifying the canonical worker boundary re-exports new primitives."""

from __future__ import annotations


class TestCanonicalWorkerExports:
    """Verify new modules are accessible from src.app.workers."""

    def test_queue_naming_exports(self) -> None:
        from src.app.workers import (  # noqa: F401
            DEFAULT_QUEUE_NAME,
            RESERVED_SCOPES,
            QueueNameError,
            QueueNamespace,
            client_queues,
            integration_queues,
            is_reserved_scope,
            platform_queues,
            validate_queue_name,
            webhook_queues,
        )

    def test_serialization_exports(self) -> None:
        from src.app.workers import (  # noqa: F401
            JobPayloadSerializationError,
            safe_payload,
            serialize_for_envelope,
            validate_json_safe,
        )

    def test_concurrency_exports(self) -> None:
        from src.app.workers import (  # noqa: F401
            ALL_PROFILES,
            PROFILE_DEFAULT,
            PROFILE_EMAIL,
            PROFILE_INTEGRATION_SYNC,
            PROFILE_REPORTS,
            PROFILE_SCHEDULED,
            PROFILE_WEBHOOK_INGEST,
            QueueConcurrencyProfile,
        )

    def test_core_worker_exports(self) -> None:
        from src.app.core.worker import (  # noqa: F401
            DEFAULT_QUEUE_NAME,
            RESERVED_SCOPES,
            JobPayloadSerializationError,
            QueueConcurrencyProfile,
            QueueNameError,
            QueueNamespace,
            safe_payload,
            serialize_for_envelope,
            validate_json_safe,
            validate_queue_name,
        )
