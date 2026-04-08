"""Deterministic test settings for FastAPI template.

This module provides test-specific settings that are hardcoded and do not depend on
environment files or environment variables for their base values. This ensures tests
always run with the same known configuration regardless of what's on disk.

The TestSettingsProfile can be extended with environment variable overrides for CI
environments where database or Redis URLs differ from defaults.
"""

import os
from typing import Any

from pydantic import Field, SecretStr
from pydantic_settings import SettingsConfigDict

from src.app.core.config import EnvironmentOption, Settings


class TestSettingsProfile(Settings):
    """Deterministic settings for tests with hardcoded, safe defaults.

    This class inherits from Settings and overrides env_file to ensure no .env
    file is loaded. All settings have deterministic defaults suitable for testing.
    Database and Redis use test-specific database numbers to avoid conflicts.
    """

    model_config = SettingsConfigDict(
        env_file=None,  # Do NOT read from any .env file
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # App settings
    APP_NAME: str = "fastapi-template-test"

    # Crypto settings
    SECRET_KEY: SecretStr = SecretStr("test-secret-key-at-least-32-characters-long-for-tests")

    # Environment
    ENVIRONMENT: EnvironmentOption = EnvironmentOption.LOCAL

    # Database settings - use test-specific database name
    # Note: Use DATABASE_URL_INPUT because DATABASE_URL is a @computed_field in the parent class
    DATABASE_URL_INPUT: str | None = "postgresql://postgres:postgres@localhost:5432/test_fastapi_template"

    # Redis cache settings - use DB 1 to avoid conflicts with development (DB 0)
    REDIS_CACHE_HOST: str = "localhost"
    REDIS_CACHE_PORT: int = 6379
    REDIS_CACHE_DB: int = 1

    # Redis queue settings - use DB 2 to avoid conflicts
    REDIS_QUEUE_HOST: str = "localhost"
    REDIS_QUEUE_PORT: int = 6379
    REDIS_QUEUE_DB: int = 2

    # Redis rate limiter settings - use DB 3 to avoid conflicts
    REDIS_RATE_LIMITER_HOST: str = "localhost"
    REDIS_RATE_LIMITER_PORT: int = 6379
    REDIS_RATE_LIMITER_DB: int = 3

    # Observability - disabled for tests
    SENTRY_ENABLED: bool = False
    METRICS_ENABLED: bool = False
    TRACING_ENABLED: bool = False

    # Admin and features
    CRUD_ADMIN_ENABLED: bool = False

    # CORS - minimal for testing
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Security - relaxed for testing (not HTTPS)
    REFRESH_TOKEN_COOKIE_SECURE: bool = False
    SESSION_SECURE_COOKIES: bool = False

    @classmethod
    def allow_env_override(cls) -> "TestSettingsProfile":
        """Create a new instance with environment variable overrides allowed.

        This method checks for specific environment variables that override
        the defaults, enabling CI environments to use their own database
        and Redis configurations while still maintaining deterministic
        base values.

        Supported environment variable overrides:
        - TEST_DATABASE_URL: Override the database connection URL
        - TEST_REDIS_HOST: Override Redis host for all Redis services

        Returns:
            TestSettingsProfile: A new instance with overrides applied.
        """
        overrides: dict[str, Any] = {}

        # Allow CI to override database URL
        if db_url := os.getenv("TEST_DATABASE_URL"):
            overrides["DATABASE_URL_INPUT"] = db_url

        # Allow CI to override Redis host for all Redis services
        if redis_host := os.getenv("TEST_REDIS_HOST"):
            overrides["REDIS_CACHE_HOST"] = redis_host
            overrides["REDIS_QUEUE_HOST"] = redis_host
            overrides["REDIS_RATE_LIMITER_HOST"] = redis_host

        return cls(**overrides)


def get_test_settings() -> TestSettingsProfile:
    """Get deterministic test settings with optional CI overrides.

    This function returns a TestSettingsProfile instance that uses hardcoded
    defaults for all settings, with support for environment variable overrides
    when needed for CI environments.

    The function checks for:
    - TEST_DATABASE_URL: Override the PostgreSQL connection URL
    - TEST_REDIS_HOST: Override the Redis host for all Redis services

    Returns:
        TestSettingsProfile: Test settings with CI overrides applied if present.
    """
    return TestSettingsProfile.allow_env_override()
