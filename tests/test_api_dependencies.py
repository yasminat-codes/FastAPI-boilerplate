from unittest.mock import Mock, patch

import pytest
from starlette.requests import Request

from src.app.api.dependencies import (
    get_current_authorization_subject,
    get_current_principal,
    get_current_superuser,
    get_current_tenant_context,
    require_admin_access,
    require_internal_access,
    require_permissions,
    require_roles,
)
from src.app.platform.authorization import TemplatePermission, TemplateRole
from src.app.platform.config import load_settings
from src.app.platform.exceptions import ForbiddenException


@pytest.mark.asyncio
async def test_get_current_authorization_subject_returns_normalized_subject(current_user_dict) -> None:
    current_user = {
        **current_user_dict,
        "role": "Support",
        "permissions": ["tickets:read"],
    }

    subject = await get_current_authorization_subject(current_principal=current_user)

    assert subject.user_id == current_user["id"]
    assert subject.roles == {TemplateRole.AUTHENTICATED.value, "support"}
    assert "tickets:read" in subject.permissions


def build_request_with_headers(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
            "root_path": "",
            "http_version": "1.1",
        }
    )


@pytest.mark.asyncio
async def test_get_current_principal_accepts_api_key_machine_credentials() -> None:
    custom_settings = load_settings(
        _env_file=None,
        API_KEY_ENABLED=True,
        API_KEY_PRINCIPALS={
            "internal-worker": {
                "key": "machine-secret-value",
                "permissions": [TemplatePermission.INTERNAL_ACCESS.value],
                "tenant_id": "tenant-123",
                "organization_id": "org-123",
            }
        },
    )
    request = build_request_with_headers({custom_settings.API_KEY_HEADER_NAME: "machine-secret-value"})

    with (
        patch("src.app.api.dependencies.settings", custom_settings),
        patch("src.app.core.security.settings", custom_settings),
    ):
        principal = await get_current_principal(request=request, db=Mock())

    assert principal["principal_type"] == "service"
    assert principal["permissions"] == [TemplatePermission.INTERNAL_ACCESS.value]
    assert principal["tenant_context"] == {
        "tenant_id": "tenant-123",
        "organization_id": "org-123",
    }


@pytest.mark.asyncio
async def test_get_current_tenant_context_returns_normalized_subject_context() -> None:
    subject = await get_current_authorization_subject(
        current_principal={
            "id": "service:internal-worker",
            "principal_type": "service",
            "permissions": [TemplatePermission.INTERNAL_ACCESS.value],
            "tenant_context": {"tenant_id": "tenant-123", "organization_id": "org-123"},
        }
    )

    tenant_context = await get_current_tenant_context(subject=subject)

    assert tenant_context.tenant_id == "tenant-123"
    assert tenant_context.organization_id == "org-123"


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
    current_principal = {
        **current_user_dict,
        "permissions": [TemplatePermission.MANAGE_TIERS.value],
    }

    result = await dependency(current_principal=current_principal)

    assert result == current_principal


@pytest.mark.asyncio
async def test_require_permissions_allows_default_admin_policy(current_user_dict) -> None:
    dependency = require_permissions(TemplatePermission.MANAGE_RATE_LIMITS)
    current_principal = {**current_user_dict, "is_superuser": True}

    result = await dependency(current_principal=current_principal)

    assert result == current_principal


@pytest.mark.asyncio
async def test_require_admin_access_allows_default_admin_policy(current_user_dict) -> None:
    dependency = require_admin_access()
    current_principal = {**current_user_dict, "is_superuser": True}

    result = await dependency(current_principal=current_principal)

    assert result == current_principal


@pytest.mark.asyncio
async def test_require_internal_access_allows_direct_permission_claim(current_user_dict) -> None:
    dependency = require_internal_access()
    current_principal = {
        **current_user_dict,
        "permissions": [TemplatePermission.INTERNAL_ACCESS.value],
    }

    result = await dependency(current_principal=current_principal)

    assert result == current_principal


@pytest.mark.asyncio
async def test_require_internal_access_allows_machine_principal_claims() -> None:
    dependency = require_internal_access()
    current_principal = {
        "id": "service:internal-worker",
        "principal_type": "service",
        "permissions": [TemplatePermission.INTERNAL_ACCESS.value],
    }

    result = await dependency(current_principal=current_principal)

    assert result == current_principal


@pytest.mark.asyncio
async def test_require_permissions_rejects_missing_permission(current_user_dict) -> None:
    dependency = require_permissions(TemplatePermission.MANAGE_POSTS)

    with pytest.raises(ForbiddenException, match="Missing required permissions: platform:posts:manage"):
        await dependency(current_principal=current_user_dict)


@pytest.mark.asyncio
async def test_require_roles_accepts_custom_role_claim(current_user_dict) -> None:
    dependency = require_roles("support")
    current_principal = {
        **current_user_dict,
        "roles": ["support"],
    }

    result = await dependency(current_principal=current_principal)

    assert result == current_principal
