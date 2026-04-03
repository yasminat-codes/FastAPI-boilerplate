from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class DeadLetterRecordStatus(StrEnum):
    PENDING = "pending"
    RETRYING = "retrying"
    DEAD_LETTERED = "dead_lettered"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class DeadLetterRecord(Base):
    __tablename__ = "dead_letter_record"
    __table_args__ = (
        UniqueConstraint("dead_letter_namespace", "dead_letter_key", name="uq_dead_letter_record_namespace_key"),
        Index("ix_dead_letter_record_correlation_id", "correlation_id"),
        Index("ix_dead_letter_record_dead_letter_namespace", "dead_letter_namespace"),
        Index("ix_dead_letter_record_dead_letter_namespace_message_type", "dead_letter_namespace", "message_type"),
        Index("ix_dead_letter_record_dead_lettered_at", "dead_lettered_at"),
        Index("ix_dead_letter_record_failure_category_dead_lettered_at", "failure_category", "dead_lettered_at"),
        Index("ix_dead_letter_record_source_system_source_reference", "source_system", "source_reference"),
        Index("ix_dead_letter_record_status_next_retry_at", "status", "next_retry_at"),
        Index("ix_dead_letter_record_status", "status"),
    )

    id: Mapped[int] = mapped_column("id", Integer, autoincrement=True, nullable=False, primary_key=True, init=False)
    dead_letter_namespace: Mapped[str] = mapped_column(String(150), index=True)
    dead_letter_key: Mapped[str] = mapped_column(String(255))
    message_type: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(32), default=DeadLetterRecordStatus.PENDING.value, index=True)
    source_system: Mapped[str | None] = mapped_column(String(100), default=None, index=True)
    source_reference: Mapped[str | None] = mapped_column(String(255), default=None)
    correlation_id: Mapped[str | None] = mapped_column(String(255), default=None)
    failure_category: Mapped[str | None] = mapped_column(String(100), default=None)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    payload_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    failure_context: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    error_code: Mapped[str | None] = mapped_column(String(100), default=None)
    error_detail: Mapped[str | None] = mapped_column(Text, default=None)
