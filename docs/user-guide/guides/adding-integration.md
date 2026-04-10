# Adding a Client Integration

Client integrations are reusable adapters for third-party APIs. They standardize HTTP communication, error handling, credential management, and health checks. This guide walks through creating an adapter for a fictional "Acme CRM" provider.

## Overview

An integration client:
1. Subclasses `BaseIntegrationClient` or implements `IntegrationClient` protocol
2. Uses the shared `TemplateHttpClient` for HTTP calls
3. Manages credentials via `IntegrationSettings` and `IntegrationSettingsRegistry`
4. Returns standardized results using `IntegrationResult`
5. Implements health checks for observability

## Step 1: Create the Provider Module

Create `src/app/integrations/providers/acme_crm.py`:

```python
"""Acme CRM integration client."""

from __future__ import annotations

from typing import Any

from src.app.integrations import (
    BaseIntegrationClient,
    IntegrationHealthStatus,
    IntegrationResult,
    IntegrationSettings,
    IntegrationMode,
)
from src.app.integrations.http_client import TemplateHttpClient


class AcmeCrmSettings(IntegrationSettings):
    """Configuration for Acme CRM integration."""

    api_key: str
    """Acme API key from environment."""
    
    sandbox_mode: bool = False
    """Use Acme sandbox environment."""


class AcmeCrmClient(BaseIntegrationClient):
    """Acme CRM API client adapter."""

    def __init__(
        self,
        http_client: TemplateHttpClient,
        api_key: str,
        *,
        mode: IntegrationMode = IntegrationMode.PRODUCTION,
        sandbox_mode: bool = False,
    ) -> None:
        """Initialize Acme CRM client.
        
        Args:
            http_client: Shared HTTP client for requests.
            api_key: Acme API key.
            mode: Integration mode (sandbox, production, dry_run).
            sandbox_mode: Use Acme sandbox environment.
        """
        super().__init__(
            http_client,
            provider_name="acme_crm",
            mode=mode,
            health_check_url="/v1/health",
        )
        self.api_key = api_key
        self.sandbox_mode = sandbox_mode
        self.base_url = (
            "https://sandbox.acme-api.com"
            if sandbox_mode
            else "https://api.acme-api.com"
        )

    async def create_contact(self, email: str, name: str) -> IntegrationResult:
        """Create a contact in Acme CRM.
        
        Args:
            email: Contact email address.
            name: Contact name.
        
        Returns:
            IntegrationResult with contact_id on success.
        """
        try:
            response = await self._request(
                "POST",
                f"{self.base_url}/v1/contacts",
                operation="create_contact",
                json={
                    "email": email,
                    "name": name,
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            
            data = response.json()
            return IntegrationResult(
                success=True,
                data={
                    "contact_id": data["id"],
                    "email": data["email"],
                },
            )
        
        except Exception as exc:
            return IntegrationResult(
                success=False,
                error_message=str(exc),
                error_code="CREATE_CONTACT_FAILED",
            )

    async def get_contact(self, contact_id: str) -> IntegrationResult:
        """Retrieve a contact by ID.
        
        Args:
            contact_id: Acme contact ID.
        
        Returns:
            IntegrationResult with contact details.
        """
        try:
            response = await self._request(
                "GET",
                f"{self.base_url}/v1/contacts/{contact_id}",
                operation="get_contact",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            
            data = response.json()
            return IntegrationResult(
                success=True,
                data=data,
            )
        
        except Exception as exc:
            return IntegrationResult(
                success=False,
                error_message=str(exc),
                error_code="GET_CONTACT_FAILED",
            )

    async def update_contact(
        self,
        contact_id: str,
        **fields: Any,
    ) -> IntegrationResult:
        """Update a contact's fields.
        
        Args:
            contact_id: Acme contact ID.
            **fields: Fields to update (e.g., name="New Name").
        
        Returns:
            IntegrationResult indicating success or failure.
        """
        try:
            response = await self._request(
                "PATCH",
                f"{self.base_url}/v1/contacts/{contact_id}",
                operation="update_contact",
                json=fields,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            
            return IntegrationResult(
                success=True,
                data=response.json(),
            )
        
        except Exception as exc:
            return IntegrationResult(
                success=False,
                error_message=str(exc),
                error_code="UPDATE_CONTACT_FAILED",
            )

    async def health_check(self) -> IntegrationHealthStatus:
        """Check Acme CRM API health.
        
        Returns:
            IntegrationHealthStatus with provider health.
        """
        try:
            response = await self._request(
                "GET",
                f"{self.base_url}/v1/health",
                operation="health_check",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                },
                raise_for_status_codes=False,
            )
            
            healthy = response.is_success
            return IntegrationHealthStatus(
                healthy=healthy,
                provider=self.provider_name,
                detail=None if healthy else f"HTTP {response.status_code}",
            )
        
        except Exception as exc:
            return IntegrationHealthStatus(
                healthy=False,
                provider=self.provider_name,
                detail=str(exc),
            )
```

!!! tip
    The `_request()` method automatically adds provider context to logs and wraps HTTP errors. Use it for all provider calls.

## Step 2: Create Settings and Registry

Create `src/app/integrations/providers/acme_crm_settings.py`:

```python
"""Acme CRM settings and registry."""

from __future__ import annotations

import os

from src.app.integrations import (
    IntegrationSettingsRegistry,
    build_integration_settings,
)
from .acme_crm import AcmeCrmSettings, AcmeCrmClient


def build_acme_crm_settings() -> AcmeCrmSettings:
    """Build Acme CRM settings from environment variables."""
    return build_integration_settings(
        AcmeCrmSettings,
        api_key=os.getenv("ACME_CRM_API_KEY", ""),
        sandbox_mode=os.getenv("ACME_CRM_SANDBOX", "false").lower() == "true",
    )


# Registry for Acme CRM (use this for credential rotation, validation)
acme_crm_registry = IntegrationSettingsRegistry(
    provider="acme_crm",
    settings_class=AcmeCrmSettings,
)
```

## Step 3: Factory for Creating Clients

Add to the same file:

```python
async def create_acme_crm_client(
    http_client: TemplateHttpClient,
    settings: AcmeCrmSettings | None = None,
) -> AcmeCrmClient:
    """Create an Acme CRM client.
    
    Args:
        http_client: Shared HTTP client.
        settings: Optional settings override.
    
    Returns:
        AcmeCrmClient instance ready to use.
    """
    if settings is None:
        settings = build_acme_crm_settings()
    
    return AcmeCrmClient(
        http_client,
        api_key=settings.api_key,
        mode=settings.mode,
        sandbox_mode=settings.sandbox_mode,
    )
```

## Step 4: Use the Client in a Route

In a FastAPI route:

```python
from fastapi import APIRouter, Depends
from src.app.core.config import get_http_client
from src.app.integrations.providers.acme_crm_settings import (
    create_acme_crm_client,
)
from src.app.integrations.http_client import TemplateHttpClient

router = APIRouter(prefix="/crm", tags=["crm"])


@router.post("/contacts")
async def create_contact(
    email: str,
    name: str,
    http_client: TemplateHttpClient = Depends(get_http_client),
):
    """Create a contact in Acme CRM."""
    client = await create_acme_crm_client(http_client)
    
    try:
        result = await client.create_contact(email=email, name=name)
        
        if not result.success:
            return {
                "error": result.error_message,
                "error_code": result.error_code,
            }
        
        return {
            "contact_id": result.data["contact_id"],
            "email": result.data["email"],
        }
    
    finally:
        await client.close()
```

## Step 5 (Optional): Use as Async Context Manager

Clients can be used with `async with`:

```python
async def sync_contacts():
    """Sync all contacts from template to Acme CRM."""
    http_client = get_http_client()
    
    async with await create_acme_crm_client(http_client) as client:
        # Client is automatically closed on exit
        users = await get_all_users()
        
        for user in users:
            result = await client.create_contact(
                email=user.email,
                name=user.name,
            )
            
            if not result.success:
                logger.error(
                    "Failed to sync contact",
                    user_id=user.id,
                    error=result.error_message,
                )
```

## Step 6 (Optional): Add Error Classification

Handle provider-specific errors:

```python
from src.app.integrations import (
    IntegrationRateLimitError,
    IntegrationValidationError,
    classify_http_error,
)


async def create_contact(self, email: str, name: str) -> IntegrationResult:
    """Create contact with error classification."""
    try:
        response = await self._request(
            "POST",
            f"{self.base_url}/v1/contacts",
            operation="create_contact",
            json={"email": email, "name": name},
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        
        return IntegrationResult(
            success=True,
            data=response.json(),
        )
    
    except IntegrationRateLimitError as exc:
        logger.warning("Rate limit hit", retry_after=exc.retry_after_seconds)
        return IntegrationResult(
            success=False,
            error_code="RATE_LIMITED",
            error_message="Acme CRM rate limit exceeded",
        )
    
    except IntegrationValidationError as exc:
        logger.error("Validation error", details=exc.details)
        return IntegrationResult(
            success=False,
            error_code="VALIDATION_ERROR",
            error_message=str(exc),
        )
    
    except Exception as exc:
        return IntegrationResult(
            success=False,
            error_code="UNKNOWN_ERROR",
            error_message=str(exc),
        )
```

## Step 7: Test the Client

```python
import pytest
from src.app.integrations.http_client import TemplateHttpClient
from src.app.integrations.providers.acme_crm import AcmeCrmClient


@pytest.mark.asyncio
async def test_create_contact():
    http_client = TemplateHttpClient()
    client = AcmeCrmClient(
        http_client,
        api_key="test-key",
        mode="sandbox",
    )
    
    result = await client.create_contact(
        email="alice@example.com",
        name="Alice",
    )
    
    assert result.success
    assert result.data["contact_id"] is not None
    
    await client.close()


@pytest.mark.asyncio
async def test_health_check():
    http_client = TemplateHttpClient()
    client = AcmeCrmClient(http_client, api_key="test-key")
    
    status = await client.health_check()
    assert status.provider == "acme_crm"
```

## Checklist

- [ ] Created provider module under `src/app/integrations/providers/`
- [ ] Subclassed `BaseIntegrationClient` or implemented `IntegrationClient`
- [ ] Implemented all provider methods using `_request()`
- [ ] Created settings class extending `IntegrationSettings`
- [ ] Created settings registry with `IntegrationSettingsRegistry`
- [ ] Implemented `health_check()` method
- [ ] Added factory function for creating clients
- [ ] Used client in a FastAPI route
- [ ] (Optional) Added error classification for provider-specific errors
- [ ] (Optional) Implemented dry-run or sandbox mode
- [ ] Added unit tests covering success and failure paths
- [ ] Documented required environment variables

## Next Steps

See [Adding a Workflow](adding-workflow.md) to orchestrate multi-step integration workflows.
