"""Webhook-to-workflow event correlation primitives.

This module provides reusable contracts for linking webhook events to downstream
workflow executions so operators can trace end-to-end from inbound delivery
through processing to workflow completion.

The correlation primitives are template-owned and provider-agnostic.  Cloned
projects use these to connect their provider-specific webhook receivers to
workflow orchestration without building ad hoc correlation logic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..platform.database import WebhookEvent, WorkflowExecution


@dataclass(slots=True, frozen=True)
class WebhookWorkflowCorrelation:
    """Typed link between a webhook event and a workflow execution.

    This is the primary correlation handle.  When a webhook processing job
    creates a workflow execution, it builds one of these to record the
    relationship in both the webhook event's processing metadata and the
    workflow execution's context.
    """

    webhook_event_id: int
    workflow_execution_id: int
    source: str
    event_type: str
    workflow_name: str
    correlation_id: str | None = None
    delivery_id: str | None = None
    event_id: str | None = None
    correlated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_webhook_processing_metadata(self) -> dict[str, Any]:
        """Render correlation details for the webhook event processing_metadata column."""
        metadata: dict[str, Any] = {
            "workflow_execution_id": self.workflow_execution_id,
            "workflow_name": self.workflow_name,
            "correlated_at": self.correlated_at.isoformat(),
        }
        if self.correlation_id is not None:
            metadata["correlation_id"] = self.correlation_id
        return {"workflow_correlation": metadata}

    def as_workflow_execution_context(self) -> dict[str, Any]:
        """Render correlation details for the workflow execution execution_context column."""
        context: dict[str, Any] = {
            "webhook_event_id": self.webhook_event_id,
            "source": self.source,
            "event_type": self.event_type,
            "correlated_at": self.correlated_at.isoformat(),
        }
        if self.delivery_id is not None:
            context["delivery_id"] = self.delivery_id
        if self.event_id is not None:
            context["event_id"] = self.event_id
        if self.correlation_id is not None:
            context["correlation_id"] = self.correlation_id
        return {"webhook_trigger": context}


def build_webhook_workflow_correlation(
    event: WebhookEvent,
    execution: WorkflowExecution,
    *,
    correlation_id: str | None = None,
) -> WebhookWorkflowCorrelation:
    """Build a typed correlation handle from a webhook event and workflow execution.

    Call this after creating a ``WorkflowExecution`` from a webhook processing
    job.  The returned handle provides ``as_webhook_processing_metadata()`` and
    ``as_workflow_execution_context()`` for persisting the bidirectional link.
    """
    return WebhookWorkflowCorrelation(
        webhook_event_id=event.id,
        workflow_execution_id=execution.id,
        source=event.source,
        event_type=event.event_type,
        workflow_name=execution.workflow_name,
        correlation_id=correlation_id,
        delivery_id=event.delivery_id,
        event_id=event.event_id,
    )


def apply_correlation_to_webhook_event(
    event: WebhookEvent,
    correlation: WebhookWorkflowCorrelation,
) -> WebhookEvent:
    """Merge workflow correlation metadata into a webhook event's processing_metadata."""
    existing_metadata: dict[str, Any] = dict(event.processing_metadata or {})
    existing_metadata.update(correlation.as_webhook_processing_metadata())
    event.processing_metadata = existing_metadata
    return event


def apply_correlation_to_workflow_execution(
    execution: WorkflowExecution,
    correlation: WebhookWorkflowCorrelation,
) -> WorkflowExecution:
    """Merge webhook trigger context into a workflow execution's execution_context."""
    existing_context: dict[str, Any] = dict(execution.execution_context or {})
    existing_context.update(correlation.as_workflow_execution_context())
    execution.execution_context = existing_context
    return execution


def build_workflow_input_from_webhook(
    event: WebhookEvent,
    *,
    extra_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a workflow input payload from a webhook event for workflow creation.

    This is a convenience helper for the common pattern where a webhook event
    triggers a workflow execution.  The resulting dict is suitable for the
    ``input_payload`` column on ``WorkflowExecution``.
    """
    input_payload: dict[str, Any] = {
        "webhook_event_id": event.id,
        "source": event.source,
        "endpoint_key": event.endpoint_key,
        "event_type": event.event_type,
    }
    if event.delivery_id is not None:
        input_payload["delivery_id"] = event.delivery_id
    if event.event_id is not None:
        input_payload["event_id"] = event.event_id
    if event.normalized_payload is not None:
        input_payload["normalized_payload"] = dict(event.normalized_payload)

    if extra_context:
        input_payload["extra_context"] = dict(extra_context)

    return input_payload


__all__ = [
    "WebhookWorkflowCorrelation",
    "apply_correlation_to_webhook_event",
    "apply_correlation_to_workflow_execution",
    "build_webhook_workflow_correlation",
    "build_workflow_input_from_webhook",
]
