from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class IdempotencyKeyStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class IdempotencyKey(Base):
    __tablename__ = "idempotency_key"
    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_idempotency_key_scope_key"),
        Index("ix_idempotency_key_scope_request_fingerprint", "scope", "request_fingerprint"),
        Index("ix_idempotency_key_status_locked_until", "status", "locked_until"),
    )

    id: Mapped[int] = mapped_column("id", Integer, autoincrement=True, nullable=False, primary_key=True, init=False)
    scope: Mapped[str] = mapped_column(String(100), index=True)
    key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default=IdempotencyKeyStatus.RECEIVED.value, index=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), default=None)
    recovery_point: Mapped[str | None] = mapped_column(String(100), default=None)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    hit_count: Mapped[int] = mapped_column(Integer, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    processing_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    error_code: Mapped[str | None] = mapped_column(String(100), default=None)
    error_detail: Mapped[str | None] = mapped_column(Text, default=None)
