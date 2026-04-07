"""Tests for webhook retention policy (Wave 5.2)."""

from __future__ import annotations

import pytest

from src.app.webhooks.retention import (
    WebhookRetentionPolicy,
    WebhookRetentionResult,
    WebhookRetentionService,
    webhook_retention_service,
)


class TestWebhookRetentionPolicy:
    def test_valid_policy(self) -> None:
        policy = WebhookRetentionPolicy(retention_days=7, archive_days=90)
        assert policy.retention_days == 7
        assert policy.archive_days == 90
        assert policy.batch_size == 500

    def test_negative_retention_days(self) -> None:
        with pytest.raises(ValueError, match="Retention days cannot be negative"):
            WebhookRetentionPolicy(retention_days=-1)

    def test_archive_before_retention(self) -> None:
        with pytest.raises(ValueError, match="Archive days must be greater"):
            WebhookRetentionPolicy(retention_days=30, archive_days=7)

    def test_invalid_batch_size(self) -> None:
        with pytest.raises(ValueError, match="Batch size must be at least 1"):
            WebhookRetentionPolicy(retention_days=7, batch_size=0)

    def test_zero_retention_valid(self) -> None:
        policy = WebhookRetentionPolicy(retention_days=0, archive_days=0)
        assert policy.retention_days == 0

    def test_default_scrub_statuses(self) -> None:
        policy = WebhookRetentionPolicy(retention_days=7)
        assert "processed" in policy.scrub_statuses
        assert "failed" in policy.scrub_statuses
        assert "rejected" in policy.scrub_statuses


class TestWebhookRetentionResult:
    def test_as_summary(self) -> None:
        result = WebhookRetentionResult(payloads_scrubbed=10, events_purged=5)
        summary = result.as_summary()
        assert summary["payloads_scrubbed"] == 10
        assert summary["events_purged"] == 5
        assert "started_at" in summary


class TestWebhookRetentionService:
    def test_singleton_service(self) -> None:
        assert webhook_retention_service is not None
        assert isinstance(webhook_retention_service, WebhookRetentionService)


class TestRetentionExports:
    def test_canonical_surface(self) -> None:
        from src.app.webhooks import (
            build_retention_policy,
        )
        assert build_retention_policy is not None

    def test_platform_surface(self) -> None:
        from src.app.platform.webhooks import (
            WebhookRetentionPolicy,
        )
        assert WebhookRetentionPolicy is not None

    def test_legacy_surface(self) -> None:
        from src.app.core.webhooks import (
            build_retention_policy,
        )
        assert build_retention_policy is not None
