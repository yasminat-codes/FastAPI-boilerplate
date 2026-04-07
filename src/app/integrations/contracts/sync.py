"""Sync checkpoint and cursor storage patterns for provider data synchronization.

This module provides reusable helper patterns that sit on top of the
``IntegrationSyncCheckpoint`` table for managing provider data synchronization.

The patterns here address:

- **Cursor management**: Different providers use different pagination schemes
  (opaque cursors, offset/limit, timestamp-based, ID-based). SyncCursor
  abstracts these differences.
- **Checkpoint persistence**: Syncs can be interrupted. The checkpoint table
  stores cursor state so you can resume from where you left off.
- **Progress tracking**: SyncProgress tracks how many items have been fetched
  and processed during a sync run.
- **Strategy selection**: Different providers benefit from different sync
  strategies. SyncStrategy helps you choose the right one.

## Choosing a Sync Strategy

### Cursor-Based Sync (Recommended)

Use when the provider returns an opaque cursor for pagination.

**Pros:**
- Most efficient: directly tells you where to resume
- Handles additions, updates, and deletes naturally
- Common in modern REST APIs

**Cons:**
- Cursor lifetime is provider-dependent (usually 5 minutes to 24 hours)
- If cursor expires, you may need to fall back to full sync or timestamp-based

**Providers using cursor-based:**
- Slack (returns next_cursor for list operations)
- Discord (uses cursor pagination)
- Linear (cursor-based pagination)

Example:

    cursor = SyncCursor(cursor_value="abc123xyz")
    # Next sync fetches from cursor: /api/v1/messages?cursor=abc123xyz

### Timestamp-Based Sync

Use when the provider supports filtering by modification time but not cursors.

**Pros:**
- Simple to understand
- Works well for append-only or update-heavy APIs
- Cursor doesn't expire

**Cons:**
- Doesn't handle deletes automatically (need separate delete sync)
- Requires provider to expose modified_at or similar
- Assumes accurate server time across retries

**Providers using timestamp-based:**
- GitHub (can fetch PRs modified after a timestamp)
- Jira (supports updated >= filter)
- Salesforce (supports LastModifiedDate filtering)

Example:

    cursor = SyncCursor(last_modified_at=datetime(2024, 1, 15, 10, 30, tzinfo=UTC))
    # Next sync fetches: /api/v1/items?modified_after=2024-01-15T10:30:00Z

### Offset-Based Sync

Use when the provider only supports offset/limit pagination.

**Pros:**
- Very simple, supported by almost all APIs
- Good for APIs that don't expose cursors

**Cons:**
- Inefficient: if new items are inserted during pagination, you get duplicates
- Doesn't scale well to large datasets
- Requires careful handling of page size changes

**Providers using offset-based:**
- Older REST APIs (many legacy systems)
- CSV/JSON exports with limit/offset support

Example:

    cursor = SyncCursor(page_number=0)
    # Next sync fetches: /api/v1/items?offset=0&limit=100

### Full Sync

Use when you don't support incremental sync (or as a fallback).

**Pros:**
- Simple to implement
- Guarantees consistency (you see everything)

**Cons:**
- Very expensive at scale
- Not suitable for real-time or frequent syncs
- Only use for small datasets or low-frequency full refreshes

## Checkpoint and Cursor State

Cursor state is stored as JSON in the ``IntegrationSyncCheckpoint.cursor_state``
column. This JSON can contain:

- The opaque cursor from the provider
- Page numbers for offset-based sync
- Last-fetched timestamps for timestamp-based sync
- High-water marks for ID-based sync
- Provider-specific metadata

Example cursor_state for a Slack-like cursor-based API:

    {
      "cursor_value": "dXNlcl9pZDo1",
      "last_cursor_was_empty": false
    }

Example cursor_state for timestamp-based API:

    {
      "last_modified_at": "2024-01-15T10:30:00Z",
      "items_fetched": 150
    }

Example cursor_state for offset-based API:

    {
      "page_number": 3,
      "page_size": 100
    }

The ``SyncCursor`` dataclass handles serialization/deserialization:

    # Deserialize from checkpoint
    state_dict = checkpoint.cursor_state or {}
    cursor = SyncCursor.from_cursor_state(state_dict)

    # Use cursor to fetch next page
    page = await operation.fetch_page(cursor)

    # Serialize back to checkpoint
    checkpoint.cursor_state = page.next_cursor.to_cursor_state()

## Implementing a Provider-Specific SyncOperation

A SyncOperation encapsulates the details of fetching and processing data
from a specific provider:

    from typing import Generic, TypeVar
    from .sync import SyncOperation, SyncPage, SyncCursor, SyncStrategy

    ItemType = TypeVar("ItemType")

    class SlackMessageSync(SyncOperation):
        def __init__(self, client: TemplateHttpClient, channel_id: str):
            self._client = client
            self._channel_id = channel_id

        @property
        def provider_name(self) -> str:
            return "slack"

        @property
        def sync_scope(self) -> str:
            return f"channel:{self._channel_id}:messages"

        @property
        def strategy(self) -> SyncStrategy:
            return SyncStrategy.CURSOR_BASED

        async def fetch_page(self, cursor: SyncCursor) -> SyncPage[dict[str, Any]]:
            params = {"channel": self._channel_id, "limit": 100}
            if cursor.cursor_value:
                params["cursor"] = cursor.cursor_value

            response = await self._client.get("/api/conversations.history", params=params)
            data = response.json()

            messages = data.get("messages", [])
            next_cursor_value = data.get("response_metadata", {}).get("next_cursor")

            return SyncPage(
                items=messages,
                next_cursor=SyncCursor(cursor_value=next_cursor_value) if next_cursor_value else None,
                has_more=data.get("has_more", False),
                total_count=None,
                fetched_at=datetime.now(UTC),
            )

        async def process_page(self, page: SyncPage) -> int:
            count = 0
            for message in page.items:
                await self._db.insert_or_update_message(
                    channel_id=self._channel_id,
                    message_id=message["ts"],
                    text=message.get("text"),
                    user_id=message.get("user"),
                    timestamp=message.get("ts"),
                )
                count += 1
            return count

## Handling Interrupted Syncs (Checkpoint Recovery)

The checkpoint table allows you to resume a sync that was interrupted:

    from src.app.core.db.integration_sync_checkpoint import (
        IntegrationSyncCheckpoint,
        IntegrationSyncCheckpointStatus,
    )

    async def resume_sync(db_session, checkpoint_id: int, operation: SyncOperation):
        # Load checkpoint from database
        checkpoint = await db_session.get(IntegrationSyncCheckpoint, checkpoint_id)

        # Reconstruct cursor from stored state
        cursor_state = checkpoint.cursor_state or {}
        cursor = SyncCursor.from_cursor_state(cursor_state)

        # Resume fetching from cursor
        progress = SyncProgress(
            provider_name=operation.provider_name,
            sync_scope=operation.sync_scope,
            strategy=operation.strategy,
            pages_fetched=0,
            items_processed=0,
            started_at=checkpoint.last_synced_at or datetime.now(UTC),
            current_cursor=cursor,
            is_complete=False,
            error=None,
        )

        # Continue from where we left off
        current_cursor = cursor
        while current_cursor is not None:
            try:
                page = await operation.fetch_page(current_cursor)
                items_count = await operation.process_page(page)

                progress.pages_fetched += 1
                progress.items_processed += items_count
                progress.current_cursor = page.next_cursor
                current_cursor = page.next_cursor

                # Update checkpoint with progress
                checkpoint.cursor_state = page.next_cursor.to_cursor_state() if page.next_cursor else None
                checkpoint.last_synced_at = datetime.now(UTC)
                db_session.add(checkpoint)
                await db_session.commit()

            except Exception as e:
                progress.error = str(e)
                progress.is_complete = False
                raise

        progress.is_complete = True
        return progress

## Handling Provider API Pagination Patterns

Different providers expose pagination differently:

**Slack-style: Opaque cursor with has_more flag**

    response = await client.get("/api/conversations.list")
    data = response.json()
    # {
    #   "channels": [...],
    #   "response_metadata": {"next_cursor": "abc123xyz"},
    #   "has_more": true
    # }

**GitHub-style: Link header with rel="next"**

    response = await client.get("/repos/owner/repo/issues")
    # Link header: <https://api.github.com/...?page=2>; rel="next"
    next_url = parse_link_header(response.headers["Link"])["next"]["url"]
    # Extract page number or cursor from next_url

**Stripe-style: has_more flag with object IDs**

    response = await client.get("/v1/customers")
    data = response.json()
    # {
    #   "object": "list",
    #   "data": [...],
    #   "has_more": true,
    #   "url": "/v1/customers?starting_after=cus_xxx"
    # }

**Jira-style: startAt offset with isLastPage flag**

    response = await client.get("/rest/api/3/search")
    data = response.json()
    # {
    #   "issues": [...],
    #   "startAt": 0,
    #   "maxResults": 50,
    #   "total": 250,
    #   "isLastPage": false
    # }

## Best Practices for Sync Operations

### Batch Sizing

Balance between API rate limits and sync latency:

    # Too small: lots of roundtrips, slower sync
    page_size = 10  # Bad for most APIs

    # Good: 50-200 items per request (common default)
    page_size = 100

    # Too large: large responses, timeout risk, backpressure
    page_size = 5000  # Only if you have fast processing

Guidelines:
- Check provider documentation for recommended page sizes
- Monitor response time and network throughput
- Start with 100-200 items and adjust based on observed latency

### Rate Limiting During Sync

Respect provider rate limits to avoid getting blocked:

    from tenacity import retry, wait_exponential, stop_after_attempt

    @retry(wait=wait_exponential(multiplier=1, min=2, max=60), stop=stop_after_attempt(3))
    async def fetch_with_backoff(self, cursor: SyncCursor) -> SyncPage:
        try:
            return await self.fetch_page(cursor)
        except HttpRateLimitError as e:
            # Tenacity will automatically retry with exponential backoff
            raise

Or implement adaptive backoff:

    import time

    async def fetch_page_with_adaptive_backoff(self, cursor: SyncCursor) -> SyncPage:
        while True:
            try:
                return await self.fetch_page(cursor)
            except HttpRateLimitError as e:
                retry_after = int(e.response.headers.get("Retry-After", "60"))
                logger.info("rate_limited", retry_after=retry_after)
                await asyncio.sleep(retry_after)

### Handling Backpressure

If your processing is slower than fetching, implement backpressure:

    from asyncio import Semaphore

    class RateLimitedSync:
        def __init__(self, max_concurrent_items: int = 1000):
            self.semaphore = Semaphore(max_concurrent_items)

        async def fetch_page(self, cursor: SyncCursor) -> SyncPage:
            # Wait if we're too far ahead in processing
            async with self.semaphore:
                return await self._fetch_from_provider(cursor)

Alternatively, slow down fetching if queue grows:

    queue_size = len(pending_items)
    if queue_size > 1000:
        await asyncio.sleep(0.5)  # Slow down fetching
    elif queue_size > 500:
        await asyncio.sleep(0.1)  # Light backpressure

## Monitoring Sync Health

Track sync performance over time:

    from dataclasses import replace

    async def execute_sync_with_monitoring(
        operation: SyncOperation,
        checkpoint: IntegrationSyncCheckpoint,
        metrics: MetricsCollector,
    ) -> SyncProgress:
        progress = SyncProgress(
            provider_name=operation.provider_name,
            sync_scope=operation.sync_scope,
            strategy=operation.strategy,
            pages_fetched=0,
            items_processed=0,
            started_at=datetime.now(UTC),
            current_cursor=SyncCursor.from_cursor_state(checkpoint.cursor_state),
            is_complete=False,
            error=None,
        )

        try:
            cursor = progress.current_cursor
            while cursor is not None:
                page = await operation.fetch_page(cursor)
                count = await operation.process_page(page)

                progress = replace(
                    progress,
                    pages_fetched=progress.pages_fetched + 1,
                    items_processed=progress.items_processed + count,
                    current_cursor=page.next_cursor,
                )

                # Emit metrics
                metrics.increment("sync.pages_fetched", tags={"provider": operation.provider_name})
                metrics.increment("sync.items_processed", value=count, tags={"provider": operation.provider_name})

                cursor = page.next_cursor

            progress = replace(progress, is_complete=True)
            metrics.timing("sync.duration_seconds", (datetime.now(UTC) - progress.started_at).total_seconds())

        except Exception as e:
            progress = replace(progress, error=str(e))
            metrics.increment("sync.failed", tags={"provider": operation.provider_name})
            raise

        return progress

See also ``src/app/integrations/contracts/secrets.py`` for patterns on managing
provider credentials during sync operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable


class SyncStrategy(StrEnum):
    """Strategy for iterating through provider data.

    Choose the strategy that best matches the provider's pagination API:

    - CURSOR_BASED: Provider returns an opaque cursor for resuming pagination
    - TIMESTAMP_BASED: Filter by modification time to get only recent changes
    - OFFSET_BASED: Use offset/limit pagination (less efficient)
    - FULL_SYNC: Fetch everything from scratch (only for small datasets)
    """

    CURSOR_BASED = "cursor_based"
    TIMESTAMP_BASED = "timestamp_based"
    OFFSET_BASED = "offset_based"
    FULL_SYNC = "full_sync"


@dataclass(frozen=True)
class SyncCursor:
    """Opaque cursor and position markers for pagination resumption.

    Encapsulates the different pagination schemes used by providers:

    - cursor_value: Opaque cursor string (Slack, Discord, etc.)
    - page_number: Offset-based page number (Jira, SQL OFFSET)
    - last_modified_at: Timestamp for timestamp-based sync (GitHub, Salesforce)
    - high_water_mark: Last-seen ID for ID-based resume (some APIs)
    - extra: Provider-specific cursor metadata stored as JSON

    Attributes:
        cursor_value: Opaque pagination cursor from provider
        page_number: For offset/limit pagination, the page number (0-indexed)
        last_modified_at: For timestamp-based sync, the last modification time fetched
        high_water_mark: For ID-based sync, the last seen ID or sort key
        extra: Provider-specific metadata (e.g., {"include_deleted": true})
    """

    cursor_value: str | None = None
    page_number: int | None = None
    last_modified_at: datetime | None = None
    high_water_mark: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_cursor_state(cls, state: dict[str, Any] | None) -> SyncCursor:
        """Deserialize cursor from checkpoint JSON.

        Args:
            state: Dictionary loaded from IntegrationSyncCheckpoint.cursor_state

        Returns:
            Reconstructed SyncCursor. If state is None, returns a new cursor
            with all fields as None (start from beginning).
        """
        if state is None:
            return cls()

        last_modified_at = state.get("last_modified_at")
        if last_modified_at and isinstance(last_modified_at, str):
            last_modified_at = datetime.fromisoformat(last_modified_at)

        return cls(
            cursor_value=state.get("cursor_value"),
            page_number=state.get("page_number"),
            last_modified_at=last_modified_at,
            high_water_mark=state.get("high_water_mark"),
            extra=state.get("extra", {}),
        )

    def to_cursor_state(self) -> dict[str, Any]:
        """Serialize cursor to checkpoint JSON.

        Returns:
            Dictionary suitable for storing in IntegrationSyncCheckpoint.cursor_state
        """
        result: dict[str, Any] = {}

        if self.cursor_value is not None:
            result["cursor_value"] = self.cursor_value

        if self.page_number is not None:
            result["page_number"] = self.page_number

        if self.last_modified_at is not None:
            result["last_modified_at"] = self.last_modified_at.isoformat()

        if self.high_water_mark is not None:
            result["high_water_mark"] = self.high_water_mark

        if self.extra:
            result["extra"] = self.extra

        return result


T = TypeVar("T")


@dataclass(frozen=True)
class SyncPage(Generic[T]):
    """One page of data fetched from a provider API.

    Attributes:
        items: The actual data items from this page
        next_cursor: Cursor to fetch the next page, or None if no more pages
        has_more: Whether more data is available (some APIs don't provide next_cursor)
        total_count: Total count of all items if available, None if unknown
        fetched_at: When this page was fetched
    """

    items: list[T]
    next_cursor: SyncCursor | None
    has_more: bool
    total_count: int | None
    fetched_at: datetime


@runtime_checkable
class SyncOperation(Protocol):
    """Protocol for a provider-specific sync operation.

    Implementers encapsulate the details of fetching and processing data
    from a particular provider or provider endpoint.

    Example:

        class SlackChannelMessageSync(SyncOperation):
            def __init__(self, client: TemplateHttpClient, channel_id: str):
                self._client = client
                self._channel_id = channel_id

            @property
            def provider_name(self) -> str:
                return "slack"

            @property
            def sync_scope(self) -> str:
                return f"channel:{self._channel_id}:messages"

            @property
            def strategy(self) -> SyncStrategy:
                return SyncStrategy.CURSOR_BASED

            async def fetch_page(self, cursor: SyncCursor) -> SyncPage:
                params = {"channel": self._channel_id, "limit": 100}
                if cursor.cursor_value:
                    params["cursor"] = cursor.cursor_value
                response = await self._client.get("/api/conversations.history", params=params)
                ...

            async def process_page(self, page: SyncPage) -> int:
                # Database inserts, updates, etc.
                ...
    """

    @property
    def provider_name(self) -> str:
        """Name of the integration provider (e.g., "slack", "stripe").

        Used for logging, monitoring, and checkpoint storage.
        """
        ...

    @property
    def sync_scope(self) -> str:
        """Unique identifier for what is being synced.

        Examples: "channel:C123:messages", "users", "account:12345:invoices"

        Used to allow multiple concurrent syncs for the same provider
        (e.g., syncing different channels independently).
        """
        ...

    @property
    def strategy(self) -> SyncStrategy:
        """Which pagination strategy this operation uses."""
        ...

    async def fetch_page(self, cursor: SyncCursor) -> SyncPage:
        """Fetch one page of data from the provider API.

        Args:
            cursor: Where to resume pagination from. Use cursor fields
                relevant to the strategy (e.g., cursor.cursor_value for
                CURSOR_BASED, cursor.page_number for OFFSET_BASED).

        Returns:
            SyncPage containing fetched items and the next cursor to resume from
        """
        ...

    async def process_page(self, page: SyncPage) -> int:
        """Process and persist one page of data.

        Typically inserts or updates records in the database. Called after
        fetch_page() returns successfully.

        Args:
            page: The fetched page to process

        Returns:
            Number of items processed. Used for progress tracking.
        """
        ...


@dataclass(frozen=True)
class SyncProgress:
    """Tracks progress of an in-flight or completed sync operation.

    Attributes:
        provider_name: Provider being synced
        sync_scope: What is being synced
        strategy: Which pagination strategy is used
        pages_fetched: Number of pages successfully fetched
        items_processed: Total items processed across all pages
        started_at: When the sync started
        current_cursor: The cursor for resuming from current position
        is_complete: Whether the sync finished successfully
        error: Error message if sync failed
    """

    provider_name: str
    sync_scope: str
    strategy: SyncStrategy
    pages_fetched: int
    items_processed: int
    started_at: datetime
    current_cursor: SyncCursor | None
    is_complete: bool
    error: str | None = None

    @property
    def elapsed_seconds(self) -> float:
        """How many seconds have elapsed since sync started."""
        return (datetime.now(UTC) - self.started_at).total_seconds()

    @property
    def items_per_second(self) -> float:
        """Items processed per second (if started, 0 if no elapsed time)."""
        if self.elapsed_seconds == 0:
            return 0.0
        return self.items_processed / self.elapsed_seconds


__all__ = [
    "SyncStrategy",
    "SyncCursor",
    "SyncPage",
    "SyncOperation",
    "SyncProgress",
]
