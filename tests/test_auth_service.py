from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Response
from jose import JWTError

from src.app.core.schemas import TokenData
from src.app.domain.auth_service import auth_service
from src.app.domain.auth_service import settings as auth_service_settings
from src.app.platform.exceptions import UnauthorizedException


@pytest.mark.asyncio
async def test_refresh_access_token_rotates_refresh_cookie_and_returns_new_access_token(mock_db) -> None:
    response = Response()

    token_data = TokenData(username_or_email="template")
    with (
        patch("src.app.domain.auth_service.verify_token", new=AsyncMock(return_value=token_data)),
        patch(
            "src.app.domain.auth_service.rotate_refresh_token",
            new=AsyncMock(return_value=("new-access-token", "new-refresh-token")),
        ) as rotate_mock,
        patch("src.app.domain.auth_service.set_refresh_token_cookie") as set_cookie_mock,
    ):
        result = await auth_service.refresh_access_token(
            response=response,
            refresh_token="old-refresh-token",
            db=mock_db,
        )

    assert result == {"access_token": "new-access-token", "token_type": "bearer"}
    rotate_mock.assert_awaited_once_with(
        refresh_token="old-refresh-token",
        subject="template",
        db=mock_db,
        crypt_settings=auth_service_settings,
    )
    set_cookie_mock.assert_called_once()
    assert set_cookie_mock.call_args.kwargs["refresh_token"] == "new-refresh-token"


@pytest.mark.asyncio
async def test_refresh_access_token_rejects_invalid_refresh_token(mock_db) -> None:
    with patch("src.app.domain.auth_service.verify_token", new=AsyncMock(return_value=None)):
        with pytest.raises(UnauthorizedException, match="Invalid refresh token."):
            await auth_service.refresh_access_token(
                response=Response(),
                refresh_token="invalid-refresh-token",
                db=mock_db,
            )


@pytest.mark.asyncio
async def test_refresh_access_token_rejects_replayed_refresh_token(mock_db) -> None:
    token_data = TokenData(username_or_email="template")
    with (
        patch("src.app.domain.auth_service.verify_token", new=AsyncMock(return_value=token_data)),
        patch(
            "src.app.domain.auth_service.rotate_refresh_token",
            new=AsyncMock(side_effect=JWTError("already consumed")),
        ),
    ):
        with pytest.raises(UnauthorizedException, match="Invalid refresh token."):
            await auth_service.refresh_access_token(
                response=Response(),
                refresh_token="replayed-refresh-token",
                db=mock_db,
            )
