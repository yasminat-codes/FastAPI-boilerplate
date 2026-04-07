"""Tests for webhook replay tooling (Wave 5.2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.core.db.webhook_event import WebhookEventStatus
from src.app.webhooks.replay_tooling import (
    WebhookReplayFilter,
    WebhookReplayRequest,
    WebhookReplayResult,
    WebhookReplayService,
    webhook_replay_service,
)


class TestWebhookReplayFilter:
    def test_valid_filter(self) -> None:
        f = WebhookReplayFilter(source="stripe", max_results=50)
        assert f.source == "stripe"
        assert f.max_results == 50

    def test_invalid_max_results_zero(self) -> None:
        with pytest.raises(ValueError, match="max_results must be at least 1"):
            WebhookReplayFilter(max_results=0)

    def test_invalid_max_results_over_limit(self) -> None:
        with pytest.raises(ValueError, match="max_results must not exceed 1000"):
            WebhookReplayFilter(max_results=1001)

    def test_default_max_results(self) -> None:
        f = WebhookReplayFilter()
        assert f.max_results == 100


class TestWebhookReplayRequest:
    def test_as_processing_metadata(self) -> None:
        request = WebhookReplayRequest(
            webhook_event_id=42,
            reason="operator_test",
            replayed_by="admin@test.com",
        )
        metadata = request.as_processing_metadata()
        assert "replay" in metadata
        assert metadata["replay"]["reason"] == "operator_test"
        assert metadata["replay"]["replayed_by"] == "admin@test.com"

    def test_default_reason(self) -> None:
        request = WebhookReplayRequest(webhook_event_id=1)
        assert request.reason == "manual_replay"


class TestWebhookReplayResult:
    def test_was_replayed(self) -> None:
        result = WebhookReplayResult(
            webhook_event_id=42,
            previous_status="failed",
            new_status=WebhookEventStatus.ENQUEUED.value,
        )
        assert result.was_replayed is True

    def test_not_replayed(self) -> None:
        result = WebhookReplayResult(
            webhook_event_id=42,
            previous_status="failed",
            new_status="failed",
        )
        assert result.was_replayed is False


class TestWebhookReplayService:
    def test_prepare_for_replay(self) -> None:
        service = WebhookReplayService()
        event = MagicMock()
        event.id = 42
        event.status = WebhookEventStatus.FAILED.value
        event.processing_metadata = {"existing": "data"}

        request = WebhookReplayRequest(webhook_event_id=42, reason="test_replay")
        result = service.prepare_for_replay(event, request)

        assert result.previous_status == "failed"
        assert result.new_status == WebhookEventStatus.ENQUEUED.value
        assert event.status == WebhookEventStatus.ENQUEUED.value
        assert event.processed_at is None
        assert event.processing_error is None
        assert "replay" in event.processing_metadata
        assert event.processing_metadata["existing"] == "data"

    @pytest.mark.asyncio
    async def test_find_replayable_events(self) -> None:
        service = WebhookReplayService()
        mock_event = MagicMock()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_event]
        mock_result.scalars.return_value = mock_scalars
        session.execute = AsyncMock(return_value=mock_result)

        events = await service.find_replayable_events(
            session,
            WebhookReplayFilter(source="stripe", status="failed"),
        )
        assert len(events) == 1
        session.execute.assert_awaited_once()

    def test_singleton_service(self) -> None:
        assert webhook_replay_service is not None


class TestReplayToolingExports:
    def test_canonical_surface(self) -> None:
        from src.app.webhooks import (
            WebhookReplayService,
        )
        assert WebhookReplayService is not None

    def test_platform_surface(self) -> None:
        from src.app.platform.webhooks import (
            webhook_replay_service,
        )
        assert webhook_replay_service is not None

    def test_legacy_surface(self) -> None:
        from src.app.core.webhooks import (
            WebhookReplayFilter,
        )
        assert WebhookReplayFilter is not None
