# Troubleshooting Guide

This guide covers the most common failure scenarios in a production FastAPI application using FastAPI, PostgreSQL, Redis, ARQ workers, and Alembic migrations.

## Application Won't Start

### Symptom: Application crashes immediately on startup

#### Missing or Invalid DATABASE_URL

**Error Message:**
```
sqlalchemy.exc.ArgumentError: Could not parse SQLAlchemy URL
ValueError: could not convert string to Credential object
```

**Why It Happens:**
The `DATABASE_URL` environment variable is missing, malformed, or uses incorrect credentials.

**How to Fix:**

1. Verify `DATABASE_URL` is set:
```bash
echo $DATABASE_URL
```

2. Check the format matches your database:
```bash
# PostgreSQL with SSL
postgresql://user:password@host:5432/dbname?sslmode=require

# PostgreSQL without SSL (development only)
postgresql://user:password@localhost:5432/dbname
```

3. Test the connection directly:
```bash
psql $DATABASE_URL
```

4. If using a connection string from a service (RDS, Railway, etc.), ensure special characters are URL-encoded:
```bash
# Example: password with @ symbol
postgresql://user:p%40ssword@host:5432/dbname
```

---

#### Missing SECRET_KEY in Production

**Error Message:**
```
ValueError: SECRET_KEY environment variable not set
KeyError: 'SECRET_KEY'
```

**Why It Happens:**
The `SECRET_KEY` environment variable is required for JWT signing but wasn't provided. This is a security-critical setting.

**How to Fix:**

1. Generate a secure key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

2. Set the environment variable:
```bash
export SECRET_KEY="your-generated-key-here"
```

3. In Docker, add to `.env` or pass via docker-compose:
```yaml
environment:
  - SECRET_KEY=${SECRET_KEY}
```

4. In production (Heroku, Railway, etc.), set via the platform's environment configuration.

!!! warning "Security Note"
    Never commit `SECRET_KEY` to version control. Use environment variables or secrets management (AWS Secrets Manager, HashiCorp Vault, etc.).

---

#### Redis Connection Refused

**Error Message:**
```
redis.exceptions.ConnectionError: Error -2 connecting to localhost:6379.
Name or service not known.

redis.exceptions.ConnectionError: Error 111 connecting to 127.0.0.1:6379.
Connection refused.
```

**Why It Happens:**
Redis is not running, the host/port is incorrect, or there's a network connectivity issue.

**How to Fix:**

1. Check if Redis is running:
```bash
ps aux | grep redis
```

2. Start Redis locally:
```bash
# macOS (using Homebrew)
brew services start redis

# Linux
sudo systemctl start redis-server

# Docker
docker run -d -p 6379:6379 redis:latest
```

3. Verify Redis is accessible:
```bash
redis-cli ping
# Should return: PONG
```

4. Check `REDIS_URL` environment variable:
```bash
echo $REDIS_URL
# Should be: redis://localhost:6379/0 (or your actual host)
```

5. Test the connection with credentials (if using password-protected Redis):
```bash
redis-cli -h your-host -p 6379 --pass your-password ping
```

---

#### Port Already in Use

**Error Message:**
```
OSError: [Errno 98] Address already in use
socket.error: [Errno 48] Address already in use
```

**Why It Happens:**
Another process is already listening on the port (default 8000).

**How to Fix:**

1. Find the process using the port:
```bash
# macOS/Linux
lsof -i :8000

# Windows
netstat -ano | findstr :8000
```

2. Kill the process:
```bash
# macOS/Linux
kill -9 <PID>

# Windows
taskkill /PID <PID> /F
```

3. Or use a different port:
```bash
uvicorn main:app --port 8001
```

4. In Docker, check your port mapping:
```bash
# Wrong
docker run -p 8000:8000 app  # Both sides should match

# Correct
docker run -p 8000:8000 app
docker run -p 8001:8000 app  # Host:Container
```

---

#### Migration Not Applied (Tables Missing)

**Error Message:**
```
sqlalchemy.exc.ProgrammingError: (psycopg2.errors.UndefinedTable)
relation "users" does not exist

sqlalchemy.exc.OperationalError: (psycopg2.errors.UndefinedTable)
column "user_id" of relation "posts" does not exist
```

**Why It Happens:**
Alembic migrations haven't been applied to the database yet.

**How to Fix:**

1. Check current migration status:
```bash
alembic current
```

2. Upgrade to the latest migration:
```bash
alembic upgrade head
```

3. If running in Docker, ensure migration runs before app starts:
```dockerfile
# Dockerfile
FROM python:3.11
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

# Run migrations
RUN alembic upgrade head

# Start app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0"]
```

4. Better: Use an init container in docker-compose:
```yaml
services:
  api:
    build: .
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/myapp
    depends_on:
      - db
      - migrate

  migrate:
    build: .
    command: alembic upgrade head
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/myapp
    depends_on:
      - db

  db:
    image: postgres:15
    environment:
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=myapp
```

---

## Database Issues

### Connection Pool Exhausted (Too Many Connections)

**Error Message:**
```
sqlalchemy.exc.ResourceClosedError: QueuePool limit of size X reached
sqlalchemy.pool.NullPool does not use connection pooling

psycopg2.OperationalError: too many connections for role "user"
```

**Why It Happens:**
The connection pool size is too small for the number of concurrent requests, or connections aren't being returned to the pool.

**How to Fix:**

1. Increase the connection pool size:
```python
# In your database configuration
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,           # Increase from default 5
    max_overflow=40,        # Allow 40 more temporary connections
    pool_pre_ping=True,     # Verify connections before use
    pool_recycle=3600,      # Recycle connections after 1 hour
)
```

2. Enable connection pooling debug logging:
```python
import logging
logging.basicConfig()
logging.getLogger('sqlalchemy.pool').setLevel(logging.DEBUG)
```

3. Check for connection leaks (sessions not closed):
```python
# Bad: Connection leak
user = db.query(User).first()
# Session not closed, connection held

# Good: Proper cleanup
with db.begin():
    user = db.query(User).first()
# Session auto-closed
```

4. Monitor active connections:
```sql
-- Check active connections
SELECT count(*) FROM pg_stat_activity WHERE state = 'active';

-- See what's running
SELECT pid, usename, application_name, query, state
FROM pg_stat_activity
WHERE state != 'idle';
```

5. For long-running processes, use `expire_on_commit=False`:
```python
session = SessionLocal()
user = session.query(User).first()
session.commit()
# Attributes still accessible
print(user.name)  # Works
```

---

### Statement Timeout Errors

**Error Message:**
```
sqlalchemy.exc.OperationalError: (psycopg2.errors.QueryCanceledError)
canceling statement due to statement timeout

psycopg2.extensions.QueryCanceledError: canceling statement due to statement timeout
```

**Why It Happens:**
A database query is taking too long and exceeds the timeout threshold.

**How to Fix:**

1. Increase the statement timeout (temporary, for testing):
```sql
SET statement_timeout = '30s';
SELECT * FROM large_table;
```

2. Or set per-user in PostgreSQL:
```sql
ALTER USER myuser SET statement_timeout = '30s';
```

3. Find slow queries using EXPLAIN:
```sql
EXPLAIN ANALYZE SELECT * FROM large_table WHERE complex_condition;
```

4. Add missing indexes:
```sql
CREATE INDEX idx_user_email ON users(email);
CREATE INDEX idx_post_user_id ON posts(user_id);
```

5. Optimize the query:
```python
# Bad: N+1 query problem
users = db.query(User).all()
for user in users:
    print(user.posts)  # Triggers separate query for each user

# Good: Use eager loading
users = db.query(User).options(
    joinedload(User.posts)
).all()
```

6. Set timeouts in SQLAlchemy for all queries:
```python
from sqlalchemy import event
from sqlalchemy.engine import Engine

@event.listens_for(Engine, "before_execute")
def set_timeout(conn, clauseelement, multiparams, params, execution_options):
    conn.execute("SET LOCAL statement_timeout = '10s'")
```

---

### Migration Drift (Model != Database Schema)

**Error Message:**
```
sqlalchemy.exc.OperationalError: column "updated_at" does not exist
sqlalchemy.exc.ProgrammingError: column "is_active" is of type boolean but expression is of type integer
```

**Why It Happens:**
You modified a SQLAlchemy model but didn't create an Alembic migration, or migrations were skipped.

**How to Fix:**

1. Generate a migration from the model:
```bash
alembic revision --autogenerate -m "Add updated_at to users table"
```

2. Review the generated migration:
```bash
cat alembic/versions/abc123_add_updated_at_to_users.py
```

3. Apply the migration:
```bash
alembic upgrade head
```

4. If models and database are out of sync, reset (development only):
```bash
# Drop and recreate all tables
alembic downgrade base
alembic upgrade head
```

5. Always follow this workflow:
```bash
# 1. Modify model
# 2. Generate migration
alembic revision --autogenerate -m "descriptive message"
# 3. Review the migration file
# 4. Apply it
alembic upgrade head
# 5. Commit both the model change and migration file
```

!!! warning "Never Manual Schema Changes"
    Always use Alembic for schema changes. Never use raw SQL in production without a migration.

---

### Alembic Multi-Head Error

**Error Message:**
```
alembic.util.exc.CommandError: Multiple heads in alembic version table
FAILED: Multiple heads identified among the revisions supplied
```

**Why It Happens:**
Two separate migration branches were created (usually from merge conflicts or parallel development).

**How to Fix:**

1. Check current state:
```bash
alembic branches
alembic heads
```

2. Examine the conflicting migrations:
```bash
cat alembic/versions/<revision_id_1>.py
cat alembic/versions/<revision_id_2>.py
```

3. Merge the heads:
```bash
alembic merge -m "Merge migration branches"
```

4. Review the merge migration:
```bash
cat alembic/versions/<merge_revision>.py
```

5. Apply it:
```bash
alembic upgrade head
```

6. For future prevention, follow a strict merge conflict resolution:
```python
# In conflicting migration files, ensure they have proper depends_on
revision = 'abc123'
down_revision = 'xyz789'  # Explicitly set parent
branch_labels = None
depends_on = None
```

---

### SSL Connection Failures

**Error Message:**
```
ssl.SSLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed
psycopg2.OperationalError: could not translate host name "db.example.com" to address

ssl.SSLError: CERTIFICATE_VERIFY_FAILED: self signed certificate
```

**Why It Happens:**
SSL certificate verification is failing due to missing CA certificates, self-signed certs, or hostname mismatches.

**How to Fix:**

1. Download the RDS CA certificate (if using AWS RDS):
```bash
wget https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
```

2. Configure SQLAlchemy to use the certificate:
```python
from sqlalchemy import create_engine

engine = create_engine(
    DATABASE_URL,
    connect_args={
        "sslmode": "require",
        "sslcert": "/path/to/client-cert.pem",
        "sslkey": "/path/to/client-key.pem",
        "sslrootcert": "/path/to/global-bundle.pem",
    }
)
```

3. Or update the DATABASE_URL:
```bash
postgresql://user:pass@host/db?sslmode=require&sslrootcert=/path/to/ca.pem
```

4. For self-signed certificates (development only):
```bash
# Disable verification (NOT for production)
postgresql://user:pass@host/db?sslmode=allow
```

5. Verify the connection:
```bash
psql "sslmode=require sslrootcert=/path/to/ca.pem postgresql://user:pass@host/db"
```

---

## Authentication Failures

### JWT Decode Errors

**Error Message:**
```
jwt.exceptions.DecodeError: Signature verification failed
jwt.exceptions.InvalidSignatureError: Signature verification failed
jwt.exceptions.ExpiredSignatureError: Signature has expired
jwt.exceptions.InvalidIssuerError: Invalid issuer
jwt.exceptions.InvalidAudienceError: Invalid audience
```

**Why It Happens:**
- The token was signed with a different secret key
- The token has expired
- The issuer or audience claims don't match what the application expects

**How to Fix:**

1. Verify the SECRET_KEY matches across requests and server restarts:
```python
import os
SECRET_KEY = os.getenv("SECRET_KEY")

# Debug: Print key fingerprint (don't log the actual key)
print(f"SECRET_KEY fingerprint: {SECRET_KEY[:10]}...")
```

2. Check token expiration in the token itself:
```python
import jwt
import json
from base64 import urlsafe_b64decode

# Decode without verification to see claims
token = "your-jwt-token"
parts = token.split(".")
payload = json.loads(urlsafe_b64decode(parts[1] + "=="))
print(payload)
# Check 'exp' (expiration) timestamp
```

3. Ensure issuer and audience match:
```python
# When creating token
token = jwt.encode(
    {
        "sub": user_id,
        "iss": "myapp",  # Issuer
        "aud": "myapp-users",  # Audience
        "exp": datetime.utcnow() + timedelta(hours=1)
    },
    SECRET_KEY,
    algorithm="HS256"
)

# When decoding, verify they match
try:
    payload = jwt.decode(
        token,
        SECRET_KEY,
        algorithms=["HS256"],
        issuer="myapp",
        audience="myapp-users"
    )
except jwt.InvalidIssuerError:
    # Issuer doesn't match
    pass
```

4. For key rotation, accept both old and new keys temporarily:
```python
def decode_token_with_rotation(token, current_secret, previous_secret=None):
    try:
        return jwt.decode(token, current_secret, algorithms=["HS256"])
    except jwt.InvalidSignatureError:
        if previous_secret:
            try:
                return jwt.decode(token, previous_secret, algorithms=["HS256"])
            except jwt.InvalidSignatureError:
                raise
        raise
```

---

### Refresh Token Rejected After Rotation

**Error Message:**
```
403 Forbidden: Invalid refresh token
401 Unauthorized: Token not found in token store
ValueError: Refresh token does not match stored hash
```

**Why It Happens:**
Refresh tokens are being rotated/invalidated when a new one is issued, but old refresh tokens are being used.

**How to Fix:**

1. Implement refresh token rotation properly:
```python
from datetime import datetime, timedelta

async def refresh_access_token(refresh_token: str, db: Session):
    # Verify refresh token
    token_data = await verify_refresh_token(refresh_token)
    user = db.query(User).filter(User.id == token_data['sub']).first()
    
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    # Optional: Invalidate old refresh token
    # await revoke_refresh_token(refresh_token)
    
    # Issue new tokens
    new_access_token = create_access_token(user.id)
    new_refresh_token = create_refresh_token(user.id)
    
    # Store new refresh token
    await store_refresh_token(user.id, new_refresh_token)
    
    return {"access_token": new_access_token, "refresh_token": new_refresh_token}
```

2. Store refresh tokens in Redis with expiration:
```python
import redis

redis_client = redis.Redis.from_url(REDIS_URL)

async def store_refresh_token(user_id: int, token: str, ttl_days: int = 7):
    key = f"refresh_token:{user_id}"
    redis_client.setex(key, timedelta(days=ttl_days), token)

async def verify_refresh_token(token: str) -> dict:
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    user_id = payload.get("sub")
    
    stored_token = redis_client.get(f"refresh_token:{user_id}")
    if stored_token != token.encode():
        raise HTTPException(status_code=401, detail="Token rotated")
    
    return payload
```

3. Handle rotation gracefully for clients:
```python
# Client side: If 401 on refresh, clear tokens and force re-login
async def refresh_with_fallback(refresh_token: str):
    try:
        response = await post("/auth/refresh", json={"refresh_token": refresh_token})
        return response
    except HTTPException as e:
        if e.status_code == 401:
            # Token was rotated or invalidated
            clear_auth_tokens()
            redirect_to_login()
        raise
```

---

### Token Blacklist Not Working (Redis Down)

**Error Message:**
```
redis.exceptions.ConnectionError: Error 111 connecting
Cannot revoke token: Redis unavailable
redis.exceptions.TimeoutError: Timeout connecting to Redis
```

**Why It Happens:**
Redis is down or unreachable, preventing token blacklist lookups.

**How to Fix:**

1. Implement fallback behavior:
```python
async def is_token_blacklisted(token: str) -> bool:
    try:
        return redis_client.exists(f"blacklist:{token}")
    except redis.ConnectionError:
        # Fallback: accept token if Redis is down
        # Log the error for alerts
        logger.error("Redis unavailable for token blacklist")
        return False  # Or raise 503 Service Unavailable
```

2. Use persistent token blacklist (if Redis is unreliable):
```python
# Store blacklist in database instead
class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"
    id = Column(Integer, primary_key=True)
    token = Column(String, unique=True, index=True)
    blacklisted_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)  # When token is no longer valid anyway

async def blacklist_token(token: str, expires_at: datetime, db: Session):
    db.add(TokenBlacklist(token=token, expires_at=expires_at))
    db.commit()

async def is_token_blacklisted(token: str, db: Session) -> bool:
    return db.query(TokenBlacklist).filter(
        TokenBlacklist.token == token,
        TokenBlacklist.expires_at > datetime.utcnow()
    ).first() is not None
```

3. Clean up expired tokens:
```python
async def cleanup_blacklist(db: Session):
    db.query(TokenBlacklist).filter(
        TokenBlacklist.expires_at < datetime.utcnow()
    ).delete()
    db.commit()

# Schedule with APScheduler or ARQ
@app.on_event("startup")
async def startup():
    scheduler.add_job(cleanup_blacklist, "interval", hours=1)
```

---

### KID Mismatch During Key Rotation

**Error Message:**
```
jwt.exceptions.PyJWTError: Unable to find a signing key that matches
KeyError: 'kid' not found in JWKS
```

**Why It Happens:**
The `kid` (Key ID) in the token header doesn't match any key in the JWKS (JSON Web Key Set).

**How to Fix:**

1. Implement proper JWKS rotation:
```python
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import json

# Generate multiple keys with IDs
keys = {}
for i in range(2):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    keys[f"key-{i}"] = private_key

# Sign token with current key
def create_token_with_kid(data: dict, kid: str = "key-0"):
    token = jwt.encode(data, keys[kid], algorithm="RS256", headers={"kid": kid})
    return token

# Expose JWKS endpoint
@app.get("/.well-known/jwks.json")
async def get_jwks():
    jwks = {"keys": []}
    for kid, key in keys.items():
        public_key = key.public_key()
        jwk = {
            "kty": "RSA",
            "kid": kid,
            "use": "sig",
            "n": base64.urlsafe_b64encode(
                public_key.public_numbers().n.to_bytes(256, byteorder='big')
            ).decode(),
            "e": "AQAB",
        }
        jwks["keys"].append(jwk)
    return jwks
```

2. Use PyJWT with JWKS:
```python
from jwt.api_jws import PyJWS
from jwcrypto import jwk, jwt as jjwt

async def verify_token_with_jwks(token: str):
    # Fetch JWKS from your endpoint
    response = await http_client.get("https://yourapp.com/.well-known/jwks.json")
    jwks_data = response.json()
    
    # Decode without verification to get kid
    unverified = jwt.decode(token, options={"verify_signature": False})
    
    # Find the key with matching kid
    kid = jwt.get_unverified_header(token).get("kid")
    jwks = jwk.JWKSet.from_json(json.dumps(jwks_data))
    key = jwks.get_key(kid)
    
    # Verify with the correct key
    verified = jwt.decode(token, key, algorithms=["RS256"])
    return verified
```

3. During key rotation:
```python
# 1. Generate new key
new_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
keys["key-1"] = new_key

# 2. Start signing with new key but keep old key for verification
current_kid = "key-1"

# 3. After rotation period, remove old key
# keys.pop("key-0")
```

---

## Worker and Queue Problems

### Jobs Stuck in Queue (Worker Not Running)

**Error Message:**
```
Job with ID 'abc123' has been pending for 1 hour
Queue depth increasing: 1000+ jobs waiting
Task execution never completes
```

**Why It Happens:**
The ARQ worker process has stopped, crashed, or isn't consuming from the queue.

**How to Fix:**

1. Check if the worker is running:
```bash
ps aux | grep arq
ps aux | grep worker
```

2. Start the worker:
```bash
arq myapp.tasks.worker
# Or with environment variables
DATABASE_URL=... REDIS_URL=... arq myapp.tasks.worker
```

3. In Docker, ensure the worker service is running:
```yaml
services:
  api:
    build: .
    # ... api config

  worker:
    build: .
    command: arq myapp.tasks.worker
    environment:
      - DATABASE_URL=postgresql://...
      - REDIS_URL=redis://...
    depends_on:
      - db
      - redis
    restart: unless-stopped  # Auto-restart on crash
```

4. Check worker logs:
```bash
docker logs myapp-worker-1
# Or for local development
journalctl -u myapp-worker -f
```

5. Monitor queue depth:
```python
# In your API
from arq.connections import RedisSettings
from arq import create_pool

async def get_queue_depth():
    redis = await create_pool(RedisSettings.from_url(REDIS_URL))
    queue = await redis.llen("arq:queue")
    return {"pending_jobs": queue}

@app.get("/health/queue")
async def queue_health():
    depth = await get_queue_depth()
    if depth["pending_jobs"] > 1000:
        raise HTTPException(status_code=503, detail="Queue backed up")
    return depth
```

6. Drain stuck jobs (if needed):
```python
import redis
r = redis.Redis.from_url(REDIS_URL)

# See all jobs
jobs = r.lrange("arq:queue", 0, -1)
print(f"Pending jobs: {len(jobs)}")

# Clear queue (WARNING: loses jobs)
# r.delete("arq:queue")
```

---

### Jobs Failing Silently (Check Sentry/Logs)

**Error Message:**
```
Job completed but no result
Task never updated the database
Error not reported anywhere
```

**Why It Happens:**
Job failed but exception handling is missing, or Sentry integration isn't set up.

**How to Fix:**

1. Integrate Sentry for error reporting:
```bash
pip install sentry-sdk
```

2. Configure Sentry in your worker:
```python
import sentry_sdk
from sentry_sdk.integrations.arq import ArqIntegration

sentry_sdk.init(
    dsn="https://your-sentry-dsn@sentry.io/project",
    integrations=[ArqIntegration()],
    traces_sample_rate=1.0,
    environment="production"
)

async def my_task():
    try:
        # Your task logic
        pass
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise
```

3. Or use explicit error handlers:
```python
async def my_task(ctx):
    try:
        # Task logic
        pass
    except Exception as e:
        logger.error(f"Task failed: {e}", exc_info=True)
        # Optional: Update a failure record
        ctx['db'].add(TaskFailure(task_id=ctx['job_id'], error=str(e)))
        ctx['db'].commit()
        raise
```

4. Log all job results:
```python
from datetime import datetime

class JobLog(Base):
    __tablename__ = "job_logs"
    id = Column(Integer, primary_key=True)
    job_id = Column(String, index=True)
    status = Column(String)  # 'success', 'failed'
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error = Column(String, nullable=True)

async def my_task(ctx):
    job_id = ctx.get('job_id')
    db = ctx['db']
    started = datetime.utcnow()
    
    log = JobLog(job_id=job_id, status='started', started_at=started)
    db.add(log)
    db.commit()
    
    try:
        # Do work
        result = await do_something()
        log.status = 'success'
        log.completed_at = datetime.utcnow()
    except Exception as e:
        log.status = 'failed'
        log.error = str(e)
        log.completed_at = datetime.utcnow()
        logger.error(f"Job {job_id} failed: {e}")
        raise
    finally:
        db.commit()
```

5. Monitor job results:
```python
@app.get("/jobs/{job_id}/status")
async def job_status(job_id: str, db: Session):
    log = db.query(JobLog).filter(JobLog.job_id == job_id).first()
    if not log:
        raise HTTPException(status_code=404)
    return log
```

---

### Dead-Letter Queue Growing

**Error Message:**
```
Dead-letter queue has 5000+ jobs
Jobs failing repeatedly after max retries
```

**Why It Happens:**
Jobs are failing and exhausting retry attempts, moving to the dead-letter queue.

**How to Fix:**

1. Check the dead-letter queue:
```python
import redis

r = redis.Redis.from_url(REDIS_URL)
dlq = r.lrange("arq:dlq", 0, -1)
print(f"Dead-lettered jobs: {len(dlq)}")

# Inspect first failed job
import json
if dlq:
    first_job = json.loads(dlq[0])
    print(json.dumps(first_job, indent=2))
```

2. Fix the underlying issue and retry:
```python
# Move jobs back to the queue
import redis
import json

r = redis.Redis.from_url(REDIS_URL)
dlq_jobs = r.lrange("arq:dlq", 0, -1)

for job_data in dlq_jobs:
    job = json.loads(job_data)
    # Re-queue with a fresh attempt count
    job['attempts'] = 0
    r.rpush("arq:queue", json.dumps(job))

# Clear DLQ
r.delete("arq:dlq")
```

3. Implement retry logic with exponential backoff:
```python
from arq import concurrent
from datetime import timedelta

async def unreliable_task(ctx, item_id: int):
    try:
        result = await do_work(item_id)
        return result
    except Exception as e:
        attempt = ctx.get('attempt', 1)
        if attempt < 3:
            # Retry with exponential backoff
            delay = 2 ** attempt  # 2, 4, 8 seconds
            ctx['session'].enqueue_in(
                timedelta(seconds=delay),
                unreliable_task,
                item_id,
                attempt=attempt + 1
            )
        else:
            logger.error(f"Task failed after {attempt} attempts: {e}")
            raise
```

4. Set up alerts:
```python
@app.get("/health/dlq")
async def dlq_health():
    import redis
    r = redis.Redis.from_url(REDIS_URL)
    dlq_count = r.llen("arq:dlq")
    
    if dlq_count > 100:
        # Alert operations
        raise HTTPException(status_code=503, detail="DLQ backing up")
    
    return {"dlq_jobs": dlq_count}
```

---

### Worker Can't Connect to Redis

**Error Message:**
```
redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379
aioredis.ConnectionClosedError: Connection closed
```

**Why It Happens:**
Redis is down, unreachable, or the credentials are wrong.

**How to Fix:**

1. Verify Redis is running:
```bash
redis-cli ping
# PONG
```

2. Check REDIS_URL:
```bash
echo $REDIS_URL
# Should be: redis://localhost:6379/0 or redis://host:port/db
```

3. Test the connection:
```bash
redis-cli -u $REDIS_URL ping
```

4. With a password:
```bash
redis-cli -u redis://:password@host:6379/0 ping
```

5. In docker-compose, ensure service is reachable:
```yaml
services:
  redis:
    image: redis:latest
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  worker:
    depends_on:
      redis:
        condition: service_healthy
    environment:
      - REDIS_URL=redis://redis:6379/0
```

6. Add retry logic to worker startup:
```python
import asyncio
from arq.connections import RedisSettings, create_pool

async def initialize_redis(retries=10):
    for attempt in range(retries):
        try:
            redis = await create_pool(RedisSettings.from_url(REDIS_URL))
            await redis.ping()
            return redis
        except ConnectionError as e:
            if attempt < retries - 1:
                wait = 2 ** attempt
                logger.warning(f"Redis unavailable, retrying in {wait}s...")
                await asyncio.sleep(wait)
            else:
                logger.error("Failed to connect to Redis after retries")
                raise
```

---

### Worker Shutdown Taking Too Long (Stuck Jobs)

**Error Message:**
```
Worker shutdown timeout reached
Jobs still running after 30 seconds
SIGTERM not stopping worker
```

**Why It Happens:**
Long-running jobs don't check for shutdown signals or don't have proper cancellation.

**How to Fix:**

1. Make jobs cancellable with asyncio:
```python
import asyncio
from contextlib import asynccontextmanager

@asynccontextmanager
async def cancellable_task():
    task = asyncio.current_task()
    try:
        yield task
    except asyncio.CancelledError:
        logger.info("Task cancelled, cleaning up...")
        # Cleanup code here
        raise

async def long_running_task(ctx, data):
    async with cancellable_task() as task:
        for item in data:
            # Check for cancellation periodically
            try:
                result = await process_item(item)
            except asyncio.CancelledError:
                logger.warning("Task interrupted mid-execution")
                raise
```

2. Set worker graceful shutdown timeout:
```python
# In your worker config
from arq import Worker

class WorkerSettings:
    shutdown_timeout = 30  # Seconds to wait before force kill
    max_jobs = 1000  # Restart worker after N jobs
    allow_abort_jobs = True
```

3. Implement proper signal handling:
```python
import signal
import asyncio

async def graceful_shutdown(signum, frame):
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    # Give running jobs time to finish
    await asyncio.sleep(5)
    # Then exit
    exit(0)

signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)
```

4. In docker-compose, set proper stop grace period:
```yaml
services:
  worker:
    stop_grace_period: 30s  # Wait 30s before killing
    stop_signal: SIGTERM
```

---

## Webhook Failures

### Signature Verification Failing

**Error Message:**
```
400 Bad Request: Signature verification failed
401 Unauthorized: Invalid signature
Webhook signature does not match
```

**Why It Happens:**
- The webhook secret used for verification doesn't match the one used for signing
- Encoding mismatch (bytes vs. string)
- Request body was modified before verification

**How to Fix:**

1. Verify the webhook secret is correct:
```python
# When setting up webhook
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
assert WEBHOOK_SECRET, "WEBHOOK_SECRET not set"
```

2. Verify signature correctly (before reading body):
```python
import hmac
import hashlib
from fastapi import Request

@app.post("/webhooks/provider")
async def handle_webhook(request: Request):
    # Read raw body before any processing
    body = await request.body()
    signature = request.headers.get("x-signature")
    
    # Compute expected signature
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    # Compare using constant-time comparison
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Now parse JSON
    payload = json.loads(body)
    return await process_webhook(payload)
```

3. Common encoding issues:
```python
# Wrong: String instead of bytes
hmac.new(WEBHOOK_SECRET, body)  # Fails

# Right: Encode string to bytes
hmac.new(WEBHOOK_SECRET.encode(), body)

# Wrong: Body might be JSON string, not bytes
body_str = await request.json()  # Converts to dict
hmac.new(WEBHOOK_SECRET.encode(), str(body_str))  # Different from original

# Right: Always use raw request body
body_bytes = await request.body()
hmac.new(WEBHOOK_SECRET.encode(), body_bytes)
```

4. Check provider documentation for signature format:
```python
# GitHub uses: SHA256=hash
# Stripe uses: t=timestamp,v1=hash
# Generic uses: Authorization: Bearer hash

# Stripe example
import stripe

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    body = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(
            body, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    return await process_event(event)
```

---

### Replay Protection Rejecting Valid Events (Clock Skew)

**Error Message:**
```
400 Bad Request: Timestamp outside acceptable window
401 Unauthorized: Request too old
Webhook rejected: timestamp mismatch
```

**Why It Happens:**
Server clock is out of sync with the webhook provider, causing timestamp verification to fail.

**How to Fix:**

1. Increase the acceptable timestamp window:
```python
from datetime import datetime, timedelta

@app.post("/webhooks/provider")
async def handle_webhook(request: Request):
    payload = await request.json()
    timestamp = int(payload.get("timestamp", 0))
    
    # Allow 5-minute window instead of strict verification
    current_time = int(datetime.utcnow().timestamp())
    window = 300  # 5 minutes
    
    if abs(current_time - timestamp) > window:
        raise HTTPException(status_code=401, detail="Timestamp outside window")
    
    return await process_webhook(payload)
```

2. Sync server clock:
```bash
# Linux/macOS
sudo ntpdate -s time.nist.gov
# Or with timedatectl
timedatectl set-ntp true

# Docker
# Use NTP in container
ntpd -p pool.ntp.org
```

3. Check clock in monitoring:
```python
@app.get("/health/clock")
async def clock_status():
    from datetime import datetime
    # In production, compare with external NTP server
    return {
        "server_time": datetime.utcnow().isoformat(),
        "status": "ok"
    }
```

4. Log timestamp differences for debugging:
```python
@app.post("/webhooks/provider")
async def handle_webhook(request: Request):
    payload = await request.json()
    timestamp = int(payload.get("timestamp", 0))
    current_time = int(datetime.utcnow().timestamp())
    skew = abs(current_time - timestamp)
    
    logger.info(f"Webhook timestamp skew: {skew}s")
    
    if skew > 300:
        logger.error(f"Clock skew too large: {skew}s")
        raise HTTPException(status_code=401, detail="Clock skew")
    
    return await process_webhook(payload)
```

---

### Duplicate Events Getting Through

**Error Message:**
```
Event processed twice
Duplicate records created
Webhook idempotency not working
```

**Why It Happens:**
Webhook provider retried a request, but the application isn't detecting duplicates.

**How to Fix:**

1. Implement idempotency keys:
```python
from datetime import datetime, timedelta

class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id = Column(Integer, primary_key=True)
    provider = Column(String)
    event_id = Column(String, index=True, unique=True)
    processed_at = Column(DateTime)
    data = Column(JSON)

@app.post("/webhooks/provider")
async def handle_webhook(request: Request, db: Session):
    payload = await request.json()
    event_id = payload.get("id") or payload.get("event_id")
    
    # Check if already processed
    existing = db.query(WebhookEvent).filter(
        WebhookEvent.event_id == event_id,
        WebhookEvent.provider == "provider"
    ).first()
    
    if existing:
        logger.info(f"Duplicate event {event_id}, returning cached result")
        return {"status": "ok", "duplicate": True}
    
    # Process new event
    try:
        result = await process_webhook(payload)
        
        # Record successful processing
        event = WebhookEvent(
            provider="provider",
            event_id=event_id,
            processed_at=datetime.utcnow(),
            data=payload
        )
        db.add(event)
        db.commit()
        
        return {"status": "ok", "duplicate": False}
    except Exception as e:
        # Don't record failed events; allow retry
        logger.error(f"Failed to process webhook {event_id}: {e}")
        raise HTTPException(status_code=500, detail="Processing failed")
```

2. Use Redis for fast deduplication:
```python
import redis

r = redis.Redis.from_url(REDIS_URL)

@app.post("/webhooks/provider")
async def handle_webhook(request: Request, db: Session):
    payload = await request.json()
    event_id = payload.get("id")
    
    # Check Redis first (fast)
    if r.exists(f"webhook:{event_id}"):
        logger.info(f"Duplicate event {event_id}")
        return {"status": "ok", "duplicate": True}
    
    # Process event
    result = await process_webhook(payload)
    
    # Mark as processed (expire after 24 hours)
    r.setex(f"webhook:{event_id}", 86400, "1")
    
    return {"status": "ok", "duplicate": False}
```

---

### Provider Not Receiving Timely 200 (Processing Inline Instead of Enqueuing)

**Error Message:**
```
Webhook timeout: endpoint took more than 30 seconds
504 Gateway Timeout from webhook provider
Webhook provider disabled due to timeout
```

**Why It Happens:**
Processing is happening inline (synchronously), making the response slow.

**How to Fix:**

1. Enqueue work instead of processing inline:
```python
from arq import create_pool

@app.post("/webhooks/provider")
async def handle_webhook(request: Request, session: Session):
    payload = await request.json()
    
    # Verify signature (fast)
    if not verify_signature(request, payload):
        raise HTTPException(status_code=401)
    
    # Save to database for processing (fast)
    event = WebhookEvent(provider="provider", data=payload)
    session.add(event)
    session.commit()
    
    # Enqueue for async processing (returns immediately)
    redis = await create_pool(RedisSettings.from_url(REDIS_URL))
    await redis.enqueue("process_webhook", payload)
    
    # Return 200 immediately
    return {"status": "accepted"}
```

2. Move long operations to worker:
```python
# In tasks.py (worker code)
async def process_webhook(ctx, payload: dict):
    db = ctx['db']
    
    # Long-running operations here
    result = await long_process(payload)
    
    # Update database
    event = db.query(WebhookEvent).filter(
        WebhookEvent.id == payload['event_id']
    ).first()
    event.status = "processed"
    event.result = result
    db.commit()
```

3. Implement webhook request timeout:
```python
from fastapi import BackgroundTasks

@app.post("/webhooks/provider")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()
    
    # Add to background tasks (returns immediately)
    background_tasks.add_task(process_webhook_background, payload)
    
    return {"status": "accepted"}

async def process_webhook_background(payload: dict):
    # This runs after response is sent
    try:
        await heavy_processing(payload)
    except Exception as e:
        logger.error(f"Background processing failed: {e}")
```

---

## Docker and Deployment Issues

### Container Health Check Failing

**Error Message:**
```
Container unhealthy
health: starting -> unhealthy
Health check failed
docker run returned non-zero exit code
```

**Why It Happens:**
The health check command is failing, usually because the app isn't ready yet.

**How to Fix:**

1. Implement a proper health check endpoint:
```python
@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/health/ready")
async def readiness():
    """Check if app is ready to accept traffic"""
    try:
        # Test database
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail="Database not ready")
    
    # Test Redis
    try:
        r = redis.Redis.from_url(REDIS_URL)
        r.ping()
    except Exception as e:
        raise HTTPException(status_code=503, detail="Redis not ready")
    
    return {"status": "ready"}
```

2. Configure Docker health check:
```dockerfile
FROM python:3.11
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8000/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0"]
```

3. Or use docker-compose:
```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 30s
```

4. Increase `start_period` if app is slow to start:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 60s  # 60 seconds to fully start
```

---

### NGINX 502 Bad Gateway (API Not Ready Yet)

**Error Message:**
```
502 Bad Gateway
upstream server temporarily disabled
connect() failed (111: Connection refused)
```

**Why It Happens:**
NGINX is forwarding requests before the application is ready to accept connections.

**How to Fix:**

1. Ensure proper startup order in docker-compose:
```yaml
services:
  db:
    image: postgres:15
    environment:
      - POSTGRES_PASSWORD=postgres
    healthcheck:
      test: ["CMD", "pg_isready"]
      interval: 5s
      timeout: 5s
      retries: 5

  api:
    build: .
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      start_period: 30s

  nginx:
    image: nginx:latest
    ports:
      - "80:80"
    depends_on:
      api:
        condition: service_healthy
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
```

2. Add health check to NGINX config:
```nginx
upstream api {
    server api:8000;
}

server {
    listen 80;
    
    location / {
        proxy_pass http://api;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        
        # Timeouts to wait for upstream
        proxy_connect_timeout 10s;
        proxy_send_timeout 10s;
        proxy_read_timeout 10s;
    }
    
    # Health check for load balancer
    location /health {
        access_log off;
        proxy_pass http://api;
    }
}
```

3. Add startup delay:
```yaml
services:
  api:
    build: .
    command: >
      sh -c "sleep 10 && uvicorn main:app --host 0.0.0.0"
    # Not ideal, but works as a last resort
```

---

### Migration Container Failing (DB Not Ready)

**Error Message:**
```
Migration failed: could not connect to database
Error: Connection refused
pg_isready: could not translate host name
```

**Why It Happens:**
The migration container starts before the database is ready.

**How to Fix:**

1. Use `depends_on` with health checks:
```yaml
services:
  db:
    image: postgres:15
    environment:
      - POSTGRES_PASSWORD=postgres
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres"]
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 10s

  migrate:
    build: .
    command: alembic upgrade head
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/myapp
    depends_on:
      db:
        condition: service_healthy
    restart: on-failure
```

2. Implement retry logic in migration script:
```dockerfile
FROM python:3.11
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# Create entrypoint script
RUN echo '#!/bin/sh\n\
set -e\n\
echo "Waiting for database..."\n\
for i in 1 2 3 4 5; do\n\
  if pg_isready -h $DB_HOST -p $DB_PORT; then\n\
    echo "Database is ready!"\n\
    break\n\
  fi\n\
  echo "Database not ready, waiting... ($i/5)"\n\
  sleep 5\n\
done\n\
echo "Running migrations..."\n\
alembic upgrade head\n\
' > /entrypoint.sh && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
```

3. Or use a dedicated init container:
```yaml
services:
  migrate-init:
    build: .
    command: >
      sh -c "
      until pg_isready -h db -p 5432; do
        echo 'Waiting for postgres...'
        sleep 2
      done;
      alembic upgrade head
      "
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/myapp
    depends_on:
      - db

  api:
    build: .
    depends_on:
      migrate-init:
        condition: service_completed_successfully
```

---

### Permission Denied Errors (Non-Root User)

**Error Message:**
```
Permission denied: /app/logs
cannot create directory /var/log
Operation not permitted
```

**Why It Happens:**
The container runs as a non-root user but tries to write to protected directories.

**How to Fix:**

1. Create a non-root user in Dockerfile:
```dockerfile
FROM python:3.11

# Create non-root user
RUN useradd -m -u 1000 appuser

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY --chown=appuser:appuser . .

# Use non-root user
USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0"]
```

2. Ensure writable directories exist and have correct permissions:
```dockerfile
FROM python:3.11

RUN useradd -m -u 1000 appuser

WORKDIR /app
RUN mkdir -p /app/logs && chown -R appuser:appuser /app

COPY requirements.txt .
RUN pip install -r requirements.txt
COPY --chown=appuser:appuser . .

USER appuser
CMD ["uvicorn", "main:app"]
```

3. Or use named volumes:
```yaml
services:
  api:
    build: .
    user: "1000:1000"
    volumes:
      - logs:/app/logs
      - tmp:/app/tmp

volumes:
  logs:
  tmp:
```

4. Check file permissions in running container:
```bash
docker exec myapp ls -la /app
docker exec myapp id  # Check current user
```

---

## Performance Problems

### Slow API Responses (Check DB Queries, Connection Pool, Missing Indexes)

**Symptom:**
```
Response time: 5-10 seconds
Requests taking longer than expected
Timeout errors starting to occur
```

**Why It Happens:**
- Database queries are slow (missing indexes, full table scans)
- Connection pool exhausted (waiting for connection)
- N+1 query problems

**How to Fix:**

1. Enable query logging to find slow queries:
```python
import logging
logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

# Or log only slow queries
from sqlalchemy import event
from sqlalchemy.engine import Engine
import time

@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault('query_start_time', []).append(time.time())

@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    total_time = time.time() - conn.info['query_start_time'].pop(-1)
    if total_time > 0.5:  # Log queries slower than 500ms
        logger.warning(f"Slow query ({total_time:.2f}s): {statement}")
```

2. Find slow queries in database:
```sql
-- PostgreSQL slow query log
CREATE EXTENSION pg_stat_statements;

SELECT query, calls, mean_time, total_time
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 10;
```

3. Add missing indexes:
```sql
-- Find unused indexes
SELECT schemaname, tablename, indexname
FROM pg_stat_user_indexes
WHERE idx_scan = 0;

-- Find index suggestions
EXPLAIN ANALYZE SELECT * FROM users WHERE email = 'user@example.com';

-- Add index if scan is slow
CREATE INDEX idx_users_email ON users(email);
```

4. Fix N+1 query problems:
```python
# Bad
users = db.query(User).all()
for user in users:
    posts = db.query(Post).filter(Post.user_id == user.id).all()  # N queries!

# Good: Use joinedload
from sqlalchemy.orm import joinedload
users = db.query(User).options(joinedload(User.posts)).all()

# Or use selectinload for collections
from sqlalchemy.orm import selectinload
users = db.query(User).options(selectinload(User.posts)).all()
```

5. Monitor connection pool usage:
```python
from sqlalchemy import event
from sqlalchemy.engine import Engine

@event.listens_for(Engine, "connect")
def receive_connect(dbapi_conn, connection_record):
    print(f"Connections in pool: {engine.pool.checkedout()}")

# Or check programmatically
@app.get("/health/db")
async def db_health():
    return {
        "pooled_connections": engine.pool.checkedout(),
        "pool_size": engine.pool.size(),
        "overflow": engine.pool.overflow()
    }
```

6. Optimize pagination for large result sets:
```python
# Bad: OFFSET is slow on large tables
users = db.query(User).offset(100000).limit(10).all()

# Good: Use keyset pagination
last_id = request.query_params.get("last_id", 0)
users = db.query(User).filter(User.id > last_id).limit(10).all()
```

---

### High Memory Usage (Check Connection Pool Size, Response Buffering)

**Symptom:**
```
Container memory usage: 500MB, 1GB, growing
OOM killed
Swap usage increasing
```

**Why It Happens:**
- Connection pool is too large
- Responses are being buffered in memory
- Memory leaks in code

**How to Fix:**

1. Reduce connection pool size:
```python
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,        # Reduce from 20
    max_overflow=10,    # Reduce from 40
    pool_pre_ping=True,
    pool_recycle=3600,
)
```

2. Stream large responses:
```python
from fastapi.responses import StreamingResponse
import json

@app.get("/api/large-data")
async def get_large_data():
    async def generate():
        for chunk in fetch_data_in_chunks():
            yield json.dumps(chunk) + "\n"
    
    return StreamingResponse(generate(), media_type="application/x-ndjson")
```

3. Limit response size:
```python
from fastapi import Query

@app.get("/users")
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),  # Max 100 items
):
    return db.query(User).offset(skip).limit(limit).all()
```

4. Profile memory usage:
```python
from memory_profiler import profile

@profile
def fetch_all_users():
    return db.query(User).all()  # Loads everything into memory

# Better
def fetch_users_batched(batch_size=1000):
    offset = 0
    while True:
        batch = db.query(User).offset(offset).limit(batch_size).all()
        if not batch:
            break
        yield from batch
        offset += batch_size
```

5. Monitor memory in your API:
```python
import psutil
import os

@app.get("/health/memory")
async def memory_status():
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    
    return {
        "rss_mb": mem_info.rss / 1024 / 1024,  # Physical memory
        "vms_mb": mem_info.vms / 1024 / 1024,  # Virtual memory
        "percent": process.memory_percent()
    }
```

---

### Redis Latency (Check maxmemory Policy, Network)

**Symptom:**
```
Redis commands taking 100ms+
Operation timed out
Cache hits but slow response
```

**Why It Happens:**
- Redis memory is full (maxmemory) and eviction is slow
- Network latency
- CPU-bound eviction policy

**How to Fix:**

1. Check Redis memory usage:
```bash
redis-cli INFO memory
# Look for: used_memory, used_memory_peak, maxmemory

# In Python
import redis
r = redis.Redis.from_url(REDIS_URL)
info = r.info('memory')
print(f"Used: {info['used_memory_human']}")
print(f"Max: {info['maxmemory_human']}")
```

2. Increase maxmemory:
```bash
# In redis.conf
maxmemory 1gb
maxmemory-policy allkeys-lru  # Evict least recently used keys

# Or at runtime
redis-cli CONFIG SET maxmemory 2gb
redis-cli CONFIG SET maxmemory-policy allkeys-lru
```

3. Check eviction policy:
```bash
redis-cli CONFIG GET maxmemory-policy
# Better policies: allkeys-lru, allkeys-lfu
# Worse: volatile-ttl (only evicts keys with TTL)
```

4. Monitor Redis latency:
```bash
# Check latency samples
redis-cli LATENCY LATEST

# Or in Python
async def test_redis_latency():
    import time
    r = redis.Redis.from_url(REDIS_URL)
    
    start = time.time()
    r.ping()
    latency = (time.time() - start) * 1000
    
    if latency > 10:  # 10ms
        logger.warning(f"Redis latency: {latency:.2f}ms")
```

5. Check network latency between app and Redis:
```bash
# From app server to Redis server
ping redis-host
# Should be <1ms on local network

# In docker-compose
docker exec myapp ping redis
```

6. Enable Redis persistence optimization:
```bash
# Disable RDB snapshots during peak hours
redis-cli CONFIG SET save ""

# Or configure less frequent saves
redis-cli CONFIG SET save "900 1 300 10 60 10000"
# Save if 1 key changed in 900s, 10 in 300s, 10000 in 60s
```

---

## Summary Table

| Issue | Quick Diagnostic | Quick Fix |
|-------|-----------------|-----------|
| App won't start | Check logs for `DATABASE_URL`, `SECRET_KEY`, Redis connection | Set env vars, verify service ports |
| Slow queries | Enable query logging, check EXPLAIN ANALYZE | Add indexes, use eager loading, fix N+1 |
| Connection pool exhausted | Check `engine.pool.checkedout()` | Increase pool_size/max_overflow, find connection leaks |
| Jobs stuck in queue | `ps aux \| grep arq` | Start worker, check logs |
| JWT decode error | Verify SECRET_KEY consistency | Ensure same key across requests |
| 502 Bad Gateway | Check app is healthy: `curl localhost:8000/health` | Ensure startup order, add health check |
| High memory | `ps aux`, check RES column | Reduce pool size, stream large responses |
| Redis latency | `redis-cli LATENCY LATEST` | Check maxmemory, network latency |

