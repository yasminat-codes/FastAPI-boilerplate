from sqlalchemy import JSON, Text

from src.app.core.db.job_state_history import JobStateHistory, JobStateHistoryStatus
from src.app.platform.database import Base
from src.app.platform.database import JobStateHistory as PlatformJobStateHistory
from src.app.platform.database import JobStateHistoryStatus as PlatformStatus


def test_job_state_history_table_is_registered_in_canonical_metadata() -> None:
    assert Base.metadata.tables["job_state_history"] is JobStateHistory.__table__
    assert PlatformJobStateHistory is JobStateHistory
    assert PlatformStatus is JobStateHistoryStatus


def test_job_state_history_table_exposes_expected_lookup_indexes() -> None:
    index_names = {index.name for index in JobStateHistory.__table__.indexes}

    assert {
        "ix_job_state_history_correlation_id",
        "ix_job_state_history_job_name",
        "ix_job_state_history_job_name_run_key",
        "ix_job_state_history_last_transition_at",
        "ix_job_state_history_queue_name",
        "ix_job_state_history_queue_name_queue_job_id",
        "ix_job_state_history_status",
        "ix_job_state_history_status_last_transition_at",
        "ix_job_state_history_status_scheduled_at",
        "ix_job_state_history_trigger_source",
        "ix_job_state_history_trigger_source_reference",
    }.issubset(index_names)


def test_job_state_history_table_tracks_lifecycle_and_payload_metadata() -> None:
    input_payload_column = JobStateHistory.__table__.c.input_payload
    execution_context_column = JobStateHistory.__table__.c.execution_context
    output_payload_column = JobStateHistory.__table__.c.output_payload
    status_metadata_column = JobStateHistory.__table__.c.status_metadata
    error_detail_column = JobStateHistory.__table__.c.error_detail
    attempt_count_column = JobStateHistory.__table__.c.attempt_count
    status_column = JobStateHistory.__table__.c.status

    assert isinstance(input_payload_column.type, JSON)
    assert isinstance(execution_context_column.type, JSON)
    assert isinstance(output_payload_column.type, JSON)
    assert isinstance(status_metadata_column.type, JSON)
    assert isinstance(error_detail_column.type, Text)
    assert attempt_count_column.default is not None
    assert attempt_count_column.default.arg == 0
    assert status_column.default is not None
    assert status_column.default.arg == JobStateHistoryStatus.PENDING.value
