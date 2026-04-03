from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class JobStateHistoryStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    DEAD_LETTERED = "dead_lettered"
    EXPIRED = "expired"


class JobStateHistory(Base):
    __tablename__ = "job_state_history"
    __table_args__ = (
        Index("ix_job_state_history_correlation_id", "correlation_id"),
        Index("ix_job_state_history_job_name", "job_name"),
        Index("ix_job_state_history_job_name_run_key", "job_name", "run_key"),
        Index("ix_job_state_history_last_transition_at", "last_transition_at"),
        Index("ix_job_state_history_queue_name", "queue_name"),
        Index("ix_job_state_history_queue_name_queue_job_id", "queue_name", "queue_job_id"),
        Index("ix_job_state_history_status_last_transition_at", "status", "last_transition_at"),
        Index("ix_job_state_history_status_scheduled_at", "status", "scheduled_at"),
        Index("ix_job_state_history_trigger_source", "trigger_source"),
        Index("ix_job_state_history_trigger_source_reference", "trigger_source", "trigger_reference"),
    )

    id: Mapped[int] = mapped_column("id", Integer, autoincrement=True, nullable=False, primary_key=True, init=False)
    job_name: Mapped[str] = mapped_column(String(150))
    queue_name: Mapped[str] = mapped_column(String(100))
    job_version: Mapped[str | None] = mapped_column(String(50), default=None)
    queue_backend: Mapped[str | None] = mapped_column(String(50), default=None)
    queue_job_id: Mapped[str | None] = mapped_column(String(255), default=None)
    worker_name: Mapped[str | None] = mapped_column(String(150), default=None)
    worker_version: Mapped[str | None] = mapped_column(String(50), default=None)
    trigger_source: Mapped[str | None] = mapped_column(String(100), default=None)
    trigger_reference: Mapped[str | None] = mapped_column(String(255), default=None)
    run_key: Mapped[str | None] = mapped_column(String(255), default=None)
    correlation_id: Mapped[str | None] = mapped_column(String(255), default=None)
    status: Mapped[str] = mapped_column(String(32), default=JobStateHistoryStatus.PENDING.value, index=True)
    current_step: Mapped[str | None] = mapped_column(String(150), default=None)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int | None] = mapped_column(Integer, default=None)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_transition_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=lambda: datetime.now(UTC),
    )
    input_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    execution_context: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    status_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    error_code: Mapped[str | None] = mapped_column(String(100), default=None)
    error_detail: Mapped[str | None] = mapped_column(Text, default=None)
