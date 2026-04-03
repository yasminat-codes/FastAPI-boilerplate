"""Canonical rate-limiting surface."""

from typing import Any

from ..core.utils import rate_limit as _legacy_rate_limit

RateLimiter = _legacy_rate_limit.RateLimiter
rate_limiter = _legacy_rate_limit.rate_limiter

__all__ = ["RateLimiter", "rate_limiter"]


def __getattr__(name: str) -> Any:
    return getattr(_legacy_rate_limit, name)
