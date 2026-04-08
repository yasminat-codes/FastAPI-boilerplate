# Secrets and Environment Management

This guide covers managing secrets, configuring environment variables, and rotating credentials safely across deployments.

## Environment Files

The FastAPI boilerplate uses `.env` files for configuration. The template provides `.env.example` files as templates in each deployment profile.

### .env.example Structure

Each deployment profile includes a `.env.example`:

=== "Local"
    **Path:** `scripts/local_with_uvicorn/.env.example`
    
    Contains development-friendly placeholders:
    - `DEBUG=true`
    - `ENVIRONMENT=local`
    - Database password: simple test value
    - Secret key: short placeholder
    - CORS: allows localhost:3000

=== "Staging"
    **Path:** `scripts/gunicorn_managing_uvicorn_workers/.env.example`
    
    Production-like values, still development-safe:
    - `DEBUG=false`
    - `ENVIRONMENT=staging`
    - Database password: test value (must be changed)
    - Secret key: placeholder (must be rotated)
    - CORS: single origin placeholder

=== "Production"
    **Path:** `scripts/production_with_nginx/.env.example`
    
    Requires replacement of all secrets:
    - `DEBUG=false`
    - `ENVIRONMENT=production`
    - Database password: MUST be changed
    - Secret key: MUST be generated
    - CORS: MUST be set to actual domain

### Creating .env for First Time

```bash
# Copy the appropriate template
python setup.py production  # Copies scripts/production_with_nginx/.env.example → src/.env

# Edit with real secrets
vim src/.env
```

## Required Production Secrets

These settings **MUST** be changed from the `.env.example` defaults before production deployment:

| Variable | Purpose | Example | How to Generate |
|----------|---------|---------|-------------------|
| `SECRET_KEY` | JWT signing key | (32+ chars) | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | Database password | (16+ chars, symbols) | `openssl rand -base64 16` |
| `REDIS_PASSWORD` | Redis authentication | (16+ chars) | `openssl rand -base64 16` |
| `ALGORITHM` | JWT algorithm | `HS256` | Use default |
| `ENVIRONMENT` | Environment name | `production` | Set explicitly |
| `ALLOWED_HOSTS` | CORS/Host validation | `["api.example.com"]` | Your domain |
| `CORS_ORIGINS` | Frontend CORS | `["https://example.com"]` | Your frontend URLs |

### Production Safety Check

The FastAPI boilerplate includes a startup check that prevents running in production with default secrets:

```python
# src/app/core/config.py
if settings.ENVIRONMENT == "production":
    if settings.SECRET_KEY in ["your-super-secret-key", "change-me", ""]:
        raise ValueError("❌ Cannot start in production with default SECRET_KEY")
    if settings.POSTGRES_PASSWORD in ["postgres", "password", ""]:
        raise ValueError("❌ Cannot start in production with default POSTGRES_PASSWORD")
```

**This is intentional.** The app will refuse to start if you forget to update secrets.

## Secret Manager Integration

For large deployments, use external secret managers instead of .env files.

### Generic Integration Pattern

```python
# src/app/core/config.py
import os
from typing import Optional

class Settings:
    def __init__(self):
        # Try external secret manager first
        self.SECRET_KEY = self._get_secret("SECRET_KEY")
        
    def _get_secret(self, name: str) -> str:
        # 1. Check environment (local .env, container env vars)
        if env_value := os.getenv(name):
            return env_value
        
        # 2. Check secret manager
        if manager := os.getenv("SECRET_MANAGER"):
            if manager == "aws-secrets":
                return self._get_aws_secret(name)
            elif manager == "vault":
                return self._get_vault_secret(name)
        
        raise ValueError(f"Secret {name} not found")
    
    def _get_aws_secret(self, name: str) -> str:
        """Fetch from AWS Secrets Manager"""
        import boto3
        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=name)
        return response["SecretString"]
    
    def _get_vault_secret(self, name: str) -> str:
        """Fetch from HashiCorp Vault"""
        import hvac
        client = hvac.Client()
        response = client.secrets.kv.read_secret_version(path=name)
        return response["data"]["data"]["value"]
```

### Provider-Specific Patterns

=== "AWS Secrets Manager"
    ```python
    import boto3
    import json
    
    def get_secrets():
        client = boto3.client("secretsmanager", region_name="us-east-1")
        secret = client.get_secret_value(SecretId="fastapi/production")
        return json.loads(secret["SecretString"])
    
    secrets = get_secrets()
    SECRET_KEY = secrets["SECRET_KEY"]
    POSTGRES_PASSWORD = secrets["POSTGRES_PASSWORD"]
    ```

=== "HashiCorp Vault"
    ```python
    import hvac
    
    client = hvac.Client(url="https://vault.example.com")
    client.auth.kubernetes.login(
        role="fastapi-app",
        jwt=open("/var/run/secrets/kubernetes.io/serviceaccount/token").read()
    )
    
    secrets = client.secrets.kv.read_secret_version(path="fastapi/production")
    data = secrets["data"]["data"]
    SECRET_KEY = data["SECRET_KEY"]
    ```

=== "Docker Secrets"
    ```python
    # For Docker Swarm / Docker containers
    def read_docker_secret(secret_name: str) -> str:
        try:
            with open(f"/run/secrets/{secret_name}", "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return os.getenv(secret_name)
    
    SECRET_KEY = read_docker_secret("SECRET_KEY")
    POSTGRES_PASSWORD = read_docker_secret("POSTGRES_PASSWORD")
    ```

=== "Kubernetes Secrets"
    ```yaml
    # kubernetes/secrets.yaml
    apiVersion: v1
    kind: Secret
    metadata:
      name: app-secrets
    type: Opaque
    stringData:
      SECRET_KEY: "actual-secret-key-here"
      POSTGRES_PASSWORD: "actual-password-here"
    
    ---
    # Deployment uses the secret
    apiVersion: apps/v1
    kind: Deployment
    spec:
      template:
        spec:
          containers:
          - name: app
            env:
            - name: SECRET_KEY
              valueFrom:
                secretKeyRef:
                  name: app-secrets
                  key: SECRET_KEY
    ```

## Secret Rotation

Rotating secrets periodically reduces impact of potential compromise.

### JWT Secret Key Rotation

JWT keys can be rotated using key ID (`kid`) without invalidating existing tokens.

**Strategy:** Support multiple keys, sign new tokens with latest, verify with any known key.

```python
# src/app/core/security.py
from datetime import datetime
from typing import Optional

class JWTKeyManager:
    def __init__(self, keys: dict[str, str]):
        """
        keys = {
            "2024-01-current": "secret-key-1",
            "2024-02-previous": "secret-key-2",
        }
        """
        self.keys = keys
        self.current_kid = "2024-01-current"
    
    def encode_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Encode with current key and kid"""
        current_key = self.keys[self.current_kid]
        
        payload = {
            "data": data,
            "kid": self.current_kid,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + (expires_delta or timedelta(hours=1))
        }
        
        return jwt.encode(
            payload,
            current_key,
            algorithm="HS256",
            headers={"kid": self.current_kid}
        )
    
    def decode_token(self, token: str) -> dict:
        """Decode using the appropriate key"""
        # Get kid from token header
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid", self.current_kid)
        
        if kid not in self.keys:
            raise ValueError(f"Unknown key ID: {kid}")
        
        return jwt.decode(
            token,
            self.keys[kid],
            algorithms=["HS256"]
        )
    
    def rotate_key(self, new_key_id: str, new_key: str):
        """Add new key and set as current"""
        self.keys[new_key_id] = new_key
        self.current_kid = new_key_id
        # Old keys remain for verification (tokens still valid)

# Usage in FastAPI
jwt_manager = JWTKeyManager({
    "2024-01": os.getenv("JWT_KEY_CURRENT"),
    "2024-02": os.getenv("JWT_KEY_PREVIOUS"),  # Optional, for rollback
})
```

**Rotation procedure:**

```bash
# 1. Generate new key
NEW_KEY=$(openssl rand -hex 32)

# 2. Add to environment
export JWT_KEY_CURRENT_NEW=$NEW_KEY

# 3. Update app configuration to use new key

# 4. Redeploy

# 5. Monitor: old tokens still work during rollback window
# 6. After grace period, remove old key from configuration
```

### Database Credential Rotation

PostgreSQL supports role password rotation without downtime:

```sql
-- 1. Create new database role
CREATE ROLE app_prod_new WITH PASSWORD 'new-secure-password' LOGIN;

-- 2. Grant same permissions as old role
GRANT ALL PRIVILEGES ON DATABASE prod_db TO app_prod_new;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO app_prod_new;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_prod_new;

-- 3. Update application to use new role
-- (Update DATABASE_URL or POSTGRES_PASSWORD in environment)

-- 4. Verify no connections with old role
SELECT * FROM pg_stat_activity WHERE usename = 'app_prod';

-- 5. After grace period, drop old role
DROP ROLE app_prod;
```

### Redis Password Rotation

Redis doesn't support per-connection password rotation, but you can use a separate Redis instance temporarily:

```bash
# 1. Provision new Redis instance with new password
# 2. Update REDIS_PASSWORD in environment
# 3. Restart application (brief connection attempt to new Redis)
# 4. Migrate data from old to new:
redis-cli --pipe < migration.txt

# 5. Verify all data moved
# 6. Decommission old Redis
```

### Provider API Key Rotation

For third-party API integrations (payment providers, email services):

```python
# src/app/core/config.py
import os
from typing import Optional

class ProviderConfig:
    def __init__(self):
        # Support primary and fallback keys
        self.stripe_key = os.getenv("STRIPE_API_KEY")
        self.stripe_key_fallback = os.getenv("STRIPE_API_KEY_FALLBACK")
    
    def get_stripe_client(self):
        import stripe
        try:
            stripe.api_key = self.stripe_key
            # Test the key
            stripe.Account.retrieve()
            return stripe
        except Exception as e:
            # Fallback to previous key if current is invalid
            if self.stripe_key_fallback:
                stripe.api_key = self.stripe_key_fallback
                return stripe
            raise

# Rotation procedure:
# 1. Generate new API key in provider dashboard
# 2. Set STRIPE_API_KEY_FALLBACK to current key
# 3. Set STRIPE_API_KEY to new key
# 4. Deploy and monitor for errors
# 5. After grace period, remove fallback key
```

### Webhook Signing Secret Rotation

Webhook integrations (Stripe, GitHub, etc.) use signing secrets:

```python
# src/app/api/webhooks/stripe.py
import hmac
import hashlib
from typing import Optional

class WebhookVerifier:
    def __init__(self, secrets: dict[str, str]):
        """
        secrets = {
            "2024-01": "current-secret",
            "2024-02": "previous-secret",  # For rollback window
        }
        """
        self.secrets = secrets
    
    def verify_signature(self, payload: bytes, signature: str) -> Optional[str]:
        """Verify webhook signature against any known key"""
        for key_id, secret in self.secrets.items():
            expected = hmac.new(
                secret.encode(),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            if hmac.compare_digest(signature, expected):
                return key_id  # Return which key verified it
        
        return None  # No keys matched

# FastAPI endpoint
@router.post("/webhooks/stripe")
async def handle_stripe_webhook(
    request: Request,
    verifier: WebhookVerifier = Depends()
):
    body = await request.body()
    signature = request.headers.get("Stripe-Signature")
    
    key_id = verifier.verify_signature(body, signature)
    if not key_id:
        return {"error": "Invalid signature"}, 403
    
    if key_id == "2024-02":
        # Old key still valid, but log for operator awareness
        logger.warning("Webhook verified with old key - rotation may be needed")
    
    # Process webhook...
    return {"status": "ok"}

# Rotation procedure:
# 1. Provider generates new secret
# 2. Update WEBHOOK_SECRET_CURRENT with new secret
# 3. Keep WEBHOOK_SECRET_PREVIOUS for grace period
# 4. After grace period, remove previous secret
```

## Environment Variable Documentation

### Complete Environment Variables Reference

See [Configuration: Environment Variables](../configuration/environment-variables.md) for comprehensive documentation of every setting.

Key production settings:

```env
# Application
ENVIRONMENT=production
DEBUG=false
APP_NAME="Your Application"

# Database
DATABASE_URL=postgresql://user:pass@host:5432/dbname
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=10
DATABASE_POOL_RECYCLE=1800
DATABASE_SSL_MODE=require

# Redis
REDIS_CACHE_HOST=redis-host
REDIS_CACHE_PORT=6379
REDIS_CACHE_PASSWORD=secure-password
REDIS_QUEUE_HOST=redis-host
REDIS_QUEUE_PASSWORD=secure-password

# Security
SECRET_KEY=<32+ character random string>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
ALLOWED_HOSTS=["api.example.com"]
CORS_ORIGINS=["https://example.com"]

# Third-party integrations
STRIPE_API_KEY=sk_live_...
SENDGRID_API_KEY=SG.xxxxx

# Logging
LOG_LEVEL=INFO
```

## Environment-Specific Examples

### Local Development

```env
ENVIRONMENT=local
DEBUG=true
DATABASE_URL=postgresql://user:password@localhost:5432/dev_db
REDIS_CACHE_HOST=localhost
REDIS_QUEUE_HOST=localhost
SECRET_KEY=dev-key-not-secure
CORS_ORIGINS=["http://localhost:3000", "http://127.0.0.1:3000"]
LOG_LEVEL=DEBUG
```

### Staging

```env
ENVIRONMENT=staging
DEBUG=false
DATABASE_URL=postgresql://staging_user:staging_pass@db-staging.internal:5432/staging_db
REDIS_CACHE_HOST=redis-staging.internal
REDIS_QUEUE_HOST=redis-staging.internal
REDIS_CACHE_PASSWORD=staging-password
SECRET_KEY=staging-secret-key-minimum-32-chars-required-here
CORS_ORIGINS=["https://staging.example.com"]
LOG_LEVEL=INFO
```

### Production

```env
ENVIRONMENT=production
DEBUG=false
DATABASE_URL=postgresql://prod_user:prod_secure_password@db-prod.internal:5432/production_db
DATABASE_SSL_MODE=require
REDIS_CACHE_HOST=redis-prod.internal
REDIS_QUEUE_HOST=redis-prod.internal
REDIS_CACHE_PASSWORD=very-secure-production-password
SECRET_KEY=generate-with-openssl-rand-hex-32
CORS_ORIGINS=["https://api.example.com"]
ALLOWED_HOSTS=["api.example.com"]
LOG_LEVEL=WARN
SENTRY_DSN=https://key@sentry.example.com/project-id
```

## Best Practices Checklist

- [ ] Never commit `.env` files (add to `.gitignore`)
- [ ] All secrets in `.env.example` are placeholders
- [ ] Production secrets generated with `openssl rand -hex 32`
- [ ] Database passwords minimum 16 characters with symbols
- [ ] Secrets rotated every 90 days for compliance
- [ ] JWT keys support multiple key IDs for rotation
- [ ] Database credentials rotated without downtime
- [ ] Webhook signing secrets validated against all known keys
- [ ] Fallback/previous keys supported during rotation grace period
- [ ] Secret manager configured for large deployments
- [ ] All secrets in container registries scanned for leaks
- [ ] Audit logs track secret access (where available)
