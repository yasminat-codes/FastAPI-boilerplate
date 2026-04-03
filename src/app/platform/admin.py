"""Canonical admin extension surface."""

from ..admin.initialize import create_admin_interface
from ..admin.views import PostCreateAdmin, register_admin_views

__all__ = ["PostCreateAdmin", "create_admin_interface", "register_admin_views"]
