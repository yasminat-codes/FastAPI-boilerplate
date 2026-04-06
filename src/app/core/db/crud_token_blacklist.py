from datetime import UTC, datetime
from typing import cast

from fastcrud import FastCRUD
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Delete

from ..db.token_blacklist import TokenBlacklist
from ..schemas import TokenBlacklistCreate, TokenBlacklistRead, TokenBlacklistUpdate

CRUDTokenBlacklist = FastCRUD[
    TokenBlacklist,
    TokenBlacklistCreate,
    TokenBlacklistUpdate,
    TokenBlacklistUpdate,
    TokenBlacklistUpdate,
    TokenBlacklistRead,
]
crud_token_blacklist = CRUDTokenBlacklist(TokenBlacklist)


def build_expired_token_blacklist_cleanup_statement(*, expired_before: datetime) -> Delete:
    """Build a reusable delete statement for expired token blacklist rows."""

    return delete(TokenBlacklist).where(TokenBlacklist.expires_at < expired_before)


async def delete_expired_token_blacklist_entries(
    session: AsyncSession,
    *,
    expired_before: datetime | None = None,
) -> int:
    """Delete expired token blacklist rows and return the number removed."""

    cutoff = expired_before or datetime.now(UTC).replace(tzinfo=None)
    result = await session.execute(build_expired_token_blacklist_cleanup_statement(expired_before=cutoff))
    rowcount = cast(int | None, result.rowcount)
    return int(rowcount or 0)


__all__ = [
    "CRUDTokenBlacklist",
    "build_expired_token_blacklist_cleanup_statement",
    "crud_token_blacklist",
    "delete_expired_token_blacklist_entries",
]
