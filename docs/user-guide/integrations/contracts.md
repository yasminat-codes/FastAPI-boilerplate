# Integration Contracts

The `src/app/integrations/contracts/` package defines the standard contracts that all provider integration adapters should follow. These contracts sit on top of the [HTTP client layer](index.md) and provide consistent patterns for client lifecycle, error handling, result wrapping, settings registration, sandbox modes, secret management, and data synchronization.

## Client Protocol and Base Class

Every integration adapter should either implement the `IntegrationClient` protocol or subclass `BaseIntegrationClient`.

### IntegrationClient Protocol

The protocol defines the minimum interface for any integration adapter: a provider name, a health check, lifecycle management, and context manager support.

```python
from src.app.integrations import IntegrationClient, IntegrationHealthStatus

class MyClient:
    @property
    def provider_name(self) -> str:
        return "my_provider"

    async def health_check(self) -> IntegrationHealthStatus:
        return IntegrationHealthStatus(healthy=True, provider="my_provider")

    async def close(self) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
```

### BaseIntegrationClient

The abstract base class provides default implementations for health checks, HTTP request wrapping with structured logging, and resource lifecycle management:

```python
from src.app.integrations import BaseIntegrationClient, IntegrationMode
from src.app.integrations.http_client import TemplateHttpClient

class StripeClient(BaseIntegrationClient):
    def __init__(self, http_client: TemplateHttpClient) -> None:
        super().__init__(
            http_client=http_client,
            provider_name="stripe",
            mode=IntegrationMode.PRODUCTION,
            health_check_url="/v1/balance",
        )

    async def get_customer(self, customer_id: str) -> dict:
        response = await self._request("GET", f"/v1/customers/{customer_id}", operation="get_customer")
        return response.json()
```

The `_request(...)` method wraps `TemplateHttpClient.request(...)` with provider-scoped structured log events at `integration_request_start` and `integration_request_complete`, plus a `integration_request_error` warning on exceptions.

## Error Taxonomy

The error taxonomy maps HTTP-level errors into semantic integration errors so callers can make retry and fallback decisions without inspecting raw status codes.

### Error Hierarchy

All errors inherit from `IntegrationError`, which carries `provider_name`, `operation`, `detail`, and `cause` fields for structured logging and diagnostics.

| Error Class | Trigger | Retryable |
|-------------|---------|-----------|
| `IntegrationAuthError` | 401/403 | No |
| `IntegrationNotFoundError` | 404 | No |
| `IntegrationValidationError` | 400 | No |
| `IntegrationConfigError` | Misconfiguration | No |
| `IntegrationRateLimitError` | 429 | Yes |
| `IntegrationTimeoutError` | Timeout | Yes |
| `IntegrationConnectionError` | Network failure | Yes |
| `IntegrationServerError` | 5xx | Yes |
| `IntegrationUnavailableError` | Circuit breaker open | Yes |
| `IntegrationDisabledError` | Integration disabled | No |
| `IntegrationCredentialError` | Missing/bad credentials | No |
| `IntegrationProductionValidationError` | Production config invalid | No |

### classify_http_error

Converts an `HttpClientError` from the HTTP client layer into the appropriate `IntegrationError` subclass:

```python
from src.app.integrations import classify_http_error
from src.app.integrations.http_client import HttpClientError

try:
    response = await client.get("/resource")
except HttpClientError as exc:
    integration_error = classify_http_error("provider_name", "operation_name", exc)
    if is_retryable_integration_error(integration_error):
        schedule_retry(integration_error)
```

## Result Models

Integration operations should return typed result wrappers instead of raw responses or exceptions.

### IntegrationResult

Wraps either success data or a failure error with provider context and timing:

```python
from src.app.integrations import IntegrationResult

# Success
result = IntegrationResult.ok(data=customer, provider="stripe", operation="get_customer", duration_ms=125.5)

# Failure
result = IntegrationResult.fail(error=integration_error)

# Conditional handling
if result.success:
    process(result.data)
elif result.is_retryable:
    schedule_retry(result)
```

### PaginatedIntegrationResult

Extends `IntegrationResult` with cursor and pagination metadata for streaming large result sets.

### BulkIntegrationResult

Tracks per-item success and failure for batch operations, with `succeeded`, `failed`, `partial_success`, and retry support.

## Settings and Registry

### IntegrationSettings

Base configuration model for provider-specific settings with sandbox/production/dry-run mode support, credential fields, and HTTP client overrides.

```python
from src.app.integrations import IntegrationSettings, IntegrationMode, build_integration_settings

# From environment variables (reads STRIPE_MODE, STRIPE_BASE_URL, STRIPE_API_KEY, etc.)
stripe = build_integration_settings("stripe", "STRIPE", base_url="https://api.stripe.com")

# Or direct construction
stripe = IntegrationSettings(
    provider_name="stripe",
    base_url="https://api.stripe.com",
    sandbox_base_url="https://api.stripe.com/test",
    mode=IntegrationMode.SANDBOX,
    api_key="sk_test_xxx",
)

# Get the right URL for the current mode
url = stripe.effective_base_url()
```

### IntegrationSettingsRegistry

Centralized storage for all registered integrations, with batch validation and enabled/disabled filtering:

```python
from src.app.integrations import IntegrationSettingsRegistry

registry = IntegrationSettingsRegistry()
registry.register(stripe_settings)
registry.register(slack_settings)

# Query
stripe = registry.get("stripe")
all_enabled = registry.get_enabled()

# Validate all production integrations at startup
failures = registry.validate_all()
```

## Sandbox and Dry-Run Modes

### IntegrationMode

Three modes control adapter behavior:

- **SANDBOX**: Calls real sandbox APIs with test credentials
- **PRODUCTION**: Calls real production APIs with validated credentials
- **DRY_RUN**: Logs what would execute without making HTTP calls

### DryRunMixin

Add dry-run support to integration clients by mixing in `DryRunMixin` and calling `_should_execute()` before HTTP requests:

```python
from src.app.integrations import DryRunMixin

class MyClient(DryRunMixin):
    def create_resource(self, data: dict) -> dict:
        self._dry_run_log("create_resource", **data)
        if self._should_execute():
            return self._http_client.post("/resources", json=data)
        return {"id": "dry_run_placeholder"}
```

## Secret Management

### SecretProvider Protocol

Defines a generic interface for retrieving and rotating secrets across different storage backends (environment variables, AWS Secrets Manager, GCP Secret Manager, HashiCorp Vault).

The template ships `EnvironmentSecretProvider` for development. Implement `SecretProvider` for your production vault.

### Credential Health

`CredentialStatus` and `check_credential_health()` track credential lifecycle and trigger rotation based on configurable `SecretRotationPolicy`:

```python
from src.app.integrations import CredentialStatus, SecretRotationPolicy, check_credential_health

status = CredentialStatus(
    provider_name="stripe",
    credential_key="STRIPE_API_KEY",
    is_valid=True,
    expires_at=credential_expiry,
    days_until_expiry=25,
    needs_rotation=False,
    last_rotated_at=last_rotation_time,
)

policy = SecretRotationPolicy(rotation_interval_days=90, warn_before_expiry_days=14)
healthy, reason = check_credential_health(status, policy)
```

See `src/app/integrations/contracts/secrets.py` for detailed guidance on API key rotation, webhook secret rotation with dual-signature periods, and OAuth token management.

## Sync Checkpoint and Cursor Patterns

For integrations that pull data incrementally from external providers, the template provides cursor and checkpoint primitives that sit on top of the `IntegrationSyncCheckpoint` database table.

### SyncStrategy

Choose the right pagination strategy for the provider:

- **CURSOR_BASED**: Provider returns opaque cursor (Slack, Discord, Linear)
- **TIMESTAMP_BASED**: Filter by modification time (GitHub, Jira, Salesforce)
- **OFFSET_BASED**: Use offset/limit pagination (legacy APIs)
- **FULL_SYNC**: Fetch everything (small datasets or full refreshes)

### SyncCursor

Abstracts different pagination schemes into a single serializable cursor. Roundtrips through JSON for checkpoint persistence:

```python
from src.app.integrations import SyncCursor

# Create from provider response
cursor = SyncCursor(cursor_value="abc123")

# Serialize to checkpoint
state = cursor.to_cursor_state()  # {"cursor_value": "abc123"}

# Restore from checkpoint
restored = SyncCursor.from_cursor_state(state)
```

### SyncOperation Protocol

Implement for each provider-specific sync to define `fetch_page()` and `process_page()` logic. See `src/app/integrations/contracts/sync.py` for a complete Slack-style example with checkpoint recovery and progress monitoring.

## See Also

For patterns to handle integration failures gracefully, see [Resilience Patterns](resilience.md):

- **Fallback providers** — Use cached or stale data when primary provider is unavailable
- **Partial failure handling** — Salvage successful items when some items in a batch fail
- **Compensating actions** — Automate rollback for multi-step workflows that partially fail
- **Deferred retries** — Push failed calls to background job queue when inline retries exhaust

For operational guidance when integrations degrade, see [Runbooks](runbooks.md).
