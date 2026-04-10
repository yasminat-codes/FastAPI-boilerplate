# Architecture Diagrams

This document provides comprehensive visual diagrams of the FastAPI template's architecture, including system-level design, application layers, request flows, authentication patterns, and data models.

## High-Level System Architecture

The system follows a distributed architecture with clear separation between API tier, background workers, and external dependencies.

```mermaid
graph TB
    Client["Client Applications"]
    NGINX["NGINX Reverse Proxy<br/>(TLS, Load Balancing)"]
    FastAPI["FastAPI API Server<br/>(uvicorn)"]
    Worker["ARQ Background Workers<br/>(async job processing)"]
    
    DB[(PostgreSQL<br/>async via asyncpg<br/>+ SQLAlchemy 2.0)]
    Cache[(Redis<br/>caching, rate-limit<br/>& queue)]
    
    ExternalProviders["External Providers<br/>(via HTTP Client)"]
    
    Client -->|HTTPS| NGINX
    NGINX -->|HTTP| FastAPI
    FastAPI -->|SQL| DB
    FastAPI -->|pub/sub<br/>cache| Cache
    Worker -->|consume jobs| Cache
    Worker -->|SQL| DB
    Worker -->|HTTP| ExternalProviders
    FastAPI -->|HTTP| ExternalProviders
```

## Application Layer Architecture

The codebase is organized into logical layers, each with well-defined boundaries and dependencies. The diagram shows how data flows from routers through services to persistence.

```mermaid
graph TB
    API["api/\n(FastAPI Routers, Versioning)<br/>thin HTTP contract layer"]
    
    Domain["domain/\n(Business Logic)<br/>├─ entities/\n├─ schemas/\n├─ repositories/<br/>├─ auth_service\n├─ user_service\n├─ post_service\n├─ tier_service\n├─ rate_limit_service"]
    
    Platform["platform/\n(Cross-cutting Runtime)<br/>├─ settings\n├─ app factory/lifespan\n├─ security\n├─ logging\n├─ database\n├─ middleware\n├─ admin\n├─ cache/queue\n└─ exceptions"]
    
    Shared["shared/\n(Framework-agnostic Helpers)<br/>no runtime deps"]
    
    Workers["workers/\n(Background Jobs)<br/>├─ WorkerJob\n├─ JobEnvelope\n└─ WorkerSettings"]
    
    Webhooks["webhooks/\n(Inbound Ingestion)<br/>├─ signature verification\n├─ replay protection\n├─ idempotency\n├─ dead-letter\n└─ persistence"]
    
    Integrations["integrations/\n(Outbound HTTP)<br/>├─ TemplateHttpClient\n├─ circuit breaker\n├─ retry logic\n├─ rate-limit\n└─ BaseIntegrationClient"]
    
    Workflows["workflows/\n(Orchestration)<br/>├─ WorkflowStep\n├─ WorkflowRunner\n└─ compensation"]
    
    Core["core/\n(Legacy Compatibility)"]
    
    API -->|depends on| Domain
    API -->|depends on| Platform
    Domain -->|depends on| Platform
    Domain -->|depends on| Shared
    Workers -->|depends on| Platform
    Workers -->|depends on| Shared
    Webhooks -->|depends on| Platform
    Webhooks -->|depends on| Domain
    Integrations -->|depends on| Platform
    Integrations -->|depends on| Shared
    Workflows -->|depends on| Platform
    Workflows -->|depends on| Domain
    Core -->|compatibility shims| Platform
```

## Request Flow

A typical HTTP request travels through multiple layers, each adding value through middleware, authentication, rate limiting, and database session management.

```mermaid
graph LR
    Client["Client<br/>HTTP Request"]
    NGINX["NGINX"]
    
    MW1["Middleware Stack"]
    MW1_Items["├─ CORS<br/>├─ Security Headers<br/>├─ Trusted Host<br/>├─ Request Context<br/>└─ Body Limits"]
    
    Router["Router<br/>(api/)"]
    DI["Dependency Injection"]
    DI_Items["├─ Auth + JWT<br/>├─ Rate Limit Check<br/>└─ DB Session"]
    
    Service["Service Layer<br/>(domain/)"]
    Repository["Repository<br/>(data access)"]
    Database[(Database)]
    Response["Response"]
    
    Client -->|TLS| NGINX
    NGINX -->|HTTP| MW1
    MW1 -.->|config| MW1_Items
    MW1 -->|validated request| Router
    Router -->|resolve| DI
    DI -.->|inject| DI_Items
    DI -->|validated dependencies| Service
    Service -->|query/command| Repository
    Repository -->|SQL| Database
    Database -->|result set| Repository
    Repository -->|entities| Service
    Service -->|business result| Router
    Router -->|serialize| Response
    Response -->|JSON| Client
```

## Authentication Flow

JWT-based authentication with refresh token rotation and blacklist management ensures secure, long-lived sessions with automatic token refresh.

```mermaid
graph TD
    User["User"]
    Login["POST /auth/login"]
    Verify["Verify Credentials<br/>(password hash)"]
    Issue["Issue Tokens"]
    AccessToken["Access Token<br/>(short-lived JWT<br/>~15 min)"]
    RefreshToken["Refresh Token<br/>(long-lived JWT<br/>~7 days)<br/>stored as HttpOnly<br/>Secure cookie"]
    
    User -->|username + password| Login
    Login -->|hash compare| Verify
    Verify -->|valid| Issue
    Issue -->|sign kid-based| AccessToken
    Issue -->|sign kid-based| RefreshToken
    
    AccessToken -->|in Authorization header<br/>Bearer token| Client["Client"]
    RefreshToken -->|in HttpOnly cookie| Client
    
    Client -->|uses access JWT| API["API Calls"]
    API -->|verify signature<br/>check expiry| Validate["Validate"]
    Validate -->|expired?| CheckRefresh{Expired?}
    
    CheckRefresh -->|no| GrantAccess["Grant Access"]
    CheckRefresh -->|yes| RefreshCall["POST /auth/refresh"]
    
    RefreshCall -->|send refresh JWT| RefreshEndpoint["Refresh Endpoint"]
    RefreshEndpoint -->|verify not<br/>in blacklist| ValidateRefresh["Validate Refresh"]
    ValidateRefresh -->|valid| BlacklistOld["Add Old Refresh<br/>to Blacklist"]
    BlacklistOld -->|sign new kid| IssueNew["Issue New<br/>Access + Refresh"]
    IssueNew -->|return new tokens| Client
    IssueNew -->|cache for revocation| TokenBlacklist[(TokenBlacklist<br/>Table)]
```

## Data Model Overview

The platform manages several key persistence tables supporting authentication, rate limiting, webhooks, workflows, and audit trails.

```mermaid
graph TB
    User["User<br/>├─ id, email, username<br/>├─ password_hash<br/>├─ tier_id (FK)<br/>├─ permissions<br/>├─ created_at<br/>└─ updated_at"]
    
    Tier["Tier<br/>├─ id, name<br/>├─ request_limit<br/>├─ features JSON<br/>└─ cost_per_month"]
    
    RateLimit["RateLimit<br/>├─ id, user_id (FK)<br/>├─ tier_id (FK)<br/>├─ window_start<br/>├─ request_count<br/>└─ reset_at"]
    
    TokenBlacklist["TokenBlacklist<br/>├─ id, jti (JWT ID)<br/>├─ user_id (FK)<br/>├─ blacklisted_at<br/>└─ expires_at"]
    
    WebhookEvent["WebhookEvent<br/>├─ id, provider<br/>├─ signature, timestamp<br/>├─ payload JSON<br/>├─ processed<br/>└─ dead_letter_reason"]
    
    IdempotencyKey["IdempotencyKey<br/>├─ id, idempotency_key<br/>├─ user_id (FK)<br/>├─ request_hash<br/>├─ response_body<br/>└─ created_at"]
    
    WorkflowExecution["WorkflowExecution<br/>├─ id, workflow_id<br/>├─ user_id (FK)<br/>├─ status<br/>├─ current_step<br/>├─ context JSON<br/>└─ created_at"]
    
    JobStateHistory["JobStateHistory<br/>├─ id, job_id<br/>├─ state<br/>├─ result JSON<br/>├─ error<br/>├─ attempt<br/>└─ timestamp"]
    
    IntegrationSyncCheckpoint["IntegrationSyncCheckpoint<br/>├─ id, integration<br/>├─ user_id (FK)<br/>├─ last_cursor<br/>├─ last_sync_at<br/>└─ pages_synced"]
    
    AuditLogEvent["AuditLogEvent<br/>├─ id, user_id (FK)<br/>├─ action<br/>├─ resource<br/>├─ resource_id<br/>├─ changes JSON<br/>└─ timestamp"]
    
    DeadLetterRecord["DeadLetterRecord<br/>├─ id, source<br/>├─ original_payload JSON<br/>├─ error_reason<br/>├─ retry_count<br/>└─ created_at"]
    
    User ---|has many| RateLimit
    Tier ---|constrains| RateLimit
    User ---|revokes tokens| TokenBlacklist
    User ---|triggers| WebhookEvent
    User ---|creates| IdempotencyKey
    User ---|orchestrates| WorkflowExecution
    WorkflowExecution ---|tracks steps| JobStateHistory
    User ---|syncs| IntegrationSyncCheckpoint
    User ---|audited via| AuditLogEvent
    WebhookEvent ---|may become| DeadLetterRecord
    
    style User fill:#e1f5ff
    style Tier fill:#f3e5f5
    style RateLimit fill:#fff3e0
    style TokenBlacklist fill:#fce4ec
    style WebhookEvent fill:#e0f2f1
    style IdempotencyKey fill:#f1f8e9
    style WorkflowExecution fill:#ede7f6
    style JobStateHistory fill:#fbe9e7
    style IntegrationSyncCheckpoint fill:#e8f5e9
    style AuditLogEvent fill:#fff9c4
    style DeadLetterRecord fill:#ffebee
```

## Middleware & Security Pipeline

Request security is layered through multiple middleware components that validate, sanitize, and enrich incoming requests.

```mermaid
graph TB
    Request["Incoming Request"]
    
    CORS["CORS Middleware<br/>(trusted origins)"]
    SecurityHeaders["Security Headers<br/>(CSP, X-Frame, HSTS)"]
    TrustedHost["Trusted Host<br/>(Host header validation)"]
    RequestContext["Request Context<br/>(trace ID, user context)"]
    BodyLimit["Request Body Limit<br/>(size validation)"]
    
    Auth["Authentication<br/>(JWT verification)"]
    RateLimit["Rate Limit<br/>(token bucket)"]
    RBAC["RBAC Permission Check<br/>(role-based access)"]
    
    Handler["Route Handler"]
    
    Request --> CORS
    CORS --> SecurityHeaders
    SecurityHeaders --> TrustedHost
    TrustedHost --> RequestContext
    RequestContext --> BodyLimit
    BodyLimit --> Auth
    Auth --> RateLimit
    RateLimit --> RBAC
    RBAC -->|allowed| Handler
    RBAC -->|denied| Forbidden["403 Forbidden"]
```

## Service & Repository Pattern

The domain layer implements a clean separation between business logic (services) and data access (repositories), with SQLAlchemy 2.0 ORM backing persistence.

```mermaid
graph TB
    Router["Router<br/>(api/)"]
    
    Service["Service Layer<br/>(domain/)"]
    AuthService["auth_service<br/>├─ login()\n├─ refresh_token()\n├─ revoke_token()\n└─ verify_jwt()"]
    UserService["user_service<br/>├─ get_user()\n├─ create_user()\n├─ update_profile()\n└─ change_password()"]
    PostService["post_service<br/>├─ list_posts()\n├─ create_post()\n├─ update_post()\n└─ delete_post()"]
    TierService["tier_service<br/>├─ get_tier()\n├─ upgrade_tier()\n└─ check_limits()"]
    RateLimitService["rate_limit_service<br/>├─ check_limit()\n├─ increment_counter()\n└─ reset_window()"]
    
    Repository["Repository Layer<br/>(domain/)"]
    UserRepository["UserRepository<br/>├─ find_by_id()\n├─ find_by_email()\n├─ create()\n├─ update()\n└─ delete()"]
    PostRepository["PostRepository<br/>├─ find_by_id()\n├─ find_by_user()\n├─ create()\n├─ update()\n└─ delete()"]
    TierRepository["TierRepository<br/>├─ find_all()\n├─ find_by_id()\n└─ find_by_name()"]
    
    SQLAlchemy["SQLAlchemy 2.0 ORM<br/>(async)"]
    Database[(PostgreSQL)]
    
    Router -->|call business logic| Service
    Service -->|UserService| AuthService
    Service -->|UserService| UserService
    Service -->|PostService| PostService
    Service -->|TierService| TierService
    Service -->|RateLimitService| RateLimitService
    
    AuthService -->|query/command| UserRepository
    UserService -->|query/command| UserRepository
    PostService -->|query/command| PostRepository
    TierService -->|query/command| TierRepository
    RateLimitService -->|counter ops| SQLAlchemy
    
    UserRepository -->|ORM| SQLAlchemy
    PostRepository -->|ORM| SQLAlchemy
    TierRepository -->|ORM| SQLAlchemy
    
    SQLAlchemy -->|async SQL| Database
```

## Webhook Ingestion Pipeline

External webhooks flow through a multi-step pipeline with signature verification, replay protection, and eventual persistence.

```mermaid
graph LR
    Provider["External Provider<br/>(sends webhook)"]
    
    Endpoint["POST /webhooks/{provider}"]
    
    Signature["Verify Signature<br/>(HMAC-SHA256)"]
    Replay["Check Replay<br/>Protected?<br/>(timestamp)"]
    Idempotent["Check Idempotency<br/>Key<br/>(dedup)"]
    
    Persist["Persist to<br/>WebhookEvent"]
    Queue["Enqueue to<br/>ARQ Queue"]
    
    Worker["Background Worker<br/>processes event"]
    ProcessLogic["Apply Business<br/>Logic"]
    Success{Success?}
    DeadLetter["Move to<br/>DeadLetterRecord"]
    
    Provider -->|signature in header| Endpoint
    Endpoint -->|verify secret| Signature
    Signature -->|invalid?| Reject1["400 Bad Request"]
    Signature -->|valid| Replay
    Replay -->|stale?| Reject2["409 Conflict"]
    Replay -->|fresh| Idempotent
    Idempotent -->|duplicate?| Reject3["200 OK<br/>idempotent"]
    Idempotent -->|new| Persist
    Persist -->|200 OK| Queue
    Queue -->|consume| Worker
    Worker -->|execute| ProcessLogic
    ProcessLogic -->|result| Success
    Success -->|yes| Complete["Mark Complete"]
    Success -->|no| Retry{Retries<br/>Exhausted?}
    Retry -->|no| Queue
    Retry -->|yes| DeadLetter
```

## Background Worker Architecture

ARQ workers consume jobs from Redis queues and provide durable job execution with state tracking and retry logic.

```mermaid
graph TB
    Producer["Event Producer<br/>(API, Webhook)"]
    
    Queue["Redis Queue<br/>(ARQ)"]
    
    Worker["ARQ Worker<br/>(async process)"]
    
    JobEnvelope["JobEnvelope<br/>├─ job_id<br/>├─ queue_name<br/>├─ payload<br/>└─ max_retries"]
    
    ExecutionContext["Execution Context<br/>├─ settings<br/>├─ logger<br/>├─ db_session<br/>└─ http_client"]
    
    JobFunction["Job Function<br/>(WorkerJob)"]
    
    StateHistory["JobStateHistory<br/>├─ enqueued<br/>├─ processing<br/>├─ completed<br/>├─ failed<br/>└─ retry"]
    
    Database[(PostgreSQL)]
    
    ErrorHandler["Error Handler<br/>├─ log error<br/>├─ update state<br/>└─ schedule retry"]
    
    Producer -->|serialize| JobEnvelope
    JobEnvelope -->|push| Queue
    Queue -->|pop + ack| Worker
    Worker -->|deserialize| JobEnvelope
    Worker -->|setup| ExecutionContext
    ExecutionContext -->|execute| JobFunction
    JobFunction -->|result| StateHistory
    StateHistory -->|persist| Database
    JobFunction -->|error| ErrorHandler
    ErrorHandler -->|backoff retry| Queue
    ErrorHandler -->|log| Database
```

## External Integration Pattern

The TemplateHttpClient provides a resilient HTTP client for external API calls with automatic retry, circuit breaker, and rate limiting.

```mermaid
graph TB
    Service["Service Layer"]
    
    TemplateHttpClient["TemplateHttpClient<br/>├─ base_url<br/>├─ timeout<br/>├─ headers<br/>└─ auth"]
    
    CircuitBreaker["Circuit Breaker<br/>├─ closed<br/>├─ open<br/>└─ half_open"]
    
    RetryPolicy["Retry Policy<br/>├─ max_retries<br/>├─ backoff<br/>└─ jitter"]
    
    RateLimit["Rate Limiter<br/>├─ requests/sec<br/>├─ tokens<br/>└─ refill rate"]
    
    Request["HTTP Request<br/>(GET, POST, etc)"]
    
    Response["Response<br/>├─ status<br/>├─ headers<br/>└─ body"]
    
    Timeout["Timeout Handler"]
    Error["Error Handler<br/>├─ circuit open<br/>├─ retry exhausted<br/>└─ rate limit"]
    
    Service -->|create client| TemplateHttpClient
    TemplateHttpClient -->|check state| CircuitBreaker
    CircuitBreaker -->|closed/half_open| RetryPolicy
    CircuitBreaker -->|open| Error
    RetryPolicy -->|acquire token| RateLimit
    RateLimit -->|ready| Request
    RateLimit -->|backpressure| Error
    Request -->|send| Response
    Response -->|success| CircuitBreaker
    Response -->|failure| Timeout
    Timeout -->|retry?| RetryPolicy
    Timeout -->|exhausted| Error
```

## Observability & Monitoring Stack

Optional integrations for metrics, tracing, error monitoring, and structured logging provide comprehensive observability.

```mermaid
graph TB
    Application["Application<br/>(FastAPI)"]
    
    StructuredLogging["Structured Logging<br/>(structlog)"]
    Metrics["Prometheus Metrics<br/>(opt-in)"]
    Tracing["OpenTelemetry<br/>Tracing<br/>(opt-in)"]
    ErrorMonitoring["Sentry Error<br/>Monitoring<br/>(opt-in)"]
    
    LogAggregation["Log Aggregation<br/>(ELK, Datadog, etc)"]
    MetricsDB["Metrics DB<br/>(Prometheus,<br/>VictoriaMetrics)"]
    TracingBackend["Tracing Backend<br/>(Jaeger, Tempo,<br/>Datadog)"]
    ErrorTracker["Error Tracker<br/>(Sentry)"]
    
    Dashboard["Monitoring Dashboard<br/>(Grafana, Datadog)"]
    Alerts["Alerting<br/>(PagerDuty, etc)"]
    
    Application -->|emit| StructuredLogging
    Application -->|emit| Metrics
    Application -->|emit| Tracing
    Application -->|capture| ErrorMonitoring
    
    StructuredLogging -->|ship| LogAggregation
    Metrics -->|scrape| MetricsDB
    Tracing -->|export| TracingBackend
    ErrorMonitoring -->|report| ErrorTracker
    
    LogAggregation -->|query| Dashboard
    MetricsDB -->|query| Dashboard
    TracingBackend -->|query| Dashboard
    ErrorTracker -->|query| Dashboard
    
    Dashboard -->|rule trigger| Alerts
```

## Deployment Architecture

The application can be deployed in containerized environments with PostgreSQL and Redis as required external services.

```mermaid
graph TB
    DevEnv["Development<br/>(uvicorn)<br/>localhost:8000"]
    
    ProdContainer["Production<br/>Environment"]
    Container["Container<br/>(Docker)"]
    FastAPIApp["FastAPI App<br/>(gunicorn +<br/>uvicorn workers)"]
    Workers["ARQ Workers<br/>(separate containers)"]
    
    PostgreSQL["PostgreSQL<br/>(managed/self-hosted)"]
    Redis["Redis<br/>(managed/self-hosted)"]
    
    LoadBalancer["Load Balancer<br/>(ALB, NLB)"]
    AutoScale["Auto-scaling<br/>Group"]
    
    Migrations["Alembic Migrations<br/>(on startup)"]
    HealthCheck["Health Check<br/>Endpoint<br/>(/health)"]
    
    DevEnv -->|develop| Container
    ProdContainer -->|multi-container| Container
    Container -->|run| FastAPIApp
    Container -->|run| Workers
    FastAPIApp -->|SQL| PostgreSQL
    FastAPIApp -->|cache/queue| Redis
    Workers -->|SQL| PostgreSQL
    Workers -->|consume| Redis
    FastAPIApp -->|init| Migrations
    FastAPIApp -->|liveness| HealthCheck
    FastAPIApp -->|distributed| LoadBalancer
    LoadBalancer -->|scale| AutoScale
```

## Configuration Management

Settings flow from environment variables through a centralized Pydantic configuration model, enabling flexible deployment across environments.

```mermaid
graph LR
    Environment["Environment<br/>Variables"]
    
    SettingsModel["Settings Model<br/>(pydantic)<br/>├─ database_url<br/>├─ redis_url<br/>├─ jwt_secret<br/>├─ jwt_algorithm<br/>├─ jwt_expiry<br/>├─ allowed_origins<br/>├─ sentry_dsn<br/>├─ log_level<br/>└─ debug"]
    
    AppFactory["App Factory<br/>(create_app)"]
    
    Middleware["Middleware<br/>Configuration"]
    Routes["Route<br/>Registration"]
    Dependencies["Dependency<br/>Injection"]
    Lifespan["App Lifespan<br/>Events"]
    
    FastAPIApp["FastAPI App<br/>(configured)"]
    
    Environment -->|load| SettingsModel
    SettingsModel -->|pass| AppFactory
    AppFactory -->|setup| Middleware
    AppFactory -->|setup| Routes
    AppFactory -->|setup| Dependencies
    AppFactory -->|setup| Lifespan
    Middleware -->|build| FastAPIApp
    Routes -->|build| FastAPIApp
    Dependencies -->|build| FastAPIApp
    Lifespan -->|build| FastAPIApp
```

## Database Connection Lifecycle

AsyncPG with SQLAlchemy 2.0 provides high-performance async database operations with connection pooling and session management.

```mermaid
graph TB
    AppStart["App Startup<br/>(lifespan)"]
    
    ConnPool["Connection Pool<br/>(asyncpg)<br/>├─ min_size<br/>├─ max_size<br/>└─ timeout"]
    
    SessionFactory["Session Factory<br/>(AsyncSession)"]
    
    Request["HTTP Request"]
    
    GetSession["Dependency:<br/>get_db()"]
    
    ActiveSession["Active Session<br/>for request"]
    
    Query["SQLAlchemy Query"]
    
    Execute["Execute via<br/>AsyncPG"]
    
    Rollback["Auto Rollback<br/>on error"]
    
    Cleanup["Session Cleanup<br/>(commit or<br/>rollback)"]
    
    AppStop["App Shutdown<br/>(lifespan)"]
    
    DisposePool["Dispose Pool<br/>(close all<br/>connections)"]
    
    AppStart -->|initialize| ConnPool
    ConnPool -->|create factory| SessionFactory
    Request -->|inject| GetSession
    GetSession -->|acquire from pool| ActiveSession
    ActiveSession -->|use in handler| Query
    Query -->|async execute| Execute
    Execute -->|result| Query
    Query -->|error?| Rollback
    Rollback -->|cleanup| Cleanup
    Cleanup -->|return to pool| ConnPool
    AppStop -->|signal| DisposePool
    DisposePool -->|close all| ConnPool
```

## Key Design Patterns

### Repository Pattern
All data access is abstracted behind repository interfaces, enabling testability and potential database migration without affecting business logic.

### Service Layer Pattern
Business logic lives in services that orchestrate repositories and coordinate domain operations. Services are stateless and reusable.

### Dependency Injection
FastAPI's built-in DI system injects authenticated users, rate limit info, database sessions, and other dependencies at the handler level.

### Circuit Breaker Pattern
The external HTTP client implements circuit breaker to fail fast on cascading failures from downstream services.

### Event-Driven Architecture
Webhooks and background jobs decouple time-critical API responses from long-running operations via async job queues.

### RBAC (Role-Based Access Control)
Permission checks operate at the middleware/dependency level, enforcing authorization before route handlers execute.

### Idempotency Keys
POST/PUT requests support idempotency keys to prevent duplicate side effects from retried requests.

---

**Last Updated:** 2026-04-10 | **Architecture Version:** 1.0