"""Reusable request and correlation context helpers for HTTP requests."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import Request

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
    "build_request_context",
    "get_correlation_id",
    "get_request_context",
    "get_request_id",
]
