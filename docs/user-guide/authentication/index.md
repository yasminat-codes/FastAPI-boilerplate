# Authentication & Security

Learn how to implement secure authentication in your FastAPI application. The template currently standardizes on a stateless dual-JWT model for user auth: short-lived access tokens in the `Authorization` header plus longer-lived refresh tokens delivered through an HTTP-only cookie. A blacklist table handles explicit revocation and logout, and the baseline now supports optional issuer and audience claims plus key-id-based signing-key rotation. For internal hooks and machine clients, the same auth layer can also resolve optional API-key-backed machine principals from settings.

## What You'll Learn

- **[JWT Tokens](jwt-tokens.md)** - Understand access and refresh token management
- **[User Management](user-management.md)** - Handle registration, login, and user profiles
- **[Permissions](permissions.md)** - Implement role-based access control and authorization

## Authentication Overview

Phase 4 Wave 4.1 now formally keeps the template on a stateless JWT-only posture instead of introducing a server-backed refresh-session store by default. That keeps the reusable scaffold simple and broadly compatible while still giving adopters a production-minded baseline:

- **Access tokens** remain short-lived signed JWTs for API requests.
- **Refresh tokens** remain signed JWTs, are delivered through an HTTP-only cookie, and now rotate on `/refresh`.
- **Revocation** is handled through blacklist records for logout and explicit invalidation flows.
- **Hardening hooks included**: optional `iss`/`aud` claims and a `kid`-driven verification key ring for secret rotation.
- **Not included by default**: server-backed refresh-session tables, per-device session management, or mandatory hybrid-session infrastructure.

This means the next auth-hardening roadmap items build on the existing token model rather than replacing it wholesale.

```python
# Basic login flow
@router.post("/login", response_model=Token)
async def login_for_access_token(response: Response, form_data: OAuth2PasswordRequestForm):
    user = await authenticate_user(form_data.username, form_data.password, db)
    access_token = await create_access_token(data={"sub": user["username"]})
    refresh_token = await create_refresh_token(data={"sub": user["username"]})

    # Apply the template's refresh-cookie policy from settings
    set_refresh_token_cookie(
        response,
        refresh_token=refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        cookie_settings=settings,
    )
    return {"access_token": access_token, "token_type": "bearer"}
```

## Key Features

### JWT Token System
- **Access tokens**: Short-lived (30 minutes), for API requests
- **Refresh tokens**: Long-lived (7 days), stored in secure cookies
- **Token blacklisting**: Secure logout and explicit revocation implementation
- **Automatic expiration**: Built-in token lifecycle management

### User Management
- **Flexible authentication**: Username or email login
- **Secure passwords**: bcrypt hashing with salt
- **Profile management**: Complete user CRUD operations
- **Soft delete**: User deactivation without data loss

### Permission System
- **Default shared roles**: Every authenticated user gets `authenticated`; `is_superuser=True` adds `admin`
- **Explicit permission dependencies**: Built-in routes can depend on named platform permissions instead of one hard-coded admin check
- **Internal versus external boundary**: `/api/v1/internal/*` now requires the template's internal-access permission, while `/health` and `/ready` stay safe for unauthenticated infrastructure probes
- **Machine principal support**: internal hooks and other machine clients can authenticate with configured `API_KEY_PRINCIPALS` instead of end-user JWTs
- **Tenant/org hook support**: normalized tenant and organization context can flow through the authorization subject when a cloned project needs tenant-aware policy later
- **Custom claims support**: `role`, `roles`, `permissions`, and `scopes` claims are normalized automatically when projects extend the auth payload
- **Ownership stays explicit**: Fine-grained self-versus-other checks remain in services instead of being hidden in route decorators

## Authentication Patterns

### Endpoint Protection

```python
from app.api.dependencies import (
    get_current_authorization_subject,
    get_current_user,
    require_permissions,
)
from app.platform.authorization import TemplatePermission


@router.get("/protected")
async def protected_endpoint(current_user: dict = Depends(get_current_user)):
    return {"message": f"Hello {current_user['username']}"}


@router.get(
    "/admin/users",
    dependencies=[Depends(require_permissions(TemplatePermission.MANAGE_USERS))],
)
async def admin_users_endpoint():
    return {"admin_data": "sensitive"}


@router.get("/whoami")
async def whoami(subject=Depends(get_current_authorization_subject)):
    return {"roles": sorted(subject.roles), "permissions": sorted(subject.permissions)}
```

### Resource Ownership

```python
@router.patch("/posts/{post_id}")
async def update_post(post_id: int, current_user: dict = Depends(get_current_user)):
    post = await crud_posts.get(db=db, id=post_id)

    # Ownership remains explicit in the service or handler layer.
    if post["created_by_user_id"] != current_user["id"]:
        raise ForbiddenException("Cannot update other users' posts")

    return await crud_posts.update(db=db, id=post_id, object=updates)
```

## Security Features

### Token Security
- Short-lived access tokens limit exposure
- HTTP-only refresh token cookies prevent XSS
- Token blacklisting enables secure logout and explicit revocation
- Configurable token expiration times

### Password Security
- bcrypt hashing with a configurable work factor
- Automatic rehash-on-login when the configured bcrypt cost increases
- No plain text passwords stored anywhere
- Documented guidance for login throttling and temporary lockouts

### API Protection
- CORS policies for cross-origin request control
- Rate limiting prevents brute force attacks
- Input validation prevents injection attacks
- Consistent error messages prevent information disclosure

## CSRF Review For Cookie-Based Flows

The template currently exposes two browser cookie surfaces:

- the refresh-token cookie used by `/login`, `/refresh`, and `/logout`
- the optional CRUDAdmin session cookie when `CRUD_ADMIN_ENABLED=true`

The default posture is intentionally narrow:

- access tokens stay in the `Authorization` header, so normal API mutations are not cookie-authenticated by default
- the refresh-token cookie is `HttpOnly` and defaults to `SameSite="lax"`
- secure environments require `Secure` transport for the refresh cookie, and also for the admin session cookie when the admin UI is enabled
- the browser admin surface stays disabled until you opt in

That baseline is a good start, but it is not a complete CSRF solution for every deployment shape:

- `SameSite="lax"` helps with common cross-site CSRF, but it does not cover every same-site cross-origin scenario, such as sibling subdomains you do not fully trust
- `CORS` is not a CSRF defense; it only controls whether browser JavaScript can read the response
- if a cloned project changes the refresh cookie to `SameSite="none"` for a frontend hosted on a different site, it should add explicit CSRF controls before relying on that cookie for state-changing requests

Recommended template posture:

- keep cookie auth limited to refresh/logout and the opt-in admin surface
- prefer bearer tokens or API keys for machine clients and cross-site integrations
- if you add more cookie-authenticated mutation routes, layer Origin/Referer validation or double-submit CSRF tokens on top

## Configuration

### JWT Settings
```env
SECRET_KEY="your-super-secret-key-here"
ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
JWT_ISSUER="https://api.example.com"
JWT_AUDIENCE="template-api"
JWT_ACTIVE_KEY_ID="2026-04"
JWT_VERIFICATION_KEYS='{"2026-01":"previous-signing-secret"}'
```

### Security Settings
```env
# Refresh-token cookie security
REFRESH_TOKEN_COOKIE_SECURE=true
REFRESH_TOKEN_COOKIE_HTTPONLY=true
REFRESH_TOKEN_COOKIE_SAMESITE="lax"
SESSION_SECURE_COOKIES=true

# Password hashing policy
PASSWORD_HASH_SCHEME="bcrypt"
PASSWORD_BCRYPT_ROUNDS=12
PASSWORD_HASH_REHASH_ON_LOGIN=true

# Optional machine-principal auth
API_KEY_ENABLED=true
API_KEY_HEADER_NAME="X-API-Key"
API_KEY_PRINCIPALS='{"internal-worker":{"key":"change-me-machine-secret","permissions":["platform:internal:access"]}}'
```

## Login Throttling Guidance

The template now ships a reusable baseline rate-limit strategy for `/login`, `/refresh`, and `/logout`:

- `/login` uses its own budget keyed by client identity plus a fingerprinted username or email hint, so repeated sign-in attempts do not consume the same bucket as token refresh traffic
- `/refresh` and `/logout` use separate auth-route budgets so browser token lifecycle traffic stays isolated from interactive password entry
- all three budgets are controlled through `AUTH_RATE_LIMIT_*` settings and can be tuned without route rewrites

The template still does not hardcode one full lockout product policy, so cloned projects should extend the baseline with the following pattern when needed:

- use the existing Redis-backed rate-limit foundation for login-attempt counters keyed by normalized username or email plus client IP or proxy-aware network identity
- enforce a short rolling-attempt budget and a separate temporary lockout window instead of relying on one unbounded counter
- keep invalid-login responses generic, reset counters on successful authentication, and log lockout events with request and correlation IDs
- apply separate limits for `/login`, `/refresh`, and admin auth flows so browser token refreshes are not coupled to interactive password-entry limits

## Getting Started

Follow this progressive learning path:

### 1. **[JWT Tokens](jwt-tokens.md)** - Foundation
Understand how JWT tokens work, including access and refresh token management, verification, and blacklisting.

### 2. **[User Management](user-management.md)** - Core Features
Implement user registration, login, profile management, and administrative operations.

### 3. **[Permissions](permissions.md)** - Access Control
Use the shared permission-policy layer, then extend it with project-specific roles or permissions only where needed.

## Implementation Examples

### Quick Authentication Setup

```python
from app.api.dependencies import require_permissions
from app.platform.authorization import DEFAULT_PERMISSION_POLICY, TemplateRole


SUPPORT_POLICY = DEFAULT_PERMISSION_POLICY.extend(
    role_permissions={"support": {"tickets:reply"}},
    role_inheritance={"support": {TemplateRole.AUTHENTICATED}},
)


@router.post(
    "/tickets/{ticket_id}/reply",
    dependencies=[Depends(require_permissions("tickets:reply", policy=SUPPORT_POLICY))],
)
async def reply_to_ticket(ticket_id: int):
    return {"ticket_id": ticket_id}
```

### Frontend Integration

```javascript
// Basic authentication flow
class AuthManager {
    async login(username, password) {
        const response = await fetch('/api/v1/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: new URLSearchParams({username, password})
        });
        
        const tokens = await response.json();
        localStorage.setItem('access_token', tokens.access_token);
        return tokens;
    }
    
    async makeAuthenticatedRequest(url, options = {}) {
        const token = localStorage.getItem('access_token');
        return fetch(url, {
            ...options,
            headers: {
                ...options.headers,
                'Authorization': `Bearer ${token}`
            }
        });
    }
}
```

## What's Next

Start building your authentication system:

1. **[JWT Tokens](jwt-tokens.md)** - Learn token creation, verification, and lifecycle management
2. **[User Management](user-management.md)** - Implement registration, login, and profile operations  
3. **[Permissions](permissions.md)** - Add authorization patterns and access control

The authentication system provides a secure foundation for your API. Each guide includes practical examples and implementation details for production-ready authentication. 
