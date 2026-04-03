# Database Reliability

This guide documents the template's database reliability posture: how the async engine is tuned, how sessions should be scoped, and how to handle timeouts, retries, and SSL in a reusable way.

## Engine Hardening

The template exposes SQLAlchemy engine tuning through `src.app.core.config.PostgresSettings` and builds the async engine in `src/app/core/db/database.py`.

Use these settings to keep production connections stable:

- `DATABASE_POOL_SIZE` and `DATABASE_MAX_OVERFLOW` control pool capacity.
- `DATABASE_POOL_PRE_PING` helps detect stale connections before they are handed to a request.
- `DATABASE_POOL_USE_LIFO` prefers reusing hotter connections instead of round-robining through the full pool.
- `DATABASE_POOL_RECYCLE` bounds connection age for long-lived workers and load balancers.
- `DATABASE_POOL_TIMEOUT` limits how long callers wait for a pool slot.
- `DATABASE_CONNECT_TIMEOUT` and `DATABASE_COMMAND_TIMEOUT` keep connection and driver-level waits bounded.
- `DATABASE_STATEMENT_TIMEOUT_MS` can be used to enforce a server-side statement timeout for PostgreSQL.
- `DATABASE_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS` helps fail sessions that sit idle inside an open transaction.
- `DATABASE_STARTUP_RETRY_*` settings bound how aggressively API and worker startup retry initial engine connectivity.

The canonical code paths that expose this behavior are:

- `src/app/core/db/database.py`
- `src/app/platform/database.py`

## Session Scoping Rules

Use the smallest session scope that fits the work being done:

- API requests should use `Depends(async_get_db)` so each request gets its own short-lived session.
- Background jobs should use `async_get_job_db()` or `open_database_session(..., DatabaseSessionScope.BACKGROUND_JOB)` so each job execution owns its own session.
- Scripts and maintenance tasks should use `async_get_script_db()` or `open_database_session(..., DatabaseSessionScope.SCRIPT)` rather than sharing sessions across operations.

Recommended pattern for multi-step work:

```python
from src.app.platform.database import (
    DatabaseSessionScope,
    database_transaction,
    local_session,
    open_database_session,
)


async with open_database_session(local_session, DatabaseSessionScope.SCRIPT) as db:
    async with database_transaction(db):
        ...
```

That keeps commit boundaries clear, lets exceptions roll back the unit of work automatically, and avoids leaking a session beyond the logical operation that owns it.

## Timeout Strategy

The template keeps timeout responsibilities layered:

- Connection acquisition timeout: `DATABASE_POOL_TIMEOUT`
- Database connection timeout: `DATABASE_CONNECT_TIMEOUT`
- Driver command timeout: `DATABASE_COMMAND_TIMEOUT`
- PostgreSQL server-side statement timeout: `DATABASE_STATEMENT_TIMEOUT_MS`

Use shorter values for external-facing APIs and longer values for administrative or batch flows. The important rule is to keep timeouts explicit so a slow query fails predictably instead of holding a worker or request open indefinitely.

## Retry Guidance

Database retries are safest when the operation is idempotent or read-only:

- Retrying a health check or a read query is generally safe.
- Retrying a write is only safe when the write is idempotent or guarded by a deduplication key.
- For long-running workflows, prefer retrying at the workflow/job layer instead of replaying the same transaction automatically inside repository code.

The template does not hide database retries behind the ORM. That keeps retry behavior visible to the caller and makes it easier to reason about duplicate writes.

When you do need a bounded retry helper, use `retry_database_operation(...)` from `src.app.platform.database` around read-only or explicitly idempotent work.

## SSL Guidance

The template supports PostgreSQL SSL through `DATABASE_SSL_MODE` and related certificate settings:

- `disable` disables database SSL.
- `require` turns on SSL without hostname verification.
- `verify-ca` and `verify-full` require `DATABASE_SSL_CA_FILE`.

When client certificates are used, provide `DATABASE_SSL_CERT_FILE` and `DATABASE_SSL_KEY_FILE` together.

The SSL implementation lives in `src/app/core/db/database.py`, while the validation rules live in `src/app/core/config.py`.

## How This Connects To The Template

- API routes should rely on the request-scoped dependency in `src/app/api/dependencies.py`.
- App startup primes the shared async engine and then tears it down through the lifespan in `src/app/core/setup.py`.
- Worker startup now uses the same template-owned DB primitives so API and background processes stay aligned.

If you are adding a new client project, start with these defaults and only widen scopes or raise timeouts where the workload truly needs it.
