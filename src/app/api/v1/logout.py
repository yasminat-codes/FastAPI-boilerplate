from fastapi import APIRouter, Depends, Request, Response
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import UnauthorizedException
from ...core.security import blacklist_tokens, clear_refresh_token_cookie, oauth2_scheme

router = APIRouter(tags=["login"])


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    access_token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(async_get_db),
) -> dict[str, str]:
    try:
        refresh_token = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
        if not refresh_token:
            raise UnauthorizedException("Refresh token not found")

        await blacklist_tokens(access_token=access_token, refresh_token=refresh_token, db=db)
        clear_refresh_token_cookie(response, cookie_settings=settings)

        return {"message": "Logged out successfully"}

    except JWTError:
        raise UnauthorizedException("Invalid token.")
