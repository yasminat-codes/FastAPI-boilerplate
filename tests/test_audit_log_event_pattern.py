from sqlalchemy import JSON, Text

from src.app.core.db.audit_log_event import AuditLogEvent, AuditLogEventSeverity, AuditLogEventStatus
from src.app.platform.database import AuditLogEvent as PlatformAuditLogEvent
from src.app.platform.database import AuditLogEventSeverity as PlatformSeverity
from src.app.platform.database import AuditLogEventStatus as PlatformStatus
from src.app.platform.database import Base


def test_audit_log_event_table_is_registered_in_canonical_metadata() -> None:
    assert Base.metadata.tables["audit_log_event"] is AuditLogEvent.__table__
    assert PlatformAuditLogEvent is AuditLogEvent
    assert PlatformSeverity is AuditLogEventSeverity
    assert PlatformStatus is AuditLogEventStatus


def test_audit_log_event_table_exposes_expected_lookup_indexes() -> None:
    index_names = {index.name for index in AuditLogEvent.__table__.indexes}

    assert {
        "ix_audit_log_event_actor_type",
        "ix_audit_log_event_actor_type_actor_reference",
        "ix_audit_log_event_category",
        "ix_audit_log_event_category_occurred_at",
        "ix_audit_log_event_correlation_id",
        "ix_audit_log_event_event_source",
        "ix_audit_log_event_event_source_event_type",
        "ix_audit_log_event_event_type",
        "ix_audit_log_event_retention_expires_at",
        "ix_audit_log_event_request_id",
        "ix_audit_log_event_severity",
        "ix_audit_log_event_status",
        "ix_audit_log_event_status_occurred_at",
        "ix_audit_log_event_subject_type",
        "ix_audit_log_event_subject_type_subject_reference",
    }.issubset(index_names)


def test_audit_log_event_table_tracks_operational_metadata_and_defaults() -> None:
    audit_event = AuditLogEvent(event_source="system", event_type="template.audit")
    event_payload_column = AuditLogEvent.__table__.c.event_payload
    event_context_column = AuditLogEvent.__table__.c.event_context
    summary_column = AuditLogEvent.__table__.c.summary
    error_detail_column = AuditLogEvent.__table__.c.error_detail
    severity_column = AuditLogEvent.__table__.c.severity
    status_column = AuditLogEvent.__table__.c.status
    recorded_at_column = AuditLogEvent.__table__.c.recorded_at
    occurred_at_column = AuditLogEvent.__table__.c.occurred_at

    assert isinstance(event_payload_column.type, JSON)
    assert isinstance(event_context_column.type, JSON)
    assert isinstance(summary_column.type, Text)
    assert isinstance(error_detail_column.type, Text)
    assert severity_column.default is not None
    assert severity_column.default.arg == AuditLogEventSeverity.INFO.value
    assert status_column.default is not None
    assert status_column.default.arg == AuditLogEventStatus.RECORDED.value
    assert recorded_at_column.nullable is False
    assert occurred_at_column.nullable is False
    assert audit_event.recorded_at is not None
    assert audit_event.occurred_at is not None
