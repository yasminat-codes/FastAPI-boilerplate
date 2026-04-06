from hashlib import sha256
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.repositories import rate_limit_repository, tier_repository, user_repository
from ..domain.schemas import RateLimitRead, TierRead, sanitize_path
from ..platform.authorization import (
    DEFAULT_PERMISSION_POLICY,
    AuthorizationSubject,
    PermissionPolicy,
    TemplatePermission,
    TemplateRole,
    build_authorization_subject,
    ensure_permissions,
    ensure_roles,
)
from ..platform.config import settings
from ..platform.database import async_get_db
from ..platform.exceptions import RateLimitException, UnauthorizedException
from ..platform.logger import logging
from ..platform.rate_limit import rate_limiter
from ..platform.schemas import TenantContext
from ..platform.security import TokenType, oauth2_scheme, resolve_api_key_principal, verify_token

logger = logging.getLogger(__name__)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict[str, Any]:
    token_data = await verify_token(token, TokenType.ACCESS, db)
    if token_data is None:
        raise UnauthorizedException("User not authenticated.")

    if "@" in token_data.username_or_email:
        user = await user_repository.get(db=db, email=token_data.username_or_email, is_deleted=False)
    else:
        user = await user_repository.get(db=db, username=token_data.username_or_email, is_deleted=False)

    if user:
        return user

    raise UnauthorizedException("User not authenticated.")


async def get_current_principal(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any]:
    api_key = request.headers.get(settings.API_KEY_HEADER_NAME)
    if api_key is not None:
        principal = resolve_api_key_principal(api_key)
        if principal is None:
            raise UnauthorizedException("Invalid API key.")
        return principal

    authorization = request.headers.get("Authorization")
    if authorization:
        token_type, _, token_value = authorization.partition(" ")
        if token_type.lower() != "bearer" or not token_value:
            raise UnauthorizedException("Invalid Authorization header.")
        return await get_current_user(token_value, db=db)

    raise UnauthorizedException("Authentication required.")


async def get_optional_user(request: Request, db: AsyncSession = Depends(async_get_db)) -> dict | None:
    token = request.headers.get("Authorization")
    if not token:
        return None

    try:
        token_type, _, token_value = token.partition(" ")
        if token_type.lower() != "bearer" or not token_value:
            return None

        token_data = await verify_token(token_value, TokenType.ACCESS, db)
        if token_data is None:
            return None

        return await get_current_user(token_value, db=db)

    except HTTPException as http_exc:
        if http_exc.status_code != 401:
            logger.error(f"Unexpected HTTPException in get_optional_user: {http_exc.detail}")
        return None

    except Exception as exc:
        logger.error(f"Unexpected error in get_optional_user: {exc}")
        return None


async def get_current_superuser(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
    ensure_roles(build_authorization_subject(current_user), (TemplateRole.ADMIN,))

    return current_user


async def get_current_authorization_subject(
    current_principal: Annotated[dict[str, Any], Depends(get_current_principal)],
) -> AuthorizationSubject:
    return build_authorization_subject(current_principal)


async def get_current_tenant_context(
    subject: Annotated[AuthorizationSubject, Depends(get_current_authorization_subject)],
) -> TenantContext:
    return subject.tenant_context


def require_roles(
    *roles: str,
    require_all: bool = False,
    policy: PermissionPolicy = DEFAULT_PERMISSION_POLICY,
):
    async def dependency(
        current_principal: Annotated[dict[str, Any], Depends(get_current_principal)],
    ) -> dict[str, Any]:
        ensure_roles(
            build_authorization_subject(current_principal, policy=policy),
            roles,
            require_all=require_all,
        )
        return current_principal

    return dependency


def require_permissions(
    *permissions: str,
    require_all: bool = True,
    policy: PermissionPolicy = DEFAULT_PERMISSION_POLICY,
):
    async def dependency(
        current_principal: Annotated[dict[str, Any], Depends(get_current_principal)],
    ) -> dict[str, Any]:
        ensure_permissions(
            build_authorization_subject(current_principal, policy=policy),
            permissions,
            require_all=require_all,
        )
        return current_principal

    return dependency


def require_admin_access(*, policy: PermissionPolicy = DEFAULT_PERMISSION_POLICY):
    return require_permissions(TemplatePermission.ADMIN_ACCESS, policy=policy)


def require_internal_access(*, policy: PermissionPolicy = DEFAULT_PERMISSION_POLICY):
    return require_permissions(TemplatePermission.INTERNAL_ACCESS, policy=policy)


def _normalize_rate_limit_identity(value: str | None, *, fallback: str) -> str:
    if value is None:
        return fallback

    normalized = "".join(character if character.isalnum() else "-" for character in value.strip().casefold())
    normalized = normalized.strip("-")
    return normalized or fallback


def _resolve_client_rate_limit_identity(request: Request) -> str:
    client_host = request.client.host if request.client is not None else None
    return _normalize_rate_limit_identity(client_host, fallback="unknown-client")


def _fingerprint_rate_limit_credential(value: str | None) -> str:
    normalized = _normalize_rate_limit_identity(value, fallback="anonymous")
    return sha256(normalized.encode("utf-8")).hexdigest()


async def _wait_for_rate_limit_runtime(request: Request) -> None:
    application = request.scope.get("app")
    state = getattr(application, "state", None)
    initialization_complete = getattr(state, "initialization_complete", None)
    if initialization_complete is not None:
        await initialization_complete.wait()


async def _enforce_rate_limit(
    *,
    request: Request,
    db: AsyncSession,
    subject_id: str,
    limit: int,
    period: int,
) -> None:
    await _wait_for_rate_limit_runtime(request)

    is_limited = await rate_limiter.is_rate_limited(
        db=db,
        subject_id=subject_id,
        path=request.url.path,
        limit=limit,
        period=period,
    )
    if is_limited:
        raise RateLimitException("Rate limit exceeded.")


async def rate_limiter_dependency(
    request: Request, db: Annotated[AsyncSession, Depends(async_get_db)], user: dict | None = Depends(get_optional_user)
) -> None:
    if not settings.API_RATE_LIMIT_ENABLED:
        return

    path = sanitize_path(request.url.path)
    if user:
        subject_id = str(user["id"])
        tier = await tier_repository.get(db=db, id=user["tier_id"], schema_to_select=TierRead)
        if tier:
            rate_limit = await rate_limit_repository.get(
                db=db, tier_id=tier["id"], path=path, schema_to_select=RateLimitRead
            )
            if rate_limit:
                limit, period = rate_limit["limit"], rate_limit["period"]
            else:
                logger.warning(
                    f"User {subject_id} with tier '{tier['name']}' has no specific rate limit for path '{path}'. \
                        Applying default rate limit."
                )
                limit, period = settings.DEFAULT_RATE_LIMIT_LIMIT, settings.DEFAULT_RATE_LIMIT_PERIOD
        else:
            logger.warning(f"User {subject_id} has no assigned tier. Applying default rate limit.")
            limit, period = settings.DEFAULT_RATE_LIMIT_LIMIT, settings.DEFAULT_RATE_LIMIT_PERIOD
    else:
        subject_id = _resolve_client_rate_limit_identity(request)
        limit, period = settings.DEFAULT_RATE_LIMIT_LIMIT, settings.DEFAULT_RATE_LIMIT_PERIOD

    await _enforce_rate_limit(
        request=request,
        db=db,
        subject_id=subject_id,
        limit=limit,
        period=period,
    )


async def auth_login_rate_limiter_dependency(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> None:
    if not settings.AUTH_RATE_LIMIT_ENABLED:
        return

    subject_id = (
        f"{_resolve_client_rate_limit_identity(request)}:"
        f"{_fingerprint_rate_limit_credential(form_data.username)}"
    )
    await _enforce_rate_limit(
        request=request,
        db=db,
        subject_id=subject_id,
        limit=settings.AUTH_RATE_LIMIT_LOGIN_LIMIT,
        period=settings.AUTH_RATE_LIMIT_LOGIN_PERIOD,
    )


async def auth_refresh_rate_limiter_dependency(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> None:
    if not settings.AUTH_RATE_LIMIT_ENABLED:
        return

    await _enforce_rate_limit(
        request=request,
        db=db,
        subject_id=_resolve_client_rate_limit_identity(request),
        limit=settings.AUTH_RATE_LIMIT_REFRESH_LIMIT,
        period=settings.AUTH_RATE_LIMIT_REFRESH_PERIOD,
    )


async def auth_logout_rate_limiter_dependency(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    user: dict | None = Depends(get_optional_user),
) -> None:
    if not settings.AUTH_RATE_LIMIT_ENABLED:
        return

    subject_id = str(user["id"]) if user else _resolve_client_rate_limit_identity(request)
    await _enforce_rate_limit(
        request=request,
        db=db,
        subject_id=subject_id,
        limit=settings.AUTH_RATE_LIMIT_LOGOUT_LIMIT,
        period=settings.AUTH_RATE_LIMIT_LOGOUT_PERIOD,
    )


async def webhook_rate_limiter_dependency(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> None:
    if not settings.WEBHOOK_RATE_LIMIT_ENABLED:
        return

    await _enforce_rate_limit(
        request=request,
        db=db,
        subject_id=_resolve_client_rate_limit_identity(request),
        limit=settings.WEBHOOK_RATE_LIMIT_LIMIT,
        period=settings.WEBHOOK_RATE_LIMIT_PERIOD,
    )
