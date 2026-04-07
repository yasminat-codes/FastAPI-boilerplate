"""Tests for webhook-to-workflow event correlation contracts (Wave 5.2)."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.app.webhooks.correlation import (
    WebhookWorkflowCorrelation,
    apply_correlation_to_webhook_event,
    apply_correlation_to_workflow_execution,
    build_webhook_workflow_correlation,
    build_workflow_input_from_webhook,
)


def _mock_event(
    *,
    event_id: int = 1,
    source: str = "stripe",
    endpoint_key: str = "default",
    event_type: str = "invoice.paid",
    delivery_id: str | None = "del-1",
    webhook_event_id: str | None = "evt-1",
    normalized_payload: dict | None = None,
    payload_sha256: str | None = "abc123",
) -> MagicMock:
    event = MagicMock()
    event.id = event_id
    event.source = source
    event.endpoint_key = endpoint_key
    event.event_type = event_type
    event.delivery_id = delivery_id
    event.event_id = webhook_event_id
    event.normalized_payload = normalized_payload
    event.payload_sha256 = payload_sha256
    event.processing_metadata = None
    return event


def _mock_execution(
    *,
    execution_id: int = 100,
    workflow_name: str = "process_invoice",
) -> MagicMock:
    execution = MagicMock()
    execution.id = execution_id
    execution.workflow_name = workflow_name
    execution.execution_context = None
    return execution


class TestWebhookWorkflowCorrelation:
    def test_build_correlation(self) -> None:
        event = _mock_event()
        execution = _mock_execution()
        corr = build_webhook_workflow_correlation(event, execution, correlation_id="c-1")
        assert corr.webhook_event_id == 1
        assert corr.workflow_execution_id == 100
        assert corr.workflow_name == "process_invoice"
        assert corr.correlation_id == "c-1"

    def test_as_webhook_processing_metadata(self) -> None:
        corr = WebhookWorkflowCorrelation(
            webhook_event_id=1,
            workflow_execution_id=100,
            source="stripe",
            event_type="invoice.paid",
            workflow_name="process_invoice",
            correlation_id="c-1",
        )
        metadata = corr.as_webhook_processing_metadata()
        assert "workflow_correlation" in metadata
        assert metadata["workflow_correlation"]["workflow_execution_id"] == 100
        assert metadata["workflow_correlation"]["workflow_name"] == "process_invoice"

    def test_as_workflow_execution_context(self) -> None:
        corr = WebhookWorkflowCorrelation(
            webhook_event_id=1,
            workflow_execution_id=100,
            source="stripe",
            event_type="invoice.paid",
            workflow_name="process_invoice",
            delivery_id="del-1",
            event_id="evt-1",
        )
        context = corr.as_workflow_execution_context()
        assert "webhook_trigger" in context
        assert context["webhook_trigger"]["webhook_event_id"] == 1
        assert context["webhook_trigger"]["delivery_id"] == "del-1"


class TestApplyCorrelation:
    def test_apply_to_webhook_event(self) -> None:
        event = _mock_event()
        execution = _mock_execution()
        corr = build_webhook_workflow_correlation(event, execution)
        result = apply_correlation_to_webhook_event(event, corr)
        assert "workflow_correlation" in result.processing_metadata

    def test_apply_to_workflow_execution(self) -> None:
        event = _mock_event()
        execution = _mock_execution()
        corr = build_webhook_workflow_correlation(event, execution)
        result = apply_correlation_to_workflow_execution(execution, corr)
        assert "webhook_trigger" in result.execution_context

    def test_apply_preserves_existing_metadata(self) -> None:
        event = _mock_event()
        event.processing_metadata = {"existing": "data"}
        execution = _mock_execution()
        corr = build_webhook_workflow_correlation(event, execution)
        apply_correlation_to_webhook_event(event, corr)
        assert event.processing_metadata["existing"] == "data"
        assert "workflow_correlation" in event.processing_metadata


class TestBuildWorkflowInput:
    def test_basic_input(self) -> None:
        event = _mock_event(normalized_payload={"amount": 100})
        result = build_workflow_input_from_webhook(event)
        assert result["webhook_event_id"] == 1
        assert result["source"] == "stripe"
        assert result["event_type"] == "invoice.paid"
        assert result["normalized_payload"]["amount"] == 100

    def test_extra_context(self) -> None:
        event = _mock_event()
        result = build_workflow_input_from_webhook(event, extra_context={"custom": "val"})
        assert result["extra_context"]["custom"] == "val"


class TestCorrelationExports:
    def test_canonical_surface(self) -> None:
        from src.app.webhooks import (
            WebhookWorkflowCorrelation,
        )
        assert WebhookWorkflowCorrelation is not None

    def test_platform_surface(self) -> None:
        from src.app.platform.webhooks import (
            WebhookWorkflowCorrelation,
        )
        assert WebhookWorkflowCorrelation is not None

    def test_legacy_surface(self) -> None:
        from src.app.core.webhooks import (
            WebhookWorkflowCorrelation,
        )
        assert WebhookWorkflowCorrelation is not None
