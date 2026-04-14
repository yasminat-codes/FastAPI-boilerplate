"""Comprehensive tests for the retry module.

Tests cover backoff delay calculations, backoff policies, error categorization,
and job failure alerting hooks.
"""

from unittest.mock import MagicMock

import pytest

from src.app.core.worker.retry import (
    BACKOFF_FAST,
    BACKOFF_SLOW,
    BACKOFF_STANDARD,
    NON_RETRYABLE_CATEGORIES,
    BackoffPolicy,
    JobAlertHook,
    JobFailureCategory,
    LoggingAlertHook,
    NonRetryableJobError,
    calculate_backoff_delay,
    calculate_backoff_delay_deterministic,
    is_retryable_category,
)


class TestCalculateBackoffDelay:
    """Tests for calculate_backoff_delay function with jitter."""

    def test_returns_value_in_valid_range(self) -> None:
        """Delay should be between 0 and capped exponential delay."""
        base_delay = 1.0
        attempt = 2
        max_delay = 100.0

        # Run multiple times to check jitter variability
        delays = [calculate_backoff_delay(base_delay, attempt, max_delay) for _ in range(100)]

        # All delays should be within valid range
        assert all(0 <= delay <= 8.0 for delay in delays)  # 1.0 * 2^2 = 4.0

    def test_respects_max_delay_cap(self) -> None:
        """Delay should never exceed max_delay."""
        base_delay = 1.0
        attempt = 10
        max_delay = 30.0

        delays = [calculate_backoff_delay(base_delay, attempt, max_delay) for _ in range(100)]

        assert all(delay <= max_delay for delay in delays)

    def test_zero_base_delay_returns_zero(self) -> None:
        """With base_delay=0, should always return 0."""
        delay = calculate_backoff_delay(0.0, 0, 100.0)
        assert delay == 0.0

    def test_first_attempt_returns_value_up_to_base_delay(self) -> None:
        """Attempt 0 should return value between 0 and base_delay."""
        base_delay = 5.0
        delays = [calculate_backoff_delay(base_delay, 0, 100.0) for _ in range(100)]

        assert all(0 <= delay <= base_delay for delay in delays)

    def test_raises_on_negative_base_delay(self) -> None:
        """Should raise ValueError for negative base_delay."""
        with pytest.raises(ValueError, match="base_delay must be >= 0"):
            calculate_backoff_delay(-1.0, 0, 100.0)

    def test_raises_on_negative_attempt(self) -> None:
        """Should raise ValueError for negative attempt."""
        with pytest.raises(ValueError, match="attempt must be >= 0"):
            calculate_backoff_delay(1.0, -1, 100.0)

    def test_raises_on_max_delay_less_than_base_delay(self) -> None:
        """Should raise ValueError when max_delay < base_delay."""
        with pytest.raises(ValueError, match="max_delay.*must be >= base_delay"):
            calculate_backoff_delay(10.0, 0, 5.0)


class TestCalculateBackoffDelayDeterministic:
    """Tests for calculate_backoff_delay_deterministic function."""

    def test_returns_exact_expected_values(self) -> None:
        """Should return base * 2^attempt, capped at max."""
        assert calculate_backoff_delay_deterministic(1.0, 0, 100.0) == 1.0
        assert calculate_backoff_delay_deterministic(1.0, 1, 100.0) == 2.0
        assert calculate_backoff_delay_deterministic(1.0, 2, 100.0) == 4.0
        assert calculate_backoff_delay_deterministic(1.0, 3, 100.0) == 8.0
        assert calculate_backoff_delay_deterministic(1.0, 4, 100.0) == 16.0

    def test_respects_max_delay_cap(self) -> None:
        """Should cap at max_delay."""
        assert calculate_backoff_delay_deterministic(1.0, 10, 30.0) == 30.0
        assert calculate_backoff_delay_deterministic(5.0, 5, 100.0) == 100.0

    def test_zero_base_delay_returns_zero(self) -> None:
        """With base_delay=0, should always return 0."""
        assert calculate_backoff_delay_deterministic(0.0, 0, 100.0) == 0.0
        assert calculate_backoff_delay_deterministic(0.0, 5, 100.0) == 0.0

    def test_returns_float_type(self) -> None:
        """Should return float type."""
        result = calculate_backoff_delay_deterministic(1.0, 0, 100.0)
        assert isinstance(result, float)

    def test_raises_on_negative_base_delay(self) -> None:
        """Should raise ValueError for negative base_delay."""
        with pytest.raises(ValueError, match="base_delay must be >= 0"):
            calculate_backoff_delay_deterministic(-1.0, 0, 100.0)

    def test_raises_on_negative_attempt(self) -> None:
        """Should raise ValueError for negative attempt."""
        with pytest.raises(ValueError, match="attempt must be >= 0"):
            calculate_backoff_delay_deterministic(1.0, -1, 100.0)

    def test_raises_on_max_delay_less_than_base_delay(self) -> None:
        """Should raise ValueError when max_delay < base_delay."""
        with pytest.raises(ValueError, match="max_delay.*must be >= base_delay"):
            calculate_backoff_delay_deterministic(10.0, 0, 5.0)


class TestBackoffPolicy:
    """Tests for BackoffPolicy class."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        policy = BackoffPolicy()

        assert policy.base_delay_seconds == 5.0
        assert policy.max_delay_seconds == 300.0
        assert policy.multiplier == 2.0
        assert policy.jitter is True

    def test_custom_values(self) -> None:
        """Should accept custom values."""
        policy = BackoffPolicy(
            base_delay_seconds=2.0,
            max_delay_seconds=60.0,
            multiplier=3.0,
            jitter=False,
        )

        assert policy.base_delay_seconds == 2.0
        assert policy.max_delay_seconds == 60.0
        assert policy.multiplier == 3.0
        assert policy.jitter is False

    def test_frozen_dataclass(self) -> None:
        """Should be immutable after creation."""
        policy = BackoffPolicy()

        with pytest.raises(AttributeError):
            policy.base_delay_seconds = 10.0  # type: ignore

    def test_raises_on_negative_base_delay(self) -> None:
        """Should raise ValueError for negative base_delay."""
        with pytest.raises(ValueError, match="base_delay_seconds must be >= 0"):
            BackoffPolicy(base_delay_seconds=-1.0)

    def test_raises_on_negative_max_delay(self) -> None:
        """Should raise ValueError when max < base."""
        with pytest.raises(ValueError, match="max_delay_seconds.*must be >= base_delay_seconds"):
            BackoffPolicy(base_delay_seconds=10.0, max_delay_seconds=5.0)

    def test_raises_on_non_positive_multiplier(self) -> None:
        """Should raise ValueError for multiplier <= 0."""
        with pytest.raises(ValueError, match="multiplier must be > 0"):
            BackoffPolicy(multiplier=0)

        with pytest.raises(ValueError, match="multiplier must be > 0"):
            BackoffPolicy(multiplier=-1.0)

    def test_delay_for_attempt_with_jitter_in_range(self) -> None:
        """With jitter=True, delay_for_attempt should return value in range."""
        policy = BackoffPolicy(
            base_delay_seconds=1.0,
            max_delay_seconds=100.0,
            multiplier=2.0,
            jitter=True,
        )

        delays = [policy.delay_for_attempt(2) for _ in range(100)]

        # Attempt 2: 1.0 * 2^2 = 4.0
        assert all(0 <= delay <= 4.0 for delay in delays)

    def test_delay_for_attempt_deterministic(self) -> None:
        """With jitter=False, delay_for_attempt should return exact value."""
        policy = BackoffPolicy(
            base_delay_seconds=1.0,
            max_delay_seconds=100.0,
            multiplier=2.0,
            jitter=False,
        )

        assert policy.delay_for_attempt(0) == 1.0
        assert policy.delay_for_attempt(1) == 2.0
        assert policy.delay_for_attempt(2) == 4.0
        assert policy.delay_for_attempt(3) == 8.0

    def test_delay_for_attempt_respects_max_delay(self) -> None:
        """delay_for_attempt should respect max_delay cap."""
        policy = BackoffPolicy(
            base_delay_seconds=1.0,
            max_delay_seconds=10.0,
            multiplier=2.0,
            jitter=False,
        )

        # Attempt 4: 1.0 * 2^4 = 16.0, but capped at 10.0
        assert policy.delay_for_attempt(4) == 10.0

    def test_delay_for_attempt_with_custom_multiplier(self) -> None:
        """delay_for_attempt should use custom multiplier."""
        policy = BackoffPolicy(
            base_delay_seconds=2.0,
            max_delay_seconds=1000.0,
            multiplier=3.0,
            jitter=False,
        )

        assert policy.delay_for_attempt(0) == 2.0
        assert policy.delay_for_attempt(1) == 6.0  # 2 * 3^1
        assert policy.delay_for_attempt(2) == 18.0  # 2 * 3^2


class TestPredefinedPolicies:
    """Tests for predefined backoff policies."""

    def test_backoff_fast_values(self) -> None:
        """BACKOFF_FAST should have expected values."""
        assert BACKOFF_FAST.base_delay_seconds == 1.0
        assert BACKOFF_FAST.max_delay_seconds == 30.0
        assert BACKOFF_FAST.multiplier == 2.0
        assert BACKOFF_FAST.jitter is True

    def test_backoff_standard_values(self) -> None:
        """BACKOFF_STANDARD should have expected values."""
        assert BACKOFF_STANDARD.base_delay_seconds == 5.0
        assert BACKOFF_STANDARD.max_delay_seconds == 300.0
        assert BACKOFF_STANDARD.multiplier == 2.0
        assert BACKOFF_STANDARD.jitter is True

    def test_backoff_slow_values(self) -> None:
        """BACKOFF_SLOW should have expected values."""
        assert BACKOFF_SLOW.base_delay_seconds == 30.0
        assert BACKOFF_SLOW.max_delay_seconds == 1800.0
        assert BACKOFF_SLOW.multiplier == 2.0
        assert BACKOFF_SLOW.jitter is True


class TestJobFailureCategory:
    """Tests for JobFailureCategory enum."""

    def test_all_expected_members_exist(self) -> None:
        """All expected categories should exist."""
        assert JobFailureCategory.TRANSIENT == "transient"
        assert JobFailureCategory.RATE_LIMITED == "rate_limited"
        assert JobFailureCategory.INVALID_PAYLOAD == "invalid_payload"
        assert JobFailureCategory.AUTHENTICATION == "authentication"
        assert JobFailureCategory.AUTHORIZATION == "authorization"
        assert JobFailureCategory.NOT_FOUND == "not_found"
        assert JobFailureCategory.CONFLICT == "conflict"
        assert JobFailureCategory.PROVIDER_ERROR == "provider_error"
        assert JobFailureCategory.INTERNAL == "internal"
        assert JobFailureCategory.UNKNOWN == "unknown"

    def test_is_string_enum(self) -> None:
        """Should be a StrEnum with string values."""
        category = JobFailureCategory.TRANSIENT
        assert isinstance(category, str)
        assert category == "transient"


class TestNonRetryableCategories:
    """Tests for NON_RETRYABLE_CATEGORIES constant."""

    def test_contains_expected_categories(self) -> None:
        """Should contain all non-retryable categories."""
        assert JobFailureCategory.INVALID_PAYLOAD in NON_RETRYABLE_CATEGORIES
        assert JobFailureCategory.AUTHENTICATION in NON_RETRYABLE_CATEGORIES
        assert JobFailureCategory.AUTHORIZATION in NON_RETRYABLE_CATEGORIES
        assert JobFailureCategory.NOT_FOUND in NON_RETRYABLE_CATEGORIES
        assert JobFailureCategory.CONFLICT in NON_RETRYABLE_CATEGORIES

    def test_excludes_retryable_categories(self) -> None:
        """Should not contain retryable categories."""
        assert JobFailureCategory.TRANSIENT not in NON_RETRYABLE_CATEGORIES
        assert JobFailureCategory.RATE_LIMITED not in NON_RETRYABLE_CATEGORIES
        assert JobFailureCategory.PROVIDER_ERROR not in NON_RETRYABLE_CATEGORIES
        assert JobFailureCategory.INTERNAL not in NON_RETRYABLE_CATEGORIES
        assert JobFailureCategory.UNKNOWN not in NON_RETRYABLE_CATEGORIES

    def test_is_frozenset(self) -> None:
        """Should be a frozenset for immutability."""
        assert isinstance(NON_RETRYABLE_CATEGORIES, frozenset)


class TestIsRetryableCategory:
    """Tests for is_retryable_category function."""

    def test_returns_true_for_retryable_categories(self) -> None:
        """Should return True for retryable categories."""
        assert is_retryable_category(JobFailureCategory.TRANSIENT) is True
        assert is_retryable_category(JobFailureCategory.RATE_LIMITED) is True
        assert is_retryable_category(JobFailureCategory.PROVIDER_ERROR) is True
        assert is_retryable_category(JobFailureCategory.INTERNAL) is True
        assert is_retryable_category(JobFailureCategory.UNKNOWN) is True

    def test_returns_false_for_non_retryable_categories(self) -> None:
        """Should return False for non-retryable categories."""
        assert is_retryable_category(JobFailureCategory.INVALID_PAYLOAD) is False
        assert is_retryable_category(JobFailureCategory.AUTHENTICATION) is False
        assert is_retryable_category(JobFailureCategory.AUTHORIZATION) is False
        assert is_retryable_category(JobFailureCategory.NOT_FOUND) is False
        assert is_retryable_category(JobFailureCategory.CONFLICT) is False

    def test_accepts_string_categories(self) -> None:
        """Should accept string category values."""
        assert is_retryable_category("transient") is True
        assert is_retryable_category("invalid_payload") is False
        assert is_retryable_category("custom_category") is True


class TestNonRetryableJobError:
    """Tests for NonRetryableJobError exception."""

    def test_stores_message(self) -> None:
        """Should store the error message."""
        msg = "Job cannot be retried"
        error = NonRetryableJobError(msg)

        assert error.message == msg
        assert str(error) == msg

    def test_stores_error_category(self) -> None:
        """Should store the error category."""
        error = NonRetryableJobError(
            "Invalid payload",
            error_category=JobFailureCategory.INVALID_PAYLOAD,
        )

        assert error.error_category == JobFailureCategory.INVALID_PAYLOAD

    def test_stores_error_code(self) -> None:
        """Should store the error code."""
        error = NonRetryableJobError(
            "Not found",
            error_category=JobFailureCategory.NOT_FOUND,
            error_code="RESOURCE_NOT_FOUND",
        )

        assert error.error_code == "RESOURCE_NOT_FOUND"

    def test_defaults_error_category_to_unknown(self) -> None:
        """Should default error_category to UNKNOWN if not provided."""
        error = NonRetryableJobError("Some error")

        assert error.error_category == JobFailureCategory.UNKNOWN

    def test_accepts_custom_category_string(self) -> None:
        """Should accept custom category strings."""
        error = NonRetryableJobError(
            "Custom error",
            error_category="custom_category",
        )

        assert error.error_category == "custom_category"

    def test_error_code_is_optional(self) -> None:
        """Should have optional error_code."""
        error = NonRetryableJobError("Error without code")

        assert error.error_code is None


class TestJobAlertHookProtocol:
    """Tests for JobAlertHook protocol."""

    def test_implements_protocol(self) -> None:
        """LoggingAlertHook should implement JobAlertHook protocol."""
        hook = LoggingAlertHook()

        assert isinstance(hook, JobAlertHook)

    def test_protocol_defines_on_job_failure(self) -> None:
        """Protocol should define on_job_failure method."""
        assert hasattr(JobAlertHook, "on_job_failure")


class TestLoggingAlertHook:
    """Tests for LoggingAlertHook class."""

    def test_accepts_optional_logger(self) -> None:
        """Should accept optional logger in constructor."""
        mock_logger = MagicMock()
        hook = LoggingAlertHook(logger=mock_logger)

        assert hook.logger is mock_logger

    def test_uses_default_logger_if_not_provided(self) -> None:
        """Should use structlog.get_logger() if not provided."""
        hook = LoggingAlertHook()

        assert hook.logger is not None

    @pytest.mark.asyncio
    async def test_on_job_failure_logs_error_for_final_attempt(self) -> None:
        """Should log error for final attempt."""
        mock_logger = MagicMock()
        hook = LoggingAlertHook(logger=mock_logger)

        await hook.on_job_failure(
            job_name="test_job",
            envelope_data={"key": "value"},
            attempt=5,
            max_attempts=5,
            error_category="transient",
            error_message="Job failed",
            is_final_attempt=True,
        )

        mock_logger.error.assert_called_once()
        call_kwargs = mock_logger.error.call_args[1]
        assert call_kwargs["job_name"] == "test_job"
        assert call_kwargs["is_final_attempt"] is True

    @pytest.mark.asyncio
    async def test_on_job_failure_logs_warning_for_non_final_attempt(self) -> None:
        """Should log warning for non-final attempt."""
        mock_logger = MagicMock()
        hook = LoggingAlertHook(logger=mock_logger)

        await hook.on_job_failure(
            job_name="test_job",
            envelope_data={"key": "value"},
            attempt=2,
            max_attempts=5,
            error_category="transient",
            error_message="Job failed",
            is_final_attempt=False,
        )

        mock_logger.warning.assert_called_once()
        call_kwargs = mock_logger.warning.call_args[1]
        assert call_kwargs["job_name"] == "test_job"
        assert call_kwargs["is_final_attempt"] is False

    @pytest.mark.asyncio
    async def test_on_job_failure_includes_all_context(self) -> None:
        """Should include all context in log call."""
        mock_logger = MagicMock()
        hook = LoggingAlertHook(logger=mock_logger)

        envelope_data = {"id": "123", "action": "process"}

        await hook.on_job_failure(
            job_name="test_job",
            envelope_data=envelope_data,
            attempt=3,
            max_attempts=5,
            error_category="rate_limited",
            error_message="Rate limit exceeded",
            is_final_attempt=False,
        )

        mock_logger.warning.assert_called_once_with(
            "job_failure",
            job_name="test_job",
            attempt=3,
            max_attempts=5,
            error_category="rate_limited",
            error_message="Rate limit exceeded",
            is_final_attempt=False,
            envelope_data=envelope_data,
        )

    @pytest.mark.asyncio
    async def test_on_job_failure_distinguishes_attempts_correctly(self) -> None:
        """Should use correct log level based on is_final_attempt."""
        mock_logger = MagicMock()
        hook = LoggingAlertHook(logger=mock_logger)

        # Not final
        await hook.on_job_failure(
            job_name="job1",
            envelope_data={},
            attempt=1,
            max_attempts=5,
            error_category="transient",
            error_message="Attempt 1",
            is_final_attempt=False,
        )

        # Final
        await hook.on_job_failure(
            job_name="job2",
            envelope_data={},
            attempt=5,
            max_attempts=5,
            error_category="transient",
            error_message="Attempt 5",
            is_final_attempt=True,
        )

        assert mock_logger.warning.call_count == 1
        assert mock_logger.error.call_count == 1


class TestExports:
    """Tests for module exports."""

    def test_all_expected_names_are_importable(self) -> None:
        """All names in __all__ should be importable."""
        from src.app.core.worker import retry

        expected_names = [
            "calculate_backoff_delay",
            "calculate_backoff_delay_deterministic",
            "BackoffPolicy",
            "BACKOFF_FAST",
            "BACKOFF_STANDARD",
            "BACKOFF_SLOW",
            "NonRetryableJobError",
            "JobFailureCategory",
            "NON_RETRYABLE_CATEGORIES",
            "is_retryable_category",
            "JobAlertHook",
            "LoggingAlertHook",
        ]

        for name in expected_names:
            assert hasattr(retry, name), f"{name} should be importable"
