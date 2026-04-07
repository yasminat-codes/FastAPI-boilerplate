"""HTTP middleware that standardizes request and correlation identifiers."""

from __future__ import annotations

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..core.request_context import (
    RequestContext,
    attach_request_context_to_scope,
    build_request_context,
)

REQUEST_LOG_CONTEXT_KEYS = (
    "request_id",
    "correlation_id",
    "client_host",
    "status_code",
    "path",
    "method",
    "workflow_id",
    "provider_event_id",
)


class RequestContextMiddleware:
    """Bind request context to request state, logs, and response headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_context = build_request_context(Headers(scope=scope))
        attach_request_context_to_scope(scope, request_context)

        client = scope.get("client")
        client_host = None if client is None else client[0]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_context.request_id,
            correlation_id=request_context.correlation_id,
            client_host=client_host,
            status_code=None,
            path=scope.get("path"),
            method=scope.get("method"),
        )

        async def send_with_request_context(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw_headers = message.get("headers")
                if raw_headers is None:
                    raw_headers = []
                    message["headers"] = raw_headers

                headers = MutableHeaders(raw=raw_headers)
                _apply_response_headers(headers, request_context)
                structlog.contextvars.bind_contextvars(status_code=message["status"])

            await send(message)

        try:
            await self.app(scope, receive, send_with_request_context)
        finally:
            structlog.contextvars.clear_contextvars()


def _apply_response_headers(headers: MutableHeaders, request_context: RequestContext) -> None:
    for name, value in request_context.response_headers().items():
        headers[name] = value


LoggerMiddleware = RequestContextMiddleware

__all__ = ["LoggerMiddleware", "REQUEST_LOG_CONTEXT_KEYS", "RequestContextMiddleware"]
