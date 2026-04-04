"""Reusable helpers for raw-body webhook verification flows."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request

RAW_REQUEST_BODY_STATE_KEY = "raw_request_body"


async def read_raw_request_body(request: Request) -> bytes:
    """Read and cache the exact inbound request body for signature verification."""

    cached_body = getattr(request.state, RAW_REQUEST_BODY_STATE_KEY, None)
    if isinstance(cached_body, bytes):
        return cached_body

    raw_body = await request.body()
    setattr(request.state, RAW_REQUEST_BODY_STATE_KEY, raw_body)
    return raw_body


def parse_raw_json_body(raw_body: bytes) -> Any:
    """Parse a raw request body as JSON after signature verification succeeds."""

    return json.loads(raw_body)


__all__ = ["RAW_REQUEST_BODY_STATE_KEY", "parse_raw_json_body", "read_raw_request_body"]
