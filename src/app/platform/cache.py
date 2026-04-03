"""Canonical cache surface."""

from typing import Any

from ..core.utils import cache as _legacy_cache

cache = _legacy_cache.cache
async_get_redis = _legacy_cache.async_get_redis

__all__ = ["async_get_redis", "cache"]


def __getattr__(name: str) -> Any:
    return getattr(_legacy_cache, name)
