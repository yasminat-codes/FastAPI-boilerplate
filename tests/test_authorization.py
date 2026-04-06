import pytest

from src.app.platform.authorization import (
    DEFAULT_PERMISSION_POLICY,
    PermissionPolicy,
    TemplatePermission,
    TemplateRole,
    build_authorization_subject,
    ensure_permissions,
    ensure_roles,
)
from src.app.platform.exceptions import ForbiddenException


def test_build_authorization_subject_grants_default_roles_and_admin_permissions() -> None:
    subject = build_authorization_subject({"id": 1, "is_superuser": True})

    assert subject.user_id == 1
    assert subject.is_superuser is True
    assert TemplateRole.AUTHENTICATED.value in subject.roles
    assert TemplateRole.ADMIN.value in subject.roles
    assert TemplatePermission.MANAGE_USERS.value in subject.permissions
    assert TemplatePermission.MANAGE_TIERS.value in subject.permissions


def test_permission_policy_extend_supports_custom_roles_permissions_and_scopes() -> None:
    custom_policy = DEFAULT_PERMISSION_POLICY.extend(
        role_permissions={"support": {"tickets:read"}},
        role_inheritance={"support": {TemplateRole.AUTHENTICATED}},
    )

    subject = build_authorization_subject(
        {
            "id": 42,
            "role": "Support",
            "permissions": ["reports:view"],
            "scopes": "tickets:reply tickets:close",
        },
        policy=custom_policy,
    )

    assert subject.roles == {TemplateRole.AUTHENTICATED.value, "support"}
    assert subject.permissions == {
        "reports:view",
        "tickets:close",
        "tickets:read",
        "tickets:reply",
    }


def test_permission_policy_extend_merges_with_existing_grants() -> None:
    custom_policy = PermissionPolicy(
        role_permissions={"reviewer": frozenset({"reviews:read"})},
        role_inheritance={"reviewer": frozenset({TemplateRole.AUTHENTICATED})},
    ).extend(
        role_permissions={"reviewer": {"reviews:write"}},
        role_inheritance={"reviewer": {"staff"}},
    )

    assert custom_policy.role_permissions["reviewer"] == {"reviews:read", "reviews:write"}
    assert custom_policy.role_inheritance["reviewer"] == {TemplateRole.AUTHENTICATED.value, "staff"}


def test_ensure_roles_rejects_missing_roles() -> None:
    subject = build_authorization_subject({"id": 1})

    with pytest.raises(ForbiddenException, match="Requires one of the following roles: admin"):
        ensure_roles(subject, (TemplateRole.ADMIN,))


def test_ensure_permissions_rejects_missing_permissions() -> None:
    subject = build_authorization_subject({"id": 1})

    with pytest.raises(
        ForbiddenException,
        match="Missing required permissions: platform:tiers:manage, platform:users:manage",
    ):
        ensure_permissions(
            subject,
            (TemplatePermission.MANAGE_USERS, TemplatePermission.MANAGE_TIERS),
        )
