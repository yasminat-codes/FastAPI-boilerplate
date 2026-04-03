# Automation Persistence Patterns

This guide documents reusable database table patterns for webhook-driven and workflow-driven systems. These tables are part of the shared platform layer of the template, not client-specific business models.

## Inbound Webhook Event Ledger

The template now includes a generic inbound webhook event table in `src/app/core/db/webhook_event.py`.

Use this pattern when you need to:

- persist webhook deliveries before heavy processing begins
- keep an auditable inbox of what arrived and when
- look up retries or duplicates by provider delivery identifiers
- attach normalized payload data without losing the original body
- correlate webhook intake with later queue, workflow, or failure records

### Why this lives in the platform layer

Webhook ingestion is a platform concern. The shared table should exist before any cloned project adds provider-specific handlers, workflow orchestration, or business rules. Projects can extend the pattern, but they should not have to invent the storage contract from scratch.

### Included fields

The baseline table stores:

- `source`: provider or integration slug such as `stripe`, `github`, or `clerk`
- `endpoint_key`: internal route or handler identifier for the receiving endpoint
- `event_type`: provider event name after basic classification
- `status`: lightweight lifecycle status from receipt through processing
- `delivery_id` and `event_id`: provider identifiers used for lookup and replay checks
- `signature_verified`: whether the inbound request passed signature verification
- `payload_content_type`, `payload_sha256`, and `payload_size_bytes`: operational metadata about the inbound body
- `raw_payload`: the original request body for replay or investigation
- `normalized_payload`: optional parsed payload data for downstream consumers
- `processing_metadata` and `processing_error`: room for queue, workflow, or failure details
- `received_at`, `acknowledged_at`, and `processed_at`: timestamps for operational visibility

### Lookup posture

The table includes indexes for the most common operational queries:

- by `source`
- by `endpoint_key`
- by `event_type`
- by `status`
- by `(source, delivery_id)`
- by `(source, event_id)`
- by `(status, received_at)`
- by `payload_sha256`

These indexes intentionally optimize common webhook inbox and replay triage patterns without assuming any single provider's uniqueness guarantees.

### Example model

```python
class WebhookEvent(Base):
    __tablename__ = "webhook_event"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    source: Mapped[str] = mapped_column(String(100), index=True)
    endpoint_key: Mapped[str] = mapped_column(String(100), index=True)
    event_type: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(32), default="received", index=True)
    delivery_id: Mapped[str | None] = mapped_column(String(255), default=None)
    event_id: Mapped[str | None] = mapped_column(String(255), default=None)
    raw_payload: Mapped[str | None] = mapped_column(Text, default=None)
    normalized_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
```

### Extending this pattern in a cloned project

Keep the shared fields above, then add project-specific columns only if the cloned system truly needs them. Common extensions include:

- tenant or organization scoping columns
- foreign keys into a future idempotency-key table
- a workflow execution reference once orchestration primitives are added
- provider-specific delivery metadata that is safe to retain

Avoid baking provider-specific signature formats, business identifiers, or downstream workflow state directly into the base template model.

### Retention and safety notes

- Treat `raw_payload` as sensitive operational data and align retention with `WEBHOOK_STORE_RAW_PAYLOADS` and `WEBHOOK_PAYLOAD_RETENTION_DAYS`.
- Do not store raw authorization headers or secrets in this table by default.
- If a provider guarantees stable unique delivery identifiers, cloned projects may add stricter constraints after validating that assumption.

Future roadmap items will layer idempotency-key, workflow-execution, dead-letter, and audit-log patterns on top of this shared webhook ledger.
