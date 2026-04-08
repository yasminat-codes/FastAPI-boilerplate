"""Integration tests for auth and authorization flows.

End-to-end testing of:
- Token lifecycle (create -> verify -> refresh -> blacklist)
- JWT claims (issuer, audience, key rotation)
- Password hashing and verification
- Authorization flows (role-based permissions)
- API key authentication
- Mixed auth (Bearer + API key)
- Refresh token rotation
- Permission hierarchy
- Tenant/org context propagation
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import bcrypt
import pytest
from jose import JWTError, jwt
from pydantic import SecretStr

from src.app.core.schemas import TokenBlacklistCreate
from src.app.core.security import (
    TokenType,
    authenticate_user,
    blacklist_tokens,
    build_api_key_auth_headers,
    create_access_token,
    create_refresh_token,
    get_password_hash,
    password_hash_needs_rehash,
    resolve_api_key_principal,
    rotate_refresh_token,
    verify_password,
    verify_token,
)
from src.app.platform.authorization import (
    ADMIN_ROLE,
    AUTHENTICATED_ROLE,
    DEFAULT_PERMISSION_POLICY,
    Permission,
    TemplateRole,
    build_authorization_subject,
    ensure_permissions,
    ensure_roles,
    has_permission,
)
from src.app.platform.config import APIKeyPrincipalSettings, load_settings
from src.app.platform.exceptions import ForbiddenException


@pytest.fixture(autouse=True)
def _patch_crud_blacklist():
    """Patch crud_token_blacklist.exists to return False for all token verification calls."""
    with patch("src.app.core.security.crud_token_blacklist") as mock_crud:
        mock_crud.exists = AsyncMock(return_value=False)
        mock_crud.create = AsyncMock(return_value=None)
        yield mock_crud


class TestTokenLifecycle:
    """Test complete token lifecycle: create -> verify -> refresh -> blacklist."""

    @pytest.mark.asyncio
    async def test_access_token_creation_and_verification(self, mock_db):
        """Access token is created with correct claims and verifies successfully."""
        subject = "testuser"
        access_token = await create_access_token(data={"sub": subject})

        assert access_token is not None
        assert isinstance(access_token, str)

        token_data = await verify_token(access_token, TokenType.ACCESS, mock_db)
        assert token_data is not None
        assert token_data.username_or_email == subject

    @pytest.mark.asyncio
    async def test_refresh_token_creation_and_verification(self, mock_db):
        """Refresh token is created with jti claim and verifies successfully."""
        subject = "testuser"
        refresh_token = await create_refresh_token(data={"sub": subject})

        assert refresh_token is not None
        assert isinstance(refresh_token, str)

        token_data = await verify_token(refresh_token, TokenType.REFRESH, mock_db)
        assert token_data is not None
        assert token_data.username_or_email == subject

    @pytest.mark.asyncio
    async def test_token_type_validation_rejects_mismatched_types(self, mock_db):
        """Verifying access token as refresh (or vice versa) returns None."""
        subject = "testuser"
        access_token = await create_access_token(data={"sub": subject})
        refresh_token = await create_refresh_token(data={"sub": subject})

        access_as_refresh = await verify_token(access_token, TokenType.REFRESH, mock_db)
        assert access_as_refresh is None

        refresh_as_access = await verify_token(refresh_token, TokenType.ACCESS, mock_db)
        assert refresh_as_access is None

    @pytest.mark.asyncio
    async def test_blacklisted_token_fails_verification(self, mock_db, _patch_crud_blacklist):
        """Blacklisted token cannot be verified, even if structurally valid."""
        subject = "testuser"
        access_token = await create_access_token(data={"sub": subject})

        # Mark the token as blacklisted by having exists return True
        _patch_crud_blacklist.exists = AsyncMock(return_value=True)
        token_data = await verify_token(access_token, TokenType.ACCESS, mock_db)
        assert token_data is None

    @pytest.mark.asyncio
    async def test_refresh_token_rotation_blacklists_old_token(self, mock_db):
        """Old refresh token is blacklisted when rotating."""
        subject = "testuser"
        old_refresh = await create_refresh_token(data={"sub": subject})

        with patch("src.app.core.security.blacklist_token", new=AsyncMock()) as mock_blacklist:
            new_access, new_refresh = await rotate_refresh_token(
                refresh_token=old_refresh,
                subject=subject,
                db=mock_db,
            )

        assert new_access is not None
        assert new_refresh is not None
        assert new_access != old_refresh
        assert new_refresh != old_refresh
        mock_blacklist.assert_called_once()

    @pytest.mark.asyncio
    async def test_blacklist_both_tokens(self, mock_db):
        """Both access and refresh tokens can be blacklisted together."""
        subject = "testuser"
        access_token = await create_access_token(data={"sub": subject})
        refresh_token = await create_refresh_token(data={"sub": subject})

        with patch("src.app.core.security.crud_token_blacklist.create") as mock_create:
            await blacklist_tokens(access_token, refresh_token, db=mock_db)

        assert mock_create.call_count == 2
        calls = [call[1]["object"] for call in mock_create.call_args_list]
        assert all(isinstance(call, TokenBlacklistCreate) for call in calls)


class TestJWTClaimsAndKeyRotation:
    """Test JWT claims (issuer, audience, key rotation)."""

    @pytest.mark.asyncio
    async def test_issuer_claim_included_when_configured(self, mock_db):
        """JWT includes issuer claim when JWT_ISSUER is configured."""
        custom_settings = load_settings(
            _env_file=None,
            JWT_ISSUER="https://example.com",
        )
        access_token = await create_access_token(
            data={"sub": "testuser"},
            crypt_settings=custom_settings,
        )

        payload = jwt.decode(
            access_token,
            custom_settings.SECRET_KEY.get_secret_value(),
            algorithms=[custom_settings.ALGORITHM],
        )
        assert payload.get("iss") == "https://example.com"

    @pytest.mark.asyncio
    async def test_audience_claim_included_when_configured(self, mock_db):
        """JWT includes audience claim when JWT_AUDIENCE is configured."""
        custom_settings = load_settings(
            _env_file=None,
            JWT_AUDIENCE="myapi",
        )
        access_token = await create_access_token(
            data={"sub": "testuser"},
            crypt_settings=custom_settings,
        )

        payload = jwt.decode(
            access_token,
            custom_settings.SECRET_KEY.get_secret_value(),
            algorithms=[custom_settings.ALGORITHM],
            audience="myapi",
            options={"verify_aud": True},
        )
        assert payload.get("aud") == "myapi"

    @pytest.mark.asyncio
    async def test_token_with_wrong_audience_rejected(self, mock_db):
        """Token verification fails when audience doesn't match."""
        custom_settings = load_settings(
            _env_file=None,
            JWT_AUDIENCE="api1",
        )
        access_token = await create_access_token(
            data={"sub": "testuser"},
            crypt_settings=custom_settings,
        )

        with pytest.raises(JWTError):
            jwt.decode(
                access_token,
                custom_settings.SECRET_KEY.get_secret_value(),
                algorithms=[custom_settings.ALGORITHM],
                audience="api2",
                options={"verify_aud": True},
            )

    @pytest.mark.asyncio
    async def test_kid_header_identifies_active_key(self, mock_db):
        """Token includes kid header pointing to active key."""
        custom_settings = load_settings(
            _env_file=None,
            JWT_ACTIVE_KEY_ID="v1",
        )
        access_token = await create_access_token(
            data={"sub": "testuser"},
            crypt_settings=custom_settings,
        )

        header = jwt.get_unverified_header(access_token)
        assert header.get("kid") == "v1"

    @pytest.mark.asyncio
    async def test_token_decode_with_key_rotation(self, mock_db):
        """Token signed with old key can be decoded with that same old key."""
        old_key = SecretStr("old-secret-key-for-rotation-testing-purposes-only")

        token_payload = {"sub": "testuser", "token_type": "access"}
        old_token = jwt.encode(
            token_payload,
            old_key.get_secret_value(),
            algorithm="HS256",
            headers={"kid": "secondary"},
        )

        # The token can be decoded with the key it was signed with
        payload = jwt.decode(
            old_token,
            old_key.get_secret_value(),
            algorithms=["HS256"],
        )
        assert payload.get("sub") == "testuser"

        # It cannot be decoded with a different key
        different_key = SecretStr("different-key-for-rotation-test-purposes-only")
        with pytest.raises(JWTError):
            jwt.decode(old_token, different_key.get_secret_value(), algorithms=["HS256"])


class TestPasswordHashing:
    """Test password hashing and verification."""

    @pytest.mark.asyncio
    async def test_password_hashing_produces_valid_bcrypt_hash(self):
        """Password hashing produces valid bcrypt hash."""
        password = "MySecurePassword123!"
        hashed = get_password_hash(password)

        assert hashed is not None
        assert hashed != password
        assert hashed.startswith("$2")

    @pytest.mark.asyncio
    async def test_password_verification_succeeds_with_correct_password(self):
        """Password verification succeeds with correct password."""
        password = "MySecurePassword123!"
        hashed = get_password_hash(password)

        is_valid = await verify_password(password, hashed)
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_password_verification_fails_with_wrong_password(self):
        """Password verification fails with wrong password."""
        password = "MySecurePassword123!"
        wrong_password = "WrongPassword456!"
        hashed = get_password_hash(password)

        is_valid = await verify_password(wrong_password, hashed)
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_password_verification_handles_invalid_hash(self):
        """Password verification returns False for invalid hash."""
        is_valid = await verify_password("anypassword", "not-a-valid-hash")
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_password_rehash_needed_when_rounds_lower_than_current(self):
        """Password needs rehash when bcrypt rounds are below configured value."""
        custom_settings = load_settings(
            _env_file=None,
            PASSWORD_BCRYPT_ROUNDS=12,
        )

        old_hash = bcrypt.hashpw(b"password", bcrypt.gensalt(rounds=10)).decode()

        needs_rehash = password_hash_needs_rehash(old_hash, crypt_settings=custom_settings)
        assert needs_rehash is True

    @pytest.mark.asyncio
    async def test_password_rehash_not_needed_when_rounds_sufficient(self):
        """Password does not need rehash when rounds are sufficient."""
        custom_settings = load_settings(
            _env_file=None,
            PASSWORD_BCRYPT_ROUNDS=10,
        )

        current_hash = bcrypt.hashpw(b"password", bcrypt.gensalt(rounds=10)).decode()

        needs_rehash = password_hash_needs_rehash(current_hash, crypt_settings=custom_settings)
        assert needs_rehash is False

    @pytest.mark.asyncio
    async def test_authenticate_user_rehashes_password_when_needed(self):
        """Password is rehashed during login when bcrypt rounds need upgrading."""
        username = "testuser"
        password = "SecurePassword123!"

        old_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=8)).decode()
        db_user = {
            "username": username,
            "hashed_password": old_hash,
            "id": 1,
        }

        custom_settings = load_settings(
            _env_file=None,
            PASSWORD_BCRYPT_ROUNDS=12,
            PASSWORD_HASH_REHASH_ON_LOGIN=True,
        )

        with patch("src.app.core.security.crud_users.get") as mock_get, \
             patch("src.app.core.security.crud_users.update") as mock_update:
            mock_get.return_value = db_user
            mock_update.return_value = None

            result = await authenticate_user(
                username_or_email=username,
                password=password,
                db=Mock(),
                crypt_settings=custom_settings,
            )

            assert result is not None
            mock_update.assert_called_once()
            update_call = mock_update.call_args
            assert update_call[1]["object"]["hashed_password"] != old_hash


class TestAuthorizationFlows:
    """Test role-based authorization and permission checking."""

    def test_admin_role_grants_all_permissions(self):
        """Admin role has all admin permissions."""
        user_data = {
            "id": 1,
            "username": "admin",
            "role": "admin",
        }
        subject = build_authorization_subject(user_data)

        assert has_permission(subject, Permission.ADMIN_ACCESS)
        assert has_permission(subject, Permission.INTERNAL_ACCESS)
        assert has_permission(subject, Permission.MANAGE_USERS)
        assert has_permission(subject, Permission.MANAGE_TIERS)
        assert has_permission(subject, Permission.MANAGE_POSTS)

    def test_authenticated_user_has_no_admin_permissions_by_default(self):
        """Authenticated role has no admin permissions."""
        user_data = {
            "id": 1,
            "username": "user",
        }
        subject = build_authorization_subject(user_data)

        assert not has_permission(subject, Permission.ADMIN_ACCESS)
        assert not has_permission(subject, Permission.MANAGE_USERS)
        assert not has_permission(subject, Permission.MANAGE_TIERS)

    def test_superuser_has_wildcard_permission(self):
        """Superuser role grants wildcard permission."""
        user_data = {
            "id": 1,
            "username": "superuser",
            "is_superuser": True,
        }
        subject = build_authorization_subject(user_data)

        assert has_permission(subject, Permission.ADMIN_ACCESS)
        assert has_permission(subject, Permission.MANAGE_USERS)
        assert has_permission(subject, "*")

    def test_ensure_roles_grants_access_with_correct_role(self):
        """Authorization passes when user has required role."""
        user_data = {
            "id": 1,
            "username": "admin",
            "role": "admin",
        }
        subject = build_authorization_subject(user_data)

        result = ensure_roles(subject, (TemplateRole.ADMIN,))
        assert result.user_id == 1
        assert TemplateRole.ADMIN.value in result.roles

    def test_ensure_roles_denies_access_without_required_role(self):
        """Authorization fails when user lacks required role."""
        user_data = {
            "id": 1,
            "username": "user",
        }
        subject = build_authorization_subject(user_data)

        with pytest.raises(ForbiddenException, match="(?i)requires one of the following roles"):
            ensure_roles(subject, (TemplateRole.ADMIN,))

    def test_ensure_permissions_grants_access_with_all_permissions(self):
        """Authorization passes when user has all required permissions."""
        user_data = {
            "id": 1,
            "username": "admin",
            "role": "admin",
        }
        subject = build_authorization_subject(user_data)

        result = ensure_permissions(
            subject,
            (Permission.MANAGE_USERS, Permission.MANAGE_TIERS),
            require_all=True,
        )
        assert result.user_id == 1

    def test_ensure_permissions_denies_missing_permissions(self):
        """Authorization fails when user lacks required permissions."""
        user_data = {
            "id": 1,
            "username": "user",
        }
        subject = build_authorization_subject(user_data)

        with pytest.raises(ForbiddenException, match="(?i)missing required permissions"):
            ensure_permissions(
                subject,
                (Permission.MANAGE_USERS,),
            )

    def test_ensure_permissions_require_any_allows_one_permission(self):
        """Authorization passes with require_any when user has any permission."""
        user_data = {
            "id": 1,
            "username": "admin",
            "role": "admin",
        }
        subject = build_authorization_subject(user_data)

        result = ensure_permissions(
            subject,
            (Permission.MANAGE_USERS, Permission.MANAGE_TIERS),
            require_all=False,
        )
        assert result.user_id == 1


class TestAPIKeyAuthentication:
    """Test API key authentication flows."""

    def test_valid_api_key_resolves_to_principal(self):
        """Valid API key resolves to service principal with roles/permissions."""
        api_key = "test-api-key-12345"
        api_settings = load_settings(
            _env_file=None,
            API_KEY_ENABLED=True,
            API_KEY_PRINCIPALS={
                "service1": APIKeyPrincipalSettings(
                    key=SecretStr(api_key),
                    roles=["admin"],
                    permissions=["platform:admin:access"],
                    tenant_id="tenant1",
                )
            },
        )

        principal = resolve_api_key_principal(api_key, machine_auth_settings=api_settings)

        assert principal is not None
        assert principal["username"] == "service1"
        assert principal["principal_type"] == "service"
        assert "admin" in principal["roles"]
        assert "platform:admin:access" in principal["permissions"]
        assert principal["tenant_context"]["tenant_id"] == "tenant1"

    def test_invalid_api_key_returns_none(self):
        """Invalid API key returns None."""
        api_settings = load_settings(
            _env_file=None,
            API_KEY_ENABLED=True,
            API_KEY_PRINCIPALS={
                "service1": APIKeyPrincipalSettings(
                    key=SecretStr("correct-key"),
                    roles=["admin"],
                )
            },
        )

        principal = resolve_api_key_principal(
            "wrong-key",
            machine_auth_settings=api_settings,
        )

        assert principal is None

    def test_api_key_disabled_returns_none(self):
        """Returns None when API key auth is disabled."""
        api_settings = load_settings(
            _env_file=None,
            API_KEY_ENABLED=False,
        )

        principal = resolve_api_key_principal(
            "any-key",
            machine_auth_settings=api_settings,
        )

        assert principal is None

    def test_build_api_key_auth_headers_creates_header(self):
        """API key auth headers are built correctly."""
        api_settings = load_settings(
            _env_file=None,
            API_KEY_HEADER_NAME="X-API-Key",
        )

        headers = build_api_key_auth_headers(
            api_key="test-api-key",
            machine_auth_settings=api_settings,
        )

        assert headers == {"X-API-Key": "test-api-key"}

    def test_api_key_principal_has_tenant_context(self):
        """API key principal includes tenant/org context."""
        api_key = "service-key"
        api_settings = load_settings(
            _env_file=None,
            API_KEY_ENABLED=True,
            API_KEY_PRINCIPALS={
                "analytics": APIKeyPrincipalSettings(
                    key=SecretStr(api_key),
                    tenant_id="acme-corp",
                    organization_id="eng-team",
                )
            },
        )

        principal = resolve_api_key_principal(api_key, machine_auth_settings=api_settings)

        assert principal["tenant_context"]["tenant_id"] == "acme-corp"
        assert principal["tenant_context"]["organization_id"] == "eng-team"


class TestMixedAuthentication:
    """Test both Bearer tokens and API keys work for same endpoint."""

    def test_bearer_token_and_api_key_resolve_to_different_principals(self):
        """Bearer token (user) and API key (service) both authenticate correctly."""
        user_data = {
            "id": 1,
            "username": "testuser",
            "email": "test@example.com",
            "is_superuser": False,
        }
        user_subject = build_authorization_subject(user_data)

        api_key = "service-key-123"
        api_settings = load_settings(
            _env_file=None,
            API_KEY_ENABLED=True,
            API_KEY_PRINCIPALS={
                "service": APIKeyPrincipalSettings(
                    key=SecretStr(api_key),
                    roles=["admin"],
                )
            },
        )
        service_principal = resolve_api_key_principal(api_key, machine_auth_settings=api_settings)
        service_subject = build_authorization_subject(service_principal)

        assert user_subject.principal_type == "user"
        assert service_subject.principal_type == "service"
        assert user_subject.username == "testuser"
        assert service_subject.username == "service"


class TestRefreshTokenRotation:
    """Test refresh token rotation and replay attack prevention."""

    @pytest.mark.asyncio
    async def test_refresh_token_has_jti_claim(self, mock_db):
        """Refresh tokens include jti (JWT ID) claim for tracking."""
        subject = "testuser"
        refresh_token = await create_refresh_token(data={"sub": subject})

        jwt.get_unverified_header(refresh_token)
        payload = jwt.decode(
            refresh_token,
            "dummy",
            algorithms=["HS256"],
            options={"verify_signature": False},
        )

        assert payload.get("jti") is not None
        assert isinstance(payload.get("jti"), str)

    @pytest.mark.asyncio
    async def test_refresh_token_rotation_produces_unique_tokens(self, mock_db):
        """Rotated tokens are different from previous ones."""
        subject = "testuser"
        token1 = await create_refresh_token(data={"sub": subject})

        with patch("src.app.core.security.blacklist_token", new=AsyncMock()):
            token2, token3 = await rotate_refresh_token(
                refresh_token=token1,
                subject=subject,
                db=mock_db,
            )

        assert token1 != token2
        assert token2 != token3

    @pytest.mark.asyncio
    async def test_refresh_token_replay_rejected_after_rotation(self, mock_db):
        """Original refresh token cannot be replayed after rotation."""
        subject = "testuser"
        original_token = await create_refresh_token(data={"sub": subject})

        with patch("src.app.core.security.crud_token_blacklist.create") as mock_create:
            new_access, new_refresh = await rotate_refresh_token(
                refresh_token=original_token,
                subject=subject,
                db=mock_db,
            )

        assert mock_create.called
        blacklist_call = mock_create.call_args_list[0]
        blacklisted_token_obj = blacklist_call[1]["object"]
        assert blacklisted_token_obj.token == original_token


class TestPermissionHierarchy:
    """Test role inheritance and permission hierarchy."""

    def test_admin_role_inherits_authenticated_permissions(self):
        """Admin role inherits all authenticated role permissions."""
        admin_permissions = DEFAULT_PERMISSION_POLICY.permissions_for_roles(
            [ADMIN_ROLE]
        )
        authenticated_permissions = DEFAULT_PERMISSION_POLICY.permissions_for_roles(
            [AUTHENTICATED_ROLE]
        )

        assert authenticated_permissions.issubset(admin_permissions)

    def test_superuser_role_inherits_admin_role(self):
        """Superuser role has wildcard and admin permissions."""
        superuser_perms = DEFAULT_PERMISSION_POLICY.permissions_for_roles(
            ["superuser"]
        )

        assert "*" in superuser_perms

    def test_custom_role_inheritance_chain(self):
        """Custom role inheritance expands nested roles."""
        custom_policy = DEFAULT_PERMISSION_POLICY.extend(
            role_permissions={
                "moderator": {Permission.MANAGE_POSTS},
            },
            role_inheritance={
                "moderator": {AUTHENTICATED_ROLE},
            },
        )

        expanded_roles = custom_policy.expand_roles(["moderator"])

        assert "moderator" in expanded_roles
        assert AUTHENTICATED_ROLE in expanded_roles

    def test_admin_has_internal_access_permission(self):
        """Admin role includes platform:internal:access permission."""
        user_data = {
            "id": 1,
            "username": "admin",
            "role": "admin",
        }
        subject = build_authorization_subject(user_data)

        assert has_permission(subject, Permission.INTERNAL_ACCESS)


class TestTenantContextPropagation:
    """Test tenant/organization context in authorization subject."""

    def test_tenant_context_propagates_from_nested_dict(self):
        """Tenant context is extracted from nested tenant_context dict."""
        user_data = {
            "id": 1,
            "username": "user",
            "tenant_context": {
                "tenant_id": "tenant-123",
                "organization_id": "org-456",
            },
        }
        subject = build_authorization_subject(user_data)

        assert subject.tenant_id == "tenant-123"
        assert subject.organization_id == "org-456"

    def test_tenant_context_fallback_to_root_level(self):
        """Tenant context falls back to root tenant_id if nested not present."""
        user_data = {
            "id": 1,
            "username": "user",
            "tenant_id": "tenant-fallback",
            "organization_id": "org-fallback",
        }
        subject = build_authorization_subject(user_data)

        assert subject.tenant_id == "tenant-fallback"
        assert subject.organization_id == "org-fallback"

    def test_nested_tenant_context_takes_precedence(self):
        """Nested tenant_context takes precedence over root level."""
        user_data = {
            "id": 1,
            "username": "user",
            "tenant_id": "root-tenant",
            "tenant_context": {
                "tenant_id": "nested-tenant",
            },
        }
        subject = build_authorization_subject(user_data)

        assert subject.tenant_id == "nested-tenant"

    def test_api_key_principal_preserves_tenant_context(self):
        """API key principal includes tenant context in authorization subject."""
        api_key = "test-key"
        api_settings = load_settings(
            _env_file=None,
            API_KEY_ENABLED=True,
            API_KEY_PRINCIPALS={
                "data-processor": APIKeyPrincipalSettings(
                    key=SecretStr(api_key),
                    tenant_id="client-123",
                    organization_id="division-abc",
                )
            },
        )

        principal = resolve_api_key_principal(api_key, machine_auth_settings=api_settings)
        subject = build_authorization_subject(principal)

        assert subject.tenant_id == "client-123"
        assert subject.organization_id == "division-abc"


class TestAuthorizationSubjectConstruction:
    """Test building authorization subject from user claims."""

    def test_build_subject_from_user_dict_with_roles_list(self):
        """Authorization subject is built from user with roles list."""
        user_data = {
            "id": 1,
            "username": "user",
            "roles": ["admin", "moderator"],
        }
        subject = build_authorization_subject(user_data)

        assert "admin" in subject.roles
        assert "moderator" in subject.roles
        assert AUTHENTICATED_ROLE in subject.roles

    def test_build_subject_adds_default_authenticated_role(self):
        """Default authenticated role is added to all subjects."""
        user_data = {
            "id": 1,
            "username": "user",
        }
        subject = build_authorization_subject(user_data)

        assert AUTHENTICATED_ROLE in subject.roles

    def test_build_subject_grants_admin_role_to_superuser(self):
        """Superuser flag grants both admin and superuser roles."""
        user_data = {
            "id": 1,
            "username": "superuser",
            "is_superuser": True,
        }
        subject = build_authorization_subject(user_data)

        assert ADMIN_ROLE in subject.roles
        assert "superuser" in subject.roles

    def test_build_subject_includes_explicit_permissions(self):
        """Explicit permissions in claims are included in subject."""
        user_data = {
            "id": 1,
            "username": "user",
            "permissions": ["custom:read", "custom:write"],
        }
        subject = build_authorization_subject(user_data)

        assert "custom:read" in subject.permissions
        assert "custom:write" in subject.permissions

    def test_build_subject_parses_space_separated_scopes(self):
        """Space-separated scopes are parsed as separate permissions."""
        user_data = {
            "id": 1,
            "username": "user",
            "scopes": "read:data write:data delete:data",
        }
        subject = build_authorization_subject(user_data)

        assert "read:data" in subject.permissions
        assert "write:data" in subject.permissions
        assert "delete:data" in subject.permissions

    def test_build_subject_preserves_raw_user_data(self):
        """Raw user data is stored in subject for access."""
        user_data = {
            "id": 1,
            "username": "user",
            "email": "user@example.com",
            "custom_field": "custom_value",
        }
        subject = build_authorization_subject(user_data)

        assert subject.raw_user == user_data


class TestTokenExpiration:
    """Test token expiration and TTL handling."""

    @pytest.mark.asyncio
    async def test_access_token_has_expiration_claim(self):
        """Access token includes exp claim."""
        subject = "testuser"
        access_token = await create_access_token(data={"sub": subject})

        payload = jwt.decode(
            access_token,
            "dummy",
            algorithms=["HS256"],
            options={"verify_signature": False},
        )

        assert payload.get("exp") is not None
        assert isinstance(payload.get("exp"), int | float)

    @pytest.mark.asyncio
    async def test_refresh_token_has_longer_expiration_than_access(self):
        """Refresh token expiration is longer than access token."""
        subject = "testuser"
        access_token = await create_access_token(data={"sub": subject})
        refresh_token = await create_refresh_token(data={"sub": subject})

        access_payload = jwt.decode(
            access_token,
            "dummy",
            algorithms=["HS256"],
            options={"verify_signature": False},
        )
        refresh_payload = jwt.decode(
            refresh_token,
            "dummy",
            algorithms=["HS256"],
            options={"verify_signature": False},
        )

        access_exp = access_payload.get("exp")
        refresh_exp = refresh_payload.get("exp")

        assert refresh_exp > access_exp

    @pytest.mark.asyncio
    async def test_custom_token_expiration(self):
        """Custom token expiration delta is respected."""
        subject = "testuser"
        custom_expires = timedelta(hours=2)

        access_token = await create_access_token(
            data={"sub": subject},
            expires_delta=custom_expires,
        )

        payload = jwt.decode(
            access_token,
            "dummy",
            algorithms=["HS256"],
            options={"verify_signature": False},
        )

        exp_time = datetime.fromtimestamp(payload.get("exp"), tz=UTC)
        now = datetime.now(UTC)
        time_until_expiry = (exp_time - now).total_seconds()

        assert time_until_expiry > 0
        assert time_until_expiry < custom_expires.total_seconds() + 5


class TestPermissionPolicyExtension:
    """Test extending permission policies with custom roles."""

    def test_extend_policy_adds_new_role_permissions(self):
        """Extending policy adds new role permissions."""
        extended = DEFAULT_PERMISSION_POLICY.extend(
            role_permissions={
                "analyst": {Permission.ADMIN_ACCESS},
            }
        )

        assert "analyst" in extended.role_permissions

    def test_extend_policy_merges_existing_role_permissions(self):
        """Extending policy merges with existing role permissions."""
        extended = DEFAULT_PERMISSION_POLICY.extend(
            role_permissions={
                ADMIN_ROLE: {Permission.MANAGE_POSTS},
            }
        )

        admin_perms = extended.role_permissions[ADMIN_ROLE]
        assert Permission.ADMIN_ACCESS in admin_perms
        assert Permission.MANAGE_POSTS in admin_perms

    def test_extend_policy_adds_role_inheritance(self):
        """Extending policy can add role inheritance relationships."""
        extended = DEFAULT_PERMISSION_POLICY.extend(
            role_inheritance={
                "operator": {AUTHENTICATED_ROLE},
            }
        )

        assert "operator" in extended.role_inheritance

    def test_extended_policy_expands_roles_with_inheritance(self):
        """Expanded roles include inherited roles."""
        extended = DEFAULT_PERMISSION_POLICY.extend(
            role_inheritance={
                "moderator": {AUTHENTICATED_ROLE},
            },
            role_permissions={
                "moderator": {Permission.MANAGE_POSTS},
            },
        )

        expanded = extended.expand_roles(["moderator"])
        assert "moderator" in expanded
        assert AUTHENTICATED_ROLE in expanded


class TestAuthenticationEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_authenticate_user_by_username(self):
        """User can authenticate with username."""
        username = "testuser"
        password = "SecurePass123!"
        hashed = get_password_hash(password)

        db_user = {
            "username": username,
            "hashed_password": hashed,
            "id": 1,
        }

        with patch("src.app.core.security.crud_users.get") as mock_get:
            mock_get.return_value = db_user

            result = await authenticate_user(
                username_or_email=username,
                password=password,
                db=Mock(),
            )

            assert result is not None
            assert result["username"] == username

    @pytest.mark.asyncio
    async def test_authenticate_user_by_email(self):
        """User can authenticate with email address."""
        email = "user@example.com"
        password = "SecurePass123!"
        hashed = get_password_hash(password)

        db_user = {
            "username": "testuser",
            "email": email,
            "hashed_password": hashed,
            "id": 1,
        }

        with patch("src.app.core.security.crud_users.get") as mock_get:
            mock_get.return_value = db_user

            result = await authenticate_user(
                username_or_email=email,
                password=password,
                db=Mock(),
            )

            assert result is not None

    @pytest.mark.asyncio
    async def test_authenticate_user_not_found_returns_false(self):
        """Authentication returns False when user not found."""
        with patch("src.app.core.security.crud_users.get") as mock_get:
            mock_get.return_value = None

            result = await authenticate_user(
                username_or_email="nonexistent",
                password="password",
                db=Mock(),
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_user_wrong_password_returns_false(self):
        """Authentication returns False for wrong password."""
        db_user = {
            "username": "testuser",
            "hashed_password": get_password_hash("correct"),
            "id": 1,
        }

        with patch("src.app.core.security.crud_users.get") as mock_get:
            mock_get.return_value = db_user

            result = await authenticate_user(
                username_or_email="testuser",
                password="wrong",
                db=Mock(),
            )

            assert result is False
