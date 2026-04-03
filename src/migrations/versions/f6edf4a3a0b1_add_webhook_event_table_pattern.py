"""Add webhook event table pattern

Revision ID: f6edf4a3a0b1
Revises: d3c5b39ad89f
Create Date: 2026-04-03 12:45:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6edf4a3a0b1"
down_revision: Union[str, None] = "d3c5b39ad89f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("endpoint_key", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("delivery_id", sa.String(length=255), nullable=True),
        sa.Column("event_id", sa.String(length=255), nullable=True),
        sa.Column("signature_verified", sa.Boolean(), nullable=True),
        sa.Column("payload_content_type", sa.String(length=255), nullable=True),
        sa.Column("payload_sha256", sa.String(length=64), nullable=True),
        sa.Column("payload_size_bytes", sa.Integer(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("normalized_payload", sa.JSON(), nullable=True),
        sa.Column("processing_metadata", sa.JSON(), nullable=True),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_webhook_event_endpoint_key"), "webhook_event", ["endpoint_key"], unique=False)
    op.create_index(op.f("ix_webhook_event_event_type"), "webhook_event", ["event_type"], unique=False)
    op.create_index(op.f("ix_webhook_event_payload_sha256"), "webhook_event", ["payload_sha256"], unique=False)
    op.create_index(op.f("ix_webhook_event_source"), "webhook_event", ["source"], unique=False)
    op.create_index("ix_webhook_event_source_delivery_id", "webhook_event", ["source", "delivery_id"], unique=False)
    op.create_index("ix_webhook_event_source_event_id", "webhook_event", ["source", "event_id"], unique=False)
    op.create_index(op.f("ix_webhook_event_status"), "webhook_event", ["status"], unique=False)
    op.create_index("ix_webhook_event_status_received_at", "webhook_event", ["status", "received_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_webhook_event_status_received_at", table_name="webhook_event")
    op.drop_index(op.f("ix_webhook_event_status"), table_name="webhook_event")
    op.drop_index("ix_webhook_event_source_event_id", table_name="webhook_event")
    op.drop_index("ix_webhook_event_source_delivery_id", table_name="webhook_event")
    op.drop_index(op.f("ix_webhook_event_source"), table_name="webhook_event")
    op.drop_index(op.f("ix_webhook_event_payload_sha256"), table_name="webhook_event")
    op.drop_index(op.f("ix_webhook_event_event_type"), table_name="webhook_event")
    op.drop_index(op.f("ix_webhook_event_endpoint_key"), table_name="webhook_event")
    op.drop_table("webhook_event")
