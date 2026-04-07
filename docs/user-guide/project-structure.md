# Project Structure

The template now uses a clearer boundary-oriented layout so future client projects have obvious extension points from day one.

## Canonical App Layout

```text
src/
├── app/
│   ├── main.py                 # API entrypoint
│   ├── scheduler.py            # Future scheduler runtime placeholder
│   ├── api/                    # HTTP routers and dependencies
│   ├── domain/                 # Business entities, schemas, repositories
│   ├── platform/               # Shared runtime, security, persistence, admin, middleware
│   ├── shared/                 # Framework-agnostic shared utilities
│   ├── workers/                # Background worker entrypoints and job functions
│   ├── integrations/           # Provider adapters, contracts, and outbound HTTP client
│   ├── webhooks/               # Inbound webhook ingestion primitives and provider adapters
│   ├── workflows/              # Placeholder extension point for orchestrated processes
│   ├── core/                   # Legacy compatibility modules
│   ├── crud/                   # Legacy compatibility modules
│   ├── models/                 # Legacy compatibility modules
│   ├── schemas/                # Legacy compatibility modules
│   ├── middleware/             # Legacy compatibility modules
│   ├── admin/                  # Legacy compatibility modules
│   └── logs/                   # Runtime log output
├── migrations/                 # Alembic migrations
└── scripts/                    # Operational bootstrap scripts
```

The `platform`, `shared`, `domain`, `workers`, `integrations`, `webhooks`, and `workflows` packages are the canonical structure going forward. Legacy paths remain in place temporarily as compatibility shims while the template transitions.

## Boundary Responsibilities

### `api/`

- Owns FastAPI routers, versioning, and request dependencies.
- Should remain thin and delegate business logic downward.

### `domain/`

- Owns reusable business entities and application-facing persistence surfaces.
- `domain.models` exposes SQLAlchemy models.
- `domain.schemas` exposes Pydantic request and response models.
- `domain.repositories` exposes reusable data-access primitives.
- `domain.services` exposes reusable orchestration that routers can call without reaching into `crud_*` modules directly.

### `platform/`

- Owns cross-cutting runtime concerns shared across all client builds.
- Includes settings, app factory/lifespan wiring, security helpers, logging, database primitives, middleware, admin hooks, cache/queue helpers, and exception types.

### `shared/`

- Owns framework-agnostic helper code that can be imported anywhere without bringing in runtime state.
- Use it for pure formatting, normalization, parsing, and data-shaping helpers that do not depend on FastAPI, Redis, SQLAlchemy sessions, or application settings.

### `workers/`

- Owns worker runtime entrypoints and background job functions.
- Canonical worker entrypoint: `src.app.workers.settings.WorkerSettings`

### `integrations/`

- Owns the shared outbound HTTP client layer, integration contracts, and provider-specific adapter surfaces.
- `http_client/` provides `TemplateHttpClient` with template-owned defaults for timeouts, connection pooling, correlation propagation, structured logging, retry, circuit breaking, rate-limit handling, authentication hooks, and instrumentation protocols.
- `contracts/` provides base classes and protocols (`BaseIntegrationClient`, `IntegrationClient`), a normalized error taxonomy (`IntegrationError` hierarchy with `classify_http_error`), typed result models (`IntegrationResult`, `PaginatedIntegrationResult`, `BulkIntegrationResult`), settings registration patterns (`IntegrationSettings`, `IntegrationSettingsRegistry`), sandbox/dry-run patterns (`DryRunMixin`, `SandboxBehavior`), secret management primitives (`SecretProvider`, `CredentialStatus`), and data sync checkpoint patterns (`SyncCursor`, `SyncOperation`, `SyncProgress`).
- Provider-specific adapters should subclass `BaseIntegrationClient` rather than constructing raw httpx clients, so they inherit the template's production defaults, observability contract, and standard error handling.
- See the [Integrations guide](integrations/index.md) and [Integration Contracts](integrations/contracts.md) for usage, settings, and provider adapter patterns.

### `webhooks/`

- Owns reusable inbound webhook ingestion primitives and future provider-adapter surfaces.
- Keep raw-body verification helpers, `WebhookIngestionRequest`, `build_webhook_ingestion_request(...)`, `ingest_webhook_event(...)`, replay-protection helpers, signature-verifier contracts, `WebhookEventPersistenceRequest`, `webhook_event_store`, future normalizer interfaces, and provider placeholder packages here instead of scattering them between `api/` and `platform/`.
- HTTP route handlers still live under `src/app/api/v1/`, but provider-specific webhook logic should delegate into this boundary once implemented.

### `workflows/`

- Reserved for multi-step orchestration and domain workflows.
- Keep workflow coordination here instead of embedding it in routers or repositories.

## Shared Utilities Vs Platform Primitives

This template distinguishes between reusable helper code and runtime-owned infrastructure.

### Put code in `shared/` when

- It is framework-agnostic and side-effect free.
- It does not depend on app settings, connection pools, request state, or background worker context.
- It can be unit tested without booting FastAPI or initializing Redis, the database, or logging configuration.

### Put code in `platform/` when

- It owns runtime behavior or shared infrastructure state.
- It wraps FastAPI dependencies, settings, logging, middleware, database access, cache/queue clients, rate limiting, or security concerns.
- It is part of the production runtime surface that downstream projects should import intentionally.

### Keep `core/utils/` as compatibility only

- Existing modules under `src/app/core/utils/` remain in place so current imports keep working.
- New runtime-facing helpers should be added under `src/app/platform/`, not `src/app/core/utils/`.
- New framework-agnostic helpers should be added under `src/app/shared/`.

## Naming Conventions

Use these conventions for new template work so the repo reads consistently even while some compatibility shims remain in place.

### Modules

- Use lowercase snake_case filenames everywhere.
- Route modules use plural resource names for collection-backed APIs like `users.py` and `posts.py`, or singular concern names for operational/auth endpoints like `health.py`, `login.py`, and `logout.py`.
- Domain model and schema backing modules use singular entity filenames like `user.py`, `post.py`, and `tier.py`.
- Platform modules use singular capability names like `config.py`, `database.py`, `logger.py`, and `security.py`.
- Service modules, when introduced, should use the `<capability>_service.py` pattern.

### Routers

- Every route module exports a local variable named `router`.
- Parent router modules alias imports as `<feature>_router` before calling `include_router`.
- Keep one router module per resource or operational concern.

### Services

- The template now exposes a canonical `src.app.domain.services` surface.
- Service modules live in the owning boundary and use the `<capability>_service.py` pattern, classes `<Capability>Service`, and singleton helpers `capability_service`.
- Keep routers thin by delegating reusable orchestration to services, workflows, or repositories instead of embedding business logic directly in endpoints.

### Repositories

- Canonical repository imports go through `src.app.domain.repositories`.
- Repository instances use lower_snake_case names with the `_repository` suffix, for example `user_repository`.
- The legacy `crud_*` exports remain available as compatibility aliases while the template continues its internal transition.

### Schemas

- Public Pydantic contracts are imported from `src.app.domain.schemas`.
- Schema classes use singular entity or concern prefixes with role-based suffixes such as `UserCreate`, `UserRead`, `UserUpdate`, and `JobEnvelope`.
- Shared reusable infrastructure schemas keep descriptive suffixes like `TimestampSchema`, `UUIDSchema`, and `TokenData`.

## Typical Import Paths

Use these canonical imports in new template work:

```python
from src.app.platform.config import settings
from src.app.platform.application import create_application, lifespan_factory
from src.app.platform.cache import cache
from src.app.platform.database import Base, async_get_db
from src.app.platform.rate_limit import rate_limiter
from src.app.domain.models import User
from src.app.domain.schemas import UserRead
from src.app.domain.repositories import user_repository
from src.app.domain.services import user_service
from src.app.webhooks import (
    WebhookIngestionRequest,
    WebhookSignatureVerifier,
    build_webhook_ingestion_request,
    ingest_webhook_event,
)
from src.app.workers.settings import WorkerSettings
```

## Runtime Entry Points

- Default app factory: `src.app.main:create_app`
- Default ASGI application: `src.app.main:app`
- Worker runtime settings: `src.app.workers.settings:WorkerSettings`
- Worker runtime helper: `src.app.workers.settings:start_worker`
- Future scheduler placeholder: `src.app.scheduler:start_scheduler`

Use the app factory when you want runtime construction to stay explicit, and keep `src.app.main:app` available for ASGI servers or compatibility with existing tooling.

## Migrations And Startup

- Application startup is managed through `src.app.main`.
- Database metadata is sourced from the canonical domain boundary in `src.app.domain`.
- Schema changes are applied through Alembic in `src/migrations/`, not during app boot.

## Legacy Compatibility

The older `core`, `crud`, `models`, `schemas`, `middleware`, and `admin` paths are still present so existing imports inside the template continue to work while the new structure becomes the default. New code should prefer the canonical boundary packages.

## Testing

The `tests/` directory verifies both behavior and structure:

- Configuration validation and runtime safety
- Lifespan and startup behavior
- Canonical module boundary imports
- Endpoint and service behavior
- Services can be disabled via configuration
- Clear interfaces between components

### Scalability

- Async/await throughout the application
- Connection pooling for database access
- Caching and background task support
- Horizontal scaling ready

## Navigation Tips

### Finding Code

- **Models** → Canonical surface: `src/app/domain/models.py`; current backing modules: `src/app/models/`
- **API Endpoints** → `src/app/api/v1/`
- **Schemas** → Canonical surface: `src/app/domain/schemas.py`; current backing modules: `src/app/schemas/`
- **Repositories** → Canonical surface: `src/app/domain/repositories.py`; current backing modules: `src/app/crud/`
- **Platform Runtime** → `src/app/platform/`
- **Shared Utilities** → `src/app/shared/`
- **Worker Runtime** → `src/app/workers/`
- **Webhook Ingestion** → `src/app/webhooks/`
- **Business Logic** → Keep reusable logic in services, workflows, and repositories rather than directly in routers

### Adding New Features

1. **Model** → Add or extend `src/app/models/<entity>.py`, then export through `src/app/domain/models.py`
2. **Schema** → Add or extend `src/app/schemas/<entity>.py`, then export through `src/app/domain/schemas.py`
3. **Repository** → Add or extend `src/app/crud/crud_<resources>.py`, then expose the canonical alias from `src/app/domain/repositories.py`
4. **Shared Utility** → Add `src/app/shared/<capability>.py` only if the helper stays framework-agnostic and side-effect free
5. **Platform Primitive** → Add `src/app/platform/<capability>.py` if the helper owns runtime wiring, state, or infrastructure access
6. **Service or Workflow** → If reusable orchestration is needed, add `<capability>_service.py` in the owning boundary, export it through `src/app/domain/services.py`, or place multi-step coordination in `src/app/workflows/`
7. **Webhook Primitive** → Add shared ingestion or provider-adapter code under `src/app/webhooks/`, and keep versioned HTTP receivers in `src/app/api/v1/`
8. **API** → Add endpoints in `src/app/api/v1/<resources>.py` and export `router`
9. **Migration** → Generate with Alembic

### Understanding Data Flow

```text
Request → API Router → Dependency Resolution → Service or Workflow → Repository → Model → Database
Response ← API Response ← Schema ← Service or Workflow ← Repository ← Query Result ← Database
```

This structure provides a solid foundation for building scalable, maintainable APIs while keeping the codebase organized and easy to navigate. 
