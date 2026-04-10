# Production Deployment Quickstart

Get the template deployed to a production-like environment.

!!! warning "Change all secrets before deploying"
    The template ships with example values that are safe for local development
    only. You **must** change `SECRET_KEY`, database passwords, Redis passwords,
    and all sensitive values before exposing the application to real traffic.
    The template will refuse to boot in production mode with unsafe placeholder
    values.

## Prerequisites

- A Linux host, VM, or container orchestrator (ECS, Kubernetes, etc.)
- Docker and Docker Compose (or equivalent container runtime)
- A managed Postgres instance (recommended) or self-hosted Postgres
- A managed Redis instance (recommended) or self-hosted Redis

## Step 1: Clone and configure

```bash
git clone https://github.com/benavlabs/fastapi-boilerplate myproject
cd myproject

# Use the production setup profile
./setup.py production
```

This copies the production Dockerfile (multi-stage build, non-root user,
NGINX reverse proxy), docker-compose.yml, and `.env.example` into the right
places.

## Step 2: Set environment variables

Edit `src/.env` and set every required value. At minimum:

| Variable | What to set |
|----------|-------------|
| `ENVIRONMENT` | `production` |
| `SECRET_KEY` | A strong random string (64+ characters) |
| `DATABASE_URL` | Full Postgres connection string with SSL if applicable |
| `REDIS_URL` | Full Redis connection string |
| `SENTRY_DSN` | Your Sentry project DSN (optional but recommended) |
| `ADMIN_USERNAME` | Bootstrap admin username |
| `ADMIN_PASSWORD` | Bootstrap admin password |
| `ADMIN_EMAIL` | Bootstrap admin email |

See the [environment variables reference](../user-guide/configuration/environment-variables.md)
for the full list and the
[environment-specific guide](../user-guide/configuration/environment-specific.md)
for production-specific settings.

## Step 3: Run migrations

Migrations run before the application starts. The production Compose file
includes a `migrate` service that runs once:

```bash
docker compose run --rm migrate
```

Or run manually:

```bash
uv run db-migrate upgrade head
```

## Step 4: Build and start

```bash
docker compose up -d --build
```

The production profile starts:

- **NGINX** reverse proxy on port 80
- **Gunicorn** managing Uvicorn workers on port 8000 (internal)
- **ARQ worker** for background job processing
- **Postgres** and **Redis** (if using the bundled services)

## Step 5: Verify

```bash
# Health check (through NGINX)
curl http://localhost/api/v1/health

# Readiness check
curl http://localhost/api/v1/ready
```

Both should return `200 OK`. The readiness endpoint confirms that the database,
Redis, and queue connections are live.

## Step 6: Create the admin user

```bash
docker compose run --rm create_superuser
```

## Production hardening checklist

Before serving real traffic, verify these items:

- [ ] `SECRET_KEY` is a unique, random value (not the example default)
- [ ] Database connection uses SSL (`?sslmode=require` in the URL)
- [ ] Redis connection uses TLS if exposed over a network
- [ ] `CORS_ALLOWED_ORIGINS` is set to your frontend domain(s)
- [ ] `TRUSTED_HOSTS` is set to your domain(s)
- [ ] Sentry DSN is configured for error monitoring
- [ ] Log level is set to `WARNING` or `ERROR` for production
- [ ] Container resource limits are set (CPU and memory)
- [ ] Database backups are scheduled
- [ ] Health check endpoints are wired to your load balancer

## Next steps

- [Container hardening](../user-guide/deployment/containers.md) — Dockerfile details and image optimization
- [Runtime topology](../user-guide/deployment/runtime-topology.md) — scaling API, workers, and reverse proxy
- [Secrets management](../user-guide/deployment/secrets.md) — rotation procedures and secret manager integration
- [Backups and recovery](../user-guide/deployment/backups.md) — Postgres backup strategy and restore validation
- [Runbooks](../user-guide/runbooks/index.md) — operational procedures for common incidents
