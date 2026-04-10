<h1 align="center"> Benav Labs FastAPI Template</h1>
<p align="center" markdown=1>
  <i>Production-ready FastAPI backend foundation. Clone it, extend it with your domain logic, deploy it.</i>
</p>

<p align="center">
  <a href="https://benavlabs.github.io/FastAPI-boilerplate">
    <img src="docs/assets/FastAPI-boilerplate.png" alt="Purple Rocket with FastAPI Logo as its window." width="25%" height="auto">
  </a>
</p>

<p align="center">
📚 <a href="https://benavlabs.github.io/FastAPI-boilerplate/">Docs</a> · 🧠 <a href="https://deepwiki.com/benavlabs/FastAPI-boilerplate">DeepWiki</a> · 💬 <a href="https://discord.com/invite/TEmPs22gqB">Discord</a>
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
  <a href="https://deepwiki.com/benavlabs/FastAPI-boilerplate">
      <img src="https://img.shields.io/badge/DeepWiki-1F2937?style=for-the-badge&logoColor=white" alt="DeepWiki">
  </a>
</p>

## What This Template Is For

A production-ready FastAPI backend foundation for client projects. It provides auth, database, webhooks, background jobs, observability, and deployment assets out of the box. Clone it, extend it with your domain logic, deploy it. It's proven in production across SaaS platforms and internal tools.

## What This Template Does Not Include

- **No client-specific business logic, integrations, or dashboards** — this is a foundation, not a finished product.
- **No frontend** — this is a backend-only template.
- **No multi-service or microservice scaffold** — see the docs if you need architecture pointers for distributed systems.
- **No coupling to a single cloud provider** — Docker and standard PostgreSQL/Redis.
- **No AI/ML pipeline scaffold** — if you need that, look at FastroAI instead.

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
git clone https://github.com/<you>/FastAPI-boilerplate
cd FastAPI-boilerplate
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

Full setup details, environment examples, and PostgreSQL/Redis instructions are in the [docs](https://benavlabs.github.io/FastAPI-boilerplate/getting-started/installation/).

## Configuration

Create `src/.env` with your app, database, JWT, and environment settings. Prefer `DATABASE_URL=postgresql://...` for your database connection; fall back to composed `POSTGRES_*` settings if needed. See the [docs](https://benavlabs.github.io/FastAPI-boilerplate/getting-started/configuration/) for a copy-paste example and production guidance.

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

Full configuration matrix and examples: [docs/getting-started/configuration](https://benavlabs.github.io/FastAPI-boilerplate/getting-started/configuration/)

## Extending the Template

- **Add a new background job**: [docs/user-guide/background-tasks](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/background-tasks/)
- **Add a new webhook provider**: [docs/user-guide/webhooks](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/webhooks/)
- **Add a new workflow**: [docs/user-guide/workflows](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/workflows/)
- **Add a new client integration**: [docs/user-guide/integrations](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/integrations/)

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

More examples in the [docs](https://benavlabs.github.io/FastAPI-boilerplate/getting-started/first-run/).

## Contributing

Read [contributing](CONTRIBUTING.md).

## References

This project was inspired by a few projects, it's based on them with things changed to the way I like (and pydantic, sqlalchemy updated)

- [`Full Stack FastAPI and PostgreSQL`](https://github.com/tiangolo/full-stack-fastapi-postgresql) by @tiangolo himself
- [`FastAPI Microservices`](https://github.com/Kludex/fastapi-microservices) by @kludex which heavily inspired this boilerplate
- [`Async Web API with FastAPI + SQLAlchemy 2.0`](https://github.com/rhoboro/async-fastapi-sqlalchemy) for sqlalchemy 2.0 ORM examples
- [`FastaAPI Rocket Boilerplate`](https://github.com/asacristani/fastapi-rocket-boilerplate/tree/main) for docker compose

## License

[`MIT`](LICENSE.md)

## Contact

Benav Labs – [benav.io](https://benav.io), [discord server](https://discord.com/invite/TEmPs22gqB)

<hr>
<a href="https://benav.io">
  <img src="https://github.com/benavlabs/fastcrud/raw/main/docs/assets/benav_labs_banner.png" alt="Powered by Benav Labs - benav.io"/>
</a>
