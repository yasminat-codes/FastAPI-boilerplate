"""Operational webhook processing contracts for job offload, retry safety, and payload storage.

This module provides the reusable contracts that sit between the canonical intake
pipeline (``ingest_webhook_event``) and the downstream job workers that actually
process accepted webhook deliveries.  The primitives here are template-owned and
provider-agnostic so cloned projects can focus on the provider-specific parts.

Key contracts:

* **Acknowledgement strategy** — ``WebhookAcknowledgementPolicy`` and
  ``build_webhook_ack_response`` encode the template rule that webhook routes
  must return a fast ``202 Accepted`` response before any heavy processing.
* **Job offload** — ``WebhookProcessingJobRequest`` and
  ``WebhookProcessingJobEnqueuer`` provide a typed contract for handing a
  validated, persisted webhook event to the background worker layer.
* **Retry-safe processing** — ``WebhookProcessingAttempt``,
  ``WebhookRetryDecision``, and ``WebhookProcessingOutcome`` define a reusable
  try/retry/fail lifecycle so every downstream processor has a consistent
  retry-safety contract.
* **Payload storage and normalization** — ``WebhookPayloadSnapshot`` and
  ``build_payload_snapshot`` capture both the original raw payload and any
  provider-normalized form so downstream processors and operators can always
  inspect the exact bytes the provider sent.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..platform.database import WebhookEvent


# ---------------------------------------------------------------------------
# Acknowledgement strategy
# ---------------------------------------------------------------------------


class WebhookAcknowledgementPolicy(StrEnum):
    """Acknowledgement timing contract for webhook providers.

    Template adopters should return a fast HTTP response (usually ``202 Accepted``)
    before any heavy processing starts.  The canonical ``ingest_webhook_event``
    flow marks a ``WebhookEvent`` acknowledged immediately after persistence and
    before enqueue, so the route handler can reply without blocking on job dispatch.

    * ``IMMEDIATE`` — return the acknowledgement response from the route handler
      as soon as the event is persisted and enqueued.  This is the recommended
      default.  The provider receives a sub-second response, and all business
      logic runs in the background job layer.

    * ``DEFERRED`` — return the acknowledgement after a lightweight inline
      pre-check (e.g. event-type allowlist lookup or fast payload sanity check).
      Use only when the provider requires a richer ``2xx`` body before it
      considers the delivery settled.
    """

    IMMEDIATE = "immediate"
    DEFERRED = "deferred"


@dataclass(slots=True, frozen=True)
class WebhookAcknowledgementResult:
    """Structured acknowledgement metadata for the route response body."""

    status: str = "accepted"
    event_id: int | None = None
    correlation_id: str | None = None
    policy: WebhookAcknowledgementPolicy = WebhookAcknowledgementPolicy.IMMEDIATE
    acknowledged_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_response_body(self) -> dict[str, Any]:
        """Render a provider-safe ``202 Accepted`` response payload."""
        body: dict[str, Any] = {"status": self.status}
        if self.event_id is not None:
            body["event_id"] = self.event_id
        if self.correlation_id is not None:
            body["correlation_id"] = self.correlation_id
        return body


def build_webhook_ack_response(
    event: WebhookEvent,
    *,
    correlation_id: str | None = None,
    policy: WebhookAcknowledgementPolicy = WebhookAcknowledgementPolicy.IMMEDIATE,
) -> WebhookAcknowledgementResult:
    """Build a standard webhook acknowledgement result from a persisted event.

    Routes should call this after ``ingest_webhook_event`` returns and use
    ``result.as_response_body()`` as the JSON payload with a ``202`` status code.
    """
    return WebhookAcknowledgementResult(
        status="accepted",
        event_id=event.id,
        correlation_id=correlation_id,
        policy=policy,
    )


# ---------------------------------------------------------------------------
# Payload snapshot — original + normalized storage
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class WebhookPayloadSnapshot:
    """Immutable capture of both raw and normalized webhook payload forms.

    The template stores ``raw_payload`` (the exact text the provider sent) and
    ``normalized_payload`` (a provider-independent dict) on the ``WebhookEvent``
    row.  This dataclass provides a typed handle so downstream processors and
    replay tooling can inspect both forms without re-parsing the original bytes.
    """

    raw_payload: str | None
    normalized_payload: dict[str, Any] | None
    content_type: str | None
    payload_sha256: str | None
    payload_size_bytes: int | None
    stored_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def has_raw_payload(self) -> bool:
        return self.raw_payload is not None

    @property
    def has_normalized_payload(self) -> bool:
        return self.normalized_payload is not None


def build_payload_snapshot(event: WebhookEvent) -> WebhookPayloadSnapshot:
    """Reconstruct a typed payload snapshot from a persisted webhook event row."""
    return WebhookPayloadSnapshot(
        raw_payload=event.raw_payload,
        normalized_payload=dict(event.normalized_payload) if event.normalized_payload else None,
        content_type=event.payload_content_type,
        payload_sha256=event.payload_sha256,
        payload_size_bytes=event.payload_size_bytes,
    )


# ---------------------------------------------------------------------------
# Job offload contract
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class WebhookProcessingJobRequest:
    """Typed input contract for handing a webhook event to a background processor.

    This is the bridge between the intake pipeline and the worker layer.  The
    canonical ingestion flow persists the event and enqueues a job; the worker
    receives this request (serialized through the ``JobEnvelope`` payload) and
    runs provider-specific business logic.
    """

    webhook_event_id: int
    source: str
    endpoint_key: str
    event_type: str
    correlation_id: str | None = None
    delivery_id: str | None = None
    event_id: str | None = None
    payload_sha256: str | None = None
    processing_metadata: dict[str, Any] | None = None

    def as_job_payload(self) -> dict[str, Any]:
        """Serialize into a dict suitable for ``WorkerJob.enqueue(payload=...)``."""
        payload: dict[str, Any] = {
            "webhook_event_id": self.webhook_event_id,
            "source": self.source,
            "endpoint_key": self.endpoint_key,
            "event_type": self.event_type,
        }
        if self.correlation_id is not None:
            payload["correlation_id"] = self.correlation_id
        if self.delivery_id is not None:
            payload["delivery_id"] = self.delivery_id
        if self.event_id is not None:
            payload["event_id"] = self.event_id
        if self.payload_sha256 is not None:
            payload["payload_sha256"] = self.payload_sha256
        if self.processing_metadata is not None:
            payload["processing_metadata"] = dict(self.processing_metadata)
        return payload

    @classmethod
    def from_job_payload(cls, payload: Mapping[str, Any]) -> WebhookProcessingJobRequest:
        """Reconstruct from a deserialized ``JobEnvelope.payload`` dict."""
        return cls(
            webhook_event_id=int(payload["webhook_event_id"]),
            source=str(payload["source"]),
            endpoint_key=str(payload["endpoint_key"]),
            event_type=str(payload["event_type"]),
            correlation_id=payload.get("correlation_id"),
            delivery_id=payload.get("delivery_id"),
            event_id=payload.get("event_id"),
            payload_sha256=payload.get("payload_sha256"),
            processing_metadata=payload.get("processing_metadata"),
        )


def build_processing_job_request(
    event: WebhookEvent,
    *,
    correlation_id: str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> WebhookProcessingJobRequest:
    """Build a typed job request from a persisted webhook event."""
    metadata: dict[str, Any] | None = None
    if extra_metadata:
        metadata = dict(extra_metadata)
    return WebhookProcessingJobRequest(
        webhook_event_id=event.id,
        source=event.source,
        endpoint_key=event.endpoint_key,
        event_type=event.event_type,
        correlation_id=correlation_id,
        delivery_id=event.delivery_id,
        event_id=event.event_id,
        payload_sha256=event.payload_sha256,
        processing_metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Retry-safe processing contracts
# ---------------------------------------------------------------------------


class WebhookProcessingStatus(StrEnum):
    """Lifecycle status for a webhook processing attempt."""

    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"
    DEAD_LETTERED = "dead_lettered"


class WebhookRetryDecision(StrEnum):
    """Decision outcome after a webhook processing failure."""

    RETRY = "retry"
    DEAD_LETTER = "dead_letter"
    DISCARD = "discard"


@dataclass(slots=True, frozen=True)
class WebhookProcessingAttempt:
    """Record of a single webhook processing attempt for retry-safety tracking.

    Workers should create an attempt at the start of processing and update it
    with the outcome.  The ``attempt_number`` and ``max_attempts`` fields let
    the retry decision logic determine whether to retry, dead-letter, or discard
    after a failure.
    """

    webhook_event_id: int
    attempt_number: int
    max_attempts: int
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    source: str = ""
    event_type: str = ""
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("Processing attempt_number must be at least 1")
        if self.max_attempts < 1:
            raise ValueError("Processing max_attempts must be at least 1")

    @property
    def is_final_attempt(self) -> bool:
        return self.attempt_number >= self.max_attempts

    @property
    def remaining_attempts(self) -> int:
        return max(self.max_attempts - self.attempt_number, 0)


@dataclass(slots=True, frozen=True)
class WebhookProcessingOutcome:
    """Outcome of a webhook processing attempt including retry decision."""

    attempt: WebhookProcessingAttempt
    status: WebhookProcessingStatus
    retry_decision: WebhookRetryDecision | None = None
    error_message: str | None = None
    error_category: str | None = None
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    processing_metadata: dict[str, Any] | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is WebhookProcessingStatus.SUCCEEDED

    @property
    def should_retry(self) -> bool:
        return self.retry_decision is WebhookRetryDecision.RETRY

    @property
    def should_dead_letter(self) -> bool:
        return self.retry_decision is WebhookRetryDecision.DEAD_LETTER

    def as_processing_metadata(self) -> dict[str, Any]:
        """Render outcome details for webhook event processing metadata."""
        metadata: dict[str, Any] = {
            "status": self.status.value,
            "attempt_number": self.attempt.attempt_number,
            "max_attempts": self.attempt.max_attempts,
            "started_at": self.attempt.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
        }
        if self.retry_decision is not None:
            metadata["retry_decision"] = self.retry_decision.value
        if self.error_message is not None:
            metadata["error_message"] = self.error_message
        if self.error_category is not None:
            metadata["error_category"] = self.error_category
        return {"processing": metadata}


def decide_retry(
    attempt: WebhookProcessingAttempt,
    error: Exception,
    *,
    retryable_errors: tuple[type[Exception], ...] = (),
    permanent_errors: tuple[type[Exception], ...] = (),
) -> WebhookProcessingOutcome:
    """Decide whether a failed processing attempt should be retried, dead-lettered, or discarded.

    The decision logic follows this order:

    1. If the error matches ``permanent_errors``, the event is immediately dead-lettered.
    2. If the attempt is the final attempt, the event is dead-lettered.
    3. If the error matches ``retryable_errors`` (or no ``retryable_errors`` are
       specified, treating all non-permanent errors as retryable), the event is retried.
    4. Otherwise, the event is dead-lettered.
    """
    error_message = str(error).strip() or error.__class__.__name__
    error_category = error.__class__.__name__

    if permanent_errors and isinstance(error, permanent_errors):
        return WebhookProcessingOutcome(
            attempt=attempt,
            status=WebhookProcessingStatus.FAILED_PERMANENT,
            retry_decision=WebhookRetryDecision.DEAD_LETTER,
            error_message=error_message,
            error_category=error_category,
        )

    if attempt.is_final_attempt:
        return WebhookProcessingOutcome(
            attempt=attempt,
            status=WebhookProcessingStatus.FAILED_RETRYABLE,
            retry_decision=WebhookRetryDecision.DEAD_LETTER,
            error_message=error_message,
            error_category=error_category,
        )

    is_retryable = not retryable_errors or isinstance(error, retryable_errors)
    if is_retryable:
        return WebhookProcessingOutcome(
            attempt=attempt,
            status=WebhookProcessingStatus.FAILED_RETRYABLE,
            retry_decision=WebhookRetryDecision.RETRY,
            error_message=error_message,
            error_category=error_category,
        )

    return WebhookProcessingOutcome(
        attempt=attempt,
        status=WebhookProcessingStatus.FAILED_PERMANENT,
        retry_decision=WebhookRetryDecision.DEAD_LETTER,
        error_message=error_message,
        error_category=error_category,
    )


def build_success_outcome(attempt: WebhookProcessingAttempt) -> WebhookProcessingOutcome:
    """Build a successful processing outcome for a completed attempt."""
    return WebhookProcessingOutcome(
        attempt=attempt,
        status=WebhookProcessingStatus.SUCCEEDED,
        retry_decision=None,
    )


__all__ = [
    "WebhookAcknowledgementPolicy",
    "WebhookAcknowledgementResult",
    "WebhookPayloadSnapshot",
    "WebhookProcessingAttempt",
    "WebhookProcessingJobRequest",
    "WebhookProcessingOutcome",
    "WebhookProcessingStatus",
    "WebhookRetryDecision",
    "build_payload_snapshot",
    "build_processing_job_request",
    "build_success_outcome",
    "build_webhook_ack_response",
    "decide_retry",
]
