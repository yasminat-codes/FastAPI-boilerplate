# Runtime Topology

This guide covers how to orchestrate the FastAPI boilerplate's components (API, worker, scheduler, migration) as separate processes or containers, with patterns for Docker Compose and orchestrated deployments (Kubernetes, ECS).

## Component Processes

Each deployable component runs as a separate, independently scalable process.

### API Server

**Responsibility**: Handle HTTP requests, validate input, return responses.

```bash
gunicorn src.app.main:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
```

**Characteristics:**
- Stateless (can run multiple instances)
- Long-lived process
- Handles concurrent requests
- Exposed to client traffic (via reverse proxy)

**Scaling:** Add more instances behind load balancer

**Health:** `/health` endpoint returns 200 if operational

### ARQ Worker

**Responsibility**: Consume background jobs from Redis queue, execute tasks, handle retries.

```bash
arq src.app.core.worker.settings.WorkerSettings
```

**Characteristics:**
- Stateless job processor
- Blocks on queue reads (low CPU when idle)
- Can run multiple instances
- Not exposed to client traffic
- Gracefully drains in-flight jobs on shutdown

**Scaling:** Add more instances to process jobs faster

**Health:** Redis connectivity health check

### Optional Scheduler

**Responsibility**: Trigger periodic tasks (cleanup, reports, maintenance).

**Implementation approaches:**

=== "Embedded"
    ```python
    # scheduler.py - runs in API process
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    
    async def lifespan(app):
        scheduler = AsyncIOScheduler()
        scheduler.add_job(cleanup_tokens, "cron", hour=2)
        scheduler.start()
        yield
        scheduler.shutdown()
    
    app = FastAPI(lifespan=lifespan)
    ```
    
    **Pros:** Single process, no coordination needed
    
    **Cons:** Scheduler runs on every API instance (duplicate tasks)

=== "Separate Container"
    ```dockerfile
    # Dockerfile.scheduler
    FROM python:3.11-slim
    COPY . /code
    WORKDIR /code
    CMD ["python", "-m", "src.app.tasks.scheduler"]
    ```
    
    ```yaml
    # docker-compose.yml
    scheduler:
      build:
        context: .
        dockerfile: Dockerfile.scheduler
      env_file:
        - ./src/.env
      depends_on:
        - db
        - redis
    ```
    
    **Pros:** Single scheduler instance (no duplicates), can be disabled/restarted independently
    
    **Cons:** Additional process to manage

**Recommendation:** Use separate container for production. Use embedded for local development.

### Migration Job

**Responsibility**: Apply database schema migrations (one-time at deployment).

```bash
alembic upgrade head
```

**Characteristics:**
- Runs once per deployment
- Blocks API startup until complete
- Must succeed before service is ready
- Handles schema evolution safely

**Implementation in docker-compose.yml:**

```yaml
services:
  migrate:
    build: .
    command: alembic upgrade head
    env_file:
      - ./src/.env
    depends_on:
      - db
    volumes:
      - ./alembic:/code/alembic  # Mount migrations directory

  web:
    build: .
    depends_on:
      migrate:
        condition: service_completed_successfully  # Wait for migrate
    # ... rest of config
```

**Important:** The `service_completed_successfully` condition ensures API doesn't start until migration succeeds.

## Docker Compose Deployment

Docker Compose orchestrates containers on a single host with built-in networking.

### Complete docker-compose.yml Example

```yaml
version: '3.8'

services:
  # Database
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  # Redis (cache + queue)
  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  # Run migrations
  migrate:
    build: .
    command: alembic upgrade head
    env_file:
      - ./src/.env
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./alembic:/code/alembic

  # API Server (can scale: docker compose up --scale web=3)
  web:
    build: .
    command: gunicorn src.app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
    env_file:
      - ./src/.env
    depends_on:
      migrate:
        condition: service_completed_successfully
    expose:
      - "8000"
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1G
        reservations:
          memory: 512M

  # Background worker (can scale: docker compose up --scale worker=3)
  worker:
    build: .
    command: arq src.app.core.worker.settings.WorkerSettings
    env_file:
      - ./src/.env
    depends_on:
      - db
      - redis
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M

  # Reverse proxy
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
    depends_on:
      - web
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
```

### Scaling with Docker Compose

```bash
# Start 3 API instances
docker compose up --scale web=3 web

# Start 5 worker instances
docker compose up --scale worker=5 worker

# Full stack with scaling
docker compose up --scale web=2 --scale worker=3 -d
```

**Networking:**

- Services communicate via service names: `db:5432`, `redis:6379`
- Docker's internal DNS resolves service names to container IPs
- External traffic only through NGINX (exposed port 80/443)

## Orchestrated Deployment (Kubernetes / ECS)

For multi-host deployments with automatic scaling and health management.

### Kubernetes Patterns

Kubernetes deployments use Deployments and StatefulSets:

```yaml
# api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fastapi-app
spec:
  replicas: 3  # Auto-scaled by HPA
  selector:
    matchLabels:
      app: fastapi-app
  template:
    metadata:
      labels:
        app: fastapi-app
    spec:
      containers:
      - name: app
        image: registry.example.com/fastapi-app:v1.0.0
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: app-secrets
              key: database_url
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1Gi
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 15"]
      terminationGracePeriodSeconds: 30

---
# worker-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fastapi-worker
spec:
  replicas: 2
  selector:
    matchLabels:
      app: fastapi-worker
  template:
    metadata:
      labels:
        app: fastapi-worker
    spec:
      containers:
      - name: worker
        image: registry.example.com/fastapi-app:v1.0.0
        command: ["arq", "src.app.core.worker.settings.WorkerSettings"]
        env:
        - name: REDIS_QUEUE_HOST
          value: "redis-service"
        resources:
          requests:
            cpu: 250m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi

---
# migration-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: fastapi-migrate
spec:
  backoffLimit: 3
  template:
    spec:
      containers:
      - name: migrate
        image: registry.example.com/fastapi-app:v1.0.0
        command: ["alembic", "upgrade", "head"]
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: app-secrets
              key: database_url
      restartPolicy: Never
```

### ECS (Elastic Container Service) Patterns

ECS uses Task Definitions and Services:

```json
{
  "family": "fastapi-app",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "1024",
  "memory": "2048",
  "containerDefinitions": [
    {
      "name": "app",
      "image": "123456789.dkr.ecr.us-east-1.amazonaws.com/fastapi-app:latest",
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "ENVIRONMENT",
          "value": "production"
        }
      ],
      "secrets": [
        {
          "name": "DATABASE_URL",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789:secret:database-url"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/fastapi-app",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      },
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 30
      }
    }
  ]
}
```

## Release Promotion

Promote the same image through environments without rebuilding.

### Process

```
1. Build image once in development
   docker build -t fastapi-app:v1.0.0 .
   docker tag fastapi-app:v1.0.0 registry.example.com/fastapi-app:v1.0.0

2. Push to registry
   docker push registry.example.com/fastapi-app:v1.0.0

3. Deploy to staging (with staging secrets)
   docker compose -f docker-compose.staging.yml up -d
   # or
   kubectl set image deployment/fastapi-app app=registry.example.com/fastapi-app:v1.0.0 -n staging

4. Run tests, validation, monitoring

5. Deploy to production (with production secrets)
   kubectl set image deployment/fastapi-app app=registry.example.com/fastapi-app:v1.0.0 -n production
```

**Key principle:** Same image, different secrets, different environment configs.

## Blue-Green Deployment

Zero-downtime deployment by running two parallel environments.

```
┌─────────────────────────────────────────────────────────────┐
│ NGINX Load Balancer                                         │
│ (points to "green" = current)                               │
└──────────┬────────────────────────────┬─────────────────────┘
           │                            │
       Blue Pool                   Green Pool
       (idle)                       (active)
           │                            │
   ┌───────┴─────────┐     ┌───────────┴──────────┐
   │ API v1.0 (old)  │     │ API v1.0.1 (new)     │
   │ (3 instances)   │     │ (3 instances)        │
   └─────────────────┘     └──────────────────────┘

Deployment steps:
1. New v1.0.1 starts in blue pool
2. Run smoke tests against blue
3. NGINX switches to blue (traffic redirects)
4. Old green (v1.0) shuts down gracefully
```

### Implementation with Kubernetes

```yaml
# canary-deployment.yaml
apiVersion: v1
kind: Service
metadata:
  name: fastapi-app
spec:
  selector:
    app: fastapi-app
  ports:
  - port: 8000
    targetPort: 8000

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fastapi-app-blue
spec:
  replicas: 3
  selector:
    matchLabels:
      app: fastapi-app
      version: blue
  template:
    metadata:
      labels:
        app: fastapi-app
        version: blue
    spec:
      containers:
      - name: app
        image: registry.example.com/fastapi-app:v1.0.0

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fastapi-app-green
spec:
  replicas: 3
  selector:
    matchLabels:
      app: fastapi-app
      version: green
  template:
    metadata:
      labels:
        app: fastapi-app
        version: green
    spec:
      containers:
      - name: app
        image: registry.example.com/fastapi-app:v1.0.1
```

Switch traffic by updating service selector:

```bash
# Initial state: traffic goes to blue
kubectl patch service fastapi-app -p '{"spec":{"selector":{"version":"blue"}}}'

# After validation: switch to green
kubectl patch service fastapi-app -p '{"spec":{"selector":{"version":"green"}}}'

# Clean up blue
kubectl delete deployment fastapi-app-blue
```

## Rolling Deployment

Gradually replace instances with new version.

```
v1.0 v1.0 v1.0  (3 instances, current)
     ↓
v1.1 v1.0 v1.0  (1 new, 2 old)
v1.1 v1.1 v1.0  (2 new, 1 old)
v1.1 v1.1 v1.1  (3 new, 0 old)
```

### Kubernetes Rolling Update

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fastapi-app
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1          # Allow 1 extra instance
      maxUnavailable: 0    # Keep all running
  selector:
    matchLabels:
      app: fastapi-app
  template:
    spec:
      containers:
      - name: app
        image: registry.example.com/fastapi-app:v1.0.1
```

Rolling updates automatically:
- Start new instance with new image
- Wait for health checks to pass
- Drain old instance (stop accepting requests)
- Wait for in-flight requests to complete (terminationGracePeriodSeconds)
- Delete old instance

## Stop and Graceful Shutdown

Proper shutdown prevents data corruption and incomplete requests.

### Sequence

```
1. Orchestrator sends SIGTERM (container terminates in stop_grace_period)
2. Gunicorn stops accepting new requests
3. In-flight requests finish (up to timeout)
4. Worker processes finish in-flight jobs (graceful drain)
5. Database connections close
6. Process exits
7. If still running after timeout, SIGKILL terminates forcefully
```

### Configuration

**Docker Compose:**

```yaml
services:
  web:
    stop_signal: SIGTERM
    stop_grace_period: 30s  # 30 seconds to shutdown gracefully
```

**Kubernetes:**

```yaml
spec:
  terminationGracePeriodSeconds: 30  # Give process 30s to shutdown
  containers:
  - name: app
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 5"]  # Let load balancer drain
```

**Gunicorn:**

```python
# gunicorn.conf.py
timeout = 30  # Kill worker if request takes >30s
graceful_timeout = 30  # Worker has 30s to finish existing requests
```

### Testing Graceful Shutdown

```bash
# Send SIGTERM and monitor for clean shutdown
docker compose stop -t 30 web

# Check logs for graceful shutdown messages
docker compose logs web | grep -i shutdown
```

## Summary

- **Components:** API, Worker, Scheduler, Migration run as separate processes
- **Docker Compose:** Single-host orchestration with internal networking
- **Kubernetes/ECS:** Multi-host with auto-scaling and health management
- **Release Promotion:** Same image, different secrets per environment
- **Deployment Strategies:** Blue-green (instant) or rolling (gradual)
- **Graceful Shutdown:** Always respect stop signals and drain in-flight work
