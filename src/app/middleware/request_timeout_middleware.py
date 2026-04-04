"""HTTP request-timeout middleware."""

from __future__ import annotations

import asyncio

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..api.errors import build_api_error_response


class RequestTimeoutMiddleware:
    """Abort long-running HTTP requests with a consistent API error payload."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        timeout_seconds: float,
        exempt_path_prefixes: list[str] | None = None,
    ) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds
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

        try:
            async with asyncio.timeout(self.timeout_seconds):
                await self.app(scope, receive, send_with_tracking)
        except TimeoutError:
            if response_started:
                raise

            response = build_api_error_response(
                status_code=504,
                code="request_timeout",
                message="Request processing exceeded the configured timeout.",
                headers={"Connection": "close"},
            )
            await response(scope, _empty_receive, send_with_tracking)


async def _empty_receive() -> Message:
    return {"type": "http.disconnect"}


__all__ = ["RequestTimeoutMiddleware"]
