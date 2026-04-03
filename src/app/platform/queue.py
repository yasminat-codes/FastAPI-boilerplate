"""Canonical queue surface."""

from typing import Any

from ..core.utils import queue as _legacy_queue

__all__: list[str] = []


def __getattr__(name: str) -> Any:
    return getattr(_legacy_queue, name)
