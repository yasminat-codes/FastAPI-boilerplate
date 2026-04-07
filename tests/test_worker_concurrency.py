"""Tests for the queue concurrency profile module."""

from __future__ import annotations

import pytest

from src.app.core.worker.concurrency import (
    ALL_PROFILES,
    PROFILE_DEFAULT,
    PROFILE_EMAIL,
    PROFILE_INTEGRATION_SYNC,
    PROFILE_REPORTS,
    PROFILE_SCHEDULED,
    PROFILE_WEBHOOK_INGEST,
    QueueConcurrencyProfile,
)


class TestQueueConcurrencyProfile:
    """Tests for QueueConcurrencyProfile dataclass."""

    def test_valid_profile(self) -> None:
        profile = QueueConcurrencyProfile(name="test", max_jobs=5, description="Test profile")
        assert profile.name == "test"
        assert profile.max_jobs == 5
        assert profile.job_timeout_seconds is None

    def test_profile_with_timeout(self) -> None:
        profile = QueueConcurrencyProfile(
            name="test", max_jobs=5, description="Test", job_timeout_seconds=60.0
        )
        assert profile.job_timeout_seconds == 60.0

    def test_zero_max_jobs_raises(self) -> None:
        with pytest.raises(ValueError, match="max_jobs must be at least 1"):
            QueueConcurrencyProfile(name="bad", max_jobs=0, description="Bad")

    def test_negative_max_jobs_raises(self) -> None:
        with pytest.raises(ValueError, match="max_jobs must be at least 1"):
            QueueConcurrencyProfile(name="bad", max_jobs=-1, description="Bad")

    def test_zero_timeout_raises(self) -> None:
        with pytest.raises(ValueError, match="job_timeout_seconds must be positive"):
            QueueConcurrencyProfile(
                name="bad", max_jobs=5, description="Bad", job_timeout_seconds=0
            )

    def test_negative_timeout_raises(self) -> None:
        with pytest.raises(ValueError, match="job_timeout_seconds must be positive"):
            QueueConcurrencyProfile(
                name="bad", max_jobs=5, description="Bad", job_timeout_seconds=-10
            )

    def test_frozen(self) -> None:
        profile = QueueConcurrencyProfile(name="test", max_jobs=5, description="Test")
        with pytest.raises(AttributeError):
            profile.max_jobs = 10  # type: ignore[misc]


class TestPrebuiltProfiles:
    """Tests for the pre-built concurrency profiles."""

    def test_default_profile(self) -> None:
        assert PROFILE_DEFAULT.name == "default"
        assert PROFILE_DEFAULT.max_jobs == 10

    def test_webhook_ingest_profile(self) -> None:
        assert PROFILE_WEBHOOK_INGEST.name == "webhook-ingest"
        assert PROFILE_WEBHOOK_INGEST.max_jobs == 25

    def test_email_profile(self) -> None:
        assert PROFILE_EMAIL.name == "email"
        assert PROFILE_EMAIL.max_jobs == 15

    def test_integration_sync_profile(self) -> None:
        assert PROFILE_INTEGRATION_SYNC.name == "integration-sync"
        assert PROFILE_INTEGRATION_SYNC.max_jobs == 10

    def test_reports_profile(self) -> None:
        assert PROFILE_REPORTS.name == "reports"
        assert PROFILE_REPORTS.max_jobs == 3

    def test_scheduled_profile(self) -> None:
        assert PROFILE_SCHEDULED.name == "scheduled"
        assert PROFILE_SCHEDULED.max_jobs == 5

    def test_all_profiles_tuple(self) -> None:
        assert len(ALL_PROFILES) == 6
        names = {p.name for p in ALL_PROFILES}
        assert names == {"default", "webhook-ingest", "email", "integration-sync", "reports", "scheduled"}

    def test_all_profiles_have_positive_max_jobs(self) -> None:
        for profile in ALL_PROFILES:
            assert profile.max_jobs >= 1, f"Profile {profile.name} has invalid max_jobs"

    def test_all_profiles_have_descriptions(self) -> None:
        for profile in ALL_PROFILES:
            assert profile.description, f"Profile {profile.name} is missing description"

    def test_all_profiles_have_timeouts(self) -> None:
        for profile in ALL_PROFILES:
            assert profile.job_timeout_seconds is not None and profile.job_timeout_seconds > 0, (
                f"Profile {profile.name} is missing job_timeout_seconds"
            )
