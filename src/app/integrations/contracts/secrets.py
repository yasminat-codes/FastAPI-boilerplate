"""Secret storage and rotation guidance for provider credentials.

This module provides reusable patterns for managing provider credentials across
integration adapters. It covers both local development (environment variables)
and production secret management (vaults, secret managers).

## Architecture

The SecretProvider protocol defines a generic interface for retrieving and
rotating secrets, allowing integration adapters to work with different storage
backends without coupling to a specific implementation.

## Storage Strategies

### Environment-Based (Development/Local)

For local development and staging, secrets are stored in environment variables:

    export SLACK_API_KEY="xoxb-..."
    export STRIPE_API_KEY="sk_live_..."

Advantages:
- Simple configuration, no external dependencies
- Works well in Docker and container orchestration
- Fits the 12-factor app model

Limitations:
- No built-in rotation
- Secrets visible in process listings and logs if not careful
- Not suitable for production with sensitive credentials

Use ``EnvironmentSecretProvider`` for this pattern.

### Vault-Based (Production)

For production workloads, use a secret vault that provides:
- Automatic rotation with versioning
- Audit logging of secret access
- Fine-grained access control
- Encrypted storage at rest

Popular options:

**AWS Secrets Manager**

    import json
    from typing import Any
    from aws_secretsmanager_caching import SecretCache
    from .secrets import SecretProvider

    class AwsSecretsManagerProvider(SecretProvider):
        def __init__(self, region: str = "us-east-1") -> None:
            self.cache = SecretCache(config=CacheConfig(max_cache_ttl_secs=3600))
            self.region = region

        async def get_secret(self, key: str) -> str | None:
            try:
                secret_json = self.cache.get_secret_string(key)
                if isinstance(secret_json, str) and secret_json.startswith('{'):
                    data = json.loads(secret_json)
                    return data.get("secret_value")
                return secret_json
            except Exception:
                return None

        async def rotate_secret(self, key: str, new_value: str) -> None:
            # AWS Secrets Manager handles versioning internally
            import boto3
            client = boto3.client("secretsmanager", region_name=self.region)
            client.put_secret_value(SecretId=key, SecretString=new_value)

**GCP Secret Manager**

    from typing import Any
    from google.cloud import secretmanager_v1
    from .secrets import SecretProvider

    class GcpSecretManagerProvider(SecretProvider):
        def __init__(self, project_id: str) -> None:
            self.client = secretmanager_v1.SecretManagerServiceClient()
            self.project_id = project_id

        async def get_secret(self, key: str) -> str | None:
            try:
                name = self.client.secret_version_path(self.project_id, key, "latest")
                response = self.client.access_secret_version(request={"name": name})
                return response.payload.data.decode("utf-8")
            except Exception:
                return None

        async def rotate_secret(self, key: str, new_value: str) -> None:
            parent = self.client.secret_path(self.project_id, key)
            self.client.add_secret_version(
                request={"parent": parent, "payload": {"data": new_value.encode("utf-8")}}
            )

**HashiCorp Vault**

    import hvac
    from typing import Any
    from .secrets import SecretProvider

    class VaultSecretProvider(SecretProvider):
        def __init__(self, vault_addr: str, vault_token: str, mount_point: str = "secret") -> None:
            self.client = hvac.Client(url=vault_addr, token=vault_token)
            self.mount_point = mount_point

        async def get_secret(self, key: str) -> str | None:
            try:
                secret = self.client.secrets.kv.v2.read_secret_version(
                    path=key, mount_point=self.mount_point
                )
                return secret["data"]["data"].get("value")
            except Exception:
                return None

        async def rotate_secret(self, key: str, new_value: str) -> None:
            self.client.secrets.kv.v2.create_or_update_secret(
                path=key,
                secret={"value": new_value},
                mount_point=self.mount_point,
            )

## Credential Types and Rotation

Different credential types have different rotation strategies:

### API Keys

API keys are typically long-lived credentials. Rotation workflow:

1. **Provision new key**: Call provider's API to generate a new key
2. **Update provider configuration**: Point adapter to new key via SecretProvider.rotate_secret()
3. **Deploy and verify**: Ensure new key works in production
4. **Revoke old key**: Call provider's API to deactivate old key
5. **Archive**: Log key ID and rotation timestamp for audit trail

Example for a generic REST API:

    async def rotate_api_key(
        adapter: "ProviderAdapter",
        secret_provider: SecretProvider,
    ) -> None:
        # 1. Provision new key
        new_key = await adapter.provision_api_key()

        # 2. Update storage
        await secret_provider.rotate_secret("PROVIDER_API_KEY", new_key)

        # 3. Verify
        test_response = await adapter.health_check()
        if not test_response.ok:
            raise RuntimeError("Health check failed with new key")

        # 4. Revoke old key (if provider supports it)
        old_key = await secret_provider.get_secret("PROVIDER_API_KEY_OLD")
        if old_key:
            await adapter.revoke_api_key(old_key)

        # 5. Archive
        logger.info("api_key_rotated", provider=adapter.name, timestamp=datetime.now(UTC))

### Webhook Secrets

Webhook secrets are used to verify webhook signatures. Rotation is more complex
because you must support both old and new signatures during the transition:

1. **Dual-signature period**: Both old and new secrets are active
2. **New signature generation**: Provider starts signing payloads with new secret
3. **Validate both**: Adapter checks signature against both old and new secrets
4. **Cutover**: After verification period, disable old secret
5. **Cleanup**: Remove old secret from storage

Example:

    @dataclass(frozen=True)
    class WebhookSecrets:
        current: str  # Currently active secret
        previous: str | None = None  # Previous secret during rotation

    async def verify_webhook_signature(
        payload: bytes,
        signature: str,
        secrets: WebhookSecrets,
    ) -> bool:
        import hmac
        import hashlib

        # Try current secret
        expected = hmac.new(secrets.current.encode(), payload, hashlib.sha256).hexdigest()
        if hmac.compare_digest(signature, expected):
            return True

        # Try previous secret if rotating
        if secrets.previous:
            expected = hmac.new(secrets.previous.encode(), payload, hashlib.sha256).hexdigest()
            if hmac.compare_digest(signature, expected):
                logger.warning("webhook_signature_matched_previous_secret")
                return True

        return False

### OAuth Tokens

OAuth tokens are short-lived and automatically refreshed. Store both access
and refresh tokens, and rotate the refresh token when the provider issues a
new one during token refresh flow:

    @dataclass(frozen=True)
    class OAuthCredentials:
        access_token: str
        refresh_token: str
        expires_at: datetime

    async def refresh_oauth_token(
        credentials: OAuthCredentials,
        secret_provider: SecretProvider,
    ) -> OAuthCredentials:
        # Call provider's token endpoint
        new_tokens = await oauth_provider.refresh_token(credentials.refresh_token)

        # Store new tokens (refresh token may have rotated)
        await secret_provider.rotate_secret("OAUTH_ACCESS_TOKEN", new_tokens.access_token)
        await secret_provider.rotate_secret("OAUTH_REFRESH_TOKEN", new_tokens.refresh_token)

        return OAuthCredentials(
            access_token=new_tokens.access_token,
            refresh_token=new_tokens.refresh_token,
            expires_at=new_tokens.expires_at,
        )

## Best Practices

### Never Log Secrets

Always use ``SecretStr`` from pydantic when building models that contain secrets:

    from pydantic import SecretStr

    @dataclass
    class ProviderConfig:
        api_key: SecretStr  # Never printed, only visible when explicitly called .get_secret_value()
        api_url: str

    config = ProviderConfig(api_key=SecretStr("sk-xxx"), api_url="https://api.example.com")
    print(config)  # Shows api_key='**********' instead of actual value

Avoid logging secrets in request/response hooks:

    async def before_request(*, method: str, url: str, headers: dict[str, str], **kw) -> dict[str, str]:
        # BAD: logger.debug("headers", headers=headers)  # Headers may contain Authorization
        logger.debug("request", method=method, url=url)  # Just log safe data
        return headers

### Implement Credential Health Monitoring

Use ``CredentialStatus`` and ``check_credential_health()`` to proactively
detect expired or soon-to-expire credentials:

    from datetime import UTC, datetime, timedelta

    async def monitor_credential_health(
        adapter_name: str,
        credentials: ProviderCredentials,
        policy: SecretRotationPolicy,
    ) -> None:
        status = CredentialStatus(
            provider_name=adapter_name,
            credential_key=f"{adapter_name}_api_key",
            is_valid=True,
            expires_at=credentials.expires_at,
            days_until_expiry=(credentials.expires_at - datetime.now(UTC)).days,
            needs_rotation=credentials.expires_at < (
                datetime.now(UTC) + timedelta(days=policy.warn_before_expiry_days)
            ),
            last_rotated_at=credentials.last_rotated_at,
        )

        healthy, reason = check_credential_health(status, policy)
        if not healthy:
            logger.warning("credential_unhealthy", reason=reason, status=status)
            # Trigger rotation workflow

### Rotate on Schedule

Use a background job or scheduled task to periodically rotate credentials:

    from datetime import UTC, datetime, timedelta

    async def background_credential_rotation_task(
        adapter_registry: AdapterRegistry,
        secret_provider: SecretProvider,
    ) -> None:
        now = datetime.now(UTC)
        for adapter in adapter_registry.all():
            status = await adapter.get_credential_status()
            policy = adapter.rotation_policy

            days_since_rotation = (now - status.last_rotated_at).days
            if days_since_rotation >= policy.rotation_interval_days:
                logger.info(
                    "rotating_credential",
                    provider=adapter.name,
                    days_since_rotation=days_since_rotation,
                )
                await adapter.rotate_credentials(secret_provider)

See also ``src/app/integrations/contracts/sync.py`` for patterns on managing
long-lived sync state alongside credential rotation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretProvider(Protocol):
    """Protocol for retrieving and rotating provider secrets.

    Implementations should handle different storage backends:
    - Environment variables (development)
    - AWS Secrets Manager (AWS)
    - GCP Secret Manager (Google Cloud)
    - HashiCorp Vault (self-hosted)
    - Custom vault (internal systems)

    Secrets are identified by string keys (e.g., "SLACK_BOT_TOKEN"). The
    provider is responsible for resolving those keys to actual secret values.
    """

    async def get_secret(self, key: str) -> str | None:
        """Retrieve a secret by key.

        Args:
            key: The secret identifier (e.g., "SLACK_BOT_TOKEN")

        Returns:
            The secret value, or None if not found. Callers should handle
            None gracefully and fail explicitly if a secret is required.
        """
        ...

    async def rotate_secret(self, key: str, new_value: str) -> None:
        """Store a rotated secret.

        Called after provisioning a new credential from the provider to
        update the stored value. This should be atomic if possible.

        Args:
            key: The secret identifier
            new_value: The new secret value to store

        Raises:
            NotImplementedError: If rotation is not supported by this backend
        """
        ...


class EnvironmentSecretProvider:
    """SecretProvider that reads secrets from environment variables.

    Suitable for development and staging. In production, integrate with a
    proper secret manager (AWS Secrets Manager, Vault, etc.).

    Usage::

        provider = EnvironmentSecretProvider()
        api_key = await provider.get_secret("SLACK_API_KEY")
    """

    async def get_secret(self, key: str) -> str | None:
        """Return the environment variable value, or None if not set."""
        return os.environ.get(key)

    async def rotate_secret(self, key: str, new_value: str) -> None:
        """Raise NotImplementedError with guidance for implementing rotation.

        Environment variables cannot be rotated at runtime. To implement
        credential rotation:

        1. Use a proper secret manager (AWS Secrets Manager, Vault, etc.)
        2. Implement a custom SecretProvider for that backend
        3. Design your rotation workflow to update the manager, then
           restart or signal your application to reload secrets
        4. For zero-downtime rotation, support hot-swapping via a
           configuration reload mechanism

        Example vault-based implementation::

            class VaultSecretProvider(SecretProvider):
                def __init__(self, vault_addr: str, token: str):
                    self.vault = hvac.Client(url=vault_addr, token=token)

                async def rotate_secret(self, key: str, new_value: str) -> None:
                    self.vault.secrets.kv.v2.create_or_update_secret(
                        path=key,
                        secret={"value": new_value},
                    )
        """
        raise NotImplementedError(
            f"EnvironmentSecretProvider does not support rotation. "
            f"To rotate '{key}', implement a custom SecretProvider backed by "
            f"AWS Secrets Manager, GCP Secret Manager, HashiCorp Vault, or similar. "
            f"See module docstring for examples."
        )


@dataclass(frozen=True)
class SecretRotationPolicy:
    """Policy governing when credentials should be rotated.

    Attributes:
        rotation_interval_days: Number of days between rotations.
            Default 90 days (industry standard for API keys).
        warn_before_expiry_days: Number of days before expiry to start
            warning about upcoming rotation. Default 14 days.
        require_rotation: If True, credentials MUST be rotated even if
            they haven't expired. Used for compliance requirements.
    """

    rotation_interval_days: int = 90
    warn_before_expiry_days: int = 14
    require_rotation: bool = False


@dataclass(frozen=True)
class CredentialStatus:
    """Current health and rotation status of a credential.

    Used to track credential lifecycle and make rotation decisions.

    Attributes:
        provider_name: Name of the integration provider (e.g., "slack", "stripe")
        credential_key: The secret key identifier (e.g., "SLACK_API_KEY")
        is_valid: Whether the credential is currently valid and usable
        expires_at: When the credential expires, or None if no expiry
        days_until_expiry: Number of days until credential expires. None
            if no expiry or already expired.
        needs_rotation: True if credential should be rotated (expired,
            expiring soon, or forced by policy)
        last_rotated_at: When the credential was last rotated. None if
            never rotated.
    """

    provider_name: str
    credential_key: str
    is_valid: bool
    expires_at: datetime | None
    days_until_expiry: int | None
    needs_rotation: bool
    last_rotated_at: datetime | None


def check_credential_health(
    status: CredentialStatus,
    policy: SecretRotationPolicy,
) -> tuple[bool, str]:
    """Check whether a credential is healthy given a rotation policy.

    Returns a tuple of (healthy: bool, reason: str). If healthy is False,
    the reason string explains why (e.g., "Expired", "Expiring in 5 days").

    Args:
        status: Current credential status
        policy: Rotation policy to check against

    Returns:
        Tuple of (is_healthy, reason_if_unhealthy). If is_healthy is True,
        reason is empty string.
    """
    now = datetime.now(UTC)

    # Check if already invalid
    if not status.is_valid:
        return False, "Credential is not valid"

    # Check if already expired
    if status.expires_at is not None and status.expires_at < now:
        days_expired = (now - status.expires_at).days
        return False, f"Credential expired {days_expired} days ago"

    # Check if expiring soon
    if status.expires_at is not None and status.days_until_expiry is not None:
        if status.days_until_expiry < policy.warn_before_expiry_days:
            return (
                False,
                f"Credential expiring in {status.days_until_expiry} days"
                f" (threshold: {policy.warn_before_expiry_days})",
            )

    # Check if rotation is required
    if policy.require_rotation and status.needs_rotation:
        return False, "Credential rotation required by policy"

    return True, ""


__all__ = [
    "SecretProvider",
    "EnvironmentSecretProvider",
    "SecretRotationPolicy",
    "CredentialStatus",
    "check_credential_health",
]
