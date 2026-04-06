from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.schemas import Token
from ...domain.services import auth_service
from ...platform.config import settings
from ...platform.database import async_get_db

router = APIRouter(tags=["auth"])


@router.post("/login", response_model=Token)
async def login_for_access_token(
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    return await auth_service.login(
        response=response,
        username_or_email=form_data.username,
        password=form_data.password,
        db=db,
    )


@router.post("/refresh", response_model=Token)
async def refresh_access_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(async_get_db),
) -> dict[str, str]:
    refresh_token = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    return await auth_service.refresh_access_token(response=response, refresh_token=refresh_token, db=db)
