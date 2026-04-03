"""Canonical authentication service patterns for API routers."""

from __future__ import annotations

from datetime import timedelta

from fastapi import Response
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from ..platform.config import settings
from ..platform.exceptions import UnauthorizedException
from ..platform.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    TokenType,
    authenticate_user,
    blacklist_tokens,
    clear_refresh_token_cookie,
    create_access_token,
    create_refresh_token,
    set_refresh_token_cookie,
    verify_token,
)


class AuthService:
    """Encapsulate reusable authentication flows for the HTTP layer."""

    async def login(
        self,
        *,
        response: Response,
        username_or_email: str,
        password: str,
        db: AsyncSession,
    ) -> dict[str, str]:
        user = await authenticate_user(username_or_email=username_or_email, password=password, db=db)
        if not user:
            raise UnauthorizedException("Wrong username, email or password.")

        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = await create_access_token(data={"sub": user["username"]}, expires_delta=access_token_expires)

        refresh_token = await create_refresh_token(data={"sub": user["username"]})
        max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60

        set_refresh_token_cookie(
            response,
            refresh_token=refresh_token,
            max_age=max_age,
            cookie_settings=settings,
        )

        return {"access_token": access_token, "token_type": "bearer"}

    async def refresh_access_token(self, *, refresh_token: str | None, db: AsyncSession) -> dict[str, str]:
        if not refresh_token:
            raise UnauthorizedException("Refresh token missing.")

        user_data = await verify_token(refresh_token, TokenType.REFRESH, db)
        if not user_data:
            raise UnauthorizedException("Invalid refresh token.")

        new_access_token = await create_access_token(data={"sub": user_data.username_or_email})
        return {"access_token": new_access_token, "token_type": "bearer"}

    async def logout(
        self,
        *,
        response: Response,
        refresh_token: str | None,
        access_token: str,
        db: AsyncSession,
    ) -> dict[str, str]:
        try:
            if not refresh_token:
                raise UnauthorizedException("Refresh token not found")

            await blacklist_tokens(access_token=access_token, refresh_token=refresh_token, db=db)
            clear_refresh_token_cookie(response, cookie_settings=settings)
            return {"message": "Logged out successfully"}
        except JWTError as exc:
            raise UnauthorizedException("Invalid token.") from exc


auth_service = AuthService()

__all__ = ["AuthService", "auth_service"]
