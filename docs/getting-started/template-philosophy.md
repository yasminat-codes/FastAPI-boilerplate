# Template Philosophy

This page documents the design principles, scope boundaries, and standing decisions that shape the template. If you are evaluating whether this template fits your project, or if you are about to extend it, start here.

## What This Template Is

A production-ready FastAPI backend foundation. It provides the platform layer that every serious backend needs — auth, database, background jobs, webhooks, observability, deployment — so that each new project starts from a verified baseline instead of from scratch.

Clone it, add your domain logic, deploy it.

## What This Template Is Not

- **Not a client-specific system.** No business rules, dashboards, or integrations that belong to a single company live here.
- **Not a frontend.** This is a backend-only template. Pair it with whatever frontend you prefer.
- **Not a microservice scaffold.** It ships a single-service architecture with a worker sidecar. If you need service decomposition, add that in your derived project.
- **Not locked to a cloud provider.** It uses Docker, PostgreSQL, and Redis — standard infrastructure that runs anywhere.

## Core Principles

### Extension over modification

The template provides protocols, base classes, and documented hooks for the things that change between projects: webhook providers, integration adapters, background jobs, and workflow steps. When you add a new integration or webhook source, you implement a contract — you do not modify the platform internals.

### Migrations only, no auto-created schema

The template does not call `create_all()` at startup. Database schema changes go through Alembic migrations, always. This is a non-negotiable production discipline: every schema change is versioned, reviewable, and reversible.

### Observable by default

Structured logging, Sentry error monitoring, Prometheus metrics, and OpenTelemetry tracing are wired into the platform layer. You do not need to add observability plumbing to your domain code — it is already there. Metrics and tracing are opt-in via optional dependencies so they add zero overhead when not needed.

### Async-safe, failure-aware defaults

Database connections use pool hardening with pre-ping, bounded retries, and configurable timeouts. Background jobs have retry and backoff built in. Webhook ingestion includes signature verification, replay protection, and dead-letter handling. The shared outbound HTTP client ships with a circuit breaker and rate-limit awareness. Failures are controlled and logged, not silent.

### Local development stays easy

Production hardening does not come at the cost of developer experience. `uv sync && uv run uvicorn src.app.main:app --reload` gets you running locally. Docker Compose handles the full stack. The setup script picks the right configuration for your environment.

## Python Version Policy

The template targets **Python 3.11** as the minimum supported version (`requires-python = ">=3.11, <4"`). This provides:

- `TaskGroup` and `ExceptionGroup` for structured concurrency.
- Improved error messages and startup performance.
- Full compatibility with current async SQLAlchemy, Pydantic v2, and FastAPI releases.

When Python 3.12 or later introduces features the template benefits from, the minimum version will be bumped and documented in the changelog.

## Dependency Support Policy

The template pins minimum versions for its core dependencies and is tested against the latest compatible releases.

| Dependency | Role | Minimum | Policy |
|------------|------|---------|--------|
| FastAPI | Web framework | 0.109+ | Track latest minor within 90 days of release |
| SQLAlchemy | ORM and database | 2.0+ | Stay on 2.x, adopt async improvements as they land |
| Pydantic | Validation and settings | 2.12+ | Stay on 2.x |
| asyncpg | PostgreSQL driver | 0.29+ | Track latest compatible |
| Redis (py-redis) | Cache, queue, rate-limit | 5.0+ | Track latest compatible |
| ARQ | Background jobs | 0.25+ | Default queue backend, see architecture decisions |
| Alembic | Migrations | 1.13+ | Track latest compatible |
| structlog | Structured logging | 25.1+ | Track latest compatible |
| Sentry SDK | Error monitoring | 2.0+ | Track latest compatible |

Optional dependencies (Prometheus, OpenTelemetry) follow the same policy: pin a working minimum, test against latest, and update when upstream changes require it.

## Core vs Optional Features

### Always enabled (core)

These ship with every clone and are part of the verified baseline:

- FastAPI app factory with async lifespan management
- PostgreSQL via async SQLAlchemy 2.0 with pool hardening
- Redis for caching, job queuing, and rate limiting
- Stateless JWT auth with refresh rotation, RBAC, API key support, and logout via token blacklist
- ARQ background jobs with retry, backoff, dead-letter, and result retention
- Webhook ingestion with signature verification, replay protection, and idempotency
- Workflow orchestration with step tracking and compensation
- Shared outbound HTTP client with circuit breaker and retry
- Alembic migrations with CI drift detection
- Structured logging with context propagation and field redaction
- Sentry error monitoring (requires DSN configuration)
- MkDocs documentation site
- Production Dockerfiles (local, staging, production)
- Health and readiness endpoints

### Opt-in via feature flags

These are built into the platform but toggled off or on per deployment:

| Feature | Setting | Default |
|---------|---------|---------|
| CRUDAdmin browser panel | `CRUD_ADMIN_ENABLED` | Enabled |
| Client-side cache headers | `FEATURE_CLIENT_CACHE_ENABLED` | Enabled |
| Auth routes (login/logout) | `FEATURE_API_AUTH_ROUTES_ENABLED` | Enabled |
| User management routes | `FEATURE_API_USERS_ENABLED` | Enabled |
| Post routes (example domain) | `FEATURE_API_POSTS_ENABLED` | Enabled |
| Tier routes (example domain) | `FEATURE_API_TIERS_ENABLED` | Enabled |
| Rate limit routes | `FEATURE_API_RATE_LIMITS_ENABLED` | Enabled |

### Opt-in via optional dependencies

These add zero overhead when not installed:

| Feature | Install group | What it adds |
|---------|---------------|-------------|
| Prometheus metrics | `pip install .[metrics]` | `/metrics` endpoint, request/job/webhook counters and histograms |
| OpenTelemetry tracing | `pip install .[tracing]` | W3C Trace Context propagation, OTLP export |
| Both | `pip install .[observability]` | Metrics and tracing together |

## What Gets Customized Per Project

When you clone this template for a new project, you will typically:

- **Replace** the example domain models, schemas, and routes (posts, tiers) with your actual business entities.
- **Add** webhook providers for the services your project integrates with (Stripe, GitHub, Slack, etc.) by implementing the provider adapter contract.
- **Add** integration clients for external APIs by implementing the integration client contract.
- **Add** background jobs for your domain-specific async processing.
- **Add** workflows for multi-step business processes.
- **Configure** environment variables for your database, Redis, JWT secrets, Sentry DSN, and external service credentials.
- **Update** branding: repository name, `APP_NAME`, docs site labels, support channels.

What you should **not** need to modify:

- The platform layer (app factory, lifespan, middleware, security, logging, database primitives).
- The webhook ingestion pipeline (signature verification, replay protection, dead-letter handling).
- The background job infrastructure (ARQ settings, retry, backoff).
- The shared HTTP client and its resilience stack.
- The observability plumbing (metrics, tracing, Sentry wiring).
- The deployment assets (Dockerfiles, compose files, NGINX config) — configure them, do not rewrite them.
