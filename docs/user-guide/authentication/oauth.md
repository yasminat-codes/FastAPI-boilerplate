# OAuth Authentication

This application supports OAuth 2.0 authentication with multiple providers, allowing users to sign in using their existing accounts from GitHub, Google, or Microsoft.

## Overview

OAuth provides a secure way for users to authenticate without creating a new password. Users created through OAuth:

- **Do not have passwords** - `hashed_password` is `NULL`
- **Cannot use password authentication** - Password login is automatically rejected for OAuth users
- **Can only authenticate via their OAuth provider**
- **Have usernames from email** - Username is extracted from the email's local part and converted to lowercase

## Supported Providers

### GitHub OAuth
- **Login endpoint**: `/api/v1/login/github`
- **Callback endpoint**: `/api/v1/callback/github`

### Google OAuth
- **Login endpoint**: `/api/v1/login/google`
- **Callback endpoint**: `/api/v1/callback/google`

### Microsoft OAuth
- **Login endpoint**: `/api/v1/login/microsoft`
- **Callback endpoint**: `/api/v1/callback/microsoft`

## Configuration

### Environment Variables

Add the following to your `.env` file (in `src/`):

```bash
# Backend URL for OAuth callbacks
APP_BACKEND_HOST="http://localhost:8000"

# GitHub OAuth
GITHUB_CLIENT_ID="your_github_client_id"
GITHUB_CLIENT_SECRET="your_github_client_secret"

# Google OAuth
GOOGLE_CLIENT_ID="your_google_client_id"
GOOGLE_CLIENT_SECRET="your_google_client_secret"

# Microsoft OAuth
MICROSOFT_CLIENT_ID="your_microsoft_client_id"
MICROSOFT_CLIENT_SECRET="your_microsoft_client_secret"
MICROSOFT_TENANT="your_microsoft_tenant_id"
```

### Provider Setup

#### GitHub

1. Go to [GitHub Developer Settings](https://github.com/settings/developers)
2. Click "New OAuth App"
3. Configure:
   - **Application name**: Your app name
   - **Homepage URL**: `http://localhost:8000` (or your production URL)
   - **Authorization callback URL**: `http://localhost:8000/api/v1/callback/github`
4. Copy the **Client ID** and **Client Secret**

#### Google

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a project (if needed)
3. Configure OAuth consent screen:
   - Choose "External"
   - Add your email as a test user
4. Create OAuth 2.0 Client ID:
   - Type: "Web application"
   - **Authorized redirect URIs**: `http://localhost:8000/api/v1/callback/google`
5. Copy the **Client ID** and **Client Secret**

#### Microsoft

1. Go to [Azure Portal](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps)
2. Click "New registration"
3. Configure:
   - **Name**: Your app name
   - **Redirect URI**: `http://localhost:8000/api/v1/callback/microsoft`
4. Copy the **Application (client) ID**, **Client Secret**, and **Directory (tenant) ID**

### Provider Enablement

Providers are automatically enabled when their credentials are configured. If credentials are missing or incomplete, the provider's routes will not be registered.

## OAuth Flow

### 1. Login Initiation

User navigates to the login endpoint:

```bash
GET /api/v1/login/{provider}
# Example: GET /api/v1/login/github
```

The application redirects the user to the OAuth provider's authorization page.

### 2. User Authorization

The user authorizes the application on the provider's website.

### 3. Callback Processing

The provider redirects back to the callback endpoint with an authorization code:

```bash
GET /api/v1/callback/{provider}?code=AUTHORIZATION_CODE
```

The application:

1. Exchanges the code for an access token
2. Retrieves user information (email, name, username)
3. Checks if a user with that email exists:
   - **If exists**: Logs in the existing user
   - **If new**: Creates a new user with `hashed_password = NULL`
4. Returns JWT tokens

### 4. Response

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

A refresh token is also set as an HTTP-only cookie.

## Username Extraction

Usernames are derived from the user's email address:

**Validation pattern**: `^[a-z0-9._+-]+$` (lowercase letters, numbers, and valid email characters: `.` `_` `+` `-`)

**Extraction process**:
1. Extract username from email (part before `@`)
2. Convert to lowercase

**Examples**:

| Email | Derived Username |
|-------|-----------------|
| `john.doe@example.com` | `john.doe` |
| `Jane_Smith@example.com` | `jane_smith` |
| `user+tag@example.com` | `user+tag` |
| `Test.User-123@example.com` | `test.user-123` |

The username keeps all valid email local part characters (letters, numbers, `.`, `_`, `+`, `-`) and only converts to lowercase. This aligns perfectly with email standards and ensures usernames match the validation pattern.

## Security Features

### NULL Password Protection

OAuth users have `hashed_password = NULL` in the database. This provides several security benefits:

1. **Prevents password authentication**: Password login is automatically rejected for OAuth users
2. **No password to compromise**: OAuth users cannot have their passwords leaked
3. **Forces OAuth authentication**: Users must authenticate through their OAuth provider

The authentication function explicitly checks for NULL passwords:

```python
if db_user["hashed_password"] is None:
    return False  # Reject authentication
```

### Schema-Level Protection

NULL passwords can only be created through OAuth:

- **Public API** (`/user` endpoint) requires `UserCreate` schema with a mandatory `password` field
- **OAuth flow** uses internal `UserCreateInternal` schema that allows `hashed_password: None`
- **No way to bypass**: FastAPI validates all incoming requests against the schema

### Mixed Authentication Warning

If both password authentication and OAuth are enabled, a warning is logged:

```
Both password authentication and {provider} OAuth are enabled.
For enterprise or B2B deployments, it is recommended to disable password
authentication by setting ENABLE_PASSWORD_AUTH=false and relying solely on OAuth.
```

To disable password authentication, set in `.env`:

```bash
ENABLE_PASSWORD_AUTH=false
```

## Using OAuth Tokens

After receiving the access token, include it in API requests:

### Authorization Header

```bash
curl -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
     http://localhost:8000/api/v1/users/me
```

### In API Documentation

1. Go to `http://localhost:8000/docs`
2. Click "Authorize" button
3. Enter: `Bearer YOUR_ACCESS_TOKEN`
4. Test authenticated endpoints

## Frontend Integration

### Basic Flow

```javascript
// Step 1: Redirect user to OAuth login
window.location.href = 'http://localhost:8000/api/v1/login/github';

// Step 2: Handle callback (your frontend callback page)
// Extract tokens from the response
const response = await fetch(window.location.href);
const { access_token } = await response.json();

// Step 3: Store and use the token
localStorage.setItem('access_token', access_token);

// Step 4: Make authenticated requests
fetch('http://localhost:8000/api/v1/users/me', {
  headers: {
    'Authorization': `Bearer ${access_token}`
  }
});
```

### Using Refresh Tokens

The refresh token is automatically stored as an HTTP-only cookie. To refresh the access token:

```javascript
const response = await fetch('http://localhost:8000/api/v1/refresh', {
  method: 'POST',
  credentials: 'include' // Include cookies
});

const { access_token } = await response.json();
```

## Database Schema

OAuth users are stored with the following characteristics:

```sql
-- OAuth user example
INSERT INTO "user" (
    name,
    username,
    email,
    hashed_password,  -- NULL for OAuth users
    profile_image_url,
    created_at,
    is_superuser
) VALUES (
    'John Doe',
    'johndoe',
    'john.doe@example.com',
    NULL,  -- No password
    'https://avatars.github.com/...',
    NOW(),
    false
);
```

## Testing OAuth

### Manual Testing

1. **Configure credentials** in `.env`
2. **Start the application**:
   ```bash
   docker compose up
   ```
3. **Open browser** to `http://localhost:8000/api/v1/login/github`
4. **Authorize** the application
5. **Verify** you receive an access token

### Automated Testing

See `tests/test_oauth.py` for comprehensive OAuth tests including:

- Provider enablement logic
- Username extraction from emails
- User creation with NULL passwords
- Callback handling
- Security validations

Run tests:

```bash
uv run pytest tests/test_oauth.py -v
```

## Troubleshooting

### Routes Not Found (404)

**Problem**: `/api/v1/login/github` returns 404

**Solution**: The provider is disabled because credentials are missing or incomplete. Check:
- `GITHUB_CLIENT_ID` is set
- `GITHUB_CLIENT_SECRET` is set
- Restart the application after adding credentials

### Callback URL Mismatch

**Problem**: Error during callback about redirect URI mismatch

**Solution**: Ensure the callback URL in the provider settings exactly matches:
```
http://localhost:8000/api/v1/callback/{provider}
```

### Database Constraint Error

**Problem**: `NULL value in column "hashed_password" violates not-null constraint`

**Solution**: The database schema hasn't been updated. Run:

```bash
docker compose exec db psql -U postgres -d postgres \
  -c "ALTER TABLE \"user\" ALTER COLUMN hashed_password DROP NOT NULL;"
```

### Username Validation Error

**Problem**: `String should match pattern '^[a-z0-9._+-]+$'`

**Solution**: The username contains characters not allowed in the pattern. Valid characters are:
- Lowercase letters (a-z)
- Numbers (0-9)
- Period (`.`), underscore (`_`), plus (`+`), hyphen (`-`)

This should not occur with standard email addresses, as the extraction process preserves these valid characters. If you see this error, the email address may contain unusual characters not supported by standard email specifications.

## Architecture

### Base OAuth Provider

All OAuth providers inherit from `BaseOAuthProvider`, ensuring consistent behavior:

```python
class BaseOAuthProvider(ABC):
    provider_config: dict[str, Any]
    sso_provider: type[SSOBase]

    async def _login_handler(self) -> RedirectResponse:
        # Redirects to OAuth provider

    async def _callback_handler(self, request, response, db):
        # Handles OAuth callback and user creation

    async def _get_user_details(self, oauth_user) -> UserCreateInternal:
        # Extracts username from email and creates user object
```

### Adding a New Provider

To add support for a new OAuth provider:

1. Install the provider's SSO library
2. Create a new provider class:

```python
class NewOAuthProvider(BaseOAuthProvider):
    sso_provider = NewProviderSSO
    provider_config = {
        "client_id": settings.NEW_PROVIDER_CLIENT_ID,
        "client_secret": settings.NEW_PROVIDER_CLIENT_SECRET,
    }

# Register the provider
NewOAuthProvider(router)
```

3. Add configuration to `settings.py`
4. Add credentials to `.env`

## Best Practices

### Production Deployment

1. **Use HTTPS**: Set `APP_BACKEND_HOST=https://your-domain.com`
2. **Update callback URLs** in provider settings
3. **Disable password auth** for OAuth-only deployments
4. **Secure credentials**: Never commit `.env` to version control
5. **Use environment-specific credentials**: Different keys for dev/staging/production

### Security Considerations

1. **Validate redirect URIs**: Only allow specific callback URLs
2. **Use HTTPS in production**: OAuth tokens should never be transmitted over HTTP
3. **Implement rate limiting**: Prevent OAuth callback abuse
4. **Monitor failed attempts**: Log and alert on repeated OAuth failures
5. **Review OAuth scopes**: Only request necessary permissions from providers

### User Experience

1. **Clear error messages**: Inform users when OAuth fails
2. **Handle edge cases**: Users without email addresses, denied permissions
3. **Provide alternatives**: Offer both OAuth and password auth (if applicable)
4. **Account linking**: Allow users to link multiple OAuth providers to one account (future enhancement)
