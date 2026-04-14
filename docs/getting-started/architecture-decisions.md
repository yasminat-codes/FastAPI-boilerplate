# Architecture Decisions

This page records the key architecture decisions made during the template's development. Each decision explains what was chosen, why, and what the alternatives were. If you are extending the template or evaluating it for your project, these decisions tell you what assumptions the platform makes.

## Single-Service With Worker Sidecar

**Decision:** The template ships as a single API service with a separate ARQ worker process. It does not scaffold multiple services, API gateways, or service meshes.

**Why:** Most backend projects start as a single service. Premature decomposition adds operational complexity (networking, deployment, observability, data consistency) without delivering value until the project outgrows a single codebase. The template provides clear internal boundaries (`api/`, `domain/`, `platform/`, `integrations/`, `workers/`) that make future extraction straightforward when the time comes.

**If you need service decomposition:** Extract boundaries into separate services in your derived project. The internal package structure is designed to make this possible without rewriting business logic.

## ARQ As The Default Queue Backend

**Decision:** Background jobs use [ARQ](https://arq-docs.helpmanual.io/), an async-native Redis-backed job queue built on Python's `asyncio`.

**Why:** ARQ is lightweight, async-first, and uses the same Redis infrastructure the template already depends on for caching and rate limiting. It avoids the operational weight of Celery (separate broker, result backend, flower monitoring) while providing the primitives production systems need: retry with backoff, result retention, job timeouts, and concurrent worker limits.

**Alternatives considered:**

- **Celery** — more mature ecosystem and broader protocol support, but heavier operationally and not async-native. A valid choice for projects that need RabbitMQ, priority queues, or canvas workflows.
- **Dramatiq** — simpler than Celery with good defaults, but smaller community and less async integration.
- **TaskIQ** — async-native like ARQ with more broker options, but younger and less battle-tested at the time of this decision.

**If ARQ does not fit your project:** The worker layer is isolated in `src/app/workers/`. Replacing ARQ with another queue backend requires changing the worker settings, job registration, and queue client — the domain logic and job functions stay the same.

## Scheduled Jobs: Placeholder, Not Built In

**Decision:** The template includes a `scheduler.py` placeholder but does not ship a running scheduler process or cron-style job execution.

**Why:** Scheduling strategies vary too much between projects to justify a single default. Some projects use ARQ's built-in cron support. Others use external schedulers (Kubernetes CronJobs, systemd timers, cloud-native schedulers). Shipping a running scheduler would impose one strategy and create maintenance burden for projects that do not need it.

**How to add scheduling:** The background tasks documentation covers how to wire scheduled execution using ARQ cron functions, external triggers, or a dedicated scheduler process.

## Runtime Architecture

**Decision:** The template targets a four-component runtime:

| Component | Process | Scaling |
|-----------|---------|---------|
| **API server** | Uvicorn (local) or Gunicorn managing Uvicorn workers (staging/production) | Horizontal — add instances behind a load balancer |
| **ARQ worker** | `arq src.app.workers.settings.WorkerSettings` | Horizontal — add instances to increase job throughput |
| **PostgreSQL** | External managed or containerized | Per your infrastructure |
| **Redis** | External managed or containerized (three logical databases: cache, queue, rate-limit) | Per your infrastructure |

An optional **NGINX reverse proxy** is included for production deployments. An optional **scheduler** process can be added when the project needs it.

**Why this topology:** It separates request handling from background processing so that slow jobs do not block API responses. Each component scales independently. The API server and worker share the same codebase and database, which keeps data access simple until the project grows large enough to justify further decomposition.

## Extension Points For Client-Specific Work

The template defines explicit extension contracts so that client-specific logic plugs in without modifying platform internals.

### Webhook providers

Implement `WebhookProviderAdapter` to add a new webhook source. The adapter handles signature verification, event normalization, and dispatch routing. The ingestion pipeline (replay protection, idempotency, persistence, dead-letter) is handled by the platform.

See: [Adding a Webhook Provider](../user-guide/webhooks/adding-provider.md)

### Integration clients

Implement `BaseIntegrationClient` to add a new outbound integration. The contract provides health checking, error taxonomy, result typing, sandbox/dry-run behavior, and credential management. The shared HTTP client provides retry, circuit breaker, and rate-limit handling.

See: [Adding a Client Integration](../user-guide/guides/adding-integration.md)

### Background jobs

Define a new job function in `workers/` and register it in the ARQ settings. The `WorkerJob` base class provides structured logging, retry configuration, and metric instrumentation.

See: [Adding a Background Job](../user-guide/guides/adding-background-job.md)

### Workflows

Add a new workflow in `workflows/` using the step-tracking and compensation primitives. Workflows support resumability and partial failure handling.

See: [Adding a Workflow](../user-guide/guides/adding-workflow.md)

### Domain entities

Add models in `domain/models.py`, schemas in `domain/schemas.py`, repositories in `domain/repositories.py`, services in `domain/services.py`, and routes in `api/v1/`. The example post and tier entities demonstrate the full pattern.

## Multi-Tenant Posture

**Decision:** The template is **single-tenant by default** with **tenant-ready primitives** available for multi-tenant projects.

**What is provided:**

- `TenantContext` dataclass with `tenant_id` and `organization_id` fields.
- Automatic extraction of tenant context from JWT claims and API key principals.
- Tenant context propagation into request context, structured logs, and background jobs.
- Per-API-key-principal tenant and organization scoping.

**What is not provided:**

- No tenant-scoped database columns or row-level security at the template level.
- No tenant isolation middleware.
- No tenant provisioning or onboarding flow.

**Why:** Tenant isolation strategies vary dramatically between projects. Some use schema-per-tenant, some use row-level filtering, some use separate databases. Shipping any one strategy would be wrong for most adopters. The template provides the context extraction and propagation primitives so that whichever isolation strategy you choose can consume tenant identity from a single source.

**If your project is multi-tenant:** Add a `tenant_id` column to your domain models, implement row-level filtering in your repository layer, and use the `TenantContext` from the request context to scope queries. The extraction and propagation plumbing is already in place.

## Observability Standard

**Decision:** The template ships four observability layers, each independently configurable:

| Layer | Technology | Status | Configuration |
|-------|-----------|--------|---------------|
| **Structured logging** | structlog + Rich | Always enabled | `LOGGING_*` settings |
| **Error monitoring** | Sentry SDK | Always installed, requires DSN | `SENTRY_*` settings |
| **Metrics** | Prometheus client | Optional dependency | `METRICS_*` settings, install `.[metrics]` |
| **Tracing** | OpenTelemetry | Optional dependency | `TRACING_*` settings, install `.[tracing]` |

**Why this stack:**

- **structlog** provides structured, contextual logging that works in development (Rich console) and production (JSON output) without changing application code.
- **Sentry** is the most widely adopted error monitoring service and integrates with minimal configuration.
- **Prometheus** is the de facto standard for metrics in containerized environments, and the client library has no runtime dependencies beyond the standard library.
- **OpenTelemetry** is the emerging standard for distributed tracing, with broad vendor support (Jaeger, Zipkin, Datadog, Honeycomb, etc.) via the OTLP exporter.

**Why metrics and tracing are optional:** Not every project needs them from day one, and their dependencies add weight. Making them opt-in via extras (`.[metrics]`, `.[tracing]`, `.[observability]`) means the base template installs fast and the overhead is zero until you need it.

## Deployment Target Surfaces

**Decision:** The template ships deployment assets for three environments out of the box:

| Environment | Server | Reverse proxy | Use case |
|-------------|--------|---------------|----------|
| **Local** | Uvicorn with `--reload` | None | Development and debugging |
| **Staging** | Gunicorn managing Uvicorn workers | None | Production-like testing |
| **Production** | Gunicorn managing Uvicorn workers | NGINX | Real deployments |

Each environment has its own Dockerfile, Docker Compose file, and `.env` template in the `scripts/` directory. The `setup.py` script copies the right set of files for your chosen environment.

**Why these three:** Local needs fast iteration with auto-reload. Staging needs production-like behavior without the reverse proxy complexity. Production needs a hardened multi-worker server behind a reverse proxy that handles TLS termination, static files, and connection management.

**Cloud-specific deployment:** The template does not include Kubernetes manifests, Terraform modules, or cloud-specific deployment scripts. These vary too much between organizations to justify a single default. The Docker images and compose files provide a portable foundation that works with any orchestrator.

## Repository Name And Template Positioning

**Decision:** The repository is named `fastapi-template` and is intended to be used as a **GitHub template repository** that teams clone for new projects.

**Branding:** The template ships with generic placeholder branding (`FastAPI Template`, `Template Maintainers`). When you clone it for a project, update `APP_NAME`, docs labels, support channels, and repository metadata to match your product.

**Not a library or framework:** This is not a pip-installable package that you import into an existing project. It is a starting point that you clone and own. Once cloned, the derived project diverges from the template — there is no upstream merge path.
