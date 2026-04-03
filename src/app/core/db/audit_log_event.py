from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class AuditLogEventStatus(StrEnum):
    RECORDED = "recorded"
    ENQUEUED = "enqueued"
    PROCESSED = "processed"
    FAILED = "failed"
    ARCHIVED = "archived"


class AuditLogEventSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditLogEvent(Base):
    __tablename__ = "audit_log_event"
    __table_args__ = (
        Index("ix_audit_log_event_actor_type_actor_reference", "actor_type", "actor_reference"),
        Index("ix_audit_log_event_category_occurred_at", "category", "occurred_at"),
        Index("ix_audit_log_event_correlation_id", "correlation_id"),
        Index("ix_audit_log_event_event_source_event_type", "event_source", "event_type"),
        Index("ix_audit_log_event_retention_expires_at", "retention_expires_at"),
        Index("ix_audit_log_event_status_occurred_at", "status", "occurred_at"),
        Index("ix_audit_log_event_subject_type_subject_reference", "subject_type", "subject_reference"),
    )

    id: Mapped[int] = mapped_column("id", Integer, autoincrement=True, nullable=False, primary_key=True, init=False)
    event_source: Mapped[str] = mapped_column(String(100), index=True)
    event_type: Mapped[str] = mapped_column(String(150), index=True)
    severity: Mapped[str] = mapped_column(String(16), default=AuditLogEventSeverity.INFO.value, index=True)
    category: Mapped[str | None] = mapped_column(String(100), default=None, index=True)
    status: Mapped[str] = mapped_column(String(32), default=AuditLogEventStatus.RECORDED.value, index=True)
    actor_type: Mapped[str | None] = mapped_column(String(100), default=None, index=True)
    actor_reference: Mapped[str | None] = mapped_column(String(255), default=None)
    subject_type: Mapped[str | None] = mapped_column(String(100), default=None, index=True)
    subject_reference: Mapped[str | None] = mapped_column(String(255), default=None)
    correlation_id: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    request_id: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    event_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    event_context: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    outcome_code: Mapped[str | None] = mapped_column(String(100), default=None)
    error_detail: Mapped[str | None] = mapped_column(Text, default=None)
