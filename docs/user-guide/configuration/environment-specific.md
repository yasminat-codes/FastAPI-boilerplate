# Environment-Specific Configuration

This guide maps the template's configuration model to the three supported deployment profiles: `local`, `staging`, and `production`.

Use it together with:

- `ENVIRONMENT` in `src/.env`
- the profile-aware settings loader in `src/app/core/config.py`
- the example env files under `scripts/`

## Supported Profiles

The template loads one of three settings profiles based on `ENVIRONMENT`:

| `ENVIRONMENT` | Settings class | Primary use |
| --- | --- | --- |
| `local` | `LocalSettings` | Developer machines, local Docker Compose, fast iteration |
| `staging` | `StagingSettings` | Pre-production validation, QA, smoke tests |
| `production` | `ProductionSettings` | Live traffic, hardened runtime defaults |

Set the profile explicitly:

```env
ENVIRONMENT="local"  # or "staging" or "production"
```

## Recommended Starting Points

Start from the example that is closest to the environment you are standing up, then replace every placeholder secret, password, hostname, and domain before sharing it with a team or deploying it anywhere.

| Profile | Setup shortcut | Example file | Notes |
| --- | --- | --- | --- |
| `local` | `./setup.py local` | `scripts/local_with_uvicorn/.env.example` | Fast local development with public docs and HTTP-friendly cookie defaults |
| `staging` | `./setup.py staging` | `scripts/gunicorn_managing_uvicorn_workers/.env.example` | Production-like process model with superuser-only docs |
| `production` | `./setup.py production` | `scripts/production_with_nginx/.env.example` | Reverse-proxy deployment shape with stricter host, cookie, and TLS expectations |

## Profile Behavior Matrix

This table describes behavior that comes directly from the settings classes and application setup.

| Concern | `local` | `staging` | `production` |
| --- | --- | --- | --- |
| API docs exposure | Public at `/docs`, `/redoc`, `/openapi.json` | Same endpoints, but guarded by `get_current_superuser` | Disabled |
| `SENTRY_ENVIRONMENT` default | `local` | `staging` | `production` |
| `CORS_ORIGINS` if omitted | Defaults to the built-in localhost allowlist | Empty allowlist until you configure explicit origins | Empty allowlist until you configure explicit origins |
| `REFRESH_TOKEN_COOKIE_SECURE` default | `false` | `true` | `true` |
| `SESSION_SECURE_COOKIES` default | `false` | `true` | `true` |
| Placeholder `SECRET_KEY`, DB password, or admin password | Allowed for local bootstrap only | Rejected at startup | Rejected at startup |
| Wildcard `CORS_ORIGINS`, `TRUSTED_HOSTS`, or trusted proxies | Allowed only when individual validators permit it | Rejected by secure-environment validation | Rejected by secure-environment validation |

## Recommended Settings Matrix

Use these values as a reusable template baseline. The exact hostnames, networks, secrets, and observability endpoints should come from the adopting project.

| Setting group | `local` | `staging` | `production` |
| --- | --- | --- | --- |
| App identity | Friendly local names are fine | Match the shared staging deployment name | Use the public service identity and release version |
| Database connection | `localhost` or Docker service names are fine; `DATABASE_URL` or composed `POSTGRES_*` both work | Point to a staging PostgreSQL instance and use non-placeholder credentials | Point to the production PostgreSQL instance and use managed secrets or injected credentials |
| Redis topology | A single Redis instance can back cache, queue, and rate limiting | One shared Redis can still be acceptable for smaller staging environments | Prefer separate Redis roles or instances for cache, queues, and rate limiting |
| `CORS_ORIGINS` | Localhost frontend origins such as `http://localhost:3000` and `http://localhost:5173` | Explicit staging frontend origins only | Explicit production frontend origins only |
| `TRUSTED_HOSTS` | Optional for local dev; set localhost values when testing host filtering | Explicit staging domains only | Explicit production domains only |
| `PROXY_HEADERS_*` | Usually disabled unless you are testing behind a local proxy | Enable only when a proxy or ingress is actually present, and trust explicit proxy IPs or CIDRs | Same as staging, with final ingress IPs or CIDRs |
| `SECURITY_HEADERS_*` | Keep the baseline headers enabled; HSTS usually stays off on plain HTTP | Test the final CSP and enable HSTS only when HTTPS termination is in place | Keep baseline headers enabled, define the final CSP, and enable HSTS when HTTPS is enforced |
| Refresh and admin cookies | Non-secure cookies are acceptable for local HTTP | Secure cookies should stay enabled | Secure cookies must stay enabled |
| `FEATURE_*` toggles | Keep defaults unless a developer is intentionally exercising an optional-module-off path | Match the feature mix you plan to ship so staging reflects production behavior | Keep only the modules you intend to operate |
| `WEBHOOK_*` settings | Shorter payload retention and looser provider testing can be acceptable | Run the same verification and replay protections you expect in production | Keep signature verification and replay protection enabled |
| Observability | Sentry, metrics, and tracing can stay off until needed | Enable the telemetry you need for QA, smoke tests, and release validation | Enable the telemetry needed for live operations and incident response |

## Minimal Profile Snippets

These are intentionally small examples that line up with the matrix above.

### Local

```env
ENVIRONMENT="local"
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/fastapi_template"
CORS_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000","http://localhost:5173","http://127.0.0.1:5173"]
REFRESH_TOKEN_COOKIE_SECURE=false
SESSION_SECURE_COOKIES=false
SENTRY_ENABLE=false
TRUSTED_HOSTS=["localhost","127.0.0.1"]
```

### Staging

```env
ENVIRONMENT="staging"
DATABASE_URL="postgresql://staging_user:replace-me@staging-db.example.com:5432/fastapi_template"
CORS_ORIGINS=["https://staging.example.com"]
REFRESH_TOKEN_COOKIE_SECURE=true
SESSION_SECURE_COOKIES=true
TRUSTED_HOSTS=["staging.example.com"]
PROXY_HEADERS_ENABLED=true
PROXY_HEADERS_TRUSTED_PROXIES=["10.0.0.0/8"]
SENTRY_ENABLE=true
```

### Production

```env
ENVIRONMENT="production"
DATABASE_URL="postgresql://prod_user:replace-me@prod-db.example.com:5432/fastapi_template"
CORS_ORIGINS=["https://app.example.com"]
REFRESH_TOKEN_COOKIE_SECURE=true
SESSION_SECURE_COOKIES=true
TRUSTED_HOSTS=["app.example.com","www.app.example.com"]
PROXY_HEADERS_ENABLED=true
PROXY_HEADERS_TRUSTED_PROXIES=["10.0.0.0/8"]
SECURITY_HEADERS_HSTS_ENABLED=true
SENTRY_ENABLE=true
METRICS_ENABLED=true
TRACING_ENABLED=true
```

## Promotion Checklist

Move from one environment to the next by promoting the same template shape, not by inventing a separate configuration model per deployment tier.

- Replace all placeholder secrets and passwords before leaving `local`.
- Keep `CORS_ORIGINS`, `TRUSTED_HOSTS`, and `PROXY_HEADERS_TRUSTED_PROXIES` explicit in secure environments.
- Test optional-module feature flags in `staging` before changing them in `production`.
- Validate proxy trust, cookie behavior, and API docs exposure in `staging` before going live.
- Turn on the observability integrations you actually plan to use before promoting to `production`.

## Related Guides

- [Environment Variables](environment-variables.md)
- [Settings Classes](settings-classes.md)
- [Production Guide](../production.md)
