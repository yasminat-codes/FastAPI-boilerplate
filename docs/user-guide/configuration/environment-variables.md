# Configuration Guide

This guide covers all configuration options available in the FastAPI Boilerplate, including environment variables, settings classes, and advanced deployment configurations.

## Configuration Overview

The boilerplate uses a layered configuration approach:

- **Environment Variables** (`.env` file) - Primary configuration method
- **Settings Classes** (`src/app/core/config.py`) - Python-based configuration
- **Docker Configuration** (`docker-compose.yml`) - Container orchestration
- **Database Configuration** (`alembic.ini`) - Database migrations

## Environment Variables Reference

All configuration is managed through environment variables defined in the `.env` file located in the `src/` directory.

If you want profile-specific recommendations instead of the full variable catalog, use the [Environment-Specific Configuration](environment-specific.md) matrix alongside this reference.

### Application Settings

Basic application metadata displayed in API documentation:

```env
# ------------- app settings -------------
APP_NAME="Your App Name"
APP_DESCRIPTION="Your app description here"
APP_VERSION="0.1.0"
CONTACT_NAME="Your Name"
CONTACT_EMAIL="your.email@example.com"
LICENSE_NAME="MIT"
```

**Variables Explained:**

- `APP_NAME`: Displayed in API documentation and responses
- `APP_DESCRIPTION`: Shown in OpenAPI documentation
- `APP_VERSION`: API version for documentation and headers
- `CONTACT_NAME`: Contact information for API documentation
- `CONTACT_EMAIL`: Support email for API users
- `LICENSE_NAME`: License type for the API

### Database Configuration

PostgreSQL database connection settings:

```env
# ------------- database -------------
DATABASE_URL="postgresql://your_postgres_user:your_secure_password@localhost:5432/your_database_name"

# Optional fallback composition
POSTGRES_USER="your_postgres_user"
POSTGRES_PASSWORD="your_secure_password"
POSTGRES_SERVER="localhost"
POSTGRES_PORT=5432
POSTGRES_DB="your_database_name"

# Runtime tuning
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
DATABASE_POOL_PRE_PING=true
DATABASE_POOL_RECYCLE=1800
DATABASE_POOL_TIMEOUT=30
DATABASE_CONNECT_TIMEOUT=10
DATABASE_COMMAND_TIMEOUT=60
DATABASE_STATEMENT_TIMEOUT_MS=30000
DATABASE_SSL_MODE="disable"
DATABASE_SSL_CA_FILE="/path/to/ca.pem"
DATABASE_SSL_CERT_FILE="/path/to/client.crt"
DATABASE_SSL_KEY_FILE="/path/to/client.key"
```

**Variables Explained:**

- `DATABASE_URL`: Preferred first-class PostgreSQL connection string for runtime, migrations, and tests
- `POSTGRES_USER`: Database user with appropriate permissions
- `POSTGRES_PASSWORD`: Strong password for database access
- `POSTGRES_SERVER`: Hostname or IP of PostgreSQL server
- `POSTGRES_PORT`: PostgreSQL port (default: 5432)
- `POSTGRES_DB`: Name of the database to connect to
- `DATABASE_POOL_SIZE`: Number of persistent async connections in the SQLAlchemy pool
- `DATABASE_MAX_OVERFLOW`: Temporary extra connections allowed above the pool size
- `DATABASE_POOL_PRE_PING`: Whether SQLAlchemy checks connections before reusing them
- `DATABASE_POOL_RECYCLE`: Max connection age in seconds before SQLAlchemy refreshes it
- `DATABASE_POOL_TIMEOUT`: Seconds to wait for a pooled connection before failing
- `DATABASE_CONNECT_TIMEOUT`: Seconds allowed to establish a new PostgreSQL connection
- `DATABASE_COMMAND_TIMEOUT`: Default asyncpg command timeout in seconds
- `DATABASE_STATEMENT_TIMEOUT_MS`: Optional PostgreSQL server-side statement timeout in milliseconds
- `DATABASE_SSL_MODE`: SSL posture for the database connection: `disable`, `require`, `verify-ca`, or `verify-full`
- `DATABASE_SSL_CA_FILE`: CA bundle path used for `verify-ca` and `verify-full`
- `DATABASE_SSL_CERT_FILE`: Optional client certificate path
- `DATABASE_SSL_KEY_FILE`: Optional client certificate key path

`DATABASE_URL` is the preferred template interface. If it is omitted, the template composes an equivalent connection string from the `POSTGRES_*` values.

**Environment-Specific Values:**

```env
# Local development
POSTGRES_SERVER="localhost"

# Docker Compose
POSTGRES_SERVER="db"

# Production
POSTGRES_SERVER="your-prod-db-host.com"
```

### Security & Authentication

JWT and password security configuration:

```env
# ------------- crypt -------------
SECRET_KEY="your-super-secret-key-here"
ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
JWT_ISSUER="https://api.example.com"
JWT_AUDIENCE="template-api"
JWT_ACTIVE_KEY_ID="2026-04"
JWT_VERIFICATION_KEYS='{"2026-01":"previous-signing-secret"}'
PASSWORD_HASH_SCHEME="bcrypt"
PASSWORD_BCRYPT_ROUNDS=12
PASSWORD_HASH_REHASH_ON_LOGIN=true
```

**Variables Explained:**

- `SECRET_KEY`: Used for JWT token signing (generate with `openssl rand -hex 32`)
- `ALGORITHM`: JWT signing algorithm (HS256 recommended)
- `ACCESS_TOKEN_EXPIRE_MINUTES`: How long access tokens remain valid
- `REFRESH_TOKEN_EXPIRE_DAYS`: How long refresh tokens remain valid
- `JWT_ISSUER`: Optional issuer claim added to new tokens and enforced during verification
- `JWT_AUDIENCE`: Optional audience claim added to new tokens and enforced during verification
- `JWT_ACTIVE_KEY_ID`: `kid` header assigned to newly issued tokens
- `JWT_VERIFICATION_KEYS`: JSON object of previous signing secrets keyed by `kid` for zero-downtime key rotation
- `PASSWORD_HASH_SCHEME`: Password-hash implementation used by the shared auth helpers; today the template ships with `bcrypt`
- `PASSWORD_BCRYPT_ROUNDS`: bcrypt work factor used for new password hashes
- `PASSWORD_HASH_REHASH_ON_LOGIN`: Rehash older stored passwords after a successful login when the configured policy becomes stronger

!!! danger "Security Warning"
Never use default values in production. Generate a strong secret key:
`bash     openssl rand -hex 32     `

### Redis Configuration

Redis is used for caching, job queues, and rate limiting:

```env
# ------------- redis cache -------------
REDIS_CACHE_HOST="localhost"  # Use "redis" for Docker Compose
REDIS_CACHE_PORT=6379
REDIS_CACHE_DB=0
# REDIS_CACHE_USERNAME="cache-user"
# REDIS_CACHE_PASSWORD="cache-password"
REDIS_CACHE_CONNECT_TIMEOUT=5
REDIS_CACHE_SOCKET_TIMEOUT=5
REDIS_CACHE_RETRY_ATTEMPTS=3
REDIS_CACHE_RETRY_BASE_DELAY=0.1
REDIS_CACHE_RETRY_MAX_DELAY=1.0
REDIS_CACHE_RETRY_ON_TIMEOUT=true
REDIS_CACHE_MAX_CONNECTIONS=null
REDIS_CACHE_SSL=false
REDIS_CACHE_SSL_CHECK_HOSTNAME=false
REDIS_CACHE_SSL_CERT_REQS="required"
# REDIS_CACHE_SSL_CA_CERTS="/path/to/cache-ca.pem"
# REDIS_CACHE_SSL_CERTFILE="/path/to/cache-client.crt"
# REDIS_CACHE_SSL_KEYFILE="/path/to/cache-client.key"

# ------------- redis queue -------------
REDIS_QUEUE_HOST="localhost"  # Use "redis" for Docker Compose
REDIS_QUEUE_PORT=6379
REDIS_QUEUE_DB=0
# REDIS_QUEUE_USERNAME="queue-user"
# REDIS_QUEUE_PASSWORD="queue-password"
REDIS_QUEUE_CONNECT_TIMEOUT=5
REDIS_QUEUE_CONNECT_RETRIES=5
REDIS_QUEUE_RETRY_DELAY=1
REDIS_QUEUE_RETRY_ON_TIMEOUT=true
REDIS_QUEUE_MAX_CONNECTIONS=null
REDIS_QUEUE_SSL=false
REDIS_QUEUE_SSL_CHECK_HOSTNAME=false
REDIS_QUEUE_SSL_CERT_REQS="required"
# REDIS_QUEUE_SSL_CA_CERTS="/path/to/queue-ca.pem"
# REDIS_QUEUE_SSL_CERTFILE="/path/to/queue-client.crt"
# REDIS_QUEUE_SSL_KEYFILE="/path/to/queue-client.key"

# ------------- redis rate limit -------------
REDIS_RATE_LIMIT_HOST="localhost"  # Use "redis" for Docker Compose
REDIS_RATE_LIMIT_PORT=6379
REDIS_RATE_LIMIT_DB=0
# REDIS_RATE_LIMIT_USERNAME="rate-limit-user"
# REDIS_RATE_LIMIT_PASSWORD="rate-limit-password"
REDIS_RATE_LIMIT_CONNECT_TIMEOUT=5
REDIS_RATE_LIMIT_SOCKET_TIMEOUT=5
REDIS_RATE_LIMIT_RETRY_ATTEMPTS=3
REDIS_RATE_LIMIT_RETRY_BASE_DELAY=0.1
REDIS_RATE_LIMIT_RETRY_MAX_DELAY=1.0
REDIS_RATE_LIMIT_RETRY_ON_TIMEOUT=true
REDIS_RATE_LIMIT_MAX_CONNECTIONS=null
REDIS_RATE_LIMIT_SSL=false
REDIS_RATE_LIMIT_SSL_CHECK_HOSTNAME=false
REDIS_RATE_LIMIT_SSL_CERT_REQS="required"
# REDIS_RATE_LIMIT_SSL_CA_CERTS="/path/to/rate-limit-ca.pem"
# REDIS_RATE_LIMIT_SSL_CERTFILE="/path/to/rate-limit-client.crt"
# REDIS_RATE_LIMIT_SSL_KEYFILE="/path/to/rate-limit-client.key"
```

**Best Practices:**

- **Development**: Use the same Redis instance for all services
- **Production**: Use separate Redis instances for better isolation

```env
# Production example with separate instances
REDIS_CACHE_HOST="cache.redis.example.com"
REDIS_QUEUE_HOST="queue.redis.example.com"
REDIS_RATE_LIMIT_HOST="ratelimit.redis.example.com"
```

The template computes `REDIS_CACHE_URL`, `REDIS_QUEUE_URL`, and `REDIS_RATE_LIMIT_URL` from these fields and passes the timeout, retry, and TLS settings into the cache pool, ARQ worker connection, and rate-limiter connection pool.

### Worker Runtime Settings

Shared worker defaults for ARQ:

```env
WORKER_QUEUE_NAME="arq:queue"
WORKER_MAX_JOBS=10
WORKER_JOB_MAX_TRIES=3
WORKER_JOB_RETRY_DELAY_SECONDS=5.0
WORKER_KEEP_RESULT_SECONDS=3600
WORKER_KEEP_RESULT_FOREVER=false
WORKER_JOB_EXPIRES_EXTRA_MS=86400000
```

**Variables Explained:**

- `WORKER_QUEUE_NAME`: Queue name consumed by the canonical worker entrypoint
- `WORKER_MAX_JOBS`: Maximum number of concurrent jobs a worker process will execute
- `WORKER_JOB_MAX_TRIES`: Default retry attempt cap for `WorkerJob` subclasses that do not override `retry_policy`
- `WORKER_JOB_RETRY_DELAY_SECONDS`: Default defer delay used when a `RetryableJobError` is raised without a custom delay
- `WORKER_KEEP_RESULT_SECONDS`: Default amount of time completed job results are retained
- `WORKER_KEEP_RESULT_FOREVER`: Retain completed job results indefinitely instead of expiring them
- `WORKER_JOB_EXPIRES_EXTRA_MS`: Additional queue retention window ARQ uses before treating queued jobs as expired

### Webhook Runtime Settings

Generic webhook ingestion defaults for future provider adapters:

```env
WEBHOOK_SIGNATURE_VERIFICATION_ENABLED=true
WEBHOOK_SIGNATURE_MAX_AGE_SECONDS=300
WEBHOOK_REPLAY_PROTECTION_ENABLED=true
WEBHOOK_REPLAY_WINDOW_SECONDS=300
WEBHOOK_STORE_RAW_PAYLOADS=true
WEBHOOK_PAYLOAD_RETENTION_DAYS=7
```

**Variables Explained:**

- `WEBHOOK_SIGNATURE_VERIFICATION_ENABLED`: Require provider adapters to verify incoming webhook signatures by default
- `WEBHOOK_SIGNATURE_MAX_AGE_SECONDS`: Maximum accepted age for timestamped signatures before the request is treated as stale
- `WEBHOOK_REPLAY_PROTECTION_ENABLED`: Enable replay-window enforcement for duplicate or delayed webhook delivery attempts
- `WEBHOOK_REPLAY_WINDOW_SECONDS`: Length of time the template should consider a webhook delivery eligible for replay protection checks
- `WEBHOOK_STORE_RAW_PAYLOADS`: Persist raw webhook bodies when the future webhook ingestion layer is enabled
- `WEBHOOK_PAYLOAD_RETENTION_DAYS`: How long retained raw webhook payloads should remain available before cleanup

### Sentry Settings

Error monitoring defaults:

```env
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
```

**Variables Explained:**

- `SENTRY_ENABLE`: Toggle Sentry initialization in the current runtime
- `SENTRY_DSN`: DSN used when Sentry is enabled
- `SENTRY_ENVIRONMENT`: Environment tag attached to Sentry events
- `SENTRY_RELEASE`: Optional release identifier for deploy correlation
- `SENTRY_DEBUG`: Enable verbose Sentry SDK diagnostics
- `SENTRY_ATTACH_STACKTRACE`: Attach stack traces to captured log events
- `SENTRY_SEND_DEFAULT_PII`: Allow default PII capture when your deployment needs it
- `SENTRY_MAX_BREADCRUMBS`: Limit the number of breadcrumbs attached to an event
- `SENTRY_TRACES_SAMPLE_RATE`: Sentry tracing sample rate between `0.0` and `1.0`
- `SENTRY_PROFILES_SAMPLE_RATE`: Sentry profiling sample rate between `0.0` and `1.0`

### Metrics Settings

Metrics configuration hooks for future instrumentation:

```env
METRICS_ENABLED=false
METRICS_PATH="/metrics"
METRICS_NAMESPACE="fastapi_template"
METRICS_INCLUDE_REQUEST_PATH_LABELS=false
```

**Variables Explained:**

- `METRICS_ENABLED`: Enable the template metrics surface once instrumentation is wired in
- `METRICS_PATH`: HTTP path reserved for metrics exposure
- `METRICS_NAMESPACE`: Prefix/namespace used by future metric names
- `METRICS_INCLUDE_REQUEST_PATH_LABELS`: Include request paths as labels when instrumentation needs route-level detail

### Tracing Settings

Tracing configuration hooks for future instrumentation:

```env
TRACING_ENABLED=false
TRACING_EXPORTER="otlp"
TRACING_SAMPLE_RATE=1.0
TRACING_SERVICE_NAME="fastapi-template-api"
TRACING_PROPAGATE_CORRELATION_IDS=true
```

**Variables Explained:**

- `TRACING_ENABLED`: Enable distributed tracing hooks when tracing instrumentation is added
- `TRACING_EXPORTER`: Trace export strategy, currently `otlp` or `console`
- `TRACING_SAMPLE_RATE`: Fraction of traces to keep between `0.0` and `1.0`
- `TRACING_SERVICE_NAME`: Service name reported to the tracing backend
- `TRACING_PROPAGATE_CORRELATION_IDS`: Carry correlation/request identifiers into future trace context

### Log Verbosity Settings

Structured logging level controls:

```env
LOG_LEVEL="INFO"
UVICORN_LOG_LEVEL="INFO"
WORKER_LOG_LEVEL="INFO"
CONSOLE_LOG_LEVEL="INFO"
CONSOLE_LOG_FORMAT_JSON=false
FILE_LOG_ENABLED=false
FILE_LOG_LEVEL="INFO"
FILE_LOG_FORMAT_JSON=true
```

**Variables Explained:**

- `LOG_LEVEL`: Root logger verbosity for the application
- `UVICORN_LOG_LEVEL`: Verbosity for Uvicorn and Uvicorn access/error loggers
- `WORKER_LOG_LEVEL`: Verbosity for background worker processes
- `CONSOLE_LOG_LEVEL`: Minimum level written to stdout/stderr
- `CONSOLE_LOG_FORMAT_JSON`: `true` for JSON lines (production), `false` for human-readable (local dev)
- `FILE_LOG_ENABLED`: Set to `true` to enable the rotating file handler (off by default)
- `FILE_LOG_LEVEL`: Minimum level written to the rotating file handler (when enabled)
- `FILE_LOG_FORMAT_JSON`: `true` for JSON output in the file handler

See the [logging guide](../logging.md) for the full standard log shape, per-handler context key filtering, redaction settings, and environment-specific recommendations.

### Caching Settings

Client-side and server-side caching configuration:

```env
# ------------- redis client-side cache -------------
CLIENT_CACHE_MAX_AGE=30  # seconds
```

**Variables Explained:**

- `CLIENT_CACHE_MAX_AGE`: How long browsers should cache responses

### Feature Flags And Optional Modules

High-level toggles for template-owned route groups and modules:

```env
FEATURE_ADMIN_ENABLED=true
FEATURE_CLIENT_CACHE_ENABLED=true
FEATURE_API_AUTH_ROUTES_ENABLED=true
FEATURE_API_USERS_ENABLED=true
FEATURE_API_POSTS_ENABLED=true
FEATURE_API_TIERS_ENABLED=true
FEATURE_API_RATE_LIMITS_ENABLED=true
```

**Variables Explained:**

- `FEATURE_ADMIN_ENABLED`: Enable or disable the built-in CRUD admin mount at a high level
- `FEATURE_CLIENT_CACHE_ENABLED`: Enable or disable the template-owned client cache middleware
- `FEATURE_API_AUTH_ROUTES_ENABLED`: Register or skip the built-in `/api/v1/login` and `/api/v1/logout` routes
- `FEATURE_API_USERS_ENABLED`: Register or skip the starter user-management routes
- `FEATURE_API_POSTS_ENABLED`: Register or skip the starter post routes
- `FEATURE_API_TIERS_ENABLED`: Register or skip the starter tier routes
- `FEATURE_API_RATE_LIMITS_ENABLED`: Register or skip the starter rate-limit management routes

These flags are intentionally coarse-grained. They let template adopters trim starter surfaces without having to fork router registration or app wiring.

### Rate Limiting

Default rate limiting configuration:

```env
# ------------- default rate limit settings -------------
API_RATE_LIMIT_ENABLED=true
DEFAULT_RATE_LIMIT_LIMIT=10      # requests per period
DEFAULT_RATE_LIMIT_PERIOD=3600   # period in seconds (1 hour)
AUTH_RATE_LIMIT_ENABLED=true
AUTH_RATE_LIMIT_LOGIN_LIMIT=5
AUTH_RATE_LIMIT_LOGIN_PERIOD=300
AUTH_RATE_LIMIT_REFRESH_LIMIT=30
AUTH_RATE_LIMIT_REFRESH_PERIOD=300
AUTH_RATE_LIMIT_LOGOUT_LIMIT=30
AUTH_RATE_LIMIT_LOGOUT_PERIOD=300
WEBHOOK_RATE_LIMIT_ENABLED=true
WEBHOOK_RATE_LIMIT_LIMIT=120
WEBHOOK_RATE_LIMIT_PERIOD=60
```

**Variables Explained:**

- `API_RATE_LIMIT_ENABLED`: Enable or disable the shared public-API rate-limit dependency
- `DEFAULT_RATE_LIMIT_LIMIT`: Number of requests allowed per period
- `DEFAULT_RATE_LIMIT_PERIOD`: Time window in seconds
- `AUTH_RATE_LIMIT_ENABLED`: Enable or disable the template-owned auth-route rate limits
- `AUTH_RATE_LIMIT_LOGIN_LIMIT` / `AUTH_RATE_LIMIT_LOGIN_PERIOD`: Budget for `/api/v1/login`
- `AUTH_RATE_LIMIT_REFRESH_LIMIT` / `AUTH_RATE_LIMIT_REFRESH_PERIOD`: Budget for `/api/v1/refresh`
- `AUTH_RATE_LIMIT_LOGOUT_LIMIT` / `AUTH_RATE_LIMIT_LOGOUT_PERIOD`: Budget for `/api/v1/logout`
- `WEBHOOK_RATE_LIMIT_ENABLED`: Enable or disable the default webhook route-group rate limit
- `WEBHOOK_RATE_LIMIT_LIMIT` / `WEBHOOK_RATE_LIMIT_PERIOD`: Budget for `/api/v1/webhooks/*`

### Admin User

Opt-in CRUD admin and bootstrap credential configuration:

```env
# ------------- CRUD admin -------------
CRUD_ADMIN_ENABLED=false
CRUD_ADMIN_MOUNT_PATH="/admin"

# ------------- admin -------------
ADMIN_NAME="Admin User"
ADMIN_EMAIL="admin@example.com"
ADMIN_USERNAME="admin"
ADMIN_PASSWORD="secure_admin_password"
```

**Variables Explained:**

- `CRUD_ADMIN_ENABLED`: Enable the built-in CRUD admin UI. Defaults to `false` so the browser admin surface is opt-in.
- `CRUD_ADMIN_MOUNT_PATH`: Mount path for the built-in CRUD admin UI when enabled
- `ADMIN_NAME`: Display name for the admin user
- `ADMIN_EMAIL`: Email address for the admin account
- `ADMIN_USERNAME`: Username for admin login
- `ADMIN_PASSWORD`: Initial password used by the opt-in CRUD admin UI and the `create_first_superuser` helper (change after first login)

### CORS Configuration

Cross-Origin Resource Sharing (CORS) settings for frontend integration:

```env
# ------------- CORS -------------
CORS_ORIGINS=["https://app.example.com"]
CORS_ALLOW_CREDENTIALS=true
CORS_METHODS=["GET","POST","PUT","PATCH","DELETE","OPTIONS"]
CORS_HEADERS=["Accept","Authorization","Content-Type","X-Requested-With","X-Request-ID","X-Correlation-ID"]
CORS_EXPOSE_HEADERS=["X-Request-ID","X-Correlation-ID"]
CORS_MAX_AGE=600
```

**Variables Explained:**

- `CORS_ORIGINS`: Comma-separated list of allowed origins (e.g., `["https://app.com","https://www.app.com"]`)
- `CORS_ALLOW_CREDENTIALS`: Allow cookies and authenticated browser credentials for approved origins
- `CORS_METHODS`: Allowed HTTP methods (e.g., `["GET","POST","PUT","DELETE"]`)
- `CORS_HEADERS`: Allowed request headers (e.g., `["Authorization","Content-Type"]`)
- `CORS_EXPOSE_HEADERS`: Response headers browsers are allowed to read, such as `X-Request-ID` and `X-Correlation-ID`
- `CORS_MAX_AGE`: Browser cache duration for preflight responses, in seconds

**Environment-Specific Values:**

```env
# Development - Local profile defaults to common localhost frontend ports
CORS_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000","http://localhost:5173","http://127.0.0.1:5173"]
CORS_ALLOW_CREDENTIALS=true
CORS_METHODS=["GET","POST","PUT","PATCH","DELETE","OPTIONS"]
CORS_HEADERS=["Accept","Authorization","Content-Type","X-Requested-With","X-Request-ID","X-Correlation-ID"]
CORS_EXPOSE_HEADERS=["X-Request-ID","X-Correlation-ID"]
CORS_MAX_AGE=600

# Production - Explicit domains only; leaving CORS_ORIGINS unset blocks cross-origin browser access by default
CORS_ORIGINS=["https://yourapp.com","https://www.yourapp.com"]
CORS_ALLOW_CREDENTIALS=true
CORS_METHODS=["GET","POST","PUT","DELETE","PATCH","OPTIONS"]
CORS_HEADERS=["Accept","Authorization","Content-Type","X-Requested-With","X-Request-ID","X-Correlation-ID"]
CORS_EXPOSE_HEADERS=["X-Request-ID","X-Correlation-ID"]
CORS_MAX_AGE=600
```

!!! danger "Security Warning"
When `CORS_ALLOW_CREDENTIALS=true`, wildcard values are rejected for `CORS_ORIGINS`, `CORS_METHODS`, and `CORS_HEADERS`. Secure environments should either specify exact origins or leave `CORS_ORIGINS` empty to fail closed.

### Security Headers And Cookie Behavior

Template-owned response-header and cookie controls:

```env
SECURITY_HEADERS_ENABLED=true
SECURITY_HEADERS_FRAME_OPTIONS="DENY"
SECURITY_HEADERS_REFERRER_POLICY="strict-origin-when-cross-origin"
# SECURITY_HEADERS_CONTENT_SECURITY_POLICY="default-src 'self'"
# SECURITY_HEADERS_PERMISSIONS_POLICY="geolocation=()"
SECURITY_HEADERS_CROSS_ORIGIN_OPENER_POLICY="same-origin"
SECURITY_HEADERS_CROSS_ORIGIN_RESOURCE_POLICY="same-origin"
SECURITY_HEADERS_HSTS_ENABLED=false
SECURITY_HEADERS_HSTS_MAX_AGE_SECONDS=31536000
SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS=true
SECURITY_HEADERS_HSTS_PRELOAD=false

REFRESH_TOKEN_COOKIE_NAME="refresh_token"
REFRESH_TOKEN_COOKIE_PATH="/"
# REFRESH_TOKEN_COOKIE_DOMAIN="auth.example.com"
REFRESH_TOKEN_COOKIE_SECURE=false
REFRESH_TOKEN_COOKIE_HTTPONLY=true
REFRESH_TOKEN_COOKIE_SAMESITE="lax"

SESSION_SECURE_COOKIES=false
```

**Variables Explained:**

- `SECURITY_HEADERS_ENABLED`: Enable the template’s baseline security-header middleware
- `SECURITY_HEADERS_FRAME_OPTIONS`: Set `X-Frame-Options` to `DENY` or `SAMEORIGIN`
- `SECURITY_HEADERS_REFERRER_POLICY`: Set the `Referrer-Policy` header
- `SECURITY_HEADERS_CONTENT_SECURITY_POLICY`: Optional raw `Content-Security-Policy` value
- `SECURITY_HEADERS_PERMISSIONS_POLICY`: Optional raw `Permissions-Policy` value
- `SECURITY_HEADERS_CROSS_ORIGIN_OPENER_POLICY`: Optional `Cross-Origin-Opener-Policy` value
- `SECURITY_HEADERS_CROSS_ORIGIN_RESOURCE_POLICY`: Optional `Cross-Origin-Resource-Policy` value
- `SECURITY_HEADERS_HSTS_ENABLED`: Enable the `Strict-Transport-Security` header
- `SECURITY_HEADERS_HSTS_MAX_AGE_SECONDS`: Max age used for HSTS when enabled
- `SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS`: Add `includeSubDomains` to HSTS
- `SECURITY_HEADERS_HSTS_PRELOAD`: Add `preload` to HSTS; requires HSTS to be enabled with subdomains included
- `REFRESH_TOKEN_COOKIE_NAME`: Cookie name used by the built-in refresh-token flow
- `REFRESH_TOKEN_COOKIE_PATH`: Cookie path used for set/delete operations
- `REFRESH_TOKEN_COOKIE_DOMAIN`: Optional cookie domain for cross-subdomain deployments
- `REFRESH_TOKEN_COOKIE_SECURE`: Require HTTPS transport for the refresh-token cookie
- `REFRESH_TOKEN_COOKIE_HTTPONLY`: Prevent JavaScript access to the refresh-token cookie
- `REFRESH_TOKEN_COOKIE_SAMESITE`: SameSite policy for the refresh-token cookie: `lax`, `strict`, or `none`
- `SESSION_SECURE_COOKIES`: Require HTTPS transport for the built-in admin session cookie

**Environment-Specific Values:**

```env
# Local development defaults
SECURITY_HEADERS_ENABLED=true
SECURITY_HEADERS_FRAME_OPTIONS="DENY"
SECURITY_HEADERS_REFERRER_POLICY="strict-origin-when-cross-origin"
SECURITY_HEADERS_HSTS_ENABLED=false
REFRESH_TOKEN_COOKIE_SECURE=false
REFRESH_TOKEN_COOKIE_HTTPONLY=true
REFRESH_TOKEN_COOKIE_SAMESITE="lax"
SESSION_SECURE_COOKIES=false

# Production example
SECURITY_HEADERS_ENABLED=true
SECURITY_HEADERS_FRAME_OPTIONS="DENY"
SECURITY_HEADERS_REFERRER_POLICY="strict-origin-when-cross-origin"
SECURITY_HEADERS_CONTENT_SECURITY_POLICY="default-src 'self'"
SECURITY_HEADERS_HSTS_ENABLED=true
SECURITY_HEADERS_HSTS_MAX_AGE_SECONDS=31536000
SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS=true
SECURITY_HEADERS_HSTS_PRELOAD=false
REFRESH_TOKEN_COOKIE_SECURE=true
REFRESH_TOKEN_COOKIE_HTTPONLY=true
REFRESH_TOKEN_COOKIE_SAMESITE="lax"
SESSION_SECURE_COOKIES=true
```

!!! danger "Security Warning"
Secure environments reject `REFRESH_TOKEN_COOKIE_SECURE=false`, and they also reject `SESSION_SECURE_COOKIES=false` when the built-in CRUD admin surface is enabled. Browsers additionally require `REFRESH_TOKEN_COOKIE_SECURE=true` when `REFRESH_TOKEN_COOKIE_SAMESITE="none"`.

!!! warning "CSRF Review For Cookie-Authenticated Routes"
`REFRESH_TOKEN_COOKIE_SAMESITE="lax"` is the template default because it keeps the built-in cookie surface on a safer browser baseline. If you move to `SameSite="none"` for a frontend hosted on a different site, or if you introduce more cookie-authenticated mutation endpoints, add explicit CSRF protection such as `Origin`/`Referer` validation or a double-submit token. `CORS_ALLOW_CREDENTIALS` and explicit origin allowlists do not replace CSRF protection.

### Trusted Hosts And Proxy Headers

Explicit host-header and forwarded-header trust controls:

```env
TRUSTED_HOSTS=["api.example.com","*.api.example.com"]
TRUSTED_HOSTS_WWW_REDIRECT=true
PROXY_HEADERS_ENABLED=false
PROXY_HEADERS_TRUSTED_PROXIES=["127.0.0.1"]
```

**Variables Explained:**

- `TRUSTED_HOSTS`: Enable the host-header allowlist when you provide one or more exact hosts / `*.` subdomain patterns
- `TRUSTED_HOSTS_WWW_REDIRECT`: Redirect requests to a `www.` host variant when the target host is in the allowlist
- `PROXY_HEADERS_ENABLED`: Opt into `X-Forwarded-For` and `X-Forwarded-Proto` handling
- `PROXY_HEADERS_TRUSTED_PROXIES`: IPs, CIDRs, or literal proxy addresses that are allowed to supply forwarded headers

**Environment-Specific Values:**

```env
# Local reverse proxy example
TRUSTED_HOSTS=["localhost","127.0.0.1"]
TRUSTED_HOSTS_WWW_REDIRECT=false
PROXY_HEADERS_ENABLED=true
PROXY_HEADERS_TRUSTED_PROXIES=["127.0.0.1"]

# Production example
TRUSTED_HOSTS=["api.example.com","www.api.example.com"]
TRUSTED_HOSTS_WWW_REDIRECT=true
PROXY_HEADERS_ENABLED=false  # Enable only after replacing the trusted proxy list below
PROXY_HEADERS_TRUSTED_PROXIES=["10.0.0.0/8"]
```

!!! danger "Security Warning"
Secure environments reject `TRUSTED_HOSTS=["*"]`, and they also reject `PROXY_HEADERS_TRUSTED_PROXIES=["*"]` when proxy header handling is enabled. Keep these values explicit so only known hosts and proxy hops are trusted.

### Request Safety Controls

Generic request-size, timeout, and structured-log redaction settings:

```env
REQUEST_BODY_LIMIT_ENABLED=true
REQUEST_BODY_MAX_BYTES=1048576
REQUEST_BODY_LIMIT_EXEMPT_PATH_PREFIXES=["/api/v1/webhooks/provider"]
REQUEST_TIMEOUT_ENABLED=false
REQUEST_TIMEOUT_SECONDS=30
REQUEST_TIMEOUT_EXEMPT_PATH_PREFIXES=["/api/v1/ops"]
LOG_REDACTION_ENABLED=true
LOG_REDACTION_EXACT_FIELDS=["authorization","cookie","set-cookie","x-api-key","password","email"]
LOG_REDACTION_SUBSTRING_FIELDS=["token","secret","password","authorization","cookie","session","email","phone","ssn"]
LOG_REDACTION_REPLACEMENT="[REDACTED]"
```

**Variables Explained:**

- `REQUEST_BODY_LIMIT_ENABLED`: Enable the shared request-body size guardrail
- `REQUEST_BODY_MAX_BYTES`: Maximum request size before the middleware returns `413 payload_too_large`
- `REQUEST_BODY_LIMIT_EXEMPT_PATH_PREFIXES`: Route prefixes that should bypass the global body-size guardrail
- `REQUEST_TIMEOUT_ENABLED`: Enable the shared application-layer request timeout middleware
- `REQUEST_TIMEOUT_SECONDS`: Maximum request runtime before the middleware returns `504 request_timeout`
- `REQUEST_TIMEOUT_EXEMPT_PATH_PREFIXES`: Route prefixes that should bypass the global timeout middleware
- `LOG_REDACTION_ENABLED`: Enable structured-log redaction before console or file rendering
- `LOG_REDACTION_EXACT_FIELDS`: Exact case-insensitive field names that should always have their values redacted
- `LOG_REDACTION_SUBSTRING_FIELDS`: Field-name fragments that trigger redaction for nested structured log values
- `LOG_REDACTION_REPLACEMENT`: Replacement string written in place of sensitive values

**Environment-Specific Values:**

```env
# Local example
REQUEST_BODY_LIMIT_ENABLED=true
REQUEST_BODY_MAX_BYTES=1048576
REQUEST_BODY_LIMIT_EXEMPT_PATH_PREFIXES=[]
REQUEST_TIMEOUT_ENABLED=false
REQUEST_TIMEOUT_SECONDS=30
REQUEST_TIMEOUT_EXEMPT_PATH_PREFIXES=[]
LOG_REDACTION_ENABLED=true

# Production example
REQUEST_BODY_LIMIT_ENABLED=true
REQUEST_BODY_MAX_BYTES=1048576
REQUEST_BODY_LIMIT_EXEMPT_PATH_PREFIXES=["/api/v1/webhooks/provider"]
REQUEST_TIMEOUT_ENABLED=true
REQUEST_TIMEOUT_SECONDS=15
REQUEST_TIMEOUT_EXEMPT_PATH_PREFIXES=["/api/v1/internal/stream"]
LOG_REDACTION_ENABLED=true
```

### HTTP Client Settings

Shared outbound HTTP client defaults for integration adapters:

```env
HTTP_CLIENT_TIMEOUT_SECONDS=30.0
HTTP_CLIENT_CONNECT_TIMEOUT_SECONDS=10.0
HTTP_CLIENT_READ_TIMEOUT_SECONDS=30.0
HTTP_CLIENT_WRITE_TIMEOUT_SECONDS=30.0
HTTP_CLIENT_POOL_MAX_CONNECTIONS=100
HTTP_CLIENT_POOL_MAX_KEEPALIVE=20
HTTP_CLIENT_RETRY_ENABLED=true
HTTP_CLIENT_RETRY_MAX_ATTEMPTS=3
HTTP_CLIENT_RETRY_BACKOFF_BASE_SECONDS=1.0
HTTP_CLIENT_RETRY_BACKOFF_MAX_SECONDS=30.0
HTTP_CLIENT_RETRY_BACKOFF_MULTIPLIER=2.0
HTTP_CLIENT_RETRY_BACKOFF_JITTER=true
HTTP_CLIENT_CIRCUIT_BREAKER_ENABLED=false
HTTP_CLIENT_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
HTTP_CLIENT_CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS=30.0
HTTP_CLIENT_LOG_REQUEST_BODY=false
HTTP_CLIENT_LOG_RESPONSE_BODY=false
```

**Variables Explained:**

- `HTTP_CLIENT_TIMEOUT_SECONDS`: Overall request timeout applied to all outbound calls
- `HTTP_CLIENT_CONNECT_TIMEOUT_SECONDS`: TCP connection timeout (must be <= overall timeout)
- `HTTP_CLIENT_READ_TIMEOUT_SECONDS`: Response read timeout
- `HTTP_CLIENT_WRITE_TIMEOUT_SECONDS`: Request write timeout
- `HTTP_CLIENT_POOL_MAX_CONNECTIONS`: Maximum connection pool size
- `HTTP_CLIENT_POOL_MAX_KEEPALIVE`: Maximum keepalive connections in the pool
- `HTTP_CLIENT_RETRY_ENABLED`: Enable automatic retries for transient failures
- `HTTP_CLIENT_RETRY_MAX_ATTEMPTS`: Maximum retry attempts (including the first try)
- `HTTP_CLIENT_RETRY_BACKOFF_BASE_SECONDS`: Starting delay for exponential backoff
- `HTTP_CLIENT_RETRY_BACKOFF_MAX_SECONDS`: Maximum delay cap for backoff
- `HTTP_CLIENT_RETRY_BACKOFF_MULTIPLIER`: Exponential growth factor for backoff delays
- `HTTP_CLIENT_RETRY_BACKOFF_JITTER`: Apply full jitter to retry delays
- `HTTP_CLIENT_CIRCUIT_BREAKER_ENABLED`: Enable in-process circuit breaker
- `HTTP_CLIENT_CIRCUIT_BREAKER_FAILURE_THRESHOLD`: Consecutive failures before opening
- `HTTP_CLIENT_CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS`: Seconds before half-open probe
- `HTTP_CLIENT_LOG_REQUEST_BODY`: Log outbound request body size in structured logs
- `HTTP_CLIENT_LOG_RESPONSE_BODY`: Log inbound response body size in structured logs

See the [Integrations guide](../integrations/index.md) for usage patterns and provider adapter examples.

### User Tiers

Initial tier configuration:

```env
# ------------- first tier -------------
TIER_NAME="free"
```

**Variables Explained:**

- `TIER_NAME`: Name of the default user tier

### Environment Type

Controls API documentation visibility and behavior:

```env
# ------------- environment -------------
ENVIRONMENT="local"  # local, staging, or production
```

**Environment Types:**

- **local**: Full API docs available publicly at `/docs`
- **staging**: API docs available to superusers only
- **production**: API docs completely disabled

## Secure Environment Validation

When `ENVIRONMENT="staging"` or `ENVIRONMENT="production"`, the settings layer loads a dedicated environment profile and fails fast on a small set of unsafe defaults so template adopters do not accidentally ship example credentials.

Secure environment startup is blocked when any of these are still unsafe:

- `SECRET_KEY`
- `POSTGRES_PASSWORD`
- `ADMIN_PASSWORD` when CRUD admin is enabled
- `CORS_ORIGINS` containing `"*"` in secure environments
- `REFRESH_TOKEN_COOKIE_SECURE=false` in secure environments
- `SESSION_SECURE_COOKIES=false` when CRUD admin is enabled in secure environments
- `TRUSTED_HOSTS` containing `"*"` in secure environments
- `PROXY_HEADERS_TRUSTED_PROXIES` containing `"*"` when proxy header handling is enabled

This validation happens when settings are loaded, so fix the environment values before starting the API, workers, or other secure-environment processes.

## Docker Compose Configuration

### Basic Setup

Docker Compose automatically loads the `.env` file:

```yaml
# In docker-compose.yml
services:
  web:
    env_file:
      - ./src/.env
```

### Development Overrides

Create `docker-compose.override.yml` for local customizations:

```yaml
version: '3.8'
services:
  web:
    ports:
      - "8001:8000"  # Use different port
    environment:
      - DEBUG=true
    volumes:
      - ./custom-logs:/code/logs
```

### Service Configuration

Understanding each Docker service:

```yaml
services:
  web:          # FastAPI application
  db:           # PostgreSQL database
  redis:        # Redis for caching/queues
  worker:       # ARQ background task worker
  nginx:        # Reverse proxy (optional)
```

## Python Settings Classes

Advanced configuration is handled in `src/app/core/config.py`:

### Settings Composition

The main `Settings` class inherits from multiple setting groups:

```python
class Settings(
    AppSettings,
    PostgresSettings,
    CryptSettings,
    FirstUserSettings,
    RedisCacheSettings,
    ClientSideCacheSettings,
    RedisQueueSettings,
    RedisRateLimiterSettings,
    DefaultRateLimitSettings,
    EnvironmentSettings,
    CORSSettings,
):
    pass
```

### Adding Custom Settings

Create your own settings group:

```python
class CustomSettings(BaseSettings):
    CUSTOM_API_KEY: str = ""
    CUSTOM_TIMEOUT: int = 30
    ENABLE_FEATURE_X: bool = False


# Add to main Settings class
class Settings(
    AppSettings,
    # ... other settings ...
    CustomSettings,
):
    pass
```

### Opting Out of Services

Remove unused services by excluding their settings:

```python
# Minimal setup without Redis services
class Settings(
    AppSettings,
    PostgresSettings,
    CryptSettings,
    FirstUserSettings,
    # Removed: RedisCacheSettings
    # Removed: RedisQueueSettings
    # Removed: RedisRateLimiterSettings
    EnvironmentSettings,
):
    pass
```

## Database Configuration

### Alembic Configuration

Database migrations are configured in the repository-root `alembic.ini`:

```ini
[alembic]
script_location = %(here)s/src/migrations
prepend_sys_path = %(here)s/src
sqlalchemy.url = driver://user:pass@localhost/dbname
```

### Connection Pooling

SQLAlchemy connection pool settings in `src/app/core/db/database.py`:

```python
engine = create_async_engine(settings.DATABASE_URL, **build_database_engine_kwargs(settings))
```

### Database Best Practices

**Connection Pool Sizing:**

- Start with `DATABASE_POOL_SIZE=10`, `DATABASE_MAX_OVERFLOW=20`
- Monitor connection usage and adjust based on load
- Keep `DATABASE_POOL_PRE_PING=true` in long-lived environments
- Use `DATABASE_STATEMENT_TIMEOUT_MS` to cap runaway queries when your workload needs a server-side default

**Migration Strategy:**

- Always backup database before running migrations
- Test migrations on staging environment first
- Use `alembic revision --autogenerate` for model changes

## Security Configuration

### JWT Token Configuration

Customize JWT behavior in `src/app/core/security.py`:

```python
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
```

### CORS Configuration

Customize Cross-Origin Resource Sharing in `src/app/core/setup.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Specify allowed origins
    allow_credentials=True,
    allow_methods=["GET", "POST"],  # Specify allowed methods
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Correlation-ID"],
    expose_headers=["X-Request-ID", "X-Correlation-ID"],
    max_age=600,
)
```

**Production CORS Settings:**

```python
# Never use wildcard (*) in production
allow_origins = (["https://yourapp.com", "https://www.yourapp.com"],)
```

### Security Headers

Add security headers middleware:

```python
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response
```

## Logging Configuration

### Basic Logging Setup

Configure logging in `src/app/core/logger.py`:

```python
import logging
from logging.handlers import RotatingFileHandler

# Set log level
LOGGING_LEVEL = logging.INFO

# Configure file rotation
file_handler = RotatingFileHandler("logs/app.log", maxBytes=10485760, backupCount=5)  # 10MB  # Keep 5 backup files
```

### Structured Logging

Use structured logging for better observability:

```python
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)
```

### Log Levels by Environment

```python
# Environment-specific log levels
LOG_LEVELS = {"local": logging.DEBUG, "staging": logging.INFO, "production": logging.WARNING}

LOGGING_LEVEL = LOG_LEVELS.get(settings.ENVIRONMENT, logging.INFO)
```

## Environment-Specific Configurations

### Development (.env.development)

```env
ENVIRONMENT="local"
POSTGRES_SERVER="localhost"
REDIS_CACHE_HOST="localhost"
SECRET_KEY="dev-secret-key-not-for-production"
ACCESS_TOKEN_EXPIRE_MINUTES=60  # Longer for development
DEBUG=true
```

### Staging (.env.staging)

```env
ENVIRONMENT="staging"
POSTGRES_SERVER="staging-db.example.com"
REDIS_CACHE_HOST="staging-redis.example.com"
SECRET_KEY="staging-secret-key-different-from-prod"
ACCESS_TOKEN_EXPIRE_MINUTES=30
DEBUG=false
```

### Production (.env.production)

```env
ENVIRONMENT="production"
POSTGRES_SERVER="prod-db.example.com"
REDIS_CACHE_HOST="prod-redis.example.com"
SECRET_KEY="ultra-secure-production-key-generated-with-openssl"
ACCESS_TOKEN_EXPIRE_MINUTES=15
DEBUG=false
REDIS_CACHE_PORT=6380  # Custom port for security
POSTGRES_PORT=5433     # Custom port for security
```

## Advanced Configuration

### Custom Middleware

Add custom middleware in `src/app/core/setup.py`:

```python
def create_application(router, settings, **kwargs):
    app = FastAPI(...)

    # Add custom middleware
    app.add_middleware(CustomMiddleware, setting=value)
    app.add_middleware(TimingMiddleware)
    app.add_middleware(RequestIDMiddleware)

    return app
```

### Feature Toggles

Implement feature flags:

```python
class FeatureSettings(BaseSettings):
    ENABLE_ADVANCED_CACHING: bool = False
    ENABLE_ANALYTICS: bool = True
    ENABLE_EXPERIMENTAL_FEATURES: bool = False
    ENABLE_API_VERSIONING: bool = True


# Use in endpoints
if settings.ENABLE_ADVANCED_CACHING:
    # Advanced caching logic
    pass
```

## Configuration Validation

### Environment Validation

Add validation to prevent misconfiguration:

```python
def validate_settings():
    if not settings.SECRET_KEY:
        raise ValueError("SECRET_KEY must be set")

    if settings.ENVIRONMENT == "production":
        if settings.SECRET_KEY == "dev-secret-key":
            raise ValueError("Production must use secure SECRET_KEY")

        if settings.DEBUG:
            raise ValueError("DEBUG must be False in production")
```

### Runtime Checks

Add validation to application startup:

```python
@app.on_event("startup")
async def startup_event():
    validate_settings()
    await check_database_connection()
    await check_redis_connection()
    logger.info(f"Application started in {settings.ENVIRONMENT} mode")
```

## Configuration Troubleshooting

### Common Issues

**Environment Variables Not Loading:**

```bash
# Check file location and permissions
ls -la src/.env

# Check file format (no spaces around =)
cat src/.env | grep "=" | head -5

# Verify environment loading in Python
python -c "from src.app.core.config import settings; print(settings.APP_NAME)"
```

**Database Connection Failed:**

```bash
# Test connection manually
psql -h localhost -U postgres -d myapp

# Check if PostgreSQL is running
systemctl status postgresql
# or on macOS
brew services list | grep postgresql
```

**Redis Connection Failed:**

```bash
# Test Redis connection
redis-cli -h localhost -p 6379 ping

# Check Redis status
systemctl status redis
# or on macOS
brew services list | grep redis
```

### Configuration Testing

Test your configuration with a simple script:

```python
# test_config.py
import asyncio
from src.app.core.config import settings
from src.app.core.db.database import async_get_db


async def test_config():
    print(f"App: {settings.APP_NAME}")
    print(f"Environment: {settings.ENVIRONMENT}")

    # Test database
    try:
        db = await anext(async_get_db())
        print("✓ Database connection successful")
        await db.close()
    except Exception as e:
        print(f"✗ Database connection failed: {e}")

    # Test Redis (if enabled)
    try:
        from src.app.core.utils.cache import redis_client

        await redis_client.ping()
        print("✓ Redis connection successful")
    except Exception as e:
        print(f"✗ Redis connection failed: {e}")


if __name__ == "__main__":
    asyncio.run(test_config())
```

Run with:

```bash
uv run python test_config.py
```
