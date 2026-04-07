"""Tests for the queue naming conventions module."""

from __future__ import annotations

import pytest

from src.app.core.worker.queue_naming import (
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


class TestValidateQueueName:
    """Tests for validate_queue_name()."""

    def test_valid_two_segment_name(self) -> None:
        assert validate_queue_name("arq:default") == "arq:default"

    def test_valid_three_segment_name(self) -> None:
        assert validate_queue_name("arq:platform:default") == "arq:platform:default"

    def test_valid_name_with_hyphens(self) -> None:
        assert validate_queue_name("arq:my-scope:my-purpose") == "arq:my-scope:my-purpose"

    def test_valid_name_with_digits(self) -> None:
        assert validate_queue_name("arq2:queue1:test3") == "arq2:queue1:test3"

    def test_empty_name_raises(self) -> None:
        with pytest.raises(QueueNameError, match="must not be empty"):
            validate_queue_name("")

    def test_whitespace_name_raises(self) -> None:
        with pytest.raises(QueueNameError, match="must not be empty"):
            validate_queue_name("   ")

    def test_too_long_name_raises(self) -> None:
        long_name = "arq:" + "a" * 200
        with pytest.raises(QueueNameError, match="exceeds"):
            validate_queue_name(long_name)

    def test_uppercase_raises(self) -> None:
        with pytest.raises(QueueNameError, match="invalid characters"):
            validate_queue_name("ARQ:default")

    def test_spaces_raise(self) -> None:
        with pytest.raises(QueueNameError, match="invalid characters"):
            validate_queue_name("arq:my queue")

    def test_underscores_raise(self) -> None:
        with pytest.raises(QueueNameError, match="invalid characters"):
            validate_queue_name("arq:my_queue")

    def test_single_segment_raises(self) -> None:
        with pytest.raises(QueueNameError, match="at least 2"):
            validate_queue_name("singleword")


class TestQueueNamespace:
    """Tests for QueueNamespace."""

    def test_builds_valid_queue_name(self) -> None:
        ns = QueueNamespace(prefix="arq", scope="client")
        assert ns.queue("email") == "arq:client:email"

    def test_default_values(self) -> None:
        ns = QueueNamespace()
        assert ns.prefix == "arq"
        assert ns.scope == "client"

    def test_queue_validates(self) -> None:
        ns = QueueNamespace(prefix="arq", scope="client")
        with pytest.raises(QueueNameError, match="invalid characters"):
            ns.queue("BAD NAME")

    def test_empty_prefix_raises(self) -> None:
        with pytest.raises(QueueNameError, match="prefix must not be empty"):
            QueueNamespace(prefix="", scope="client")

    def test_empty_scope_raises(self) -> None:
        with pytest.raises(QueueNameError, match="scope must not be empty"):
            QueueNamespace(prefix="arq", scope="")

    def test_scope_constants(self) -> None:
        assert QueueNamespace.SCOPE_PLATFORM == "platform"
        assert QueueNamespace.SCOPE_WEBHOOKS == "webhooks"
        assert QueueNamespace.SCOPE_CLIENT == "client"
        assert QueueNamespace.SCOPE_INTEGRATIONS == "integrations"


class TestPrebuiltNamespaces:
    """Tests for the pre-built namespace instances."""

    def test_platform_queues(self) -> None:
        assert platform_queues.scope == "platform"
        assert platform_queues.queue("default") == "arq:platform:default"

    def test_webhook_queues(self) -> None:
        assert webhook_queues.scope == "webhooks"
        assert webhook_queues.queue("ingest") == "arq:webhooks:ingest"

    def test_client_queues(self) -> None:
        assert client_queues.scope == "client"
        assert client_queues.queue("email") == "arq:client:email"

    def test_integration_queues(self) -> None:
        assert integration_queues.scope == "integrations"
        assert integration_queues.queue("sync") == "arq:integrations:sync"


class TestReservedScopes:
    """Tests for reserved scope detection."""

    def test_platform_is_reserved(self) -> None:
        assert is_reserved_scope("platform") is True

    def test_platform_case_insensitive(self) -> None:
        assert is_reserved_scope("PLATFORM") is True

    def test_client_is_not_reserved(self) -> None:
        assert is_reserved_scope("client") is False

    def test_reserved_scopes_frozenset(self) -> None:
        assert "platform" in RESERVED_SCOPES


class TestDefaultQueueName:
    """Tests for the DEFAULT_QUEUE_NAME constant."""

    def test_follows_naming_convention(self) -> None:
        assert DEFAULT_QUEUE_NAME == "arq:platform:default"

    def test_is_valid(self) -> None:
        assert validate_queue_name(DEFAULT_QUEUE_NAME) == DEFAULT_QUEUE_NAME
