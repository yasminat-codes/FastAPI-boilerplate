# API Development

The template's API boundary is now organized around a small set of reusable platform contracts:

- versioned routers rooted at `/api/<version>`
- explicit route groups for `public`, `ops`, `admin`, `internal`, and `webhooks`
- thin routers that delegate reusable orchestration to domain services
- typed pagination, filtering, and sorting query models
- consistent machine-readable error payloads
- request-safety guardrails for size limits, timeouts, raw-body verification, and log redaction

## Canonical API Surface

The current API boundary lives in `src/app/api/`:

```text
src/app/api/
├── __init__.py          # API root router + version registry
├── routing.py           # Version + route-group helpers
├── query_params.py      # Pagination, filter, and sort contracts
├── contracts.py         # Reusable response envelopes
├── errors.py            # Exception-to-response mapping
├── dependencies.py      # Shared request dependencies
└── v1/                  # Version 1 routers
```

At runtime the default template mounts:

- `/api/v1/...` for version 1 endpoints
- `/api/v1/health` and `/api/v1/ready` as ops endpoints
- public resource routes such as `/api/v1/users` and `/api/v1/{username}/posts`

Dedicated `/admin`, `/internal`, and `/webhooks` route-group prefixes are reserved inside each version so cloned projects can grow into those surfaces without inventing a second routing pattern later.

## How Routers Should Work

Routers in this template should stay thin:

1. Parse request bodies and query parameters.
2. Resolve auth and infrastructure dependencies.
3. Delegate reusable orchestration to domain services.
4. Return resource models, paginated responses, or message envelopes.

The intended flow is:

```text
Request -> API router -> domain service -> repository -> model/database
```

That keeps reusable business and orchestration logic out of the HTTP layer while still letting the API boundary own HTTP-specific concerns like pagination response formatting and cache decorators.

## Response And Error Contracts

Use these response patterns:

- raw resource models for straightforward reads and creates
- `ApiMessageResponse` for command-style endpoints that primarily confirm an action
- `ApiDataResponse[T]` when a response needs a stable `data` envelope plus optional metadata
- `ApiErrorResponse` for all handled error cases

The application factory registers the template's exception handlers automatically, so `NotFoundException`, `ForbiddenException`, `BadRequestException`, validation failures, and unhandled errors now all return a consistent machine-readable payload.

## Next Guides

- [Architecture](architecture.md): route groups, versioning rules, services, repositories, and list-endpoint conventions
- [Request Safety](request-safety.md): request size limits, timeout guidance, raw-body webhook verification, and log redaction
- [Endpoints](endpoints.md): endpoint examples and resource patterns
- [Pagination](pagination.md): typed pagination, filtering, and sorting helpers
- [Exceptions](exceptions.md): standardized error payloads and custom exceptions
- [Versioning](versioning.md): how to add a new API version without breaking the template pattern
