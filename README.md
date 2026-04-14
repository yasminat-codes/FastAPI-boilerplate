<h1 align="center">FastAPI Template</h1>
<p align="center" markdown=1>
  <i>Production-ready FastAPI backend foundation. Clone it, extend it with your domain logic, deploy it.</i>
</p>

<p align="center">
  <a href="docs/index.md">
    <img src="docs/assets/FastAPI-boilerplate.png" alt="Rocket illustration for the FastAPI template." width="25%" height="auto">
  </a>
</p>

<p align="center">
📚 <a href="docs/index.md">Docs</a> · 🛠️ <a href="docs/community.md">Support</a>
</p>

<p align="center">
  <a href="https://fastapi.tiangolo.com">
      <img src="https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi" alt="FastAPI">
  </a>
  <a href="https://www.postgresql.org">
      <img src="https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL">
  </a>
  <a href="https://redis.io">
      <img src="https://img.shields.io/badge/Redis-DC382D?logo=redis&logoColor=fff&style=for-the-badge" alt="Redis">
  </a>
</p>

## What This Template Is For

A production-ready FastAPI backend foundation for client projects. It provides auth, database, webhooks, background jobs, observability, and deployment assets out of the box. Clone it, extend it with your domain logic, deploy it. It's proven in production across SaaS platforms and internal tools.

## Template Identity

This repository's canonical template name is `FastAPI Template`, and the source repository/package baseline is `fastapi-template`. Maintain the source repository as a neutrally branded GitHub Template repository so adopters can use **Use this template** to create their own product-specific repositories, then replace the package metadata, support links, maintainer contacts, and visual branding before publishing their derived project.

## Template Philosophy

- **Extension over modification** — add webhook providers, integrations, and jobs by implementing contracts, not by editing platform internals.
- **Migrations only** — no `create_all()` at startup. Every schema change goes through Alembic.
- **Observable by default** — structured logging, Sentry, Prometheus metrics, and OpenTelemetry tracing are wired in. Metrics and tracing are opt-in via extras so they add zero overhead when not needed.
- **Async-safe, failure-aware** — pool hardening, bounded retries, circuit breakers, dead-letter handling, and replay protection are built into the platform layer.
- **Local dev stays easy** — `uv sync && uv run uvicorn src.app.main:app --reload` gets you running.

For the full philosophy, version policy, and architecture decisions, see the [Template Philosophy](docs/getting-started/template-philosophy.md) and [Architecture Decisions](docs/getting-started/architecture-decisions.md) docs.

## What This Template Does Not Include

- **No client-specific business logic, integrations, or dashboards** — this is a foundation, not a finished product.
- **No frontend** — this is a backend-only template.
- **No multi-service or microservice scaffold** — see the docs if you need architecture pointers for distributed systems.
- **No coupling to a single cloud provider** — Docker and standard PostgreSQL/Redis.
- **No AI/ML-specific scaffold** — add that in your derived project if needed.

## What You Get

- **FastAPI app factory** with async SQLAlchemy 2.0 and Pydantic v2
- **Stateless JWT auth** with refresh rotation, RBAC, API key support, and logout via token blacklist
- **ARQ background jobs** with retry, backoff, dead-letter, and result retention tuning
- **Webhook ingestion** with signature verification, replay protection, and idempotency
- **Workflow orchestration** with step tracking, compensation, and resumability
- **Shared outbound HTTP client** with circuit breaker, retry, and rate-limit handling
- **Prometheus metrics** for request, job, webhook, and failure tracking
- **OpenTelemetry tracing** with W3C Trace Context propagation
- **Sentry error monitoring** (opt-in)
- **Production Dockerfiles** — local Uvicorn, staging Gunicorn/Uvicorn, production NGINX
- **Docker Compose** for local, staging, and production configurations
- **Alembic migrations** with CI drift detection
- **MkDocs documentation site**
- **Optional CRUDAdmin** browser panel for data management (opt-in)

## Quickstart

Clone the template:

```bash
git clone https://github.com/<your-org>/<your-repo>
cd <your-repo>
```

Run the setup script to choose your deployment environment (local, staging, or production):

```bash
./setup.py
# or: ./setup.py local | ./setup.py staging | ./setup.py production
```

The script copies the right Docker, compose, and `.env` files for your environment.

Start the application:

```bash
docker compose up
```

Access your app:
- **Local**: http://127.0.0.1:8000 → [API docs](http://127.0.0.1:8000/docs)
- **Staging**: http://127.0.0.1:8000 (production-like with Gunicorn)
- **Production**: http://localhost (behind NGINX)

Create your first admin user:

```bash
docker compose run --rm create_superuser
```

Run database migrations:

```bash
uv run db-migrate upgrade head
```

Or run locally without Docker:

```bash
uv sync && uv run db-migrate upgrade head && uv run uvicorn src.app.main:app --reload
```

Full setup details, environment examples, and PostgreSQL/Redis instructions are in the [installation guide](docs/getting-started/installation.md).

## Configuration

Create `src/.env` with your app, database, JWT, and environment settings. Prefer `DATABASE_URL=postgresql://...` for your database connection; fall back to composed `POSTGRES_*` settings if needed. See the [configuration guide](docs/getting-started/configuration.md) for a copy-paste example and production guidance.

Key settings:
- `ENVIRONMENT=local|staging|production` — controls API docs exposure
- `DATABASE_URL` — your PostgreSQL connection string
- `SECRET_KEY` — set this before production
- `JWT_*` — optional issuer/audience enforcement and key rotation
- `WORKER_*` — ARQ queue naming, concurrency, retry tuning
- `WEBHOOK_*` — verification, replay window, payload retention
- `SENTRY_*`, `METRICS_*`, `TRACING_*` — observability toggles
- `FEATURE_*` — route group toggles
- `CRUD_ADMIN_ENABLED` — opt-in browser admin UI
- `HTTP_CLIENT_*` — timeouts, pooling, retry backoff, circuit breaker

Full configuration matrix and examples: [docs/getting-started/configuration.md](docs/getting-started/configuration.md)

## Branding Checklist

Before publishing a derived project, update the template metadata to match your product:

- Rename the repository, package metadata, and docs site labels.
- Replace placeholder repo URLs and support channels with your own.
- Update `APP_NAME`, docs assets, and contact information to match the adopting team.

## Extending the Template

- **Add a new background job**: [docs/user-guide/background-tasks/index.md](docs/user-guide/background-tasks/index.md)
- **Add a new webhook provider**: [docs/user-guide/webhooks/adding-provider.md](docs/user-guide/webhooks/adding-provider.md)
- **Add a new workflow**: [docs/user-guide/guides/adding-workflow.md](docs/user-guide/guides/adding-workflow.md)
- **Add a new client integration**: [docs/user-guide/guides/adding-integration.md](docs/user-guide/guides/adding-integration.md)

## Common Tasks

```bash
# run locally with reload (without Docker)
uv sync && uv run db-migrate upgrade head && uv run uvicorn src.app.main:app --reload

# create and apply Alembic migrations
uv run db-migrate revision --autogenerate && uv run db-migrate upgrade head

# prune expired token blacklist rows
uv run cleanup-token-blacklist

# run the ARQ worker runtime
uv run arq src.app.workers.settings.WorkerSettings

# install and verify the docs toolchain
uv sync --group docs && uv run mkdocs build --strict

# audit the locked dependency set
UV_CACHE_DIR=/tmp/uv-cache uv export --frozen --all-groups --format requirements.txt --no-emit-project --no-header --no-hashes --no-annotate --output-file /tmp/requirements-audit.txt
uvx --from pip-audit pip-audit -r /tmp/requirements-audit.txt --progress-spinner off

# run the secret scan
uv run pre-commit run gitleaks --all-files

# serve docs locally
uv run mkdocs serve
```

More examples in the [first run guide](docs/getting-started/first-run.md).

## Contributing

Read [contributing](CONTRIBUTING.md).

## References

This project was inspired by a few projects, it's based on them with things changed to the way I like (and pydantic, sqlalchemy updated)

- [`Full Stack FastAPI and PostgreSQL`](https://github.com/tiangolo/full-stack-fastapi-postgresql) by @tiangolo himself
- [`FastAPI Microservices`](https://github.com/Kludex/fastapi-microservices) by @kludex which heavily inspired this template
- [`Async Web API with FastAPI + SQLAlchemy 2.0`](https://github.com/rhoboro/async-fastapi-sqlalchemy) for sqlalchemy 2.0 ORM examples
- [`FastaAPI Rocket Boilerplate`](https://github.com/asacristani/fastapi-rocket-boilerplate/tree/main) for docker compose

## License

[`MIT`](LICENSE.md)

## Support

Use the support channels documented in [docs/community.md](docs/community.md). Template adopters should replace those defaults with their own repository issue tracker, discussions space, and maintainer contacts.
