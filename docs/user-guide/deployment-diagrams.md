# FastAPI Template Deployment Architecture

This guide provides visual references for the three deployment profiles included in the FastAPI template: Local, Staging, and Production. Each profile is optimized for its environment while sharing a common containerized foundation.

## Overview of Profiles

- **Local**: Development environment with hot reload via Uvicorn and source volume mounts
- **Staging**: Production-like environment with Gunicorn/Uvicorn stack but no reverse proxy
- **Production**: Full production setup with NGINX reverse proxy, load balancing, and security boundaries

---

## 1. Production Deployment Topology

The production environment follows a multi-layer architecture with clear separation of concerns: external-facing reverse proxy, application tier, worker tier, and data tier.

```mermaid
graph TB
    subgraph external["External Zone"]
        clients["API Clients"]
        webhooks["Webhook Providers"]
    end

    subgraph dmz["DMZ / Load Balancing"]
        nginx["NGINX 1.25 Alpine<br/>Reverse Proxy<br/>Port 80/443"]
    end

    subgraph app_tier["Application Tier"]
        api1["API Container 1<br/>Gunicorn + Uvicorn"]
        api2["API Container 2<br/>Gunicorn + Uvicorn"]
        api3["API Container N<br/>Gunicorn + Uvicorn"]
        migrate["Migrate Job<br/>Run Once<br/>Before API Start"]
    end

    subgraph worker_tier["Worker Tier"]
        worker1["ARQ Worker 1<br/>Redis Consumer"]
        worker2["ARQ Worker 2<br/>Redis Consumer"]
        workerN["ARQ Worker N<br/>Redis Consumer"]
    end

    subgraph data_tier["Data Tier"]
        postgres["PostgreSQL 16 Alpine<br/>Primary Database<br/>HEALTHCHECK"]
        redis["Redis 7 Alpine<br/>Queue & Cache<br/>HEALTHCHECK"]
    end

    clients -->|HTTP/HTTPS| nginx
    webhooks -->|Webhooks| nginx
    nginx -->|port 8000| api1
    nginx -->|port 8000| api2
    nginx -->|port 8000| api3

    migrate -->|SQL Scripts| postgres
    api1 -->|depends_on<br/>healthy| postgres
    api1 -->|depends_on<br/>healthy| redis
    api2 -->|depends_on<br/>healthy| postgres
    api2 -->|depends_on<br/>healthy| redis
    api3 -->|depends_on<br/>healthy| postgres
    api3 -->|depends_on<br/>healthy| redis

    worker1 -->|consume tasks| redis
    worker1 -->|read/write| postgres
    worker2 -->|consume tasks| redis
    worker2 -->|read/write| postgres
    workerN -->|consume tasks| redis
    workerN -->|read/write| postgres

    api1 -->|enqueue jobs| redis
    api2 -->|enqueue jobs| redis
    api3 -->|enqueue jobs| redis

    style nginx fill:#ff9999
    style external fill:#e6f3ff
    style app_tier fill:#e6f9e6
    style worker_tier fill:#fff9e6
    style data_tier fill:#f0e6f9
    style migrate fill:#ffe6e6
```

### Production Topology Notes

- **NGINX Reverse Proxy**: Single entry point; handles SSL termination, load balancing across multiple API instances
- **Migrate Job**: Runs before any API container starts (orchestrated via `depends_on` with `condition: service_healthy`); ensures database schema is up-to-date
- **API Containers**: Multiple instances behind NGINX for horizontal scaling; each waits for PostgreSQL and Redis to be healthy before starting
- **ARQ Workers**: Consume background jobs from Redis queue; can scale independently from API tier
- **Graceful Shutdown**: All containers use `STOPSIGNAL SIGTERM` with `stop_grace_period: 30s` (API) and `60s` (workers)

---

## 2. Multi-Stage Docker Build Architecture

The template uses a two-stage Dockerfile to minimize runtime image size and improve security.

```mermaid
graph LR
    subgraph build["Stage 1: Builder"]
        uv["uv package manager<br/>Alpine base"]
        builder_workspace["Workspace<br/>pyproject.toml<br/>requirements.lock"]
        builder_cache["Dependency Cache<br/>Compiled wheels"]
    end

    subgraph runtime["Stage 2: Runtime"]
        python_slim["Python 3.11<br/>slim-bookworm"]
        app_code["App Code<br/>/app/src"]
        migrations["Migrations<br/>/app/alembic"]
        entrypoint["Entrypoint Scripts"]
        app_user["Non-Root User<br/>appuser:1000"]
    end

    subgraph registry["Image Registry"]
        image["Final Image<br/>fastapi-template:latest"]
    end

    uv -->|install deps| builder_cache
    builder_workspace -->|locked| uv
    builder_cache -->|copy --from=builder| python_slim

    app_code -->|COPY| python_slim
    migrations -->|COPY| python_slim
    entrypoint -->|COPY| python_slim
    app_user -->|USER appuser| python_slim

    python_slim -->|build| image

    style build fill:#ffe6e6
    style runtime fill:#e6f9e6
    style app_user fill:#fff9e6
    style image fill:#e6f3ff
```

### Multi-Stage Build Details

**Stage 1: Builder (uv)**
- Uses Alpine Linux as base (minimal size)
- Installs Python dependencies via `uv`
- Generates compiled `.whl` files cached in layer
- Result: ~600MB intermediate image (discarded)

**Stage 2: Runtime**
- Python 3.11 slim-bookworm base (~150MB)
- Copies pre-built wheel cache from builder
- Copies application code (source code, migrations, scripts)
- Creates non-root `appuser` (UID 1000) for security
- Implements Python-based `HEALTHCHECK` (no external curl required)
- Sets `STOPSIGNAL SIGTERM` for graceful shutdown
- Result: ~350–400MB final production image

**Copy Strategy**
- Wheels copied at layer 3 (leverages Docker layer caching)
- App code copied at layer 4 (allows source-only rebuilds)
- Migrations copied separately (independent versioning)
- Entrypoint script included for container orchestration

---

## 3. Scaling Topology

This diagram illustrates how the template scales across different components.

```mermaid
graph TB
    subgraph lb["Load Balancer / Ingress"]
        traffic["Incoming Traffic"]
    end

    subgraph api_group["API Scale Group<br/>Horizontal Scaling"]
        api1["Instance 1"]
        api2["Instance 2"]
        api3["Instance 3<br/>...+N"]
    end

    subgraph worker_group["Worker Scale Group<br/>Independent Scaling"]
        worker1["Worker 1"]
        worker2["Worker 2"]
        worker3["Worker 3<br/>...+N"]
    end

    subgraph queue["Task Queue"]
        redis_queue["Redis Queue<br/>FIFO / Priority"]
        redis_cache["Redis Cache<br/>Session / Config"]
    end

    subgraph database["Data Persistence"]
        pg["PostgreSQL<br/>Connection Pool<br/>max_connections: 100"]
        pgwarn["⚠️ Monitor:<br/>Connection pool saturation"]
    end

    subgraph scheduler["Scheduler<br/>Single Instance"]
        scheduler_note["⚠️ Leader Election Required<br/>OR External Cron"]
        scheduler_single["One instance runs<br/>scheduled tasks"]
    end

    traffic -->|round-robin| api1
    traffic -->|round-robin| api2
    traffic -->|round-robin| api3

    api1 -->|enqueue| redis_queue
    api2 -->|enqueue| redis_queue
    api3 -->|enqueue| redis_queue

    worker1 -->|consume| redis_queue
    worker2 -->|consume| redis_queue
    worker3 -->|consume| redis_queue

    api1 -->|read/write| pg
    api2 -->|read/write| pg
    api3 -->|read/write| pg
    worker1 -->|read/write| pg
    worker2 -->|read/write| pg
    worker3 -->|read/write| pg

    api1 -->|cache| redis_cache
    api2 -->|cache| redis_cache
    api3 -->|cache| redis_cache

    scheduler_single -->|enqueue tasks| redis_queue
    scheduler_note -.->|coordinates via| redis_queue

    style api_group fill:#e6f9e6
    style worker_group fill:#fff9e6
    style queue fill:#f0e6f9
    style database fill:#ffe6e6
    style scheduler fill:#ffe6cc
    style pgwarn fill:#ffcccc
    style scheduler_note fill:#ffcccc
```

### Scaling Guidelines

**API Tier**
- Scale horizontally by adding instances behind load balancer
- Each instance is stateless (sessions stored in Redis)
- Recommended: 2–10 instances for production
- Monitor: CPU, memory, request latency

**Worker Tier**
- Scale independently from API tier
- Add more workers to reduce job queue backlog
- Each worker independently consumes from Redis
- Recommended: Start with 2–4 workers; scale based on queue depth
- Monitor: Queue depth, job processing time, error rate

**PostgreSQL**
- Single primary instance (replication recommended for HA)
- Connection pooling via PgBouncer or application pool (set `max_connections` appropriately)
- Typical guidance: Allow ~20–50 connections per application instance
- Monitor: Connection count, slow queries, replication lag

**Redis**
- Single instance (Sentinel/Cluster for HA)
- Stores both task queue and cache
- Monitor: Memory usage, eviction rate, command latency

**Scheduler**
- Must run on exactly one instance
- Use distributed leader election (Redis-based or Consul-based) or external cron service
- Do NOT run scheduler in every instance without coordination
- Recommended: Deploy as separate sidecar or external service

---

## 4. Kubernetes Deployment Reference

This diagram shows how to adapt the template for Kubernetes environments.

```mermaid
graph TB
    subgraph ingress["Ingress / Load Balancing"]
        ingress_ctrl["Ingress Controller<br/>NGINX / ALB"]
    end

    subgraph api_deployment["API Deployment<br/>replicas: 3+"]
        pod1["Pod 1<br/>Container: fastapi<br/>Port 8000"]
        pod2["Pod 2<br/>Container: fastapi<br/>Port 8000"]
        pod3["Pod 3+<br/>Container: fastapi<br/>Port 8000"]
    end

    subgraph api_service["API Service<br/>type: ClusterIP"]
        svc_api["Service: fastapi<br/>Port 8000"]
    end

    subgraph worker_deployment["Worker Deployment<br/>replicas: 2+"]
        worker_pod1["Pod 1<br/>Container: arq-worker"]
        worker_pod2["Pod 2<br/>Container: arq-worker"]
    end

    subgraph migration_job["Migration Job<br/>run-once per release"]
        job_migrate["Job: db-migrate<br/>Container: fastapi<br/>Command: alembic upgrade head"]
    end

    subgraph config["Configuration<br/>Config & Secrets"]
        configmap["ConfigMap<br/>DATABASE_URL<br/>REDIS_URL<br/>LOG_LEVEL"]
        secret["Secret<br/>DATABASE_PASSWORD<br/>SECRET_KEY"]
    end

    subgraph postgres_statefulset["PostgreSQL StatefulSet<br/>replicas: 1<br/>HA: Add replicas"]
        pg_pod["Pod 0<br/>PostgreSQL 16<br/>Port 5432"]
        pg_pvc["PVC<br/>postgres-data<br/>Storage: 50Gi+"]
    end

    subgraph redis_statefulset["Redis Deployment<br/>replicas: 1<br/>HA: Add Sentinel"]
        redis_pod["Pod 0<br/>Redis 7<br/>Port 6379"]
        redis_pvc["PVC<br/>redis-data<br/>Storage: 10Gi+"]
    end

    ingress_ctrl -->|routing| svc_api
    svc_api -->|load balance| pod1
    svc_api -->|load balance| pod2
    svc_api -->|load balance| pod3

    configmap -->|env| pod1
    configmap -->|env| pod2
    configmap -->|env| worker_pod1
    secret -->|env| pod1
    secret -->|env| pod2
    secret -->|env| worker_pod1

    pod1 -->|read/write| svc_api
    pod2 -->|read/write| svc_api

    job_migrate -->|run before app| pg_pod
    pod1 -->|depends_on| job_migrate

    worker_pod1 -->|consume jobs| redis_pod
    worker_pod2 -->|consume jobs| redis_pod

    pod1 -->|connect| pg_pod
    pod2 -->|connect| pg_pod
    worker_pod1 -->|connect| pg_pod
    worker_pod2 -->|connect| pg_pod

    pod1 -->|cache/queue| redis_pod
    pod2 -->|cache/queue| redis_pod

    pg_pod -->|persist| pg_pvc
    redis_pod -->|persist| redis_pvc

    style api_deployment fill:#e6f9e6
    style worker_deployment fill:#fff9e6
    style migration_job fill:#ffe6e6
    style postgres_statefulset fill:#f0e6f9
    style redis_statefulset fill:#ffe6cc
    style config fill:#e6f3ff
```

### Kubernetes Deployment Notes

**Manifests to Create**
1. **Namespace**: `fastapi-app` (or custom)
2. **ConfigMap**: Database URL, Redis URL, log level, feature flags
3. **Secret**: Database password, secret key, API keys
4. **API Deployment**: 3+ replicas, resource requests/limits, liveness/readiness probes
5. **Worker Deployment**: 2–4 replicas, separate from API
6. **Migration Job**: Runs once per release before API pods start
7. **PostgreSQL StatefulSet**: 1 pod (add replicas for HA)
8. **Redis Deployment**: 1 pod (add Sentinel for HA)
9. **Service (ClusterIP)**: Exposes API internally
10. **Ingress**: Routes external traffic to API service

**Resource Sizing**
- API Container: `requests: {cpu: 200m, memory: 256Mi}`, `limits: {cpu: 1000m, memory: 512Mi}`
- Worker Container: `requests: {cpu: 100m, memory: 256Mi}`, `limits: {cpu: 500m, memory: 512Mi}`
- PostgreSQL: `requests: {cpu: 500m, memory: 512Mi}`, `limits: {cpu: 2000m, memory: 2Gi}`
- Redis: `requests: {cpu: 100m, memory: 256Mi}`, `limits: {cpu: 500m, memory: 1Gi}`

**Health Checks**
- Liveness Probe: HTTP GET `/health` (500ms initial delay, 30s period)
- Readiness Probe: HTTP GET `/ready` (5s initial delay, 5s period)

---

## 5. Network and Security Boundaries

This diagram illustrates network zones and access controls.

```mermaid
graph LR
    subgraph external_zone["External Zone<br/>Untrusted"]
        clients["API Clients<br/>Internet"]
        providers["Webhook Providers<br/>Third-party Services"]
    end

    subgraph dmz_zone["DMZ Zone<br/>Edge Security"]
        nginx["NGINX Reverse Proxy<br/>SSL/TLS Termination<br/>Rate Limiting<br/>Request Validation"]
    end

    subgraph app_zone["Application Zone<br/>Internal"]
        api["API Instances<br/>Private Network"]
        workers["Worker Instances<br/>Private Network"]
    end

    subgraph data_zone["Data Zone<br/>Restricted Access"]
        postgres["PostgreSQL<br/>Network Isolation"]
        redis["Redis<br/>Network Isolation"]
    end

    subgraph fw["Firewalls & ACLs"]
        fw1["Allow external<br/>→ NGINX:80,443"]
        fw2["Allow NGINX<br/>→ API:8000<br/>internal only"]
        fw3["Allow API/Workers<br/>→ PostgreSQL:5432<br/>internal only"]
        fw4["Allow API/Workers<br/>→ Redis:6379<br/>internal only"]
    end

    clients -->|HTTP/HTTPS| fw1
    providers -->|Webhooks| fw1
    fw1 -->|allowed| nginx

    nginx -->|decrypts| nginx
    nginx -->|validates| nginx
    nginx -->|rate limits| nginx
    nginx -->|forwards| fw2

    fw2 -->|allowed| api
    fw2 -->|allowed| workers

    api -->|queries| fw3
    workers -->|queries| fw3
    fw3 -->|allowed| postgres

    api -->|cache/queue| fw4
    workers -->|cache/queue| fw4
    fw4 -->|allowed| redis

    api -.->|no direct<br/>external access| external_zone
    workers -.->|no direct<br/>external access| external_zone
    postgres -.->|no direct<br/>external access| external_zone
    redis -.->|no direct<br/>external access| external_zone

    style external_zone fill:#ffcccc
    style dmz_zone fill:#ff9999
    style app_zone fill:#e6f9e6
    style data_zone fill:#f0e6f9
    style fw fill:#e6f3ff
```

### Security Zones

**External Zone** (Untrusted)
- API clients on the internet
- Third-party webhook providers
- No direct access to internal systems

**DMZ Zone** (Edge)
- NGINX reverse proxy
- Only exposed service to external world
- Handles: SSL/TLS termination, rate limiting, request validation, request logging
- Should run behind WAF (AWS WAF, Cloudflare, etc.) in production

**Application Zone** (Internal)
- API instances and worker instances
- Internal network only; no exposure to external traffic
- Communicate via HTTPS internally (optional but recommended)
- Access logs aggregated to centralized logging

**Data Zone** (Restricted)
- PostgreSQL and Redis instances
- Accessible only from application zone
- No external access
- Regular backups to secure storage (S3, GCS, etc.)
- Encryption at rest and in transit recommended

### Network Access Rules (Minimum)

```
External → NGINX:443 (https)  [Required]
NGINX → API:8000              [Internal only, e.g., 10.0.0.0/8]
API → PostgreSQL:5432         [Internal only]
API → Redis:6379              [Internal only]
Workers → PostgreSQL:5432     [Internal only]
Workers → Redis:6379          [Internal only]
```

### Firewall Recommendations

- **Ingress**: Only NGINX exposed on ports 80/443
- **Egress**: API/workers can make outbound requests for webhooks, external APIs; restrict domains as needed
- **Data Layer**: PostgreSQL and Redis on private network only
- **Database Credentials**: Store in secrets manager (AWS Secrets Manager, HashiCorp Vault, K8s Secrets), not in code or environment
- **API Keys**: Rotate regularly; use service accounts for inter-service communication

---

## Deployment Profile Comparison

| Aspect | Local | Staging | Production |
|--------|-------|---------|------------|
| **Web Server** | Uvicorn (dev) | Gunicorn + Uvicorn | NGINX + Gunicorn + Uvicorn |
| **Source Mounts** | Yes (--reload) | No | No |
| **Reverse Proxy** | None | None | NGINX 1.25 |
| **Scaling** | Single instance | Single instance | Multiple instances |
| **Database** | PostgreSQL 16 | PostgreSQL 16 | PostgreSQL 16 |
| **Cache/Queue** | Redis 7 | Redis 7 | Redis 7 |
| **Worker** | ARQ (optional) | ARQ | ARQ (multiple) |
| **Migrations** | Manual or migrate service | migrate service | migrate job |
| **Health Checks** | Python-based | Python-based | Python-based |
| **Graceful Shutdown** | SIGTERM (30s) | SIGTERM (30s/60s) | SIGTERM (30s/60s) |
| **Restart Policy** | unless-stopped | unless-stopped | unless-stopped |
| **Best For** | Development | Integration testing | Production workloads |

---

## Monitoring and Observability

Key metrics to monitor across all profiles:

**Application Tier**
- Request latency (p50, p95, p99)
- Error rate (4xx, 5xx)
- Active connections
- Garbage collection pauses

**Worker Tier**
- Job queue depth
- Job processing time
- Failed jobs
- Worker utilization

**Data Tier**
- Database connection count
- Slow queries (> 100ms)
- Query execution time
- Redis memory usage
- Redis eviction rate

**Infrastructure**
- Container CPU usage
- Container memory usage
- Network I/O
- Disk I/O
- Restart count and reasons

**Logging**
- Application logs aggregated to central logging (ELK, CloudWatch, GCP Logs)
- Access logs from NGINX
- Error logs with stack traces
- Structured logging (JSON format recommended)

---

## Additional Resources

- [Container Hardening](deployment/containers.md) -- Dockerfile and image build details
- [Runtime Topology](deployment/runtime-topology.md) -- Component process and scaling guidance
- [Secrets Management](deployment/secrets.md) -- Environment variable and secret rotation
- [Backups and Recovery](deployment/backups.md) -- Disaster recovery guidance

