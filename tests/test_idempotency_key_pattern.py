from sqlalchemy import JSON, Text, UniqueConstraint

from src.app.core.db.idempotency_key import IdempotencyKey, IdempotencyKeyStatus
from src.app.platform.database import Base
from src.app.platform.database import IdempotencyKey as PlatformIdempotencyKey
from src.app.platform.database import IdempotencyKeyStatus as PlatformStatus


def test_idempotency_key_table_is_registered_in_canonical_metadata() -> None:
    assert Base.metadata.tables["idempotency_key"] is IdempotencyKey.__table__
    assert PlatformIdempotencyKey is IdempotencyKey
    assert PlatformStatus is IdempotencyKeyStatus


def test_idempotency_key_table_exposes_expected_lookup_indexes_and_constraints() -> None:
    index_names = {index.name for index in IdempotencyKey.__table__.indexes}
    unique_constraint_names = {
        constraint.name
        for constraint in IdempotencyKey.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert {
        "ix_idempotency_key_expires_at",
        "ix_idempotency_key_scope",
        "ix_idempotency_key_scope_request_fingerprint",
        "ix_idempotency_key_status",
        "ix_idempotency_key_status_locked_until",
    }.issubset(index_names)
    assert "uq_idempotency_key_scope_key" in unique_constraint_names


def test_idempotency_key_table_tracks_processing_state_and_metadata() -> None:
    processing_metadata_column = IdempotencyKey.__table__.c.processing_metadata
    error_detail_column = IdempotencyKey.__table__.c.error_detail
    hit_count_column = IdempotencyKey.__table__.c.hit_count
    status_column = IdempotencyKey.__table__.c.status

    assert isinstance(processing_metadata_column.type, JSON)
    assert isinstance(error_detail_column.type, Text)
    assert hit_count_column.default is not None
    assert hit_count_column.default.arg == 1
    assert status_column.default is not None
    assert status_column.default.arg == IdempotencyKeyStatus.RECEIVED.value
