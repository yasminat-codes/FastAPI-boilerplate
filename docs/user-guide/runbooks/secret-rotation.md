# Runbook: Secret Rotation

This runbook covers the process and operational procedures for rotating secrets that the template manages or depends on: JWT signing keys, database credentials, Redis passwords, provider API keys, and webhook signing secrets.

## General Principles

1. **Never rotate secrets without a rollback plan.** Know how to revert to the previous secret if the new one causes failures.
2. **Rotate one secret at a time.** If multiple rotations happen simultaneously and something breaks, isolating the cause is harder.
3. **Test the new secret before cutting over.** Verify that the new credential works before removing the old one.
4. **Coordinate with your team.** Secret rotation can cause brief disruptions. Communicate the timing and expected impact.
5. **Log the rotation event.** Record when the rotation happened, who performed it, and which secret was rotated (without logging the secret values themselves).

## JWT Signing Keys

The template supports `kid`-based signing-key rotation so you can rotate JWT signing secrets without invalidating all active tokens at once.

### Process

1. **Generate a new signing key:**
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(64))"
   ```

2. **Add the new key to the verification key ring** without removing the old key yet:
   ```bash
   # Before:
   JWT_SECRET_KEY=old-secret-key
   JWT_ACTIVE_KEY_ID=key-2024
   JWT_VERIFICATION_KEYS='{"key-2024": "old-secret-key"}'

   # After (both keys present):
   JWT_SECRET_KEY=new-secret-key
   JWT_ACTIVE_KEY_ID=key-2025
   JWT_VERIFICATION_KEYS='{"key-2025": "new-secret-key", "key-2024": "old-secret-key"}'
   ```

3. **Deploy the updated settings.** The application will now:
   - Sign new tokens with the new key (`key-2025`).
   - Verify incoming tokens against both keys (matching by `kid` claim).

4. **Wait for the old tokens to expire.** Access tokens are short-lived (default 30 minutes). Refresh tokens are longer-lived. Wait at least as long as your longest token lifetime.

5. **Remove the old key from the verification ring:**
   ```bash
   JWT_VERIFICATION_KEYS='{"key-2025": "new-secret-key"}'
   ```

6. **Deploy again.** Any remaining tokens signed with the old key will fail verification and require re-authentication.

### Rollback

If the new key causes problems:

1. Revert `JWT_SECRET_KEY` and `JWT_ACTIVE_KEY_ID` to the old values.
2. Keep both keys in `JWT_VERIFICATION_KEYS` to avoid invalidating tokens signed with the new key during the brief window it was active.
3. Deploy and verify that token operations return to normal.

## Database Credentials

Rotating the database password requires coordination between the database server and the application.

### Process

1. **Create a new database role or update the existing password** on the PostgreSQL server:
   ```sql
   ALTER ROLE app_user WITH PASSWORD 'new-password-here';
   ```

2. **Update the application's `DATABASE_URL`** with the new password:
   ```bash
   DATABASE_URL=postgresql+asyncpg://app_user:new-password-here@db-host:5432/app_db
   ```

3. **Deploy the application.** The connection pool will be re-created on startup with the new credentials.

4. **Verify connectivity:**
   - Check `/api/v1/ready` — it should report the database as healthy.
   - Check structured logs for database connection errors.
   - Run a simple query through the application to confirm end-to-end connectivity.

### Zero-Downtime Rotation

For deployments that cannot tolerate any downtime:

1. Create a **second database role** with the same grants as the primary role:
   ```sql
   CREATE ROLE app_user_v2 WITH LOGIN PASSWORD 'new-password';
   GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO app_user_v2;
   GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_user_v2;
   ```

2. Deploy a portion of your application instances with the new role, while the rest continue using the old role.

3. Once you have confirmed the new role works, deploy all instances with the new role.

4. Drop the old role:
   ```sql
   DROP ROLE app_user;
   ```

### Rollback

If the new credentials do not work, revert `DATABASE_URL` to the old password and redeploy. The old password remains valid until you explicitly change it on the PostgreSQL server.

## Redis Password

### Process

1. **Set the new password on the Redis server:**
   ```bash
   redis-cli CONFIG SET requirepass "new-redis-password"
   ```

   If using Redis ACLs:
   ```bash
   redis-cli ACL SETUSER default on >new-redis-password ~* +@all
   ```

2. **Update the application's Redis connection settings:**
   ```bash
   REDIS_PASSWORD=new-redis-password
   ```

3. **Deploy the application.** Redis connections are re-established on startup.

4. **Verify connectivity:**
   - Check `/api/v1/ready` — it should report Redis services as healthy.
   - Check that caching, rate limiting, and queue operations function correctly.

### Rollback

Revert the Redis password on the server (`CONFIG SET requirepass "old-password"`) and revert the application's `REDIS_PASSWORD` setting.

## Provider API Keys

Each external integration has its own credential format and rotation process. The template's integration contracts layer provides a `SecretProvider` protocol and `CredentialHealth` tracking for managing provider credentials.

### General Process

1. **Generate a new key in the provider's dashboard** (Stripe, GitHub, Slack, etc.).
2. **Update the environment variable** for that provider:
   ```bash
   STRIPE_API_KEY=sk_live_new_key_here
   ```
3. **Deploy the application.**
4. **Verify the integration** by making a test call or checking structured logs for successful operations.
5. **Revoke the old key** in the provider's dashboard once you have confirmed the new key works.

### Provider-Specific Notes

- **Stripe**: Stripe supports rolling keys. You can create a new restricted key, deploy it, verify it works, and then delete the old key.
- **OAuth tokens**: If the integration uses OAuth, refresh the access token using the refresh token. If the refresh token is expired, re-authenticate through the OAuth flow.
- **API keys with expiry**: Some providers issue keys with a fixed expiry date. Set a calendar reminder to rotate before expiry.

### Rollback

If the new key does not work:

1. Revert the environment variable to the old key.
2. Redeploy.
3. Check whether the old key is still valid (some providers invalidate the old key when a new one is generated).

## Webhook Signing Secrets

Webhook signing secrets are used to verify that incoming webhook deliveries are authentic. Rotation requires updating both the provider's configuration and your application's verification settings.

### Process

1. **Generate a new signing secret in the provider's webhook settings.** Most providers allow you to view the current secret and generate a new one.

2. **Some providers support dual secrets during rotation:**
   - If the provider sends both the old and new signature headers during a transition period, your verifier will match on either.
   - Check the provider's documentation for rotation support.

3. **Update your application's signing secret:**
   ```bash
   STRIPE_WEBHOOK_SECRET=whsec_new_secret_here
   ```

4. **Deploy the application.**

5. **Verify by sending a test webhook** from the provider's dashboard. Confirm that signature verification succeeds in your logs.

6. **If the provider does not support dual secrets:** there will be a brief window where in-flight deliveries signed with the old secret are rejected. The provider will retry them, and the retries will be signed with the new secret. The template's replay protection ensures they are not processed twice.

### Rollback

Revert the signing secret environment variable and redeploy. Ask the provider to retry any deliveries that failed during the rotation window.

## Rotation Schedule

Establish a regular rotation schedule based on the sensitivity and exposure of each secret:

| Secret Type | Recommended Interval | Urgency if Compromised |
|-------------|---------------------|----------------------|
| JWT signing key | Every 90 days | Immediate — rotate and invalidate all active sessions |
| Database password | Every 90 days | Immediate — rotate and audit access logs |
| Redis password | Every 90 days | High — rotate promptly |
| Provider API keys | Every 90-180 days or per provider policy | Depends on provider — revoke and rotate immediately if compromised |
| Webhook signing secrets | Every 180 days or when provider rotates | High — rotate promptly to prevent spoofed deliveries |

## Automation Guidance

For teams that want to automate secret rotation:

1. **Use a secret manager** (AWS Secrets Manager, HashiCorp Vault, GCP Secret Manager) to store and rotate secrets automatically.
2. **Configure your deployment pipeline** to pull secrets from the secret manager at deploy time rather than storing them in environment files.
3. **Use the template's settings validation** to catch missing or empty secrets at startup. The template refuses to boot in production if critical secrets are not set.
4. **Set up rotation reminders** as scheduled tasks or calendar events. The template does not manage secret rotation schedules internally — this is an operational responsibility.

## Further Reading

- [Authentication — JWT Tokens](../authentication/jwt-tokens.md) — JWT issuer, audience, and key rotation configuration.
- [Configuration — Environment Variables](../configuration/environment-variables.md) — all settings that accept secret values.
- [Integration Contracts](../integrations/contracts.md) — secret provider protocol and credential health tracking.
- [Migration Failures](migration-failures.md) — when a rotation causes database connectivity issues.
