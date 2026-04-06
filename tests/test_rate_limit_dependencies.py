from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from src.app.api.dependencies import (
    auth_login_rate_limiter_dependency,
    auth_refresh_rate_limiter_dependency,
    rate_limiter_dependency,
    webhook_rate_limiter_dependency,
)
from src.app.platform.config import load_settings
from src.app.platform.exceptions import RateLimitException


def _build_request(path: str, *, method: str = "POST", client_host: str = "203.0.113.10") -> Request:
    application = FastAPI()
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "root_path": "",
        "query_string": b"",
        "headers": [],
        "client": (client_host, 44321),
        "server": ("testserver", 443),
        "app": application,
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_api_rate_limiter_dependency_uses_tier_specific_limits_for_authenticated_users() -> None:
    request = _build_request("/api/v1/users", method="GET")
    db = AsyncMock()
    user = {"id": 123, "tier_id": 7}
    custom_settings = load_settings(
        _env_file=None,
        API_RATE_LIMIT_ENABLED=True,
        DEFAULT_RATE_LIMIT_LIMIT=10,
        DEFAULT_RATE_LIMIT_PERIOD=3600,
    )
    limiter = AsyncMock(return_value=False)

    with (
        patch("src.app.api.dependencies.settings", custom_settings),
        patch("src.app.api.dependencies.tier_repository.get", new=AsyncMock(return_value={"id": 7, "name": "pro"})),
        patch(
            "src.app.api.dependencies.rate_limit_repository.get",
            new=AsyncMock(return_value={"limit": 25, "period": 60}),
        ),
        patch("src.app.api.dependencies.rate_limiter.is_rate_limited", new=limiter),
    ):
        await rate_limiter_dependency(request=request, db=db, user=user)

    limiter.assert_awaited_once_with(
        db=db,
        subject_id="123",
        path="/api/v1/users",
        limit=25,
        period=60,
    )


@pytest.mark.asyncio
async def test_api_rate_limiter_dependency_falls_back_to_client_identity_for_anonymous_requests() -> None:
    request = _build_request("/api/v1/posts", method="GET")
    db = AsyncMock()
    custom_settings = load_settings(
        _env_file=None,
        API_RATE_LIMIT_ENABLED=True,
        DEFAULT_RATE_LIMIT_LIMIT=18,
        DEFAULT_RATE_LIMIT_PERIOD=90,
    )
    limiter = AsyncMock(return_value=False)

    with (
        patch("src.app.api.dependencies.settings", custom_settings),
        patch("src.app.api.dependencies.rate_limiter.is_rate_limited", new=limiter),
    ):
        await rate_limiter_dependency(request=request, db=db, user=None)

    limiter.assert_awaited_once_with(
        db=db,
        subject_id="203-0-113-10",
        path="/api/v1/posts",
        limit=18,
        period=90,
    )


@pytest.mark.asyncio
async def test_auth_login_rate_limiter_dependency_hashes_credentials_per_client() -> None:
    request = _build_request("/api/v1/login")
    db = AsyncMock()
    form_data = SimpleNamespace(username="Casey@example.com")
    custom_settings = load_settings(
        _env_file=None,
        AUTH_RATE_LIMIT_ENABLED=True,
        AUTH_RATE_LIMIT_LOGIN_LIMIT=4,
        AUTH_RATE_LIMIT_LOGIN_PERIOD=120,
    )
    limiter = AsyncMock(return_value=False)
    credential_fingerprint = sha256(b"casey-example-com").hexdigest()

    with (
        patch("src.app.api.dependencies.settings", custom_settings),
        patch("src.app.api.dependencies.rate_limiter.is_rate_limited", new=limiter),
    ):
        await auth_login_rate_limiter_dependency(request=request, form_data=form_data, db=db)

    limiter.assert_awaited_once_with(
        db=db,
        subject_id=f"203-0-113-10:{credential_fingerprint}",
        path="/api/v1/login",
        limit=4,
        period=120,
    )


@pytest.mark.asyncio
async def test_auth_refresh_rate_limiter_dependency_uses_refresh_budget() -> None:
    request = _build_request("/api/v1/refresh")
    db = AsyncMock()
    custom_settings = load_settings(
        _env_file=None,
        AUTH_RATE_LIMIT_ENABLED=True,
        AUTH_RATE_LIMIT_REFRESH_LIMIT=12,
        AUTH_RATE_LIMIT_REFRESH_PERIOD=240,
    )
    limiter = AsyncMock(return_value=False)

    with (
        patch("src.app.api.dependencies.settings", custom_settings),
        patch("src.app.api.dependencies.rate_limiter.is_rate_limited", new=limiter),
    ):
        await auth_refresh_rate_limiter_dependency(request=request, db=db)

    limiter.assert_awaited_once_with(
        db=db,
        subject_id="203-0-113-10",
        path="/api/v1/refresh",
        limit=12,
        period=240,
    )


@pytest.mark.asyncio
async def test_webhook_rate_limiter_dependency_raises_when_webhook_budget_is_exceeded() -> None:
    request = _build_request("/api/v1/webhooks/provider")
    db = AsyncMock()
    custom_settings = load_settings(
        _env_file=None,
        WEBHOOK_RATE_LIMIT_ENABLED=True,
        WEBHOOK_RATE_LIMIT_LIMIT=2,
        WEBHOOK_RATE_LIMIT_PERIOD=60,
    )
    limiter = AsyncMock(return_value=True)

    with (
        patch("src.app.api.dependencies.settings", custom_settings),
        patch("src.app.api.dependencies.rate_limiter.is_rate_limited", new=limiter),
        pytest.raises(RateLimitException, match="Rate limit exceeded."),
    ):
        await webhook_rate_limiter_dependency(request=request, db=db)
