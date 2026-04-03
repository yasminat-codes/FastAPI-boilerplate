from sqlalchemy import JSON, Text, UniqueConstraint

from src.app.core.db.dead_letter_record import DeadLetterRecord, DeadLetterRecordStatus
from src.app.platform.database import Base
from src.app.platform.database import DeadLetterRecord as PlatformDeadLetterRecord
from src.app.platform.database import DeadLetterRecordStatus as PlatformStatus


def test_dead_letter_record_table_is_registered_in_canonical_metadata() -> None:
    assert Base.metadata.tables["dead_letter_record"] is DeadLetterRecord.__table__
    assert PlatformDeadLetterRecord is DeadLetterRecord
    assert PlatformStatus is DeadLetterRecordStatus


def test_dead_letter_record_table_exposes_expected_lookup_indexes() -> None:
    index_names = {index.name for index in DeadLetterRecord.__table__.indexes}
    unique_constraint_names = {
        constraint.name
        for constraint in DeadLetterRecord.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert {
        "ix_dead_letter_record_correlation_id",
        "ix_dead_letter_record_dead_letter_namespace",
        "ix_dead_letter_record_dead_letter_namespace_message_type",
        "ix_dead_letter_record_dead_lettered_at",
        "ix_dead_letter_record_failure_category_dead_lettered_at",
        "ix_dead_letter_record_message_type",
        "ix_dead_letter_record_source_system",
        "ix_dead_letter_record_source_system_source_reference",
        "ix_dead_letter_record_status",
        "ix_dead_letter_record_status_next_retry_at",
    }.issubset(index_names)
    assert "uq_dead_letter_record_namespace_key" in unique_constraint_names


def test_dead_letter_record_table_tracks_payloads_and_failure_metadata() -> None:
    payload_snapshot_column = DeadLetterRecord.__table__.c.payload_snapshot
    failure_context_column = DeadLetterRecord.__table__.c.failure_context
    error_detail_column = DeadLetterRecord.__table__.c.error_detail
    attempt_count_column = DeadLetterRecord.__table__.c.attempt_count
    status_column = DeadLetterRecord.__table__.c.status

    assert isinstance(payload_snapshot_column.type, JSON)
    assert isinstance(failure_context_column.type, JSON)
    assert isinstance(error_detail_column.type, Text)
    assert attempt_count_column.default is not None
    assert attempt_count_column.default.arg == 0
    assert status_column.default is not None
    assert status_column.default.arg == DeadLetterRecordStatus.PENDING.value
