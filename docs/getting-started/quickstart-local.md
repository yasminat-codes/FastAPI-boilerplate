# Local Development Quickstart

Get the template running locally in under five minutes.

## Prerequisites

- Python 3.11+
- Docker and Docker Compose (for Postgres and Redis)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Option A: Docker Compose (fastest)

```bash
git clone https://github.com/benavlabs/fastapi-boilerplate myproject
cd myproject

# Interactive setup — choose "local"
./setup.py local

# Start everything
docker compose up -d
```

This brings up the API server, Postgres, Redis, and the ARQ worker. The local
profile enables auto-reload so file changes take effect immediately.

**Verify it works:**

```bash
curl http://localhost:8000/api/v1/health
# {"status":"healthy","environment":"local",...}

curl http://localhost:8000/api/v1/ready
# {"status":"ready","dependencies":{...}}
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) for the interactive
API documentation.

## Option B: Without Docker (native)

Use this when you want to run the Python process directly and manage Postgres
and Redis yourself (or point at remote instances).

```bash
git clone https://github.com/benavlabs/fastapi-boilerplate myproject
cd myproject

# Install dependencies
uv sync

# Copy the local environment example
cp scripts/local_with_uvicorn/.env.example src/.env
```

Edit `src/.env` and set `DATABASE_URL` to point at your Postgres instance. The
default value works if you have Postgres running locally with the template's
default credentials.

```bash
# Run database migrations
uv run db-migrate upgrade head

# Start the API server with auto-reload
uv run uvicorn src.app.main:app --reload
```

To run the background worker in a separate terminal:

```bash
uv run arq src.app.workers.settings.WorkerSettings
```

## Create an admin user

```bash
# Docker Compose
docker compose run --rm create_superuser

# Native
uv run python -m src.scripts.create_superuser
```

## Run the quality gates

```bash
uv run ruff check src tests
uv run mypy src --config-file pyproject.toml
uv run pytest
```

## Next steps

- [Configuration guide](configuration.md) — understand the settings surface
- [Project structure](../user-guide/project-structure.md) — learn the module layout
- [Extension guides](../user-guide/guides/index.md) — add your first job, workflow, or integration
