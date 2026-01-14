"""Unit tests for OAuth functionality."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.app.api.v1.oauth import BaseOAuthProvider, GithubOAuthProvider, GoogleOAuthProvider, MicrosoftOAuthProvider
from src.app.core.exceptions.http_exceptions import UnauthorizedException
from src.app.schemas.user import UserCreateInternal


class MockOpenID:
    """Mock OpenID response from OAuth provider."""

    def __init__(self, email: str, display_name: str | None = None, id: str | None = None):
        self.email = email
        self.display_name = display_name
        self.id = id


class TestOAuthProviderEnabled:
    """Test OAuth provider enabled/disabled logic."""

    def test_github_provider_enabled_with_credentials(self):
        """Test GitHub provider is enabled when credentials are set."""
        with patch("src.app.api.v1.oauth.settings") as mock_settings:
            mock_settings.GITHUB_CLIENT_ID = "test_client_id"
            mock_settings.GITHUB_CLIENT_SECRET = "test_client_secret"
            mock_settings.ENABLE_PASSWORD_AUTH = False

            provider = GithubOAuthProvider.__new__(GithubOAuthProvider)
            provider.provider_config = {
                "client_id": mock_settings.GITHUB_CLIENT_ID,
                "client_secret": mock_settings.GITHUB_CLIENT_SECRET,
            }

            assert provider.is_enabled is True

    def test_github_provider_disabled_without_credentials(self):
        """Test GitHub provider is disabled when credentials are missing."""
        provider = GithubOAuthProvider.__new__(GithubOAuthProvider)
        provider.provider_config = {
            "client_id": "",
            "client_secret": "",
        }

        assert provider.is_enabled is False


class TestUsernameExtraction:
    """Test username extraction from email addresses."""

    @pytest.mark.asyncio
    async def test_extract_username_with_periods(self, mock_db):
        """Test username keeps periods from email."""
        oauth_user = MockOpenID(email="test.user.name@example.com", display_name="Test User")

        provider = GithubOAuthProvider.__new__(GithubOAuthProvider)
        provider.provider_name = "github"

        user_internal = await provider._get_user_details(oauth_user)

        assert user_internal.username == "test.user.name"
        assert user_internal.email == "test.user.name@example.com"
        assert user_internal.hashed_password is None

    @pytest.mark.asyncio
    async def test_extract_username_with_special_chars(self, mock_db):
        """Test username keeps valid email special characters."""
        oauth_user = MockOpenID(
            email="User.Name+Tag-12@example.com",
            display_name="Test User"
        )

        provider = GithubOAuthProvider.__new__(GithubOAuthProvider)
        provider.provider_name = "github"

        user_internal = await provider._get_user_details(oauth_user)

        assert user_internal.username == "user.name+tag-12"
        assert user_internal.hashed_password is None
        assert user_internal.username.islower()
        assert "." in user_internal.username
        assert "+" in user_internal.username
        assert "-" in user_internal.username

    @pytest.mark.asyncio
    async def test_extract_username_lowercase_conversion(self, mock_db):
        """Test username is converted to lowercase."""
        oauth_user = MockOpenID(email="TestUser@example.com", display_name="Test User")

        provider = GithubOAuthProvider.__new__(GithubOAuthProvider)
        provider.provider_name = "github"

        user_internal = await provider._get_user_details(oauth_user)

        assert user_internal.username == "testuser"
        assert user_internal.username.islower()

    @pytest.mark.asyncio
    async def test_extract_common_email_patterns(self, mock_db):
        """Test username extraction with common real-world email patterns."""
        test_cases = [
            ("john.doe@gmail.com", "john.doe"),
            ("jane_smith@outlook.com", "jane_smith"),
            ("user+tag@example.com", "user+tag"),
            ("first-last@company.com", "first-last"),
            ("test.user_name-123@domain.com", "test.user_name-123"),
        ]

        provider = GithubOAuthProvider.__new__(GithubOAuthProvider)
        provider.provider_name = "github"

        for email, expected_username in test_cases:
            oauth_user = MockOpenID(email=email, display_name="Test User")
            user_internal = await provider._get_user_details(oauth_user)
            assert user_internal.username == expected_username, f"Failed for {email}"
            assert user_internal.username.islower()

    @pytest.mark.asyncio
    async def test_extract_username_mixed_case(self, mock_db):
        """Test mixed case email is converted to lowercase username."""
        oauth_user = MockOpenID(
            email="User.Name+Tag@example.com",
            display_name="Test User"
        )

        provider = GithubOAuthProvider.__new__(GithubOAuthProvider)
        provider.provider_name = "github"

        user_internal = await provider._get_user_details(oauth_user)

        assert user_internal.username == "user.name+tag"
        assert user_internal.username.islower()
        assert "." in user_internal.username
        assert "+" in user_internal.username


class TestOAuthCallback:
    """Test OAuth callback handler."""

    @pytest.mark.asyncio
    async def test_callback_creates_new_user(self, mock_db):
        """Test OAuth callback creates new user when email doesn't exist."""
        oauth_user = MockOpenID(email="newuser@example.com", display_name="New User")

        mock_request = Mock()
        mock_response = Mock()

        provider = GithubOAuthProvider.__new__(GithubOAuthProvider)
        provider.provider_name = "github"
        provider.sso_provider = Mock()

        with patch("src.app.api.v1.oauth.crud_users") as mock_crud:
            mock_crud.get = AsyncMock(return_value=None)

            with patch("src.app.api.v1.oauth.write_user_internal") as mock_write:
                mock_write.return_value = {
                    "id": 1,
                    "username": "newuser",
                    "email": "newuser@example.com",
                    "name": "New User",
                }

                with patch("src.app.api.v1.oauth.create_access_token") as mock_access:
                    with patch("src.app.api.v1.oauth.create_refresh_token") as mock_refresh:
                        mock_access.return_value = "access_token"
                        mock_refresh.return_value = "refresh_token"

                        mock_sso = Mock()
                        mock_sso.__aenter__ = AsyncMock(return_value=mock_sso)
                        mock_sso.__aexit__ = AsyncMock(return_value=None)
                        mock_sso.verify_and_process = AsyncMock(return_value=oauth_user)

                        provider.sso = mock_sso

                        result = await provider._callback_handler(mock_request, mock_response, mock_db)

                        assert result["access_token"] == "access_token"
                        assert result["token_type"] == "bearer"
                        mock_write.assert_called_once()

                        call_args = mock_write.call_args
                        user_arg = call_args.kwargs["user"]
                        assert isinstance(user_arg, UserCreateInternal)
                        assert user_arg.hashed_password is None

    @pytest.mark.asyncio
    async def test_callback_existing_user_login(self, mock_db):
        """Test OAuth callback logs in existing user."""
        oauth_user = MockOpenID(email="existing@example.com", display_name="Existing User")

        mock_request = Mock()
        mock_response = Mock()

        provider = GithubOAuthProvider.__new__(GithubOAuthProvider)
        provider.provider_name = "github"

        existing_user = {
            "id": 1,
            "username": "existing",
            "email": "existing@example.com",
            "name": "Existing User",
        }

        with patch("src.app.api.v1.oauth.crud_users") as mock_crud:
            mock_crud.get = AsyncMock(return_value=existing_user)

            with patch("src.app.api.v1.oauth.write_user_internal") as mock_write:
                with patch("src.app.api.v1.oauth.create_access_token") as mock_access:
                    with patch("src.app.api.v1.oauth.create_refresh_token") as mock_refresh:
                        mock_access.return_value = "access_token"
                        mock_refresh.return_value = "refresh_token"

                        mock_sso = Mock()
                        mock_sso.__aenter__ = AsyncMock(return_value=mock_sso)
                        mock_sso.__aexit__ = AsyncMock(return_value=None)
                        mock_sso.verify_and_process = AsyncMock(return_value=oauth_user)

                        provider.sso = mock_sso

                        result = await provider._callback_handler(mock_request, mock_response, mock_db)

                        assert result["access_token"] == "access_token"
                        mock_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_no_email_raises_error(self, mock_db):
        """Test OAuth callback raises error when email is missing."""
        oauth_user = MockOpenID(email=None, display_name="User")

        mock_request = Mock()
        mock_response = Mock()

        provider = GithubOAuthProvider.__new__(GithubOAuthProvider)
        provider.provider_name = "github"

        mock_sso = Mock()
        mock_sso.__aenter__ = AsyncMock(return_value=mock_sso)
        mock_sso.__aexit__ = AsyncMock(return_value=None)
        mock_sso.verify_and_process = AsyncMock(return_value=oauth_user)

        provider.sso = mock_sso

        with pytest.raises(UnauthorizedException, match="Invalid response from Github OAuth"):
            await provider._callback_handler(mock_request, mock_response, mock_db)


class TestOAuthSecurity:
    """Test OAuth security features."""

    @pytest.mark.asyncio
    async def test_oauth_user_has_null_password(self, mock_db):
        """Test OAuth users are created with NULL password."""
        oauth_user = MockOpenID(email="oauth@example.com", display_name="OAuth User")

        provider = GithubOAuthProvider.__new__(GithubOAuthProvider)
        provider.provider_name = "github"

        user_internal = await provider._get_user_details(oauth_user)

        assert user_internal.hashed_password is None

    @pytest.mark.asyncio
    async def test_oauth_user_cannot_password_login(self, mock_db):
        """Test OAuth users cannot login with password authentication."""
        from src.app.core.security import authenticate_user

        oauth_user = {
            "username": "oauthuser",
            "email": "oauth@example.com",
            "hashed_password": None,
        }

        with patch("src.app.core.security.crud_users") as mock_crud:
            mock_crud.get = AsyncMock(return_value=oauth_user)

            result = await authenticate_user(
                username_or_email="oauthuser",
                password="any_password",
                db=mock_db
            )

            assert result is False


class TestMultipleProviders:
    """Test all OAuth providers work consistently."""

    @pytest.mark.asyncio
    async def test_github_provider_extracts_username(self, mock_db):
        """Test GitHub provider extracts usernames correctly."""
        oauth_user = MockOpenID(email="test.user@example.com")

        provider = GithubOAuthProvider.__new__(GithubOAuthProvider)
        provider.provider_name = "github"

        user = await provider._get_user_details(oauth_user)
        assert user.username == "test.user"

    @pytest.mark.asyncio
    async def test_google_provider_extracts_username(self, mock_db):
        """Test Google provider extracts usernames correctly."""
        oauth_user = MockOpenID(email="test.user@example.com")

        provider = GoogleOAuthProvider.__new__(GoogleOAuthProvider)
        provider.provider_name = "google"

        user = await provider._get_user_details(oauth_user)
        assert user.username == "test.user"

    @pytest.mark.asyncio
    async def test_microsoft_provider_extracts_username(self, mock_db):
        """Test Microsoft provider extracts usernames correctly."""
        oauth_user = MockOpenID(email="test.user@example.com")

        provider = MicrosoftOAuthProvider.__new__(MicrosoftOAuthProvider)
        provider.provider_name = "microsoft"

        user = await provider._get_user_details(oauth_user)
        assert user.username == "test.user"
