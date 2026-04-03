# Database Migrations

This guide covers database migrations using Alembic, the migration tool for SQLAlchemy. Learn how to manage database schema changes safely and efficiently in development and production.

## Overview

The FastAPI Boilerplate uses [Alembic](https://alembic.sqlalchemy.org/) for database migrations. Alembic provides:

- **Version-controlled schema changes** - Track every database modification
- **Automatic migration generation** - Generate migrations from model changes  
- **Reversible migrations** - Upgrade and downgrade database versions
- **Environment-specific configurations** - Different settings for dev/staging/production
- **Safe schema evolution** - Apply changes incrementally

## Migrations-Only Startup

The template no longer creates tables automatically during application startup. Database schema changes should be applied with Alembic before serving traffic, not as a side effect of booting the API process.

Use the following startup split:

- Application boot initializes runtime dependencies and shared clients.
- Migration execution is a separate operational step.
- Schema creation belongs to Alembic, not to `create_application()`.

This keeps production boot deterministic and avoids hiding schema drift behind application startup.

## Configuration

### Alembic Setup

Alembic is configured in the repository-root `alembic.ini` so template users can run migration commands from the project root:

```ini
[alembic]
script_location = %(here)s/src/migrations
prepend_sys_path = %(here)s/src
sqlalchemy.url = driver://user:pass@localhost/dbname
```

Use `uv run db-migrate ...` as the preferred developer command. It is a thin wrapper around Alembic that always injects the canonical repository-root config, so developers do not need to remember `-c alembic.ini` or change directories before running migration commands.

### Environment Configuration

Migration environment is configured in `src/migrations/env.py`:

```python
# src/migrations/env.py
import importlib
import pkgutil

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.platform.config import settings
from app.platform.database import Base

def import_models(package_name: str) -> None:
    package = importlib.import_module(package_name)
    for _, module_name, _ in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        importlib.import_module(module_name)

config = context.config

# Import domain models so autogenerate sees the full metadata.
import_models("app.domain")

# Override the placeholder URL from the config file with the environment-backed runtime URL.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata
```

For connection tuning, session scope, and SSL guidance that complement migrations, see [Database Reliability](reliability.md).

## Migration Workflow

### 1. Creating Migrations

Generate migrations automatically when you change models:

```bash
# Generate migration from model changes
uv run db-migrate revision --autogenerate -m "Add user profile fields"
```

**What happens:**
- Alembic compares current models with database schema
- Generates a new migration file in `src/migrations/versions/`
- Migration includes upgrade and downgrade functions

### 2. Review Generated Migration

Always review auto-generated migrations before applying:

```python
# Example migration file: src/migrations/versions/20241215_1430_add_user_profile_fields.py
"""Add user profile fields

Revision ID: abc123def456
Revises: previous_revision_id
Create Date: 2024-12-15 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'abc123def456'
down_revision = 'previous_revision_id'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add new columns
    op.add_column('user', sa.Column('bio', sa.String(500), nullable=True))
    op.add_column('user', sa.Column('website', sa.String(255), nullable=True))
    
    # Create index
    op.create_index('ix_user_website', 'user', ['website'])

def downgrade() -> None:
    # Remove changes (reverse order)
    op.drop_index('ix_user_website', 'user')
    op.drop_column('user', 'website')
    op.drop_column('user', 'bio')
```

### 3. Apply Migration

Apply migrations to update database schema:

```bash
# Apply all pending migrations
uv run db-migrate upgrade head

# Apply specific number of migrations
uv run db-migrate upgrade +2

# Apply to specific revision
uv run db-migrate upgrade abc123def456
```

### 4. Verify Migration

Check migration status and current version:

```bash
# Show current database version
uv run db-migrate current

# Show migration history
uv run db-migrate history

# Show pending migrations
uv run db-migrate show head
```

To verify the full template migration path on a disposable database, use the repo-provided verification wrapper:

```bash
# Apply all revisions, then fail if model metadata would autogenerate new drift
uv run db-migrate-verify
```

## Operational Guidance

- Run migrations before bringing up the API or worker process in production.
- Keep destructive schema changes out of normal boot paths.
- For rollback planning, decide ahead of time whether the safe recovery path is downgrade, forward-fix, or backup restore.
- Use data migrations and script-scoped backfills for data movement, not ad hoc SQL in application startup.
- Roll schema changes out with an expand-contract sequence when a change removes or renames live structures.
- In CI, run `uv run db-migrate-verify` against an ephemeral PostgreSQL database so migration application and schema drift are both checked from a clean state.

## Rollback Guidance For Migration Failures

Rollback planning belongs in the design of the revision, not in the incident call after a deploy has already failed.
Before a migration reaches production, decide which of these three recovery paths applies:

- **Downgrade** when the revision is reversible, the downgrade path has been tested, and the migration has not already invalidated live application assumptions.
- **Forward-fix** when the safest recovery is a new corrective migration instead of trying to reverse partially applied schema or data changes.
- **Restore from backup** when the change is destructive or irreversible and reversing it with Alembic would not safely reconstruct the previous state.

### Recommended rollback checklist

1. Stop the rollout and confirm whether the failure happened before, during, or after the revision was applied.
2. Capture the current revision with `uv run db-migrate current` and save the failing logs or database error details.
3. Decide whether the incident should use downgrade, forward-fix, or restore based on the revision design.
4. If downgrading is safe, run the exact target downgrade on the same disposable or staging shape you rehearsed before production.
5. Verify the database state, rerun smoke checks, and only then restore API or worker traffic.
6. Follow with a corrected revision, updated runbook notes, and a documented cause of failure before the next deploy attempt.

### When to prefer downgrade

Use an Alembic downgrade only when all of the following are true:

- The revision has an explicit `downgrade()` path.
- The downgrade has been exercised in staging or a disposable production-like database.
- The migration does not drop or rewrite data that the downgrade cannot reconstruct.
- The application code can still run safely against the older schema after traffic is shifted back.

If any of those conditions are false, prefer a forward-fix migration or a restore from backup.

### Minimal recovery commands

```bash
# Inspect the current revision before making changes
uv run db-migrate current
uv run db-migrate history

# Downgrade one revision when the rollback plan explicitly allows it
uv run db-migrate downgrade -1

# Or downgrade to a known-safe revision
uv run db-migrate downgrade <known_safe_revision>
```

Treat backups as part of the rollback contract for every production migration.
For destructive or high-risk revisions, the template expectation is:

- Take a fresh backup before the migration window.
- Rehearse the restore path as well as the Alembic path.
- Record whether the operational recovery step is downgrade, forward-fix, or restore in the deploy plan.

## Data Backfill Guidance And Script Pattern

Backfills should run as explicit operational work, not inside API startup, request handlers, or normal worker boot hooks.
The reusable template pattern is:

- use a script-scoped database session,
- process rows in bounded batches,
- commit each batch independently,
- make the script idempotent so it can resume safely,
- support a dry-run mode before touching production data.

### Backfill script scaffold

```python
import argparse
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.platform.database import (
    DatabaseSessionScope,
    database_transaction,
    local_session,
    open_database_session,
    retry_database_operation,
)

LOGGER = logging.getLogger(__name__)


async def process_batch(
    session: AsyncSession,
    *,
    batch_size: int,
    dry_run: bool,
) -> int:
    result = await session.execute(
        select(ExampleModel)
        .where(ExampleModel.new_value.is_(None))
        .order_by(ExampleModel.id)
        .limit(batch_size)
    )
    rows = list(result.scalars())
    if not rows:
        return 0

    if dry_run:
        for row in rows:
            row.new_value = build_new_value(row)
        await session.rollback()
        return len(rows)

    async with database_transaction(session):
        for row in rows:
            row.new_value = build_new_value(row)

    return len(rows)


async def run_backfill(*, batch_size: int, dry_run: bool) -> None:
    async with open_database_session(local_session, DatabaseSessionScope.SCRIPT) as session:
        while True:
            updated = await retry_database_operation(
                lambda: process_batch(
                    session,
                    batch_size=batch_size,
                    dry_run=dry_run,
                ),
                attempts=3,
            )
            if updated == 0:
                break

            LOGGER.info("Processed %s rows", updated)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Template backfill pattern")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run_backfill(batch_size=args.batch_size, dry_run=args.dry_run))
```

### Backfill rules

- Keep each batch small enough to retry safely and to limit lock duration.
- Make the selection predicate exclude already-processed rows so reruns are safe.
- Prefer monotonic checkpoints such as primary-key ranges, timestamps, or an explicit progress table when a backfill spans many batches.
- Log batch counts and boundaries so operators can estimate remaining work.
- Run schema migration first, then the backfill, then the later contract step that makes the old shape unreachable.
- If a backfill is large enough to compete with live traffic, throttle it or run it during a maintenance window.

## Destructive Schema Changes And Expand-Contract Rules

Destructive changes are any revisions that remove, rename, or narrow data structures that live code may still depend on.
Those changes should not ship as a one-step migration in the template. Use an expand-contract rollout instead.

### Expand-contract sequence

1. **Expand**: add the new column, table, index, or compatibility structure in a backwards-compatible form.
2. **Migrate reads and writes**: deploy application code that can use both the old and new shapes, or dual-write where necessary.
3. **Backfill**: populate the new structure outside application startup and verify completeness.
4. **Contract**: remove the old column, table, constraint, or code path in a later deploy once the new path is fully live.

### Rules for destructive changes

- Do not combine add, backfill, and drop steps in a single production deploy.
- Treat renames as add-copy-switch-drop, not as an instantaneous rename when application code and external clients may still reference the old name.
- Add new non-null columns as nullable or server-defaulted first, then enforce stricter constraints only after the backfill succeeds.
- Delay table drops, column drops, and irreversible type changes until logs, metrics, and application reads confirm the old path is unused.
- Keep downgrade expectations realistic: a contract-step migration may need a restore plan instead of a true downgrade if data was discarded.
- Review large index builds, table rewrites, and lock-heavy operations for operational impact before scheduling the rollout.

### Example rollout for a column rename

```text
Release A:
- add new_column as nullable
- write both old_column and new_column

Release B:
- backfill new_column from old_column
- switch reads to new_column
- verify no traffic depends on old_column

Release C:
- drop old_column
- remove compatibility code
```

## Common Migration Scenarios

### Adding New Model

1. **Create the model** in `src/app/models/`:

```python
# src/app/models/category.py
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from app.core.db.database import Base

class Category(Base):
    __tablename__ = "category"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

2. **Import in __init__.py**:

```python
# src/app/models/__init__.py
from .user import User
from .post import Post
from .tier import Tier
from .rate_limit import RateLimit
from .category import Category  # Add new import
```

3. **Generate migration**:

```bash
uv run db-migrate revision --autogenerate -m "Add category model"
```

### Adding Foreign Key

1. **Update model with foreign key**:

```python
# Add to Post model
category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("category.id"), nullable=True)
```

2. **Generate migration**:

```bash
uv run db-migrate revision --autogenerate -m "Add category_id to posts"
```

3. **Review and apply**:

```python
# Generated migration will include:
def upgrade() -> None:
    op.add_column('post', sa.Column('category_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_post_category_id', 'post', 'category', ['category_id'], ['id'])
    op.create_index('ix_post_category_id', 'post', ['category_id'])
```

### Data Migrations

Sometimes you need to migrate data, not just schema. Keep the migration step focused on schema compatibility and run larger data movement with the backfill pattern above:

```python
# Example: Populate default category for existing posts
def upgrade() -> None:
    # Add the column
    op.add_column('post', sa.Column('category_id', sa.Integer(), nullable=True))
    
    # Data migration
    connection = op.get_bind()
    
    # Create default category
    connection.execute(
        "INSERT INTO category (name, slug, description) VALUES ('General', 'general', 'Default category')"
    )
    
    # Get default category ID
    result = connection.execute("SELECT id FROM category WHERE slug = 'general'")
    default_category_id = result.fetchone()[0]
    
    # Update existing posts
    connection.execute(
        f"UPDATE post SET category_id = {default_category_id} WHERE category_id IS NULL"
    )
    
    # Make column non-nullable after data migration
    op.alter_column('post', 'category_id', nullable=False)
```

### Renaming Columns

```python
def upgrade() -> None:
    # Rename column
    op.alter_column('user', 'full_name', new_column_name='name')

def downgrade() -> None:
    # Reverse the rename
    op.alter_column('user', 'name', new_column_name='full_name')
```

### Dropping Tables

```python
def upgrade() -> None:
    # Drop table (be careful!)
    op.drop_table('old_table')

def downgrade() -> None:
    # Recreate table structure
    op.create_table('old_table',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(50), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
```

## Production Migration Strategy

### 1. Development Workflow

```bash
# 1. Make model changes
# 2. Generate migration
uv run db-migrate revision --autogenerate -m "Descriptive message"

# 3. Review migration file
# 4. Test migration
uv run db-migrate upgrade head

# 5. Test downgrade (optional)
uv run db-migrate downgrade -1
uv run db-migrate upgrade head
```

### 2. Staging Deployment

```bash
# 1. Deploy code with migrations
# 2. Backup database
pg_dump -h staging-db -U user dbname > backup_$(date +%Y%m%d_%H%M%S).sql

# 3. Apply migrations
uv run db-migrate upgrade head

# 4. Verify application works
# 5. Run tests
```

### 3. Production Deployment

```bash
# 1. Schedule maintenance window
# 2. Create database backup
pg_dump -h prod-db -U user dbname > prod_backup_$(date +%Y%m%d_%H%M%S).sql

# 3. Apply migrations (with monitoring)
uv run db-migrate upgrade head

# 4. Verify health checks pass
# 5. Monitor application metrics
```

## Docker Considerations

### Development with Docker Compose

For local development, migrations run automatically:

```yaml
# docker-compose.yml
services:
  web:
    # ... other config
    depends_on:
      - db
    command: |
      sh -c "
        uv run db-migrate upgrade head &&
        uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
      "
```

### Production Docker

In production, run migrations separately:

```dockerfile
# Dockerfile migration stage
FROM python:3.11-slim as migration
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src/ /app/
WORKDIR /app
CMD ["alembic", "upgrade", "head"]
```

```yaml
# docker-compose.prod.yml
services:
  migrate:
    build:
      context: .
      target: migration
    env_file:
      - .env
    depends_on:
      - db
    command: alembic upgrade head
    
  web:
    # ... web service config
    depends_on:
      - migrate
```

## Migration Best Practices

### 1. Always Review Generated Migrations

```python
# Check for issues like:
# - Missing imports
# - Incorrect nullable settings
# - Missing indexes
# - Data loss operations
```

### 2. Use Descriptive Messages

```bash
# Good
uv run db-migrate revision --autogenerate -m "Add user email verification fields"

# Bad
uv run db-migrate revision --autogenerate -m "Update user model"
```

### 3. Handle Nullable Columns Carefully

```python
# When adding non-nullable columns to existing tables:
def upgrade() -> None:
    # 1. Add as nullable first
    op.add_column('user', sa.Column('phone', sa.String(20), nullable=True))
    
    # 2. Populate with default data
    op.execute("UPDATE user SET phone = '' WHERE phone IS NULL")
    
    # 3. Make non-nullable
    op.alter_column('user', 'phone', nullable=False)
```

### 4. Test Rollbacks

```bash
# Test that your downgrade works
uv run db-migrate downgrade -1
uv run db-migrate upgrade head
```

### 5. Use Transactions for Complex Migrations

```python
def upgrade() -> None:
    # Complex migration with transaction
    connection = op.get_bind()
    trans = connection.begin()
    try:
        # Multiple operations
        op.create_table(...)
        op.add_column(...)
        connection.execute("UPDATE ...")
        trans.commit()
    except:
        trans.rollback()
        raise
```

## Next Steps

- **[CRUD Operations](crud.md)** - Working with migrated database schema
- **[API Development](../api/index.md)** - Building endpoints for your models
- **[Testing](../testing.md)** - Testing database migrations 
