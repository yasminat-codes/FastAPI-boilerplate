"""Add job state history table pattern

Revision ID: 2208c3f7c9d8
Revises: 44aeb0b1ef43
Create Date: 2026-04-03 19:10:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2208c3f7c9d8"
down_revision: Union[str, None] = "44aeb0b1ef43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_state_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_name", sa.String(length=150), nullable=False),
        sa.Column("queue_name", sa.String(length=100), nullable=False),
        sa.Column("job_version", sa.String(length=50), nullable=True),
        sa.Column("queue_backend", sa.String(length=50), nullable=True),
        sa.Column("queue_job_id", sa.String(length=255), nullable=True),
        sa.Column("worker_name", sa.String(length=150), nullable=True),
        sa.Column("worker_version", sa.String(length=50), nullable=True),
        sa.Column("trigger_source", sa.String(length=100), nullable=True),
        sa.Column("trigger_reference", sa.String(length=255), nullable=True),
        sa.Column("run_key", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_step", sa.String(length=150), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_transition_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=True),
        sa.Column("execution_context", sa.JSON(), nullable=True),
        sa.Column("output_payload", sa.JSON(), nullable=True),
        sa.Column("status_metadata", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_state_history_correlation_id"), "job_state_history", ["correlation_id"], unique=False)
    op.create_index(op.f("ix_job_state_history_job_name"), "job_state_history", ["job_name"], unique=False)
    op.create_index(
        "ix_job_state_history_job_name_run_key",
        "job_state_history",
        ["job_name", "run_key"],
        unique=False,
    )
    op.create_index(
        "ix_job_state_history_last_transition_at",
        "job_state_history",
        ["last_transition_at"],
        unique=False,
    )
    op.create_index(op.f("ix_job_state_history_queue_name"), "job_state_history", ["queue_name"], unique=False)
    op.create_index(
        "ix_job_state_history_queue_name_queue_job_id",
        "job_state_history",
        ["queue_name", "queue_job_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_state_history_status_last_transition_at",
        "job_state_history",
        ["status", "last_transition_at"],
        unique=False,
    )
    op.create_index(
        "ix_job_state_history_status_scheduled_at",
        "job_state_history",
        ["status", "scheduled_at"],
        unique=False,
    )
    op.create_index(op.f("ix_job_state_history_status"), "job_state_history", ["status"], unique=False)
    op.create_index(op.f("ix_job_state_history_trigger_source"), "job_state_history", ["trigger_source"], unique=False)
    op.create_index(
        "ix_job_state_history_trigger_source_reference",
        "job_state_history",
        ["trigger_source", "trigger_reference"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_job_state_history_trigger_source_reference", table_name="job_state_history")
    op.drop_index(op.f("ix_job_state_history_trigger_source"), table_name="job_state_history")
    op.drop_index(op.f("ix_job_state_history_status"), table_name="job_state_history")
    op.drop_index("ix_job_state_history_status_scheduled_at", table_name="job_state_history")
    op.drop_index("ix_job_state_history_status_last_transition_at", table_name="job_state_history")
    op.drop_index("ix_job_state_history_queue_name_queue_job_id", table_name="job_state_history")
    op.drop_index(op.f("ix_job_state_history_queue_name"), table_name="job_state_history")
    op.drop_index("ix_job_state_history_last_transition_at", table_name="job_state_history")
    op.drop_index("ix_job_state_history_job_name_run_key", table_name="job_state_history")
    op.drop_index(op.f("ix_job_state_history_job_name"), table_name="job_state_history")
    op.drop_index(op.f("ix_job_state_history_correlation_id"), table_name="job_state_history")
    op.drop_table("job_state_history")
