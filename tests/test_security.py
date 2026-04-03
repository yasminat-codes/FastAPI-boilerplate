from fastapi import Response

from src.app.core.security import (
    build_refresh_token_cookie_delete_kwargs,
    build_refresh_token_cookie_kwargs,
    clear_refresh_token_cookie,
    set_refresh_token_cookie,
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
