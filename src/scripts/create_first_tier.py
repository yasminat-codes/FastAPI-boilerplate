import asyncio
import logging

from sqlalchemy import select

from ..app.core.config import settings
from ..app.core.db.database import AsyncSession, local_session
from ..app.core.db.sessions import DatabaseSessionScope, database_transaction, open_database_session
from ..app.models.tier import Tier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_first_tier(session: AsyncSession) -> None:
    try:
        tier_name = getattr(settings, "TIER_NAME", "free")

        query = select(Tier).where(Tier.name == tier_name)
        result = await session.execute(query)
        tier = result.scalar_one_or_none()

        if tier is None:
            async with database_transaction(session):
                session.add(Tier(name=tier_name))
            logger.info(f"Tier '{tier_name}' created successfully.")

        else:
            logger.info(f"Tier '{tier_name}' already exists.")

    except Exception as e:
        logger.error(f"Error creating tier: {e}")


async def main():
    async with open_database_session(local_session, DatabaseSessionScope.SCRIPT) as session:
        await create_first_tier(session)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
