from typing import cast
from unittest.mock import AsyncMock, patch

import bcrypt
import pytest
from fastapi import Response
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.security import (
    ALGORITHM,
    SECRET_KEY,
    TokenType,
    authenticate_user,
    build_refresh_token_cookie_delete_kwargs,
    build_refresh_token_cookie_kwargs,
    clear_refresh_token_cookie,
    create_access_token,
    create_refresh_token,
    get_password_hash,
    password_hash_needs_rehash,
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
    assert isinstance(refresh_payload["jti"], str)
    assert refresh_payload["jti"]


@pytest.mark.asyncio
async def test_refresh_tokens_are_unique_across_rotations() -> None:
    first_refresh_token = await create_refresh_token(data={"sub": "template-user"})
    second_refresh_token = await create_refresh_token(data={"sub": "template-user"})

    first_payload = jwt.decode(first_refresh_token, SECRET_KEY.get_secret_value(), algorithms=[ALGORITHM])
    second_payload = jwt.decode(second_refresh_token, SECRET_KEY.get_secret_value(), algorithms=[ALGORITHM])

    assert first_refresh_token != second_refresh_token
    assert first_payload["jti"] != second_payload["jti"]


@pytest.mark.asyncio
async def test_tokens_embed_configured_issuer_audience_and_key_id() -> None:
    custom_settings = load_settings(
        _env_file=None,
        SECRET_KEY="a" * 64,
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="template-api",
        JWT_ACTIVE_KEY_ID="2026-04",
    )

    access_token = await create_access_token(data={"sub": "template-user"}, crypt_settings=custom_settings)

    access_header = jwt.get_unverified_header(access_token)
    access_payload = jwt.decode(
        access_token,
        custom_settings.SECRET_KEY.get_secret_value(),
        algorithms=[custom_settings.ALGORITHM],
        audience=custom_settings.JWT_AUDIENCE,
        issuer=custom_settings.JWT_ISSUER,
    )

    assert access_header["kid"] == "2026-04"
    assert access_payload["iss"] == "https://auth.example.com"
    assert access_payload["aud"] == "template-api"


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
async def test_verify_token_enforces_configured_issuer_and_audience() -> None:
    custom_settings = load_settings(
        _env_file=None,
        SECRET_KEY="a" * 64,
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="template-api",
        JWT_ACTIVE_KEY_ID="2026-04",
    )
    access_token = await create_access_token(data={"sub": "template-user"}, crypt_settings=custom_settings)

    with patch("src.app.core.security.crud_token_blacklist.exists", new=AsyncMock(return_value=False)):
        verified = await verify_token(
            access_token,
            TokenType.ACCESS,
            cast(AsyncSession, object()),
            crypt_settings=custom_settings,
        )
        wrong_audience = await verify_token(
            access_token,
            TokenType.ACCESS,
            cast(AsyncSession, object()),
            crypt_settings=load_settings(
                _env_file=None,
                SECRET_KEY="a" * 64,
                JWT_ISSUER="https://auth.example.com",
                JWT_AUDIENCE="different-audience",
                JWT_ACTIVE_KEY_ID="2026-04",
            ),
        )
        wrong_issuer = await verify_token(
            access_token,
            TokenType.ACCESS,
            cast(AsyncSession, object()),
            crypt_settings=load_settings(
                _env_file=None,
                SECRET_KEY="a" * 64,
                JWT_ISSUER="https://different.example.com",
                JWT_AUDIENCE="template-api",
                JWT_ACTIVE_KEY_ID="2026-04",
            ),
        )

    assert verified is not None
    assert wrong_audience is None
    assert wrong_issuer is None


@pytest.mark.asyncio
async def test_verify_token_accepts_legacy_key_ids_from_rotation_ring() -> None:
    current_settings = load_settings(
        _env_file=None,
        SECRET_KEY="a" * 64,
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="template-api",
        JWT_ACTIVE_KEY_ID="2026-04",
        JWT_VERIFICATION_KEYS={"2026-01": "b" * 64},
    )
    legacy_settings = load_settings(
        _env_file=None,
        SECRET_KEY="b" * 64,
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="template-api",
        JWT_ACTIVE_KEY_ID="2026-01",
    )
    legacy_access_token = await create_access_token(data={"sub": "template-user"}, crypt_settings=legacy_settings)

    with patch("src.app.core.security.crud_token_blacklist.exists", new=AsyncMock(return_value=False)):
        token_data = await verify_token(
            legacy_access_token,
            TokenType.ACCESS,
            cast(AsyncSession, object()),
            crypt_settings=current_settings,
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


def test_get_password_hash_uses_configured_bcrypt_rounds() -> None:
    custom_settings = load_settings(
        _env_file=None,
        SECRET_KEY="a" * 64,
        PASSWORD_BCRYPT_ROUNDS=13,
    )

    hashed_password = get_password_hash("template-password", crypt_settings=custom_settings)

    assert hashed_password.startswith("$2b$13$")


def test_password_hash_needs_rehash_for_lower_bcrypt_rounds() -> None:
    custom_settings = load_settings(
        _env_file=None,
        SECRET_KEY="a" * 64,
        PASSWORD_BCRYPT_ROUNDS=13,
    )
    legacy_hash = bcrypt.hashpw(b"template-password", bcrypt.gensalt(rounds=12)).decode()

    assert password_hash_needs_rehash(legacy_hash, crypt_settings=custom_settings) is True
    assert password_hash_needs_rehash(
        get_password_hash("template-password", crypt_settings=custom_settings),
        crypt_settings=custom_settings,
    ) is False


@pytest.mark.asyncio
async def test_authenticate_user_rehashes_legacy_password_hashes() -> None:
    custom_settings = load_settings(
        _env_file=None,
        SECRET_KEY="a" * 64,
        PASSWORD_BCRYPT_ROUNDS=13,
        PASSWORD_HASH_REHASH_ON_LOGIN=True,
    )
    legacy_hash = bcrypt.hashpw(b"template-password", bcrypt.gensalt(rounds=12)).decode()
    db_user = {
        "username": "template-user",
        "email": "template@example.com",
        "hashed_password": legacy_hash,
    }

    with (
        patch("src.app.core.security.crud_users.get", new=AsyncMock(return_value=db_user)),
        patch("src.app.core.security.crud_users.update", new=AsyncMock()) as update_mock,
    ):
        authenticated_user = await authenticate_user(
            "template-user",
            "template-password",
            cast(AsyncSession, object()),
            crypt_settings=custom_settings,
        )

    assert authenticated_user is not False
    assert authenticated_user["hashed_password"].startswith("$2b$13$")
    update_mock.assert_awaited_once()
