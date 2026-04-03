"""Canonical platform boundary for runtime, security, persistence, and shared services."""

from .application import create_application, lifespan_factory
from .config import Settings, settings

__all__ = ["Settings", "create_application", "lifespan_factory", "settings"]
