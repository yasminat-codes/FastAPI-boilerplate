"""Unit tests for the canonical post service authorization paths."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.app.domain.post_service import post_service
from src.app.domain.schemas import PostCreate, PostRead, PostUpdate
from src.app.platform.exceptions import ForbiddenException


@pytest.mark.asyncio
async def test_create_post_rejects_non_owner_without_override_permission(mock_db) -> None:
    current_user = {"id": 7, "username": "other-user"}
    post = PostCreate(title="Hello", text="World")

    with (
        patch("src.app.domain.post_service.user_repository") as user_repository,
        patch("src.app.domain.post_service.post_repository") as post_repository,
    ):
        user_repository.get = AsyncMock(return_value={"id": 1, "username": "template-owner"})
        post_repository.create = AsyncMock()

        with pytest.raises(ForbiddenException):
            await post_service.create_post(
                username="template-owner",
                post=post,
                current_user=current_user,
                db=mock_db,
            )

        post_repository.create.assert_not_called()


@pytest.mark.asyncio
async def test_update_post_allows_admin_role(mock_db) -> None:
    current_user = {"id": 7, "username": "admin", "roles": ["admin"], "is_superuser": False}
    post_update = PostUpdate(title="Updated title")
    post_record = PostRead(
        id=3,
        title="Original title",
        text="Original text",
        media_url=None,
        created_by_user_id=1,
        created_at=datetime.utcnow(),
    ).model_dump()

    with (
        patch("src.app.domain.post_service.user_repository") as user_repository,
        patch("src.app.domain.post_service.post_repository") as post_repository,
    ):
        user_repository.get = AsyncMock(return_value={"id": 1, "username": "template-owner"})
        post_repository.get = AsyncMock(return_value=post_record)
        post_repository.update = AsyncMock(return_value=None)

        result = await post_service.update_post(
            username="template-owner",
            post_id=3,
            values=post_update,
            current_user=current_user,
            db=mock_db,
        )

        assert result == {"message": "Post updated"}
        post_repository.update.assert_called_once_with(db=mock_db, object=post_update, id=3)
