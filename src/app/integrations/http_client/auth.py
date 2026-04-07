"""Authentication hooks for outbound HTTP requests.

Provides reusable request hooks that inject authorization credentials
into outbound requests. Integration adapters compose these hooks with
the ``TemplateHttpClient`` to handle provider-specific auth patterns.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)


@runtime_checkable
class TokenProvider(Protocol):
    """Protocol for dynamic token sources (e.g., OAuth refresh, vault lookup)."""

    async def get_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        ...


class BearerTokenAuth:
    """Request hook that adds a static or dynamic Bearer token to outbound requests.

    Usage with static token::

        auth = BearerTokenAuth(token="sk-live-xxx")
        client = TemplateHttpClient(request_hooks=[auth])

    Usage with dynamic token provider::

        auth = BearerTokenAuth(token_provider=my_oauth_provider)
        client = TemplateHttpClient(request_hooks=[auth])
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        token_provider: TokenProvider | None = None,
    ) -> None:
        if token is None and token_provider is None:
            raise ValueError("Either token or token_provider must be provided")
        self._static_token = token
        self._token_provider = token_provider

    async def before_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        content: bytes | None,
    ) -> dict[str, str]:
        """Add Authorization: Bearer <token> header."""
        if self._token_provider is not None:
            token = await self._token_provider.get_token()
        else:
            token = self._static_token or ""

        headers["Authorization"] = f"Bearer {token}"
        return headers


class ApiKeyAuth:
    """Request hook that adds an API key to outbound requests.

    Supports both header-based and query-parameter-based API key injection.

    Usage::

        auth = ApiKeyAuth(key="sk-xxx", header_name="X-Api-Key")
        client = TemplateHttpClient(request_hooks=[auth])
    """

    def __init__(
        self,
        *,
        key: str,
        header_name: str = "X-Api-Key",
    ) -> None:
        self._key = key
        self._header_name = header_name

    async def before_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        content: bytes | None,
    ) -> dict[str, str]:
        """Add the API key header."""
        headers[self._header_name] = self._key
        return headers


class BasicAuth:
    """Request hook that adds HTTP Basic authentication to outbound requests.

    Usage::

        auth = BasicAuth(username="user", password="pass")
        client = TemplateHttpClient(request_hooks=[auth])
    """

    def __init__(self, *, username: str, password: str) -> None:
        import base64

        credentials = f"{username}:{password}"
        self._encoded = base64.b64encode(credentials.encode()).decode()

    async def before_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        content: bytes | None,
    ) -> dict[str, str]:
        """Add Authorization: Basic <encoded> header."""
        headers["Authorization"] = f"Basic {self._encoded}"
        return headers


class CustomAuth:
    """Request hook that delegates authentication to a user-provided callable.

    Usage::

        async def add_hmac(method, url, headers, content):
            headers["X-Signature"] = compute_hmac(content)
            return headers

        auth = CustomAuth(handler=add_hmac)
        client = TemplateHttpClient(request_hooks=[auth])
    """

    def __init__(self, *, handler: Any) -> None:
        self._handler = handler

    async def before_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        content: bytes | None,
    ) -> dict[str, str]:
        """Delegate to the custom handler."""
        result = self._handler(method=method, url=url, headers=headers, content=content)
        if hasattr(result, "__await__"):
            resolved: dict[str, str] = await result
            return resolved
        return dict(result)


__all__ = [
    "ApiKeyAuth",
    "BasicAuth",
    "BearerTokenAuth",
    "CustomAuth",
    "TokenProvider",
]
