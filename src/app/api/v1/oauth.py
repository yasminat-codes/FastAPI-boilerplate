import logging
from abc import ABC
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from fastapi_sso.sso.base import OpenID, SSOBase
from fastapi_sso.sso.github import GithubSSO
from fastapi_sso.sso.google import GoogleSSO
from fastapi_sso.sso.microsoft import MicrosoftSSO
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import UnauthorizedException
from ...core.security import (
    create_access_token,
    create_refresh_token,
)
from ...crud.crud_users import crud_users
from ...schemas.user import UserCreateInternal, UserRead
from .users import write_user_internal

router = APIRouter(tags=["login", "oauth"])
logger = logging.getLogger(__name__)


class BaseOAuthProvider(ABC):
    provider_config: dict[str, Any]
    sso_provider: type[SSOBase]

    def __init__(self, router: Any):
        self.router = router
        self.provider_name: str = self.sso_provider.provider
        if self.is_enabled:
            self.sso = self.sso_provider(redirect_uri=self.redirect_uri, **self.provider_config)
            tag = f"{self.sso_provider.provider.title()} OAuth"
            self.router.add_api_route(
                f"/login/{self.provider_name}",
                self._login_handler,
                methods=["GET"],
                tags=[tag],
                summary=f"Login with {self.provider_name.title()} OAuth",
            )
            self.router.add_api_route(
                f"/callback/{self.provider_name}",
                self._callback_handler,
                methods=["GET"],
                tags=[tag],
                summary=f"Callback for {self.provider_name.title()} OAuth",
            )

    @property
    def redirect_uri(self) -> str:
        return f"{settings.APP_BACKEND_HOST}/api/v1/callback/{self.provider_name}"

    @property
    def is_enabled(self) -> bool:
        is_enabled = all(self.provider_config.values())
        if settings.ENABLE_PASSWORD_AUTH and is_enabled:
            logger.warning(
                f"Both password authentication and {self.provider_name} OAuth are enabled. "
                "For enterprise or B2B deployments, it is recommended to disable password authentication "
                "by setting ENABLE_PASSWORD_AUTH=false and relying solely on OAuth."
            )
        return is_enabled

    async def _create_and_set_token(self, response: Response, user: dict[str, Any]) -> str:
        access_token = await create_access_token(data={"sub": user["username"]})
        refresh_token = await create_refresh_token(data={"sub": user["username"]})
        max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        response.set_cookie(
            key="refresh_token", value=refresh_token, httponly=True, secure=True, samesite="lax", max_age=max_age
        )
        return access_token

    async def _login_handler(self) -> RedirectResponse:
        async with self.sso:
            return await self.sso.get_login_redirect()

    async def _callback_handler(self, request: Request, response: Response, db: AsyncSession = Depends(async_get_db)):
        async with self.sso:
            oauth_user: OpenID | None = await self.sso.verify_and_process(request)
        if not oauth_user or not oauth_user.email:
            raise UnauthorizedException(f"Invalid response from {self.provider_name.title()} OAuth.")

        db_user = await crud_users.get(db=db, email=oauth_user.email, is_deleted=False, schema_to_select=UserRead)
        if not db_user:
            user = await self._get_user_details(oauth_user)
            db_user = await write_user_internal(user=user, db=db)

        access_token = await self._create_and_set_token(response, db_user)
        return {"access_token": access_token, "token_type": "bearer"}

    async def _get_user_details(self, oauth_user: OpenID) -> UserCreateInternal:
        if not oauth_user.email:
            raise UnauthorizedException(f"Invalid response from {self.provider_name.title()} OAuth.")
        username = oauth_user.email.split("@")[0].lower()
        name = oauth_user.display_name or username

        return UserCreateInternal(
            email=oauth_user.email,
            name=name,
            username=username,
            hashed_password=None,
        )


class GoogleOAuthProvider(BaseOAuthProvider):
    sso_provider = GoogleSSO
    provider_config = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
    }


class MicrosoftOAuthProvider(BaseOAuthProvider):
    sso_provider = MicrosoftSSO
    provider_config = {
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "client_secret": settings.MICROSOFT_CLIENT_SECRET,
        "tenant": settings.MICROSOFT_TENANT,
    }


class GithubOAuthProvider(BaseOAuthProvider):
    sso_provider = GithubSSO
    provider_config = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "client_secret": settings.GITHUB_CLIENT_SECRET,
    }


GoogleOAuthProvider(router)
MicrosoftOAuthProvider(router)
GithubOAuthProvider(router)
