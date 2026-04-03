from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class WebhookEventStatus(StrEnum):
    RECEIVED = "received"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    ENQUEUED = "enqueued"
    PROCESSED = "processed"
    FAILED = "failed"


class WebhookEvent(Base):
    __tablename__ = "webhook_event"
    __table_args__ = (
        Index("ix_webhook_event_source_delivery_id", "source", "delivery_id"),
        Index("ix_webhook_event_source_event_id", "source", "event_id"),
        Index("ix_webhook_event_status_received_at", "status", "received_at"),
    )

    id: Mapped[int] = mapped_column("id", Integer, autoincrement=True, nullable=False, primary_key=True, init=False)
    source: Mapped[str] = mapped_column(String(100), index=True)
    endpoint_key: Mapped[str] = mapped_column(String(100), index=True)
    event_type: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(32), default=WebhookEventStatus.RECEIVED.value, index=True)
    delivery_id: Mapped[str | None] = mapped_column(String(255), default=None)
    event_id: Mapped[str | None] = mapped_column(String(255), default=None)
    signature_verified: Mapped[bool | None] = mapped_column(Boolean, default=None)
    payload_content_type: Mapped[str | None] = mapped_column(String(255), default=None)
    payload_sha256: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    payload_size_bytes: Mapped[int | None] = mapped_column(Integer, default=None)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    raw_payload: Mapped[str | None] = mapped_column(Text, default=None)
    normalized_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    processing_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    processing_error: Mapped[str | None] = mapped_column(Text, default=None)
