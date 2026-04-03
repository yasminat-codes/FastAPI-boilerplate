"""Canonical request-context surface."""

from ..core.request_context import (
    CORRELATION_ID_HEADER,
    CORRELATION_ID_STATE_KEY,
    REQUEST_CONTEXT_STATE_KEY,
    REQUEST_ID_HEADER,
    REQUEST_ID_STATE_KEY,
    RequestContext,
    attach_request_context_to_scope,
    build_correlation_headers,
    build_request_context,
    get_correlation_id,
    get_current_correlation_id,
    get_current_request_id,
    get_request_context,
    get_request_id,
    merge_correlation_headers,
    resolve_correlation_id,
)

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
