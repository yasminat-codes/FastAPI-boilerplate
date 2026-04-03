from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class IntegrationSyncCheckpointStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    IDLE = "idle"
    FAILED = "failed"
    PAUSED = "paused"
    COMPLETED = "completed"


class IntegrationSyncCheckpoint(Base):
    __tablename__ = "integration_sync_checkpoint"
    __table_args__ = (
        UniqueConstraint(
            "integration_name",
            "sync_scope",
            "checkpoint_key",
            name="uq_integration_sync_checkpoint_scope_key",
        ),
        Index(
            "ix_integration_sync_checkpoint_integration_name_sync_scope",
            "integration_name",
            "sync_scope",
        ),
        Index(
            "ix_integration_sync_checkpoint_status_next_sync_after",
            "status",
            "next_sync_after",
        ),
        Index(
            "ix_integration_sync_checkpoint_status_last_transition_at",
            "status",
            "last_transition_at",
        ),
        Index(
            "ix_integration_sync_checkpoint_sync_scope_last_synced_at",
            "sync_scope",
            "last_synced_at",
        ),
        Index("ix_integration_sync_checkpoint_lease_expires_at", "lease_expires_at"),
    )

    id: Mapped[int] = mapped_column("id", Integer, autoincrement=True, nullable=False, primary_key=True, init=False)
    integration_name: Mapped[str] = mapped_column(String(100), index=True)
    sync_scope: Mapped[str] = mapped_column(String(150), index=True)
    checkpoint_key: Mapped[str] = mapped_column(String(255), default="default")
    status: Mapped[str] = mapped_column(String(32), default=IntegrationSyncCheckpointStatus.PENDING.value, index=True)
    cursor_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    checkpoint_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    lease_owner: Mapped[str | None] = mapped_column(String(255), default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    next_sync_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    cursor_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_transition_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=lambda: datetime.now(UTC),
    )
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100), default=None)
    error_detail: Mapped[str | None] = mapped_column(Text, default=None)
