"""Webhook payload validation, event-type routing, and poison-payload detection primitives."""

from __future__ import annotations

import json
from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class WebhookValidationErrorKind(StrEnum):
    """Machine-readable classification for webhook validation failures."""

    MALFORMED_CONTENT_TYPE = "malformed_content_type"
    EMPTY_PAYLOAD = "empty_payload"
    INVALID_JSON = "invalid_json"
    INVALID_JSON_STRUCTURE = "invalid_json_structure"
    UNKNOWN_EVENT_TYPE = "unknown_event_type"
    MISSING_EVENT_TYPE = "missing_event_type"
    POISON_PAYLOAD = "poison_payload"


class WebhookPayloadValidationError(ValueError):
    """Base error for webhook payload validation failures.

    Template adopters should catch this at the route level to return
    a consistent 400-family response to the webhook provider while
    persisting the delivery as REJECTED in the webhook event ledger.
    """

    def __init__(
        self,
        kind: WebhookValidationErrorKind,
        message: str,
        *,
        source: str | None = None,
        endpoint_key: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.kind = kind
        self.source = source
        self.endpoint_key = endpoint_key
        self.details = details or {}
        super().__init__(message)

    def as_processing_metadata(self) -> dict[str, object]:
        """Render validation failure details into webhook processing metadata."""
        metadata: dict[str, object] = {
            "kind": self.kind.value,
            "message": str(self),
        }
        if self.source is not None:
            metadata["source"] = self.source
        if self.endpoint_key is not None:
            metadata["endpoint_key"] = self.endpoint_key
        if self.details:
            metadata["details"] = dict(self.details)
        return {"validation_error": metadata}


class MalformedPayloadError(WebhookPayloadValidationError):
    """Raised when the inbound payload cannot be parsed or has an unsupported structure."""

    def __init__(
        self,
        kind: WebhookValidationErrorKind = WebhookValidationErrorKind.INVALID_JSON,
        message: str = "Webhook payload is malformed",
        **kwargs: Any,
    ) -> None:
        super().__init__(kind, message, **kwargs)


class UnknownEventTypeError(WebhookPayloadValidationError):
    """Raised when the webhook event type is not in the provider's registered set."""

    def __init__(
        self,
        event_type: str,
        *,
        source: str | None = None,
        endpoint_key: str | None = None,
        allowed_types: Set[str] | None = None,
    ) -> None:
        details: dict[str, Any] = {"event_type": event_type}
        if allowed_types is not None:
            details["allowed_types_count"] = len(allowed_types)
        super().__init__(
            WebhookValidationErrorKind.UNKNOWN_EVENT_TYPE,
            f"Unknown webhook event type: {event_type}",
            source=source,
            endpoint_key=endpoint_key,
            details=details,
        )
        self.event_type = event_type
        self.allowed_types = allowed_types


class PoisonPayloadError(WebhookPayloadValidationError):
    """Raised when a payload has been identified as a poison message.

    Poison payloads are deliveries that have failed processing repeatedly
    and should be routed to dead-letter storage instead of retried again.
    """

    def __init__(
        self,
        message: str = "Webhook payload identified as poison",
        *,
        failure_count: int | None = None,
        max_failures: int | None = None,
        source: str | None = None,
        endpoint_key: str | None = None,
        event_type: str | None = None,
        payload_sha256: str | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if failure_count is not None:
            details["failure_count"] = failure_count
        if max_failures is not None:
            details["max_failures"] = max_failures
        if event_type is not None:
            details["event_type"] = event_type
        if payload_sha256 is not None:
            details["payload_sha256"] = payload_sha256
        super().__init__(
            WebhookValidationErrorKind.POISON_PAYLOAD,
            message,
            source=source,
            endpoint_key=endpoint_key,
            details=details,
        )
        self.failure_count = failure_count
        self.max_failures = max_failures


def validate_webhook_content_type(
    content_type: str | None,
    *,
    allowed_media_types: Set[str] | None = None,
) -> str | None:
    """Validate and normalize the inbound content type.

    Returns the normalized media type or raises MalformedPayloadError
    if the content type is not in the allowed set.

    When *allowed_media_types* is None the default set accepts
    ``application/json`` and ``application/json; charset=utf-8`` variants.
    """

    default_allowed: frozenset[str] = frozenset({"application/json"})
    resolved_allowed = default_allowed if allowed_media_types is None else allowed_media_types

    if content_type is None:
        return None

    media_type = content_type.split(";", maxsplit=1)[0].strip().lower()
    if not media_type:
        return None

    if media_type not in resolved_allowed:
        raise MalformedPayloadError(
            kind=WebhookValidationErrorKind.MALFORMED_CONTENT_TYPE,
            message=f"Unsupported webhook content type: {media_type}",
            details={"content_type": content_type, "media_type": media_type},
        )
    return media_type


def validate_webhook_payload_json(
    raw_body: bytes,
    *,
    require_object: bool = True,
) -> Any:
    """Parse raw bytes as JSON and optionally enforce an object-level structure.

    Raises MalformedPayloadError for empty bodies, invalid JSON, or
    non-object payloads when *require_object* is True.
    """

    if not raw_body:
        raise MalformedPayloadError(
            kind=WebhookValidationErrorKind.EMPTY_PAYLOAD,
            message="Webhook payload is empty",
        )

    try:
        parsed = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MalformedPayloadError(
            kind=WebhookValidationErrorKind.INVALID_JSON,
            message=f"Webhook payload is not valid JSON: {exc}",
            details={"payload_size_bytes": len(raw_body)},
        ) from exc

    if require_object and not isinstance(parsed, dict):
        raise MalformedPayloadError(
            kind=WebhookValidationErrorKind.INVALID_JSON_STRUCTURE,
            message=(
                f"Webhook JSON payload must be an object, "
                f"got {type(parsed).__name__}"
            ),
            details={"payload_type": type(parsed).__name__},
        )

    return parsed


def validate_webhook_event_type(
    event_type: str | None,
    *,
    allowed_event_types: Set[str] | None = None,
    source: str | None = None,
    endpoint_key: str | None = None,
) -> str:
    """Validate a webhook event type string.

    When *allowed_event_types* is not None, raises UnknownEventTypeError
    if the event type is not in the set.  When it is None, only basic
    non-empty validation is applied.
    """

    if event_type is None or not event_type.strip():
        raise MalformedPayloadError(
            kind=WebhookValidationErrorKind.MISSING_EVENT_TYPE,
            message="Webhook payload must include a non-empty event type",
            source=source,
            endpoint_key=endpoint_key,
        )

    normalized = event_type.strip()

    if allowed_event_types is not None and normalized not in allowed_event_types:
        raise UnknownEventTypeError(
            normalized,
            source=source,
            endpoint_key=endpoint_key,
            allowed_types=allowed_event_types,
        )

    return normalized


@dataclass(slots=True, frozen=True)
class WebhookPoisonDetectionRequest:
    """Input contract for poison-payload detection checks."""

    source: str
    endpoint_key: str
    event_type: str
    payload_sha256: str
    max_failures: int = 5
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_id: str | None = None
    delivery_id: str | None = None


@dataclass(slots=True, frozen=True)
class WebhookPoisonDetectionResult:
    """Outcome of a poison-payload detection check."""

    is_poison: bool
    failure_count: int
    max_failures: int
    source: str
    endpoint_key: str
    event_type: str
    payload_sha256: str
    checked_at: datetime

    def as_processing_metadata(self) -> dict[str, object]:
        """Render poison-detection details into webhook processing metadata."""
        return {
            "poison_detection": {
                "is_poison": self.is_poison,
                "failure_count": self.failure_count,
                "max_failures": self.max_failures,
                "checked_at": self.checked_at.isoformat(),
            },
        }


class WebhookDuplicateEventError(ValueError):
    """Raised when a webhook delivery is an exact duplicate of a previously processed event.

    This differs from replay protection in that duplicate detection
    applies to events that have already been fully processed (status PROCESSED),
    while replay protection catches deliveries still in the intake pipeline.
    """

    def __init__(
        self,
        *,
        source: str,
        endpoint_key: str,
        event_id: str | None = None,
        delivery_id: str | None = None,
        existing_event_id: int | None = None,
        existing_status: str | None = None,
    ) -> None:
        self.source = source
        self.endpoint_key = endpoint_key
        self.event_id = event_id
        self.delivery_id = delivery_id
        self.existing_event_id = existing_event_id
        self.existing_status = existing_status

        identifier = event_id or delivery_id or "unknown"
        super().__init__(
            f"Duplicate webhook event for {source}/{endpoint_key}: {identifier} "
            f"(existing record {existing_event_id}, status={existing_status})"
        )

    def as_processing_metadata(self) -> dict[str, object]:
        """Render duplicate-detection details into webhook processing metadata."""
        metadata: dict[str, object] = {
            "source": self.source,
            "endpoint_key": self.endpoint_key,
        }
        if self.event_id is not None:
            metadata["event_id"] = self.event_id
        if self.delivery_id is not None:
            metadata["delivery_id"] = self.delivery_id
        if self.existing_event_id is not None:
            metadata["existing_event_id"] = self.existing_event_id
        if self.existing_status is not None:
            metadata["existing_status"] = self.existing_status
        return {"duplicate_detection": metadata}


@dataclass(slots=True, frozen=True)
class WebhookEventTypeRegistration:
    """Registration entry for a known webhook event type.

    Template adopters build a mapping of these registrations per provider
    so the ingestion pipeline can reject unknown event types early.
    """

    event_type: str
    description: str = ""
    handler_name: str | None = None
    enabled: bool = True


class WebhookEventTypeRegistry:
    """In-memory registry of known event types for a webhook provider.

    Template adopters create one registry per provider and pass it to the
    ingestion pipeline so unknown event types are caught during validation
    instead of failing silently during downstream processing.
    """

    def __init__(
        self,
        *,
        source: str,
        strict: bool = True,
    ) -> None:
        self.source = source
        self.strict = strict
        self._registrations: dict[str, WebhookEventTypeRegistration] = {}

    def register(
        self,
        event_type: str,
        *,
        description: str = "",
        handler_name: str | None = None,
        enabled: bool = True,
    ) -> WebhookEventTypeRegistration:
        """Register a known event type for this provider."""
        registration = WebhookEventTypeRegistration(
            event_type=event_type,
            description=description,
            handler_name=handler_name,
            enabled=enabled,
        )
        self._registrations[event_type] = registration
        return registration

    def register_many(
        self,
        event_types: Mapping[str, str] | Set[str],
    ) -> None:
        """Register multiple event types at once.

        Accepts either a mapping of event_type -> description or a
        plain set of event type strings.
        """
        if isinstance(event_types, Mapping):
            for event_type, description in event_types.items():
                self.register(event_type, description=description)
        else:
            for event_type in event_types:
                self.register(event_type)

    def is_known(self, event_type: str) -> bool:
        """Return True if the event type is registered."""
        return event_type in self._registrations

    def is_enabled(self, event_type: str) -> bool:
        """Return True if the event type is registered and enabled."""
        registration = self._registrations.get(event_type)
        return registration is not None and registration.enabled

    def get(self, event_type: str) -> WebhookEventTypeRegistration | None:
        """Look up a registration by event type."""
        return self._registrations.get(event_type)

    @property
    def known_types(self) -> frozenset[str]:
        """Return the set of all registered event type strings."""
        return frozenset(self._registrations)

    @property
    def enabled_types(self) -> frozenset[str]:
        """Return the set of all registered and enabled event type strings."""
        return frozenset(
            event_type
            for event_type, reg in self._registrations.items()
            if reg.enabled
        )

    def validate(
        self,
        event_type: str,
        *,
        endpoint_key: str | None = None,
    ) -> str:
        """Validate an event type against this registry.

        When strict mode is enabled, raises UnknownEventTypeError for
        unregistered types.  When strict mode is disabled, unknown types
        pass through without error.
        """
        normalized = event_type.strip()
        if not normalized:
            raise MalformedPayloadError(
                kind=WebhookValidationErrorKind.MISSING_EVENT_TYPE,
                message="Webhook event type must not be empty",
                source=self.source,
                endpoint_key=endpoint_key,
            )

        if self.strict and not self.is_known(normalized):
            raise UnknownEventTypeError(
                normalized,
                source=self.source,
                endpoint_key=endpoint_key,
                allowed_types=self.known_types,
            )

        return normalized


__all__ = [
    "MalformedPayloadError",
    "PoisonPayloadError",
    "UnknownEventTypeError",
    "WebhookDuplicateEventError",
    "WebhookEventTypeRegistration",
    "WebhookEventTypeRegistry",
    "WebhookPayloadValidationError",
    "WebhookPoisonDetectionRequest",
    "WebhookPoisonDetectionResult",
    "WebhookValidationErrorKind",
    "validate_webhook_content_type",
    "validate_webhook_event_type",
    "validate_webhook_payload_json",
]
