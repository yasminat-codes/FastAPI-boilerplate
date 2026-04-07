"""Rate-limit response handling helpers for outbound HTTP requests.

Provides utilities for parsing rate-limit response headers and computing
appropriate backoff delays when a provider returns 429 Too Many Requests
or signals rate-limit pressure through standard headers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimitInfo:
    """Parsed rate-limit metadata from a provider response.

    Attributes:
        limit: Maximum requests allowed in the window (from X-RateLimit-Limit).
        remaining: Requests remaining in the current window (from X-RateLimit-Remaining).
        reset_seconds: Seconds until the rate limit window resets (from X-RateLimit-Reset or Retry-After).
        retry_after_seconds: Explicit Retry-After value if present.
    """

    limit: int | None = None
    remaining: int | None = None
    reset_seconds: float | None = None
    retry_after_seconds: float | None = None

    @property
    def is_exhausted(self) -> bool:
        """Whether the rate limit appears to be exhausted."""
        if self.remaining is not None:
            return self.remaining <= 0
        return False

    @property
    def is_approaching_limit(self) -> bool:
        """Whether the rate limit is approaching exhaustion (< 10% remaining)."""
        if self.limit is not None and self.remaining is not None and self.limit > 0:
            return self.remaining / self.limit < 0.1
        return False


def _safe_int(value: str | None) -> int | None:
    """Parse a string to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value.strip())
    except (ValueError, TypeError):
        return None


def _safe_float(value: str | None) -> float | None:
    """Parse a string to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value.strip())
    except (ValueError, TypeError):
        return None


def parse_rate_limit_headers(headers: dict[str, str] | Any) -> RateLimitInfo:
    """Parse standard rate-limit headers from an HTTP response.

    Supports the common header patterns used by most API providers:
    - X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset
    - RateLimit-Limit, RateLimit-Remaining, RateLimit-Reset (IETF draft)
    - Retry-After (seconds or date)

    Args:
        headers: Response headers as a dict-like mapping.

    Returns:
        Parsed rate-limit metadata with available fields populated.
    """
    header_map = {k.lower(): v for k, v in headers.items()} if hasattr(headers, "items") else {}

    limit = (
        _safe_int(header_map.get("x-ratelimit-limit"))
        or _safe_int(header_map.get("ratelimit-limit"))
    )
    remaining = (
        _safe_int(header_map.get("x-ratelimit-remaining"))
        or _safe_int(header_map.get("ratelimit-remaining"))
    )
    reset_value = (
        _safe_float(header_map.get("x-ratelimit-reset"))
        or _safe_float(header_map.get("ratelimit-reset"))
    )
    retry_after = _safe_float(header_map.get("retry-after"))

    return RateLimitInfo(
        limit=limit,
        remaining=remaining,
        reset_seconds=reset_value,
        retry_after_seconds=retry_after,
    )


def compute_rate_limit_delay(info: RateLimitInfo, *, default_delay: float = 1.0) -> float:
    """Compute the recommended delay based on parsed rate-limit metadata.

    Priority order:
    1. Retry-After header (most authoritative)
    2. Rate-limit reset timestamp
    3. Default delay fallback

    Args:
        info: Parsed rate-limit metadata.
        default_delay: Fallback delay if no rate-limit headers are available.

    Returns:
        Recommended delay in seconds.
    """
    if info.retry_after_seconds is not None and info.retry_after_seconds > 0:
        return info.retry_after_seconds
    if info.reset_seconds is not None and info.reset_seconds > 0:
        return info.reset_seconds
    return default_delay


__all__ = [
    "RateLimitInfo",
    "compute_rate_limit_delay",
    "parse_rate_limit_headers",
]
