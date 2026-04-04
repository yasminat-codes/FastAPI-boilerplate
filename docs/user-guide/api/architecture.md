# API Architecture

Phase 3 establishes one reusable API contract for the template instead of leaving each cloned project to invent its own router layout.

## Router Structure

The default API root is still `/api`, and each supported version is mounted underneath it:

```text
/api
└── /v1
```

Inside a version, the template now reserves these route groups:

| Group | Prefix inside `/api/<version>` | Purpose |
|------|-------------------------------|---------|
| `public` | none | External application APIs such as users, posts, tiers, auth, and similar resource routes |
| `ops` | none | Lightweight liveness and readiness endpoints |
| `admin` | `/admin` | Future admin-only HTTP surfaces |
| `internal` | `/internal` | Trusted internal endpoints such as runtime diagnostics and future service-to-service hooks |
| `webhooks` | `/webhooks` | Future inbound webhook receivers |

The current code wires this through:

- `src/app/api/routing.py`
- `src/app/api/__init__.py`
- `src/app/api/v1/__init__.py`

## Versioning Rules

The template currently supports `v1` through:

- `ApiVersion`
- `SUPPORTED_API_VERSIONS`
- `build_version_router(...)`
- `build_api_router(...)`

When a cloned project needs `v2`, follow this pattern:

1. Create `src/app/api/v2/`.
2. Add a `build_v2_router(...)` function.
3. Register `ApiVersion.V2` in the version registry.
4. Keep `v1` stable for existing clients.
5. Move only breaking changes into `v2`.

Additive changes such as new optional fields, new endpoints, or new filter parameters should stay in the existing version when they do not break clients.

## Thin Router Pattern

Routers should own HTTP concerns, not reusable orchestration. In practice that means:

- request parsing and dependency injection stay in the router
- service orchestration moves to `src/app/domain/*_service.py`
- repositories remain behind `src/app/domain/repositories.py`
- persistence details stay out of route handlers

The current template ships canonical services for auth, users, posts, tiers, and rate limits, all re-exported through `src/app/domain/services.py`.

## Repository Pattern

Canonical data-access imports go through `src.app.domain.repositories`:

```python
from src.app.domain.repositories import user_repository
```

Services, not routers, should normally depend on repositories directly. This keeps the API surface resilient if the template later swaps CRUD helpers, adds richer repository types, or introduces workflow-level orchestration around the same data.

## Response Envelopes

Use these rules by default:

- Return resource models directly for normal reads and creates when no wrapper adds useful value.
- Use `ApiMessageResponse` for command-style endpoints like update, delete, or logout.
- Use `ApiDataResponse[T]` when the response needs a stable top-level `data` envelope plus metadata.
- Let the registered exception handlers produce `ApiErrorResponse` for handled failures.

That is why the template currently uses direct resource responses for reads and create endpoints, but command endpoints now declare `ApiMessageResponse`.

## Pagination, Filtering, And Sorting

List endpoints should use the shared query-param models in `src/app/api/query_params.py`:

- `PaginationParams`
- `SortParams`
- typed resource filters such as `UserListFilters` or `PostListFilters`
- `build_paginated_api_response(...)`

The router should:

1. resolve typed pagination/filter/sort params
2. validate `sort_by` against the owning service's allowed fields
3. pass plain filter/sort kwargs into the service
4. format the final paginated payload at the API boundary

That keeps list-endpoint conventions stable across resource types without forcing every domain service to understand FastAPI-specific query models.

## Error Mapping

`create_application(...)` now registers the template's canonical error handlers automatically.

Handled errors return:

```json
{
  "error": {
    "code": "not_found",
    "message": "User not found"
  }
}
```

Validation errors add `details`, and unhandled exceptions are normalized to `internal_server_error` without leaking raw stack traces in the response body.

## Request IDs And Correlation IDs

`RequestContextMiddleware` now standardizes two tracing headers for every HTTP request:

- `X-Request-ID` identifies the current HTTP request. If a caller sends it, the template preserves it; otherwise the middleware generates a UUID4 value.
- `X-Correlation-ID` identifies the broader workflow or upstream call chain. If a caller sends it, the template preserves it; otherwise it defaults to the current `request_id`.

The middleware also:

- stores the canonical values on `request.state.request_context`, `request.state.request_id`, and `request.state.correlation_id`
- binds both IDs into structured log context alongside `method`, `path`, `client_host`, and `status_code`
- echoes both headers on every HTTP response so browsers, API clients, and operators can correlate failures

Treat `request_id` as request-local and use `correlation_id` as the durable hand-off value across async work and outbound traffic.

Trusted proxy handling is opt-in. When `PROXY_HEADERS_ENABLED=true` and the connecting peer is listed in `PROXY_HEADERS_TRUSTED_PROXIES`, the template lets Uvicorn's `ProxyHeadersMiddleware` honor `X-Forwarded-For` and `X-Forwarded-Proto` before request context is bound. That means `request.client`, `request.url.scheme`, and the structured-log `client_host` field all reflect the proxied client only for explicitly trusted ingress hops; untrusted peers keep the raw socket client and scheme.

The current template now exposes two reusable propagation hooks through `src.app.platform.request_context`:

- `WorkerJob.enqueue(...)` automatically falls back to the currently bound `correlation_id` when the caller does not pass one explicitly.
- `build_correlation_headers(...)` and `merge_correlation_headers(...)` build outbound `X-Request-ID` / `X-Correlation-ID` headers from the active structured-log context so future provider clients can preserve correlation without copying request-state logic.

## Health And Diagnostics

The template now reserves three distinct runtime-health surfaces:

- `/api/v1/health` is the lightweight liveness endpoint. It reports only process-local metadata like status, environment, version, and timestamp. Keep it cheap so load balancers and container runtimes can probe it frequently.
- `/api/v1/ready` is the API readiness endpoint. It checks the template-owned dependencies the API process needs before it should receive traffic: database connectivity, cache Redis, queue Redis, and rate-limiter Redis.
- `/api/v1/internal/health` is the internal diagnostics endpoint. It returns the same readiness posture plus safe per-dependency summaries and the current ARQ worker heartbeat state from the configured queue.

Use the internal endpoint only behind trusted ingress, VPN, or future service-to-service auth. It is designed for operators and automation, not for unauthenticated public clients.

The dependency summaries are intentionally safe. They explain which probe succeeded or failed without echoing DSNs, hostnames, usernames, secrets, or raw exception payloads.

## Metrics Planning

Metrics collection is intentionally planned here but deferred to Phase 8, where the template will choose the concrete Prometheus/OpenTelemetry implementation.

Until then, treat these rules as the reserved template posture:

- Keep `/api/v1/health` and `/api/v1/ready` focused on health, not metrics scraping.
- Prefer a dedicated `/metrics` surface or an internal-only ingress mapping once metrics are added.
- Do not expose future metrics publicly by default; treat them like other operator-only diagnostics.
