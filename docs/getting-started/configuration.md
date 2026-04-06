# Configuration

This guide covers the essential configuration steps to get your FastAPI application running quickly.

## Quick Setup

The fastest way to get started is to copy the example environment file and modify just a few values:

```bash
cp src/.env.example src/.env
```

## Essential Configuration

Open `src/.env` and set these required values:

### Application Settings

```env
# App Settings
APP_NAME="Your app name here"
APP_DESCRIPTION="Your app description here"
APP_VERSION="0.1"
CONTACT_NAME="Your name"
CONTACT_EMAIL="Your email"
LICENSE_NAME="The license you picked"
```

### Database Connection

```env
# Preferred: one first-class database URL
DATABASE_URL="postgresql://your_postgres_user:your_password@localhost:5432/your_database_name"

# Optional fallback: composed PostgreSQL parts
POSTGRES_USER="your_postgres_user"
POSTGRES_PASSWORD="your_password"
POSTGRES_SERVER="localhost"  # Use "db" for Docker Compose
POSTGRES_PORT=5432           # Use 5432 for Docker Compose
POSTGRES_DB="your_database_name"
```

`DATABASE_URL` is the canonical setting used by the application runtime, Alembic migrations, and test helpers. If you do not supply it, the template composes the same connection from `POSTGRES_*` values.

Optional database runtime tuning is also available when you need stricter production controls:

```env
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
DATABASE_POOL_PRE_PING=true
DATABASE_POOL_USE_LIFO=true
DATABASE_POOL_RECYCLE=1800
DATABASE_POOL_TIMEOUT=30
DATABASE_CONNECT_TIMEOUT=10
DATABASE_COMMAND_TIMEOUT=60
DATABASE_STATEMENT_TIMEOUT_MS=30000
DATABASE_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS=60000
DATABASE_STARTUP_RETRY_ATTEMPTS=3
DATABASE_STARTUP_RETRY_BASE_DELAY=0.5
DATABASE_STARTUP_RETRY_MAX_DELAY=5.0
DATABASE_SSL_MODE="disable"  # disable, require, verify-ca, verify-full
DATABASE_SSL_CA_FILE="/path/to/ca.pem"      # required for verify-ca / verify-full
DATABASE_SSL_CERT_FILE="/path/to/client.crt"  # optional client certificate
DATABASE_SSL_KEY_FILE="/path/to/client.key"   # optional client key
```

For the full database reliability contract, including session scoping rules, timeout strategy, retry guidance, and SSL behavior, see [Database Reliability](../user-guide/database/reliability.md).

### PGAdmin (Optional)

For database administration:

```env
# PGAdmin
PGADMIN_DEFAULT_EMAIL="your_email_address"
PGADMIN_DEFAULT_PASSWORD="your_password"
PGADMIN_LISTEN_PORT=80
```

**To connect to database in PGAdmin:**

1. Login with `PGADMIN_DEFAULT_EMAIL` and `PGADMIN_DEFAULT_PASSWORD`
1. Click "Add Server"
1. Use these connection settings:
   - **Hostname/address**: `db` (if using containers) or `localhost`
   - **Port**: Value from `POSTGRES_PORT`
   - **Database**: `postgres` (leave as default)
   - **Username**: Value from `POSTGRES_USER`
   - **Password**: Value from `POSTGRES_PASSWORD`

### Security

Generate a secret key and set it:

```bash
# Generate a secure secret key
openssl rand -hex 32
```

```env
# Cryptography
SECRET_KEY="your-generated-secret-key-here"  # Result of openssl rand -hex 32
ALGORITHM="HS256"                            # Default: HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30               # Default: 30
REFRESH_TOKEN_EXPIRE_DAYS=7                  # Default: 7
```

### First Admin User

```env
# Admin User
ADMIN_NAME="your_name"
ADMIN_EMAIL="your_email"
ADMIN_USERNAME="your_username"
ADMIN_PASSWORD="your_password"
```

### Redis Configuration

```env
# Redis Cache
REDIS_CACHE_HOST="localhost"     # Use "redis" for Docker Compose
REDIS_CACHE_PORT=6379
REDIS_CACHE_DB=0
REDIS_CACHE_CONNECT_TIMEOUT=5
REDIS_CACHE_SOCKET_TIMEOUT=5
REDIS_CACHE_RETRY_ATTEMPTS=3
REDIS_CACHE_SSL=false

# Client-side Cache
CLIENT_CACHE_MAX_AGE=30          # Default: 30 seconds

# Redis Job Queue
REDIS_QUEUE_HOST="localhost"     # Use "redis" for Docker Compose
REDIS_QUEUE_PORT=6379
REDIS_QUEUE_DB=0
REDIS_QUEUE_CONNECT_TIMEOUT=5
REDIS_QUEUE_CONNECT_RETRIES=5
REDIS_QUEUE_SSL=false

# Worker Runtime
WORKER_QUEUE_NAME="arq:queue"
WORKER_MAX_JOBS=10
WORKER_JOB_MAX_TRIES=3
WORKER_JOB_RETRY_DELAY_SECONDS=5.0
WORKER_KEEP_RESULT_SECONDS=3600
WORKER_KEEP_RESULT_FOREVER=false
WORKER_JOB_EXPIRES_EXTRA_MS=86400000

# Redis Rate Limiting
REDIS_RATE_LIMIT_HOST="localhost"  # Use "redis" for Docker Compose
REDIS_RATE_LIMIT_PORT=6379
REDIS_RATE_LIMIT_DB=0
REDIS_RATE_LIMIT_CONNECT_TIMEOUT=5
REDIS_RATE_LIMIT_SOCKET_TIMEOUT=5
REDIS_RATE_LIMIT_RETRY_ATTEMPTS=3
REDIS_RATE_LIMIT_SSL=false

# Webhook Runtime
WEBHOOK_SIGNATURE_VERIFICATION_ENABLED=true
WEBHOOK_SIGNATURE_MAX_AGE_SECONDS=300
WEBHOOK_REPLAY_PROTECTION_ENABLED=true
WEBHOOK_REPLAY_WINDOW_SECONDS=300
WEBHOOK_STORE_RAW_PAYLOADS=true
WEBHOOK_PAYLOAD_RETENTION_DAYS=7

# Observability
SENTRY_ENABLE=false
# SENTRY_DSN="https://public@example.ingest.sentry.io/1"
SENTRY_ENVIRONMENT="local"
SENTRY_RELEASE="fastapi-template@0.1.0"
SENTRY_DEBUG=false
SENTRY_ATTACH_STACKTRACE=true
SENTRY_SEND_DEFAULT_PII=false
SENTRY_MAX_BREADCRUMBS=100
SENTRY_TRACES_SAMPLE_RATE=1.0
SENTRY_PROFILES_SAMPLE_RATE=1.0
METRICS_ENABLED=false
METRICS_PATH="/metrics"
METRICS_NAMESPACE="fastapi_template"
METRICS_INCLUDE_REQUEST_PATH_LABELS=false
TRACING_ENABLED=false
TRACING_EXPORTER="otlp"
TRACING_SAMPLE_RATE=1.0
TRACING_SERVICE_NAME="fastapi-template-api"
TRACING_PROPAGATE_CORRELATION_IDS=true
LOG_LEVEL="INFO"
UVICORN_LOG_LEVEL="INFO"
FILE_LOG_LEVEL="INFO"
CONSOLE_LOG_LEVEL="INFO"
```

!!! warning "Redis in Production"
You may use the same Redis instance for caching and queues while developing, but use separate containers in production.

### Rate Limiting Defaults

```env
# Default Rate Limits
DEFAULT_RATE_LIMIT_LIMIT=10      # Default: 10 requests
DEFAULT_RATE_LIMIT_PERIOD=3600   # Default: 3600 seconds (1 hour)
```

### CORS Configuration

Configure Cross-Origin Resource Sharing for your frontend:

```env
# CORS Settings
CORS_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000"]  # Explicit origins; secure envs default to no cross-origin access
CORS_ALLOW_CREDENTIALS=true
CORS_METHODS=["GET","POST","PUT","PATCH","DELETE","OPTIONS"]
CORS_HEADERS=["Accept","Authorization","Content-Type","X-Requested-With","X-Request-ID","X-Correlation-ID"]
CORS_EXPOSE_HEADERS=["X-Request-ID","X-Correlation-ID"]
CORS_MAX_AGE=600
```

!!! warning "CORS in Production"
Specify exact domains for production and staging:
`env     CORS_ORIGINS=["https://yourapp.com","https://www.yourapp.com"]     CORS_ALLOW_CREDENTIALS=true     CORS_METHODS=["GET","POST","PUT","DELETE","PATCH"]     CORS_HEADERS=["Authorization","Content-Type","X-Request-ID","X-Correlation-ID"]     CORS_EXPOSE_HEADERS=["X-Request-ID","X-Correlation-ID"]     CORS_MAX_AGE=600     `

### Trusted Hosts And Proxy Headers

Use these settings when the template sits behind a reverse proxy or load balancer and you want explicit host-header and forwarded-header trust controls:

```env
TRUSTED_HOSTS=["api.example.com","*.api.example.com"]
TRUSTED_HOSTS_WWW_REDIRECT=true
PROXY_HEADERS_ENABLED=false
PROXY_HEADERS_TRUSTED_PROXIES=["127.0.0.1"]  # Replace with the proxy IPs, CIDRs, or socket literals you actually trust
```

- `TRUSTED_HOSTS` enables Starlette's host-header allowlist middleware when the list is non-empty.
- `TRUSTED_HOSTS_WWW_REDIRECT` controls whether requests redirect to a `www.` host when that variant is allowed.
- `PROXY_HEADERS_ENABLED` enables `X-Forwarded-For` and `X-Forwarded-Proto` handling.
- `PROXY_HEADERS_TRUSTED_PROXIES` must list the proxy addresses that are allowed to supply forwarded headers.

!!! warning "Proxy Trust In Secure Environments"
    Staging and production profiles reject `TRUSTED_HOSTS=["*"]` and `PROXY_HEADERS_TRUSTED_PROXIES=["*"]`. Keep both settings explicit and template adopters can swap in the ingress addresses or CIDRs that fit their deployment.

### Request Safety Controls

Use these settings to add generic request-size, timeout, and log-redaction guardrails:

```env
REQUEST_BODY_LIMIT_ENABLED=true
REQUEST_BODY_MAX_BYTES=1048576
REQUEST_BODY_LIMIT_EXEMPT_PATH_PREFIXES=["/api/v1/webhooks/provider"]
REQUEST_TIMEOUT_ENABLED=false
REQUEST_TIMEOUT_SECONDS=30
REQUEST_TIMEOUT_EXEMPT_PATH_PREFIXES=["/api/v1/ops"]
LOG_REDACTION_ENABLED=true
LOG_REDACTION_EXACT_FIELDS=["authorization","cookie","set-cookie","password","email"]
LOG_REDACTION_SUBSTRING_FIELDS=["token","secret","password","authorization","cookie","session","email","phone","ssn"]
LOG_REDACTION_REPLACEMENT="[REDACTED]"
```

- `REQUEST_BODY_*` protects the app from oversized bodies and returns a standard `413` payload when the limit is exceeded.
- `REQUEST_TIMEOUT_*` adds an optional application-layer timeout budget that returns a standard `504` payload when a request runs too long.
- `LOG_REDACTION_*` controls the structured-log redaction processor that scrubs common headers, tokens, secrets, and PII-like keys before logs are rendered.

For the webhook-specific raw-body verification pattern, see [User Guide - API Request Safety](../user-guide/api/request-safety.md).

### Security Headers And Cookie Behavior

Use these settings to control the baseline security headers the template adds and the cookie behavior the template itself owns:

```env
SECURITY_HEADERS_ENABLED=true
SECURITY_HEADERS_FRAME_OPTIONS="DENY"
SECURITY_HEADERS_REFERRER_POLICY="strict-origin-when-cross-origin"
SECURITY_HEADERS_CONTENT_SECURITY_POLICY="default-src 'self'"
SECURITY_HEADERS_HSTS_ENABLED=false
REFRESH_TOKEN_COOKIE_NAME="refresh_token"
REFRESH_TOKEN_COOKIE_SECURE=false          # Local profile default; secure environments should use true
REFRESH_TOKEN_COOKIE_HTTPONLY=true
REFRESH_TOKEN_COOKIE_SAMESITE="lax"
SESSION_SECURE_COOKIES=false              # Local profile default for the admin session cookie
PASSWORD_HASH_SCHEME="bcrypt"
PASSWORD_BCRYPT_ROUNDS=12
PASSWORD_HASH_REHASH_ON_LOGIN=true
```

- `SECURITY_HEADERS_*` configures the reusable response-header middleware the template owns.
- `REFRESH_TOKEN_COOKIE_*` configures the refresh token cookie used by the built-in auth routes.
- `SESSION_SECURE_COOKIES` controls whether the built-in admin session cookie requires HTTPS.
- `PASSWORD_*` controls the shared password-hash policy so cloned projects can raise bcrypt cost over time without changing auth code.

!!! warning "Secure Environment Cookie Defaults"
    Staging and production profiles reject `REFRESH_TOKEN_COOKIE_SECURE=false`. They also reject `SESSION_SECURE_COOKIES=false` while CRUD admin is enabled, so secure deployments cannot silently fall back to insecure cookie transport.

### Feature Flags And Optional Modules

Use `FEATURE_*` settings to disable template-owned route groups or modules without editing application code:

```env
FEATURE_ADMIN_ENABLED=true
FEATURE_CLIENT_CACHE_ENABLED=true
FEATURE_API_AUTH_ROUTES_ENABLED=true
FEATURE_API_USERS_ENABLED=true
FEATURE_API_POSTS_ENABLED=true
FEATURE_API_TIERS_ENABLED=true
FEATURE_API_RATE_LIMITS_ENABLED=true
```

- `FEATURE_ADMIN_ENABLED` short-circuits the built-in admin mount even if admin settings remain configured.
- `FEATURE_CLIENT_CACHE_ENABLED` disables the template’s client-cache middleware while leaving cache configuration values available.
- The `FEATURE_API_*` flags control whether the corresponding starter route groups are registered under `/api/v1`.

### First Tier

```env
# Default Tier
TIER_NAME="free"
```

## Environment Types

Set your environment type:

```env
ENVIRONMENT="local"  # local, staging, or production
```

- **local**: API docs available at `/docs`, `/redoc`, and `/openapi.json`
- **staging**: API docs available to superusers only
- **production**: API docs completely disabled

When `ENVIRONMENT="staging"` or `ENVIRONMENT="production"`, the template loads an environment-specific settings profile before boot. Both secure profiles fail fast if `SECRET_KEY`, the resolved database password, or `ADMIN_PASSWORD` still use placeholder values. CORS now defaults to a fail-closed allowlist in secure environments, and wildcard origins are rejected when credentials are enabled.

For a side-by-side matrix covering docs exposure, cookies, CORS, trusted hosts, proxy trust, observability, and example env files, see [User Guide - Environment-Specific Configuration](../user-guide/configuration/environment-specific.md).

## Docker Compose Settings

If using Docker Compose, use these values instead:

```env
# Docker Compose values
POSTGRES_SERVER="db"
REDIS_CACHE_HOST="redis"
REDIS_QUEUE_HOST="redis"
REDIS_RATE_LIMIT_HOST="redis"
```

## Optional Services

The boilerplate includes Redis for caching, job queues, and rate limiting. If running locally without Docker, either:

1. **Install Redis** and keep the default settings
1. **Disable Redis services** (see [User Guide - Configuration](../user-guide/configuration/index.md) for details)

## That's It!

With these basic settings configured, you can start the application:

- **Docker Compose**: `docker compose up`
- **Manual**: `uv run uvicorn src.app.main:app --reload`

For detailed configuration options, advanced settings, and production deployment, see the [User Guide - Configuration](../user-guide/configuration/index.md).
