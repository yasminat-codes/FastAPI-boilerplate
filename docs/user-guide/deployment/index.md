# Deployment Overview

This section covers comprehensive deployment and operations guidance for the FastAPI boilerplate. It provides practical strategies for moving your application from development through production, with architectural patterns and best practices for reliability, security, and scalability.

## Deployable Components

The FastAPI boilerplate is modular and can be deployed as separate, independently scalable components:

### API Server
- **FastAPI application** running with Gunicorn + Uvicorn workers or standalone Uvicorn
- Handles HTTP/HTTPS requests from clients
- Manages request parsing, validation, authentication, and response serialization
- Stateless design allows horizontal scaling
- Standard port: 8000 (exposed through reverse proxy)

### ARQ Worker
- **Background job processing** for asynchronous work (emails, webhooks, heavy computation)
- Consumes tasks from the Redis queue (ARQ backend)
- Can be scaled independently based on workload
- Includes retry logic and exponential backoff
- Graceful shutdown: waits for in-flight jobs to complete

### Optional Scheduler
- **Periodic task execution** for cron-like operations (cleanup, reports, maintenance)
- APScheduler integration for recurrent tasks
- Runs as a separate process or embedded in the main app
- Typically single instance (unless distributed job scheduler is implemented)

### Migration Job
- **Database schema migrations** using Alembic
- Runs once before deployment (containers, orchestration platforms)
- Ensures schema consistency across environment changes
- Blocks other services until complete

### Reverse Proxy
- **NGINX** (recommended) or similar reverse proxy
- Terminates SSL/TLS connections
- Routes requests to one or more API server instances
- Enforces rate limiting, request logging, and security headers
- Serves static assets if needed

## Deployment Profiles

The template provides three pre-configured deployment profiles via `setup.py`. Each profile includes matching `Dockerfile`, `docker-compose.yml`, and `.env.example`:

=== "Local"
    **Profile**: `local`
    
    **Command**: `python setup.py local`
    
    **Purpose**: Development and testing on your machine
    
    - Uvicorn with auto-reload enabled
    - Full debug output and exception details
    - FastAPI interactive API docs (`/docs`)
    - No HTTPS or reverse proxy
    - Simplified secrets (dev placeholders acceptable)
    - Mutable application code (volume mounts)
    
    **When to use**: Running locally, debugging, feature development

=== "Staging"
    **Profile**: `staging`
    
    **Command**: `python setup.py staging`
    
    **Purpose**: Production-like testing environment
    
    - Gunicorn managing Uvicorn workers (multi-process)
    - Debug disabled, production logging
    - No interactive docs (can be enabled via environment variable)
    - Supports NGINX reverse proxy
    - Secrets must be properly configured
    - Immutable container image
    
    **When to use**: Integration testing, performance testing, pre-production validation

=== "Production"
    **Profile**: `production`
    
    **Command**: `python setup.py production`
    
    **Purpose**: Customer-facing deployment
    
    - Hardened Dockerfile (minimal base image, non-root user)
    - Multi-stage build with uv for dependency management
    - NGINX with SSL/TLS, security headers, rate limiting
    - No debug output or interactive docs
    - All secrets required (app refuses to start with defaults)
    - Comprehensive health checks and graceful shutdown
    
    **When to use**: Customer production, public APIs, regulated environments

## How `setup.py` Works

The `setup.py` script automates environment setup by copying the correct configuration files for your chosen profile:

```bash
python setup.py <profile>
```

**What happens:**

1. Copies deployment-specific `Dockerfile` to project root
2. Copies deployment-specific `docker-compose.yml` to project root
3. Copies `.env.example` to `src/.env` (respects existing `.env` files)
4. Displays next steps and configuration reminders

**Example:**

```bash
$ python setup.py production
🚀 Setting up Production with NGINX...
   Full production setup with reverse proxy

✅ Copied scripts/production_with_nginx/Dockerfile → Dockerfile
✅ Copied scripts/production_with_nginx/docker-compose.yml → docker-compose.yml
✅ Copied scripts/production_with_nginx/.env.example → src/.env

🎉 Setup complete!

⚠️  IMPORTANT: Update the .env file with your production values:
   - Generate a new SECRET_KEY: openssl rand -hex 32
   - Change all passwords and sensitive values
   - Set explicit CORS_ORIGINS values for your deployed frontend
   - The app will refuse to boot in production until placeholder secrets are replaced

Next steps:
   docker compose up
```

## Architecture Diagram

The typical deployment architecture looks like this:

```
┌────────────────────────────────────────────────────────────────────┐
│ Internet / Client Traffic                                          │
└────────────────────────────┬─────────────────────────────────────┘
                              │
                              ▼
                  ┌──────────────────────┐
                  │  NGINX Reverse Proxy │
                  │  - SSL/TLS          │
                  │  - Security Headers  │
                  │  - Rate Limiting    │
                  └──────────────────────┘
                              │
                ┌─────────────┼─────────────┐
                ▼             ▼             ▼
        ┌────────────┐ ┌────────────┐ ┌────────────┐
        │   API      │ │   API      │ │   API      │
        │  Server 1  │ │  Server 2  │ │  Server 3  │ (Stateless)
        │ Gunicorn + │ │ Gunicorn + │ │ Gunicorn + │ (Scaled)
        │ Uvicorn    │ │ Uvicorn    │ │ Uvicorn    │
        └─────┬──────┘ └─────┬──────┘ └─────┬──────┘
              │              │              │
              └──────────────┼──────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌─────────────┐ ┌──────────┐ ┌──────────────┐
        │ PostgreSQL  │ │  Redis   │ │  ARQ Worker  │
        │  Database   │ │  Cache & │ │  (Background │
        │  (Single)   │ │  Queue   │ │  Tasks)      │
        └─────────────┘ └──────────┘ └──────────────┘
```

**Key points:**

- **NGINX** is the single entry point for all client traffic
- **API Servers** are stateless and can be added/removed without downtime
- **PostgreSQL** is a single persistent data store (can be replicated/HA at DB level)
- **Redis** provides both caching and job queue (monitored for data loss risk)
- **ARQ Workers** consume background tasks asynchronously (can run multiple instances)

## Release Promotion Flow

Deployments typically flow through three tiers:

```
Development (local) 
    ↓ 
Staging (test PROD-like)
    ↓ 
Production (customers)
```

Each tier uses the same container image but different secrets and configurations:

1. **Local** → Run `python setup.py local` for development
2. **Staging** → Run `python setup.py staging` for testing
3. **Production** → Run `python setup.py production` for customer deployment

All use the same `Dockerfile` and application code, ensuring consistency.

## Next Steps

- **[Container Hardening](containers.md)** — Learn about secure Dockerfile practices, multi-stage builds, and resource limits
- **[Runtime Topology](runtime-topology.md)** — Understand component orchestration, networking, and deployment strategies
- **[Secrets Management](secrets.md)** — Configure and rotate secrets safely across environments
- **[Backups and Recovery](backups.md)** — Implement data backup, restore validation, and maintenance procedures

## Related Documentation

- [Configuration: Environment Variables](../configuration/environment-variables.md) — Complete environment variable reference
- [Configuration: Docker Setup](../configuration/docker-setup.md) — Docker-specific configuration details
- [Runbooks and Alerting](../runbooks/index.md) — Operational procedures and troubleshooting
- [Metrics and Tracing](../metrics-and-tracing.md) — Observability and monitoring
- [Logging](../logging.md) — Log configuration and best practices
