"""Integration-specific settings registration patterns.

This module provides reusable patterns for configuring integrations with
environment-based settings, sandbox/production mode support, and validation.

Patterns are inspired by the HttpClientRuntimeSettings pattern in core.config,
and follow Pydantic v2 patterns with proper type safety and validation.

Example usage:

    # Create a provider-specific settings class
    class StripeSettings(IntegrationSettings):
        model_config = ConfigDict(frozen=True)

    # Register at app startup
    stripe_settings = build_integration_settings(
        "stripe",
        "STRIPE",
        base_url="https://api.stripe.com",
        sandbox_base_url="https://api.stripe.com/test",
        api_key=os.getenv("STRIPE_API_KEY"),
    )
    registry.register(stripe_settings)

    # Use in integration clients
    client = StripeClient(settings=stripe_settings)
    url = stripe_settings.effective_base_url()
    http_config = stripe_settings.to_http_client_config()
"""
from __future__ import annotations

import os
from enum import Enum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import (
    IntegrationConfigError,
    IntegrationProductionValidationError,
)


class IntegrationMode(str, Enum):
    """Integration execution modes for different environments."""

    SANDBOX = "sandbox"
    PRODUCTION = "production"
    DRY_RUN = "dry_run"


class IntegrationSettings(BaseModel):
    """Base class for integration-specific configuration settings.

    Provides common patterns for configuring third-party integrations with
    support for sandbox/production modes, credentials, and HTTP client overrides.

    Sandbox vs. Production Mode
    ===========================
    In SANDBOX mode:
    - The integration uses sandbox_base_url if provided, otherwise base_url
    - Test/dummy credentials are expected (e.g., test API keys from the provider)
    - No real transactions occur; all calls are safe for testing
    - Useful for development, integration testing, and CI/CD pipelines
    - Set via environment: PROVIDER_MODE=sandbox

    In PRODUCTION mode:
    - The integration uses base_url exclusively
    - Real credentials are required; validation enforces secret presence
    - All calls interact with the provider's live API
    - Strict validation prevents accidental misconfigurations
    - Requires explicit enable via environment and secret presence
    - Set via environment: PROVIDER_MODE=production

    Dry-Run Mode
    ============
    In DRY_RUN mode:
    - The integration logs what would be executed without making real requests
    - Useful for testing integration logic in production without side effects
    - Must be implemented by the integration client using DryRunMixin
    - Complements sandbox mode (which uses real sandbox APIs)
    - Set via environment: PROVIDER_MODE=dry_run or DRY_RUN=true

    Best Practices
    ==============
    1. Development:
       - Set MODE=sandbox and use provider's test credentials
       - Sandbox base URLs should be clearly marked in documentation

    2. Integration Testing:
       - Use sandbox mode with mocked HTTP responses
       - Or use dry_run mode to verify logic without external calls

    3. Staging:
       - Use production credentials with sandbox mode (if provider supports)
       - Or use dry_run for final validation before go-live

    4. Production:
       - Set MODE=production; validation will enforce credential presence
       - Use environment variables with proper secret management
       - Monitor for credential expiration and rotation

    5. Switching Modes:
       - Never hardcode mode; always read from environment
       - Use configuration management for infrastructure-level changes
       - Document required environment variables per mode
    """

    # Core configuration
    provider_name: str = Field(
        ...,
        description="Name of the integration provider (e.g., 'stripe', 'slack')",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this integration is enabled",
    )
    mode: IntegrationMode = Field(
        default=IntegrationMode.SANDBOX,
        description="Execution mode: sandbox, production, or dry_run",
    )

    # Base URLs for API endpoints
    base_url: str = Field(
        ...,
        description="Production API base URL",
    )
    sandbox_base_url: str | None = Field(
        default=None,
        description="Sandbox API base URL (optional; uses base_url if not provided)",
    )

    # HTTP client configuration overrides
    timeout_seconds: float = Field(
        default=30.0,
        ge=0.1,
        description="HTTP request timeout in seconds",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum number of automatic retries for transient failures",
    )

    # Credentials
    api_key: str | None = Field(
        default=None,
        description="API key for the integration (may be sandbox or production)",
    )
    api_secret: str | None = Field(
        default=None,
        description="API secret for signing requests or authentication",
    )
    webhook_secret: str | None = Field(
        default=None,
        description="Secret for validating incoming webhook signatures",
    )

    model_config = ConfigDict(frozen=True)

    def effective_base_url(self) -> str:
        """Return the appropriate base URL for the current mode.

        In sandbox mode, returns sandbox_base_url if configured, otherwise base_url.
        In production or dry_run mode, always returns base_url.

        Returns:
            The effective base URL to use for API calls.

        Raises:
            IntegrationConfigError: If base_url is not configured.
        """
        if not self.base_url:
            raise IntegrationConfigError(
                f"base_url is required for {self.provider_name}",
                provider_name=self.provider_name,
            )

        if self.mode == IntegrationMode.SANDBOX and self.sandbox_base_url:
            return self.sandbox_base_url

        return self.base_url

    def validate_for_production(self) -> None:
        """Validate that this integration is properly configured for production.

        Production mode requires:
        - mode must be PRODUCTION
        - api_key must be configured
        - base_url must be configured and not a sandbox URL

        Raises:
            IntegrationProductionValidationError: If validation fails.
        """
        if self.mode != IntegrationMode.PRODUCTION:
            raise IntegrationProductionValidationError(
                f"{self.provider_name} is not in PRODUCTION mode",
                provider_name=self.provider_name,
            )

        if not self.api_key:
            raise IntegrationProductionValidationError(
                f"{self.provider_name} requires api_key for production mode",
                provider_name=self.provider_name,
            )

        if not self.base_url or "sandbox" in self.base_url.lower():
            raise IntegrationProductionValidationError(
                f"{self.provider_name} is configured with a sandbox base_url in production mode",
                provider_name=self.provider_name,
            )

    def to_http_client_config(self) -> dict[str, Any]:
        """Return configuration overrides suitable for HttpClientConfig.

        This method generates a dictionary that can be used to override
        default HttpClientRuntimeSettings for this specific integration.

        Returns:
            A dict with keys like 'timeout_seconds', 'max_retries', etc.
            suitable for passing to HttpClientConfig or as overrides.

        Example:
            settings = IntegrationSettings(...)
            config = settings.to_http_client_config()
            # config = {'HTTP_CLIENT_TIMEOUT_SECONDS': 30.0, ...}
        """
        return {
            "HTTP_CLIENT_TIMEOUT_SECONDS": self.timeout_seconds,
            "HTTP_CLIENT_RETRY_MAX_ATTEMPTS": self.max_retries,
        }

    @model_validator(mode="after")
    def validate_sandbox_credentials(self) -> Self:
        """Validate that sandbox mode has a sandbox URL if one is defined.

        This ensures that when sandbox_base_url is provided, we're in a mode
        that would actually use it.
        """
        if (
            self.sandbox_base_url
            and self.mode != IntegrationMode.SANDBOX
            and not self.sandbox_base_url.endswith("test")
        ):
            # Allow flexibility: if sandbox_base_url is defined but mode is
            # production, it's ok—just won't be used. This is not an error.
            pass

        return self


class IntegrationSettingsRegistry:
    """Registry for managing multiple integration settings.

    Provides centralized storage and validation of all registered integrations,
    with methods to query by provider name, filter by enabled status, and
    perform batch validation.

    Example:
        registry = IntegrationSettingsRegistry()
        registry.register(stripe_settings)
        registry.register(slack_settings)

        # Query
        stripe = registry.get("stripe")
        all_enabled = registry.get_enabled()

        # Validate all at once
        failures = registry.validate_all()
        if failures:
            for name, exc in failures:
                logger.error(f"{name}: {exc}")
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._settings: dict[str, IntegrationSettings] = {}

    def register(self, settings: IntegrationSettings) -> None:
        """Register an integration's settings.

        Args:
            settings: The IntegrationSettings instance to register.

        Raises:
            IntegrationConfigError: If provider_name is empty or settings is invalid.
        """
        if not settings.provider_name:
            raise IntegrationConfigError(
                "provider_name cannot be empty",
                provider_name=settings.provider_name,
            )

        self._settings[settings.provider_name] = settings

    def get(self, provider_name: str) -> IntegrationSettings | None:
        """Get settings for a specific provider.

        Args:
            provider_name: The name of the provider to look up.

        Returns:
            The IntegrationSettings if found, None otherwise.
        """
        return self._settings.get(provider_name)

    def get_enabled(self) -> list[IntegrationSettings]:
        """Get all enabled integrations.

        Returns:
            A list of all registered settings where enabled=True,
            in registration order.
        """
        return [s for s in self._settings.values() if s.enabled]

    def validate_all(self) -> list[tuple[str, Exception]]:
        """Validate all registered integrations.

        Attempts to call validate_for_production() on each registered
        integration (if in production mode) and collects any failures.

        Returns:
            A list of (provider_name, exception) tuples for all integrations
            that failed validation. An empty list means all validations passed.

        Example:
            failures = registry.validate_all()
            if failures:
                for name, exc in failures:
                    logger.error(f"Validation failed for {name}: {exc}")
        """
        failures: list[tuple[str, Exception]] = []

        for name, settings in self._settings.items():
            try:
                if settings.mode == IntegrationMode.PRODUCTION:
                    settings.validate_for_production()
            except Exception as exc:
                failures.append((name, exc))

        return failures

    def __len__(self) -> int:
        """Return the number of registered integrations."""
        return len(self._settings)

    def __contains__(self, provider_name: str) -> bool:
        """Check if a provider is registered."""
        return provider_name in self._settings


def build_integration_settings(
    provider_name: str,
    env_prefix: str,
    **defaults: Any,
) -> IntegrationSettings:
    """Factory function to build IntegrationSettings from environment variables.

    Reads configuration from environment variables with a given prefix.
    For example, with env_prefix='STRIPE', this reads:
    - STRIPE_ENABLED (bool, default True)
    - STRIPE_MODE (sandbox|production|dry_run, default sandbox)
    - STRIPE_BASE_URL (required)
    - STRIPE_SANDBOX_BASE_URL (optional)
    - STRIPE_TIMEOUT_SECONDS (float, default 30.0)
    - STRIPE_MAX_RETRIES (int, default 3)
    - STRIPE_API_KEY (optional)
    - STRIPE_API_SECRET (optional)
    - STRIPE_WEBHOOK_SECRET (optional)

    Args:
        provider_name: The name of the provider (e.g., 'stripe', 'slack').
        env_prefix: The environment variable prefix without trailing underscore
                   (e.g., 'STRIPE' for STRIPE_API_KEY).
        **defaults: Default values to use if environment variables are not set.
                   These are merged with defaults from IntegrationSettings.

    Returns:
        An IntegrationSettings instance with values from environment and defaults.

    Raises:
        IntegrationConfigError: If required fields (base_url) are missing.

    Example:
        stripe_settings = build_integration_settings(
            "stripe",
            "STRIPE",
            base_url="https://api.stripe.com",
            sandbox_base_url="https://api.stripe.com/test",
        )
    """
    prefix = f"{env_prefix}_"

    # Parse mode
    mode_str = os.getenv(f"{prefix}MODE", defaults.get("mode", "sandbox")).lower()
    try:
        mode = IntegrationMode(mode_str)
    except ValueError:
        raise IntegrationConfigError(
            f"Invalid mode '{mode_str}' for {provider_name}. Must be one of: "
            f"{', '.join([m.value for m in IntegrationMode])}",
            provider_name=provider_name,
        )

    # Parse enabled flag
    enabled_str = os.getenv(f"{prefix}ENABLED", "").lower()
    if enabled_str in ("false", "0", "no"):
        enabled = False
    elif enabled_str in ("true", "1", "yes", ""):
        enabled = defaults.get("enabled", True)
    else:
        enabled = defaults.get("enabled", True)

    # Parse timeout and retries
    try:
        timeout_seconds = float(
            os.getenv(f"{prefix}TIMEOUT_SECONDS", defaults.get("timeout_seconds", 30.0))
        )
    except ValueError:
        timeout_seconds = defaults.get("timeout_seconds", 30.0)

    try:
        max_retries = int(
            os.getenv(f"{prefix}MAX_RETRIES", defaults.get("max_retries", 3))
        )
    except ValueError:
        max_retries = defaults.get("max_retries", 3)

    # Get all other fields
    base_url = os.getenv(f"{prefix}BASE_URL", defaults.get("base_url"))
    sandbox_base_url = os.getenv(f"{prefix}SANDBOX_BASE_URL", defaults.get("sandbox_base_url"))
    api_key = os.getenv(f"{prefix}API_KEY", defaults.get("api_key"))
    api_secret = os.getenv(f"{prefix}API_SECRET", defaults.get("api_secret"))
    webhook_secret = os.getenv(f"{prefix}WEBHOOK_SECRET", defaults.get("webhook_secret"))

    if not base_url:
        raise IntegrationConfigError(
            f"base_url is required for {provider_name}; "
            f"set {prefix}BASE_URL or pass base_url to build_integration_settings()",
            provider_name=provider_name,
        )

    return IntegrationSettings(
        provider_name=provider_name,
        enabled=enabled,
        mode=mode,
        base_url=base_url,
        sandbox_base_url=sandbox_base_url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        api_key=api_key,
        api_secret=api_secret,
        webhook_secret=webhook_secret,
    )


__all__ = [
    "IntegrationMode",
    "IntegrationSettings",
    "IntegrationSettingsRegistry",
    "build_integration_settings",
]
