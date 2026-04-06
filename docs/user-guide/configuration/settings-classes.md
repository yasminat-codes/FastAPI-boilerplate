# Settings Classes

Learn how Python settings classes validate, structure, and organize your application configuration. The boilerplate uses Pydantic's `BaseSettings` for type-safe configuration management.

## Settings Architecture

The template keeps a compatibility `Settings` base class, then layers environment-specific profiles on top:

```python
# src/app/core/config.py
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
    TrustedHostSettings,
    ProxyHeadersSettings,
):
    pass


class LocalSettings(Settings):
    ENVIRONMENT = "local"


class StagingSettings(Settings):
    ENVIRONMENT = "staging"


class ProductionSettings(Settings):
    ENVIRONMENT = "production"


# Single instance used throughout the app
settings = load_settings()
```

The template also uses environment-specific settings profiles. `load_settings()` selects `LocalSettings`, `StagingSettings`, or `ProductionSettings` from `ENVIRONMENT`, and the staging/production profiles reject unsafe placeholder values before the app boots.

## Built-in Settings Groups

### Application Settings

Basic app metadata and configuration:

```python
class AppSettings(BaseSettings):
    APP_NAME: str = "FastAPI"
    APP_DESCRIPTION: str = "A FastAPI project"
    APP_VERSION: str = "0.1.0"
    CONTACT_NAME: str = "Your Name"
    CONTACT_EMAIL: str = "your.email@example.com"
    LICENSE_NAME: str = "MIT"
```

### Database Settings

PostgreSQL connection configuration:

```python
class PostgresSettings(BaseSettings):
    DATABASE_URL_INPUT: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_URL"),
    )
    DATABASE_POOL_SIZE: int = Field(default=10, ge=1)
    DATABASE_MAX_OVERFLOW: int = Field(default=20, ge=0)
    DATABASE_POOL_PRE_PING: bool = True
    DATABASE_POOL_RECYCLE: int = Field(default=1800, ge=-1)
    DATABASE_POOL_TIMEOUT: int = Field(default=30, ge=1)
    DATABASE_CONNECT_TIMEOUT: float = Field(default=10.0, gt=0)
    DATABASE_COMMAND_TIMEOUT: float = Field(default=60.0, gt=0)
    DATABASE_STATEMENT_TIMEOUT_MS: int | None = Field(default=None, ge=1)
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        # Prefer DATABASE_URL/POSTGRES_URL when provided, otherwise compose
        # from POSTGRES_* settings and normalize to the async runtime driver.
        ...

    @computed_field
    @property
    def DATABASE_SYNC_URL(self) -> str:
        # Derived sync URL for migrations and sync tooling.
        ...
```

`DATABASE_URL` is the first-class input for the template. When it is absent, the template composes an equivalent PostgreSQL connection from `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_SERVER`, `POSTGRES_PORT`, and `POSTGRES_DB`.
The same settings block also carries pool sizing, pre-ping, recycle, connect timeout, command timeout, statement timeout, and SSL options so the async engine can be tuned without editing runtime code.

### Security Settings

JWT and authentication configuration:

```python
class CryptSettings(BaseSettings):
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ISSUER: str | None = None
    JWT_AUDIENCE: str | None = None
    JWT_ACTIVE_KEY_ID: str = "primary"
    JWT_VERIFICATION_KEYS: dict[str, SecretStr] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_crypt_settings(self) -> Self:
        # Trim optional issuer/audience, require a non-empty active key id,
        # and keep rotation secrets in a kid -> SecretStr verification map.
        ...
```

### Redis Settings

Separate Redis instances for different services:

```python
class RedisCacheSettings(BaseSettings):
    REDIS_CACHE_HOST: str = "localhost"
    REDIS_CACHE_PORT: int = 6379
    REDIS_CACHE_DB: int = 0
    REDIS_CACHE_CONNECT_TIMEOUT: float = 5.0
    REDIS_CACHE_SOCKET_TIMEOUT: float = 5.0
    REDIS_CACHE_RETRY_ATTEMPTS: int = 3
    REDIS_CACHE_SSL: bool = False


class RedisQueueSettings(BaseSettings):
    REDIS_QUEUE_HOST: str = "localhost"
    REDIS_QUEUE_PORT: int = 6379
    REDIS_QUEUE_DB: int = 0
    REDIS_QUEUE_CONNECT_TIMEOUT: int = 5
    REDIS_QUEUE_CONNECT_RETRIES: int = 5
    REDIS_QUEUE_SSL: bool = False


class RedisRateLimiterSettings(BaseSettings):
    REDIS_RATE_LIMIT_HOST: str = "localhost"
    REDIS_RATE_LIMIT_PORT: int = 6379
    REDIS_RATE_LIMIT_DB: int = 0
    REDIS_RATE_LIMIT_CONNECT_TIMEOUT: float = 5.0
    REDIS_RATE_LIMIT_SOCKET_TIMEOUT: float = 5.0
    REDIS_RATE_LIMIT_RETRY_ATTEMPTS: int = 3
    REDIS_RATE_LIMIT_SSL: bool = False
```

Each Redis settings block also carries optional username/password fields, retry backoff settings, max connection limits, and TLS certificate controls. The template uses those settings to build the cache connection pool, ARQ queue connection, and rate-limiter pool without requiring runtime code edits.

### Feature Flag Settings

High-level toggles for optional template modules:

```python
class FeatureFlagsSettings(BaseSettings):
    FEATURE_ADMIN_ENABLED: bool = True
    FEATURE_CLIENT_CACHE_ENABLED: bool = True
    FEATURE_API_AUTH_ROUTES_ENABLED: bool = True
    FEATURE_API_USERS_ENABLED: bool = True
    FEATURE_API_POSTS_ENABLED: bool = True
    FEATURE_API_TIERS_ENABLED: bool = True
    FEATURE_API_RATE_LIMITS_ENABLED: bool = True
```

These settings let adopters keep the shared platform code while disabling starter route groups or template-owned modules such as CRUD admin and client cache middleware.

### Worker Runtime Settings

Template-wide ARQ worker defaults:

```python
class WorkerRuntimeSettings(BaseSettings):
    WORKER_QUEUE_NAME: str = "arq:queue"
    WORKER_MAX_JOBS: int = 10
    WORKER_JOB_MAX_TRIES: int = 3
    WORKER_JOB_RETRY_DELAY_SECONDS: float = 5.0
    WORKER_KEEP_RESULT_SECONDS: float = 3600.0
    WORKER_KEEP_RESULT_FOREVER: bool = False
    WORKER_JOB_EXPIRES_EXTRA_MS: int = 86_400_000
```

These values feed both the canonical `WorkerSettings` entrypoint and the `WorkerJob` base class. That means cloned projects can change queue names, concurrency, retry defaults, and result retention without editing worker code.

### Webhook Runtime Settings

Template-wide defaults for future webhook ingestion modules:

```python
class WebhookRuntimeSettings(BaseSettings):
    WEBHOOK_SIGNATURE_VERIFICATION_ENABLED: bool = True
    WEBHOOK_SIGNATURE_MAX_AGE_SECONDS: int = 300
    WEBHOOK_REPLAY_PROTECTION_ENABLED: bool = True
    WEBHOOK_REPLAY_WINDOW_SECONDS: int = 300
    WEBHOOK_STORE_RAW_PAYLOADS: bool = True
    WEBHOOK_PAYLOAD_RETENTION_DAYS: int = 7
```

These settings give cloned projects a generic contract for provider verification requirements, replay acceptance windows, and raw payload retention before any provider-specific webhook adapters are added.

### CORS Settings

Template-wide cross-origin defaults:

```python
class CORSSettings(BaseSettings):
    CORS_ORIGINS: list[str] = []
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_METHODS: list[str] = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    CORS_HEADERS: list[str] = [
        "Accept",
        "Authorization",
        "Content-Type",
        "X-Requested-With",
        "X-Request-ID",
        "X-Correlation-ID",
    ]
    CORS_EXPOSE_HEADERS: list[str] = ["X-Request-ID", "X-Correlation-ID"]
    CORS_MAX_AGE: int = 600
```

The base settings now fail closed by default: if a secure environment does not specify `CORS_ORIGINS`, the template does not allow cross-origin browser access. The `LocalSettings` profile overrides `CORS_ORIGINS` with a small set of common localhost frontend ports so development stays easy without using `*`.

### Security Header Settings

Reusable response-header hardening controls:

```python
class SecurityHeadersSettings(BaseSettings):
    SECURITY_HEADERS_ENABLED: bool = True
    SECURITY_HEADERS_FRAME_OPTIONS: FrameOptions | None = FrameOptions.DENY
    SECURITY_HEADERS_CONTENT_TYPE_OPTIONS: bool = True
    SECURITY_HEADERS_REFERRER_POLICY: ReferrerPolicy | None = ReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN
    SECURITY_HEADERS_CONTENT_SECURITY_POLICY: str | None = None
    SECURITY_HEADERS_PERMISSIONS_POLICY: str | None = None
    SECURITY_HEADERS_CROSS_ORIGIN_OPENER_POLICY: CrossOriginOpenerPolicy | None = (
        CrossOriginOpenerPolicy.SAME_ORIGIN
    )
    SECURITY_HEADERS_CROSS_ORIGIN_RESOURCE_POLICY: CrossOriginResourcePolicy | None = (
        CrossOriginResourcePolicy.SAME_ORIGIN
    )
    SECURITY_HEADERS_HSTS_ENABLED: bool = False
```

These values feed the template’s `SecurityHeadersMiddleware`, which adds baseline headers without forcing adopters into one CSP or deployment-specific HSTS posture.

### Refresh Token Cookie Settings

Cookie controls for the built-in auth refresh flow:

```python
class RefreshTokenCookieSettings(BaseSettings):
    REFRESH_TOKEN_COOKIE_NAME: str = "refresh_token"
    REFRESH_TOKEN_COOKIE_PATH: str = "/"
    REFRESH_TOKEN_COOKIE_DOMAIN: str | None = None
    REFRESH_TOKEN_COOKIE_SECURE: bool = True
    REFRESH_TOKEN_COOKIE_HTTPONLY: bool = True
    REFRESH_TOKEN_COOKIE_SAMESITE: CookieSameSite = CookieSameSite.LAX
```

The `LocalSettings` profile overrides `REFRESH_TOKEN_COOKIE_SECURE` to `False` so the built-in auth flow still works over local HTTP. Staging and production profiles reject insecure refresh-cookie transport before the app boots.

### Trusted Host Settings

Optional host-header allowlist controls:

```python
class TrustedHostSettings(BaseSettings):
    TRUSTED_HOSTS: list[str] = []
    TRUSTED_HOSTS_WWW_REDIRECT: bool = True
```

When `TRUSTED_HOSTS` is non-empty, the template adds Starlette's `TrustedHostMiddleware`. Exact hostnames and `*.` subdomain patterns are allowed, while secure environments reject the catch-all `"*"` value.

### Proxy Header Settings

Optional forwarded-header trust controls:

```python
class ProxyHeadersSettings(BaseSettings):
    PROXY_HEADERS_ENABLED: bool = False
    PROXY_HEADERS_TRUSTED_PROXIES: list[str] = []
```

These settings feed Uvicorn's `ProxyHeadersMiddleware`. Template adopters can opt in to forwarded client IP and scheme handling only after supplying the proxy IPs, CIDRs, or literals they explicitly trust.

### Request Body Limit Settings

Reusable request-size guardrails:

```python
class RequestBodyLimitSettings(BaseSettings):
    REQUEST_BODY_LIMIT_ENABLED: bool = True
    REQUEST_BODY_MAX_BYTES: int = 1_048_576
    REQUEST_BODY_LIMIT_EXEMPT_PATH_PREFIXES: list[str] = []
```

These settings feed `RequestBodyLimitMiddleware`, which rejects oversized request bodies with a standard `413` API payload while still allowing path-prefix exemptions for intentionally larger routes.

### Request Timeout Settings

Optional application-layer request timeouts:

```python
class RequestTimeoutSettings(BaseSettings):
    REQUEST_TIMEOUT_ENABLED: bool = False
    REQUEST_TIMEOUT_SECONDS: float = 30.0
    REQUEST_TIMEOUT_EXEMPT_PATH_PREFIXES: list[str] = []
```

These settings feed `RequestTimeoutMiddleware`. The timeout is disabled by default so cloned projects can align it with ingress, proxy, and workload expectations instead of inheriting an arbitrary hard cutoff.

### Log Redaction Settings

Structured-log redaction controls:

```python
class LogRedactionSettings(BaseSettings):
    LOG_REDACTION_ENABLED: bool = True
    LOG_REDACTION_EXACT_FIELDS: list[str] = [...]
    LOG_REDACTION_SUBSTRING_FIELDS: list[str] = [...]
    LOG_REDACTION_REPLACEMENT: str = "[REDACTED]"
```

These settings feed the shared structlog redaction processor so nested headers, tokens, secrets, cookies, and PII-like keys are scrubbed before console or file log rendering.

### Sentry Settings

Current Sentry runtime settings:

```python
class SentrySettings(BaseSettings):
    SENTRY_ENABLE: bool = False
    SENTRY_DSN: SecretStr | None = None
    SENTRY_ENVIRONMENT: str = "local"
    SENTRY_RELEASE: str | None = None
    SENTRY_DEBUG: bool = False
    SENTRY_ATTACH_STACKTRACE: bool = True
    SENTRY_SEND_DEFAULT_PII: bool = False
    SENTRY_MAX_BREADCRUMBS: int = 100
    SENTRY_TRACES_SAMPLE_RATE: float = 1.0
    SENTRY_PROFILES_SAMPLE_RATE: float = 1.0
```

These values feed the existing Sentry initialization hook in the template runtime, so cloned projects can control capture behavior without editing startup code.

### Metrics Settings

Template-wide metrics configuration hooks:

```python
class MetricsSettings(BaseSettings):
    METRICS_ENABLED: bool = False
    METRICS_PATH: str = "/metrics"
    METRICS_NAMESPACE: str = "fastapi_template"
    METRICS_INCLUDE_REQUEST_PATH_LABELS: bool = False
```

These values establish a stable configuration contract for the later metrics endpoint and instrumentation work without forcing a metrics backend into the template yet.

### Tracing Settings

Template-wide tracing configuration hooks:

```python
class TracingSettings(BaseSettings):
    TRACING_ENABLED: bool = False
    TRACING_EXPORTER: TracingExporter = TracingExporter.OTLP
    TRACING_SAMPLE_RATE: float = 1.0
    TRACING_SERVICE_NAME: str | None = None
    TRACING_PROPAGATE_CORRELATION_IDS: bool = True
```

These settings give future tracing middleware and worker instrumentation a consistent place to read exporter, service-name, and sampling defaults.

### Log Verbosity Settings

Validated logging level controls:

```python
class LogVerbositySettings(BaseSettings):
    LOG_LEVEL: LogLevel = LogLevel.INFO
    UVICORN_LOG_LEVEL: LogLevel = LogLevel.INFO


class FileLoggerSettings(BaseSettings):
    FILE_LOG_LEVEL: LogLevel = LogLevel.INFO


class ConsoleLoggerSettings(BaseSettings):
    CONSOLE_LOG_LEVEL: LogLevel = LogLevel.INFO
```

These settings drive the existing root logger, Uvicorn logger integration, and structured file/console handlers, so verbosity can be adjusted through environment variables instead of code edits.

### Rate Limiting Settings

Default rate limiting configuration:

```python
class DefaultRateLimitSettings(BaseSettings):
    DEFAULT_RATE_LIMIT_LIMIT: int = 10
    DEFAULT_RATE_LIMIT_PERIOD: int = 3600  # 1 hour
```

### Admin User Settings

First superuser account creation:

```python
class FirstUserSettings(BaseSettings):
    ADMIN_NAME: str = "Admin"
    ADMIN_EMAIL: str
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str

    @field_validator("ADMIN_EMAIL")
    @classmethod
    def validate_admin_email(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("ADMIN_EMAIL must be a valid email")
        return v
```

## Creating Custom Settings

### Basic Custom Settings

Add your own settings group:

```python
class CustomSettings(BaseSettings):
    CUSTOM_API_KEY: str = ""
    CUSTOM_TIMEOUT: int = 30
    ENABLE_FEATURE_X: bool = False
    MAX_UPLOAD_SIZE: int = 10485760  # 10MB

    @field_validator("MAX_UPLOAD_SIZE")
    @classmethod
    def validate_upload_size(cls, v: int) -> int:
        if v < 1024:  # 1KB minimum
            raise ValueError("MAX_UPLOAD_SIZE must be at least 1KB")
        if v > 104857600:  # 100MB maximum
            raise ValueError("MAX_UPLOAD_SIZE cannot exceed 100MB")
        return v


# Add to main Settings class
class Settings(
    AppSettings,
    PostgresSettings,
    # ... other settings ...
    CustomSettings,  # Add your custom settings
):
    pass
```

### Advanced Custom Settings

Settings with complex validation and computed fields:

```python
class EmailSettings(BaseSettings):
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    EMAIL_FROM: str = ""
    EMAIL_FROM_NAME: str = ""

    @computed_field
    @property
    def EMAIL_ENABLED(self) -> bool:
        return bool(self.SMTP_HOST and self.SMTP_USERNAME)

    @model_validator(mode="after")
    def validate_email_config(self) -> "EmailSettings":
        if self.SMTP_HOST and not self.EMAIL_FROM:
            raise ValueError("EMAIL_FROM required when SMTP_HOST is set")
        if self.SMTP_USERNAME and not self.SMTP_PASSWORD:
            raise ValueError("SMTP_PASSWORD required when SMTP_USERNAME is set")
        return self
```

### Feature Flag Settings

Organize feature toggles:

```python
class FeatureSettings(BaseSettings):
    # Core features
    ENABLE_CACHING: bool = True
    ENABLE_RATE_LIMITING: bool = True
    ENABLE_BACKGROUND_JOBS: bool = True

    # Optional features
    ENABLE_ANALYTICS: bool = False
    ENABLE_EMAIL_NOTIFICATIONS: bool = False
    ENABLE_FILE_UPLOADS: bool = False

    # Experimental features
    ENABLE_EXPERIMENTAL_API: bool = False
    ENABLE_BETA_FEATURES: bool = False

    @model_validator(mode="after")
    def validate_feature_dependencies(self) -> "FeatureSettings":
        if self.ENABLE_EMAIL_NOTIFICATIONS and not self.ENABLE_BACKGROUND_JOBS:
            raise ValueError("Email notifications require background jobs")
        return self
```

## Settings Validation

### Field Validation

Validate individual fields:

```python
class DatabaseSettings(BaseSettings):
    DATABASE_POOL_SIZE: int = Field(default=10, ge=1)
    DATABASE_POOL_TIMEOUT: int = Field(default=30, ge=1)

    @field_validator("DATABASE_POOL_SIZE")
    @classmethod
    def validate_pool_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Pool size must be at least 1")
        if v > 100:
            raise ValueError("Pool size should not exceed 100")
        return v

    @field_validator("DATABASE_POOL_TIMEOUT")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if v < 5:
            raise ValueError("Timeout must be at least 5 seconds")
        return v
```

### Model Validation

Validate across multiple fields:

```python
class SecuritySettings(BaseSettings):
    DATABASE_SSL_MODE: str = "disable"
    DATABASE_SSL_CA_FILE: str | None = None
    DATABASE_SSL_CERT_FILE: str | None = None
    DATABASE_SSL_KEY_FILE: str | None = None

    @model_validator(mode="after")
    def validate_ssl_config(self) -> "SecuritySettings":
        if self.DATABASE_SSL_MODE in {"verify-ca", "verify-full"} and not self.DATABASE_SSL_CA_FILE:
            raise ValueError("DATABASE_SSL_CA_FILE is required for verified SSL modes")

        if bool(self.DATABASE_SSL_CERT_FILE) != bool(self.DATABASE_SSL_KEY_FILE):
            raise ValueError("DATABASE_SSL_CERT_FILE and DATABASE_SSL_KEY_FILE must be set together")

        return self
```

### Environment-Specific Validation

Different validation rules per environment:

```python
class EnvironmentSettings(BaseSettings):
    ENVIRONMENT: str = "local"
    DEBUG: bool = True

    @model_validator(mode="after")
    def validate_environment_config(self) -> "EnvironmentSettings":
        if self.ENVIRONMENT == "production":
            if self.DEBUG:
                raise ValueError("DEBUG must be False in production")

        if self.ENVIRONMENT not in ["local", "staging", "production"]:
            raise ValueError("ENVIRONMENT must be local, staging, or production")

        return self
```

## Computed Properties

### Dynamic Configuration

Create computed values from other settings:

```python
class StorageSettings(BaseSettings):
    STORAGE_TYPE: str = "local"  # local, s3, gcs

    # Local storage
    LOCAL_STORAGE_PATH: str = "./uploads"

    # S3 settings
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_BUCKET_NAME: str = ""
    AWS_REGION: str = "us-east-1"

    @computed_field
    @property
    def STORAGE_ENABLED(self) -> bool:
        if self.STORAGE_TYPE == "local":
            return bool(self.LOCAL_STORAGE_PATH)
        elif self.STORAGE_TYPE == "s3":
            return bool(self.AWS_ACCESS_KEY_ID and self.AWS_SECRET_ACCESS_KEY and self.AWS_BUCKET_NAME)
        return False

    @computed_field
    @property
    def STORAGE_CONFIG(self) -> dict:
        if self.STORAGE_TYPE == "local":
            return {"path": self.LOCAL_STORAGE_PATH}
        elif self.STORAGE_TYPE == "s3":
            return {
                "bucket": self.AWS_BUCKET_NAME,
                "region": self.AWS_REGION,
                "credentials": {
                    "access_key": self.AWS_ACCESS_KEY_ID,
                    "secret_key": self.AWS_SECRET_ACCESS_KEY,
                },
            }
        return {}
```

## Organizing Settings

### Service-Based Organization

Group settings by service or domain:

```python
# Authentication service settings
class AuthSettings(BaseSettings):
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE: int = 30
    REFRESH_TOKEN_EXPIRE: int = 7200
    PASSWORD_MIN_LENGTH: int = 8


# Notification service settings
class NotificationSettings(BaseSettings):
    EMAIL_ENABLED: bool = False
    SMS_ENABLED: bool = False
    PUSH_ENABLED: bool = False

    # Email settings
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587

    # SMS settings (example with Twilio)
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""


# Main settings
class Settings(
    AppSettings,
    AuthSettings,
    NotificationSettings,
    # ... other settings
):
    pass
```

### Conditional Settings Loading

Load different settings based on environment:

```python
class BaseAppSettings(BaseSettings):
    APP_NAME: str = "FastAPI App"
    DEBUG: bool = False


class DevelopmentSettings(BaseAppSettings):
    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"
    DATABASE_ECHO: bool = True


class ProductionSettings(BaseAppSettings):
    DEBUG: bool = False
    LOG_LEVEL: str = "WARNING"
    DATABASE_ECHO: bool = False


def get_settings() -> BaseAppSettings:
    environment = os.getenv("ENVIRONMENT", "local")

    if environment == "production":
        return ProductionSettings()
    else:
        return DevelopmentSettings()


settings = get_settings()
```

## Removing Unused Services

### Minimal Configuration

Remove services you don't need:

```python
# Minimal setup without Redis services
class MinimalSettings(
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

### Service Feature Flags

Use feature flags to conditionally enable services:

```python
class ServiceSettings(BaseSettings):
    ENABLE_REDIS: bool = True
    ENABLE_CELERY: bool = True
    ENABLE_MONITORING: bool = False


class ConditionalSettings(
    AppSettings,
    PostgresSettings,
    CryptSettings,
    ServiceSettings,
):
    # Add Redis settings only if enabled
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        if self.ENABLE_REDIS:
            # Dynamically add Redis settings
            self.__class__ = type("ConditionalSettings", (self.__class__, RedisCacheSettings), {})
```

## Testing Settings

### Test Configuration

Create separate settings for testing:

```python
class TestSettings(BaseSettings):
    # Override database for testing
    POSTGRES_DB: str = "test_database"

    # Disable external services
    ENABLE_REDIS: bool = False
    ENABLE_EMAIL: bool = False

    # Speed up tests
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 5

    # Test-specific settings
    TEST_USER_EMAIL: str = "test@example.com"
    TEST_USER_PASSWORD: str = "testpassword123"


# Use in tests
@pytest.fixture
def test_settings():
    return TestSettings()
```

### Settings Validation Testing

Test your custom settings:

```python
def test_custom_settings_validation():
    # Test valid configuration
    settings = CustomSettings(CUSTOM_API_KEY="test-key", CUSTOM_TIMEOUT=60, MAX_UPLOAD_SIZE=5242880)  # 5MB
    assert settings.CUSTOM_TIMEOUT == 60

    # Test validation error
    with pytest.raises(ValueError, match="MAX_UPLOAD_SIZE cannot exceed 100MB"):
        CustomSettings(MAX_UPLOAD_SIZE=209715200)  # 200MB


def test_settings_computed_fields():
    settings = StorageSettings(
        STORAGE_TYPE="s3",
        AWS_ACCESS_KEY_ID="test-key",
        AWS_SECRET_ACCESS_KEY="test-secret",
        AWS_BUCKET_NAME="test-bucket",
    )

    assert settings.STORAGE_ENABLED is True
    assert settings.STORAGE_CONFIG["bucket"] == "test-bucket"
```

## Best Practices

### Organization

- Group related settings in dedicated classes
- Use descriptive names for settings groups
- Keep validation logic close to the settings
- Document complex validation rules

### Security

- Validate sensitive settings like secret keys
- Never set default values for secrets in production
- Use computed fields to derive connection strings
- Separate test and production configurations

### Performance

- Use `@computed_field` for expensive calculations
- Cache settings instances appropriately
- Avoid complex validation in hot paths
- Use model validators for cross-field validation

### Testing

- Create separate test settings classes
- Test all validation rules
- Mock external service settings in tests
- Use dependency injection for settings in tests

The settings system provides type safety, validation, and organization for your application configuration. Start with the built-in settings and extend them as your application grows!
