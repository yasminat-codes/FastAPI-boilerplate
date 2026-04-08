# Backups, Recovery, and Maintenance

This guide covers backup strategies for PostgreSQL and Redis, data recovery procedures, and ongoing maintenance tasks to keep the FastAPI boilerplate healthy in production.

## PostgreSQL Backup Strategy

PostgreSQL data is persistent and critical. A comprehensive backup strategy is essential.

### Backup Methods

=== "pg_dump (SQL Text)"
    **Best for:** Smaller databases, manual backups, cross-version migration
    
    ```bash
    # Full database backup
    pg_dump -h localhost -U postgres -d myapp > backup.sql
    
    # Compressed backup (smaller file)
    pg_dump -h localhost -U postgres -d myapp | gzip > backup.sql.gz
    
    # With verbose output
    pg_dump -h localhost -U postgres -d myapp -v > backup.sql
    
    # Only schema (no data)
    pg_dump -h localhost -U postgres -d myapp --schema-only > schema.sql
    
    # Only data (no schema)
    pg_dump -h localhost -U postgres -d myapp --data-only > data.sql
    ```

=== "pg_dump (Custom Format)"
    **Best for:** Large databases, faster restore, selective restoration
    
    ```bash
    # Custom format (faster compression, parallel restore)
    pg_dump -h localhost -U postgres -d myapp \
      -F custom -f backup.dump
    
    # Parallel dump (faster for large databases)
    pg_dump -h localhost -U postgres -d myapp \
      -F custom --jobs=4 -f backup.dump
    
    # With progress
    pg_dump -h localhost -U postgres -d myapp \
      -F custom -f backup.dump -v
    ```

=== "WAL Archiving"
    **Best for:** Point-in-time recovery, continuous protection
    
    ```bash
    # Enable in postgresql.conf
    wal_level = replica
    archive_mode = on
    archive_command = 'cp %p /backup/wal_archive/%f'
    
    # Or with S3 (e.g., pgBackRest)
    pgbackrest --stanza=main --log-level-console=info backup
    ```

### Automated Backup Script

```bash
#!/bin/bash
# backup-postgres.sh

set -e

BACKUP_DIR="/backups/postgres"
RETENTION_DAYS=30
DB_NAME="myapp"
DB_USER="postgres"
DB_HOST="localhost"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/backup_${DB_NAME}_${TIMESTAMP}.sql.gz"

# Run backup
echo "Starting backup at $(date)"
pg_dump \
  -h "$DB_HOST" \
  -U "$DB_USER" \
  -d "$DB_NAME" \
  | gzip > "$BACKUP_FILE"

echo "✅ Backup complete: $BACKUP_FILE"

# Delete old backups
echo "Cleaning backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -name "backup_*.sql.gz" -mtime +$RETENTION_DAYS -delete

# Verify backup
echo "Verifying backup integrity..."
gunzip -t "$BACKUP_FILE" || {
  echo "❌ Backup verification failed!"
  exit 1
}

echo "✅ Backup verified"
```

### Scheduling with cron

```bash
# Add to crontab: backup daily at 2 AM
0 2 * * * /opt/scripts/backup-postgres.sh >> /var/log/backup.log 2>&1

# Backup multiple databases
0 2 * * * for db in app_db user_db; do \
  pg_dump -h localhost -U postgres -d $db | gzip > /backups/$db-$(date +\%Y\%m\%d).sql.gz; \
  done
```

### S3 Backup with Retention

```bash
#!/bin/bash
# backup-to-s3.sh

BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sql.gz"
S3_BUCKET="s3://my-backups/postgres"
RETENTION_DAYS=30

# Backup locally first
pg_dump -h localhost -U postgres -d myapp | gzip > "$BACKUP_FILE"

# Upload to S3
aws s3 cp "$BACKUP_FILE" "$S3_BUCKET/"

# Delete local backup
rm "$BACKUP_FILE"

# Delete old S3 backups
aws s3 ls "$S3_BUCKET/" | awk '{print $4}' | while read file; do
  file_date=$(echo "$file" | cut -d'_' -f2 | cut -d'.' -f1)
  current_date=$(date +%Y%m%d)
  days_old=$(( ($(date +%s -d "$current_date") - $(date +%s -d "$file_date")) / 86400 ))
  
  if [ "$days_old" -gt "$RETENTION_DAYS" ]; then
    aws s3 rm "$S3_BUCKET/$file"
  fi
done
```

## PostgreSQL Restore and Validation

### Basic Restore

```bash
# Restore from SQL dump
psql -h localhost -U postgres -d myapp < backup.sql

# Restore from compressed dump
gunzip < backup.sql.gz | psql -h localhost -U postgres -d myapp

# Restore custom format
pg_restore -h localhost -U postgres -d myapp backup.dump

# Parallel restore (faster)
pg_restore -h localhost -U postgres -d myapp backup.dump -j 4
```

### Restore to Point-in-Time

```bash
# Find transaction logs needed
ls -la /backup/wal_archive/ | grep 000000010000000000

# Recover to specific timestamp
pg_ctl stop -m fast
cp /backup/backup.dump /var/lib/postgresql/data
cp /backup/wal_archive/* /var/lib/postgresql/data/pg_wal/

# Create recovery.conf
cat > /var/lib/postgresql/data/recovery.conf <<EOF
restore_command = 'cp /backup/wal_archive/%f %p'
recovery_target_timeline = 'latest'
recovery_target_xid = '1234567'  # Or timestamp
recovery_target_inclusive = true
EOF

pg_ctl start
```

### Restore Validation

Always validate backups before relying on them:

```bash
#!/bin/bash
# validate-backup.sh

BACKUP_FILE="$1"
TEST_DB="test_restore_validation"

# Clean up previous test
psql -h localhost -U postgres -d postgres -c "DROP DATABASE IF EXISTS $TEST_DB;"

# Create test database
psql -h localhost -U postgres -d postgres -c "CREATE DATABASE $TEST_DB;"

# Restore backup
gunzip < "$BACKUP_FILE" | psql -h localhost -U postgres -d "$TEST_DB"

# Validate structure
echo "Validating schema..."
psql -h localhost -U postgres -d "$TEST_DB" -c "\dt" | wc -l

# Check row counts
echo "Validating data..."
psql -h localhost -U postgres -d "$TEST_DB" -c "
  SELECT schemaname, tablename, n_live_tup 
  FROM pg_stat_user_tables 
  ORDER BY n_live_tup DESC LIMIT 10;
"

# Run application-specific validation
psql -h localhost -U postgres -d "$TEST_DB" -c "
  -- Check for referential integrity
  SELECT constraint_name, table_name 
  FROM information_schema.table_constraints 
  WHERE constraint_type = 'FOREIGN KEY';
"

# Clean up
psql -h localhost -U postgres -d postgres -c "DROP DATABASE $TEST_DB;"
echo "✅ Backup validation complete"
```

## Redis Data and Queue Management

Redis holds two types of data with different retention requirements.

### Redis Data Types

| Data Type | Content | Persistence | Action on Loss |
|-----------|---------|-------------|-----------------|
| **Cache** | Session data, query cache, rate limits | Ephemeral | OK - can regenerate |
| **Queue** | Background job tasks (ARQ) | Should persist | Loss = missing jobs |
| **Sessions** | User login state | Ephemeral | User needs to re-login |
| **Rate Limits** | Request counts | Ephemeral | Brief cleanup delay |

### Redis Persistence Configuration

```bash
# redis.conf - Enable persistence
save 900 1          # Save if 1 key changed in 900 seconds
save 300 10         # Save if 10 keys changed in 300 seconds
save 60 10000       # Save if 10000 keys changed in 60 seconds

appendonly yes      # Enable AOF (append-only file)
appendfsync everysec  # Sync to disk every second

# Set memory limits
maxmemory 512mb
maxmemory-policy allkeys-lru  # Evict least recently used when full
```

### Redis Backup

```bash
# Create Redis backup (snapshot)
redis-cli BGSAVE

# Save to S3
redis-cli --rdb /tmp/redis.rdb
aws s3 cp /tmp/redis.rdb s3://backups/redis/

# Backup AOF
redis-cli --pipe < /var/lib/redis/appendonly.aof | \
  aws s3 cp - s3://backups/redis/appendonly.aof

# Automated backup with cron
0 3 * * * redis-cli BGSAVE && \
  aws s3 cp /var/lib/redis/dump.rdb s3://backups/redis/dump-$(date +\%Y\%m\%d).rdb
```

### Restore Redis Data

```bash
# Stop Redis
redis-cli SHUTDOWN

# Restore from backup
aws s3 cp s3://backups/redis/dump.rdb /var/lib/redis/dump.rdb

# Restart Redis
redis-server /etc/redis/redis.conf

# Verify data
redis-cli DBSIZE
redis-cli KEYS "*" | head -20
```

### Queue Monitoring

Monitor job queue to catch buildup early:

```bash
#!/bin/bash
# monitor-queue.sh

REDIS_HOST="localhost"
QUEUE_NAME="default"

while true; do
  pending_jobs=$(redis-cli -h "$REDIS_HOST" LLEN "$QUEUE_NAME:queue")
  echo "$(date): Pending jobs: $pending_jobs"
  
  if [ "$pending_jobs" -gt 1000 ]; then
    echo "⚠️  WARNING: Queue backlog critical!"
    # Alert ops team
  fi
  
  sleep 60
done
```

## Maintenance Tasks

Regular maintenance keeps the application healthy and performs well.

### Token Blacklist Cleanup

If using token blacklisting for logout, clean up expired tokens regularly:

```python
# src/app/tasks/maintenance.py
from datetime import datetime, timedelta
from sqlalchemy import select, delete
from app.core.models import TokenBlacklist

async def cleanup_expired_tokens(db: AsyncSession):
    """Remove expired tokens from blacklist"""
    cutoff = datetime.utcnow() - timedelta(days=7)
    
    await db.execute(
        delete(TokenBlacklist).where(TokenBlacklist.expires_at < cutoff)
    )
    await db.commit()
    
    logger.info("Token blacklist cleanup complete")
```

Schedule with APScheduler:

```python
# src/app/tasks/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler

def setup_scheduler(app: FastAPI):
    scheduler = AsyncIOScheduler()
    
    # Run token cleanup daily at 3 AM
    scheduler.add_job(
        cleanup_expired_tokens,
        "cron",
        hour=3,
        minute=0
    )
    
    scheduler.start()
```

### Webhook Event Retention

Limit webhook event storage to prevent database bloat:

```python
# src/app/tasks/maintenance.py
from datetime import datetime, timedelta
from sqlalchemy import select, delete
from app.core.models import WebhookEvent

async def cleanup_old_webhook_events(db: AsyncSession, retention_days: int = 90):
    """Delete webhook events older than retention_days"""
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    
    result = await db.execute(
        delete(WebhookEvent).where(WebhookEvent.created_at < cutoff)
    )
    await db.commit()
    
    logger.info(f"Deleted {result.rowcount} old webhook events")
```

Add to scheduler:

```python
scheduler.add_job(
    cleanup_old_webhook_events,
    "cron",
    hour=2,
    minute=0,
    kwargs={"retention_days": 90}
)
```

### Dead-Letter Queue Cleanup

Failed jobs in ARQ's dead-letter queue need monitoring:

```python
# src/app/tasks/maintenance.py
import json
from aioredis import Redis

async def cleanup_dead_letter_queue(redis: Redis, max_age_days: int = 30):
    """Clean up old items in dead-letter queue"""
    dlq_key = "arq:dead-letter"
    
    # Get all items
    items = await redis.lrange(dlq_key, 0, -1)
    
    cutoff_time = time.time() - (max_age_days * 86400)
    removed = 0
    
    for item in items:
        job_data = json.loads(item)
        if job_data.get("created_time", 0) < cutoff_time:
            await redis.lrem(dlq_key, 1, item)
            removed += 1
    
    logger.info(f"Cleaned up {removed} dead-letter jobs")
```

### Audit Log Retention

Keep audit logs for compliance but manage storage:

```python
# src/app/tasks/maintenance.py
from datetime import datetime, timedelta
from sqlalchemy import select, delete
from app.core.models import AuditLog

async def cleanup_old_audit_logs(db: AsyncSession, retention_days: int = 365):
    """Delete audit logs older than retention_days"""
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    
    # First, archive to cold storage if needed
    old_logs = await db.execute(
        select(AuditLog).where(AuditLog.created_at < cutoff)
    )
    
    # Export to file
    logs_to_archive = old_logs.scalars().all()
    if logs_to_archive:
        await export_logs_to_archive(logs_to_archive)
    
    # Delete from database
    result = await db.execute(
        delete(AuditLog).where(AuditLog.created_at < cutoff)
    )
    await db.commit()
    
    logger.info(f"Archived and deleted {result.rowcount} old audit logs")
```

### Database Statistics

Update database statistics for query optimizer:

```bash
# Run ANALYZE to update query planner stats
psql -h localhost -U postgres -d myapp -c "ANALYZE;"

# Or in a scheduled script
0 4 * * * psql -h localhost -U postgres -d myapp -c "ANALYZE;"
```

### Log Cleanup

Manage application log files to prevent disk fill:

```bash
#!/bin/bash
# cleanup-logs.sh

LOG_DIR="/var/log/app"
RETENTION_DAYS=30
MAX_SIZE_MB=1000

# Delete logs older than retention period
find "$LOG_DIR" -name "*.log" -mtime +$RETENTION_DAYS -delete

# Compress old logs
find "$LOG_DIR" -name "*.log" -mtime +7 -exec gzip {} \;

# Delete if total size exceeds max
total_size=$(du -sb "$LOG_DIR" | cut -f1)
total_size_mb=$((total_size / 1024 / 1024))

if [ "$total_size_mb" -gt "$MAX_SIZE_MB" ]; then
  # Delete oldest compressed logs
  ls -t "$LOG_DIR"/*.gz | tail -n +10 | xargs rm -f
fi
```

## Maintenance Schedule

| Task | Frequency | Impact | Command |
|------|-----------|--------|---------|
| PostgreSQL backup | Daily | None | `pg_dump ... \| gzip` |
| Backup validation | Weekly | None | Restore to test DB |
| Token cleanup | Weekly | None | Delete expired tokens |
| Webhook event cleanup | Monthly | None | Delete old events |
| Dead-letter cleanup | Monthly | None | Clean failed jobs |
| Log rotation | Daily | Disk space | `logrotate` |
| DB ANALYZE | Weekly | Query performance | `ANALYZE` |
| Audit log archive | Monthly | Compliance | Export to storage |
| Security updates | As needed | Availability | Update base images |
| Dependency updates | Monthly | Compatibility | Update lockfile |

## Data Retention Policy

Define retention periods for compliance and storage optimization:

| Data Type | Retention | Reason | Action |
|-----------|-----------|--------|--------|
| Database backups | 30 days | Recovery window | Delete after |
| Transaction logs | 7 days | Point-in-time recovery | Auto-delete |
| Webhook events | 90 days | Audit/debugging | Export and delete |
| Audit logs | 365 days | Compliance/legal | Archive to cold storage |
| Session tokens | Until expiration | Security | Auto-delete on expiry |
| Rate limit counters | TTL based | Performance | Auto-expire |
| User logs | 30 days | Debugging | Delete after |
| API access logs | 14 days | Monitoring | Delete after |
| Error/exception logs | 90 days | Debugging | Export and delete |
| Dead-letter jobs | 30 days | Operations | Delete after |

## Disaster Recovery

### RTO and RPO Targets

- **RTO (Recovery Time Objective):** < 4 hours to restore service
- **RPO (Recovery Point Objective):** < 1 hour data loss

### Recovery Checklist

- [ ] Latest backup available and validated
- [ ] Backup location accessible (S3, offline storage, etc.)
- [ ] PostgreSQL and Redis restore procedures tested
- [ ] Database restoration time measured (< 1 hour expected)
- [ ] Application startup verified after restore
- [ ] Data integrity checks passed
- [ ] Monitoring and alerting re-enabled

### Full Environment Restoration

```bash
# 1. Provision new infrastructure
# 2. Restore PostgreSQL
pg_restore -h new-db-host -d myapp backup.dump

# 3. Restore Redis
redis-cli -h new-redis-host < /backup/redis.dump

# 4. Deploy application
docker pull registry.example.com/app:v1.0.0
docker run -e DATABASE_URL=... registry.example.com/app:v1.0.0

# 5. Run smoke tests
curl https://api.example.com/health

# 6. Update DNS to point to new environment
# 7. Monitor for errors
```

## Summary Checklist

- [ ] Daily automated PostgreSQL backups
- [ ] Weekly backup validation to test database
- [ ] S3 or off-site storage for backups
- [ ] Redis persistence enabled for queue data
- [ ] Weekly token cleanup scheduled
- [ ] Monthly webhook event cleanup
- [ ] Audit logs retained per compliance requirements
- [ ] Log rotation prevents disk overflow
- [ ] Database ANALYZE scheduled weekly
- [ ] RTO/RPO targets defined and tested
- [ ] Disaster recovery plan documented
- [ ] Full restore test conducted monthly
