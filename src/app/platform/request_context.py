"""Canonical request-context surface."""

from ..core.request_context import (
    CORRELATION_ID_HEADER,
    CORRELATION_ID_STATE_KEY,
    REQUEST_CONTEXT_STATE_KEY,
    REQUEST_ID_HEADER,
    REQUEST_ID_STATE_KEY,
    RequestContext,
    attach_request_context_to_scope,
    build_request_context,
    get_correlation_id,
    get_request_context,
    get_request_id,
)

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
