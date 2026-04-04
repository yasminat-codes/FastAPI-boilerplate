from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Response
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.security import (
    ALGORITHM,
    SECRET_KEY,
    TokenType,
    build_refresh_token_cookie_delete_kwargs,
    build_refresh_token_cookie_kwargs,
    clear_refresh_token_cookie,
    create_access_token,
    create_refresh_token,
    set_refresh_token_cookie,
    verify_token,
)
from src.app.platform.config import load_settings


def test_build_refresh_token_cookie_kwargs_use_runtime_settings() -> None:
    custom_settings = load_settings(
        _env_file=None,
        REFRESH_TOKEN_COOKIE_NAME="template_refresh",
        REFRESH_TOKEN_COOKIE_PATH="/auth",
        REFRESH_TOKEN_COOKIE_DOMAIN="auth.example.com",
        REFRESH_TOKEN_COOKIE_SECURE=True,
        REFRESH_TOKEN_COOKIE_HTTPONLY=False,
        REFRESH_TOKEN_COOKIE_SAMESITE="strict",
    )

    kwargs = build_refresh_token_cookie_kwargs(
        refresh_token="refresh-token-value",
        max_age=900,
        cookie_settings=custom_settings,
    )

    assert kwargs == {
        "key": "template_refresh",
        "value": "refresh-token-value",
        "max_age": 900,
        "path": "/auth",
        "domain": "auth.example.com",
        "secure": True,
        "httponly": False,
        "samesite": "strict",
    }


def test_build_refresh_token_cookie_delete_kwargs_use_runtime_settings() -> None:
    custom_settings = load_settings(
        _env_file=None,
        REFRESH_TOKEN_COOKIE_NAME="template_refresh",
        REFRESH_TOKEN_COOKIE_PATH="/auth",
        REFRESH_TOKEN_COOKIE_DOMAIN="auth.example.com",
        REFRESH_TOKEN_COOKIE_SECURE=True,
        REFRESH_TOKEN_COOKIE_HTTPONLY=False,
        REFRESH_TOKEN_COOKIE_SAMESITE="strict",
    )

    kwargs = build_refresh_token_cookie_delete_kwargs(cookie_settings=custom_settings)

    assert kwargs == {
        "key": "template_refresh",
        "path": "/auth",
        "domain": "auth.example.com",
        "secure": True,
        "httponly": False,
        "samesite": "strict",
    }


def test_refresh_token_cookie_helpers_apply_runtime_settings_to_response_headers() -> None:
    custom_settings = load_settings(
        _env_file=None,
        REFRESH_TOKEN_COOKIE_NAME="template_refresh",
        REFRESH_TOKEN_COOKIE_PATH="/auth",
        REFRESH_TOKEN_COOKIE_DOMAIN="auth.example.com",
        REFRESH_TOKEN_COOKIE_SECURE=True,
        REFRESH_TOKEN_COOKIE_HTTPONLY=True,
        REFRESH_TOKEN_COOKIE_SAMESITE="none",
    )

    set_response = Response()
    set_refresh_token_cookie(
        set_response,
        refresh_token="refresh-token-value",
        max_age=900,
        cookie_settings=custom_settings,
    )

    set_cookie_header = set_response.headers["set-cookie"]
    assert "template_refresh=refresh-token-value" in set_cookie_header
    assert "Domain=auth.example.com" in set_cookie_header
    assert "HttpOnly" in set_cookie_header
    assert "Max-Age=900" in set_cookie_header
    assert "Path=/auth" in set_cookie_header
    assert "SameSite=none" in set_cookie_header
    assert "Secure" in set_cookie_header

    clear_response = Response()
    clear_refresh_token_cookie(clear_response, cookie_settings=custom_settings)

    clear_cookie_header = clear_response.headers["set-cookie"]
    assert "template_refresh=" in clear_cookie_header
    assert "Domain=auth.example.com" in clear_cookie_header
    assert "Max-Age=0" in clear_cookie_header
    assert "Path=/auth" in clear_cookie_header
    assert "SameSite=none" in clear_cookie_header
    assert "Secure" in clear_cookie_header


@pytest.mark.asyncio
async def test_stateless_tokens_embed_subject_and_type_claims() -> None:
    access_token = await create_access_token(data={"sub": "template-user"})
    refresh_token = await create_refresh_token(data={"sub": "template-user"})

    access_payload = jwt.decode(access_token, SECRET_KEY.get_secret_value(), algorithms=[ALGORITHM])
    refresh_payload = jwt.decode(refresh_token, SECRET_KEY.get_secret_value(), algorithms=[ALGORITHM])

    assert access_payload["sub"] == "template-user"
    assert access_payload["token_type"] == TokenType.ACCESS
    assert refresh_payload["sub"] == "template-user"
    assert refresh_payload["token_type"] == TokenType.REFRESH


@pytest.mark.asyncio
async def test_verify_token_accepts_matching_token_type() -> None:
    access_token = await create_access_token(data={"sub": "template-user"})

    with patch("src.app.core.security.crud_token_blacklist.exists", new=AsyncMock(return_value=False)):
        token_data = await verify_token(
            access_token,
            TokenType.ACCESS,
            cast(AsyncSession, object()),
        )

    assert token_data is not None
    assert token_data.username_or_email == "template-user"


@pytest.mark.asyncio
async def test_verify_token_rejects_mismatched_or_blacklisted_tokens() -> None:
    access_token = await create_access_token(data={"sub": "template-user"})

    with patch("src.app.core.security.crud_token_blacklist.exists", new=AsyncMock(return_value=False)):
        mismatched = await verify_token(
            access_token,
            TokenType.REFRESH,
            cast(AsyncSession, object()),
        )

    with patch("src.app.core.security.crud_token_blacklist.exists", new=AsyncMock(return_value=True)):
        blacklisted = await verify_token(
            access_token,
            TokenType.ACCESS,
            cast(AsyncSession, object()),
        )

    assert mismatched is None
    assert blacklisted is None
