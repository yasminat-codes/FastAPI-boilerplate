import pytest

from src.app.api.dependencies import (
    get_current_authorization_subject,
    get_current_superuser,
    require_admin_access,
    require_internal_access,
    require_permissions,
    require_roles,
)
from src.app.platform.authorization import TemplatePermission, TemplateRole
from src.app.platform.exceptions import ForbiddenException


@pytest.mark.asyncio
async def test_get_current_authorization_subject_returns_normalized_subject(current_user_dict) -> None:
    current_user = {
        **current_user_dict,
        "role": "Support",
        "permissions": ["tickets:read"],
    }

    subject = await get_current_authorization_subject(current_user=current_user)

    assert subject.user_id == current_user["id"]
    assert subject.roles == {TemplateRole.AUTHENTICATED.value, "support"}
    assert "tickets:read" in subject.permissions


@pytest.mark.asyncio
async def test_get_current_superuser_allows_admin_role(current_user_dict) -> None:
    current_user = {**current_user_dict, "is_superuser": True}

    result = await get_current_superuser(current_user=current_user)

    assert result == current_user


@pytest.mark.asyncio
async def test_get_current_superuser_rejects_non_admin(current_user_dict) -> None:
    with pytest.raises(ForbiddenException, match="Requires one of the following roles: admin"):
        await get_current_superuser(current_user=current_user_dict)


@pytest.mark.asyncio
async def test_require_permissions_allows_direct_permission_claims(current_user_dict) -> None:
    dependency = require_permissions(TemplatePermission.MANAGE_TIERS)
    current_user = {
        **current_user_dict,
        "permissions": [TemplatePermission.MANAGE_TIERS.value],
    }

    result = await dependency(current_user=current_user)

    assert result == current_user


@pytest.mark.asyncio
async def test_require_permissions_allows_default_admin_policy(current_user_dict) -> None:
    dependency = require_permissions(TemplatePermission.MANAGE_RATE_LIMITS)
    current_user = {**current_user_dict, "is_superuser": True}

    result = await dependency(current_user=current_user)

    assert result == current_user


@pytest.mark.asyncio
async def test_require_admin_access_allows_default_admin_policy(current_user_dict) -> None:
    dependency = require_admin_access()
    current_user = {**current_user_dict, "is_superuser": True}

    result = await dependency(current_user=current_user)

    assert result == current_user


@pytest.mark.asyncio
async def test_require_internal_access_allows_direct_permission_claim(current_user_dict) -> None:
    dependency = require_internal_access()
    current_user = {
        **current_user_dict,
        "permissions": [TemplatePermission.INTERNAL_ACCESS.value],
    }

    result = await dependency(current_user=current_user)

    assert result == current_user


@pytest.mark.asyncio
async def test_require_permissions_rejects_missing_permission(current_user_dict) -> None:
    dependency = require_permissions(TemplatePermission.MANAGE_POSTS)

    with pytest.raises(ForbiddenException, match="Missing required permissions: platform:posts:manage"):
        await dependency(current_user=current_user_dict)


@pytest.mark.asyncio
async def test_require_roles_accepts_custom_role_claim(current_user_dict) -> None:
    dependency = require_roles("support")
    current_user = {
        **current_user_dict,
        "roles": ["support"],
    }

    result = await dependency(current_user=current_user)

    assert result == current_user
