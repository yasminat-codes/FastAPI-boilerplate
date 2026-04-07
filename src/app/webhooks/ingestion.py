"""Canonical webhook ingestion helpers and reusable intake pipeline primitives."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from fastapi import Request
from starlette.datastructures import Headers

from ..core.config import settings
from ..core.request_context import get_correlation_id

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..core.config import SettingsProfile, WebhookRuntimeSettings
    from ..platform.database import WebhookEvent
    from .persistence import WebhookEventStore
    from .replay import WebhookReplayProtectionResult, WebhookReplayProtector
    from .signatures import (
        WebhookSignatureVerificationResult,
    )

RAW_REQUEST_BODY_STATE_KEY = "raw_request_body"


@dataclass(slots=True, frozen=True)
class WebhookIngestionRequest:
    """Raw-body webhook request context for signature verification and later parsing."""

    request: Request
    raw_body: bytes
    content_type: str | None

    @property
    def headers(self) -> Headers:
        return self.request.headers

    @property
    def payload_size_bytes(self) -> int:
        return len(self.raw_body)

    @property
    def media_type(self) -> str | None:
        if not self.content_type:
            return None

        media_type = self.content_type.split(";", maxsplit=1)[0].strip().lower()
        return media_type or None

    @property
    def charset(self) -> str | None:
        if not self.content_type:
            return None

        for component in self.content_type.split(";")[1:]:
            name, _, value = component.partition("=")
            if name.strip().lower() != "charset":
                continue

            charset = value.strip().strip("\"'")
            return charset or None

        return None

    def text(self, *, encoding: str | None = None, errors: str = "strict") -> str:
        return self.raw_body.decode(encoding or self.charset or "utf-8", errors)

    def json(self) -> Any:
        return parse_raw_json_body(self.raw_body)


@dataclass(slots=True, frozen=True)
class WebhookValidatedEvent:
    """Validated webhook payload details used by the canonical intake pipeline."""

    event_type: str
    event_id: str | None = None
    delivery_id: str | None = None
    normalized_payload: dict[str, Any] | None = None
    processing_metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.event_type.strip():
            raise ValueError("Webhook validated event_type must not be empty")


@runtime_checkable
class WebhookEventValidator(Protocol):
    """Validate a webhook payload and extract canonical event metadata."""

    async def validate(
        self,
        request: WebhookIngestionRequest,
        verification: WebhookSignatureVerificationResult | None,
    ) -> WebhookValidatedEvent: ...


WebhookEventValidatorCallable = Callable[[WebhookIngestionRequest, Any], Any]
WebhookEventValidatorLike = WebhookEventValidator | WebhookEventValidatorCallable


@dataclass(slots=True, frozen=True)
class WebhookEventEnqueueRequest:
    """Canonical input contract for handing a validated webhook to async processing."""

    source: str
    endpoint_key: str
    webhook_request: WebhookIngestionRequest
    persisted_event: WebhookEvent
    validated_event: WebhookValidatedEvent
    signature_verification: WebhookSignatureVerificationResult | None = None
    replay_protection: WebhookReplayProtectionResult | None = None
    correlation_id: str | None = None


@dataclass(slots=True, frozen=True)
class WebhookEventEnqueueResult:
    """Optional metadata recorded after a webhook is successfully enqueued."""

    job_name: str | None = None
    queue_name: str | None = None
    job_id: str | None = None
    processing_metadata: Mapping[str, Any] | None = None


@runtime_checkable
class WebhookEventEnqueuer(Protocol):
    """Enqueue a validated webhook into downstream processing."""

    async def enqueue(self, request: WebhookEventEnqueueRequest) -> WebhookEventEnqueueResult | None: ...


WebhookEventEnqueuerCallable = Callable[[WebhookEventEnqueueRequest], Any]
WebhookEventEnqueuerLike = WebhookEventEnqueuer | WebhookEventEnqueuerCallable


@dataclass(slots=True, frozen=True)
class WebhookIngestionResult:
    """Outcome of the reusable webhook receive-validate-persist-ack-enqueue flow."""

    persisted_event: WebhookEvent
    validated_event: WebhookValidatedEvent
    signature_verification: WebhookSignatureVerificationResult | None
    enqueue_result: WebhookEventEnqueueResult | None
    correlation_id: str | None = None
    replay_protection: WebhookReplayProtectionResult | None = None


async def read_raw_request_body(request: Request) -> bytes:
    """Read and cache the exact inbound request body for signature verification."""

    cached_body = getattr(request.state, RAW_REQUEST_BODY_STATE_KEY, None)
    if isinstance(cached_body, bytes):
        return cached_body

    raw_body = await request.body()
    setattr(request.state, RAW_REQUEST_BODY_STATE_KEY, raw_body)
    return raw_body


async def build_webhook_ingestion_request(request: Request) -> WebhookIngestionRequest:
    """Build a reusable raw-body webhook request context for route dependencies."""

    raw_body = await read_raw_request_body(request)
    return WebhookIngestionRequest(
        request=request,
        raw_body=raw_body,
        content_type=request.headers.get("content-type"),
    )


def parse_raw_json_body(raw_body: bytes) -> Any:
    """Parse a raw request body as JSON after signature verification succeeds."""

    return json.loads(raw_body)


def validate_json_webhook_event(
    request: WebhookIngestionRequest,
    verification: WebhookSignatureVerificationResult | None = None,
) -> WebhookValidatedEvent:
    """Validate a JSON-object webhook payload and extract the canonical event fields."""

    del verification

    payload = request.json()
    if not isinstance(payload, dict):
        raise ValueError("Webhook JSON payload must be an object")

    raw_event_type = payload.get("type")
    if not isinstance(raw_event_type, str) or not raw_event_type.strip():
        raise ValueError("Webhook payload must include a non-empty 'type' field")

    raw_event_id = payload.get("id")
    event_id = None if raw_event_id is None else str(raw_event_id).strip() or None

    return WebhookValidatedEvent(
        event_type=raw_event_type.strip(),
        event_id=event_id,
        normalized_payload=dict(payload),
    )


async def ingest_webhook_event(
    *,
    session: AsyncSession,
    webhook_request: WebhookIngestionRequest,
    source: str,
    endpoint_key: str,
    enqueuer: WebhookEventEnqueuerLike,
    verifier: object | None = None,
    event_validator: WebhookEventValidatorLike = validate_json_webhook_event,
    runtime_settings: SettingsProfile | WebhookRuntimeSettings | None = None,
    signature_max_age_seconds: int | None = None,
    replay_window_seconds: int | None = None,
    store_raw_payload: bool | None = None,
    processing_metadata: Mapping[str, Any] | None = None,
    event_store: WebhookEventStore | None = None,
    replay_protector: WebhookReplayProtector | None = None,
) -> WebhookIngestionResult:
    """Run the canonical webhook receive-validate-persist-acknowledge-enqueue flow."""

    from .persistence import WebhookEventPersistenceRequest, webhook_event_store
    from .replay import WebhookReplayProtectionRequest, webhook_replay_protector
    from .signatures import verify_webhook_signature

    configured_settings = settings if runtime_settings is None else runtime_settings
    resolved_event_store = webhook_event_store if event_store is None else event_store
    resolved_store_raw_payload = (
        configured_settings.WEBHOOK_STORE_RAW_PAYLOADS if store_raw_payload is None else store_raw_payload
    )

    signature_verification = None
    if verifier is not None:
        signature_verification = await verify_webhook_signature(
            cast(Any, verifier),
            request=webhook_request,
            provider=source,
            endpoint_key=endpoint_key,
            signature_max_age_seconds=(
                configured_settings.WEBHOOK_SIGNATURE_MAX_AGE_SECONDS
                if signature_max_age_seconds is None
                else signature_max_age_seconds
            ),
        )
    elif configured_settings.WEBHOOK_SIGNATURE_VERIFICATION_ENABLED:
        raise ValueError(
            "A webhook signature verifier is required when WEBHOOK_SIGNATURE_VERIFICATION_ENABLED is enabled"
        )

    validated_event = await _call_webhook_event_validator(
        event_validator,
        webhook_request=webhook_request,
        verification=signature_verification,
    )

    correlation_id = get_correlation_id(webhook_request.request)
    replay_protection = None
    if configured_settings.WEBHOOK_REPLAY_PROTECTION_ENABLED:
        resolved_replay_protector = webhook_replay_protector if replay_protector is None else replay_protector
        replay_protection = await resolved_replay_protector.protect(
            session,
            WebhookReplayProtectionRequest(
                source=source,
                endpoint_key=endpoint_key,
                webhook_request=webhook_request,
                validated_event=validated_event,
                replay_window_seconds=(
                    configured_settings.WEBHOOK_REPLAY_WINDOW_SECONDS
                    if replay_window_seconds is None
                    else replay_window_seconds
                ),
            ),
        )

    persisted_event = await resolved_event_store.persist(
        session,
        WebhookEventPersistenceRequest(
            source=source,
            endpoint_key=endpoint_key,
            event_type=validated_event.event_type,
            delivery_id=validated_event.delivery_id,
            event_id=validated_event.event_id,
            webhook_request=webhook_request,
            normalized_payload=validated_event.normalized_payload,
            processing_metadata=_merge_metadata(
                processing_metadata,
                validated_event.processing_metadata,
                None if correlation_id is None else {"correlation_id": correlation_id},
                None if replay_protection is None else replay_protection.as_processing_metadata(),
            ),
            signature_verification=signature_verification,
            store_raw_payload=resolved_store_raw_payload,
        ),
    )
    resolved_event_store.mark_acknowledged(persisted_event)

    enqueue_request = WebhookEventEnqueueRequest(
        source=source,
        endpoint_key=endpoint_key,
        webhook_request=webhook_request,
        persisted_event=persisted_event,
        validated_event=validated_event,
        signature_verification=signature_verification,
        replay_protection=replay_protection,
        correlation_id=correlation_id,
    )

    try:
        enqueue_result = await _call_webhook_event_enqueuer(enqueuer, request=enqueue_request)
    except Exception as exc:
        resolved_event_store.mark_failed(
            persisted_event,
            processing_error=_format_exception_message(exc),
            processing_metadata={"enqueue": {"status": "failed"}},
        )
        raise

    resolved_event_store.mark_enqueued(
        persisted_event,
        processing_metadata=_build_enqueue_processing_metadata(enqueue_result),
    )

    return WebhookIngestionResult(
        persisted_event=persisted_event,
        validated_event=validated_event,
        signature_verification=signature_verification,
        enqueue_result=enqueue_result,
        correlation_id=correlation_id,
        replay_protection=replay_protection,
    )


async def _call_webhook_event_validator(
    validator: WebhookEventValidatorLike,
    *,
    webhook_request: WebhookIngestionRequest,
    verification: WebhookSignatureVerificationResult | None,
) -> WebhookValidatedEvent:
    if isinstance(validator, WebhookEventValidator):
        validation: Any = validator.validate(webhook_request, verification)
    else:
        validator_callable = cast(WebhookEventValidatorCallable, validator)
        validation = validator_callable(webhook_request, verification)

    if inspect.isawaitable(validation):
        return cast(WebhookValidatedEvent, await cast(Awaitable[Any], validation))

    return cast(WebhookValidatedEvent, validation)


async def _call_webhook_event_enqueuer(
    enqueuer: WebhookEventEnqueuerLike,
    *,
    request: WebhookEventEnqueueRequest,
) -> WebhookEventEnqueueResult | None:
    if isinstance(enqueuer, WebhookEventEnqueuer):
        enqueue_result: Any = enqueuer.enqueue(request)
    else:
        enqueue_callable = cast(WebhookEventEnqueuerCallable, enqueuer)
        enqueue_result = enqueue_callable(request)

    if inspect.isawaitable(enqueue_result):
        return cast(WebhookEventEnqueueResult | None, await cast(Awaitable[Any], enqueue_result))

    return cast(WebhookEventEnqueueResult | None, enqueue_result)


def _build_enqueue_processing_metadata(
    enqueue_result: WebhookEventEnqueueResult | None,
) -> dict[str, Any] | None:
    if enqueue_result is None:
        return {"enqueue": {"status": "queued"}}

    enqueue_metadata: dict[str, Any] = {}
    if enqueue_result.job_name is not None:
        enqueue_metadata["job_name"] = enqueue_result.job_name
    if enqueue_result.queue_name is not None:
        enqueue_metadata["queue_name"] = enqueue_result.queue_name
    if enqueue_result.job_id is not None:
        enqueue_metadata["job_id"] = enqueue_result.job_id
    enqueue_metadata["status"] = "queued"

    additional_metadata = dict(enqueue_result.processing_metadata or {})
    if "enqueue" in additional_metadata:
        existing_enqueue = additional_metadata.pop("enqueue")
        if isinstance(existing_enqueue, Mapping):
            enqueue_metadata = {
                **dict(existing_enqueue),
                **enqueue_metadata,
            }

    combined_metadata = dict(additional_metadata)
    combined_metadata["enqueue"] = enqueue_metadata
    return combined_metadata


def _merge_metadata(*mappings: Mapping[str, Any] | None) -> dict[str, Any] | None:
    merged_metadata: dict[str, Any] = {}
    for mapping in mappings:
        if mapping is None:
            continue
        merged_metadata.update(dict(mapping))

    return merged_metadata or None


def _format_exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return message

    return exc.__class__.__name__


__all__ = [
    "RAW_REQUEST_BODY_STATE_KEY",
    "WebhookEventEnqueueRequest",
    "WebhookEventEnqueueResult",
    "WebhookEventEnqueuer",
    "WebhookEventValidator",
    "WebhookIngestionResult",
    "WebhookIngestionRequest",
    "WebhookValidatedEvent",
    "build_webhook_ingestion_request",
    "ingest_webhook_event",
    "parse_raw_json_body",
    "read_raw_request_body",
    "validate_json_webhook_event",
]
