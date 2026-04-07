"""Contracts and guidance for building reusable provider integration adapters.

This package provides base contracts (protocols), dataclasses, and utilities
that integration adapters build on top of to implement provider-specific logic.

The contracts are designed to be:

- **Generic**: Work across providers (Slack, Stripe, GitHub, etc.)
- **Extensible**: Support custom provider-specific behavior
- **Observable**: Integrate with logging, metrics, and tracing
- **Resilient**: Handle rate limits, retries, credential rotation, interruption

## Modules

**client.py**: Base classes and protocols for integration clients

- ``IntegrationClient``: Protocol for all integration adapters
- ``BaseIntegrationClient``: Abstract base with HTTP transport, health checks, lifecycle
- ``IntegrationHealthStatus``: Health snapshot for observability

**errors.py**: Normalized integration error taxonomy

- ``IntegrationError``: Base exception with provider context
- Semantic subclasses for auth, not-found, rate-limit, timeout, etc.
- ``classify_http_error()``: Map HTTP errors to integration errors
- ``is_retryable_integration_error()``: Determine retry eligibility

**results.py**: Standard result models for external calls

- ``IntegrationResult``: Single operation result with success/failure semantics
- ``PaginatedIntegrationResult``: Cursor-based paginated results
- ``BulkIntegrationResult``: Batch operations with per-item tracking

**settings.py**: Integration-specific settings registration patterns

- ``IntegrationMode``: Sandbox, production, and dry-run modes
- ``IntegrationSettings``: Base configuration with env-var factory
- ``IntegrationSettingsRegistry``: Centralized settings management
- ``build_integration_settings()``: Factory from environment variables

**sandbox.py**: Sandbox and dry-run patterns

- ``SandboxBehavior``: Protocol for sandbox-specific responses
- ``DryRunMixin``: Mixin for dry-run logging without HTTP calls

**secrets.py**: Secret storage and rotation patterns

- ``SecretProvider``: Protocol for retrieving and rotating credentials
- ``EnvironmentSecretProvider``: Environment variable-based implementation
- ``SecretRotationPolicy``: Configuration for rotation schedules
- ``CredentialStatus``: Health tracking for credentials
- ``check_credential_health()``: Determine if credential needs rotation

**sync.py**: Data synchronization checkpoint and cursor patterns

- ``SyncStrategy``: Choose between cursor-based, timestamp-based, offset-based, or full sync
- ``SyncCursor``: Opaque pagination cursor (handles different pagination schemes)
- ``SyncPage``: One page of fetched data
- ``SyncOperation``: Protocol for provider-specific fetch/process logic
- ``SyncProgress``: Progress tracking for sync operations
"""

from __future__ import annotations

from .client import (
    BaseIntegrationClient,
    IntegrationClient,
    IntegrationHealthStatus,
)
from .errors import (
    IntegrationAuthError,
    IntegrationConfigError,
    IntegrationConnectionError,
    IntegrationCredentialError,
    IntegrationDisabledError,
    IntegrationError,
    IntegrationModeError,
    IntegrationNotFoundError,
    IntegrationProductionValidationError,
    IntegrationRateLimitError,
    IntegrationServerError,
    IntegrationTimeoutError,
    IntegrationUnavailableError,
    IntegrationValidationError,
    classify_http_error,
    is_retryable_integration_error,
)
from .results import (
    BulkIntegrationResult,
    IntegrationResult,
    PaginatedIntegrationResult,
)
from .sandbox import (
    DryRunMixin,
    SandboxBehavior,
)
from .secrets import (
    CredentialStatus,
    EnvironmentSecretProvider,
    SecretProvider,
    SecretRotationPolicy,
    check_credential_health,
)
from .settings import (
    IntegrationMode,
    IntegrationSettings,
    IntegrationSettingsRegistry,
    build_integration_settings,
)
from .sync import (
    SyncCursor,
    SyncOperation,
    SyncPage,
    SyncProgress,
    SyncStrategy,
)

__all__ = [
    # Client protocols and base classes
    "BaseIntegrationClient",
    "IntegrationClient",
    "IntegrationHealthStatus",
    # Error taxonomy
    "IntegrationAuthError",
    "IntegrationConfigError",
    "IntegrationConnectionError",
    "IntegrationCredentialError",
    "IntegrationDisabledError",
    "IntegrationError",
    "IntegrationModeError",
    "IntegrationNotFoundError",
    "IntegrationProductionValidationError",
    "IntegrationRateLimitError",
    "IntegrationServerError",
    "IntegrationTimeoutError",
    "IntegrationUnavailableError",
    "IntegrationValidationError",
    "classify_http_error",
    "is_retryable_integration_error",
    # Result models
    "BulkIntegrationResult",
    "IntegrationResult",
    "PaginatedIntegrationResult",
    # Settings and registry
    "IntegrationMode",
    "IntegrationSettings",
    "IntegrationSettingsRegistry",
    "build_integration_settings",
    # Sandbox and dry-run
    "DryRunMixin",
    "SandboxBehavior",
    # Secrets
    "CredentialStatus",
    "EnvironmentSecretProvider",
    "SecretProvider",
    "SecretRotationPolicy",
    "check_credential_health",
    # Sync
    "SyncCursor",
    "SyncOperation",
    "SyncPage",
    "SyncProgress",
    "SyncStrategy",
]
