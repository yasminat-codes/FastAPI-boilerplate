# Container Hardening

This guide covers best practices for building secure, efficient Docker images for the FastAPI boilerplate. A properly hardened container minimizes attack surface, reduces image size, and ensures consistent deployments.

## Non-Root User

All FastAPI boilerplate Dockerfiles enforce running the application as a non-root user. This prevents privilege escalation attacks and is essential for multi-tenant or regulated environments.

### Implementation

```dockerfile
# Create a non-root user with explicit UID/GID
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --shell /bin/bash --create-home app

# Copy assets with correct ownership
COPY --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app /code ./

# Switch to non-root user BEFORE CMD
USER app
```

**Why it matters:**

- Container breakout exploits gain only non-root access
- Prevents accidental modifications to system files
- Enforces principle of least privilege
- Required by many container security policies

## Multi-Stage Builds

The boilerplate uses a two-stage Dockerfile pattern to minimize final image size and attack surface.

### Builder Stage
- Includes build tools (gcc, build-essential) needed for dependency compilation
- Runs dependency installation and compilation
- Discarded after build (not included in final image)
- Large size acceptable (only builder uses it)

### Final Stage
- Minimal Python runtime (python:3.11-slim-bookworm)
- Copy only the compiled `.venv` from builder
- Copy only application source code
- No build tools, compilers, or development headers
- Smaller, faster deployments

### Example Structure

```dockerfile
# Stage 1: Builder
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies (cached layer)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Copy and install project
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# Stage 2: Runtime
FROM python:3.11-slim-bookworm

# Non-root user
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --shell /bin/bash --create-home app

# Copy pre-compiled venv
COPY --from=builder --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"
USER app
WORKDIR /code

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Benefits

- **Smaller images**: Final image excludes build tools (50-60% size reduction)
- **Faster deployments**: Smaller artifacts push/pull faster
- **Reduced attack surface**: No compilers or build utilities in production
- **Better caching**: Builder stage can be cached separately

## Minimal File Copying

Only necessary files should be included in the final image. Exclude everything else.

### What to Include

```dockerfile
# Application code
COPY ./src/app /code/app

# Pre-built virtual environment
COPY --from=builder /app/.venv /app/.venv

# Static files (if serving from container)
COPY ./src/static /code/static

# Configuration files (non-secret)
COPY ./src/config.yml /code/config.yml
```

### What to Exclude

- `.git/` and `.gitignore` (version control)
- `.venv/` in local filesystem (superseded by builder)
- `node_modules/` (if using Node.js)
- Test files (`tests/`, `pytest.ini`)
- Development scripts and notebooks
- IDE configuration (`.vscode/`, `.idea/`)
- Logs and temp files
- `.env*` files (secrets managed separately)

## .dockerignore

The `.dockerignore` file prevents unnecessary files from being sent to the Docker daemon during build.

### Example

```
# Version control
.git
.gitignore
.gitattributes

# Development
.venv
venv
__pycache__
*.pyc
.pytest_cache
.mypy_cache
.coverage
htmlcov

# IDE
.vscode
.idea
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Environment and secrets
.env*
.env.*.local
secrets/

# Build artifacts
build/
dist/
*.egg-info

# Documentation
docs/_build/
site/

# Logs
*.log

# Testing
coverage/
.tox/

# Package files (use uv.lock instead)
poetry.lock
requirements.txt
```

**How it works:**

1. Docker build skips these files when creating the build context
2. Smaller context reduces build time
3. Prevents accidental inclusion of secrets or sensitive data

## HEALTHCHECK Directives

Health checks enable container orchestrators to monitor application status and restart unhealthy instances.

### API Server Healthcheck

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
```

**Parameters:**

- `--interval=30s`: Check every 30 seconds
- `--timeout=10s`: Fail if check takes longer than 10 seconds
- `--start-period=5s`: Grace period before first check (app startup time)
- `--retries=3`: Mark unhealthy after 3 consecutive failures

### Worker Healthcheck

For ARQ workers, check Redis connectivity since they don't expose HTTP:

```dockerfile
HEALTHCHECK --interval=60s --timeout=10s --start-period=10s --retries=3 \
    CMD redis-cli -h redis ping | grep PONG || exit 1
```

### Custom Health Endpoint

Implement a `/health` endpoint in FastAPI:

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health_check():
    """Minimal health check endpoint"""
    return {"status": "ok"}

@router.get("/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Detailed readiness check including dependencies"""
    try:
        # Check database connectivity
        await db.execute(select(1))
        # Check Redis connectivity
        await redis.ping()
        return {"status": "ready"}
    except Exception as e:
        return {"status": "not_ready", "reason": str(e)}, 503
```

Then use a simpler health check:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
```

## STOPSIGNAL for Graceful Shutdown

Configure containers to use SIGTERM instead of SIGKILL for termination.

```dockerfile
STOPSIGNAL SIGTERM
```

**How it works:**

1. Orchestrator sends SIGTERM to container (time to shutdown gracefully)
2. Gunicorn/Uvicorn catch SIGTERM and stop accepting new requests
3. Existing requests complete (up to timeout period)
4. Worker processes wait for in-flight jobs to complete
5. If not stopped after `stop_grace_period`, orchestrator sends SIGKILL

### Docker Compose Example

```yaml
services:
  web:
    image: app:latest
    stop_signal: SIGTERM
    stop_grace_period: 30s  # Wait 30 seconds before SIGKILL
```

### Kubernetes Example

```yaml
spec:
  terminationGracePeriodSeconds: 30
  containers:
    - name: app
      lifecycle:
        preStop:
          exec:
            command: ["/bin/sh", "-c", "sleep 5"]  # Let load balancer drain
```

## Image Size Optimization

Smaller images deploy faster and have smaller attack surface.

### Current Sizes (Example)

- **Local profile** (Uvicorn, full system tools): ~500 MB
- **Staging profile** (Gunicorn, slim base): ~350 MB
- **Production profile** (multi-stage, slim, no tools): ~180 MB

### Optimization Techniques

1. **Use slim base images**
   ```dockerfile
   FROM python:3.11-slim-bookworm  # ~150 MB vs ~900 MB for full image
   ```

2. **Multi-stage builds**
   - Builder stage: 1.2 GB (discarded)
   - Final stage: 180 MB (deployed)

3. **Compile bytecode**
   ```dockerfile
   ENV UV_COMPILE_BYTECODE=1
   ```
   Saves ~10-15% on startup time and slightly reduces size.

4. **Minimize layers**
   ```dockerfile
   # Bad: Multiple RUN statements (extra layers)
   RUN apt-get update
   RUN apt-get install -y gcc
   
   # Good: Combine into single RUN (single layer)
   RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
   ```

5. **Clean package managers**
   ```dockerfile
   RUN apt-get update && apt-get install -y curl \
       && rm -rf /var/lib/apt/lists/*  # Clear cache
   ```

6. **Use Alpine? (Not recommended for this template)**
   - Alpine Python images are smaller (120 MB vs 150 MB)
   - But: Slim Debian is more stable for data science/ML dependencies
   - Trade-off: Stick with `-slim-bookworm` for reliability

## Resource Limits

Container resource limits prevent memory leaks and runaway CPU usage from affecting other services.

### Docker Compose Limits

```yaml
services:
  web:
    image: app:latest
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
        reservations:
          cpus: '0.5'
          memory: 512M

  worker:
    image: app:latest
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 256M

  db:
    image: postgres:15
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '1.0'
          memory: 1G
```

**Terminology:**

- `limits`: Hard cap (container killed if exceeded)
- `reservations`: Guaranteed allocation (may be less in practice)
- `cpus`: CPU cores (0.5 = 50% of one core, 2.0 = two cores)
- `memory`: RAM allocation

### Recommended Baseline

| Component | CPU Limit | Memory Limit | Notes |
|-----------|----------|-------------|-------|
| API Server | 1.0 | 1 GB | Per instance; scale horizontally |
| ARQ Worker | 0.5 | 512 MB | Adjust for job complexity |
| Scheduler | 0.25 | 256 MB | Minimal if only scheduling |
| PostgreSQL | 2.0 | 2 GB | Single instance |
| Redis | 0.5 | 512 MB | More if using as primary cache |
| NGINX | 0.25 | 256 MB | Load balancer |

### Tuning

**API Server too slow?**
- Increase CPU limit and worker count
- Monitor: `docker stats`
- Profile: Use Prometheus + Grafana

**Memory spike?**
- Check for memory leaks (SQLAlchemy session leaks are common)
- Monitor database pool size
- Restart workers periodically (Gunicorn: `max_requests=1000`)

**Redis running out of memory?**
- Reduce TTL for cache entries
- Implement Redis eviction policy (`maxmemory-policy`)
- Consider separating cache Redis from queue Redis

## Security Scanning

Use vulnerability scanners to detect known CVEs in dependencies:

```bash
# Scan image for vulnerabilities
docker scan app:latest

# Or with Trivy (recommended)
trivy image app:latest

# Fail build on HIGH/CRITICAL
trivy image --exit-code 1 --severity HIGH,CRITICAL app:latest
```

### CI/CD Integration

Add to GitHub Actions:

```yaml
- name: Build image
  run: docker build -t app:latest .

- name: Scan with Trivy
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: app:latest
    format: 'sarif'
    output: 'trivy-results.sarif'

- name: Upload to GitHub Security
  uses: github/codeql-action/upload-sarif@v2
  with:
    sarif_file: 'trivy-results.sarif'
```

## Summary Checklist

- [ ] Non-root user (UID 1000) in final image
- [ ] Multi-stage build (builder → runtime)
- [ ] Only necessary files copied (use .dockerignore)
- [ ] HEALTHCHECK defined for all services
- [ ] STOPSIGNAL SIGTERM for graceful shutdown
- [ ] Image size optimized (target: <200MB for API)
- [ ] Resource limits configured in docker-compose.yml
- [ ] Vulnerability scanning enabled in CI/CD
- [ ] Base image regularly updated (python:3.11-slim-bookworm latest)
