from sqlalchemy import JSON, Text

from src.app.core.db.webhook_event import WebhookEvent, WebhookEventStatus
from src.app.platform.database import Base
from src.app.platform.database import WebhookEvent as PlatformWebhookEvent
from src.app.platform.database import WebhookEventStatus as PlatformStatus


def test_webhook_event_table_is_registered_in_canonical_metadata() -> None:
    assert Base.metadata.tables["webhook_event"] is WebhookEvent.__table__
    assert PlatformWebhookEvent is WebhookEvent
    assert PlatformStatus is WebhookEventStatus


def test_webhook_event_table_exposes_expected_lookup_indexes() -> None:
    index_names = {index.name for index in WebhookEvent.__table__.indexes}

    assert {
        "ix_webhook_event_endpoint_key",
        "ix_webhook_event_event_type",
        "ix_webhook_event_payload_sha256",
        "ix_webhook_event_source",
        "ix_webhook_event_source_delivery_id",
        "ix_webhook_event_source_event_id",
        "ix_webhook_event_status",
        "ix_webhook_event_status_received_at",
    }.issubset(index_names)


def test_webhook_event_table_uses_text_and_json_payload_storage() -> None:
    raw_payload_column = WebhookEvent.__table__.c.raw_payload
    normalized_payload_column = WebhookEvent.__table__.c.normalized_payload
    processing_metadata_column = WebhookEvent.__table__.c.processing_metadata
    status_column = WebhookEvent.__table__.c.status

    assert isinstance(raw_payload_column.type, Text)
    assert isinstance(normalized_payload_column.type, JSON)
    assert isinstance(processing_metadata_column.type, JSON)
    assert status_column.default is not None
    assert status_column.default.arg == WebhookEventStatus.RECEIVED.value
