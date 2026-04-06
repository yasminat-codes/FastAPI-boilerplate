"""Unit tests for the canonical user service."""

from unittest.mock import AsyncMock, patch

import pytest

from src.app.domain.schemas import UserCreate, UserRead, UserUpdate
from src.app.domain.user_service import user_service
from src.app.platform.exceptions import DuplicateValueException, ForbiddenException, NotFoundException


class TestWriteUser:
    """Test user creation logic."""

    @pytest.mark.asyncio
    async def test_create_user_success(self, mock_db, sample_user_data, sample_user_read):
        """Test successful user creation."""
        user_create = UserCreate(**sample_user_data)

        with patch("src.app.domain.user_service.user_repository") as mock_repository:
            # Mock that email and username don't exist
            mock_repository.exists = AsyncMock(side_effect=[False, False])  # email, then username
            mock_repository.create = AsyncMock(return_value=sample_user_read.model_dump())

            with patch("src.app.domain.user_service.get_password_hash") as mock_hash:
                mock_hash.return_value = "hashed_password"

                result = await user_service.create_user(user=user_create, db=mock_db)

                assert result == sample_user_read.model_dump()
                mock_repository.exists.assert_any_call(db=mock_db, email=user_create.email)
                mock_repository.exists.assert_any_call(db=mock_db, username=user_create.username)
                mock_repository.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_user_duplicate_email(self, mock_db, sample_user_data):
        """Test user creation with duplicate email."""
        user_create = UserCreate(**sample_user_data)

        with patch("src.app.domain.user_service.user_repository") as mock_repository:
            # Mock that email already exists
            mock_repository.exists = AsyncMock(return_value=True)

            with pytest.raises(DuplicateValueException, match="Email is already registered"):
                await user_service.create_user(user=user_create, db=mock_db)

    @pytest.mark.asyncio
    async def test_create_user_duplicate_username(self, mock_db, sample_user_data):
        """Test user creation with duplicate username."""
        user_create = UserCreate(**sample_user_data)

        with patch("src.app.domain.user_service.user_repository") as mock_repository:
            # Mock email doesn't exist, but username does
            mock_repository.exists = AsyncMock(side_effect=[False, True])

            with pytest.raises(DuplicateValueException, match="Username not available"):
                await user_service.create_user(user=user_create, db=mock_db)


class TestReadUser:
    """Test user retrieval logic."""

    @pytest.mark.asyncio
    async def test_read_user_success(self, mock_db, sample_user_read):
        """Test successful user retrieval."""
        username = "test_user"

        with patch("src.app.domain.user_service.user_repository") as mock_repository:
            user_dict = sample_user_read.model_dump()
            mock_repository.get = AsyncMock(return_value=user_dict)

            result = await user_service.get_user(username=username, db=mock_db)

            assert result == user_dict
            mock_repository.get.assert_called_once_with(
                db=mock_db, username=username, is_deleted=False, schema_to_select=UserRead
            )

    @pytest.mark.asyncio
    async def test_read_user_not_found(self, mock_db):
        """Test user retrieval when user doesn't exist."""
        username = "nonexistent_user"

        with patch("src.app.domain.user_service.user_repository") as mock_repository:
            mock_repository.get = AsyncMock(return_value=None)

            with pytest.raises(NotFoundException, match="User not found"):
                await user_service.get_user(username=username, db=mock_db)


class TestReadUsers:
    """Test users list logic."""

    @pytest.mark.asyncio
    async def test_read_users_success(self, mock_db):
        """Test successful users list retrieval."""
        mock_users_data = {"data": [{"id": 1}, {"id": 2}], "count": 2}

        with patch("src.app.domain.user_service.user_repository") as mock_repository:
            mock_repository.get_multi = AsyncMock(return_value=mock_users_data)

            result = await user_service.list_users(
                db=mock_db,
                offset=10,
                limit=10,
                filters={"is_superuser": True},
                sort_columns="created_at",
                sort_orders="desc",
            )

            assert result == mock_users_data
            mock_repository.get_multi.assert_called_once_with(
                db=mock_db,
                offset=10,
                limit=10,
                sort_columns="created_at",
                sort_orders="desc",
                is_deleted=False,
                is_superuser=True,
            )


class TestPatchUser:
    """Test user update logic."""

    @pytest.mark.asyncio
    async def test_patch_user_success(self, mock_db, current_user_dict, sample_user_read):
        """Test successful user update."""
        username = current_user_dict["username"]
        user_update = UserUpdate(name="New Name")

        user_dict = sample_user_read.model_dump()
        user_dict["username"] = username

        with patch("src.app.domain.user_service.user_repository") as mock_repository:
            mock_repository.get = AsyncMock(return_value=user_dict)
            mock_repository.exists = AsyncMock(return_value=False)
            mock_repository.update = AsyncMock(return_value=None)

            result = await user_service.update_user(
                username=username,
                values=user_update,
                current_user=current_user_dict,
                db=mock_db,
            )

            assert result == {"message": "User updated"}
            mock_repository.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_patch_user_forbidden(self, mock_db, current_user_dict, sample_user_read):
        """Test user update when user tries to update another user."""
        username = "different_user"
        user_update = UserUpdate(name="New Name")
        user_dict = sample_user_read.model_dump()
        user_dict["username"] = username

        with patch("src.app.domain.user_service.user_repository") as mock_repository:
            mock_repository.get = AsyncMock(return_value=user_dict)

            with pytest.raises(ForbiddenException):
                await user_service.update_user(
                    username=username,
                    values=user_update,
                    current_user=current_user_dict,
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_patch_user_allows_admin_role(self, mock_db, sample_user_read):
        """Test user update when the actor has template admin permissions."""
        username = "different_user"
        user_update = UserUpdate(name="Managed Name")
        user_dict = sample_user_read.model_dump()
        user_dict["username"] = username
        admin_user = {
            "id": 999,
            "username": "admin",
            "email": "admin@example.com",
            "roles": ["admin"],
            "is_superuser": False,
        }

        with patch("src.app.domain.user_service.user_repository") as mock_repository:
            mock_repository.get = AsyncMock(return_value=user_dict)
            mock_repository.update = AsyncMock(return_value=None)

            result = await user_service.update_user(
                username=username,
                values=user_update,
                current_user=admin_user,
                db=mock_db,
            )

            assert result == {"message": "User updated"}
            mock_repository.update.assert_called_once_with(db=mock_db, object=user_update, username=username)


class TestEraseUser:
    """Test user deletion logic."""

    @pytest.mark.asyncio
    async def test_erase_user_success(self, mock_db, current_user_dict, sample_user_read):
        """Test successful user deletion."""
        username = current_user_dict["username"]
        sample_user_read.username = username
        token = "mock_token"

        with patch("src.app.domain.user_service.user_repository") as mock_repository:
            mock_repository.get = AsyncMock(return_value=sample_user_read)
            mock_repository.delete = AsyncMock(return_value=None)

            with patch("src.app.domain.user_service.blacklist_token", new_callable=AsyncMock) as mock_blacklist:
                result = await user_service.delete_user(
                    username=username,
                    current_user=current_user_dict,
                    db=mock_db,
                    token=token,
                )

                assert result == {"message": "User deleted"}
                mock_repository.delete.assert_called_once_with(db=mock_db, username=username)
                mock_blacklist.assert_called_once_with(token=token, db=mock_db)

    @pytest.mark.asyncio
    async def test_erase_user_not_found(self, mock_db, current_user_dict):
        """Test user deletion when user doesn't exist."""
        username = "nonexistent_user"
        token = "mock_token"

        with patch("src.app.domain.user_service.user_repository") as mock_repository:
            mock_repository.get = AsyncMock(return_value=None)

            with pytest.raises(NotFoundException, match="User not found"):
                await user_service.delete_user(
                    username=username,
                    current_user=current_user_dict,
                    db=mock_db,
                    token=token,
                )

    @pytest.mark.asyncio
    async def test_erase_user_forbidden(self, mock_db, current_user_dict, sample_user_read):
        """Test user deletion when user tries to delete another user."""
        username = "different_user"
        sample_user_read.username = username
        token = "mock_token"

        with patch("src.app.domain.user_service.user_repository") as mock_repository:
            mock_repository.get = AsyncMock(return_value=sample_user_read)

            with pytest.raises(ForbiddenException):
                await user_service.delete_user(
                    username=username,
                    current_user=current_user_dict,
                    db=mock_db,
                    token=token,
                )
