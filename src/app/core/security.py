"""Template auth primitives: stateless JWT access and refresh tokens with blacklist-based revocation."""

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Literal, cast

import bcrypt
from fastapi import Response
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from ..crud.crud_users import crud_users
from .config import CryptSettings, RefreshTokenCookieSettings, settings
from .db.crud_token_blacklist import crud_token_blacklist
from .schemas import TokenBlacklistCreate, TokenData

SECRET_KEY: SecretStr = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS
JWT_ISSUER = settings.JWT_ISSUER
JWT_AUDIENCE = settings.JWT_AUDIENCE
JWT_ACTIVE_KEY_ID = settings.JWT_ACTIVE_KEY_ID

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login")


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


def build_refresh_token_cookie_kwargs(
    *,
    refresh_token: str,
    max_age: int,
    cookie_settings: RefreshTokenCookieSettings,
) -> dict[str, Any]:
    return {
        "key": cookie_settings.REFRESH_TOKEN_COOKIE_NAME,
        "value": refresh_token,
        "max_age": max_age,
        "path": cookie_settings.REFRESH_TOKEN_COOKIE_PATH,
        "domain": cookie_settings.REFRESH_TOKEN_COOKIE_DOMAIN,
        "secure": cookie_settings.REFRESH_TOKEN_COOKIE_SECURE,
        "httponly": cookie_settings.REFRESH_TOKEN_COOKIE_HTTPONLY,
        "samesite": cookie_settings.REFRESH_TOKEN_COOKIE_SAMESITE.value,
    }


def build_refresh_token_cookie_delete_kwargs(
    *,
    cookie_settings: RefreshTokenCookieSettings,
) -> dict[str, Any]:
    return {
        "key": cookie_settings.REFRESH_TOKEN_COOKIE_NAME,
        "path": cookie_settings.REFRESH_TOKEN_COOKIE_PATH,
        "domain": cookie_settings.REFRESH_TOKEN_COOKIE_DOMAIN,
        "secure": cookie_settings.REFRESH_TOKEN_COOKIE_SECURE,
        "httponly": cookie_settings.REFRESH_TOKEN_COOKIE_HTTPONLY,
        "samesite": cookie_settings.REFRESH_TOKEN_COOKIE_SAMESITE.value,
    }


def set_refresh_token_cookie(
    response: Response,
    *,
    refresh_token: str,
    max_age: int,
    cookie_settings: RefreshTokenCookieSettings,
) -> None:
    response.set_cookie(**build_refresh_token_cookie_kwargs(
        refresh_token=refresh_token,
        max_age=max_age,
        cookie_settings=cookie_settings,
    ))


def clear_refresh_token_cookie(response: Response, *, cookie_settings: RefreshTokenCookieSettings) -> None:
    response.delete_cookie(**build_refresh_token_cookie_delete_kwargs(cookie_settings=cookie_settings))


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    correct_password: bool = bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
    return correct_password


def get_password_hash(password: str) -> str:
    hashed_password: str = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    return hashed_password


async def authenticate_user(username_or_email: str, password: str, db: AsyncSession) -> dict[str, Any] | Literal[False]:
    if "@" in username_or_email:
        db_user = await crud_users.get(db=db, email=username_or_email, is_deleted=False)
    else:
        db_user = await crud_users.get(db=db, username=username_or_email, is_deleted=False)

    if not db_user:
        return False

    if not await verify_password(password, db_user["hashed_password"]):
        return False

    return db_user


def _get_jwt_key_ring(*, crypt_settings: CryptSettings) -> dict[str, SecretStr]:
    return {
        crypt_settings.JWT_ACTIVE_KEY_ID: crypt_settings.SECRET_KEY,
        **crypt_settings.JWT_VERIFICATION_KEYS,
    }


def _build_jwt_decode_kwargs(*, crypt_settings: CryptSettings) -> dict[str, Any]:
    decode_kwargs: dict[str, Any] = {
        "options": {
            "verify_aud": crypt_settings.JWT_AUDIENCE is not None,
            "verify_iss": crypt_settings.JWT_ISSUER is not None,
        }
    }
    if crypt_settings.JWT_AUDIENCE is not None:
        decode_kwargs["audience"] = crypt_settings.JWT_AUDIENCE
    if crypt_settings.JWT_ISSUER is not None:
        decode_kwargs["issuer"] = crypt_settings.JWT_ISSUER
    return decode_kwargs


def _get_jwt_verification_secrets(*, token: str, crypt_settings: CryptSettings) -> list[str]:
    key_ring = _get_jwt_key_ring(crypt_settings=crypt_settings)
    header = jwt.get_unverified_header(token)
    key_id = header.get("kid")
    if key_id is None:
        return [secret.get_secret_value() for secret in key_ring.values()]

    secret = key_ring.get(key_id)
    if secret is None:
        raise JWTError("Unknown JWT key id")

    return [secret.get_secret_value()]


def _decode_token_payload(*, token: str, crypt_settings: CryptSettings) -> dict[str, Any]:
    last_error: JWTError | None = None
    for secret in _get_jwt_verification_secrets(token=token, crypt_settings=crypt_settings):
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=[crypt_settings.ALGORITHM],
                **_build_jwt_decode_kwargs(crypt_settings=crypt_settings),
            )
            return cast(dict[str, Any], payload)
        except JWTError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error

    raise JWTError("No JWT verification keys are configured")


def _build_token_claims(
    *,
    data: dict[str, Any],
    expire: datetime,
    token_type: TokenType,
    crypt_settings: CryptSettings,
) -> dict[str, Any]:
    claims = data.copy()
    claims.update({"exp": expire, "token_type": token_type})
    if crypt_settings.JWT_ISSUER is not None:
        claims["iss"] = crypt_settings.JWT_ISSUER
    if crypt_settings.JWT_AUDIENCE is not None:
        claims["aud"] = crypt_settings.JWT_AUDIENCE
    return claims


async def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
    *,
    crypt_settings: CryptSettings = settings,
) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC).replace(tzinfo=None) + expires_delta
    else:
        expire = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=crypt_settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = _build_token_claims(
        data=to_encode,
        expire=expire,
        token_type=TokenType.ACCESS,
        crypt_settings=crypt_settings,
    )
    encoded_jwt: str = jwt.encode(
        to_encode,
        crypt_settings.SECRET_KEY.get_secret_value(),
        algorithm=crypt_settings.ALGORITHM,
        headers={"kid": crypt_settings.JWT_ACTIVE_KEY_ID},
    )
    return encoded_jwt


async def create_refresh_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
    *,
    crypt_settings: CryptSettings = settings,
) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC).replace(tzinfo=None) + expires_delta
    else:
        expire = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=crypt_settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = _build_token_claims(
        data=to_encode,
        expire=expire,
        token_type=TokenType.REFRESH,
        crypt_settings=crypt_settings,
    )
    encoded_jwt: str = jwt.encode(
        to_encode,
        crypt_settings.SECRET_KEY.get_secret_value(),
        algorithm=crypt_settings.ALGORITHM,
        headers={"kid": crypt_settings.JWT_ACTIVE_KEY_ID},
    )
    return encoded_jwt


async def verify_token(
    token: str,
    expected_token_type: TokenType,
    db: AsyncSession,
    *,
    crypt_settings: CryptSettings = settings,
) -> TokenData | None:
    """Verify a JWT token and return TokenData if valid.

    Parameters
    ----------
    token: str
        The JWT token to be verified.
    expected_token_type: TokenType
        The expected type of token (access or refresh)
    db: AsyncSession
        Database session for performing database operations.

    Returns
    -------
    TokenData | None
        TokenData instance if the token is valid, None otherwise.
    """
    is_blacklisted = await crud_token_blacklist.exists(db, token=token)
    if is_blacklisted:
        return None

    try:
        payload = _decode_token_payload(token=token, crypt_settings=crypt_settings)
        username_or_email: str | None = payload.get("sub")
        token_type: str | None = payload.get("token_type")

        if username_or_email is None or token_type != expected_token_type:
            return None

        return TokenData(username_or_email=username_or_email)

    except JWTError:
        return None


async def blacklist_tokens(
    access_token: str,
    refresh_token: str,
    db: AsyncSession,
    *,
    crypt_settings: CryptSettings = settings,
) -> None:
    """Blacklist both access and refresh tokens.

    Parameters
    ----------
    access_token: str
        The access token to blacklist
    refresh_token: str
        The refresh token to blacklist
    db: AsyncSession
        Database session for performing database operations.
    """
    for token in [access_token, refresh_token]:
        payload = _decode_token_payload(token=token, crypt_settings=crypt_settings)
        exp_timestamp = payload.get("exp")
        if exp_timestamp is not None:
            expires_at = datetime.fromtimestamp(exp_timestamp)
            await crud_token_blacklist.create(db, object=TokenBlacklistCreate(token=token, expires_at=expires_at))


async def blacklist_token(
    token: str,
    db: AsyncSession,
    *,
    crypt_settings: CryptSettings = settings,
) -> None:
    payload = _decode_token_payload(token=token, crypt_settings=crypt_settings)
    exp_timestamp = payload.get("exp")
    if exp_timestamp is not None:
        expires_at = datetime.fromtimestamp(exp_timestamp)
        await crud_token_blacklist.create(db, object=TokenBlacklistCreate(token=token, expires_at=expires_at))
