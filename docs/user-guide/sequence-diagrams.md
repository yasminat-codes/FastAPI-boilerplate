# Sequence Diagrams

This document illustrates the key flows in the FastAPI template application using Mermaid sequence diagrams. These diagrams show the interactions between components for critical operations.

---

## 1. Webhook Ingestion Flow

The webhook ingestion pipeline provides a robust, idempotent mechanism for receiving and processing external events. It includes signature verification, replay protection, and deduplication to ensure data integrity. Events are persisted immediately and processed asynchronously via a background job queue.

**Key Features:**
- Request context tracking (request ID, correlation ID)
- Provider-specific HMAC/signature verification
- Configurable replay window protection
- Idempotency via event deduplication
- Immediate acknowledgment to provider
- Asynchronous event processing with retry logic
- Dead-letter handling for failed events

```mermaid
sequenceDiagram
    actor Provider as External Provider
    participant NGINX
    participant FastAPI as FastAPI App
    participant Middleware as RequestContext<br/>Middleware
    participant RateLimit as Rate Limiter
    participant BodyCapture as build_webhook<br/>_ingestion_request()
    participant Verifier as Provider Signature<br/>Verifier
    participant ReplayCheck as Replay<br/>Protector
    participant IdempCheck as Idempotency<br/>Protector
    participant EventStore as WebhookEventStore
    participant Queue as ARQ Redis<br/>Queue
    participant Worker as Background<br/>Worker
    participant DeadLetter as Dead Letter<br/>Storage

    Provider->>NGINX: POST /api/v1/webhooks/{provider}
    NGINX->>FastAPI: Forward request
    FastAPI->>Middleware: Process request
    Middleware->>Middleware: Assign request_id, correlation_id
    Middleware->>RateLimit: Check rate limits
    alt Rate limit exceeded
        RateLimit-->>Provider: 429 Too Many Requests
    else Rate limit OK
        RateLimit->>BodyCapture: Proceed
        BodyCapture->>BodyCapture: Capture raw body bytes
        BodyCapture->>Verifier: Validate HMAC/signature
        alt Signature invalid
            Verifier-->>Provider: 401 Unauthorized
        else Signature valid
            Verifier->>ReplayCheck: Check timestamp window
            alt Timestamp outside window
                ReplayCheck-->>Provider: 400 Bad Request
            else Timestamp valid
                ReplayCheck->>IdempCheck: Check event_id for duplicates
                alt Event already processed
                    IdempCheck-->>Provider: 200 OK (idempotent)
                else New event
                    IdempCheck->>EventStore: Persist event (status=received)
                    EventStore-->>FastAPI: Event stored
                    FastAPI-->>Provider: 200 OK
                    FastAPI->>Queue: Enqueue event for processing
                    Queue-->>FastAPI: Job queued
                    
                    par Worker Processing
                        Worker->>Queue: Poll for jobs
                        Queue-->>Worker: Get event job
                        Worker->>Worker: Deserialize event
                        Worker->>Worker: Bind correlation_id to context
                        Worker->>EventStore: Process event (status=processing)
                        alt Processing succeeds
                            Worker->>EventStore: Update status=processed
                            Worker-->>Queue: Mark job complete
                        else Processing fails (transient)
                            Worker->>Worker: Raise RetryableJobError
                            Worker-->>Queue: Retry with exponential backoff
                            Queue->>Queue: Re-enqueue with backoff
                        else Processing fails (permanent)
                            Worker->>Worker: Raise NonRetryableJobError
                            Worker->>EventStore: Update status=failed
                            Worker->>DeadLetter: Send to dead letter
                            Worker-->>Queue: Mark job failed
                        end
                    end
                end
            end
        end
    end
```

---

## 2. Background Job Execution Flow

The background job execution system handles asynchronous work with full context preservation, comprehensive error handling, and automatic retry logic. Jobs are enqueued with correlation context to maintain observability across distributed operations.

**Key Features:**
- Context-aware job execution (correlation ID, tenant context)
- Configurable retry policies with exponential backoff and jitter
- Transient vs. permanent failure handling
- Job state tracking and history
- Dead-letter queue for unrecoverable failures
- Alert hooks for failures
- Database session lifecycle management

```mermaid
sequenceDiagram
    participant Trigger as API Handler /<br/>Webhook Processor
    participant JobEnvelope as JobEnvelope
    participant WorkerJob as WorkerJob
    participant Queue as ARQ Redis<br/>Queue
    participant Worker as ARQ Worker
    participant Logger as Structlog<br/>Context
    participant DB as Database
    participant JobHistory as JobStateHistory
    participant Alerts as Alert Hooks
    participant DeadLetter as Dead Letter<br/>Queue

    Trigger->>JobEnvelope: Create with correlation_id,<br/>tenant_context, retry_policy
    JobEnvelope-->>Trigger: JobEnvelope instance
    Trigger->>WorkerJob: enqueue(envelope)
    WorkerJob->>WorkerJob: Serialize JobEnvelope
    WorkerJob->>Queue: Push to ARQ Redis queue
    Queue-->>WorkerJob: Queued
    WorkerJob-->>Trigger: Job queued

    par Worker Poll Cycle
        Worker->>Queue: Poll for jobs
        Queue-->>Worker: Get JobEnvelope
        Worker->>Worker: Deserialize JobEnvelope
        Worker->>Logger: Bind correlation_id to context
        Worker->>DB: Initialize session (job scope)
        DB-->>Worker: Session ready
        Worker->>Worker: Execute job.execute()
        
        alt Job succeeds
            Worker->>JobHistory: Record completion
            JobHistory-->>Worker: State updated
            Worker->>DB: Commit transaction
            Worker-->>Queue: Mark job complete
            Worker->>DB: Close session
        else Transient failure
            Worker->>Worker: Raise RetryableJobError
            Worker->>JobHistory: Record attempt, retry scheduled
            JobHistory-->>Worker: State updated
            Worker->>Queue: Retry with exponential backoff + jitter
            Queue->>Queue: Re-enqueue for later retry
            Worker->>DB: Rollback transaction
            Worker->>DB: Close session
        else Permanent failure
            Worker->>Worker: Raise NonRetryableJobError
            Worker->>JobHistory: Record failure
            JobHistory-->>Worker: State updated
            Worker->>DeadLetter: Send job to dead letter queue
            Worker->>Alerts: Fire alert hooks
            Alerts-->>Worker: Alert sent
            Worker-->>Queue: Mark job failed
            Worker->>DB: Rollback transaction
            Worker->>DB: Close session
        end
    end
```

---

## 3. Workflow Orchestration Flow

The workflow orchestration system enables complex multi-step operations with retry logic, compensation (rollback) capabilities, and comprehensive state tracking. Workflows can be triggered by webhooks, API calls, or scheduled jobs and maintain full visibility into execution progress.

**Key Features:**
- WorkflowExecution state tracking
- Sequential step execution with result recording
- Per-step retry policies
- Compensation steps for rollback on failure
- Comprehensive error context
- Status transitions (running → completed/failed)
- Step-level result persistence

```mermaid
sequenceDiagram
    actor Client
    participant Trigger as Webhook Event /<br/>API Call / Scheduled Job
    participant Runner as WorkflowRunner
    participant Store as Workflow State<br/>Store
    participant Step as WorkflowStep
    participant StepExecutor as Step Executor
    participant CompensationMgr as Compensation<br/>Manager
    participant ErrorRecorder as Error<br/>Recorder

    Client->>Trigger: Initiate workflow
    Trigger->>Runner: Start workflow
    Runner->>Store: Create WorkflowExecution (status=running)
    Store-->>Runner: Execution created
    Runner-->>Trigger: Workflow started

    par Workflow Execution
        Runner->>Runner: Iterate WorkflowStep list
        loop For each step in workflow
            Runner->>Store: Update step status=in_progress
            Store-->>Runner: Status updated
            Runner->>Step: Get step definition
            Step-->>Runner: Step config
            Runner->>StepExecutor: Execute step logic
            
            alt Step succeeds
                StepExecutor-->>Runner: Step result
                Runner->>Store: Record step result, status=completed
                Store-->>Runner: Result recorded
            else Step fails (transient)
                StepExecutor->>Runner: Exception raised
                Runner->>Step: Check retry policy
                Step-->>Runner: Retry configuration
                alt Max retries not exceeded
                    Runner->>Store: Schedule retry with backoff
                    Store-->>Runner: Retry scheduled
                    Runner->>StepExecutor: Re-execute with backoff
                else Max retries exceeded
                    Runner->>CompensationMgr: Begin compensation
                else Step fails (permanent)
                    StepExecutor->>Runner: Exception raised
                    Runner->>CompensationMgr: Begin compensation
                end
            end
        end
    end

    alt All steps completed successfully
        Runner->>Store: Update WorkflowExecution (status=completed)
        Store-->>Runner: Status updated
        Runner-->>Client: Workflow completed
    else Unrecoverable failure
        CompensationMgr->>Store: Get completed steps in order
        Store-->>CompensationMgr: Step list
        CompensationMgr->>CompensationMgr: Iterate steps in reverse order
        loop Reverse step iteration
            CompensationMgr->>Step: Get compensation logic
            Step-->>CompensationMgr: Compensation definition
            CompensationMgr->>StepExecutor: Execute compensation
            StepExecutor-->>CompensationMgr: Compensation done
            CompensationMgr->>Store: Record compensation result
            Store-->>CompensationMgr: Recorded
        end
        CompensationMgr->>ErrorRecorder: Record error context
        ErrorRecorder-->>CompensationMgr: Error recorded
        Runner->>Store: Update WorkflowExecution (status=failed, error_context)
        Store-->>Runner: Status updated
        Runner-->>Client: Workflow failed
    end
```

---

## 4. Authentication and Token Lifecycle

The authentication system provides secure JWT-based token management with short-lived access tokens, persistent refresh tokens, and token rotation. Password verification uses bcrypt with configurable work factors, and all tokens are tracked in a blacklist for immediate revocation.

**Key Features:**
- Password hashing with bcrypt (configurable rounds)
- JWT access tokens with key ID (kid) headers
- Refresh token rotation with automatic blacklist
- HttpOnly, Secure, SameSite cookie policies
- Token blacklist for revocation
- Subject extraction (user, roles, permissions, tenant)
- Automatic blacklist cleanup via scheduled jobs

```mermaid
sequenceDiagram
    actor Client
    participant AuthEndpoint as Authentication<br/>Endpoint
    participant PasswordVerifier as Password<br/>Verifier (bcrypt)
    participant JWTIssuer as JWT Issuer
    participant KeyStore as Key Store<br/>(kid lookup)
    participant TokenCache as Token<br/>Blacklist Cache
    participant DB as Database
    participant APIEndpoint as Protected<br/>API Endpoint
    participant TokenValidator as JWT<br/>Validator
    participant SubjectExtractor as Subject<br/>Extractor
    participant RefreshEndpoint as Refresh<br/>Endpoint
    participant CleanupJob as Blacklist<br/>Cleanup Job

    Client->>AuthEndpoint: POST /login with credentials
    AuthEndpoint->>PasswordVerifier: Verify password hash (bcrypt)
    alt Password invalid
        PasswordVerifier-->>AuthEndpoint: Verification failed
        AuthEndpoint-->>Client: 401 Unauthorized
    else Password valid
        PasswordVerifier-->>AuthEndpoint: Verification succeeded
        AuthEndpoint->>JWTIssuer: Create access JWT
        JWTIssuer->>KeyStore: Get key with kid
        KeyStore-->>JWTIssuer: Key retrieved
        JWTIssuer->>JWTIssuer: Create JWT (iss, aud, kid, exp claims)
        JWTIssuer-->>AuthEndpoint: Access token
        AuthEndpoint->>JWTIssuer: Create refresh JWT
        JWTIssuer->>JWTIssuer: Create JWT (longer-lived, exp claims)
        JWTIssuer-->>AuthEndpoint: Refresh token
        AuthEndpoint->>AuthEndpoint: Set-Cookie refresh token<br/>(Secure, HttpOnly, SameSite=Lax)
        AuthEndpoint-->>Client: 200 OK + access_token + refresh cookie
    end

    par API Request with Access Token
        Client->>APIEndpoint: GET /api/v1/resource<br/>Authorization: Bearer {access_token}
        APIEndpoint->>TokenValidator: Validate JWT signature
        TokenValidator->>KeyStore: Get key by kid from token header
        KeyStore-->>TokenValidator: Key retrieved
        TokenValidator->>TokenValidator: Verify signature
        alt Signature invalid
            TokenValidator-->>APIEndpoint: Invalid signature
            APIEndpoint-->>Client: 401 Unauthorized
        else Signature valid
            TokenValidator->>TokenCache: Check if token in blacklist
            alt Token is blacklisted
                TokenCache-->>TokenValidator: Token blacklisted
                TokenValidator-->>APIEndpoint: Token revoked
                APIEndpoint-->>Client: 401 Unauthorized
            else Token not blacklisted
                TokenValidator-->>APIEndpoint: Token valid
                APIEndpoint->>SubjectExtractor: Extract authorization subject
                SubjectExtractor->>SubjectExtractor: Parse user, roles,<br/>permissions, tenant_context
                SubjectExtractor-->>APIEndpoint: Subject context
                APIEndpoint->>APIEndpoint: Authorize + process request
                APIEndpoint-->>Client: 200 OK + resource
            end
        end
    end

    Client->>RefreshEndpoint: POST /refresh with refresh cookie
    RefreshEndpoint->>TokenValidator: Validate refresh JWT
    TokenValidator->>KeyStore: Get key by kid
    KeyStore-->>TokenValidator: Key retrieved
    TokenValidator->>TokenValidator: Verify signature
    alt Refresh token invalid/expired
        TokenValidator-->>RefreshEndpoint: Invalid refresh token
        RefreshEndpoint-->>Client: 401 Unauthorized
    else Refresh token valid
        RefreshEndpoint->>TokenCache: Check if refresh token blacklisted
        alt Token is blacklisted
            TokenCache-->>RefreshEndpoint: Token blacklisted
            RefreshEndpoint-->>Client: 401 Unauthorized
        else Token valid
            RefreshEndpoint->>TokenCache: Blacklist old refresh token
            TokenCache-->>RefreshEndpoint: Old token blacklisted
            RefreshEndpoint->>JWTIssuer: Create new access JWT
            JWTIssuer-->>RefreshEndpoint: New access token
            RefreshEndpoint->>JWTIssuer: Create new refresh JWT
            JWTIssuer-->>RefreshEndpoint: New refresh token
            RefreshEndpoint->>RefreshEndpoint: Set-Cookie new refresh token<br/>(Secure, HttpOnly, SameSite=Lax)
            RefreshEndpoint-->>Client: 200 OK + new access_token + new refresh cookie
        end
    end

    Client->>AuthEndpoint: POST /logout
    AuthEndpoint->>TokenCache: Blacklist access token
    TokenCache-->>AuthEndpoint: Access token blacklisted
    AuthEndpoint->>TokenCache: Blacklist refresh token
    TokenCache-->>AuthEndpoint: Refresh token blacklisted
    AuthEndpoint-->>Client: 200 OK

    par Scheduled Maintenance
        CleanupJob->>DB: Query expired blacklist entries
        DB-->>CleanupJob: Expired entries
        CleanupJob->>DB: Delete expired entries
        DB-->>CleanupJob: Entries deleted
        CleanupJob->>TokenCache: Sync cache after deletion
        TokenCache-->>CleanupJob: Cache synced
    end
```

---

## Implementation Notes

### Webhook Ingestion Flow
- **Request Context**: `RequestContextMiddleware` automatically assigns unique `request_id` and `correlation_id` to track requests through the system
- **Signature Verification**: Raw request body bytes are captured before parsing to ensure HMAC verification uses identical bytes to the provider's signature
- **Replay Protection**: Configurable via `WEBHOOK_REPLAY_WINDOW_SECONDS` environment variable
- **Idempotency**: Event deduplication prevents duplicate processing of the same webhook payload
- **Asynchronous Processing**: Fast acknowledgment to provider decouples ingestion from processing, improving reliability

### Background Job Execution Flow
- **Context Preservation**: Correlation IDs and tenant context are bound to structured logging context for full observability
- **Error Classification**: Jobs distinguish between transient errors (retryable) and permanent errors (fail-fast)
- **Exponential Backoff**: Retry timing uses exponential backoff with jitter to prevent thundering herd
- **Dead Letter**: Unrecoverable failures are sent to dead-letter queue with alert notifications

### Workflow Orchestration Flow
- **Compensation Steps**: Failed steps trigger reverse-order compensation for automatic rollback
- **Step Retries**: Each step can have independent retry policies separate from the overall workflow
- **State Persistence**: All step results and workflow state are persisted for auditability
- **Error Context**: Comprehensive error information is recorded for debugging and monitoring

### Authentication and Token Lifecycle
- **JWT Structure**: Access tokens include `kid` (key ID) header for key rotation support without downtime
- **Token Claims**: Tokens include standard claims (`iss`, `aud`, `exp`) plus custom subject claims
- **Cookie Security**: Refresh tokens are stored in `HttpOnly`, `Secure`, `SameSite=Lax` cookies to mitigate XSS
- **Token Rotation**: Refresh operations issue both new access and refresh tokens with automatic rotation
- **Blacklist Cleanup**: Expired blacklist entries are automatically pruned by scheduled maintenance job
