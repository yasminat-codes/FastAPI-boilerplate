from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import cache
from typing import Any

from fastapi import FastAPI

from .api import build_api_router
from .platform.admin import create_admin_interface
from .platform.application import create_application, lifespan_factory
from .platform.config import settings


@cache
def get_admin_interface() -> Any:
    """Create the default admin interface once per process."""
    return create_admin_interface()


def create_app() -> FastAPI:
    """Build the template's default FastAPI application."""
    admin = get_admin_interface()
    api_router = build_api_router(settings)

    @asynccontextmanager
    async def lifespan_with_admin(app: FastAPI) -> AsyncGenerator[None, None]:
        default_lifespan = lifespan_factory(settings)

        async with default_lifespan(app):
            if admin:
                await admin.initialize()

            yield

    application = create_application(router=api_router, settings=settings, lifespan=lifespan_with_admin)

    if admin:
        application.mount(settings.CRUD_ADMIN_MOUNT_PATH, admin.app)

    return application


app = create_app()

__all__ = ["app", "create_app", "get_admin_interface"]
