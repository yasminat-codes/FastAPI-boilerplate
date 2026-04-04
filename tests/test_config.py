import ssl

import pytest
from pydantic import ValidationError

from src.app.platform.config import (
    CookieSameSite,
    CrossOriginOpenerPolicy,
    DatabaseSSLMode,
    FrameOptions,
    LocalSettings,
    LogLevel,
    ProductionSettings,
    RedisSSLCertRequirements,
    ReferrerPolicy,
    Settings,
    StagingSettings,
    TracingExporter,
    get_settings_class,
    load_settings,
)
from src.app.platform.database import build_database_connect_args, build_database_engine_kwargs


def test_local_settings_allow_template_defaults() -> None:
    settings = load_settings(_env_file=None, ENVIRONMENT="local")

    assert isinstance(settings, LocalSettings)
    assert settings.ENVIRONMENT.value == "local"
    assert settings.SENTRY_ENVIRONMENT == "local"
    assert "http://localhost:3000" in settings.CORS_ORIGINS
    assert settings.CORS_ALLOW_CREDENTIALS is True
    assert settings.REFRESH_TOKEN_COOKIE_SECURE is False
    assert settings.SESSION_SECURE_COOKIES is False


def test_get_settings_class_uses_environment_profiles() -> None:
    assert get_settings_class("local") is LocalSettings
    assert get_settings_class("staging") is StagingSettings
    assert get_settings_class("production") is ProductionSettings


def test_database_url_prefers_direct_setting() -> None:
    settings = load_settings(
        _env_file=None,
        DATABASE_URL="postgresql://template-user:template-password@db.example.com:5433/template_db",
    )

    assert settings.DATABASE_URL == "postgresql+asyncpg://template-user:template-password@db.example.com:5433/template_db"
    assert settings.DATABASE_SYNC_URL == "postgresql://template-user:template-password@db.example.com:5433/template_db"
    assert settings.POSTGRES_URI == "template-user:template-password@db.example.com:5433/template_db"


def test_database_url_falls_back_to_composed_postgres_settings() -> None:
    settings = load_settings(
        _env_file=None,
        POSTGRES_USER="template-user",
        POSTGRES_PASSWORD="template-password",
        POSTGRES_SERVER="db.example.com",
        POSTGRES_PORT=5433,
        POSTGRES_DB="template_db",
    )

    assert settings.DATABASE_URL == "postgresql+asyncpg://template-user:template-password@db.example.com:5433/template_db"
    assert settings.DATABASE_SYNC_URL == "postgresql://template-user:template-password@db.example.com:5433/template_db"


def test_database_url_rejects_non_postgres_backends() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL must use a PostgreSQL URL"):
        load_settings(_env_file=None, DATABASE_URL="sqlite:///tmp/template.db")


def test_database_engine_kwargs_include_pool_and_timeout_settings() -> None:
    settings = load_settings(
        _env_file=None,
        DATABASE_POOL_SIZE=15,
        DATABASE_MAX_OVERFLOW=5,
        DATABASE_POOL_PRE_PING=False,
        DATABASE_POOL_USE_LIFO=False,
        DATABASE_POOL_RECYCLE=900,
        DATABASE_POOL_TIMEOUT=12,
        DATABASE_CONNECT_TIMEOUT=7.5,
        DATABASE_COMMAND_TIMEOUT=45.0,
        DATABASE_STATEMENT_TIMEOUT_MS=30000,
        DATABASE_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS=15000,
    )

    engine_kwargs = build_database_engine_kwargs(settings)

    assert engine_kwargs["pool_size"] == 15
    assert engine_kwargs["max_overflow"] == 5
    assert engine_kwargs["pool_pre_ping"] is False
    assert engine_kwargs["pool_use_lifo"] is False
    assert engine_kwargs["pool_recycle"] == 900
    assert engine_kwargs["pool_timeout"] == 12
    assert engine_kwargs["connect_args"] == {
        "timeout": 7.5,
        "command_timeout": 45.0,
        "ssl": False,
        "server_settings": {
            "statement_timeout": "30000",
            "idle_in_transaction_session_timeout": "15000",
        },
    }


def test_database_startup_retry_settings_reject_invalid_delay_order() -> None:
    with pytest.raises(
        ValidationError,
        match="DATABASE_STARTUP_RETRY_MAX_DELAY must be greater than or equal to DATABASE_STARTUP_RETRY_BASE_DELAY",
    ):
        load_settings(
            _env_file=None,
            DATABASE_STARTUP_RETRY_ATTEMPTS=2,
            DATABASE_STARTUP_RETRY_BASE_DELAY=2.0,
            DATABASE_STARTUP_RETRY_MAX_DELAY=1.0,
        )


def test_database_connect_args_build_ssl_context_for_require_mode() -> None:
    settings = load_settings(
        _env_file=None,
        DATABASE_SSL_MODE=DatabaseSSLMode.REQUIRE.value,
    )

    connect_args = build_database_connect_args(settings)

    assert isinstance(connect_args["ssl"], ssl.SSLContext)
    assert connect_args["ssl"].check_hostname is False
    assert connect_args["ssl"].verify_mode == ssl.CERT_NONE


def test_database_ssl_verify_modes_require_ca_file() -> None:
    with pytest.raises(ValidationError, match="DATABASE_SSL_CA_FILE is required"):
        load_settings(
            _env_file=None,
            DATABASE_SSL_MODE=DatabaseSSLMode.VERIFY_FULL.value,
        )


def test_database_ssl_cert_and_key_must_be_provided_together() -> None:
    with pytest.raises(
        ValidationError,
        match="DATABASE_SSL_CERT_FILE and DATABASE_SSL_KEY_FILE must be provided together",
    ):
        load_settings(
            _env_file=None,
            DATABASE_SSL_MODE=DatabaseSSLMode.REQUIRE.value,
            DATABASE_SSL_CERT_FILE="/tmp/client.crt",
        )


def test_redis_urls_include_credentials_database_and_tls_scheme() -> None:
    settings = load_settings(
        _env_file=None,
        REDIS_CACHE_HOST="cache.example.com",
        REDIS_CACHE_PORT=6380,
        REDIS_CACHE_DB=2,
        REDIS_CACHE_USERNAME="cache-user",
        REDIS_CACHE_PASSWORD="cache-password",
        REDIS_CACHE_SSL=True,
        REDIS_QUEUE_HOST="queue.example.com",
        REDIS_QUEUE_PORT=6381,
        REDIS_QUEUE_DB=4,
        REDIS_QUEUE_PASSWORD="queue-password",
        REDIS_RATE_LIMIT_HOST="limit.example.com",
        REDIS_RATE_LIMIT_PORT=6382,
        REDIS_RATE_LIMIT_DB=6,
        REDIS_RATE_LIMIT_SSL=True,
    )

    assert settings.REDIS_CACHE_URL == "rediss://cache-user:cache-password@cache.example.com:6380/2"
    assert settings.REDIS_QUEUE_URL == "redis://:queue-password@queue.example.com:6381/4"
    assert settings.REDIS_RATE_LIMIT_URL == "rediss://limit.example.com:6382/6"


def test_redis_tls_settings_require_ssl_to_be_enabled() -> None:
    with pytest.raises(ValidationError, match="REDIS_CACHE_SSL must be enabled"):
        load_settings(
            _env_file=None,
            REDIS_CACHE_SSL_CA_CERTS="/tmp/ca.pem",
        )


def test_redis_retry_backoff_validation_rejects_invalid_delay_order() -> None:
    with pytest.raises(ValidationError, match="REDIS_RATE_LIMIT_RETRY_MAX_DELAY"):
        load_settings(
            _env_file=None,
            REDIS_RATE_LIMIT_RETRY_ATTEMPTS=2,
            REDIS_RATE_LIMIT_RETRY_BASE_DELAY=0.5,
            REDIS_RATE_LIMIT_RETRY_MAX_DELAY=0.1,
        )


def test_redis_queue_tls_cert_and_key_must_be_provided_together() -> None:
    with pytest.raises(
        ValidationError,
        match="REDIS_QUEUE_SSL_CERTFILE and REDIS_QUEUE_SSL_KEYFILE must be provided together",
    ):
        load_settings(
            _env_file=None,
            REDIS_QUEUE_SSL=True,
            REDIS_QUEUE_SSL_CERTFILE="/tmp/client.crt",
            REDIS_QUEUE_SSL_CERT_REQS=RedisSSLCertRequirements.REQUIRED.value,
        )


def test_worker_runtime_settings_cover_queue_retry_and_retention() -> None:
    settings = load_settings(
        _env_file=None,
        WORKER_QUEUE_NAME="template:workers:default",
        WORKER_MAX_JOBS=24,
        WORKER_JOB_MAX_TRIES=6,
        WORKER_JOB_RETRY_DELAY_SECONDS=12.5,
        WORKER_KEEP_RESULT_SECONDS=7200,
        WORKER_JOB_EXPIRES_EXTRA_MS=120000,
    )

    assert settings.WORKER_QUEUE_NAME == "template:workers:default"
    assert settings.WORKER_MAX_JOBS == 24
    assert settings.WORKER_JOB_MAX_TRIES == 6
    assert settings.WORKER_JOB_RETRY_DELAY_SECONDS == 12.5
    assert settings.WORKER_KEEP_RESULT_SECONDS == 7200
    assert settings.WORKER_KEEP_RESULT_FOREVER is False
    assert settings.WORKER_JOB_EXPIRES_EXTRA_MS == 120000


def test_worker_queue_name_must_not_be_blank() -> None:
    with pytest.raises(ValidationError, match="WORKER_QUEUE_NAME must not be empty"):
        load_settings(
            _env_file=None,
            WORKER_QUEUE_NAME="   ",
        )


def test_webhook_runtime_settings_cover_verification_replay_and_retention() -> None:
    settings = load_settings(
        _env_file=None,
        WEBHOOK_SIGNATURE_VERIFICATION_ENABLED=True,
        WEBHOOK_SIGNATURE_MAX_AGE_SECONDS=600,
        WEBHOOK_REPLAY_PROTECTION_ENABLED=True,
        WEBHOOK_REPLAY_WINDOW_SECONDS=900,
        WEBHOOK_STORE_RAW_PAYLOADS=True,
        WEBHOOK_PAYLOAD_RETENTION_DAYS=14,
    )

    assert settings.WEBHOOK_SIGNATURE_VERIFICATION_ENABLED is True
    assert settings.WEBHOOK_SIGNATURE_MAX_AGE_SECONDS == 600
    assert settings.WEBHOOK_REPLAY_PROTECTION_ENABLED is True
    assert settings.WEBHOOK_REPLAY_WINDOW_SECONDS == 900
    assert settings.WEBHOOK_STORE_RAW_PAYLOADS is True
    assert settings.WEBHOOK_PAYLOAD_RETENTION_DAYS == 14


def test_webhook_replay_window_must_cover_signature_age_when_enabled() -> None:
    with pytest.raises(ValidationError, match="WEBHOOK_REPLAY_WINDOW_SECONDS must be greater than or equal to"):
        load_settings(
            _env_file=None,
            WEBHOOK_SIGNATURE_VERIFICATION_ENABLED=True,
            WEBHOOK_SIGNATURE_MAX_AGE_SECONDS=600,
            WEBHOOK_REPLAY_PROTECTION_ENABLED=True,
            WEBHOOK_REPLAY_WINDOW_SECONDS=300,
        )


def test_webhook_payload_retention_requires_positive_days_when_storage_is_enabled() -> None:
    with pytest.raises(ValidationError, match="WEBHOOK_PAYLOAD_RETENTION_DAYS must be at least 1"):
        load_settings(
            _env_file=None,
            WEBHOOK_STORE_RAW_PAYLOADS=True,
            WEBHOOK_PAYLOAD_RETENTION_DAYS=0,
        )


def test_webhook_payload_retention_can_be_disabled_when_raw_storage_is_off() -> None:
    settings = load_settings(
        _env_file=None,
        WEBHOOK_STORE_RAW_PAYLOADS=False,
        WEBHOOK_PAYLOAD_RETENTION_DAYS=0,
    )

    assert settings.WEBHOOK_STORE_RAW_PAYLOADS is False
    assert settings.WEBHOOK_PAYLOAD_RETENTION_DAYS == 0


def test_cors_settings_use_explicit_allowlists_and_runtime_controls() -> None:
    settings = load_settings(
        _env_file=None,
        CORS_ORIGINS=["https://app.example.com", "https://admin.example.com"],
        CORS_ALLOW_CREDENTIALS=True,
        CORS_METHODS=["GET", "POST"],
        CORS_HEADERS=["Authorization", "Content-Type", "X-Request-ID"],
        CORS_EXPOSE_HEADERS=["X-Request-ID"],
        CORS_MAX_AGE=900,
    )

    assert settings.CORS_ORIGINS == ["https://app.example.com", "https://admin.example.com"]
    assert settings.CORS_ALLOW_CREDENTIALS is True
    assert settings.CORS_METHODS == ["GET", "POST"]
    assert settings.CORS_HEADERS == ["Authorization", "Content-Type", "X-Request-ID"]
    assert settings.CORS_EXPOSE_HEADERS == ["X-Request-ID"]
    assert settings.CORS_MAX_AGE == 900


def test_cors_settings_expose_request_context_headers_by_default() -> None:
    settings = load_settings(_env_file=None)

    assert "X-Request-ID" in settings.CORS_HEADERS
    assert "X-Correlation-ID" in settings.CORS_HEADERS
    assert settings.CORS_EXPOSE_HEADERS == ["X-Request-ID", "X-Correlation-ID"]


def test_cors_credentials_disallow_wildcard_origins() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS cannot contain '\\*' when CORS_ALLOW_CREDENTIALS is true"):
        load_settings(
            _env_file=None,
            CORS_ORIGINS=["*"],
            CORS_ALLOW_CREDENTIALS=True,
        )


def test_cors_settings_reject_blank_values() -> None:
    with pytest.raises(ValidationError, match="CORS_HEADERS must not contain blank values"):
        load_settings(
            _env_file=None,
            CORS_ORIGINS=["https://app.example.com"],
            CORS_HEADERS=["Authorization", "   "],
        )


def test_trusted_host_settings_normalize_explicit_allowlists() -> None:
    settings = load_settings(
        _env_file=None,
        TRUSTED_HOSTS=[" app.example.com ", "*.admin.example.com"],
        TRUSTED_HOSTS_WWW_REDIRECT=False,
    )

    assert settings.TRUSTED_HOSTS == ["app.example.com", "*.admin.example.com"]
    assert settings.TRUSTED_HOSTS_WWW_REDIRECT is False


def test_trusted_host_settings_reject_invalid_wildcard_patterns() -> None:
    with pytest.raises(ValidationError, match="TRUSTED_HOSTS wildcard entries must be"):
        load_settings(
            _env_file=None,
            TRUSTED_HOSTS=["api.*.example.com"],
        )


def test_proxy_header_settings_require_explicit_trusted_proxies_when_enabled() -> None:
    with pytest.raises(
        ValidationError,
        match="PROXY_HEADERS_TRUSTED_PROXIES must not be empty when PROXY_HEADERS_ENABLED is true",
    ):
        load_settings(
            _env_file=None,
            PROXY_HEADERS_ENABLED=True,
        )


def test_proxy_header_settings_normalize_trusted_proxy_list() -> None:
    settings = load_settings(
        _env_file=None,
        PROXY_HEADERS_ENABLED=True,
        PROXY_HEADERS_TRUSTED_PROXIES=[" 127.0.0.1 ", "10.0.0.0/8"],
    )

    assert settings.PROXY_HEADERS_ENABLED is True
    assert settings.PROXY_HEADERS_TRUSTED_PROXIES == ["127.0.0.1", "10.0.0.0/8"]


def test_request_body_limit_settings_normalize_exempt_prefixes() -> None:
    settings = load_settings(
        _env_file=None,
        REQUEST_BODY_LIMIT_EXEMPT_PATH_PREFIXES=[" /health ", "/api/v1/webhooks"],
    )

    assert settings.REQUEST_BODY_LIMIT_EXEMPT_PATH_PREFIXES == ["/health", "/api/v1/webhooks"]


def test_request_timeout_settings_reject_invalid_exempt_prefixes() -> None:
    with pytest.raises(ValidationError, match="REQUEST_TIMEOUT_EXEMPT_PATH_PREFIXES entries must start with '/'"):
        load_settings(
            _env_file=None,
            REQUEST_TIMEOUT_EXEMPT_PATH_PREFIXES=["api/v1/slow"],
        )


def test_log_redaction_settings_normalize_field_lists_and_replacement() -> None:
    settings = load_settings(
        _env_file=None,
        LOG_REDACTION_EXACT_FIELDS=[" Authorization ", "X-Api-Key"],
        LOG_REDACTION_SUBSTRING_FIELDS=[" Token ", "SeCreT"],
        LOG_REDACTION_REPLACEMENT=" [FILTERED] ",
    )

    assert settings.LOG_REDACTION_EXACT_FIELDS == ["authorization", "x-api-key"]
    assert settings.LOG_REDACTION_SUBSTRING_FIELDS == ["token", "secret"]
    assert settings.LOG_REDACTION_REPLACEMENT == "[FILTERED]"


def test_security_headers_settings_cover_common_hardening_headers() -> None:
    settings = load_settings(
        _env_file=None,
        SECURITY_HEADERS_FRAME_OPTIONS=FrameOptions.SAMEORIGIN.value,
        SECURITY_HEADERS_REFERRER_POLICY=ReferrerPolicy.SAME_ORIGIN.value,
        SECURITY_HEADERS_CONTENT_SECURITY_POLICY="default-src 'self'",
        SECURITY_HEADERS_PERMISSIONS_POLICY="geolocation=()",
        SECURITY_HEADERS_CROSS_ORIGIN_OPENER_POLICY=CrossOriginOpenerPolicy.SAME_ORIGIN_ALLOW_POPUPS.value,
        SECURITY_HEADERS_HSTS_ENABLED=True,
        SECURITY_HEADERS_HSTS_MAX_AGE_SECONDS=600,
        SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS=False,
    )

    assert settings.SECURITY_HEADERS_ENABLED is True
    assert settings.SECURITY_HEADERS_FRAME_OPTIONS is FrameOptions.SAMEORIGIN
    assert settings.SECURITY_HEADERS_REFERRER_POLICY is ReferrerPolicy.SAME_ORIGIN
    assert settings.SECURITY_HEADERS_CONTENT_SECURITY_POLICY == "default-src 'self'"
    assert settings.SECURITY_HEADERS_PERMISSIONS_POLICY == "geolocation=()"
    assert settings.SECURITY_HEADERS_CROSS_ORIGIN_OPENER_POLICY is CrossOriginOpenerPolicy.SAME_ORIGIN_ALLOW_POPUPS
    assert settings.SECURITY_HEADERS_HSTS_ENABLED is True
    assert settings.SECURITY_HEADERS_HSTS_MAX_AGE_SECONDS == 600
    assert settings.SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS is False


def test_security_headers_reject_blank_custom_policy_strings() -> None:
    with pytest.raises(ValidationError, match="SECURITY_HEADERS_CONTENT_SECURITY_POLICY must not be empty"):
        load_settings(
            _env_file=None,
            SECURITY_HEADERS_CONTENT_SECURITY_POLICY="   ",
        )


def test_security_headers_hsts_preload_requires_hsts_enabled() -> None:
    with pytest.raises(ValidationError, match="SECURITY_HEADERS_HSTS_ENABLED must be true"):
        load_settings(
            _env_file=None,
            SECURITY_HEADERS_HSTS_PRELOAD=True,
        )


def test_refresh_token_cookie_settings_cover_runtime_behavior() -> None:
    settings = load_settings(
        _env_file=None,
        REFRESH_TOKEN_COOKIE_NAME="template_refresh",
        REFRESH_TOKEN_COOKIE_PATH="/auth",
        REFRESH_TOKEN_COOKIE_DOMAIN="auth.example.com",
        REFRESH_TOKEN_COOKIE_SECURE=True,
        REFRESH_TOKEN_COOKIE_HTTPONLY=False,
        REFRESH_TOKEN_COOKIE_SAMESITE=CookieSameSite.STRICT.value,
    )

    assert settings.REFRESH_TOKEN_COOKIE_NAME == "template_refresh"
    assert settings.REFRESH_TOKEN_COOKIE_PATH == "/auth"
    assert settings.REFRESH_TOKEN_COOKIE_DOMAIN == "auth.example.com"
    assert settings.REFRESH_TOKEN_COOKIE_SECURE is True
    assert settings.REFRESH_TOKEN_COOKIE_HTTPONLY is False
    assert settings.REFRESH_TOKEN_COOKIE_SAMESITE is CookieSameSite.STRICT


def test_refresh_token_cookie_settings_require_secure_for_samesite_none() -> None:
    with pytest.raises(
        ValidationError,
        match="REFRESH_TOKEN_COOKIE_SECURE must be true when REFRESH_TOKEN_COOKIE_SAMESITE is 'none'",
    ):
        load_settings(
            _env_file=None,
            REFRESH_TOKEN_COOKIE_SECURE=False,
            REFRESH_TOKEN_COOKIE_SAMESITE=CookieSameSite.NONE.value,
        )


def test_feature_flags_settings_cover_optional_template_modules() -> None:
    settings = load_settings(
        _env_file=None,
        FEATURE_ADMIN_ENABLED=False,
        FEATURE_CLIENT_CACHE_ENABLED=False,
        FEATURE_API_AUTH_ROUTES_ENABLED=False,
        FEATURE_API_USERS_ENABLED=False,
        FEATURE_API_POSTS_ENABLED=False,
        FEATURE_API_TIERS_ENABLED=False,
        FEATURE_API_RATE_LIMITS_ENABLED=False,
    )

    assert settings.FEATURE_ADMIN_ENABLED is False
    assert settings.FEATURE_CLIENT_CACHE_ENABLED is False
    assert settings.FEATURE_API_AUTH_ROUTES_ENABLED is False
    assert settings.FEATURE_API_USERS_ENABLED is False
    assert settings.FEATURE_API_POSTS_ENABLED is False
    assert settings.FEATURE_API_TIERS_ENABLED is False
    assert settings.FEATURE_API_RATE_LIMITS_ENABLED is False


def test_observability_settings_cover_sentry_metrics_tracing_and_log_verbosity() -> None:
    settings = load_settings(
        _env_file=None,
        SENTRY_ENABLE=True,
        SENTRY_DSN="https://public@example.ingest.sentry.io/1",
        SENTRY_RELEASE="template@1.2.3",
        SENTRY_DEBUG=True,
        SENTRY_ATTACH_STACKTRACE=False,
        SENTRY_SEND_DEFAULT_PII=True,
        SENTRY_MAX_BREADCRUMBS=75,
        SENTRY_TRACES_SAMPLE_RATE=0.25,
        SENTRY_PROFILES_SAMPLE_RATE=0.1,
        METRICS_ENABLED=True,
        METRICS_PATH="/internal/metrics",
        METRICS_NAMESPACE="template_api",
        METRICS_INCLUDE_REQUEST_PATH_LABELS=True,
        TRACING_ENABLED=True,
        TRACING_EXPORTER=TracingExporter.CONSOLE.value,
        TRACING_SAMPLE_RATE=0.5,
        TRACING_SERVICE_NAME="template-api",
        TRACING_PROPAGATE_CORRELATION_IDS=False,
        LOG_LEVEL=LogLevel.DEBUG.value,
        UVICORN_LOG_LEVEL=LogLevel.WARNING.value,
        FILE_LOG_LEVEL=LogLevel.ERROR.value,
        CONSOLE_LOG_LEVEL=LogLevel.CRITICAL.value,
    )

    assert settings.SENTRY_ENABLE is True
    assert settings.SENTRY_RELEASE == "template@1.2.3"
    assert settings.SENTRY_DEBUG is True
    assert settings.SENTRY_ATTACH_STACKTRACE is False
    assert settings.SENTRY_SEND_DEFAULT_PII is True
    assert settings.SENTRY_MAX_BREADCRUMBS == 75
    assert settings.SENTRY_TRACES_SAMPLE_RATE == 0.25
    assert settings.SENTRY_PROFILES_SAMPLE_RATE == 0.1
    assert settings.METRICS_ENABLED is True
    assert settings.METRICS_PATH == "/internal/metrics"
    assert settings.METRICS_NAMESPACE == "template_api"
    assert settings.METRICS_INCLUDE_REQUEST_PATH_LABELS is True
    assert settings.TRACING_ENABLED is True
    assert settings.TRACING_EXPORTER is TracingExporter.CONSOLE
    assert settings.TRACING_SAMPLE_RATE == 0.5
    assert settings.TRACING_SERVICE_NAME == "template-api"
    assert settings.TRACING_PROPAGATE_CORRELATION_IDS is False
    assert settings.LOG_LEVEL is LogLevel.DEBUG
    assert settings.UVICORN_LOG_LEVEL is LogLevel.WARNING
    assert settings.FILE_LOG_LEVEL is LogLevel.ERROR
    assert settings.CONSOLE_LOG_LEVEL is LogLevel.CRITICAL


def test_sentry_dsn_is_required_when_sentry_is_enabled() -> None:
    with pytest.raises(ValidationError, match="SENTRY_DSN must be set when SENTRY_ENABLE is true"):
        load_settings(
            _env_file=None,
            SENTRY_ENABLE=True,
        )


def test_metrics_path_must_start_with_slash() -> None:
    with pytest.raises(ValidationError, match="METRICS_PATH must start with '/'"):
        load_settings(
            _env_file=None,
            METRICS_PATH="metrics",
        )


def test_tracing_service_name_must_not_be_blank_when_provided() -> None:
    with pytest.raises(ValidationError, match="TRACING_SERVICE_NAME must not be empty"):
        load_settings(
            _env_file=None,
            TRACING_SERVICE_NAME="   ",
        )


def test_staging_settings_reject_unsafe_defaults() -> None:
    with pytest.raises(ValidationError, match="Unsafe staging configuration"):
        load_settings(
            _env_file=None,
            ENVIRONMENT="staging",
            SECRET_KEY="secret-key",
            POSTGRES_PASSWORD="postgres",
            ADMIN_PASSWORD="!Ch4ng3Th1sP4ssW0rd!",
            CORS_ORIGINS=["*"],
            CORS_ALLOW_CREDENTIALS=False,
        )


def test_production_settings_reject_unsafe_defaults() -> None:
    with pytest.raises(ValidationError, match="Unsafe production configuration"):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            SECRET_KEY="secret-key",
            POSTGRES_PASSWORD="postgres",
            ADMIN_PASSWORD="!Ch4ng3Th1sP4ssW0rd!",
            CORS_ORIGINS=["*"],
            CORS_ALLOW_CREDENTIALS=False,
        )


def test_production_settings_reject_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS cannot contain '\\*' outside local development"):
        load_settings(
            _env_file=None,
            ENVIRONMENT="production",
            SECRET_KEY="a" * 64,
            POSTGRES_PASSWORD="database-password-123",
            ADMIN_PASSWORD="admin-password-123",
            CORS_ORIGINS=["*"],
            CORS_ALLOW_CREDENTIALS=False,
        )


def test_production_settings_reject_insecure_refresh_cookie_settings() -> None:
    with pytest.raises(ValidationError, match="REFRESH_TOKEN_COOKIE_SECURE must be true outside local development"):
        load_settings(
            _env_file=None,
            ENVIRONMENT="production",
            SECRET_KEY="a" * 64,
            POSTGRES_PASSWORD="database-password-123",
            ADMIN_PASSWORD="admin-password-123",
            REFRESH_TOKEN_COOKIE_SECURE=False,
            CORS_ORIGINS=["https://app.example.com"],
        )


def test_production_settings_reject_insecure_admin_session_cookies() -> None:
    with pytest.raises(
        ValidationError,
        match="SESSION_SECURE_COOKIES must be true when CRUD admin is enabled outside local development",
    ):
        load_settings(
            _env_file=None,
            ENVIRONMENT="production",
            SECRET_KEY="a" * 64,
            POSTGRES_PASSWORD="database-password-123",
            ADMIN_PASSWORD="admin-password-123",
            SESSION_SECURE_COOKIES=False,
            CORS_ORIGINS=["https://app.example.com"],
        )


def test_production_settings_reject_wildcard_trusted_hosts() -> None:
    with pytest.raises(ValidationError, match="TRUSTED_HOSTS cannot contain '\\*' outside local development"):
        load_settings(
            _env_file=None,
            ENVIRONMENT="production",
            SECRET_KEY="a" * 64,
            POSTGRES_PASSWORD="database-password-123",
            ADMIN_PASSWORD="admin-password-123",
            TRUSTED_HOSTS=["*"],
        )


def test_production_settings_reject_wildcard_trusted_proxies() -> None:
    with pytest.raises(
        ValidationError,
        match="PROXY_HEADERS_TRUSTED_PROXIES cannot contain '\\*' outside local development",
    ):
        load_settings(
            _env_file=None,
            ENVIRONMENT="production",
            SECRET_KEY="a" * 64,
            POSTGRES_PASSWORD="database-password-123",
            ADMIN_PASSWORD="admin-password-123",
            PROXY_HEADERS_ENABLED=True,
            PROXY_HEADERS_TRUSTED_PROXIES=["*"],
        )


def test_production_settings_accept_explicit_secure_values() -> None:
    settings = load_settings(
        _env_file=None,
        ENVIRONMENT="production",
        SECRET_KEY="a" * 64,
        POSTGRES_PASSWORD="database-password-123",
        ADMIN_PASSWORD="admin-password-123",
        CORS_ORIGINS=["https://app.example.com"],
    )

    assert isinstance(settings, ProductionSettings)
    assert settings.ENVIRONMENT.value == "production"
    assert settings.SENTRY_ENVIRONMENT == "production"


def test_production_settings_allow_fail_closed_cors_defaults() -> None:
    settings = load_settings(
        _env_file=None,
        ENVIRONMENT="production",
        SECRET_KEY="a" * 64,
        POSTGRES_PASSWORD="database-password-123",
        ADMIN_PASSWORD="admin-password-123",
    )

    assert isinstance(settings, ProductionSettings)
    assert settings.CORS_ORIGINS == []
    assert settings.CORS_METHODS == ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def test_production_settings_validate_direct_database_url_password() -> None:
    with pytest.raises(ValidationError, match="Unsafe production configuration"):
        load_settings(
            _env_file=None,
            ENVIRONMENT="production",
            SECRET_KEY="a" * 64,
            DATABASE_URL="postgresql://template-user:postgres@db.example.com:5432/template_db",
            ADMIN_PASSWORD="admin-password-123",
            CORS_ORIGINS=["https://app.example.com"],
        )
