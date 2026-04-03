from sqlalchemy import JSON, Text

from src.app.core.db.workflow_execution import WorkflowExecution, WorkflowExecutionStatus
from src.app.platform.database import Base
from src.app.platform.database import WorkflowExecution as PlatformWorkflowExecution
from src.app.platform.database import WorkflowExecutionStatus as PlatformStatus


def test_workflow_execution_table_is_registered_in_canonical_metadata() -> None:
    assert Base.metadata.tables["workflow_execution"] is WorkflowExecution.__table__
    assert PlatformWorkflowExecution is WorkflowExecution
    assert PlatformStatus is WorkflowExecutionStatus


def test_workflow_execution_table_exposes_expected_lookup_indexes() -> None:
    index_names = {index.name for index in WorkflowExecution.__table__.indexes}

    assert {
        "ix_workflow_execution_correlation_id",
        "ix_workflow_execution_status",
        "ix_workflow_execution_status_last_transition_at",
        "ix_workflow_execution_status_scheduled_at",
        "ix_workflow_execution_trigger_source",
        "ix_workflow_execution_trigger_source_reference",
        "ix_workflow_execution_workflow_name",
        "ix_workflow_execution_workflow_name_run_key",
    }.issubset(index_names)


def test_workflow_execution_table_tracks_lifecycle_and_payload_metadata() -> None:
    input_payload_column = WorkflowExecution.__table__.c.input_payload
    execution_context_column = WorkflowExecution.__table__.c.execution_context
    output_payload_column = WorkflowExecution.__table__.c.output_payload
    status_metadata_column = WorkflowExecution.__table__.c.status_metadata
    error_detail_column = WorkflowExecution.__table__.c.error_detail
    attempt_count_column = WorkflowExecution.__table__.c.attempt_count
    status_column = WorkflowExecution.__table__.c.status

    assert isinstance(input_payload_column.type, JSON)
    assert isinstance(execution_context_column.type, JSON)
    assert isinstance(output_payload_column.type, JSON)
    assert isinstance(status_metadata_column.type, JSON)
    assert isinstance(error_detail_column.type, Text)
    assert attempt_count_column.default is not None
    assert attempt_count_column.default.arg == 0
    assert status_column.default is not None
    assert status_column.default.arg == WorkflowExecutionStatus.PENDING.value
