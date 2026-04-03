"""Reusable request and correlation context helpers for HTTP requests."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import Request
from structlog.contextvars import get_contextvars

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"
REQUEST_CONTEXT_STATE_KEY = "request_context"
REQUEST_ID_STATE_KEY = "request_id"
CORRELATION_ID_STATE_KEY = "correlation_id"


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Canonical request-scoped identifiers for HTTP request handling."""

    request_id: str
    correlation_id: str

    def response_headers(self) -> dict[str, str]:
        """Return the response headers that surface the current request context."""

        return {
            REQUEST_ID_HEADER: self.request_id,
            CORRELATION_ID_HEADER: self.correlation_id,
        }


def _normalize_header_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    return normalized or None


def build_request_context(headers: Mapping[str, str]) -> RequestContext:
    """Build a canonical request context from inbound HTTP headers."""

    request_id = _normalize_header_value(headers.get(REQUEST_ID_HEADER)) or str(uuid4())
    correlation_id = _normalize_header_value(headers.get(CORRELATION_ID_HEADER)) or request_id
    return RequestContext(request_id=request_id, correlation_id=correlation_id)


def get_current_request_id() -> str | None:
    """Return the current request ID from the active structured-log context, if available."""

    return _normalize_header_value(get_contextvars().get(REQUEST_ID_STATE_KEY))


def get_current_correlation_id() -> str | None:
    """Return the active correlation ID, falling back to the current request ID when needed."""

    correlation_id = _normalize_header_value(get_contextvars().get(CORRELATION_ID_STATE_KEY))
    if correlation_id is not None:
        return correlation_id

    return get_current_request_id()


def resolve_correlation_id(correlation_id: str | None = None) -> str | None:
    """Resolve an explicit or currently-bound correlation ID for downstream propagation."""

    return _normalize_header_value(correlation_id) or get_current_correlation_id()


def build_correlation_headers(
    *,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, str]:
    """Build outbound propagation headers from explicit values or the current context."""

    resolved_request_id = _normalize_header_value(request_id) or get_current_request_id()
    resolved_correlation_id = resolve_correlation_id(correlation_id) or resolved_request_id

    headers: dict[str, str] = {}
    if resolved_request_id is not None:
        headers[REQUEST_ID_HEADER] = resolved_request_id
    if resolved_correlation_id is not None:
        headers[CORRELATION_ID_HEADER] = resolved_correlation_id

    return headers


def merge_correlation_headers(
    headers: Mapping[str, str] | None = None,
    *,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, str]:
    """Merge outbound propagation headers into an existing header mapping without dropping other values."""

    merged_headers = dict(headers or {})
    propagation_headers = build_correlation_headers(
        request_id=request_id,
        correlation_id=correlation_id,
    )
    for name, value in propagation_headers.items():
        merged_headers.setdefault(name, value)

    return merged_headers


def attach_request_context_to_scope(scope: MutableMapping[str, Any], context: RequestContext) -> RequestContext:
    """Attach the canonical request context to the ASGI scope state."""

    state = scope.setdefault("state", {})
    state[REQUEST_CONTEXT_STATE_KEY] = context
    state[REQUEST_ID_STATE_KEY] = context.request_id
    state[CORRELATION_ID_STATE_KEY] = context.correlation_id
    return context


def get_request_context(request: Request) -> RequestContext | None:
    """Return the canonical request context stored on the current request, if available."""

    existing_context = getattr(request.state, REQUEST_CONTEXT_STATE_KEY, None)
    if isinstance(existing_context, RequestContext):
        return existing_context

    request_id = _normalize_header_value(getattr(request.state, REQUEST_ID_STATE_KEY, None))
    correlation_id = _normalize_header_value(getattr(request.state, CORRELATION_ID_STATE_KEY, None))
    if request_id is None or correlation_id is None:
        return None

    return RequestContext(request_id=request_id, correlation_id=correlation_id)


def get_request_id(request: Request) -> str | None:
    """Return the request-scoped request ID, if one has been attached."""

    context = get_request_context(request)
    return None if context is None else context.request_id


def get_correlation_id(request: Request) -> str | None:
    """Return the request-scoped correlation ID, if one has been attached."""

    context = get_request_context(request)
    return None if context is None else context.correlation_id


__all__ = [
    "CORRELATION_ID_HEADER",
    "CORRELATION_ID_STATE_KEY",
    "REQUEST_CONTEXT_STATE_KEY",
    "REQUEST_ID_HEADER",
    "REQUEST_ID_STATE_KEY",
    "RequestContext",
    "attach_request_context_to_scope",
    "build_correlation_headers",
    "build_request_context",
    "get_current_correlation_id",
    "get_current_request_id",
    "get_correlation_id",
    "get_request_context",
    "get_request_id",
    "merge_correlation_headers",
    "resolve_correlation_id",
]
