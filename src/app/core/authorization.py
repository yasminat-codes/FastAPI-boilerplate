"""Template authorization primitives with reusable role and permission hooks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any

from .exceptions.http_exceptions import ForbiddenException

WILDCARD_PERMISSION = "*"
AUTHENTICATED_ROLE = "authenticated"
ADMIN_ROLE = "admin"
SUPERUSER_ROLE = "superuser"
DEFAULT_PERMISSION_DENIED_MESSAGE = "You do not have enough privileges."


class TemplateRole(StrEnum):
    AUTHENTICATED = AUTHENTICATED_ROLE
    ADMIN = ADMIN_ROLE
    SUPERUSER = SUPERUSER_ROLE


class Permission(StrEnum):
    ADMIN_ACCESS = "platform:admin:access"
    MANAGE_POSTS = "platform:posts:manage"
    MANAGE_RATE_LIMITS = "platform:rate-limits:manage"
    MANAGE_TIERS = "platform:tiers:manage"
    MANAGE_USERS = "platform:users:manage"


TemplatePermission = Permission


def _normalize_identifier(value: str | Enum) -> str:
    raw_value = value.value if isinstance(value, Enum) else value
    return str(raw_value).strip().lower()


def _normalize_identifier_set(values: Iterable[object]) -> frozenset[str]:
    normalized = {
        normalized_value
        for value in values
        if isinstance(value, str | Enum) and (normalized_value := _normalize_identifier(value))
    }
    return frozenset(normalized)


def _normalize_mapping(
    mapping: Mapping[Any, Iterable[Any]],
) -> dict[str, frozenset[str]]:
    normalized: dict[str, frozenset[str]] = {}
    for key, values in mapping.items():
        if not isinstance(key, str | Enum):
            continue
        normalized_key = _normalize_identifier(key)
        if not normalized_key:
            continue
        normalized[normalized_key] = _normalize_identifier_set(values)
    return normalized


def _normalize_claim_values(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str | Enum):
        normalized_value = _normalize_identifier(value)
        if normalized_value:
            return frozenset({normalized_value})
        return frozenset()
    if isinstance(value, Mapping):
        return frozenset()
    if isinstance(value, Iterable):
        return _normalize_identifier_set(value)
    return frozenset()


def _normalize_scope_values(value: Any) -> frozenset[str]:
    if isinstance(value, str):
        return frozenset(
            normalized_scope
            for scope in value.split()
            if (normalized_scope := _normalize_identifier(scope))
        )
    return _normalize_claim_values(value)


@dataclass(frozen=True, slots=True)
class AuthorizationSubject:
    user_id: Any | None = None
    username: str | None = None
    email: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    is_superuser: bool = False
    tier_id: Any | None = None
    raw_user: Mapping[str, Any] = field(default_factory=dict)

    @property
    def subject_id(self) -> Any | None:
        return self.user_id


@dataclass(frozen=True, slots=True)
class PermissionPolicy:
    role_permissions: Mapping[str, frozenset[str]]
    role_inheritance: Mapping[str, frozenset[str]] = field(default_factory=dict)
    default_role: str = AUTHENTICATED_ROLE
    admin_role: str = ADMIN_ROLE
    superuser_role: str = SUPERUSER_ROLE
    wildcard_permission: str = WILDCARD_PERMISSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "role_permissions", _normalize_mapping(self.role_permissions))
        object.__setattr__(self, "role_inheritance", _normalize_mapping(self.role_inheritance))
        object.__setattr__(self, "default_role", _normalize_identifier(self.default_role))
        object.__setattr__(self, "admin_role", _normalize_identifier(self.admin_role))
        object.__setattr__(self, "superuser_role", _normalize_identifier(self.superuser_role))
        object.__setattr__(self, "wildcard_permission", _normalize_identifier(self.wildcard_permission))

    def extend(
        self,
        *,
        role_permissions: Mapping[str | Enum, Iterable[str | Enum]] | None = None,
        role_inheritance: Mapping[str | Enum, Iterable[str | Enum]] | None = None,
    ) -> PermissionPolicy:
        merged_permissions = dict(self.role_permissions)
        if role_permissions:
            for role, permissions in _normalize_mapping(role_permissions).items():
                merged_permissions[role] = frozenset(merged_permissions.get(role, frozenset()) | permissions)

        merged_inheritance = dict(self.role_inheritance)
        if role_inheritance:
            for role, inherited_roles in _normalize_mapping(role_inheritance).items():
                merged_inheritance[role] = frozenset(merged_inheritance.get(role, frozenset()) | inherited_roles)

        return PermissionPolicy(
            role_permissions=merged_permissions,
            role_inheritance=merged_inheritance,
            default_role=self.default_role,
            admin_role=self.admin_role,
            superuser_role=self.superuser_role,
            wildcard_permission=self.wildcard_permission,
        )

    def expand_roles(self, roles: Iterable[str | Enum]) -> frozenset[str]:
        pending = list(_normalize_identifier_set(roles))
        resolved: set[str] = set()

        while pending:
            role = pending.pop()
            if role in resolved:
                continue
            resolved.add(role)
            pending.extend(self.role_inheritance.get(role, ()))

        return frozenset(resolved)

    def permissions_for_roles(self, roles: Iterable[str | Enum]) -> frozenset[str]:
        permissions: set[str] = set()
        for role in self.expand_roles(roles):
            permissions.update(self.role_permissions.get(role, frozenset()))
        return frozenset(permissions)

    def build_subject(self, current_user: Mapping[str, Any]) -> AuthorizationSubject:
        roles: set[str] = set()
        roles.update(_normalize_claim_values(current_user.get("role")))
        roles.update(_normalize_claim_values(current_user.get("roles")))

        if self.default_role:
            roles.add(self.default_role)
        if bool(current_user.get("is_superuser")):
            roles.add(self.admin_role)
            roles.add(self.superuser_role)

        expanded_roles = self.expand_roles(roles)
        permissions = set(self.permissions_for_roles(expanded_roles))
        permissions.update(_normalize_claim_values(current_user.get("permissions")))
        permissions.update(_normalize_scope_values(current_user.get("scopes")))

        return AuthorizationSubject(
            user_id=current_user.get("id"),
            username=current_user.get("username"),
            email=current_user.get("email"),
            roles=expanded_roles,
            permissions=frozenset(permissions),
            is_superuser=bool(current_user.get("is_superuser")),
            tier_id=current_user.get("tier_id"),
            raw_user=current_user,
        )


RolePermissionPolicy = PermissionPolicy


DEFAULT_ROLE_PERMISSION_GRANTS: dict[str, frozenset[str]] = {
    AUTHENTICATED_ROLE: frozenset(),
    ADMIN_ROLE: frozenset(
            {
                Permission.ADMIN_ACCESS,
                Permission.MANAGE_POSTS,
                Permission.MANAGE_RATE_LIMITS,
                Permission.MANAGE_TIERS,
            Permission.MANAGE_USERS,
        }
    ),
    SUPERUSER_ROLE: frozenset({WILDCARD_PERMISSION}),
}


DEFAULT_PERMISSION_POLICY = PermissionPolicy(
    role_permissions=DEFAULT_ROLE_PERMISSION_GRANTS,
    role_inheritance={
        ADMIN_ROLE: frozenset({AUTHENTICATED_ROLE}),
        SUPERUSER_ROLE: frozenset({ADMIN_ROLE}),
    },
)
DEFAULT_AUTHORIZATION_POLICY = DEFAULT_PERMISSION_POLICY


def build_authorization_subject(
    current_user: Mapping[str, Any],
    *,
    policy: PermissionPolicy = DEFAULT_PERMISSION_POLICY,
) -> AuthorizationSubject:
    return policy.build_subject(current_user)


def _coerce_subject(
    subject: Mapping[str, Any] | AuthorizationSubject,
    *,
    policy: PermissionPolicy = DEFAULT_PERMISSION_POLICY,
) -> AuthorizationSubject:
    if isinstance(subject, AuthorizationSubject):
        return subject
    return build_authorization_subject(subject, policy=policy)


def has_permission(
    subject: Mapping[str, Any] | AuthorizationSubject,
    permission: Permission | str,
    *,
    policy: PermissionPolicy = DEFAULT_PERMISSION_POLICY,
) -> bool:
    resolved_subject = _coerce_subject(subject, policy=policy)
    normalized_permission = _normalize_identifier(permission)
    return (
        normalized_permission in resolved_subject.permissions
        or policy.wildcard_permission in resolved_subject.permissions
    )


def subject_has_role(
    subject: Mapping[str, Any] | AuthorizationSubject,
    role: str | Enum,
    *,
    policy: PermissionPolicy = DEFAULT_PERMISSION_POLICY,
) -> bool:
    resolved_subject = _coerce_subject(subject, policy=policy)
    return _normalize_identifier(role) in resolved_subject.roles


def _normalize_required_values(values: Iterable[str | Enum], *, label: str) -> frozenset[str]:
    normalized = _normalize_identifier_set(values)
    if not normalized:
        raise ValueError(f"At least one {label} must be provided")
    return normalized


def ensure_roles(
    subject: Mapping[str, Any] | AuthorizationSubject,
    required_roles: Iterable[str | Enum],
    *,
    require_all: bool = False,
    policy: PermissionPolicy = DEFAULT_PERMISSION_POLICY,
    message: str | None = None,
) -> AuthorizationSubject:
    resolved_subject = _coerce_subject(subject, policy=policy)
    normalized_roles = _normalize_required_values(required_roles, label="role")

    if require_all:
        missing_roles = normalized_roles - resolved_subject.roles
        if missing_roles:
            raise ForbiddenException(message or f"Missing required roles: {', '.join(sorted(missing_roles))}")
        return resolved_subject

    if not resolved_subject.roles.intersection(normalized_roles):
        raise ForbiddenException(
            message or f"Requires one of the following roles: {', '.join(sorted(normalized_roles))}"
        )

    return resolved_subject


def ensure_permissions(
    subject: Mapping[str, Any] | AuthorizationSubject,
    required_permissions: Iterable[str | Enum],
    *,
    require_all: bool = True,
    policy: PermissionPolicy = DEFAULT_PERMISSION_POLICY,
    message: str | None = None,
) -> AuthorizationSubject:
    resolved_subject = _coerce_subject(subject, policy=policy)
    normalized_permissions = _normalize_required_values(required_permissions, label="permission")

    if require_all:
        missing_permissions = {
            permission
            for permission in normalized_permissions
            if permission not in resolved_subject.permissions
            and policy.wildcard_permission not in resolved_subject.permissions
        }
        if missing_permissions:
            raise ForbiddenException(
                message or f"Missing required permissions: {', '.join(sorted(missing_permissions))}"
            )
        return resolved_subject

    if not any(
        permission in resolved_subject.permissions or policy.wildcard_permission in resolved_subject.permissions
        for permission in normalized_permissions
    ):
        raise ForbiddenException(
            message
            or f"Requires one of the following permissions: {', '.join(sorted(normalized_permissions))}"
        )

    return resolved_subject


def authorize_permission(
    subject: Mapping[str, Any] | AuthorizationSubject,
    permission: Permission | str,
    *,
    policy: PermissionPolicy = DEFAULT_PERMISSION_POLICY,
    message: str = DEFAULT_PERMISSION_DENIED_MESSAGE,
) -> AuthorizationSubject:
    return ensure_permissions(subject, (permission,), policy=policy, message=message)


def is_resource_owner(
    subject: Mapping[str, Any] | AuthorizationSubject,
    *,
    owner_user_id: int | None = None,
    owner_username: str | None = None,
    policy: PermissionPolicy = DEFAULT_PERMISSION_POLICY,
) -> bool:
    resolved_subject = _coerce_subject(subject, policy=policy)

    if owner_user_id is not None and resolved_subject.user_id == owner_user_id:
        return True

    if owner_username is not None and resolved_subject.username == owner_username:
        return True

    return False


def authorize_owner_or_permission(
    subject: Mapping[str, Any] | AuthorizationSubject,
    *,
    permission: Permission | str,
    owner_user_id: int | None = None,
    owner_username: str | None = None,
    policy: PermissionPolicy = DEFAULT_PERMISSION_POLICY,
    message: str = DEFAULT_PERMISSION_DENIED_MESSAGE,
) -> AuthorizationSubject:
    resolved_subject = _coerce_subject(subject, policy=policy)
    if is_resource_owner(
        resolved_subject,
        owner_user_id=owner_user_id,
        owner_username=owner_username,
        policy=policy,
    ):
        return resolved_subject
    return authorize_permission(
        resolved_subject,
        permission=permission,
        policy=policy,
        message=message,
    )


__all__ = [
    "ADMIN_ROLE",
    "AUTHENTICATED_ROLE",
    "AuthorizationSubject",
    "DEFAULT_AUTHORIZATION_POLICY",
    "DEFAULT_PERMISSION_DENIED_MESSAGE",
    "DEFAULT_PERMISSION_POLICY",
    "DEFAULT_ROLE_PERMISSION_GRANTS",
    "Permission",
    "PermissionPolicy",
    "RolePermissionPolicy",
    "SUPERUSER_ROLE",
    "TemplatePermission",
    "TemplateRole",
    "WILDCARD_PERMISSION",
    "authorize_owner_or_permission",
    "authorize_permission",
    "build_authorization_subject",
    "ensure_permissions",
    "ensure_roles",
    "has_permission",
    "is_resource_owner",
    "subject_has_role",
]
