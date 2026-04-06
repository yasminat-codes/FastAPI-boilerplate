from datetime import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.db.crud_token_blacklist import (
    build_expired_token_blacklist_cleanup_statement,
    delete_expired_token_blacklist_entries,
)
from src.scripts.cleanup_token_blacklist import cleanup_expired_token_blacklist_entries


def test_build_expired_token_blacklist_cleanup_statement_targets_expired_rows() -> None:
    cutoff = datetime(2026, 4, 6, 12, 30, 0)
    statement = build_expired_token_blacklist_cleanup_statement(expired_before=cutoff)

    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))

    assert "DELETE FROM token_blacklist" in compiled
    assert "expires_at <" in compiled
    assert "2026-04-06" in compiled


@pytest.mark.asyncio
async def test_delete_expired_token_blacklist_entries_returns_rowcount() -> None:
    cutoff = datetime(2026, 4, 6, 12, 30, 0)
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = SimpleNamespace(rowcount=7)

    deleted = await delete_expired_token_blacklist_entries(cast(AsyncSession, session), expired_before=cutoff)

    assert deleted == 7
    statement = session.execute.await_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "2026-04-06 12:30:00" in compiled


@pytest.mark.asyncio
async def test_cleanup_script_delegates_to_shared_delete_helper() -> None:
    cutoff = datetime(2026, 4, 6, 12, 30, 0)
    session = object()

    with patch(
        "src.scripts.cleanup_token_blacklist.delete_expired_token_blacklist_entries",
        new=AsyncMock(return_value=3),
    ) as delete_mock:
        deleted = await cleanup_expired_token_blacklist_entries(
            cast(AsyncSession, session),
            expired_before=cutoff,
        )

    assert deleted == 3
    delete_mock.assert_awaited_once_with(cast(AsyncSession, session), expired_before=cutoff)
