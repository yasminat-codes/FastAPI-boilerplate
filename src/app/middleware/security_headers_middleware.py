from collections.abc import Mapping

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from ..platform.config import SecurityHeadersSettings


def build_security_headers(settings: SecurityHeadersSettings) -> dict[str, str]:
    """Build the configured HTTP security headers for the current runtime."""
    if not settings.SECURITY_HEADERS_ENABLED:
        return {}

    headers: dict[str, str] = {}

    if settings.SECURITY_HEADERS_FRAME_OPTIONS is not None:
        headers["X-Frame-Options"] = settings.SECURITY_HEADERS_FRAME_OPTIONS.value

    if settings.SECURITY_HEADERS_CONTENT_TYPE_OPTIONS:
        headers["X-Content-Type-Options"] = "nosniff"

    if settings.SECURITY_HEADERS_REFERRER_POLICY is not None:
        headers["Referrer-Policy"] = settings.SECURITY_HEADERS_REFERRER_POLICY.value

    if settings.SECURITY_HEADERS_CONTENT_SECURITY_POLICY is not None:
        headers["Content-Security-Policy"] = settings.SECURITY_HEADERS_CONTENT_SECURITY_POLICY

    if settings.SECURITY_HEADERS_PERMISSIONS_POLICY is not None:
        headers["Permissions-Policy"] = settings.SECURITY_HEADERS_PERMISSIONS_POLICY

    if settings.SECURITY_HEADERS_CROSS_ORIGIN_OPENER_POLICY is not None:
        headers["Cross-Origin-Opener-Policy"] = settings.SECURITY_HEADERS_CROSS_ORIGIN_OPENER_POLICY.value

    if settings.SECURITY_HEADERS_CROSS_ORIGIN_RESOURCE_POLICY is not None:
        headers["Cross-Origin-Resource-Policy"] = settings.SECURITY_HEADERS_CROSS_ORIGIN_RESOURCE_POLICY.value

    if settings.SECURITY_HEADERS_HSTS_ENABLED:
        hsts_directives = [f"max-age={settings.SECURITY_HEADERS_HSTS_MAX_AGE_SECONDS}"]
        if settings.SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS:
            hsts_directives.append("includeSubDomains")
        if settings.SECURITY_HEADERS_HSTS_PRELOAD:
            hsts_directives.append("preload")

        headers["Strict-Transport-Security"] = "; ".join(hsts_directives)

    return headers


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply a reusable set of security headers to every HTTP response."""

    def __init__(self, app: FastAPI, headers: Mapping[str, str]) -> None:
        super().__init__(app)
        self.headers = dict(headers)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        for name, value in self.headers.items():
            if name not in response.headers:
                response.headers[name] = value

        return response
