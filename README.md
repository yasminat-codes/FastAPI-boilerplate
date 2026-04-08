<h1 align="center"> Benav Labs FastAPI boilerplate</h1>
<p align="center" markdown=1>
  <i><b>Batteries-included FastAPI starter</b> with production-ready defaults, optional modules, and clear docs.</i>
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

## Features

* ⚡️ Fully async FastAPI + SQLAlchemy 2.0
* 🧱 Pydantic v2 models & validation
* 🔐 Stateless JWT auth scaffold (access + refresh), cookie-delivered refresh tokens
* 👮 Rate limiter + tiers (free/pro/etc.)
* 🧰 FastCRUD for efficient CRUD & pagination
* 🧑‍💼 **CRUDAdmin**: minimal admin panel (optional)
* 🚦 ARQ background jobs (Redis)
* 🪝 Canonical raw-body webhook ingestion dependency for signature-verified providers
* 🛡️ Provider-agnostic webhook signature verification interfaces
* 🗃️ Reusable webhook-event persistence helpers backed by the shared inbox ledger
* 📨 Reusable webhook intake pipeline for receive, validate, persist, acknowledge, enqueue
* ♻️ Replay-protection helpers for recent webhook deliveries
* 🧊 Redis caching (server + client-side headers)
* 📊 Opt-in Prometheus metrics (request, job, webhook, outbound, failure/retry)
* 🔭 Opt-in OpenTelemetry tracing with W3C Trace Context propagation
* 🌐 Configurable CORS middleware for frontend integration
* 🐳 One-command Docker Compose
* 🚀 NGINX & Gunicorn recipes for prod

## Why and When to use it

**Perfect if you want:**

* A pragmatic starter with auth, CRUD, jobs, caching and rate-limits
* **Sensible defaults** with the freedom to opt-out of modules
* **Docs over boilerplate** in README - depth lives in the site

> **Not a fit** if you need a monorepo microservices scaffold - [see the docs](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/project-structure/) for pointers.

**What you get:**

* **App**: FastAPI app factory, [env-aware docs](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/development/) exposure
* **Auth**: [JWT access/refresh scaffold](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/authentication/), logout via token blacklist
* **DB**: Postgres + SQLAlchemy 2.0, [Alembic migrations](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/database/)
* **CRUD**: [FastCRUD generics](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/database/crud/) (get, get_multi, create, update, delete, joins)
* **Caching**: [decorator-based endpoints cache](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/caching/); client cache headers
* **Queues**: [ARQ worker](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/background-tasks/) (async jobs), Redis connection helpers
* **Rate limits**: [per-tier + per-path rules](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/rate-limiting/)
* **Admin**: [CRUDAdmin views](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/admin-panel/) for common models (optional)

This is what we've been using in production apps. Several applications running in production started from this boilerplate as their foundation - from SaaS platforms to internal tools. It's proven, stable technology that works together reliably. Use this as the foundation for whatever you want to build on top.

> **Building an AI SaaS?** Skip even more setup with [**FastroAI**](https://fastro.ai) - our production-ready template with AI integration, payments, and frontend included.

## TL;DR - Quickstart

Use the template on GitHub, create your repo, then:

```bash
git clone https://github.com/<you>/FastAPI-boilerplate
cd FastAPI-boilerplate
```

**Quick setup:** Run the interactive setup script to choose your deployment configuration:

```bash
./setup.py
```

Or directly specify the deployment type: `./setup.py local`, `./setup.py staging`, or `./setup.py production`.

The script copies the right files for your deployment scenario. Here's what each option sets up:

### Option 1: Local development with Uvicorn

Best for: **Development and testing**

**Copies:**

- `scripts/local_with_uvicorn/Dockerfile` → `Dockerfile`
- `scripts/local_with_uvicorn/docker-compose.yml` → `docker-compose.yml`
- `scripts/local_with_uvicorn/.env.example` → `src/.env`

Sets up Uvicorn with auto-reload enabled. The example environment values work fine for development.

**Manual setup:** `./setup.py local` or copy the files above manually.

### Option 2: Staging with Gunicorn managing Uvicorn workers

Best for: **Staging environments and load testing**

**Copies:**

- `scripts/gunicorn_managing_uvicorn_workers/Dockerfile` → `Dockerfile`
- `scripts/gunicorn_managing_uvicorn_workers/docker-compose.yml` → `docker-compose.yml`
- `scripts/gunicorn_managing_uvicorn_workers/.env.example` → `src/.env`

Sets up Gunicorn managing multiple Uvicorn workers for production-like performance testing.

> [!WARNING]
> Change `SECRET_KEY` and passwords in the `.env` file for staging environments.

**Manual setup:** `./setup.py staging` or copy the files above manually.

### Option 3: Production with NGINX

Best for: **Production deployments**

**Copies:**

- `scripts/production_with_nginx/Dockerfile` → `Dockerfile`
- `scripts/production_with_nginx/docker-compose.yml` → `docker-compose.yml`
- `scripts/production_with_nginx/.env.example` → `src/.env`

Sets up NGINX as reverse proxy with Gunicorn + Uvicorn workers for production.

> [!CAUTION]
> You MUST change `SECRET_KEY`, all passwords, and sensitive values in the `.env` file before deploying!
> The template will refuse to boot with unsafe placeholder production settings.

**Manual setup:** `./setup.py production` or copy the files above manually.

---

This template uses a migrations-only database lifecycle. Application startup will not create tables automatically.
Shared runtime resources are brought up through FastAPI lifespan: the API process primes the shared database engine, verifies Redis-backed services before exposing them, and flushes telemetry integrations during shutdown. If startup fails midway, already-initialized shared resources are unwound before the process exits.

**Start your application:**

```bash
docker compose up
```

**Access your app:**
- **Local**: http://127.0.0.1:8000 (auto-reload enabled) → [API docs](http://127.0.0.1:8000/docs)
- **Staging**: http://127.0.0.1:8000 (production-like performance)
- **Production**: http://localhost (NGINX reverse proxy)

### Next steps

**Create your first admin user:**
```bash
docker compose run --rm create_superuser
```

The browser-based CRUD admin UI stays disabled until you explicitly set `CRUD_ADMIN_ENABLED=true`.

**Run database migrations before serving traffic:**
```bash
# repo-aware wrapper around the canonical Alembic config
uv run db-migrate upgrade head
```

**Background jobs:**
The worker runtime is included, but the template intentionally does not ship a demo task submission endpoint. Add project-specific jobs by subclassing `WorkerJob` and registering them in `src/app/workers/jobs.py`.
Worker startup and shutdown now use a shared resource stack so the template can prime the database engine, worker-side Redis aliases, optional cache and rate-limit clients, and Sentry in one reusable lifecycle path.
Tune the shared worker runtime with `WORKER_QUEUE_NAME`, `WORKER_MAX_JOBS`, `WORKER_JOB_MAX_TRIES`, `WORKER_JOB_RETRY_DELAY_SECONDS`, `WORKER_KEEP_RESULT_SECONDS`, `WORKER_KEEP_RESULT_FOREVER`, and `WORKER_JOB_EXPIRES_EXTRA_MS`.

**Webhook ingestion:**
Signature-verified webhook routes should depend on `build_webhook_ingestion_request` from `src.app.webhooks` so handlers can verify the exact inbound bytes before parsing JSON into models.
Provider adapters can implement `WebhookSignatureVerifier` and run them through `verify_webhook_signature(...)` so signature logic stays reusable instead of being embedded directly in route handlers.
Persist accepted or rejected inbound deliveries with `WebhookEventPersistenceRequest` and `webhook_event_store` so the shared `webhook_event` ledger captures payload hashes, provider identifiers, and lifecycle state before downstream jobs take over.
When a route should follow the template-owned happy path end to end, call `ingest_webhook_event(...)` with a verifier, event validator, and enqueuer so receive, validate, persist, acknowledge, and enqueue stay consistent across providers.
When replay protection is enabled, the canonical ingestion flow checks recent `webhook_event` records for matching delivery IDs, event IDs, or fallback payload fingerprints and raises typed replay errors before a duplicate delivery is persisted.

**Or run locally without Docker:**
```bash
uv sync && uv run db-migrate upgrade head && uv run uvicorn src.app.main:app --reload
```

> Full setup (from-scratch, .env examples, PostgreSQL & Redis, gunicorn, nginx) lives in the [docs](https://benavlabs.github.io/FastAPI-boilerplate/getting-started/installation/).

## Configuration (minimal)

Create `src/.env` and set **app**, **database**, **JWT**, and **environment** settings. Prefer a single `DATABASE_URL` for the application database connection; the template still supports composed `POSTGRES_*` settings as a fallback when a direct URL is not available. See the [docs](https://benavlabs.github.io/FastAPI-boilerplate/getting-started/configuration/) for a copy-pasteable example and production guidance.

The docs also include an environment settings matrix for `local`, `staging`, and `production`: [https://benavlabs.github.io/FastAPI-boilerplate/user-guide/configuration/environment-specific/](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/configuration/environment-specific/)

[https://benavlabs.github.io/FastAPI-boilerplate/getting-started/configuration/](https://benavlabs.github.io/FastAPI-boilerplate/getting-started/configuration/)

* `ENVIRONMENT=local|staging|production` controls API docs exposure
* `DATABASE_URL=postgresql://...` is the first-class database setting for runtime, migrations, and tests
* `WORKER_*` settings control ARQ queue naming, concurrency, retry defaults, and result retention
* `WEBHOOK_*` settings define generic verification, replay-window, and payload-retention defaults for future provider adapters
* `SENTRY_*`, `METRICS_*`, `TRACING_*`, and `*_LOG_LEVEL` settings define the template observability contract
* `FEATURE_*` settings provide high-level toggles for optional route groups and template-owned modules such as admin and client cache
* `CRUD_ADMIN_ENABLED=false` keeps the built-in browser admin surface off until you explicitly opt in
* `JWT_*` settings add optional issuer/audience enforcement and `kid`-based signing-key rotation on top of the default stateless token flow
* `API_KEY_*` settings register optional machine principals for internal hooks and other machine clients without forcing a client-specific auth table into the template
* `CORS_*` settings now default to a fail-closed allowlist outside local development and support credentials, exposed headers, and max-age tuning
* `SECURITY_HEADERS_*`, `REFRESH_TOKEN_COOKIE_*`, and `SESSION_SECURE_COOKIES` control baseline response-header hardening and template-owned cookie behavior
* `PASSWORD_*` settings control the shared bcrypt policy, including work-factor increases and automatic rehash-on-login
* `TRUSTED_HOSTS` and `PROXY_HEADERS_*` settings provide optional host-header protection and safe forwarded-header trust controls for reverse-proxy deployments
* `ADMIN_*` supply bootstrap credentials for the opt-in CRUD admin UI and the `create_superuser` helper
* `HTTP_CLIENT_*` settings configure the shared outbound HTTP client layer: timeouts, connection pooling, retry backoff, circuit breaker thresholds, and request/response body logging

## Common tasks

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
uv sync --group docs
uv run mkdocs build --strict

# audit the locked dependency set the same way CI does
# requires network access to fetch pip-audit and advisory data
UV_CACHE_DIR=/tmp/uv-cache uv export --frozen --all-groups --format requirements.txt --no-emit-project --no-header --no-hashes --no-annotate --output-file /tmp/requirements-audit.txt
uvx --from pip-audit pip-audit -r /tmp/requirements-audit.txt --progress-spinner off

# run the secret scan with the same gitleaks config used by CI and pre-commit
uv run pre-commit run gitleaks --all-files

# serve docs locally
uv run mkdocs serve
```

More examples (superuser creation, tiers, rate limits, admin usage) in the [docs](https://benavlabs.github.io/FastAPI-boilerplate/getting-started/first-run/).

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
