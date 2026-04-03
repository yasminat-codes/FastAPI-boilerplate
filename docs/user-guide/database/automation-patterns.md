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
- a workflow-execution reference for systems that link intake records to downstream orchestration runs
- provider-specific delivery metadata that is safe to retain

Avoid baking provider-specific signature formats, business identifiers, or downstream workflow state directly into the base template model.

### Retention and safety notes

- Treat `raw_payload` as sensitive operational data and align retention with `WEBHOOK_STORE_RAW_PAYLOADS` and `WEBHOOK_PAYLOAD_RETENTION_DAYS`.
- Do not store raw authorization headers or secrets in this table by default.
- If a provider guarantees stable unique delivery identifiers, cloned projects may add stricter constraints after validating that assumption.

## Idempotency Key Ledger

The template now includes a generic idempotency-key table in `src/app/core/db/idempotency_key.py`.

Use this pattern when you need to:

- deduplicate inbound API requests, webhook processing, or background jobs by a stable caller-provided key
- detect when the same key is replayed with a different semantic payload
- coordinate in-flight work with an expiring lock or lease
- record lightweight recovery checkpoints during multi-step execution
- retain enough operational state to investigate retries, duplicates, and failures

### Why this lives in the platform layer

Idempotency is a cross-cutting platform concern. Every cloned project should start with a consistent place to store de-duplication state instead of inventing its own key ledger in an app-specific model package. The shared table covers the reusable contract, while cloned projects can extend it with tenant scoping, response snapshots, or foreign keys once their domain rules are known.

### Included fields

The baseline table stores:

- `scope`: a logical namespace such as `api.payment.create`, `webhook.github.installation`, or `job.invoice.sync`
- `key`: the caller-provided or derived idempotency key within that scope
- `status`: a lightweight lifecycle state from first receipt through completion, failure, or expiration
- `request_fingerprint`: an optional hash of the semantic input so replays with mismatched payloads can be detected
- `recovery_point`: an optional checkpoint label for resumable multi-step workflows
- `locked_until`: a lease boundary used to coordinate in-progress work safely
- `expires_at`: the retention or replay window for the key record
- `first_seen_at`, `last_seen_at`, and `completed_at`: timestamps for operational visibility
- `hit_count`: how many times the same scoped key has been observed
- `processing_metadata`, `error_code`, and `error_detail`: room for execution details without forcing a domain-specific result schema

### Lookup posture

The table includes a unique constraint and indexes for the most common idempotency queries:

- unique by `(scope, key)`
- by `scope`
- by `(scope, request_fingerprint)`
- by `status`
- by `(status, locked_until)`
- by `expires_at`

These indexes intentionally support duplicate detection, stale-lock recovery, and cleanup workflows without assuming a single API shape or a single queueing model.

### Example model

```python
class IdempotencyKey(Base):
    __tablename__ = "idempotency_key"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    scope: Mapped[str] = mapped_column(String(100), index=True)
    key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="received", index=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), default=None)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=1)
    processing_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
```

### Extending this pattern in a cloned project

Keep the shared fields above, then add project-specific columns only if the cloned system truly needs them. Common extensions include:

- tenant or organization scoping columns when uniqueness must be isolated per customer
- response snapshot or resource-reference columns for APIs that replay prior success responses
- foreign keys to webhook-event or workflow-execution records when those project-specific flows are introduced
- stricter provider or endpoint constraints after operational data proves they are safe

Avoid encoding product-specific request schemas, business identifiers, or external API assumptions directly into the base template model.

### Retention and safety notes

- Use `expires_at` to define how long a cloned project will honor replay protection before cleanup.
- Treat `request_fingerprint` as derived metadata, not as a substitute for storing raw secrets or raw authorization headers.
- If a cloned project stores response snapshots or downstream references, keep the payload minimal and avoid persisting sensitive response bodies by default.

## Workflow Execution Ledger

The template now includes a generic workflow-execution table in `src/app/core/db/workflow_execution.py`.

Use this pattern when you need to:

- track the lifecycle of a multi-step process beyond a single request or background job
- correlate API, webhook, scheduler, or manual triggers with later orchestration state
- inspect in-flight, waiting, failed, or canceled runs after a process restart
- store lightweight workflow input, output, and operational context without hardcoding a client domain schema
- give future step-state, dead-letter, or audit tables a stable execution header to attach to

### Why this lives in the platform layer

Workflow execution tracking is a platform concern for automation-heavy backends. Cloned projects should not have to invent a process-run ledger from scratch before they can add orchestration, retries, or operational tooling. The shared table provides a reusable execution header while leaving step-level and domain-specific state open for later extension.

### Included fields

The baseline table stores:

- `workflow_name` and `workflow_version`: the reusable workflow identifier and optional contract/version label
- `status`: a lightweight lifecycle state from pending through running, waiting, success, failure, or cancellation
- `trigger_source` and `trigger_reference`: what started the workflow and the upstream reference used to look it up later
- `run_key`: an optional project-defined natural key for correlating logically identical runs
- `correlation_id`: the shared request or job correlation handle for logs and traces
- `current_step`, `attempt_count`, and `max_attempts`: minimal execution progress and retry posture
- `scheduled_at`, `started_at`, `completed_at`, and `last_transition_at`: timestamps for operational visibility
- `input_payload`, `execution_context`, `output_payload`, and `status_metadata`: room for structured inputs, orchestration context, and lightweight results
- `error_code` and `error_detail`: minimal failure detail without assuming a client-specific error schema

### Lookup posture

The table includes indexes for the most common workflow-operations queries:

- by `workflow_name`
- by `status`
- by `trigger_source`
- by `correlation_id`
- by `(workflow_name, run_key)`
- by `(trigger_source, trigger_reference)`
- by `(status, scheduled_at)`
- by `(status, last_transition_at)`

These indexes intentionally support workflow inboxes, stale-run detection, trigger correlation, and cleanup flows without assuming a single workflow engine or business domain.

### Example model

```python
class WorkflowExecution(Base):
    __tablename__ = "workflow_execution"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    workflow_name: Mapped[str] = mapped_column(String(150), index=True)
    trigger_source: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    run_key: Mapped[str | None] = mapped_column(String(255), default=None)
    correlation_id: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    current_step: Mapped[str | None] = mapped_column(String(150), default=None)
    input_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
```

### Extending this pattern in a cloned project

Keep the shared fields above, then add project-specific columns only if the cloned system truly needs them. Common extensions include:

- tenant or organization scoping columns once the cloned project defines its multi-tenant posture
- foreign keys to webhook-event, idempotency-key, or step-history tables after those relationships are real
- domain-specific result references or materialized summaries for operator dashboards
- SLA, timeout, or ownership columns if the cloned system has concrete operational contracts

Avoid using this table as an append-only event log. Keep it as the durable execution header, then attach step-history, audit, or dead-letter tables when the cloned project needs deeper operational granularity.

### Retention and safety notes

- Keep `input_payload` and `output_payload` intentionally small, and do not use them to retain secrets or full provider payload archives by default.
- Use `status_metadata` for compact operational context such as wait reasons, queue references, or retry notes, not unbounded logs.
- If a cloned project needs long-term compliance retention, archive completed runs separately from the hot operational table used for current workflow management.

Future roadmap items will layer job-history, integration-checkpoint, dead-letter, and audit-log patterns on top of these shared webhook, idempotency, and workflow ledgers.
