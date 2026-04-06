# JWT Tokens

JSON Web Tokens (JWT) form the backbone of modern web authentication. This guide explains the template's current token contract: signed access JWTs in the `Authorization` header, signed refresh JWTs in an HTTP-only cookie, and blacklist records for logout or other explicit revocation flows.

## Understanding JWT Authentication

JWT tokens are self-contained, digitally signed packages of information that can be safely transmitted between parties. Unlike traditional session-based authentication that requires server-side storage, JWT tokens are stateless: the token itself carries the claims needed for validation.

## Template Decision

Phase 4 Wave 4.1 formally keeps the default template posture as stateless JWT-only instead of moving the starter onto a server-backed refresh-session store or hybrid access/session model.

- **Access tokens**: short-lived JWTs sent in `Authorization` headers.
- **Refresh tokens**: longer-lived JWTs stored in an HTTP-only cookie.
- **Revocation path**: blacklist records for logout and other explicit invalidation events.
- **Built-in hardening hooks**: optional issuer/audience claims and key-id-based verification key rotation.
- **Built-in token lifecycle hardening**: refresh-token rotation on `/refresh` and a reusable cleanup command for expired blacklist rows.
- **Still deferred**: broader revocation retention policies beyond the baseline cleanup pattern remain later Phase 4 work.

This choice keeps the base template reusable and lightweight for cloned projects while staying honest about what the scaffold does and does not own today.

### Why Use JWT?

**Stateless Design**: No need to store session data on the server, making it perfect for distributed systems and microservices.

**Scalability**: Since tokens contain all necessary information, they work seamlessly across multiple servers without shared session storage.

**Security**: Digital signatures ensure tokens can't be tampered with, and expiration times limit exposure if compromised.

**Cross-Domain Support**: Unlike cookies, JWT tokens work across different domains and can be used in mobile applications.

## Token Types

The authentication system uses a **dual-token stateless approach**:

### Access Tokens

Access tokens are short-lived credentials that prove a user's identity for API requests. Think of them as temporary keys that grant access to protected resources.

- **Purpose**: Authenticate API requests and authorize actions
- **Lifetime**: 30 minutes (configurable) - short enough to limit damage if compromised
- **Storage**: Authorization header (`Bearer <token>`) - sent with each API request
- **Usage**: Include in every call to protected endpoints

**Why Short-Lived?** If an access token is stolen (e.g., through XSS), the damage window is limited to 30 minutes before it expires naturally.

### Refresh Tokens

Refresh tokens are longer-lived credentials used solely to generate new access tokens. They provide a balance between security and user convenience.

- **Purpose**: Generate new access tokens without requiring re-login
- **Lifetime**: 7 days (configurable) - long enough for good UX, short enough for security
- **Storage**: Secure HTTP-only cookie - inaccessible to JavaScript, preventing XSS attacks
- **Usage**: Automatically used by the browser when access tokens need refreshing
- **Server-side state**: No dedicated refresh-session table by default; blacklist entries are used for explicit invalidation

**Why HTTP-Only Cookies?** This prevents malicious JavaScript from accessing refresh tokens, providing protection against XSS attacks while allowing automatic renewal.

## Token Creation

Understanding how tokens are created helps you customize the authentication system for your specific needs.

### Creating Access Tokens

Access tokens are generated during login and token refresh operations. The process involves encoding user information with an expiration time and signing it with your secret key.

```python
from datetime import timedelta
from app.core.security import create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES

# Basic access token with default expiration
access_token = await create_access_token(data={"sub": username})

# Custom expiration for special cases (e.g., admin sessions)
custom_expires = timedelta(minutes=60)
access_token = await create_access_token(data={"sub": username}, expires_delta=custom_expires)
```

**When to Customize Expiration:**

- **High-security environments**: Shorter expiration (15 minutes)
- **Development/testing**: Longer expiration for convenience
- **Admin operations**: Variable expiration based on sensitivity

### Creating Refresh Tokens

Refresh tokens follow the same creation pattern but with longer expiration times. They're typically created only during login.

```python
from app.core.security import create_refresh_token, REFRESH_TOKEN_EXPIRE_DAYS

# Standard refresh token
refresh_token = await create_refresh_token(data={"sub": username})

# Extended refresh token for "remember me" functionality
extended_expires = timedelta(days=30)
refresh_token = await create_refresh_token(data={"sub": username}, expires_delta=extended_expires)
```

### Token Structure

JWT tokens consist of three parts separated by dots: `header.payload.signature`. The payload contains the actual user information and metadata.

```python
# Access token payload structure
{
    "sub": "username",  # Subject (user identifier)
    "exp": 1234567890,  # Expiration timestamp (Unix)
    "iss": "https://api.example.com",  # Optional configured issuer
    "aud": "template-api",  # Optional configured audience
    "token_type": "access",  # Distinguishes from refresh tokens
}

# Refresh token payload structure
{
    "sub": "username",  # Same user identifier
    "exp": 1234567890,  # Longer expiration time
    "iss": "https://api.example.com",  # Optional configured issuer
    "aud": "template-api",  # Optional configured audience
    "jti": "01962490-...",  # Unique refresh-token identifier for rotation
    "token_type": "refresh",  # Prevents confusion/misuse
}
```

**Key Fields Explained:**

- **`sub` (Subject)**: Identifies the user - can be username, email, or user ID
- **`exp` (Expiration)**: Unix timestamp when token becomes invalid
- **`iss` (Issuer)**: Optional issuer string enforced when `JWT_ISSUER` is configured
- **`aud` (Audience)**: Optional audience string enforced when `JWT_AUDIENCE` is configured
- **`jti` (JWT ID)**: Unique identifier on refresh tokens so `/refresh` can rotate to a distinct replacement token
- **`token_type`**: Custom field preventing tokens from being used incorrectly

The template still keeps the claim set intentionally lean, but it now supports optional `iss` and `aud` claims, a `kid` header for signing-key rotation, and refresh-token `jti` values so token rotation issues a distinct replacement token. Claims such as `iat` remain opt-in follow-on hardening work.

## Token Verification

Token verification is a multi-step process that ensures both the token's authenticity and the user's current authorization status.

### Verifying Access Tokens

Every protected endpoint must verify the access token before processing the request. This involves checking the signature, expiration, and blacklist status.

```python
from app.core.security import verify_token, TokenType

# Verify access token in endpoint
token_data = await verify_token(token, TokenType.ACCESS, db)
if token_data:
    username = token_data.username_or_email
    # Token is valid, proceed with request processing
else:
    # Token is invalid, expired, or blacklisted
    raise UnauthorizedException("Invalid or expired token")
```

### Verifying Refresh Tokens

Refresh token verification follows the same process but with different validation rules and outcomes.

```python
# Verify refresh token for renewal
token_data = await verify_token(token, TokenType.REFRESH, db)
if token_data:
    # Consume the current refresh token and mint a new pair
    new_access_token, new_refresh_token = await rotate_refresh_token(
        refresh_token=token,
        subject=token_data.username_or_email,
        db=db,
    )
    set_refresh_token_cookie(
        response,
        refresh_token=new_refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        cookie_settings=settings,
    )
    return {"access_token": new_access_token, "token_type": "bearer"}
else:
    # Refresh token invalid - user must log in again
    raise UnauthorizedException("Invalid refresh token")
```

### Token Verification Process

The verification process includes several security checks to prevent various attack vectors:

```python
async def verify_token(token: str, expected_token_type: TokenType, db: AsyncSession) -> TokenData | None:
    # 1. Check blacklist first (prevents use of logged-out tokens)
    is_blacklisted = await crud_token_blacklist.exists(db, token=token)
    if is_blacklisted:
        return None

    try:
        # 2. Verify signature, issuer, and audience with the configured key ring
        payload = decode_token_payload(token)

        # 3. Extract and validate claims
        username_or_email: str | None = payload.get("sub")
        token_type: str | None = payload.get("token_type")

        # 4. Ensure token type matches expectation
        if username_or_email is None or token_type != expected_token_type:
            return None

        # 5. Return validated data
        return TokenData(username_or_email=username_or_email)

    except JWTError:
        # Token is malformed, expired, or signature invalid
        return None
```

**Security Checks Explained:**

1. **Blacklist Check**: Prevents use of tokens from logged-out users
1. **Signature Verification**: Ensures token hasn't been tampered with
1. **Issuer / Audience Validation**: Enforced whenever `JWT_ISSUER` or `JWT_AUDIENCE` are configured
1. **Expiration Check**: Automatically handled by JWT library
1. **Type Validation**: Prevents refresh tokens from being used as access tokens
1. **Subject Validation**: Ensures token contains valid user identifier

## Client-Side Authentication Flow

Understanding the complete authentication flow helps frontend developers integrate properly with the API.

### Recommended Client Flow

**1. Login Process**

```javascript
// Send credentials to login endpoint
const response = await fetch('/api/v1/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'username=user&password=pass',
    credentials: 'include'  // Important: includes cookies
});

const { access_token, token_type } = await response.json();

// Store access token in memory (not localStorage)
sessionStorage.setItem('access_token', access_token);
```

**2. Making Authenticated Requests**

```javascript
// Include access token in Authorization header
const response = await fetch('/api/v1/protected-endpoint', {
    headers: {
        'Authorization': `Bearer ${sessionStorage.getItem('access_token')}`
    },
    credentials: 'include'
});
```

**3. Handling Token Expiration**

```javascript
// Automatic token refresh on 401 errors
async function apiCall(url, options = {}) {
    let response = await fetch(url, {
        ...options,
        headers: {
            ...options.headers,
            'Authorization': `Bearer ${sessionStorage.getItem('access_token')}`
        },
        credentials: 'include'
    });

    // If token expired, try to refresh
    if (response.status === 401) {
        const refreshResponse = await fetch('/api/v1/refresh', {
            method: 'POST',
            credentials: 'include'  // Sends refresh token cookie
        });

        if (refreshResponse.ok) {
            const { access_token } = await refreshResponse.json();
            sessionStorage.setItem('access_token', access_token);

            // Retry original request
            response = await fetch(url, {
                ...options,
                headers: {
                    ...options.headers,
                    'Authorization': `Bearer ${access_token}`
                },
                credentials: 'include'
            });
        } else {
            // Refresh failed - redirect to login
            window.location.href = '/login';
        }
    }

    return response;
}
```

**4. Logout Process**

```javascript
// Clear tokens and call logout endpoint
await fetch('/api/v1/logout', {
    method: 'POST',
    credentials: 'include'
});

sessionStorage.removeItem('access_token');
// Refresh token cookie is cleared by server
```

### Cookie Configuration

The refresh token cookie is configured for maximum security:

```python
response.set_cookie(
    key="refresh_token",
    value=refresh_token,
    httponly=True,  # Prevents JavaScript access (XSS protection)
    secure=True,  # HTTPS only in production
    samesite="Lax",  # CSRF protection with good usability
    max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
)
```

**SameSite Options:**

- **`Lax`** (Recommended): Cookies sent on top-level navigation but not cross-site requests
- **`Strict`**: Maximum security but may break some user flows
- **`None`**: Required for cross-origin requests (must use with Secure)

### CSRF Review For Refresh Cookies

The template keeps cookie usage intentionally narrow: `/login` can set the refresh cookie, `/refresh` rotates it, and `/logout` clears it. The rest of the built-in API auth surface uses the `Authorization` header instead of a browser session cookie.

That baseline reduces CSRF exposure, but it is important to understand the limits:

- `HttpOnly` protects the refresh cookie from JavaScript, which is an XSS mitigation, not a CSRF mitigation
- `SameSite="lax"` is the default because it blocks common cross-site POST-style attacks while remaining usable for same-site browser apps
- `SameSite="strict"` is safer when your frontend does not need cross-site or top-level-navigation cookie behavior
- `SameSite="none"` should be treated as an opt-in escape hatch for a different-site frontend, and it should always be paired with explicit CSRF defenses

`CORS` controls whether a browser exposes a response to frontend code; it does not stop the browser from sending a cookie on a forged request.

If a cloned project needs cookie-authenticated requests from a different site or adds additional cookie-authenticated `POST`, `PUT`, `PATCH`, or `DELETE` routes, add one of these reusable patterns before expanding the surface:

- strict `Origin` and `Referer` validation against an explicit allowlist
- a double-submit or synchronizer CSRF token
- a design change that keeps mutation auth in `Authorization` headers instead of cookies

For the built-in defaults, the recommended posture is to keep `REFRESH_TOKEN_COOKIE_SAMESITE="lax"` or move to `"strict"` where possible, leave the admin UI disabled unless it is needed, and keep machine clients on headers or API keys rather than cookies.

## Token Blacklisting

Token blacklisting solves a fundamental problem with JWT tokens: once issued, they remain valid until expiration, even if the user logs out. Blacklisting provides immediate token revocation.

### Why Blacklisting Matters

Without blacklisting, logged-out users could continue accessing your API until their tokens naturally expire. This creates security risks, especially on shared computers or if tokens are compromised.

### Blacklisting Implementation

The system uses a database table to track invalidated tokens:

```python
# models/token_blacklist.py
class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(unique=True, index=True)  # Full token string
    expires_at: Mapped[datetime] = mapped_column()  # When to clean up
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
```

**Design Considerations:**

- **Unique constraint**: Prevents duplicate entries
- **Index on token**: Fast lookup during verification
- **Expires_at field**: Enables automatic cleanup of old entries

### Blacklisting Tokens

The system provides functions for both single token and dual token blacklisting:

```python
from app.core.security import blacklist_token, blacklist_tokens

# Single token blacklisting (for specific scenarios)
await blacklist_token(token, db)

# Dual token blacklisting (standard logout)
await blacklist_tokens(access_token, refresh_token, db)
```

### Blacklisting Process

The blacklisting process extracts the expiration time from the token to set an appropriate cleanup schedule:

```python
async def blacklist_token(token: str, db: AsyncSession) -> None:
    # 1. Decode token to extract expiration (no verification needed)
    payload = jwt.decode(token, SECRET_KEY.get_secret_value(), algorithms=[ALGORITHM])
    exp_timestamp = payload.get("exp")

    if exp_timestamp is not None:
        # 2. Convert Unix timestamp to datetime
        expires_at = datetime.fromtimestamp(exp_timestamp)

        # 3. Store in blacklist with expiration
        await crud_token_blacklist.create(db, object=TokenBlacklistCreate(token=token, expires_at=expires_at))
```

**Cleanup Strategy**: Blacklisted tokens can be automatically removed from the database after their natural expiration time, preventing unlimited database growth.

```bash
uv run cleanup-token-blacklist
```

The cleanup command uses the shared script-scope database session helpers and deletes rows whose `expires_at` is older than the current time, giving cloned projects a reusable baseline retention strategy without assuming one scheduler or deployment topology.

## Login Flow Implementation

### Complete Login Endpoint

```python
@router.post("/login", response_model=Token)
async def login_for_access_token(
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    # 1. Authenticate user
    user = await authenticate_user(username_or_email=form_data.username, password=form_data.password, db=db)

    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    # 2. Create access token
    access_token = await create_access_token(data={"sub": user["username"]})

    # 3. Create refresh token
    refresh_token = await create_refresh_token(data={"sub": user["username"]})

    # 4. Set refresh token as HTTP-only cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )

    return {"access_token": access_token, "token_type": "bearer"}
```

### Token Refresh Endpoint

```python
@router.post("/refresh", response_model=Token)
async def refresh_access_token(
    response: Response,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    refresh_token: str = Cookie(None),
) -> dict[str, str]:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")

    # 1. Verify refresh token
    token_data = await verify_token(refresh_token, TokenType.REFRESH, db)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # 2. Rotate the refresh token and set the replacement cookie
    new_access_token, new_refresh_token = await rotate_refresh_token(
        refresh_token=refresh_token,
        subject=token_data.username_or_email,
        db=db,
    )
    set_refresh_token_cookie(
        response,
        refresh_token=new_refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        cookie_settings=settings,
    )
    return {"access_token": new_access_token, "token_type": "bearer"}
```

The default template now rotates refresh tokens during `/refresh`. Once a refresh succeeds, the previous refresh token is blacklisted, so replaying the old cookie fails instead of minting another token pair.

### Logout Implementation

```python
@router.post("/logout")
async def logout(
    response: Response,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: dict = Depends(get_current_user),
    token: str = Depends(oauth2_scheme),
    refresh_token: str = Cookie(None),
) -> dict[str, str]:
    # 1. Blacklist access token
    await blacklist_token(token, db)

    # 2. Blacklist refresh token if present
    if refresh_token:
        await blacklist_token(refresh_token, db)

    # 3. Clear refresh token cookie
    response.delete_cookie(key="refresh_token", httponly=True, secure=True, samesite="strict")

    return {"message": "Successfully logged out"}
```

## Authentication Dependencies

### get_current_user

```python
async def get_current_user(db: AsyncSession = Depends(async_get_db), token: str = Depends(oauth2_scheme)) -> dict:
    # 1. Verify token
    token_data = await verify_token(token, TokenType.ACCESS, db)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid token")

    # 2. Get user from database
    user = await crud_users.get(db=db, username=token_data.username_or_email, schema_to_select=UserRead)

    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    return user
```

### get_current_principal

Routes that use the shared authorization helpers now authenticate either a bearer-token user or a configured machine principal:

```python
async def get_current_principal(
    request: Request,
    db: AsyncSession = Depends(async_get_db),
) -> dict[str, Any]:
    api_key = request.headers.get(settings.API_KEY_HEADER_NAME)
    if api_key is not None:
        principal = resolve_api_key_principal(api_key)
        if principal is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return principal

    authorization = request.headers.get("Authorization")
    if authorization:
        token_type, _, token_value = authorization.partition(" ")
        if token_type.lower() != "bearer" or not token_value:
            raise HTTPException(status_code=401, detail="Invalid Authorization header")
        return await get_current_user(token=token_value, db=db)

    raise HTTPException(status_code=401, detail="Authentication required")
```

Keep this distinction in mind:

- `get_current_user(...)` remains the reusable user-only JWT dependency.
- `get_current_principal(...)` is the template's mixed auth boundary for permission-protected routes and internal hooks.
- `get_current_superuser(...)` still assumes a human user model, not a machine principal.

### get_optional_user

```python
async def get_optional_user(
    db: AsyncSession = Depends(async_get_db), token: str = Depends(optional_oauth2_scheme)
) -> dict | None:
    if not token:
        return None

    try:
        return await get_current_user(db=db, token=token)
    except HTTPException:
        return None
```

### get_current_superuser

```python
async def get_current_superuser(current_user: dict = Depends(get_current_user)) -> dict:
    if not current_user.get("is_superuser", False):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user
```

## Configuration

### Environment Variables

```bash
# JWT Configuration
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
JWT_ISSUER=https://api.example.com
JWT_AUDIENCE=template-api
JWT_ACTIVE_KEY_ID=2026-04
JWT_VERIFICATION_KEYS='{"2026-01":"previous-signing-secret"}'

# Optional machine-principal auth
API_KEY_ENABLED=true
API_KEY_HEADER_NAME=X-API-Key
API_KEY_PRINCIPALS='{"internal-worker":{"key":"change-me-machine-secret","permissions":["platform:internal:access"],"tenant_id":"tenant-123","organization_id":"org-123"}}'

# Security Headers
SECURE_COOKIES=true
CORS_ORIGINS=["http://localhost:3000","https://yourapp.com"]
```

### Security Configuration

```python
# app/core/config.py
class Settings(BaseSettings):
    SECRET_KEY: SecretStr
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    PASSWORD_HASH_SCHEME: PasswordHashScheme = PasswordHashScheme.BCRYPT
    PASSWORD_BCRYPT_ROUNDS: int = 12
    PASSWORD_HASH_REHASH_ON_LOGIN: bool = True
    JWT_ISSUER: str | None = None
    JWT_AUDIENCE: str | None = None
    JWT_ACTIVE_KEY_ID: str = "primary"
    JWT_VERIFICATION_KEYS: dict[str, SecretStr] = {}
    API_KEY_ENABLED: bool = False
    API_KEY_HEADER_NAME: str = "X-API-Key"
    API_KEY_PRINCIPALS: dict[str, APIKeyPrincipalSettings] = {}

    # Cookie settings
    REFRESH_TOKEN_COOKIE_SECURE: bool = True
    REFRESH_TOKEN_COOKIE_DOMAIN: str | None = None
    REFRESH_TOKEN_COOKIE_SAMESITE: str = "lax"
    SESSION_SECURE_COOKIES: bool = True
```

## Security Best Practices

### Token Security

- **Use strong secrets**: Generate cryptographically secure SECRET_KEY
- **Rotate secrets deliberately**: Move the current signing secret into `JWT_VERIFICATION_KEYS`, assign a new `SECRET_KEY`, and update `JWT_ACTIVE_KEY_ID`
- **Environment separation**: Different secrets for dev/staging/production
- **Secure transmission**: Always use HTTPS in production

### Cookie Security

- **HttpOnly flag**: Prevents JavaScript access to refresh tokens
- **Secure flag**: Ensures cookies only sent over HTTPS
- **SameSite attribute**: Prevents CSRF attacks
- **Domain restrictions**: Set cookie domain appropriately

### Implementation Security

- **Input validation**: Validate all token inputs
- **Rate limiting**: Implement login attempt limits
- **Audit logging**: Log authentication events
- **Token rotation**: Regularly refresh tokens

## Common Patterns

### API Key Authentication

For internal hooks, workers, and machine clients that do not need an end-user session, the template now provides a settings-backed API-key pattern instead of assuming a client-specific database table.

Configure named machine principals with explicit permissions and optional tenant context:

```python
from pydantic import SecretStr

from app.core.config import APIKeyPrincipalSettings, MachineAuthSettings


machine_auth_settings = MachineAuthSettings(
    API_KEY_ENABLED=True,
    API_KEY_PRINCIPALS={
        "internal-worker": APIKeyPrincipalSettings(
            key=SecretStr("change-me-machine-secret"),
            permissions=["platform:internal:access"],
            scopes=["jobs:enqueue"],
            tenant_id="tenant-123",
            organization_id="org-123",
        )
    },
)
```

At request time, the shared auth layer resolves those principals without touching the user table:

```python
from app.core.security import build_api_key_auth_headers, resolve_api_key_principal


headers = build_api_key_auth_headers(
    api_key="change-me-machine-secret",
    machine_auth_settings=machine_auth_settings,
)

principal = resolve_api_key_principal(
    headers["X-API-Key"],
    machine_auth_settings=machine_auth_settings,
)

assert principal == {
    "id": "service:internal-worker",
    "username": "internal-worker",
    "principal_type": "service",
    "permissions": ["platform:internal:access"],
    "scopes": ["jobs:enqueue"],
    "tenant_context": {
        "tenant_id": "tenant-123",
        "organization_id": "org-123",
    },
    ...
}
```

Use this pattern when:

- an internal diagnostic or operator endpoint should allow either bearer auth or a trusted machine caller
- a worker or scheduler needs stable service-to-service credentials
- a cloned project wants to carry tenant or organization context through machine auth before a full tenant-membership model exists

Avoid treating this baseline pattern as a full API-key product. The template does not yet ship rotation workflows, persistent key storage, per-key auditing, or lifecycle management.

## Troubleshooting

### Common Issues

**Token Expired**: Implement automatic refresh using refresh tokens
**Invalid Signature**: Check SECRET_KEY consistency across environments
**Blacklisted Token**: User logged out - redirect to login
**Missing Token**: Ensure Authorization header is properly set

### Debugging Tips

```python
# Enable debug logging
import logging

logging.getLogger("app.core.security").setLevel(logging.DEBUG)

# Test token validation
async def debug_token(token: str, db: AsyncSession):
    try:
        payload = jwt.decode(token, SECRET_KEY.get_secret_value(), algorithms=[ALGORITHM])
        print(f"Token payload: {payload}")

        is_blacklisted = await crud_token_blacklist.exists(db, token=token)
        print(f"Is blacklisted: {is_blacklisted}")

    except JWTError as e:
        print(f"JWT Error: {e}")
```

This comprehensive JWT implementation provides secure, scalable authentication for your FastAPI application.
