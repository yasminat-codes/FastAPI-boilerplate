"""Maintenance command for pruning expired token blacklist rows."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from ..app.core.db.crud_token_blacklist import delete_expired_token_blacklist_entries
from ..app.core.db.database import AsyncSession, local_session
from ..app.core.db.sessions import DatabaseSessionScope, database_transaction, open_database_session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def cleanup_expired_token_blacklist_entries(
    session: AsyncSession,
    *,
    expired_before: datetime | None = None,
) -> int:
    """Delete expired blacklist rows using the shared maintenance helper."""

    cutoff = expired_before or datetime.now(UTC).replace(tzinfo=None)
    deleted_count: int = await delete_expired_token_blacklist_entries(session, expired_before=cutoff)
    logger.info("Deleted %s expired token blacklist rows older than %s.", deleted_count, cutoff.isoformat())
    return deleted_count


async def async_main() -> None:
    async with open_database_session(local_session, DatabaseSessionScope.SCRIPT) as session:
        async with database_transaction(session):
            await cleanup_expired_token_blacklist_entries(session)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    asyncio.run(async_main())
