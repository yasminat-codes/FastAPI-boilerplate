# Permissions and Authorization

Authorization answers a different question than authentication. Authentication proves who the caller is. Authorization decides what that caller may do after identity has already been established.

Phase 4 Wave 4.2 now gives the template a reusable permission-policy layer instead of relying only on `get_current_superuser(...)` plus scattered ownership checks.

## What the template now ships

The shared authorization surface lives in `src/app/platform/authorization.py` and gives cloned projects a generic starting point without forcing one client's role model into the template.

- `AuthorizationSubject`: normalized actor context with `roles`, `permissions`, `user_id`, `tier_id`, and the raw user payload
- `PermissionPolicy`: reusable role-to-permission mapping with simple inheritance support
- `DEFAULT_PERMISSION_POLICY`: the built-in policy for the template's own platform routes
- `TemplateRole`: default shared roles for the base template
- `TemplatePermission`: explicit permission names for the built-in admin-style route surface

The API layer now exposes dependency helpers in `src/app/api/dependencies.py`:

- `get_current_authorization_subject`
- `require_admin_access(...)`
- `require_internal_access(...)`
- `require_roles(...)`
- `require_permissions(...)`
- `get_current_superuser(...)`

## Default behavior

The built-in template contract is intentionally small:

- Every authenticated user gets the `authenticated` role.
- Any user with `is_superuser=True` also gets the `admin` role.
- The default `admin` role receives the template's built-in management permissions for users, tiers, rate limits, posts, and admin access.
- If your project enriches the authenticated user payload with `role`, `roles`, `permissions`, or `scopes`, the authorization layer will normalize and merge those values automatically.

That means the template works today with the existing `User` model, while still leaving a clean extension point for future client-specific role models.

## Built-in permissions

The template currently reserves these default permission names for its own platform routes:

- `platform:admin:access`
- `platform:internal:access`
- `platform:posts:manage`
- `platform:rate-limits:manage`
- `platform:tiers:manage`
- `platform:users:manage`

These are template-owned permissions for the reusable starter surface. Cloned projects can add their own permission names on top of them.

## Internal versus external route access

Phase 4 Wave 4.2 now makes the route-surface boundary explicit:

- `public` routes are external application APIs. Protect individual endpoints as needed with auth and permission dependencies.
- `ops` routes stay external and unauthenticated so load balancers and orchestrators can use `/health` and `/ready` safely.
- `internal` routes are trusted operator or automation surfaces. The template now protects that group with `require_internal_access(...)`, which defaults to `platform:internal:access`.
- `admin` routes are reserved for admin-only HTTP surfaces and use `require_admin_access(...)`, which defaults to `platform:admin:access`.
- `webhooks` remain external machine-to-machine ingress. They should rely on signature verification and replay controls instead of end-user JWTs.

The built-in `admin` role receives both `platform:admin:access` and `platform:internal:access`, but cloned projects can split those concerns by extending the permission policy with a dedicated operator or service role later.

## Route-level authorization

Use `require_roles(...)` when you care about a coarse role boundary and `require_permissions(...)` when you want a more explicit route contract.

```python
from fastapi import Depends

from app.api.dependencies import require_permissions, require_roles
from app.platform.authorization import TemplatePermission, TemplateRole


@router.get("/admin", dependencies=[Depends(require_roles(TemplateRole.ADMIN))])
async def read_admin_dashboard() -> dict[str, str]:
    return {"status": "ok"}


@router.delete(
    "/tier/{name}",
    dependencies=[Depends(require_permissions(TemplatePermission.MANAGE_TIERS))],
)
async def delete_tier(name: str) -> dict[str, str]:
    return {"message": f"Deleted {name}"}
```

The reusable template now uses explicit permission dependencies on its built-in tier, rate-limit, user-management, and hard-delete post routes.

## Subject access inside endpoints

When a handler needs the normalized authorization context directly, depend on `get_current_authorization_subject(...)`:

```python
from typing import Annotated

from fastapi import Depends

from app.api.dependencies import get_current_authorization_subject
from app.platform.authorization import AuthorizationSubject


@router.get("/whoami")
async def read_whoami(
    subject: Annotated[AuthorizationSubject, Depends(get_current_authorization_subject)],
) -> dict[str, list[str]]:
    return {
        "roles": sorted(subject.roles),
        "permissions": sorted(subject.permissions),
    }
```

## Extending the policy for a real project

The template does not assume one universal business role model. Instead, extend the shared policy from the project layer:

```python
from fastapi import Depends

from app.api.dependencies import require_permissions
from app.platform.authorization import DEFAULT_PERMISSION_POLICY, TemplateRole


SUPPORT_POLICY = DEFAULT_PERMISSION_POLICY.extend(
    role_permissions={
        "support": {"tickets:read", "tickets:reply"},
    },
    role_inheritance={
        "support": {TemplateRole.AUTHENTICATED},
    },
)


@router.post(
    "/tickets/{ticket_id}/reply",
    dependencies=[Depends(require_permissions("tickets:reply", policy=SUPPORT_POLICY))],
)
async def reply_to_ticket(ticket_id: int) -> dict[str, int]:
    return {"ticket_id": ticket_id}
```

This keeps the template generic while making it straightforward to add project-specific roles and permissions in a cloned repo.

## Resource ownership is still separate

The permission-policy layer handles route-level authorization. Resource ownership checks still belong close to the business logic or repository lookup where the template can compare the actor against the resource being changed.

Use this split:

- route dependency for coarse access, such as "must have tier-management permission"
- service-layer ownership check for fine-grained rules, such as "may only edit your own profile"

That pattern keeps route contracts readable while avoiding fragile authorization logic spread across many handlers.

## What this layer does not do yet

This new template layer is intentionally generic. It does not yet provide:

- tenant or organization membership resolution
- API key or service-to-service policy mapping
- time-based or contextual business authorization rules
- automatic conversion from database role tables into permission grants

Those roadmap items remain separate so the template does not silently hardcode one application's authorization model.
