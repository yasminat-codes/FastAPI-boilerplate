from sqlalchemy import JSON, Text, UniqueConstraint

from src.app.core.db.integration_sync_checkpoint import IntegrationSyncCheckpoint, IntegrationSyncCheckpointStatus
from src.app.platform.database import Base
from src.app.platform.database import IntegrationSyncCheckpoint as PlatformIntegrationSyncCheckpoint
from src.app.platform.database import IntegrationSyncCheckpointStatus as PlatformStatus


def test_integration_sync_checkpoint_table_is_registered_in_canonical_metadata() -> None:
    assert Base.metadata.tables["integration_sync_checkpoint"] is IntegrationSyncCheckpoint.__table__
    assert PlatformIntegrationSyncCheckpoint is IntegrationSyncCheckpoint
    assert PlatformStatus is IntegrationSyncCheckpointStatus


def test_integration_sync_checkpoint_table_exposes_expected_lookup_indexes() -> None:
    index_names = {index.name for index in IntegrationSyncCheckpoint.__table__.indexes}
    unique_constraint_names = {
        constraint.name
        for constraint in IntegrationSyncCheckpoint.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert {
        "ix_integration_sync_checkpoint_integration_name",
        "ix_integration_sync_checkpoint_integration_name_sync_scope",
        "ix_integration_sync_checkpoint_lease_expires_at",
        "ix_integration_sync_checkpoint_status",
        "ix_integration_sync_checkpoint_status_last_transition_at",
        "ix_integration_sync_checkpoint_status_next_sync_after",
        "ix_integration_sync_checkpoint_sync_scope",
        "ix_integration_sync_checkpoint_sync_scope_last_synced_at",
    }.issubset(index_names)
    assert "uq_integration_sync_checkpoint_scope_key" in unique_constraint_names


def test_integration_sync_checkpoint_table_tracks_cursor_state_and_failures() -> None:
    cursor_state_column = IntegrationSyncCheckpoint.__table__.c.cursor_state
    checkpoint_metadata_column = IntegrationSyncCheckpoint.__table__.c.checkpoint_metadata
    error_detail_column = IntegrationSyncCheckpoint.__table__.c.error_detail
    checkpoint_key_column = IntegrationSyncCheckpoint.__table__.c.checkpoint_key
    failure_count_column = IntegrationSyncCheckpoint.__table__.c.failure_count
    status_column = IntegrationSyncCheckpoint.__table__.c.status

    assert isinstance(cursor_state_column.type, JSON)
    assert isinstance(checkpoint_metadata_column.type, JSON)
    assert isinstance(error_detail_column.type, Text)
    assert checkpoint_key_column.default is not None
    assert checkpoint_key_column.default.arg == "default"
    assert failure_count_column.default is not None
    assert failure_count_column.default.arg == 0
    assert status_column.default is not None
    assert status_column.default.arg == IntegrationSyncCheckpointStatus.PENDING.value
