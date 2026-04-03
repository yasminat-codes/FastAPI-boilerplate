import os
from enum import Enum
from typing import Any, Self, TypeAlias, cast
from urllib.parse import quote

from pydantic import AliasChoices, Field, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

PRODUCTION_UNSAFE_SECRET_VALUES = {
    "secret-key",
    "your-generated-secret-key-here",
    "your-super-secret-key-here",
    "change-me-to-a-random-secret-key",
    "changeme",
    "change-me",
    "change_me",
}

PRODUCTION_UNSAFE_PASSWORD_VALUES = {
    "postgres",
    "password",
    "1234",
    "!ch4ng3th1sp4ssw0rd!",
    "str1ngst!",
    "your_password",
    "your-password",
    "your_secure_password",
    "your-secure-password",
    "change-me-postgres-password",
    "change-me-admin-password",
    "changeme",
    "change-me",
    "change_me",
}

LOCAL_DEVELOPMENT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:4200",
    "http://127.0.0.1:4200",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
)


def _normalize_setting_value(value: str) -> str:
    return value.strip().casefold()


DEFAULT_ENV_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", ".env")

POSTGRES_SYNC_DRIVER = "postgresql"
POSTGRES_ASYNC_DRIVER = "postgresql+asyncpg"


def _normalize_postgres_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql://", 1)
    return database_url


def _parse_postgres_database_url(database_url: str) -> URL:
    parsed_url = make_url(_normalize_postgres_database_url(database_url))

    if parsed_url.get_backend_name() != "postgresql":
        raise ValueError("DATABASE_URL must use a PostgreSQL URL")

    return parsed_url


def _build_redis_url(
    *,
    host: str,
    port: int,
    database: int,
    username: str | None,
    password: str | None,
    ssl_enabled: bool,
) -> str:
    scheme = "rediss" if ssl_enabled else "redis"

    auth = ""
    if username is not None:
        auth = quote(username, safe="")
        if password is not None:
            auth = f"{auth}:{quote(password, safe='')}"
        auth = f"{auth}@"
    elif password is not None:
        auth = f":{quote(password, safe='')}@"

    return f"{scheme}://{auth}{host}:{port}/{database}"


def _validate_redis_tls_settings(
    *,
    service_name: str,
    ssl_enabled: bool,
    ssl_check_hostname: bool,
    ssl_ca_certs: str | None,
    ssl_certfile: str | None,
    ssl_keyfile: str | None,
) -> None:
    if (ssl_certfile is None) != (ssl_keyfile is None):
        raise ValueError(f"{service_name}_SSL_CERTFILE and {service_name}_SSL_KEYFILE must be provided together")

    if not ssl_enabled and any(
        value is not None or ssl_check_hostname
        for value in (ssl_ca_certs, ssl_certfile, ssl_keyfile)
    ):
        raise ValueError(f"{service_name}_SSL must be enabled before TLS certificate settings can be used")


def _validate_redis_retry_settings(
    *,
    service_name: str,
    retry_attempts: int,
    retry_base_delay: float,
    retry_max_delay: float,
) -> None:
    if retry_attempts == 0:
        return

    if retry_max_delay < retry_base_delay:
        raise ValueError(
            f"{service_name}_RETRY_MAX_DELAY must be greater than or equal to {service_name}_RETRY_BASE_DELAY"
        )


def _normalize_string_list(*, setting_name: str, values: list[str]) -> list[str]:
    normalized_values: list[str] = []

    for value in values:
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{setting_name} must not contain blank values")
        normalized_values.append(stripped)

    return normalized_values


def _validate_allowed_host_patterns(*, setting_name: str, values: list[str]) -> None:
    for value in values:
        if "*" not in value:
            continue

        if value != "*" and not value.startswith("*."):
            raise ValueError(f"{setting_name} wildcard entries must be '*' or start with '*.'")

        if "*" in value[1:]:
            raise ValueError(f"{setting_name} wildcard entries must be '*' or start with '*.'")


class AppSettings(BaseSettings):
    APP_NAME: str = "FastAPI app"
    APP_DESCRIPTION: str | None = None
    APP_VERSION: str | None = None
    LICENSE_NAME: str | None = None
    CONTACT_NAME: str | None = None
    CONTACT_EMAIL: str | None = None


class CryptSettings(BaseSettings):
    SECRET_KEY: SecretStr = SecretStr("secret-key")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class FileLoggerSettings(BaseSettings):
    FILE_LOG_MAX_BYTES: int = 10 * 1024 * 1024
    FILE_LOG_BACKUP_COUNT: int = 5
    FILE_LOG_FORMAT_JSON: bool = True
    FILE_LOG_LEVEL: LogLevel = LogLevel.INFO

    # Include request ID, path, method, client host, and status code in the file log
    FILE_LOG_INCLUDE_REQUEST_ID: bool = True
    FILE_LOG_INCLUDE_PATH: bool = True
    FILE_LOG_INCLUDE_METHOD: bool = True
    FILE_LOG_INCLUDE_CLIENT_HOST: bool = True
    FILE_LOG_INCLUDE_STATUS_CODE: bool = True


class ConsoleLoggerSettings(BaseSettings):
    CONSOLE_LOG_LEVEL: LogLevel = LogLevel.INFO
    CONSOLE_LOG_FORMAT_JSON: bool = False

    # Include request ID, path, method, client host, and status code in the console log
    CONSOLE_LOG_INCLUDE_REQUEST_ID: bool = False
    CONSOLE_LOG_INCLUDE_PATH: bool = False
    CONSOLE_LOG_INCLUDE_METHOD: bool = False
    CONSOLE_LOG_INCLUDE_CLIENT_HOST: bool = False
    CONSOLE_LOG_INCLUDE_STATUS_CODE: bool = False


class LogVerbositySettings(BaseSettings):
    LOG_LEVEL: LogLevel = LogLevel.INFO
    UVICORN_LOG_LEVEL: LogLevel = LogLevel.INFO


class DatabaseSettings(BaseSettings):
    pass


class SQLiteSettings(DatabaseSettings):
    SQLITE_URI: str = "./sql_app.db"
    SQLITE_SYNC_PREFIX: str = "sqlite:///"
    SQLITE_ASYNC_PREFIX: str = "sqlite+aiosqlite:///"


class MySQLSettings(DatabaseSettings):
    MYSQL_USER: str = "username"
    MYSQL_PASSWORD: str = "password"
    MYSQL_SERVER: str = "localhost"
    MYSQL_PORT: int = 5432
    MYSQL_DB: str = "dbname"
    MYSQL_SYNC_PREFIX: str = "mysql://"
    MYSQL_ASYNC_PREFIX: str = "mysql+aiomysql://"
    MYSQL_URL: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def MYSQL_URI(self) -> str:
        credentials = f"{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
        location = f"{self.MYSQL_SERVER}:{self.MYSQL_PORT}/{self.MYSQL_DB}"
        return f"{credentials}@{location}"


class DatabaseSSLMode(str, Enum):
    DISABLE = "disable"
    REQUIRE = "require"
    VERIFY_CA = "verify-ca"
    VERIFY_FULL = "verify-full"


class RedisSSLCertRequirements(str, Enum):
    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


class PostgresSettings(DatabaseSettings):
    DATABASE_URL_INPUT: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_URL"),
        exclude=True,
        repr=False,
    )
    DATABASE_POOL_SIZE: int = Field(default=10, ge=1)
    DATABASE_MAX_OVERFLOW: int = Field(default=20, ge=0)
    DATABASE_POOL_PRE_PING: bool = True
    DATABASE_POOL_USE_LIFO: bool = True
    DATABASE_POOL_RECYCLE: int = Field(default=1800, ge=-1)
    DATABASE_POOL_TIMEOUT: int = Field(default=30, ge=1)
    DATABASE_CONNECT_TIMEOUT: float = Field(default=10.0, gt=0)
    DATABASE_COMMAND_TIMEOUT: float = Field(default=60.0, gt=0)
    DATABASE_STATEMENT_TIMEOUT_MS: int | None = Field(default=None, ge=1)
    DATABASE_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS: int | None = Field(default=None, ge=1)
    DATABASE_STARTUP_RETRY_ATTEMPTS: int = Field(default=3, ge=0)
    DATABASE_STARTUP_RETRY_BASE_DELAY: float = Field(default=0.5, gt=0)
    DATABASE_STARTUP_RETRY_MAX_DELAY: float = Field(default=5.0, gt=0)
    DATABASE_SSL_MODE: DatabaseSSLMode = DatabaseSSLMode.DISABLE
    DATABASE_SSL_CA_FILE: str | None = None
    DATABASE_SSL_CERT_FILE: str | None = None
    DATABASE_SSL_KEY_FILE: str | None = None
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "postgres"
    POSTGRES_SYNC_PREFIX: str = "postgresql://"
    POSTGRES_ASYNC_PREFIX: str = "postgresql+asyncpg://"

    def _build_postgres_url(self, *, drivername: str) -> URL:
        return URL.create(
            drivername=drivername,
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        )

    def _resolve_postgres_url(self, *, drivername: str) -> URL:
        if self.DATABASE_URL_INPUT is not None:
            return _parse_postgres_database_url(self.DATABASE_URL_INPUT).set(drivername=drivername)

        return self._build_postgres_url(drivername=drivername)

    def _database_password(self) -> str | None:
        return self._resolve_postgres_url(drivername=POSTGRES_ASYNC_DRIVER).password

    @model_validator(mode="after")
    def validate_postgres_runtime_settings(self) -> Self:
        self._resolve_postgres_url(drivername=POSTGRES_ASYNC_DRIVER)

        if (self.DATABASE_SSL_CERT_FILE is None) != (self.DATABASE_SSL_KEY_FILE is None):
            raise ValueError("DATABASE_SSL_CERT_FILE and DATABASE_SSL_KEY_FILE must be provided together")

        if self.DATABASE_STARTUP_RETRY_ATTEMPTS > 0 and (
            self.DATABASE_STARTUP_RETRY_MAX_DELAY < self.DATABASE_STARTUP_RETRY_BASE_DELAY
        ):
            raise ValueError(
                "DATABASE_STARTUP_RETRY_MAX_DELAY must be greater than or equal to DATABASE_STARTUP_RETRY_BASE_DELAY"
            )

        if self.DATABASE_SSL_MODE in {DatabaseSSLMode.VERIFY_CA, DatabaseSSLMode.VERIFY_FULL}:
            if self.DATABASE_SSL_CA_FILE is None:
                raise ValueError(
                    "DATABASE_SSL_CA_FILE is required when DATABASE_SSL_MODE is verify-ca or verify-full"
                )

        if self.DATABASE_SSL_MODE is DatabaseSSLMode.DISABLE and any(
            value is not None for value in (self.DATABASE_SSL_CA_FILE, self.DATABASE_SSL_CERT_FILE)
        ):
            raise ValueError("DATABASE_SSL_MODE must enable SSL before certificate file settings can be used")

        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        return self._resolve_postgres_url(drivername=POSTGRES_ASYNC_DRIVER).render_as_string(hide_password=False)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_SYNC_URL(self) -> str:
        return self._resolve_postgres_url(drivername=POSTGRES_SYNC_DRIVER).render_as_string(hide_password=False)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def POSTGRES_URL(self) -> str:
        return self.DATABASE_URL

    @computed_field  # type: ignore[prop-decorator]
    @property
    def POSTGRES_URI(self) -> str:
        return self.DATABASE_SYNC_URL.removeprefix(self.POSTGRES_SYNC_PREFIX)


class FirstUserSettings(BaseSettings):
    ADMIN_NAME: str = "admin"
    ADMIN_EMAIL: str = "admin@admin.com"
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "!Ch4ng3Th1sP4ssW0rd!"


class TestSettings(BaseSettings):
    ...


class RedisCacheSettings(BaseSettings):
    REDIS_CACHE_HOST: str = "localhost"
    REDIS_CACHE_PORT: int = 6379
    REDIS_CACHE_DB: int = Field(default=0, ge=0)
    REDIS_CACHE_USERNAME: str | None = None
    REDIS_CACHE_PASSWORD: str | None = None
    REDIS_CACHE_CONNECT_TIMEOUT: float = Field(default=5.0, gt=0)
    REDIS_CACHE_SOCKET_TIMEOUT: float = Field(default=5.0, gt=0)
    REDIS_CACHE_RETRY_ATTEMPTS: int = Field(default=3, ge=0)
    REDIS_CACHE_RETRY_BASE_DELAY: float = Field(default=0.1, gt=0)
    REDIS_CACHE_RETRY_MAX_DELAY: float = Field(default=1.0, gt=0)
    REDIS_CACHE_RETRY_ON_TIMEOUT: bool = True
    REDIS_CACHE_MAX_CONNECTIONS: int | None = Field(default=None, ge=1)
    REDIS_CACHE_SSL: bool = False
    REDIS_CACHE_SSL_CHECK_HOSTNAME: bool = False
    REDIS_CACHE_SSL_CERT_REQS: RedisSSLCertRequirements = RedisSSLCertRequirements.REQUIRED
    REDIS_CACHE_SSL_CA_CERTS: str | None = None
    REDIS_CACHE_SSL_CERTFILE: str | None = None
    REDIS_CACHE_SSL_KEYFILE: str | None = None

    @model_validator(mode="after")
    def validate_redis_cache_settings(self) -> Self:
        _validate_redis_tls_settings(
            service_name="REDIS_CACHE",
            ssl_enabled=self.REDIS_CACHE_SSL,
            ssl_check_hostname=self.REDIS_CACHE_SSL_CHECK_HOSTNAME,
            ssl_ca_certs=self.REDIS_CACHE_SSL_CA_CERTS,
            ssl_certfile=self.REDIS_CACHE_SSL_CERTFILE,
            ssl_keyfile=self.REDIS_CACHE_SSL_KEYFILE,
        )
        _validate_redis_retry_settings(
            service_name="REDIS_CACHE",
            retry_attempts=self.REDIS_CACHE_RETRY_ATTEMPTS,
            retry_base_delay=self.REDIS_CACHE_RETRY_BASE_DELAY,
            retry_max_delay=self.REDIS_CACHE_RETRY_MAX_DELAY,
        )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_CACHE_URL(self) -> str:
        return _build_redis_url(
            host=self.REDIS_CACHE_HOST,
            port=self.REDIS_CACHE_PORT,
            database=self.REDIS_CACHE_DB,
            username=self.REDIS_CACHE_USERNAME,
            password=self.REDIS_CACHE_PASSWORD,
            ssl_enabled=self.REDIS_CACHE_SSL,
        )


class ClientSideCacheSettings(BaseSettings):
    CLIENT_CACHE_MAX_AGE: int = 60


class FeatureFlagsSettings(BaseSettings):
    FEATURE_ADMIN_ENABLED: bool = True
    FEATURE_CLIENT_CACHE_ENABLED: bool = True
    FEATURE_API_AUTH_ROUTES_ENABLED: bool = True
    FEATURE_API_USERS_ENABLED: bool = True
    FEATURE_API_POSTS_ENABLED: bool = True
    FEATURE_API_TIERS_ENABLED: bool = True
    FEATURE_API_RATE_LIMITS_ENABLED: bool = True


class RedisQueueSettings(BaseSettings):
    REDIS_QUEUE_HOST: str = "localhost"
    REDIS_QUEUE_PORT: int = 6379
    REDIS_QUEUE_DB: int = Field(default=0, ge=0)
    REDIS_QUEUE_USERNAME: str | None = None
    REDIS_QUEUE_PASSWORD: str | None = None
    REDIS_QUEUE_CONNECT_TIMEOUT: int = Field(default=5, ge=1)
    REDIS_QUEUE_CONNECT_RETRIES: int = Field(default=5, ge=0)
    REDIS_QUEUE_RETRY_DELAY: int = Field(default=1, ge=0)
    REDIS_QUEUE_RETRY_ON_TIMEOUT: bool = True
    REDIS_QUEUE_MAX_CONNECTIONS: int | None = Field(default=None, ge=1)
    REDIS_QUEUE_SSL: bool = False
    REDIS_QUEUE_SSL_CHECK_HOSTNAME: bool = False
    REDIS_QUEUE_SSL_CERT_REQS: RedisSSLCertRequirements = RedisSSLCertRequirements.REQUIRED
    REDIS_QUEUE_SSL_CA_CERTS: str | None = None
    REDIS_QUEUE_SSL_CERTFILE: str | None = None
    REDIS_QUEUE_SSL_KEYFILE: str | None = None

    @model_validator(mode="after")
    def validate_redis_queue_settings(self) -> Self:
        _validate_redis_tls_settings(
            service_name="REDIS_QUEUE",
            ssl_enabled=self.REDIS_QUEUE_SSL,
            ssl_check_hostname=self.REDIS_QUEUE_SSL_CHECK_HOSTNAME,
            ssl_ca_certs=self.REDIS_QUEUE_SSL_CA_CERTS,
            ssl_certfile=self.REDIS_QUEUE_SSL_CERTFILE,
            ssl_keyfile=self.REDIS_QUEUE_SSL_KEYFILE,
        )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_QUEUE_URL(self) -> str:
        return _build_redis_url(
            host=self.REDIS_QUEUE_HOST,
            port=self.REDIS_QUEUE_PORT,
            database=self.REDIS_QUEUE_DB,
            username=self.REDIS_QUEUE_USERNAME,
            password=self.REDIS_QUEUE_PASSWORD,
            ssl_enabled=self.REDIS_QUEUE_SSL,
        )


class WorkerRuntimeSettings(BaseSettings):
    WORKER_QUEUE_NAME: str = "arq:queue"
    WORKER_MAX_JOBS: int = Field(default=10, ge=1)
    WORKER_JOB_MAX_TRIES: int = Field(default=3, ge=1)
    WORKER_JOB_RETRY_DELAY_SECONDS: float = Field(default=5.0, ge=0)
    WORKER_KEEP_RESULT_SECONDS: float = Field(default=3600.0, ge=0)
    WORKER_KEEP_RESULT_FOREVER: bool = False
    WORKER_JOB_EXPIRES_EXTRA_MS: int = Field(default=86_400_000, ge=0)

    @model_validator(mode="after")
    def validate_worker_runtime_settings(self) -> Self:
        if not self.WORKER_QUEUE_NAME.strip():
            raise ValueError("WORKER_QUEUE_NAME must not be empty")

        return self


class WebhookRuntimeSettings(BaseSettings):
    WEBHOOK_SIGNATURE_VERIFICATION_ENABLED: bool = True
    WEBHOOK_SIGNATURE_MAX_AGE_SECONDS: int = Field(default=300, ge=1)
    WEBHOOK_REPLAY_PROTECTION_ENABLED: bool = True
    WEBHOOK_REPLAY_WINDOW_SECONDS: int = Field(default=300, ge=1)
    WEBHOOK_STORE_RAW_PAYLOADS: bool = True
    WEBHOOK_PAYLOAD_RETENTION_DAYS: int = Field(default=7, ge=0)

    @model_validator(mode="after")
    def validate_webhook_runtime_settings(self) -> Self:
        if (
            self.WEBHOOK_SIGNATURE_VERIFICATION_ENABLED
            and self.WEBHOOK_REPLAY_PROTECTION_ENABLED
            and self.WEBHOOK_REPLAY_WINDOW_SECONDS < self.WEBHOOK_SIGNATURE_MAX_AGE_SECONDS
        ):
            raise ValueError(
                "WEBHOOK_REPLAY_WINDOW_SECONDS must be greater than or equal to "
                "WEBHOOK_SIGNATURE_MAX_AGE_SECONDS when verification and replay protection are enabled"
            )

        if self.WEBHOOK_STORE_RAW_PAYLOADS and self.WEBHOOK_PAYLOAD_RETENTION_DAYS < 1:
            raise ValueError(
                "WEBHOOK_PAYLOAD_RETENTION_DAYS must be at least 1 when WEBHOOK_STORE_RAW_PAYLOADS is enabled"
            )

        return self


class RedisRateLimiterSettings(BaseSettings):
    REDIS_RATE_LIMIT_HOST: str = "localhost"
    REDIS_RATE_LIMIT_PORT: int = 6379
    REDIS_RATE_LIMIT_DB: int = Field(default=0, ge=0)
    REDIS_RATE_LIMIT_USERNAME: str | None = None
    REDIS_RATE_LIMIT_PASSWORD: str | None = None
    REDIS_RATE_LIMIT_CONNECT_TIMEOUT: float = Field(default=5.0, gt=0)
    REDIS_RATE_LIMIT_SOCKET_TIMEOUT: float = Field(default=5.0, gt=0)
    REDIS_RATE_LIMIT_RETRY_ATTEMPTS: int = Field(default=3, ge=0)
    REDIS_RATE_LIMIT_RETRY_BASE_DELAY: float = Field(default=0.1, gt=0)
    REDIS_RATE_LIMIT_RETRY_MAX_DELAY: float = Field(default=1.0, gt=0)
    REDIS_RATE_LIMIT_RETRY_ON_TIMEOUT: bool = True
    REDIS_RATE_LIMIT_MAX_CONNECTIONS: int | None = Field(default=None, ge=1)
    REDIS_RATE_LIMIT_SSL: bool = False
    REDIS_RATE_LIMIT_SSL_CHECK_HOSTNAME: bool = False
    REDIS_RATE_LIMIT_SSL_CERT_REQS: RedisSSLCertRequirements = RedisSSLCertRequirements.REQUIRED
    REDIS_RATE_LIMIT_SSL_CA_CERTS: str | None = None
    REDIS_RATE_LIMIT_SSL_CERTFILE: str | None = None
    REDIS_RATE_LIMIT_SSL_KEYFILE: str | None = None

    @model_validator(mode="after")
    def validate_redis_rate_limit_settings(self) -> Self:
        _validate_redis_tls_settings(
            service_name="REDIS_RATE_LIMIT",
            ssl_enabled=self.REDIS_RATE_LIMIT_SSL,
            ssl_check_hostname=self.REDIS_RATE_LIMIT_SSL_CHECK_HOSTNAME,
            ssl_ca_certs=self.REDIS_RATE_LIMIT_SSL_CA_CERTS,
            ssl_certfile=self.REDIS_RATE_LIMIT_SSL_CERTFILE,
            ssl_keyfile=self.REDIS_RATE_LIMIT_SSL_KEYFILE,
        )
        _validate_redis_retry_settings(
            service_name="REDIS_RATE_LIMIT",
            retry_attempts=self.REDIS_RATE_LIMIT_RETRY_ATTEMPTS,
            retry_base_delay=self.REDIS_RATE_LIMIT_RETRY_BASE_DELAY,
            retry_max_delay=self.REDIS_RATE_LIMIT_RETRY_MAX_DELAY,
        )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_RATE_LIMIT_URL(self) -> str:
        return _build_redis_url(
            host=self.REDIS_RATE_LIMIT_HOST,
            port=self.REDIS_RATE_LIMIT_PORT,
            database=self.REDIS_RATE_LIMIT_DB,
            username=self.REDIS_RATE_LIMIT_USERNAME,
            password=self.REDIS_RATE_LIMIT_PASSWORD,
            ssl_enabled=self.REDIS_RATE_LIMIT_SSL,
        )


class DefaultRateLimitSettings(BaseSettings):
    DEFAULT_RATE_LIMIT_LIMIT: int = 10
    DEFAULT_RATE_LIMIT_PERIOD: int = 3600


class CRUDAdminSettings(BaseSettings):
    CRUD_ADMIN_ENABLED: bool = True
    CRUD_ADMIN_MOUNT_PATH: str = "/admin"

    CRUD_ADMIN_ALLOWED_IPS_LIST: list[str] | None = None
    CRUD_ADMIN_ALLOWED_NETWORKS_LIST: list[str] | None = None
    CRUD_ADMIN_MAX_SESSIONS: int = 10
    CRUD_ADMIN_SESSION_TIMEOUT: int = 1440
    SESSION_SECURE_COOKIES: bool = True

    CRUD_ADMIN_TRACK_EVENTS: bool = True
    CRUD_ADMIN_TRACK_SESSIONS: bool = True

    CRUD_ADMIN_REDIS_ENABLED: bool = False
    CRUD_ADMIN_REDIS_HOST: str = "localhost"
    CRUD_ADMIN_REDIS_PORT: int = 6379
    CRUD_ADMIN_REDIS_DB: int = 0
    CRUD_ADMIN_REDIS_PASSWORD: str | None = "None"
    CRUD_ADMIN_REDIS_SSL: bool = False


class EnvironmentOption(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class EnvironmentSettings(BaseSettings):
    ENVIRONMENT: EnvironmentOption = EnvironmentOption.LOCAL


class MetricsSettings(BaseSettings):
    METRICS_ENABLED: bool = False
    METRICS_PATH: str = "/metrics"
    METRICS_NAMESPACE: str = "fastapi_template"
    METRICS_INCLUDE_REQUEST_PATH_LABELS: bool = False

    @model_validator(mode="after")
    def validate_metrics_settings(self) -> Self:
        if not self.METRICS_PATH.strip():
            raise ValueError("METRICS_PATH must not be empty")
        if not self.METRICS_PATH.startswith("/"):
            raise ValueError("METRICS_PATH must start with '/'")
        if not self.METRICS_NAMESPACE.strip():
            raise ValueError("METRICS_NAMESPACE must not be empty")

        return self


class TracingExporter(str, Enum):
    OTLP = "otlp"
    CONSOLE = "console"


class TracingSettings(BaseSettings):
    TRACING_ENABLED: bool = False
    TRACING_EXPORTER: TracingExporter = TracingExporter.OTLP
    TRACING_SAMPLE_RATE: float = Field(default=1.0, ge=0.0, le=1.0)
    TRACING_SERVICE_NAME: str | None = None
    TRACING_PROPAGATE_CORRELATION_IDS: bool = True

    @model_validator(mode="after")
    def validate_tracing_settings(self) -> Self:
        if self.TRACING_SERVICE_NAME is not None and not self.TRACING_SERVICE_NAME.strip():
            raise ValueError("TRACING_SERVICE_NAME must not be empty when provided")

        return self


class SentrySettings(BaseSettings):
    SENTRY_ENABLE: bool = False
    SENTRY_DSN: SecretStr | None = None
    SENTRY_ENVIRONMENT: str = "local"
    SENTRY_RELEASE: str | None = None
    SENTRY_DEBUG: bool = False
    SENTRY_ATTACH_STACKTRACE: bool = True
    SENTRY_SEND_DEFAULT_PII: bool = False
    SENTRY_MAX_BREADCRUMBS: int = Field(default=100, ge=0)
    SENTRY_TRACES_SAMPLE_RATE: float = Field(default=1.0, ge=0.0, le=1.0)
    SENTRY_PROFILES_SAMPLE_RATE: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_sentry_settings(self) -> Self:
        if self.SENTRY_ENABLE and self.SENTRY_DSN is None:
            raise ValueError("SENTRY_DSN must be set when SENTRY_ENABLE is true")

        return self


class CORSSettings(BaseSettings):
    CORS_ORIGINS: list[str] = Field(default_factory=list)
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_METHODS: list[str] = Field(
        default_factory=lambda: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    CORS_HEADERS: list[str] = Field(
        default_factory=lambda: [
            "Accept",
            "Authorization",
            "Content-Type",
            "X-Requested-With",
            "X-Request-ID",
            "X-Correlation-ID",
        ],
    )
    CORS_EXPOSE_HEADERS: list[str] = Field(default_factory=lambda: ["X-Request-ID", "X-Correlation-ID"])
    CORS_MAX_AGE: int = Field(default=600, ge=0)

    @model_validator(mode="after")
    def validate_cors_settings(self) -> Self:
        self.CORS_ORIGINS = _normalize_string_list(setting_name="CORS_ORIGINS", values=self.CORS_ORIGINS)
        self.CORS_METHODS = _normalize_string_list(setting_name="CORS_METHODS", values=self.CORS_METHODS)
        self.CORS_HEADERS = _normalize_string_list(setting_name="CORS_HEADERS", values=self.CORS_HEADERS)
        self.CORS_EXPOSE_HEADERS = _normalize_string_list(
            setting_name="CORS_EXPOSE_HEADERS",
            values=self.CORS_EXPOSE_HEADERS,
        )

        if self.CORS_ALLOW_CREDENTIALS:
            if "*" in self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS cannot contain '*' when CORS_ALLOW_CREDENTIALS is true")
            if "*" in self.CORS_METHODS:
                raise ValueError("CORS_METHODS cannot contain '*' when CORS_ALLOW_CREDENTIALS is true")
            if "*" in self.CORS_HEADERS:
                raise ValueError("CORS_HEADERS cannot contain '*' when CORS_ALLOW_CREDENTIALS is true")

        return self


class FrameOptions(str, Enum):
    DENY = "DENY"
    SAMEORIGIN = "SAMEORIGIN"


class ReferrerPolicy(str, Enum):
    NO_REFERRER = "no-referrer"
    NO_REFERRER_WHEN_DOWNGRADE = "no-referrer-when-downgrade"
    ORIGIN = "origin"
    ORIGIN_WHEN_CROSS_ORIGIN = "origin-when-cross-origin"
    SAME_ORIGIN = "same-origin"
    STRICT_ORIGIN = "strict-origin"
    STRICT_ORIGIN_WHEN_CROSS_ORIGIN = "strict-origin-when-cross-origin"
    UNSAFE_URL = "unsafe-url"


class CrossOriginOpenerPolicy(str, Enum):
    UNSAFE_NONE = "unsafe-none"
    SAME_ORIGIN = "same-origin"
    SAME_ORIGIN_ALLOW_POPUPS = "same-origin-allow-popups"


class CrossOriginResourcePolicy(str, Enum):
    SAME_ORIGIN = "same-origin"
    SAME_SITE = "same-site"
    CROSS_ORIGIN = "cross-origin"


class CookieSameSite(str, Enum):
    LAX = "lax"
    STRICT = "strict"
    NONE = "none"


class SecurityHeadersSettings(BaseSettings):
    SECURITY_HEADERS_ENABLED: bool = True
    SECURITY_HEADERS_FRAME_OPTIONS: FrameOptions | None = FrameOptions.DENY
    SECURITY_HEADERS_CONTENT_TYPE_OPTIONS: bool = True
    SECURITY_HEADERS_REFERRER_POLICY: ReferrerPolicy | None = ReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN
    SECURITY_HEADERS_CONTENT_SECURITY_POLICY: str | None = None
    SECURITY_HEADERS_PERMISSIONS_POLICY: str | None = None
    SECURITY_HEADERS_CROSS_ORIGIN_OPENER_POLICY: CrossOriginOpenerPolicy | None = CrossOriginOpenerPolicy.SAME_ORIGIN
    SECURITY_HEADERS_CROSS_ORIGIN_RESOURCE_POLICY: CrossOriginResourcePolicy | None = (
        CrossOriginResourcePolicy.SAME_ORIGIN
    )
    SECURITY_HEADERS_HSTS_ENABLED: bool = False
    SECURITY_HEADERS_HSTS_MAX_AGE_SECONDS: int = Field(default=31_536_000, ge=0)
    SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS: bool = True
    SECURITY_HEADERS_HSTS_PRELOAD: bool = False

    @model_validator(mode="after")
    def validate_security_headers_settings(self) -> Self:
        for setting_name in (
            "SECURITY_HEADERS_CONTENT_SECURITY_POLICY",
            "SECURITY_HEADERS_PERMISSIONS_POLICY",
        ):
            value = getattr(self, setting_name)
            if value is None:
                continue

            stripped = value.strip()
            if not stripped:
                raise ValueError(f"{setting_name} must not be empty when provided")
            setattr(self, setting_name, stripped)

        if self.SECURITY_HEADERS_HSTS_PRELOAD and not self.SECURITY_HEADERS_HSTS_ENABLED:
            raise ValueError("SECURITY_HEADERS_HSTS_ENABLED must be true when SECURITY_HEADERS_HSTS_PRELOAD is enabled")

        if self.SECURITY_HEADERS_HSTS_PRELOAD and not self.SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS:
            raise ValueError(
                "SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS must be true when SECURITY_HEADERS_HSTS_PRELOAD is enabled"
            )

        return self


class RefreshTokenCookieSettings(BaseSettings):
    REFRESH_TOKEN_COOKIE_NAME: str = "refresh_token"
    REFRESH_TOKEN_COOKIE_PATH: str = "/"
    REFRESH_TOKEN_COOKIE_DOMAIN: str | None = None
    REFRESH_TOKEN_COOKIE_SECURE: bool = True
    REFRESH_TOKEN_COOKIE_HTTPONLY: bool = True
    REFRESH_TOKEN_COOKIE_SAMESITE: CookieSameSite = CookieSameSite.LAX

    @model_validator(mode="after")
    def validate_refresh_token_cookie_settings(self) -> Self:
        self.REFRESH_TOKEN_COOKIE_NAME = self.REFRESH_TOKEN_COOKIE_NAME.strip()
        if not self.REFRESH_TOKEN_COOKIE_NAME:
            raise ValueError("REFRESH_TOKEN_COOKIE_NAME must not be empty")

        self.REFRESH_TOKEN_COOKIE_PATH = self.REFRESH_TOKEN_COOKIE_PATH.strip()
        if not self.REFRESH_TOKEN_COOKIE_PATH:
            raise ValueError("REFRESH_TOKEN_COOKIE_PATH must not be empty")
        if not self.REFRESH_TOKEN_COOKIE_PATH.startswith("/"):
            raise ValueError("REFRESH_TOKEN_COOKIE_PATH must start with '/'")

        if self.REFRESH_TOKEN_COOKIE_DOMAIN is not None:
            self.REFRESH_TOKEN_COOKIE_DOMAIN = self.REFRESH_TOKEN_COOKIE_DOMAIN.strip()
            if not self.REFRESH_TOKEN_COOKIE_DOMAIN:
                raise ValueError("REFRESH_TOKEN_COOKIE_DOMAIN must not be empty when provided")

        if self.REFRESH_TOKEN_COOKIE_SAMESITE is CookieSameSite.NONE and not self.REFRESH_TOKEN_COOKIE_SECURE:
            raise ValueError(
                "REFRESH_TOKEN_COOKIE_SECURE must be true when REFRESH_TOKEN_COOKIE_SAMESITE is 'none'"
            )

        return self


class TrustedHostSettings(BaseSettings):
    TRUSTED_HOSTS: list[str] = Field(default_factory=list)
    TRUSTED_HOSTS_WWW_REDIRECT: bool = True

    @model_validator(mode="after")
    def validate_trusted_host_settings(self) -> Self:
        self.TRUSTED_HOSTS = _normalize_string_list(setting_name="TRUSTED_HOSTS", values=self.TRUSTED_HOSTS)
        _validate_allowed_host_patterns(setting_name="TRUSTED_HOSTS", values=self.TRUSTED_HOSTS)

        return self


class ProxyHeadersSettings(BaseSettings):
    PROXY_HEADERS_ENABLED: bool = False
    PROXY_HEADERS_TRUSTED_PROXIES: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_proxy_headers_settings(self) -> Self:
        self.PROXY_HEADERS_TRUSTED_PROXIES = _normalize_string_list(
            setting_name="PROXY_HEADERS_TRUSTED_PROXIES",
            values=self.PROXY_HEADERS_TRUSTED_PROXIES,
        )

        if self.PROXY_HEADERS_ENABLED and not self.PROXY_HEADERS_TRUSTED_PROXIES:
            raise ValueError("PROXY_HEADERS_TRUSTED_PROXIES must not be empty when PROXY_HEADERS_ENABLED is true")

        return self


class Settings(
    AppSettings,
    SQLiteSettings,
    PostgresSettings,
    CryptSettings,
    FirstUserSettings,
    TestSettings,
    RedisCacheSettings,
    ClientSideCacheSettings,
    FeatureFlagsSettings,
    RedisQueueSettings,
    WorkerRuntimeSettings,
    WebhookRuntimeSettings,
    RedisRateLimiterSettings,
    DefaultRateLimitSettings,
    CRUDAdminSettings,
    EnvironmentSettings,
    MetricsSettings,
    TracingSettings,
    SentrySettings,
    CORSSettings,
    SecurityHeadersSettings,
    RefreshTokenCookieSettings,
    TrustedHostSettings,
    ProxyHeadersSettings,
    LogVerbositySettings,
    FileLoggerSettings,
    ConsoleLoggerSettings,
):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    def _validate_expected_environment(self, expected: EnvironmentOption) -> None:
        if self.ENVIRONMENT != expected:
            raise ValueError(f"{type(self).__name__} requires ENVIRONMENT={expected.value}")

    def _collect_secure_environment_errors(self) -> list[str]:
        validation_errors: list[str] = []

        secret_key = self.SECRET_KEY.get_secret_value()
        if len(secret_key) < 32 or _normalize_setting_value(secret_key) in PRODUCTION_UNSAFE_SECRET_VALUES:
            validation_errors.append(
                "SECRET_KEY must be replaced with a unique secret that is at least 32 characters long"
            )

        database_password = self._database_password()
        if not database_password or _normalize_setting_value(database_password) in PRODUCTION_UNSAFE_PASSWORD_VALUES:
            validation_errors.append("Database password must be replaced with a non-placeholder password")

        if self.CRUD_ADMIN_ENABLED and (
            _normalize_setting_value(self.ADMIN_PASSWORD) in PRODUCTION_UNSAFE_PASSWORD_VALUES
        ):
            validation_errors.append("ADMIN_PASSWORD must be replaced with a non-placeholder password")

        if "*" in {origin.strip() for origin in self.CORS_ORIGINS}:
            validation_errors.append("CORS_ORIGINS cannot contain '*' outside local development")

        if not self.REFRESH_TOKEN_COOKIE_SECURE:
            validation_errors.append("REFRESH_TOKEN_COOKIE_SECURE must be true outside local development")

        if self.CRUD_ADMIN_ENABLED and not self.SESSION_SECURE_COOKIES:
            validation_errors.append(
                "SESSION_SECURE_COOKIES must be true when CRUD admin is enabled outside local development"
            )

        if "*" in {host.strip() for host in self.TRUSTED_HOSTS}:
            validation_errors.append("TRUSTED_HOSTS cannot contain '*' outside local development")

        if self.PROXY_HEADERS_ENABLED and "*" in {
            proxy.strip() for proxy in self.PROXY_HEADERS_TRUSTED_PROXIES
        }:
            validation_errors.append("PROXY_HEADERS_TRUSTED_PROXIES cannot contain '*' outside local development")

        return validation_errors

    def _validate_secure_environment(self, *, profile_name: str) -> None:
        validation_errors = self._collect_secure_environment_errors()

        if validation_errors:
            joined_errors = "; ".join(validation_errors)
            raise ValueError(f"Unsafe {profile_name} configuration: {joined_errors}")

    @model_validator(mode="after")
    def validate_generic_environment_safety(self) -> Self:
        if type(self) is not Settings:
            return self

        if self.ENVIRONMENT in {EnvironmentOption.STAGING, EnvironmentOption.PRODUCTION}:
            self._validate_secure_environment(profile_name=self.ENVIRONMENT.value)

        return self


class LocalSettings(Settings):
    ENVIRONMENT: EnvironmentOption = EnvironmentOption.LOCAL
    SENTRY_ENVIRONMENT: str = "local"
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: list(LOCAL_DEVELOPMENT_CORS_ORIGINS))
    REFRESH_TOKEN_COOKIE_SECURE: bool = False
    SESSION_SECURE_COOKIES: bool = False

    @model_validator(mode="after")
    def validate_local_profile(self) -> Self:
        self._validate_expected_environment(EnvironmentOption.LOCAL)
        return self


class StagingSettings(Settings):
    ENVIRONMENT: EnvironmentOption = EnvironmentOption.STAGING
    SENTRY_ENVIRONMENT: str = "staging"

    @model_validator(mode="after")
    def validate_staging_profile(self) -> Self:
        self._validate_expected_environment(EnvironmentOption.STAGING)
        self._validate_secure_environment(profile_name="staging")
        return self


class ProductionSettings(Settings):
    ENVIRONMENT: EnvironmentOption = EnvironmentOption.PRODUCTION
    SENTRY_ENVIRONMENT: str = "production"

    @model_validator(mode="after")
    def validate_production_profile(self) -> Self:
        self._validate_expected_environment(EnvironmentOption.PRODUCTION)
        self._validate_secure_environment(profile_name="production")
        return self


SettingsProfile: TypeAlias = LocalSettings | StagingSettings | ProductionSettings


def get_settings_class(environment: EnvironmentOption | str) -> type[Settings]:
    environment_option = environment if isinstance(environment, EnvironmentOption) else EnvironmentOption(environment)

    return {
        EnvironmentOption.LOCAL: LocalSettings,
        EnvironmentOption.STAGING: StagingSettings,
        EnvironmentOption.PRODUCTION: ProductionSettings,
    }[environment_option]


def load_settings(**overrides: Any) -> SettingsProfile:
    bootstrap_settings = Settings(**cast(Any, overrides))
    settings_class = get_settings_class(bootstrap_settings.ENVIRONMENT)

    return cast(SettingsProfile, settings_class(**cast(Any, overrides)))


settings = load_settings()
