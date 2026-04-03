"""Add idempotency key table pattern

Revision ID: 6c15e4b5d0d2
Revises: f6edf4a3a0b1
Create Date: 2026-04-03 14:10:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6c15e4b5d0d2"
down_revision: Union[str, None] = "f6edf4a3a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "idempotency_key",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scope", sa.String(length=100), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("recovery_point", sa.String(length=100), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_metadata", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "key", name="uq_idempotency_key_scope_key"),
    )
    op.create_index(op.f("ix_idempotency_key_expires_at"), "idempotency_key", ["expires_at"], unique=False)
    op.create_index(op.f("ix_idempotency_key_scope"), "idempotency_key", ["scope"], unique=False)
    op.create_index(
        "ix_idempotency_key_scope_request_fingerprint",
        "idempotency_key",
        ["scope", "request_fingerprint"],
        unique=False,
    )
    op.create_index(op.f("ix_idempotency_key_status"), "idempotency_key", ["status"], unique=False)
    op.create_index(
        "ix_idempotency_key_status_locked_until",
        "idempotency_key",
        ["status", "locked_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_key_status_locked_until", table_name="idempotency_key")
    op.drop_index(op.f("ix_idempotency_key_status"), table_name="idempotency_key")
    op.drop_index("ix_idempotency_key_scope_request_fingerprint", table_name="idempotency_key")
    op.drop_index(op.f("ix_idempotency_key_scope"), table_name="idempotency_key")
    op.drop_index(op.f("ix_idempotency_key_expires_at"), table_name="idempotency_key")
    op.drop_table("idempotency_key")
