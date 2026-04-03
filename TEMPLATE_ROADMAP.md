# Production FastAPI Template Roadmap

This document is the working plan for turning this repository into a reusable, production-ready FastAPI backend template for client projects.

The goal is not to add client-specific business logic. The goal is to build a strong default platform that can be cloned and then extended with client-specific integrations, workflows, webhooks, and domain logic.

## Session Guardrail

This repository is a reusable template.

Read [EXECUTION_SYSTEM.md](/Users/yasmineseidu/coding/fastapi-template/EXECUTION_SYSTEM.md) before starting work in any new session.

- We are building a general-purpose production backend foundation.
- We are not building a live client system inside this repository.
- We are not adding client-specific integrations, workflows, schemas, dashboards, or business rules.
- Every change should improve the template as a starting point for future projects.
- If a future session proposes something client-specific, it should be converted into a reusable template pattern instead.

## Progress Checklist

- [ ] Phase 0: Foundation Audit And Planning
- [x] Phase 1: Core Application Hardening
- [x] Phase 2: Database And Persistence Platform
- [ ] Phase 3: API Platform And Request Pipeline
- [ ] Phase 4: Authentication, Authorization, And Security
- [ ] Phase 5: Webhook Ingestion Platform
- [ ] Phase 6: Background Jobs, Scheduling, And Workflow Execution
- [ ] Phase 7: External Integration Foundation
- [ ] Phase 8: Observability And Operational Excellence
- [ ] Phase 9: Testing And Quality Gates
- [ ] Phase 10: Deployment, Runtime, And Release Engineering
- [ ] Phase 11: Documentation And Template Experience
- [ ] Phase 12: Final Production Readiness Sweep

## How We Will Use This Document

- We will work phase by phase.
- Each wave groups related tasks that can be completed together.
- Every task is a checkbox so we can mark it off as we go.
- If scope changes, we update this file rather than letting the plan drift into chat history.
- We will mark both the task-level checkboxes and the phase-level progress checklist as work is completed.
- We follow the delivery and verification rules in [EXECUTION_SYSTEM.md](/Users/yasmineseidu/coding/fastapi-template/EXECUTION_SYSTEM.md).

## Session Summary

### April 1, 2026

- Phase 1 Wave 1.1 was finished and the template structure was stabilized:
  canonical platform boundaries, API and worker entrypoints, a scheduler placeholder, naming conventions, and the shared-vs-platform split are now in place.
- Phase 1 Wave 1.2 advanced substantially across the configuration layer:
  environment profiles, first-class `DATABASE_URL`, database runtime tuning, Redis runtime settings, worker runtime settings, webhook runtime settings, observability settings, production-safe CORS settings, host/proxy trust controls, security header / cookie settings, and feature-flag / optional-module toggles are now implemented.
- Runtime wiring was updated where the template already owned behavior:
  database and Redis helpers feed runtime setup, `WorkerJob` and ARQ defaults now come from settings, Sentry initialization consumes the new observability contract, FastAPI middleware wiring now uses explicit CORS, security-header, trusted-host, proxy-header, and client-cache feature controls, the built-in auth flow now consumes configurable refresh-cookie behavior, and starter route groups are now registered through settings-driven router builders.
- Application lifecycle hardening also moved forward:
  the FastAPI lifespan now primes the shared SQLAlchemy async engine, initializes the template-owned Redis services and Sentry using the passed settings object, and tears those shared handles down during shutdown instead of relying on ad hoc startup hooks.
- Shared resource safety was tightened as well:
  Redis-backed services are now connectivity-checked before their handles are published, partial startup failures unwind already-initialized resources automatically, and shutdown continues attempting later cleanup steps even if one resource teardown raises.
- Phase 1 Wave 1.3 is now complete:
  API workers track in-flight requests during shutdown, reject new work once draining begins, and wait for active requests before shared resources unwind; ARQ workers now bring up and tear down template-owned shared resources through reusable lifecycle hooks; and `/api/v1/ready` now evaluates a shared readiness contract instead of assembling dependency checks inline.
- Tests were expanded to match the new template contracts:
  config tests now cover profile selection, secure-environment validation, database and Redis runtime settings, worker and webhook settings, observability configuration, CORS / header / cookie / host / proxy validation, and feature flags; setup, router, admin, and worker tests cover runtime wiring for DB/Redis/Sentry lifecycle hooks, connectivity verification, failure-safe cleanup, ARQ, optional route registration, admin toggles, and middleware behavior.
- Template docs were brought forward with the implementation:
  the README, configuration quickstart, environment variable guide, settings-class guide, environment-specific guide, and deployment env examples now describe the current settings surface, including a dedicated local / staging / production settings matrix.
- Verification status at the end of the session:
  `uv run ruff check src tests`, `uv run mypy src --config-file pyproject.toml`, `uv run pytest`, and `uv run mkdocs build --strict` all passed.
- Recommended next starting point:
  Phase 2 Wave 2.2, `Standardize Alembic configuration for template users.`

### April 1, 2026 - Database Reliability Wave 2.1

- Phase 2 Wave 2.1 is now complete:
  SQLAlchemy engine configuration now exposes explicit pool hardening, pool reuse, startup retry, server-side timeout, and SSL controls through the shared settings surface and engine builder.
- Database session handling is now formalized as a reusable template primitive:
  request, job, and script scopes are defined explicitly, the canonical platform database surface exports helper APIs for those scopes, and transaction/retry helpers now live in the shared database layer instead of being left implicit in ad hoc examples.
- Runtime integration now consumes the new database reliability primitives:
  API and worker startup both use the bounded database-engine retry path, and maintenance scripts now demonstrate the script-scope session pattern instead of opening anonymous sessions directly.
- The database migration guide now matches the migrations-only startup model, with boot-time table creation removed from the narrative and Alembic treated as the explicit schema-management path.
- The database guide now links to a dedicated reliability page, and the MkDocs nav exposes that page as a first-class database topic covering engine tuning, timeouts, retries, session scope, and SSL.
- Verification status for this wave:
  `uv run ruff check src tests`, `uv run mypy src --config-file pyproject.toml`, `uv run pytest`, and `uv run mkdocs build --strict` all passed.

#### Next Session Handoff

- Current roadmap position:
  Phase 2 is now started and complete through Wave 2.1. The next unchecked work starts in Phase 2 Wave 2.2 with migrations and data-safety standardization.
- Biggest template outcomes from this session:
  a hardened database reliability layer with explicit pool protections, bounded startup retries, reusable session-scope and transaction helpers for API/jobs/scripts, and docs/tests that now describe the template’s actual database behavior instead of older boilerplate assumptions.
- Docs and tests status:
  the database guide now includes a dedicated reliability page, the configuration quickstart points to it, the migrations guide reflects the migrations-only boot model, and automated coverage now exercises engine hardening, session policies, transaction helpers, and bounded retry behavior.
- Verification status:
  `uv run ruff check src tests`, `uv run mypy src --config-file pyproject.toml`, `uv run pytest`, and `uv run mkdocs build --strict` were green at the end of the session.
- Recommended next task:
  Phase 2 Wave 2.2, `Standardize Alembic configuration for template users.`
- Guardrail for the next session:
  keep the work template-oriented by strengthening reusable migration and data-safety patterns, not by baking one team’s deployment or release process directly into the template.

## Template Outcome We Are Building

The finished template should provide:

- A hardened FastAPI application skeleton with clear boundaries and extension points.
- Safe defaults for auth, configuration, secrets, error handling, and deployment.
- A durable webhook ingestion and workflow execution foundation.
- Background processing with retries, backoff, dead-letter handling, and operational visibility.
- Observability by default, including Sentry and production-grade logging, metrics, and tracing hooks.
- Strong testing, CI, and release hygiene so a cloned project starts from a healthy baseline.
- Deployment assets and runbooks that are ready for real environments, not only local development.

## Explicit Non-Goals

- No client-specific integrations in the template.
- No client-specific business rules, workflows, or dashboards.
- No building this repository as though it were a single company's actual production system.
- No premature multi-service split unless the template truly needs it.
- No coupling to a single cloud provider unless made optional.

## Delivery Principles

- Migrations, not auto-created schema, for production database changes.
- Async-safe, failure-aware defaults.
- Idempotency and replay safety for external events.
- Logs, traces, and errors must include correlation context.
- Every subsystem should fail in a controlled, observable way.
- Local development must stay easy even as production hardening increases.

## Phase 0: Foundation Audit And Planning

### Wave 0.1: Repo Baseline

- [ ] Confirm the repository name, template branding, and intended GitHub template positioning.
- [ ] Define the target Python version policy for the template.
- [ ] Define the support policy for FastAPI, SQLAlchemy, Redis, and worker dependencies.
- [ ] Decide whether the template remains single-service with worker sidecar or grows into optional service split patterns.
- [ ] Decide which features are core and always enabled versus optional modules.
- [ ] Document a template philosophy section in the README.
- [ ] Document what gets customized per client versus what remains part of the shared platform.

### Wave 0.2: Architecture Decisions

- [ ] Define the target runtime architecture for API, worker, scheduler, migrations, and reverse proxy.
- [ ] Decide on the queue model and confirm ARQ remains the long-term default.
- [ ] Decide whether scheduled jobs are included in the core template and how they are executed.
- [x] Define the default app directory structure for platform, domain, integrations, and workflows.
- [ ] Define extension points for client-specific integrations and webhook handlers.
- [ ] Define the template’s multi-tenant posture: single-tenant by default, tenant-ready primitives, or full multi-tenant scaffolding.
- [ ] Define the initial observability standard: Sentry, structured logs, metrics, traces, health endpoints.
- [ ] Define the deployment target surfaces to support out of the box.

## Phase 1: Core Application Hardening

### Wave 1.1: Project Structure Refactor

- [x] Reorganize the codebase into clear platform-oriented modules.
- [x] Introduce explicit boundaries for `platform`, `api`, `domain`, `integrations`, `workflows`, and `workers`.
- [x] Remove or isolate demo/example resources that do not belong in a reusable production template.
- [x] Create a consistent naming convention for modules, routers, services, repositories, and schemas.
- [x] Add a canonical app factory entrypoint and runtime entrypoints for API, worker, and future scheduler.
- [x] Define a standard place for shared utilities versus platform primitives.

### Wave 1.2: Settings And Configuration System

- [x] Replace weak or unsafe default secrets with fail-fast production-safe settings behavior.
- [x] Introduce environment-specific settings profiles with strict validation.
- [x] Add a first-class `DATABASE_URL` setting while keeping composed settings optional.
- [x] Add settings for database pool size, overflow, pre-ping, recycle, SSL, and timeouts.
- [x] Add settings for Redis connections, timeouts, retries, and TLS where relevant.
- [x] Add settings for worker concurrency, queue names, retry defaults, and retention.
- [x] Add settings for webhook verification, replay windows, and payload retention.
- [x] Add settings for Sentry, metrics, tracing, and log verbosity.
- [x] Add settings for CORS with production-safe defaults.
- [x] Add settings for trusted hosts and proxy headers.
- [x] Add settings for security headers and cookie behavior.
- [x] Add settings for feature flags or optional module toggles.
- [x] Add a documented settings matrix for local, staging, and production.
- [x] Add startup validation that blocks boot when critical production settings are unsafe.

### Wave 1.3: Application Lifecycle

- [x] Remove automatic `create_all()` schema creation from app startup.
- [x] Define a proper migrations-only production startup model.
- [x] Add startup/shutdown wiring for all shared resources through lifespan.
- [x] Ensure Redis, DB, queue, and telemetry resources are initialized and cleaned up safely.
- [x] Add graceful shutdown handling for API workers.
- [x] Add graceful shutdown handling for background workers.
- [x] Add a resource readiness contract that can be consumed by readiness checks.

## Phase 2: Database And Persistence Platform

### Wave 2.1: Database Reliability

- [x] Harden SQLAlchemy engine configuration for production workloads.
- [x] Add pool health checks and stale connection protection.
- [x] Add consistent transaction management guidance and helpers.
- [x] Define session scoping rules for API requests, jobs, and scripts.
- [x] Add database timeout strategy and statement timeout guidance.
- [x] Add retry guidance for transient database failures where safe.
- [x] Add support for SSL database connections.

### Wave 2.2: Migrations And Data Safety

- [x] Standardize Alembic configuration for template users.
- [x] Add migration scripts and commands to the main developer workflow.
- [x] Add migration check tooling in CI.
- [x] Add startup documentation that clearly separates app boot from migration execution.
- [x] Add rollback guidance for migration failures.
- [x] Add data backfill guidance and script patterns.
- [x] Add rules for destructive schema changes and expand-contract rollouts.

### Wave 2.3: Persistence Patterns For Automation Systems

- [x] Add a table pattern for inbound webhook events.
- [x] Add a table pattern for idempotency keys.
- [x] Add a table pattern for workflow executions or process runs.
- [x] Add a table pattern for job state history where needed.
- [x] Add a table pattern for integration sync checkpoints.
- [x] Add a table pattern for audit logs or operational events.
- [x] Add a table pattern for dead-letter or failed message records.
- [x] Add retention and cleanup guidance for high-volume event tables.

---

## Session Report — 2026-04-03

### What was built
- Added a reusable platform-owned `IdempotencyKey` table pattern with scoped uniqueness, request fingerprint tracking, replay hit counting, lease expiry, and lightweight execution state fields.
- Added an Alembic migration for the new idempotency ledger plus regression tests covering metadata registration, lookup indexes, unique constraint posture, and migration-config primary-key checks.
- Expanded the database automation-patterns documentation and refreshed the database index/models guides so the new shared persistence primitive is documented alongside the webhook-event ledger.

### Issues encountered
| Issue | How it was fixed |
|-------|-----------------|
| `uv run db-migrate-verify` initially failed because no local PostgreSQL server was listening on `localhost:5432`. | Started a temporary local PostgreSQL container using the template's default credentials, re-ran migration verification successfully, and then stopped the container to return the environment to its prior state. |

### Quality gate results
- ruff: pass
- mypy: pass
- pytest: 143 passed, 0 failed

### Current state of the template
The template now includes two shared automation persistence ledgers: inbound webhook events and idempotency keys. Both are migration-backed, re-exported through the canonical platform database surface, documented for template users, and covered by focused regression tests. The automation persistence layer is still incomplete overall, because workflow executions, job-history records, integration checkpoints, audit logs, dead-letter records, and retention guidance have not been scaffolded yet.

### What remains
- [ ] Add a table pattern for workflow executions or process runs.
- [ ] Add a table pattern for job state history where needed.
- [ ] Add a table pattern for integration sync checkpoints.

## Phase 3: API Platform And Request Pipeline

### Wave 3.1: API Architecture

- [x] Define a consistent router structure for public, internal, ops, admin, and webhook endpoints.
- [x] Define versioning rules for the API.
- [x] Add standard request and response envelope guidance where appropriate.
- [x] Add pagination, filtering, and sorting conventions for reusable resources.
- [x] Add consistent exception-to-response mapping across the app.
- [x] Add a reusable service layer pattern so business logic does not live in routers.
- [x] Add repository or data-access patterns where useful.

### Wave 3.2: Request Context And Safety

- [ ] Standardize request IDs and correlation IDs across all requests.
- [ ] Propagate correlation context into background jobs and outbound integrations.
- [ ] Add trusted proxy handling.
- [ ] Add request size limits for large or malicious bodies.
- [ ] Add body parsing guidance for raw-body webhook verification.
- [ ] Add timeout policy guidance for inbound requests.
- [ ] Add standardized error payloads with machine-readable error codes.
- [ ] Add safe logging redaction rules for headers, tokens, secrets, and PII.

### Wave 3.3: Health, Readiness, And Ops Endpoints

- [ ] Keep a lightweight liveness endpoint.
- [ ] Expand readiness checks to include DB, Redis, queue, and other critical runtime dependencies.
- [ ] Add worker health visibility.
- [ ] Add dependency-specific health details without leaking secrets.
- [ ] Add metrics endpoint planning.
- [ ] Add optional internal ops endpoints for diagnostics.

## Phase 4: Authentication, Authorization, And Security

### Wave 4.1: Auth Hardening

- [ ] Review JWT design and decide whether to keep stateless JWT-only, session-backed refresh, or hybrid.
- [ ] Add explicit issuer, audience, and key rotation support if JWT remains the default.
- [ ] Add refresh token rotation strategy.
- [ ] Add secure password hashing policy and future-proofing.
- [ ] Add login throttling and lockout policy guidance.
- [ ] Add secure cookie policy defaults where cookies are used.
- [ ] Add token revocation cleanup and retention strategy.

### Wave 4.2: Authorization And Access Control

- [ ] Add a reusable RBAC or permission policy layer.
- [ ] Define internal versus external endpoint access rules.
- [ ] Add service-to-service authentication guidance for internal hooks.
- [ ] Add optional API key pattern for machine clients.
- [ ] Add tenant/org scoping hooks if tenant-aware support is desired.

### Wave 4.3: Platform Security Controls

- [ ] Add security headers middleware.
- [ ] Add TrustedHost middleware or equivalent protection.
- [ ] Add rate limiting strategy for auth, API, and webhook endpoints.
- [ ] Add request validation limits for untrusted payloads.
- [ ] Add secret redaction in logs and error reports.
- [ ] Add secure admin defaults or make admin disabled by default.
- [ ] Review CSRF implications for any cookie-based flows.
- [ ] Add dependency vulnerability scanning to CI.
- [ ] Add secret scanning to CI and local hooks.

## Phase 5: Webhook Ingestion Platform

### Wave 5.1: Generic Webhook Framework

- [ ] Create a dedicated webhook module structure.
- [ ] Add a raw-body-capable webhook ingestion path.
- [ ] Add provider-agnostic signature verification interfaces.
- [ ] Add a webhook event persistence model.
- [ ] Add a standard ingestion flow: receive, validate, persist, acknowledge, enqueue.
- [ ] Add replay protection primitives.
- [ ] Add idempotency protection primitives.
- [ ] Add duplicate event handling strategy.
- [ ] Add malformed payload handling strategy.
- [ ] Add unknown event type handling strategy.
- [ ] Add poison payload handling strategy.

### Wave 5.2: Operational Webhook Guarantees

- [ ] Define acknowledgement strategy so providers receive timely responses.
- [ ] Ensure heavy processing is offloaded to jobs instead of running inline.
- [ ] Add retry-safe event processing contracts.
- [ ] Add storage for original payload and normalized metadata.
- [ ] Add event correlation from webhook to workflow execution.
- [ ] Add replay tooling for local development and operations.
- [ ] Add dead-letter behavior for repeatedly failing webhook events.
- [ ] Add retention policy for webhook payload storage.

### Wave 5.3: Template Extension Points

- [ ] Add interfaces for provider-specific webhook verifiers.
- [ ] Add interfaces for provider-specific event normalizers.
- [ ] Add interfaces for provider-specific dispatch maps.
- [ ] Add example placeholder provider adapters without real client coupling.
- [ ] Add documentation for adding a new integration provider into the template.

## Phase 6: Background Jobs, Scheduling, And Workflow Execution

### Wave 6.1: Worker Platform

- [x] Replace the demo job with a real job base pattern.
- [x] Add a standard job envelope carrying correlation ID, tenant/org context, retry count, and metadata.
- [x] Add shared job logging utilities.
- [x] Add worker startup resource initialization.
- [x] Add worker shutdown cleanup.
- [ ] Add queue naming conventions.
- [ ] Add job serialization guidance.
- [ ] Add concurrency guidance per queue type.

### Wave 6.2: Retry, Backoff, And Failure Handling

- [ ] Add default retry policies for transient failures.
- [ ] Add exponential backoff and jitter behavior.
- [ ] Add explicit non-retryable error categories.
- [ ] Add dead-letter queue or equivalent failed-job storage.
- [ ] Add max-attempt policy and surfaced failure reason tracking.
- [ ] Add automatic alerting hooks for repeated job failures.
- [ ] Add manual replay tooling for failed jobs.
- [ ] Add idempotent job execution guidance.

### Wave 6.3: Workflow And Process Orchestration

- [ ] Define a workflow abstraction for multi-step processes.
- [ ] Add support for step state tracking.
- [ ] Add support for compensation or rollback steps where relevant.
- [ ] Add support for delayed retries and waiting steps.
- [ ] Add support for chaining jobs across a workflow.
- [ ] Add support for resumable workflows after process restarts.
- [ ] Add guidance on when to use workflow state in DB versus transient queue state.

### Wave 6.4: Scheduled And Recurring Work

- [ ] Decide whether the template includes a scheduler by default.
- [ ] Add scheduler runtime entrypoint if included.
- [ ] Add recurring job registration patterns.
- [ ] Add clock drift and duplicate execution protections.
- [ ] Add observability for scheduled job runs.
- [ ] Add example placeholder recurring maintenance jobs.

## Phase 7: External Integration Foundation

### Wave 7.1: HTTP Client Platform

- [ ] Create a shared outbound HTTP client layer.
- [ ] Add standard timeout defaults.
- [ ] Add retry behavior for safe transient failures.
- [ ] Add backoff and jitter behavior for outbound calls.
- [ ] Add circuit breaker or degradation hooks.
- [ ] Add rate-limit response handling helpers.
- [ ] Add authentication hooks for bearer tokens, API keys, OAuth refresh, and custom auth.
- [ ] Add request and response logging with redaction.
- [ ] Add correlation propagation headers.
- [ ] Add instrumentation hooks for tracing and metrics.

### Wave 7.2: Integration Contracts

- [ ] Define base classes or protocols for integration clients.
- [ ] Define a normalized integration error taxonomy.
- [ ] Define standard result models for external calls.
- [ ] Define integration-specific settings registration patterns.
- [ ] Add sandbox versus production mode guidance for providers.
- [ ] Add secret storage and rotation guidance for provider credentials.
- [ ] Add sync checkpoint and cursor storage patterns.

### Wave 7.3: Resilience And Fallbacks

- [ ] Add fallback behavior patterns for external outages.
- [ ] Add partial failure handling patterns.
- [ ] Add compensating action guidance.
- [ ] Add queue-based deferred retries for unavailable providers.
- [ ] Add runbooks for degraded third-party dependencies.

## Phase 8: Observability And Operational Excellence

### Wave 8.1: Logging

- [ ] Standardize structured logging shape across API and workers.
- [ ] Move production logging defaults toward stdout/stderr for container-native deployments.
- [ ] Decide whether file logging remains optional or is removed from defaults.
- [ ] Add correlation IDs, request IDs, job IDs, workflow IDs, and provider event IDs to logs.
- [ ] Add log redaction policies for secrets and sensitive payload fields.
- [ ] Add clear log level guidance by environment.

### Wave 8.2: Error Monitoring

- [ ] Harden Sentry initialization and configuration.
- [ ] Add Sentry support for worker processes.
- [ ] Add Sentry tagging for environment, release, request ID, job ID, and tenant/org where applicable.
- [ ] Add Sentry filtering and scrubbing rules.
- [ ] Add release tracking guidance.
- [ ] Add sampling guidance for high-volume systems.

### Wave 8.3: Metrics And Tracing

- [ ] Add Prometheus-compatible metrics support or equivalent metrics strategy.
- [ ] Add request metrics.
- [ ] Add queue and job metrics.
- [ ] Add webhook ingestion metrics.
- [ ] Add outbound integration metrics.
- [ ] Add failure-rate and retry metrics.
- [ ] Add tracing hooks or OpenTelemetry support.
- [ ] Add distributed trace propagation guidance across request, job, and outbound call boundaries.

### Wave 8.4: Runbooks And Alerting

- [ ] Define minimum production alerts for API failures, worker failures, and backlog growth.
- [ ] Add an operational runbook for webhook failures.
- [ ] Add an operational runbook for queue backlog incidents.
- [ ] Add an operational runbook for third-party outages.
- [ ] Add an operational runbook for migration failures.
- [ ] Add an operational runbook for secret rotation.

## Phase 9: Testing And Quality Gates

### Wave 9.1: Local Test Reliability

- [x] Fix the current test environment workflow so dev dependencies install and tests run reliably.
- [x] Fix current type-check failures and keep the baseline green.
- [ ] Add a simple project task runner or make targets for common commands.
- [ ] Add deterministic test settings separate from normal runtime settings.
- [ ] Add isolated test DB and Redis patterns.
- [ ] Add test factories and fixtures for common platform objects.

### Wave 9.2: Automated Test Coverage

- [x] Add unit tests for platform utilities and configuration validation.
- [ ] Add integration tests for API startup and lifespan behavior.
- [ ] Add integration tests for DB connectivity and migrations.
- [ ] Add integration tests for Redis and queue initialization.
- [ ] Add tests for webhook verification and replay protection.
- [ ] Add tests for idempotency logic.
- [ ] Add tests for retry and dead-letter logic.
- [ ] Add tests for workflow orchestration behavior.
- [ ] Add tests for health and readiness endpoints.
- [ ] Add tests for auth and authorization flows.

### Wave 9.3: CI Hardening

- [x] Update GitHub Actions so lint, type-check, and tests run in a reliable, reproducible way.
- [x] Add strict MkDocs documentation build verification to CI.
- [ ] Add service containers or compose-based CI for Postgres and Redis.
- [ ] Add migration checks to CI.
- [ ] Add coverage reporting.
- [ ] Add dependency audit checks.
- [ ] Add secret scanning checks.
- [ ] Add optional security/static analysis checks.
- [ ] Add build verification for production images.

## Phase 10: Deployment, Runtime, And Release Engineering

### Wave 10.1: Container Hardening

- [ ] Replace dev-oriented Dockerfiles with production-grade Dockerfiles.
- [ ] Use a non-root runtime user.
- [ ] Ensure only necessary application files are copied into the image.
- [ ] Ensure migrations and scripts are available in the image where needed.
- [ ] Add healthchecks to container definitions.
- [ ] Add restart policies and stop-grace periods.
- [ ] Add resource limit guidance.
- [ ] Add image size optimization where reasonable.

### Wave 10.2: Runtime Topology

- [ ] Define the standard deployable components: API, worker, optional scheduler, migrations job, reverse proxy.
- [ ] Add deployment examples for container-only environments.
- [ ] Add deployment examples for orchestrated environments if in scope.
- [ ] Add a migration job pattern separate from app startup.
- [ ] Add release promotion guidance across environments.
- [ ] Add blue-green or rolling deploy considerations.

### Wave 10.3: Secrets And Environment Management

- [ ] Remove unsafe example values from defaults where possible.
- [ ] Add `.env.example` files that are safe and realistic.
- [ ] Add guidance for secret manager integration.
- [ ] Add secret rotation guidance for JWT keys and provider credentials.
- [ ] Add release and environment variable documentation for every required setting.

### Wave 10.4: Backups, Recovery, And Maintenance

- [ ] Add backup strategy guidance for Postgres.
- [ ] Add restore validation guidance.
- [ ] Add retention guidance for Redis-backed transient data versus durable database state.
- [ ] Add maintenance tasks for token blacklists, event retention, dead-letter cleanup, and audit pruning.
- [ ] Add disaster recovery notes for template adopters.

## Phase 11: Documentation And Template Experience

### Wave 11.1: Template Documentation

- [ ] Rewrite the README around template adoption rather than generic boilerplate claims.
- [ ] Add a clear "what this template is for" section.
- [ ] Add a clear "what this template does not include" section.
- [ ] Add a quickstart for local development.
- [ ] Add a quickstart for production deployment.
- [ ] Add a guide for adding a new client integration.
- [ ] Add a guide for adding a new webhook provider.
- [ ] Add a guide for adding a new workflow.
- [ ] Add a guide for adding a new background job.

### Wave 11.2: Operational Docs

- [ ] Add architecture diagrams.
- [ ] Add sequence diagrams for webhook ingestion and job execution.
- [ ] Add deployment diagrams.
- [ ] Add observability setup documentation.
- [ ] Add runbooks referenced in the observability phase.
- [ ] Add troubleshooting guides for the most common failures.

### Wave 11.3: GitHub Template Readiness

- [ ] Clean up repository branding for template reuse.
- [ ] Add template-friendly issue and PR templates if desired.
- [ ] Add release/versioning guidance for the template itself.
- [ ] Add a changelog strategy.
- [ ] Add contribution guidance for maintaining the shared template.
- [ ] Confirm the repo is ready to be marked as a GitHub template repository.

## Phase 12: Final Production Readiness Sweep

### Wave 12.1: Validation Sweep

- [ ] Run a full local bootstrap from scratch and document every required step.
- [ ] Run a full staging-style deployment from scratch and validate the happy path.
- [ ] Validate migrations-only startup.
- [ ] Validate readiness and liveness behavior.
- [ ] Validate background worker processing.
- [ ] Validate webhook ingestion and replay flow using placeholder adapters.
- [ ] Validate failure handling and dead-letter flow.
- [ ] Validate observability output in logs and Sentry.
- [ ] Validate CI from a clean checkout.

### Wave 12.2: Template Acceptance Criteria

- [ ] A cloned repo can boot locally with documented steps.
- [ ] A cloned repo can be deployed without editing core platform code.
- [ ] A new client integration can be added in the designated extension points.
- [ ] A new webhook provider can be added without reworking the core ingestion model.
- [ ] Platform failures are observable, retryable where appropriate, and operationally diagnosable.
- [ ] The repository documentation matches the actual implementation.
- [ ] The baseline quality gates are green.

## Recommended Build Order

We should execute the work in this order:

1. Phase 1: Core Application Hardening
2. Phase 2: Database And Persistence Platform
3. Phase 9 Wave 9.1: Local Test Reliability
4. Phase 3: API Platform And Request Pipeline
5. Phase 4: Authentication, Authorization, And Security
6. Phase 6 Wave 6.1 and 6.2: Worker Platform, Retry, Backoff, Failure Handling
7. Phase 5: Webhook Ingestion Platform
8. Phase 7: External Integration Foundation
9. Phase 8: Observability And Operational Excellence
10. Phase 10: Deployment, Runtime, And Release Engineering
11. Phase 11: Documentation And Template Experience
12. Phase 12: Final Production Readiness Sweep

## Immediate Next Tasks

These are the best first tasks to start with:

- [x] Remove automatic schema creation from startup and move fully to migrations.
- [x] Harden the settings model and make unsafe production defaults fail fast.
- [x] Fix the local and CI test baseline so tests and type checks are reliable.
- [x] Refactor the project structure into clearer platform-oriented modules.
- [x] Replace the demo worker job pattern with a reusable job base and retry model.

---

## Session Report — 2026-04-03

### What was built
- Added a reusable `db-migrate-verify` command that applies the canonical Alembic config, upgrades to `head`, and runs Alembic drift detection.
- Added a dedicated GitHub Actions migration-check workflow backed by PostgreSQL so schema application and model drift are validated in CI.
- Added the baseline Alembic revision for the current template schema and documented the new verification flow in the database migrations guide.
- Added regression coverage for the migration verification command and for redundant unique constraints on primary-key `id` columns.

### Issues encountered
| Issue | How it was fixed |
|-------|-----------------|
| Mypy detected `src/scripts/migrations.py` under two module names after the new verifier imported it with an absolute package path. | Switched the verifier to a package-relative import so mypy resolves the script package consistently. |
| The first clean-database migration verification failed because the template had no committed baseline revision and several models declared `unique=True` on primary-key `id` columns, causing persistent schema drift. | Generated the initial Alembic revision, removed the redundant primary-key uniqueness flags from the affected models, updated the revision to match, and re-ran the verification against a fresh PostgreSQL instance. |

### Quality gate results
- ruff: pass
- mypy: pass
- pytest: 137 passed, 0 failed

### Current state of the template
The template now has a repeatable migration verification path for both local checks and GitHub Actions: a clean PostgreSQL database can be migrated to `head`, and Alembic confirms there is no uncommitted schema drift afterward. The repository also now has a committed baseline revision for the current core tables instead of relying on implicit metadata state. Database rollback guidance, backfill patterns, and destructive-change rollout rules are still not documented, and the broader persistence patterns planned for later Phase 2 waves remain incomplete.

### What remains
- [ ] Add rollback guidance for migration failures.
- [ ] Add data backfill guidance and script patterns.
- [ ] Add rules for destructive schema changes and expand-contract rollouts.

---

## Session Report — 2026-04-03

### What was built
- Expanded the database migrations guide with an explicit rollback decision framework covering downgrade, forward-fix, and backup-restore recovery paths.
- Added a reusable backfill script scaffold and operational rules for batch sizing, dry runs, checkpoints, and script-scoped database sessions.
- Documented expand-contract rollout rules for destructive schema changes and updated the database overview page to point template users at the stronger migration-safety guidance.

### Issues encountered
| Issue | How it was fixed |
|-------|-----------------|
| None | None |

### Quality gate results
- ruff: pass
- mypy: pass
- pytest: 137 passed, 0 failed

### Current state of the template
Phase 2 Wave 2.2 is now fully documented end to end: the template has a canonical Alembic workflow, clean migration verification, and explicit guidance for rollback planning, operational backfills, and phased destructive schema rollouts. The database platform is solid for migration safety and developer workflow, but the persistence patterns planned for webhook events, idempotency, workflow runs, and other high-volume automation tables are still not scaffolded yet.

### What remains
- [ ] Add a table pattern for inbound webhook events.
- [ ] Add a table pattern for idempotency keys.
- [ ] Add a table pattern for workflow executions or process runs.

---

## Session Report — 2026-04-03

### What was built
- Added a reusable platform-owned `WebhookEvent` table pattern for inbound webhook deliveries, including lifecycle fields, payload storage, and operational lookup indexes.
- Added an Alembic migration for the new webhook-event ledger and regression tests covering metadata registration, index posture, payload column types, and primary-key uniqueness behavior.
- Added database documentation for automation persistence patterns and updated the database model docs so platform-owned tables are documented separately from domain models.

### Issues encountered
| Issue | How it was fixed |
|-------|-----------------|
| `uv run db-migrate-verify` initially failed because no local PostgreSQL server was listening on `localhost:5432`. | Started a temporary local PostgreSQL container, re-ran migration verification successfully, and then stopped the container to return the environment to its prior state. |

### Quality gate results
- ruff: pass
- mypy: pass
- pytest: 140 passed, 0 failed

### Current state of the template
The template now includes a reusable inbound webhook-event ledger as a shared platform primitive instead of leaving webhook persistence to ad hoc project code. That pattern is migration-backed, documented, and covered by focused regression tests, so cloned projects have a stable starting point for durable webhook intake. The broader automation persistence layer is still incomplete: idempotency keys, workflow execution records, job-history records, and other high-volume operational tables have not been scaffolded yet.

### What remains
- [ ] Add a table pattern for idempotency keys.
- [ ] Add a table pattern for workflow executions or process runs.
- [ ] Add a table pattern for job state history where needed.

---

## Session Report — 2026-04-03

### What was built
- Added a reusable platform-owned `WorkflowExecution` table pattern with trigger correlation, lifecycle timestamps, retry posture, and structured input/output context fields.
- Added an Alembic migration plus regression tests covering metadata registration, lookup indexes, payload/status columns, and primary-key uniqueness posture for the new workflow-execution ledger.
- Expanded the automation-persistence documentation and database overview/model guides so the workflow-execution pattern is documented alongside the webhook-event and idempotency ledgers.

### Issues encountered
| Issue | How it was fixed |
|-------|-----------------|
| `uv run db-migrate-verify` initially failed because no local PostgreSQL server was listening on `localhost:5432`. | Started a temporary local PostgreSQL container using the template defaults, reran migration verification successfully, and then stopped the container to return the environment to its prior state. |

### Quality gate results
- ruff: pass
- mypy: pass
- pytest: 146 passed, 0 failed

### Current state of the template
The template now includes three reusable automation persistence ledgers in the shared platform layer: webhook events, idempotency keys, and workflow executions. Those patterns are migration-backed, exported through the canonical database surface, documented for template adopters, and covered by focused regression tests. The broader automation persistence story is still incomplete, because job-state history, integration sync checkpoints, audit/operational event ledgers, dead-letter records, and retention guidance for high-volume tables are not scaffolded yet.

### What remains
- [ ] Add a table pattern for job state history where needed.
- [ ] Add a table pattern for integration sync checkpoints.
- [ ] Add a table pattern for audit logs or operational events.

---

## Session Report — 2026-04-03

### What was built
- Added a reusable platform-owned `JobStateHistory` table pattern for durable background-job execution tracking, including queue/runtime metadata, lifecycle timestamps, retry posture, payload/context fields, and lightweight error detail.
- Added an Alembic migration plus regression tests covering metadata registration, lookup indexes, payload column types, status defaults, and primary-key uniqueness posture for the new job-history ledger.
- Expanded the automation-persistence, database overview/models, and background-task docs so template users can understand when to use `job_state_history` versus `workflow_execution`.

### Issues encountered
| Issue | How it was fixed |
|-------|-----------------|
| The initial `JobStateHistory` model shape had a required field ordered after defaulted fields, which caused SQLAlchemy's dataclass integration to fail during test collection. | Reordered the required fields and normalized the model, migration, tests, and docs around one final schema contract before rerunning the quality gates. |
| `uv run db-migrate-verify` initially failed because no local PostgreSQL server was listening on `localhost:5432`. | Started a temporary local PostgreSQL container, reran migration verification successfully, and then stopped the container to return the environment to its prior state. |

### Quality gate results
- ruff: pass
- mypy: pass
- pytest: 149 passed, 0 failed

### Current state of the template
The template now includes four reusable automation persistence ledgers in the shared platform layer: webhook events, idempotency keys, workflow executions, and job state history. Those patterns are migration-backed, exported through the canonical database surface, documented for template adopters, and covered by focused regression tests. The automation persistence story is still incomplete overall, because integration sync checkpoints, audit or operational event ledgers, dead-letter records, and retention guidance for high-volume tables remain to be scaffolded.

### What remains
- [ ] Add a table pattern for integration sync checkpoints.
- [ ] Add a table pattern for audit logs or operational events.
- [ ] Add a table pattern for dead-letter or failed message records.

## Session Report — 2026-04-03

### What was built
- Added a reusable platform-owned `IntegrationSyncCheckpoint` table pattern for durable integration cursors, high-water marks, short-lived lease coordination, and lightweight failure state.
- Added an Alembic migration plus regression tests covering metadata registration, lookup indexes, uniqueness posture, JSON payload columns, and default values for the new checkpoint ledger.
- Expanded the database automation-patterns, models, and database overview docs so template users can understand when and how to use the shared integration sync checkpoint table.

### Issues encountered
| Issue | How it was fixed |
|-------|-----------------|
| `uv run db-migrate-verify` initially failed because no local PostgreSQL server was listening on `localhost:5432`. | Started a temporary local PostgreSQL 16 container using the template defaults, reran migration verification successfully, and then stopped the container to return the environment to its prior state. |

### Quality gate results
- ruff: pass
- mypy: pass
- pytest: 152 passed, 0 failed
- additional verification: `uv run db-migrate-verify` pass; `uv run mkdocs build --strict` pass

### Current state of the template
The template now includes five reusable automation persistence ledgers in the shared platform layer: webhook events, idempotency keys, workflow executions, job state history, and integration sync checkpoints. Those patterns are migration-backed, exported through the canonical database surface, documented for template adopters, and covered by focused regression tests. The automation persistence story is still incomplete overall, because audit or operational event ledgers, dead-letter records, and retention guidance for high-volume tables remain to be scaffolded.

### What remains
- [ ] Add a table pattern for audit logs or operational events.
- [ ] Add a table pattern for dead-letter or failed message records.
- [ ] Add retention and cleanup guidance for high-volume event tables.

---

## Session Report — 2026-04-03

### What was built
- Re-verified the existing `workflow_execution` and `job_state_history` persistence patterns end to end across models, Alembic revisions, canonical exports, tests, and docs.
- Confirmed that the current Wave 2.3 roadmap checkboxes already match the repository state, so no implementation or checklist corrections were needed in this session.
- Re-ran the persistence verification stack, including migration drift detection against a real PostgreSQL instance and a strict MkDocs build, to keep the roadmap status backed by fresh evidence.

### Issues encountered
| Issue | How it was fixed |
|-------|-----------------|
| `uv run db-migrate-verify` initially failed because no local PostgreSQL server was listening on `localhost:5432`. | Started a temporary local PostgreSQL 16 container using the template defaults, reran migration verification successfully, and then stopped the container to return the environment to its prior state. |

### Quality gate results
- ruff: pass
- mypy: pass
- pytest: 149 passed, 0 failed
- additional verification: `uv run db-migrate-verify` pass; `uv run mkdocs build --strict` pass

### Current state of the template
The template still has four verified automation persistence ledgers in the shared platform layer: webhook events, idempotency keys, workflow executions, and job state history. Those patterns are migration-backed, exported through the canonical database surface, documented for template adopters, and covered by focused regression tests. The remaining Wave 2.3 work is still unfinished, because integration sync checkpoints, audit or operational event ledgers, dead-letter records, and retention guidance for high-volume tables have not been scaffolded yet.

### What remains
- [ ] Add a table pattern for integration sync checkpoints.
- [ ] Add a table pattern for audit logs or operational events.
- [ ] Add a table pattern for dead-letter or failed message records.

---

## Session Report — 2026-04-03

### What was built
- Added a reusable platform-owned `AuditLogEvent` table pattern for append-friendly audit and operational events, including actor/subject correlation, severity, status, retention windows, and compact JSON context fields.
- Added a reusable platform-owned `DeadLetterRecord` table pattern for failed-message and dead-letter triage, including namespace-scoped uniqueness, retry timing, payload snapshots, and operator-friendly failure metadata.
- Expanded the automation-persistence documentation with both new ledger contracts and added retention and cleanup guidance for high-volume event tables, then closed out the remaining Phase 2 roadmap items.

### Issues encountered
| Issue | How it was fixed |
|-------|-----------------|
| The two Wave 1 workers each produced a valid Alembic revision, but both initially pointed at the same parent revision, which created a multi-head migration graph. | Linearized the revision chain by making the dead-letter migration depend on the newly added audit-event revision before running migration verification. |
| `uv run db-migrate-verify` initially failed because no local PostgreSQL server was listening on `localhost:5432`. | Started a temporary local PostgreSQL 16 container using the template defaults, reran migration verification successfully, and then stopped the container to return the environment to its prior state. |

### Quality gate results
- ruff: pass
- mypy: pass
- pytest: 158 passed, 0 failed
- additional verification: `uv run db-migrate-verify` pass; `uv run mkdocs build --strict` pass

### Current state of the template
Phase 2 is now complete. The template includes reusable persistence ledgers for webhook events, idempotency keys, workflow executions, job state history, integration sync checkpoints, audit or operational events, and dead-letter records, all backed by Alembic revisions, canonical exports, focused regression tests, and database documentation. The database platform is now solid as a reusable foundation, while the next major gaps shift into Phase 3 API-platform conventions and request-pipeline standards.

### What remains
- [ ] Define a consistent router structure for public, internal, ops, admin, and webhook endpoints.
- [ ] Define versioning rules for the API.
- [ ] Add standard request and response envelope guidance where appropriate.

---

## Session Report — 2026-04-03

### What was built
- Added reusable API architecture primitives for version registries, route-group builders, typed pagination/filter/sort query models, response envelopes, and centralized exception-to-response mapping.
- Refactored the existing v1 routers to delegate reusable orchestration to canonical domain services for auth, users, posts, tiers, and rate limits instead of embedding that logic directly in route handlers.
- Rewrote the API documentation around the new template contract, including an architecture guide, updated pagination/exception/versioning guidance, and project-structure notes for the new `domain.services` surface.

### Issues encountered
| Issue | How it was fixed |
|-------|-----------------|
| The first pagination helper test assumed FastCRUD would derive `total_count` from a `count` key, but `fastcrud.paginated_response` only honors `total_count`. | Normalized `build_paginated_api_response(...)` so it upgrades legacy `count` inputs into `total_count` before calling the FastCRUD helper, then reran the full verification stack. |

### Quality gate results
- ruff: pass
- mypy: pass
- pytest: 171 passed, 0 failed
- docs build: pass (`uv run mkdocs build --strict`)

### Current state of the template
Phase 3 Wave 3.1 is now in place. The API boundary has explicit version and route-group builders, typed list-endpoint contracts, standardized machine-readable error payloads, and a reusable domain service layer so the routers stay thin and template-friendly. Request IDs, cross-request correlation propagation, and the broader request-safety work planned for Wave 3.2 are still outstanding.

### What remains
- [ ] Standardize request IDs and correlation IDs across all requests.
- [ ] Propagate correlation context into background jobs and outbound integrations.
- [ ] Add trusted proxy handling.

---

## Session Report — 2026-04-03

### What was built
- Re-verified the existing Phase 2 Wave 2.3 persistence work across models, Alembic revisions, canonical exports, focused regression tests, and database documentation.
- Confirmed that the roadmap checklist was already aligned with the repository state for audit-log events, dead-letter records, and retention guidance, so no implementation or checkbox corrections were needed.
- Re-ran the full verification stack for this scope, including migration drift detection against PostgreSQL and a strict documentation build, to keep the verified template state current.

### Issues encountered
| Issue | How it was fixed |
|-------|-----------------|
| `uv run db-migrate-verify` initially failed because no local PostgreSQL server was listening on `localhost:5432`. | Started a temporary local PostgreSQL 16 container using the template defaults, reran migration verification successfully, and then stopped the container to return the environment to its prior state. |

### Quality gate results
- ruff: pass
- mypy: pass
- pytest: 158 passed, 0 failed

### Current state of the template
Phase 2 remains complete and verified. The template includes reusable persistence ledgers for webhook events, idempotency keys, workflow executions, job state history, integration sync checkpoints, audit or operational events, and dead-letter records, all backed by Alembic revisions, canonical exports, focused regression tests, and database documentation. The next major gaps now sit in Phase 3, where API-platform conventions and request-pipeline standards still need to be formalized.

### What remains
- [ ] Define a consistent router structure for public, internal, ops, admin, and webhook endpoints.
- [ ] Define versioning rules for the API.
- [ ] Add standard request and response envelope guidance where appropriate.
