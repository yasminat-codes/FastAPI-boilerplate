"""HTTP request-body size enforcement middleware."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..api.errors import build_api_error_response


class PayloadTooLargeError(Exception):
    """Raised when an incoming request body exceeds the configured limit."""


class RequestBodyLimitMiddleware:
    """Reject requests whose bodies exceed the configured byte budget."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int,
        exempt_path_prefixes: list[str] | None = None,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.exempt_path_prefixes = tuple(exempt_path_prefixes or [])

    def _is_exempt(self, scope: Scope) -> bool:
        path = scope.get("path", "")
        return any(path.startswith(prefix) for prefix in self.exempt_path_prefixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._is_exempt(scope):
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_with_tracking(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        if _read_content_length(scope) > self.max_bytes:
            await _send_payload_too_large_response(scope, send_with_tracking, max_bytes=self.max_bytes)
            return

        bytes_received = 0

        async def limited_receive() -> Message:
            nonlocal bytes_received
            message = await receive()
            if message["type"] != "http.request":
                return message

            body = message.get("body", b"")
            bytes_received += len(body)
            if bytes_received > self.max_bytes:
                raise PayloadTooLargeError

            return message

        try:
            await self.app(scope, limited_receive, send_with_tracking)
        except PayloadTooLargeError:
            if response_started:
                raise
            await _send_payload_too_large_response(scope, send_with_tracking, max_bytes=self.max_bytes)


def _read_content_length(scope: Scope) -> int:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() != b"content-length":
            continue
        try:
            return max(int(raw_value.decode("latin1")), 0)
        except ValueError:
            return 0
    return 0


async def _send_payload_too_large_response(scope: Scope, send: Send, *, max_bytes: int) -> None:
    response = build_api_error_response(
        status_code=413,
        code="payload_too_large",
        message=f"Request body exceeds the configured limit of {max_bytes} bytes.",
        headers={"Connection": "close"},
    )
    await response(scope, _empty_receive, send)


async def _empty_receive() -> Message:
    return {"type": "http.disconnect"}


__all__ = ["PayloadTooLargeError", "RequestBodyLimitMiddleware"]
