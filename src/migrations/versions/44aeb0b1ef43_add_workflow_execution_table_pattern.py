"""Add workflow execution table pattern

Revision ID: 44aeb0b1ef43
Revises: 6c15e4b5d0d2
Create Date: 2026-04-03 18:15:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "44aeb0b1ef43"
down_revision: Union[str, None] = "6c15e4b5d0d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflow_execution",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_name", sa.String(length=150), nullable=False),
        sa.Column("trigger_source", sa.String(length=100), nullable=False),
        sa.Column("workflow_version", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trigger_reference", sa.String(length=255), nullable=True),
        sa.Column("run_key", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("current_step", sa.String(length=150), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
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
    op.create_index(
        op.f("ix_workflow_execution_correlation_id"),
        "workflow_execution",
        ["correlation_id"],
        unique=False,
    )
    op.create_index(op.f("ix_workflow_execution_status"), "workflow_execution", ["status"], unique=False)
    op.create_index(
        "ix_workflow_execution_status_last_transition_at",
        "workflow_execution",
        ["status", "last_transition_at"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_execution_status_scheduled_at",
        "workflow_execution",
        ["status", "scheduled_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_execution_trigger_source"),
        "workflow_execution",
        ["trigger_source"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_execution_trigger_source_reference",
        "workflow_execution",
        ["trigger_source", "trigger_reference"],
        unique=False,
    )
    op.create_index(op.f("ix_workflow_execution_workflow_name"), "workflow_execution", ["workflow_name"], unique=False)
    op.create_index(
        "ix_workflow_execution_workflow_name_run_key",
        "workflow_execution",
        ["workflow_name", "run_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_execution_workflow_name_run_key", table_name="workflow_execution")
    op.drop_index(op.f("ix_workflow_execution_workflow_name"), table_name="workflow_execution")
    op.drop_index("ix_workflow_execution_trigger_source_reference", table_name="workflow_execution")
    op.drop_index(op.f("ix_workflow_execution_trigger_source"), table_name="workflow_execution")
    op.drop_index("ix_workflow_execution_status_scheduled_at", table_name="workflow_execution")
    op.drop_index("ix_workflow_execution_status_last_transition_at", table_name="workflow_execution")
    op.drop_index(op.f("ix_workflow_execution_status"), table_name="workflow_execution")
    op.drop_index(op.f("ix_workflow_execution_correlation_id"), table_name="workflow_execution")
    op.drop_table("workflow_execution")
