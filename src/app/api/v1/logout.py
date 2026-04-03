from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.contracts import ApiMessageResponse
from ...domain.services import auth_service
from ...platform.config import settings
from ...platform.database import async_get_db
from ...platform.security import oauth2_scheme

router = APIRouter(tags=["auth"])


@router.post("/logout", response_model=ApiMessageResponse)
async def logout(
    request: Request,
    response: Response,
    access_token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(async_get_db),
) -> dict[str, str]:
    refresh_token = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    return await auth_service.logout(response=response, refresh_token=refresh_token, access_token=access_token, db=db)
