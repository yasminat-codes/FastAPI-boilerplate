"""Add audit log event table pattern

Revision ID: 9b4d52a6f1c3
Revises: 2f6e0a91b8c4
Create Date: 2026-04-03 21:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9b4d52a6f1c3"
down_revision: Union[str, None] = "2f6e0a91b8c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_log_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_source", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=150), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("actor_type", sa.String(length=100), nullable=True),
        sa.Column("actor_reference", sa.String(length=255), nullable=True),
        sa.Column("subject_type", sa.String(length=100), nullable=True),
        sa.Column("subject_reference", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_payload", sa.JSON(), nullable=True),
        sa.Column("event_context", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("outcome_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_log_event_actor_type"), "audit_log_event", ["actor_type"], unique=False)
    op.create_index(
        "ix_audit_log_event_actor_type_actor_reference",
        "audit_log_event",
        ["actor_type", "actor_reference"],
        unique=False,
    )
    op.create_index(
        "ix_audit_log_event_category_occurred_at",
        "audit_log_event",
        ["category", "occurred_at"],
        unique=False,
    )
    op.create_index(op.f("ix_audit_log_event_category"), "audit_log_event", ["category"], unique=False)
    op.create_index(op.f("ix_audit_log_event_correlation_id"), "audit_log_event", ["correlation_id"], unique=False)
    op.create_index(op.f("ix_audit_log_event_event_source"), "audit_log_event", ["event_source"], unique=False)
    op.create_index(
        "ix_audit_log_event_event_source_event_type",
        "audit_log_event",
        ["event_source", "event_type"],
        unique=False,
    )
    op.create_index(op.f("ix_audit_log_event_event_type"), "audit_log_event", ["event_type"], unique=False)
    op.create_index(
        op.f("ix_audit_log_event_retention_expires_at"),
        "audit_log_event",
        ["retention_expires_at"],
        unique=False,
    )
    op.create_index(op.f("ix_audit_log_event_request_id"), "audit_log_event", ["request_id"], unique=False)
    op.create_index(op.f("ix_audit_log_event_severity"), "audit_log_event", ["severity"], unique=False)
    op.create_index(
        "ix_audit_log_event_status_occurred_at",
        "audit_log_event",
        ["status", "occurred_at"],
        unique=False,
    )
    op.create_index(op.f("ix_audit_log_event_status"), "audit_log_event", ["status"], unique=False)
    op.create_index(op.f("ix_audit_log_event_subject_type"), "audit_log_event", ["subject_type"], unique=False)
    op.create_index(
        "ix_audit_log_event_subject_type_subject_reference",
        "audit_log_event",
        ["subject_type", "subject_reference"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_audit_log_event_subject_type_subject_reference",
        table_name="audit_log_event",
    )
    op.drop_index(op.f("ix_audit_log_event_subject_type"), table_name="audit_log_event")
    op.drop_index(op.f("ix_audit_log_event_status"), table_name="audit_log_event")
    op.drop_index("ix_audit_log_event_status_occurred_at", table_name="audit_log_event")
    op.drop_index(op.f("ix_audit_log_event_severity"), table_name="audit_log_event")
    op.drop_index(op.f("ix_audit_log_event_request_id"), table_name="audit_log_event")
    op.drop_index(op.f("ix_audit_log_event_retention_expires_at"), table_name="audit_log_event")
    op.drop_index(op.f("ix_audit_log_event_event_type"), table_name="audit_log_event")
    op.drop_index("ix_audit_log_event_event_source_event_type", table_name="audit_log_event")
    op.drop_index(op.f("ix_audit_log_event_event_source"), table_name="audit_log_event")
    op.drop_index(op.f("ix_audit_log_event_correlation_id"), table_name="audit_log_event")
    op.drop_index(op.f("ix_audit_log_event_category"), table_name="audit_log_event")
    op.drop_index(
        "ix_audit_log_event_category_occurred_at",
        table_name="audit_log_event",
    )
    op.drop_index(
        "ix_audit_log_event_actor_type_actor_reference",
        table_name="audit_log_event",
    )
    op.drop_index(op.f("ix_audit_log_event_actor_type"), table_name="audit_log_event")
    op.drop_table("audit_log_event")
