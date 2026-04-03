"""Add integration sync checkpoint table pattern

Revision ID: 2f6e0a91b8c4
Revises: 2208c3f7c9d8
Create Date: 2026-04-03 20:30:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2f6e0a91b8c4"
down_revision: Union[str, None] = "2208c3f7c9d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_sync_checkpoint",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("integration_name", sa.String(length=100), nullable=False),
        sa.Column("sync_scope", sa.String(length=150), nullable=False),
        sa.Column("checkpoint_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("cursor_state", sa.JSON(), nullable=True),
        sa.Column("checkpoint_metadata", sa.JSON(), nullable=True),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_transition_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "integration_name",
            "sync_scope",
            "checkpoint_key",
            name="uq_integration_sync_checkpoint_scope_key",
        ),
    )
    op.create_index(
        op.f("ix_integration_sync_checkpoint_integration_name"),
        "integration_sync_checkpoint",
        ["integration_name"],
        unique=False,
    )
    op.create_index(
        "ix_integration_sync_checkpoint_integration_name_sync_scope",
        "integration_sync_checkpoint",
        ["integration_name", "sync_scope"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_sync_checkpoint_lease_expires_at"),
        "integration_sync_checkpoint",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_sync_checkpoint_status"),
        "integration_sync_checkpoint",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_integration_sync_checkpoint_status_last_transition_at",
        "integration_sync_checkpoint",
        ["status", "last_transition_at"],
        unique=False,
    )
    op.create_index(
        "ix_integration_sync_checkpoint_status_next_sync_after",
        "integration_sync_checkpoint",
        ["status", "next_sync_after"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_sync_checkpoint_sync_scope"),
        "integration_sync_checkpoint",
        ["sync_scope"],
        unique=False,
    )
    op.create_index(
        "ix_integration_sync_checkpoint_sync_scope_last_synced_at",
        "integration_sync_checkpoint",
        ["sync_scope", "last_synced_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_integration_sync_checkpoint_sync_scope_last_synced_at", table_name="integration_sync_checkpoint")
    op.drop_index(op.f("ix_integration_sync_checkpoint_sync_scope"), table_name="integration_sync_checkpoint")
    op.drop_index(
        "ix_integration_sync_checkpoint_status_last_transition_at",
        table_name="integration_sync_checkpoint",
    )
    op.drop_index("ix_integration_sync_checkpoint_status_next_sync_after", table_name="integration_sync_checkpoint")
    op.drop_index(op.f("ix_integration_sync_checkpoint_status"), table_name="integration_sync_checkpoint")
    op.drop_index(op.f("ix_integration_sync_checkpoint_lease_expires_at"), table_name="integration_sync_checkpoint")
    op.drop_index(
        "ix_integration_sync_checkpoint_integration_name_sync_scope",
        table_name="integration_sync_checkpoint",
    )
    op.drop_index(op.f("ix_integration_sync_checkpoint_integration_name"), table_name="integration_sync_checkpoint")
    op.drop_table("integration_sync_checkpoint")
