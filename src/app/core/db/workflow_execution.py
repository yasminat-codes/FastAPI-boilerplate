from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class WorkflowExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class WorkflowExecution(Base):
    __tablename__ = "workflow_execution"
    __table_args__ = (
        Index("ix_workflow_execution_status_last_transition_at", "status", "last_transition_at"),
        Index("ix_workflow_execution_status_scheduled_at", "status", "scheduled_at"),
        Index("ix_workflow_execution_trigger_source_reference", "trigger_source", "trigger_reference"),
        Index("ix_workflow_execution_workflow_name_run_key", "workflow_name", "run_key"),
    )

    id: Mapped[int] = mapped_column("id", Integer, autoincrement=True, nullable=False, primary_key=True, init=False)
    workflow_name: Mapped[str] = mapped_column(String(150), index=True)
    trigger_source: Mapped[str] = mapped_column(String(100), index=True)
    workflow_version: Mapped[str | None] = mapped_column(String(50), default=None)
    status: Mapped[str] = mapped_column(String(32), default=WorkflowExecutionStatus.PENDING.value, index=True)
    trigger_reference: Mapped[str | None] = mapped_column(String(255), default=None)
    run_key: Mapped[str | None] = mapped_column(String(255), default=None)
    correlation_id: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    current_step: Mapped[str | None] = mapped_column(String(150), default=None)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int | None] = mapped_column(Integer, default=None)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
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
