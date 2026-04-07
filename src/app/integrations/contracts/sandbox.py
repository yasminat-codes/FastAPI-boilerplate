"""Sandbox and dry-run patterns for integration clients.

This module provides protocols and mixins for implementing sandbox/test modes
and dry-run logging in integration clients.

Sandbox Mode vs. Dry-Run Mode
=============================

Sandbox Mode:
- Calls real sandbox APIs provided by the integration provider
- Uses sandbox credentials and sandbox base URLs
- Returns real responses from the sandbox environment
- Useful for: integration testing, development, CI/CD pipelines
- Side effects: None (sandbox is isolated from production)
- Provider dependency: Requires provider to offer sandbox endpoints

Dry-Run Mode:
- Never makes external HTTP calls
- Logs what would be executed without performing it
- Returns mock/synthetic responses
- Useful for: testing business logic, validating request construction,
  pre-flight checks before production
- Side effects: None (purely local)
- Provider dependency: None (no external calls)

When to Use Each:
- Use SANDBOX mode when you want realistic responses from a sandbox environment
- Use DRY_RUN mode when you want to verify logic without any external calls
- Combine both: integrate both sandbox mode AND dry-run capability
- In testing: use sandbox for integration tests, dry-run for unit tests

Implementation Guide
====================

For a provider like Stripe, you might implement:

    class StripeClient(DryRunMixin):
        def __init__(self, settings: IntegrationSettings):
            self.settings = settings
            self._http_client = HttpClient(...)

        def create_charge(self, amount: int, **kwargs) -> StripeCharge:
            self._dry_run_log("create_charge", amount=amount, **kwargs)
            if self._should_execute():
                response = self._http_client.post(
                    f"{self.settings.effective_base_url()}/charges",
                    json={"amount": amount, ...},
                )
                return StripeCharge.parse_obj(response)
            else:
                # Return sandbox response in dry-run mode
                return self._sandbox_response("create_charge", amount=amount)

For sandbox-specific test data, define it per-provider:

    class StripeClient(DryRunMixin):
        SANDBOX_TEST_CARDS = {
            "success": "4242424242424242",
            "decline": "4000000000000002",
        }

        def create_charge(self, card_token: str, **kwargs) -> StripeCharge:
            if self.settings.mode == IntegrationMode.SANDBOX:
                # Use sandbox-only test data
                if card_token in self.SANDBOX_TEST_CARDS.values():
                    # Charge will behave as expected based on card
                    pass

Credential Validation:
- SANDBOX mode: Accept test credentials from provider
- PRODUCTION mode: Require real credentials, validate strictly
- DRY_RUN mode: No real credentials needed; use dummy values for logging

Example credential configuration by mode:

    # development/.env
    STRIPE_MODE=sandbox
    STRIPE_API_KEY=sk_test_123456789...

    # staging/.env
    STRIPE_MODE=production
    STRIPE_API_KEY=sk_live_987654321...
    # (production is real API with real credentials)

    # test/.env
    STRIPE_MODE=dry_run
    STRIPE_API_KEY=dummy_value_for_testing
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from .settings import IntegrationMode, IntegrationSettings

logger = logging.getLogger(__name__)


class SandboxBehavior(Protocol):
    """Protocol for providers that implement sandbox-specific behavior.

    Providers can optionally implement this protocol to provide sandbox/dry-run
    responses. Integration clients can check is_sandbox to conditionally return
    mock data or simplify responses.

    Example:
        @runtime_checkable
        class ProviderClient(SandboxBehavior):
            @property
            def is_sandbox(self) -> bool:
                return self.settings.mode == IntegrationMode.SANDBOX

            def sandbox_response(self, operation: str, **kwargs) -> Any:
                responses = {
                    "create_charge": {"id": "ch_test_123", "amount": kwargs.get("amount")},
                }
                return responses.get(operation, {})
    """

    @property
    def is_sandbox(self) -> bool:
        """Check if the client is in sandbox mode.

        Returns:
            True if operating in sandbox mode, False otherwise.
        """
        ...

    def sandbox_response(self, operation: str, **kwargs: Any) -> Any:
        """Return a mock or test response for an operation in sandbox mode.

        This method allows providers to return realistic-looking test data
        without making actual API calls.

        Args:
            operation: The name of the operation (e.g., 'create_charge').
            **kwargs: Operation-specific arguments.

        Returns:
            A mock response object suitable for the operation.

        Example:
            response = client.sandbox_response("create_charge", amount=100)
            # Returns something like:
            # {"id": "ch_test_123", "amount": 100, "status": "succeeded"}
        """
        ...


class DryRunMixin:
    """Mixin to add dry-run logging capability to integration clients.

    Dry-run mode logs what would be executed without actually performing
    the operation. This is useful for testing business logic and validating
    request construction without side effects.

    Classes using this mixin should:
    1. Have a `settings` attribute of type IntegrationSettings
    2. Call `_should_execute()` before making HTTP requests
    3. Call `_dry_run_log()` before operations to record what would happen

    Example:
        class StripeClient(DryRunMixin):
            def __init__(self, settings: IntegrationSettings):
                self.settings = settings

            def create_charge(self, amount: int) -> StripeCharge:
                self._dry_run_log("create_charge", amount=amount)
                if self._should_execute():
                    return self._http_client.post(...)
                else:
                    return StripeCharge.dry_run_response(amount=amount)
    """

    settings: IntegrationSettings

    def _should_execute(self) -> bool:
        """Check if operations should actually execute.

        Returns False in dry-run mode, True otherwise.

        Returns:
            False if in DRY_RUN mode, True for SANDBOX or PRODUCTION.
        """
        return self.settings.mode != IntegrationMode.DRY_RUN

    def _dry_run_log(self, operation: str, **kwargs: Any) -> None:
        """Log an operation that would be executed in dry-run mode.

        When not in dry-run mode, this is a no-op. In dry-run mode, logs
        what would have been executed at INFO level.

        Args:
            operation: The name of the operation (e.g., 'create_charge').
            **kwargs: Operation-specific parameters to log.

        Example:
            self._dry_run_log("create_charge", amount=100, currency="USD")
            # In dry-run mode, logs:
            # INFO: [stripe] Would execute create_charge: amount=100, currency='USD'
        """
        if self.settings.mode == IntegrationMode.DRY_RUN:
            params_str = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
            logger.info(
                f"[{self.settings.provider_name}] Would execute {operation}: {params_str}"
            )


__all__ = [
    "DryRunMixin",
    "SandboxBehavior",
]
