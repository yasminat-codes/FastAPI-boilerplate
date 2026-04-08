"""Worker lifecycle hooks shared across ARQ processes."""

import asyncio
from contextlib import AsyncExitStack
from typing import Any

import uvloop

from ..config import SettingsProfile
from ..sentry import init_sentry_for_worker, shutdown_sentry
from ..setup import (
    close_database_engine,
    close_redis_cache_pool,
    close_redis_rate_limit_pool,
    create_redis_cache_pool,
    create_redis_rate_limit_pool,
    initialize_database_engine,
)
from ..utils import queue
from .logging import bind_job_log_context, clear_job_log_context, get_job_logger

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

WORKER_SETTINGS_CONTEXT_KEY = "settings"
WORKER_RESOURCE_STACK_CONTEXT_KEY = "resource_stack"


def _get_worker_settings(ctx: dict[str, Any]) -> SettingsProfile | None:
    settings = ctx.get(WORKER_SETTINGS_CONTEXT_KEY)
    if isinstance(settings, SettingsProfile):
        return settings

    return None


def _get_resource_stack(ctx: dict[str, Any]) -> AsyncExitStack | None:
    resource_stack = ctx.get(WORKER_RESOURCE_STACK_CONTEXT_KEY)
    if isinstance(resource_stack, AsyncExitStack):
        return resource_stack

    return None


async def startup(ctx: dict[str, Any]) -> None:
    resource_stack = AsyncExitStack()
    ctx[WORKER_RESOURCE_STACK_CONTEXT_KEY] = resource_stack

    try:
        settings = _get_worker_settings(ctx)

        if "redis" in ctx:
            queue.pool = ctx["redis"]
            resource_stack.callback(setattr, queue, "pool", None)

        if settings is not None:
            await initialize_database_engine(settings)
            resource_stack.push_async_callback(close_database_engine)

            await create_redis_cache_pool(settings)
            resource_stack.push_async_callback(close_redis_cache_pool)

            await create_redis_rate_limit_pool(settings)
            resource_stack.push_async_callback(close_redis_rate_limit_pool)

            if settings.SENTRY_ENABLE:
                init_sentry_for_worker(settings)
                resource_stack.push_async_callback(shutdown_sentry, settings)

        get_job_logger().info("Worker started")
    except Exception:
        try:
            await resource_stack.aclose()
        finally:
            ctx.pop(WORKER_RESOURCE_STACK_CONTEXT_KEY, None)
        raise


async def shutdown(ctx: dict[str, Any]) -> None:
    resource_stack = _get_resource_stack(ctx)
    if resource_stack is not None:
        try:
            await resource_stack.aclose()
        finally:
            ctx.pop(WORKER_RESOURCE_STACK_CONTEXT_KEY, None)

    get_job_logger().info("Worker stopped")


async def on_job_start(ctx: dict[str, Any]) -> None:
    clear_job_log_context()
    bind_job_log_context(ctx=ctx)
    get_job_logger(ctx=ctx).info("Job started")


async def on_job_end(ctx: dict[str, Any]) -> None:
    get_job_logger(ctx=ctx).info("Job completed")
    clear_job_log_context()
