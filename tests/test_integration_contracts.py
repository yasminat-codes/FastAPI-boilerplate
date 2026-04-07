"""Regression tests for integration contract primitives (Phase 7 Wave 7.2).

Covers the full integration contracts surface: client protocols, error taxonomy,
result models, settings/registry, sandbox/dry-run patterns, secret management,
and sync checkpoint/cursor primitives.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import from the canonical integration export surface
# ---------------------------------------------------------------------------
from src.app.integrations import (
    BaseIntegrationClient,
    BulkIntegrationResult,
    CredentialStatus,
    DryRunMixin,
    EnvironmentSecretProvider,
    IntegrationAuthError,
    IntegrationConfigError,
    IntegrationConnectionError,
    IntegrationCredentialError,
    IntegrationDisabledError,
    IntegrationError,
    IntegrationHealthStatus,
    IntegrationMode,
    IntegrationModeError,
    IntegrationNotFoundError,
    IntegrationProductionValidationError,
    IntegrationRateLimitError,
    IntegrationResult,
    IntegrationServerError,
    IntegrationSettings,
    IntegrationSettingsRegistry,
    IntegrationTimeoutError,
    IntegrationUnavailableError,
    IntegrationValidationError,
    PaginatedIntegrationResult,
    SecretRotationPolicy,
    SyncCursor,
    SyncPage,
    SyncProgress,
    SyncStrategy,
    build_integration_settings,
    check_credential_health,
    classify_http_error,
    is_retryable_integration_error,
)
from src.app.integrations.http_client.exceptions import (
    HttpAuthenticationError,
    HttpCircuitOpenError,
    HttpClientBadRequestError,
    HttpClientError,
    HttpConnectionError,
    HttpNotFoundError,
    HttpRateLimitError,
    HttpServerError,
    HttpTimeoutError,
)


# ===================================================================
# Export surface completeness
# ===================================================================
class TestExportSurfaceCompleteness:
    """Verify the contracts package exports all expected symbols."""

    def test_contracts_package_exports_client_primitives(self) -> None:
        from src.app.integrations.contracts import (
            BaseIntegrationClient,
            IntegrationClient,
            IntegrationHealthStatus,
        )

        assert BaseIntegrationClient is not None
        assert IntegrationClient is not None
        assert IntegrationHealthStatus is not None

    def test_contracts_package_exports_error_taxonomy(self) -> None:
        from src.app.integrations.contracts import (
            IntegrationAuthError,
            IntegrationError,
            classify_http_error,
            is_retryable_integration_error,
        )

        assert issubclass(IntegrationAuthError, IntegrationError)
        assert callable(classify_http_error)
        assert callable(is_retryable_integration_error)

    def test_contracts_package_exports_result_models(self) -> None:
        from src.app.integrations.contracts import (
            BulkIntegrationResult,
            IntegrationResult,
            PaginatedIntegrationResult,
        )

        assert IntegrationResult is not None
        assert issubclass(PaginatedIntegrationResult, IntegrationResult)
        assert BulkIntegrationResult is not None

    def test_contracts_package_exports_settings_primitives(self) -> None:
        from src.app.integrations.contracts import (
            IntegrationMode,
            build_integration_settings,
        )

        assert IntegrationMode.SANDBOX.value == "sandbox"
        assert callable(build_integration_settings)

    def test_contracts_package_exports_sandbox_primitives(self) -> None:
        from src.app.integrations.contracts import DryRunMixin, SandboxBehavior

        assert DryRunMixin is not None
        assert SandboxBehavior is not None

    def test_contracts_package_exports_secret_primitives(self) -> None:
        from src.app.integrations.contracts import (
            EnvironmentSecretProvider,
            check_credential_health,
        )

        assert callable(check_credential_health)
        assert EnvironmentSecretProvider is not None

    def test_contracts_package_exports_sync_primitives(self) -> None:
        from src.app.integrations.contracts import (
            SyncCursor,
            SyncStrategy,
        )

        assert SyncStrategy.CURSOR_BASED.value == "cursor_based"
        assert SyncCursor is not None

    def test_top_level_integrations_exports_all_contracts(self) -> None:
        import src.app.integrations as integrations

        expected_contract_names = [
            "BaseIntegrationClient",
            "IntegrationClient",
            "IntegrationHealthStatus",
            "IntegrationMode",
            "IntegrationError",
            "IntegrationResult",
            "IntegrationSettings",
            "IntegrationSettingsRegistry",
            "DryRunMixin",
            "SandboxBehavior",
            "SecretProvider",
            "EnvironmentSecretProvider",
            "SyncStrategy",
            "SyncCursor",
            "SyncPage",
            "SyncOperation",
            "SyncProgress",
            "classify_http_error",
            "is_retryable_integration_error",
            "build_integration_settings",
            "check_credential_health",
        ]
        for name in expected_contract_names:
            assert hasattr(integrations, name), f"Missing export: {name}"


# ===================================================================
# IntegrationMode
# ===================================================================
class TestIntegrationMode:
    """Verify IntegrationMode is unified across client and settings modules."""

    def test_mode_values(self) -> None:
        assert IntegrationMode.SANDBOX == "sandbox"
        assert IntegrationMode.PRODUCTION == "production"
        assert IntegrationMode.DRY_RUN == "dry_run"

    def test_mode_shared_between_client_and_settings(self) -> None:
        from src.app.integrations.contracts.settings import IntegrationMode as SettingsMode

        assert SettingsMode is IntegrationMode


# ===================================================================
# Error taxonomy
# ===================================================================
class TestErrorTaxonomy:
    """Verify the integration error hierarchy and classification."""

    def test_all_errors_inherit_from_integration_error(self) -> None:
        error_classes = [
            IntegrationAuthError,
            IntegrationConfigError,
            IntegrationConnectionError,
            IntegrationCredentialError,
            IntegrationDisabledError,
            IntegrationModeError,
            IntegrationNotFoundError,
            IntegrationProductionValidationError,
            IntegrationRateLimitError,
            IntegrationServerError,
            IntegrationTimeoutError,
            IntegrationUnavailableError,
            IntegrationValidationError,
        ]
        for cls in error_classes:
            assert issubclass(cls, IntegrationError), f"{cls.__name__} should inherit IntegrationError"

    def test_integration_error_captures_provider_context(self) -> None:
        error = IntegrationError(
            "test failure",
            provider_name="stripe",
            operation="create_payment",
            detail="card_declined",
            cause=ValueError("bad card"),
        )
        assert error.provider_name == "stripe"
        assert error.operation == "create_payment"
        assert error.detail == "card_declined"
        assert isinstance(error.cause, ValueError)
        assert str(error) == "test failure"

    def test_rate_limit_error_captures_retry_after(self) -> None:
        error = IntegrationRateLimitError(
            "rate limited",
            provider_name="github",
            retry_after_seconds=60.0,
        )
        assert error.retry_after_seconds == 60.0

    def test_classify_http_authentication_error(self) -> None:
        http_err = HttpAuthenticationError("Unauthorized")
        result = classify_http_error("stripe", "charge", http_err)
        assert isinstance(result, IntegrationAuthError)
        assert result.provider_name == "stripe"
        assert result.operation == "charge"
        assert result.cause is http_err

    def test_classify_http_not_found_error(self) -> None:
        http_err = HttpNotFoundError("Not Found")
        result = classify_http_error("slack", "get_channel", http_err)
        assert isinstance(result, IntegrationNotFoundError)

    def test_classify_http_rate_limit_error(self) -> None:
        http_err = HttpRateLimitError("Too Many Requests")
        result = classify_http_error("github", "list_repos", http_err)
        assert isinstance(result, IntegrationRateLimitError)

    def test_classify_http_timeout_error(self) -> None:
        http_err = HttpTimeoutError("Connection timed out")
        result = classify_http_error("slack", "post_message", http_err)
        assert isinstance(result, IntegrationTimeoutError)

    def test_classify_http_connection_error(self) -> None:
        http_err = HttpConnectionError("DNS resolution failed")
        result = classify_http_error("jira", "get_issue", http_err)
        assert isinstance(result, IntegrationConnectionError)

    def test_classify_http_bad_request_error(self) -> None:
        http_err = HttpClientBadRequestError("Bad Request")
        result = classify_http_error("stripe", "create", http_err)
        assert isinstance(result, IntegrationValidationError)

    def test_classify_http_server_error(self) -> None:
        http_err = HttpServerError("Internal Server Error")
        result = classify_http_error("hubspot", "sync", http_err)
        assert isinstance(result, IntegrationServerError)

    def test_classify_http_circuit_open_error(self) -> None:
        http_err = HttpCircuitOpenError("Circuit open for stripe")
        result = classify_http_error("stripe", "charge", http_err)
        assert isinstance(result, IntegrationUnavailableError)

    def test_classify_unknown_http_error_returns_base(self) -> None:
        http_err = HttpClientError("I'm a teapot")
        result = classify_http_error("test", "test_op", http_err)
        assert type(result) is IntegrationError

    def test_retryable_errors(self) -> None:
        retryable = [
            IntegrationTimeoutError("t", provider_name="p"),
            IntegrationConnectionError("c", provider_name="p"),
            IntegrationServerError("s", provider_name="p"),
            IntegrationRateLimitError("r", provider_name="p"),
            IntegrationUnavailableError("u", provider_name="p"),
        ]
        for error in retryable:
            assert is_retryable_integration_error(error), f"{type(error).__name__} should be retryable"

    def test_non_retryable_errors(self) -> None:
        non_retryable = [
            IntegrationAuthError("a", provider_name="p"),
            IntegrationNotFoundError("n", provider_name="p"),
            IntegrationValidationError("v", provider_name="p"),
            IntegrationConfigError("c", provider_name="p"),
        ]
        for error in non_retryable:
            assert not is_retryable_integration_error(error), f"{type(error).__name__} should NOT be retryable"


# ===================================================================
# Result models
# ===================================================================
class TestIntegrationResult:
    """Verify result model semantics and convenience methods."""

    def test_ok_result(self) -> None:
        result = IntegrationResult.ok(
            data={"id": "cust_123"},
            provider="stripe",
            operation="get_customer",
            duration_ms=100.5,
        )
        assert result.success is True
        assert result.data == {"id": "cust_123"}
        assert result.error is None
        assert result.provider == "stripe"
        assert result.operation == "get_customer"
        assert result.duration_ms == 100.5
        assert result.is_retryable is False

    def test_fail_result(self) -> None:
        error = IntegrationServerError("500 error", provider_name="slack", operation="post")
        result: IntegrationResult[dict[str, Any]] = IntegrationResult.fail(error=error)
        assert result.success is False
        assert result.data is None
        assert result.error is error
        assert result.provider == "slack"
        assert result.is_retryable is True

    def test_fail_result_non_retryable(self) -> None:
        error = IntegrationAuthError("401", provider_name="github")
        result: IntegrationResult[dict[str, Any]] = IntegrationResult.fail(error=error)
        assert result.is_retryable is False

    def test_paginated_result(self) -> None:
        result = PaginatedIntegrationResult.ok(
            data=[{"id": 1}, {"id": 2}],
            provider="slack",
            operation="list_channels",
            cursor="abc123",
            has_more=True,
            total_count=50,
        )
        assert result.success is True
        assert result.cursor == "abc123"
        assert result.has_more is True
        assert result.total_count == 50

    def test_bulk_result_tracking(self) -> None:
        result = BulkIntegrationResult(
            succeeded=[{"id": 1}, {"id": 2}],
            failed=[
                IntegrationResult.fail(
                    error=IntegrationValidationError("bad data", provider_name="crm"),
                ),
            ],
            total=3,
        )
        assert result.success_count == 2
        assert result.failure_count == 1
        assert result.partial_success is True


# ===================================================================
# Integration settings and registry
# ===================================================================
class TestIntegrationSettings:
    """Verify settings model, factory, and registry."""

    def test_settings_basic_creation(self) -> None:
        settings = IntegrationSettings(
            provider_name="stripe",
            base_url="https://api.stripe.com",
        )
        assert settings.provider_name == "stripe"
        assert settings.mode == IntegrationMode.SANDBOX
        assert settings.enabled is True
        assert settings.timeout_seconds == 30.0
        assert settings.max_retries == 3

    def test_effective_base_url_sandbox_with_sandbox_url(self) -> None:
        settings = IntegrationSettings(
            provider_name="stripe",
            base_url="https://api.stripe.com",
            sandbox_base_url="https://api.stripe.com/test",
            mode=IntegrationMode.SANDBOX,
        )
        assert settings.effective_base_url() == "https://api.stripe.com/test"

    def test_effective_base_url_production(self) -> None:
        settings = IntegrationSettings(
            provider_name="stripe",
            base_url="https://api.stripe.com",
            sandbox_base_url="https://api.stripe.com/test",
            mode=IntegrationMode.PRODUCTION,
        )
        assert settings.effective_base_url() == "https://api.stripe.com"

    def test_validate_for_production_requires_api_key(self) -> None:
        settings = IntegrationSettings(
            provider_name="stripe",
            base_url="https://api.stripe.com",
            mode=IntegrationMode.PRODUCTION,
        )
        with pytest.raises(IntegrationProductionValidationError):
            settings.validate_for_production()

    def test_validate_for_production_rejects_sandbox_url(self) -> None:
        settings = IntegrationSettings(
            provider_name="stripe",
            base_url="https://sandbox.api.stripe.com",
            mode=IntegrationMode.PRODUCTION,
            api_key="sk_live_xxx",
        )
        with pytest.raises(IntegrationProductionValidationError):
            settings.validate_for_production()

    def test_validate_for_production_passes_with_valid_config(self) -> None:
        settings = IntegrationSettings(
            provider_name="stripe",
            base_url="https://api.stripe.com",
            mode=IntegrationMode.PRODUCTION,
            api_key="sk_live_xxx",
        )
        settings.validate_for_production()

    def test_to_http_client_config(self) -> None:
        settings = IntegrationSettings(
            provider_name="test",
            base_url="https://api.test.com",
            timeout_seconds=15.0,
            max_retries=5,
        )
        config = settings.to_http_client_config()
        assert config["HTTP_CLIENT_TIMEOUT_SECONDS"] == 15.0
        assert config["HTTP_CLIENT_RETRY_MAX_ATTEMPTS"] == 5


class TestIntegrationSettingsRegistry:
    """Verify the centralized settings registry."""

    def test_register_and_get(self) -> None:
        registry = IntegrationSettingsRegistry()
        settings = IntegrationSettings(provider_name="slack", base_url="https://slack.com/api")
        registry.register(settings)
        assert registry.get("slack") is settings
        assert registry.get("nonexistent") is None
        assert "slack" in registry
        assert len(registry) == 1

    def test_get_enabled(self) -> None:
        registry = IntegrationSettingsRegistry()
        registry.register(IntegrationSettings(provider_name="a", base_url="https://a.com", enabled=True))
        registry.register(IntegrationSettings(provider_name="b", base_url="https://b.com", enabled=False))
        enabled = registry.get_enabled()
        assert len(enabled) == 1
        assert enabled[0].provider_name == "a"

    def test_validate_all_catches_production_failures(self) -> None:
        registry = IntegrationSettingsRegistry()
        registry.register(IntegrationSettings(
            provider_name="bad",
            base_url="https://api.bad.com",
            mode=IntegrationMode.PRODUCTION,
        ))
        failures = registry.validate_all()
        assert len(failures) == 1
        assert failures[0][0] == "bad"

    def test_register_rejects_empty_provider_name(self) -> None:
        registry = IntegrationSettingsRegistry()
        with pytest.raises(IntegrationConfigError):
            registry.register(IntegrationSettings(provider_name="", base_url="https://a.com"))


class TestBuildIntegrationSettings:
    """Verify the environment-based settings factory."""

    def test_build_from_defaults(self) -> None:
        settings = build_integration_settings(
            "test_provider",
            "TEST_PROVIDER",
            base_url="https://api.test.com",
        )
        assert settings.provider_name == "test_provider"
        assert settings.base_url == "https://api.test.com"
        assert settings.mode == IntegrationMode.SANDBOX

    def test_build_reads_env_vars(self) -> None:
        env = {
            "STRIPE_MODE": "production",
            "STRIPE_BASE_URL": "https://api.stripe.com",
            "STRIPE_API_KEY": "sk_live_test",
            "STRIPE_TIMEOUT_SECONDS": "15.0",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = build_integration_settings("stripe", "STRIPE")
        assert settings.mode == IntegrationMode.PRODUCTION
        assert settings.api_key == "sk_live_test"
        assert settings.timeout_seconds == 15.0

    def test_build_requires_base_url(self) -> None:
        with pytest.raises(IntegrationConfigError, match="base_url is required"):
            build_integration_settings("test", "TEST")


# ===================================================================
# Sandbox and dry-run patterns
# ===================================================================
class TestDryRunMixin:
    """Verify dry-run mode behavior."""

    def test_should_execute_returns_false_in_dry_run(self) -> None:
        class TestClient(DryRunMixin):
            settings = IntegrationSettings(
                provider_name="test",
                base_url="https://test.com",
                mode=IntegrationMode.DRY_RUN,
            )

        client = TestClient()
        assert client._should_execute() is False

    def test_should_execute_returns_true_in_production(self) -> None:
        class TestClient(DryRunMixin):
            settings = IntegrationSettings(
                provider_name="test",
                base_url="https://test.com",
                mode=IntegrationMode.PRODUCTION,
            )

        client = TestClient()
        assert client._should_execute() is True

    def test_should_execute_returns_true_in_sandbox(self) -> None:
        class TestClient(DryRunMixin):
            settings = IntegrationSettings(
                provider_name="test",
                base_url="https://test.com",
                mode=IntegrationMode.SANDBOX,
            )

        client = TestClient()
        assert client._should_execute() is True


# ===================================================================
# Secret management
# ===================================================================
class TestSecretProvider:
    """Verify secret storage and credential health patterns."""

    @pytest.mark.asyncio
    async def test_environment_secret_provider_reads_env(self) -> None:
        with patch.dict(os.environ, {"TEST_SECRET": "my_value"}, clear=False):
            provider = EnvironmentSecretProvider()
            value = await provider.get_secret("TEST_SECRET")
            assert value == "my_value"

    @pytest.mark.asyncio
    async def test_environment_secret_provider_returns_none_for_missing(self) -> None:
        provider = EnvironmentSecretProvider()
        value = await provider.get_secret("DEFINITELY_NOT_SET_XYZ_123")
        assert value is None

    @pytest.mark.asyncio
    async def test_environment_secret_provider_rotation_raises(self) -> None:
        provider = EnvironmentSecretProvider()
        with pytest.raises(NotImplementedError, match="does not support rotation"):
            await provider.rotate_secret("KEY", "new_value")

    def test_secret_rotation_policy_defaults(self) -> None:
        policy = SecretRotationPolicy()
        assert policy.rotation_interval_days == 90
        assert policy.warn_before_expiry_days == 14
        assert policy.require_rotation is False


class TestCredentialHealth:
    """Verify credential health checking logic."""

    def test_healthy_credential(self) -> None:
        status = CredentialStatus(
            provider_name="stripe",
            credential_key="STRIPE_API_KEY",
            is_valid=True,
            expires_at=datetime.now(UTC) + timedelta(days=30),
            days_until_expiry=30,
            needs_rotation=False,
            last_rotated_at=datetime.now(UTC) - timedelta(days=10),
        )
        policy = SecretRotationPolicy()
        healthy, reason = check_credential_health(status, policy)
        assert healthy is True
        assert reason == ""

    def test_expired_credential(self) -> None:
        status = CredentialStatus(
            provider_name="stripe",
            credential_key="STRIPE_API_KEY",
            is_valid=True,
            expires_at=datetime.now(UTC) - timedelta(days=5),
            days_until_expiry=-5,
            needs_rotation=True,
            last_rotated_at=None,
        )
        policy = SecretRotationPolicy()
        healthy, reason = check_credential_health(status, policy)
        assert healthy is False
        assert "expired" in reason.lower()

    def test_invalid_credential(self) -> None:
        status = CredentialStatus(
            provider_name="slack",
            credential_key="SLACK_TOKEN",
            is_valid=False,
            expires_at=None,
            days_until_expiry=None,
            needs_rotation=True,
            last_rotated_at=None,
        )
        policy = SecretRotationPolicy()
        healthy, reason = check_credential_health(status, policy)
        assert healthy is False
        assert "not valid" in reason.lower()

    def test_expiring_soon_credential(self) -> None:
        status = CredentialStatus(
            provider_name="github",
            credential_key="GITHUB_TOKEN",
            is_valid=True,
            expires_at=datetime.now(UTC) + timedelta(days=5),
            days_until_expiry=5,
            needs_rotation=False,
            last_rotated_at=datetime.now(UTC) - timedelta(days=85),
        )
        policy = SecretRotationPolicy(warn_before_expiry_days=14)
        healthy, reason = check_credential_health(status, policy)
        assert healthy is False
        assert "expiring" in reason.lower()

    def test_forced_rotation_required(self) -> None:
        status = CredentialStatus(
            provider_name="test",
            credential_key="TEST_KEY",
            is_valid=True,
            expires_at=datetime.now(UTC) + timedelta(days=30),
            days_until_expiry=30,
            needs_rotation=True,
            last_rotated_at=None,
        )
        policy = SecretRotationPolicy(require_rotation=True)
        healthy, reason = check_credential_health(status, policy)
        assert healthy is False
        assert "rotation required" in reason.lower()


# ===================================================================
# Sync checkpoint and cursor patterns
# ===================================================================
class TestSyncCursor:
    """Verify cursor serialization and deserialization."""

    def test_cursor_based_roundtrip(self) -> None:
        cursor = SyncCursor(cursor_value="abc123")
        state = cursor.to_cursor_state()
        restored = SyncCursor.from_cursor_state(state)
        assert restored.cursor_value == "abc123"

    def test_timestamp_based_roundtrip(self) -> None:
        ts = datetime(2024, 1, 15, 10, 30, tzinfo=UTC)
        cursor = SyncCursor(last_modified_at=ts)
        state = cursor.to_cursor_state()
        restored = SyncCursor.from_cursor_state(state)
        assert restored.last_modified_at == ts

    def test_offset_based_roundtrip(self) -> None:
        cursor = SyncCursor(page_number=5)
        state = cursor.to_cursor_state()
        restored = SyncCursor.from_cursor_state(state)
        assert restored.page_number == 5

    def test_high_water_mark_roundtrip(self) -> None:
        cursor = SyncCursor(high_water_mark="id_999")
        state = cursor.to_cursor_state()
        restored = SyncCursor.from_cursor_state(state)
        assert restored.high_water_mark == "id_999"

    def test_extra_metadata_roundtrip(self) -> None:
        cursor = SyncCursor(cursor_value="x", extra={"include_deleted": True})
        state = cursor.to_cursor_state()
        restored = SyncCursor.from_cursor_state(state)
        assert restored.extra == {"include_deleted": True}

    def test_none_state_returns_empty_cursor(self) -> None:
        cursor = SyncCursor.from_cursor_state(None)
        assert cursor.cursor_value is None
        assert cursor.page_number is None
        assert cursor.last_modified_at is None

    def test_empty_dict_returns_empty_cursor(self) -> None:
        cursor = SyncCursor.from_cursor_state({})
        assert cursor.cursor_value is None

    def test_empty_cursor_serializes_to_empty_dict(self) -> None:
        cursor = SyncCursor()
        assert cursor.to_cursor_state() == {}


class TestSyncStrategy:
    """Verify sync strategy enum values."""

    def test_strategy_values(self) -> None:
        assert SyncStrategy.CURSOR_BASED == "cursor_based"
        assert SyncStrategy.TIMESTAMP_BASED == "timestamp_based"
        assert SyncStrategy.OFFSET_BASED == "offset_based"
        assert SyncStrategy.FULL_SYNC == "full_sync"


class TestSyncPage:
    """Verify sync page dataclass."""

    def test_page_fields(self) -> None:
        page: SyncPage[dict[str, str]] = SyncPage(
            items=[{"id": "1"}, {"id": "2"}],
            next_cursor=SyncCursor(cursor_value="next_abc"),
            has_more=True,
            total_count=100,
            fetched_at=datetime.now(UTC),
        )
        assert len(page.items) == 2
        assert page.has_more is True
        assert page.total_count == 100
        assert page.next_cursor is not None
        assert page.next_cursor.cursor_value == "next_abc"


class TestSyncProgress:
    """Verify sync progress tracking."""

    def test_progress_elapsed_seconds(self) -> None:
        progress = SyncProgress(
            provider_name="slack",
            sync_scope="channels",
            strategy=SyncStrategy.CURSOR_BASED,
            pages_fetched=5,
            items_processed=500,
            started_at=datetime.now(UTC) - timedelta(seconds=10),
            current_cursor=None,
            is_complete=True,
        )
        assert progress.elapsed_seconds >= 10
        assert progress.items_per_second > 0

    def test_progress_items_per_second_zero_elapsed(self) -> None:
        progress = SyncProgress(
            provider_name="test",
            sync_scope="data",
            strategy=SyncStrategy.FULL_SYNC,
            pages_fetched=0,
            items_processed=0,
            started_at=datetime.now(UTC),
            current_cursor=None,
            is_complete=False,
        )
        assert progress.items_per_second == 0.0


# ===================================================================
# BaseIntegrationClient
# ===================================================================
class TestBaseIntegrationClient:
    """Verify the abstract base client contract."""

    def test_client_properties(self) -> None:
        http_client = AsyncMock()
        client = BaseIntegrationClient(
            http_client=http_client,
            provider_name="test",
            mode=IntegrationMode.SANDBOX,
        )
        assert client.provider_name == "test"
        assert client.mode == IntegrationMode.SANDBOX
        assert client.http_client is http_client

    @pytest.mark.asyncio
    async def test_health_check_no_url_returns_healthy(self) -> None:
        http_client = AsyncMock()
        client = BaseIntegrationClient(
            http_client=http_client,
            provider_name="test",
        )
        status = await client.health_check()
        assert status.healthy is True
        assert status.provider == "test"
        assert "No health check configured" in (status.detail or "")

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        http_client = AsyncMock()
        async with BaseIntegrationClient(
            http_client=http_client,
            provider_name="test",
        ) as client:
            assert client.provider_name == "test"
        http_client.close.assert_awaited_once()

    def test_health_status_defaults(self) -> None:
        status = IntegrationHealthStatus(
            healthy=True,
            provider="test",
        )
        assert status.healthy is True
        assert status.provider == "test"
        assert status.checked_at is not None


# ===================================================================
# Backward compatibility shim
# ===================================================================
class TestExceptionsBackwardCompatibility:
    """Verify exceptions.py shim re-exports from errors.py."""

    def test_exceptions_shim_matches_errors(self) -> None:
        from src.app.integrations.contracts.errors import (
            IntegrationConfigError as ErrorsConfig,
        )
        from src.app.integrations.contracts.errors import (
            IntegrationError as ErrorsBase,
        )
        from src.app.integrations.contracts.exceptions import (
            IntegrationConfigError as ExceptionsConfig,
        )
        from src.app.integrations.contracts.exceptions import (
            IntegrationError as ExceptionsBase,
        )

        assert ErrorsBase is ExceptionsBase
        assert ErrorsConfig is ExceptionsConfig
