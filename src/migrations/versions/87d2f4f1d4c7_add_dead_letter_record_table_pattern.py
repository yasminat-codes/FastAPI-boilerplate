"""Add dead letter record table pattern

Revision ID: 87d2f4f1d4c7
Revises: 9b4d52a6f1c3
Create Date: 2026-04-03 21:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "87d2f4f1d4c7"
down_revision: Union[str, None] = "9b4d52a6f1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dead_letter_record",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dead_letter_namespace", sa.String(length=150), nullable=False),
        sa.Column("dead_letter_key", sa.String(length=255), nullable=False),
        sa.Column("message_type", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_system", sa.String(length=100), nullable=True),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("failure_category", sa.String(length=100), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_snapshot", sa.JSON(), nullable=True),
        sa.Column("failure_context", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dead_letter_namespace", "dead_letter_key", name="uq_dead_letter_record_namespace_key"),
    )
    op.create_index(
        op.f("ix_dead_letter_record_correlation_id"),
        "dead_letter_record",
        ["correlation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dead_letter_record_dead_letter_namespace"),
        "dead_letter_record",
        ["dead_letter_namespace"],
        unique=False,
    )
    op.create_index(
        "ix_dead_letter_record_dead_letter_namespace_message_type",
        "dead_letter_record",
        ["dead_letter_namespace", "message_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dead_letter_record_message_type"),
        "dead_letter_record",
        ["message_type"],
        unique=False,
    )
    op.create_index(
        "ix_dead_letter_record_dead_lettered_at",
        "dead_letter_record",
        ["dead_lettered_at"],
        unique=False,
    )
    op.create_index(
        "ix_dead_letter_record_failure_category_dead_lettered_at",
        "dead_letter_record",
        ["failure_category", "dead_lettered_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dead_letter_record_source_system"),
        "dead_letter_record",
        ["source_system"],
        unique=False,
    )
    op.create_index(
        "ix_dead_letter_record_source_system_source_reference",
        "dead_letter_record",
        ["source_system", "source_reference"],
        unique=False,
    )
    op.create_index(
        "ix_dead_letter_record_status_next_retry_at",
        "dead_letter_record",
        ["status", "next_retry_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dead_letter_record_status"),
        "dead_letter_record",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dead_letter_record_status"), table_name="dead_letter_record")
    op.drop_index("ix_dead_letter_record_status_next_retry_at", table_name="dead_letter_record")
    op.drop_index("ix_dead_letter_record_source_system_source_reference", table_name="dead_letter_record")
    op.drop_index(op.f("ix_dead_letter_record_source_system"), table_name="dead_letter_record")
    op.drop_index(
        "ix_dead_letter_record_failure_category_dead_lettered_at",
        table_name="dead_letter_record",
    )
    op.drop_index("ix_dead_letter_record_dead_lettered_at", table_name="dead_letter_record")
    op.drop_index(op.f("ix_dead_letter_record_message_type"), table_name="dead_letter_record")
    op.drop_index(
        "ix_dead_letter_record_dead_letter_namespace_message_type",
        table_name="dead_letter_record",
    )
    op.drop_index(op.f("ix_dead_letter_record_dead_letter_namespace"), table_name="dead_letter_record")
    op.drop_index(op.f("ix_dead_letter_record_correlation_id"), table_name="dead_letter_record")
    op.drop_table("dead_letter_record")
