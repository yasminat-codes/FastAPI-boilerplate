"""Job payload serialization guidance and helpers.

ARQ serializes job arguments with :mod:`pickle` by default.  While pickle is
convenient, it creates coupling between the enqueuing process and the worker
process because both sides must share the exact same class definitions at the
exact same import paths.  It also makes it impossible to inspect queued jobs
with external tools.

Template serialization contract
-------------------------------
The template standardizes on **JSON-safe dictionaries** as the canonical job
payload format.  Every :class:`~src.app.core.worker.jobs.WorkerJob` receives a
:class:`~src.app.core.worker.jobs.JobEnvelope` whose ``payload`` field is a
``dict[str, Any]`` that *must* survive a round-trip through
:func:`json.dumps` / :func:`json.loads`.

What is safe to put in a job payload
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Strings, integers, floats, booleans, ``None``
- Lists and dicts composed of the above types
- ISO-8601 date/time strings (serialize on enqueue, parse on execute)
- UUIDs serialized as strings
- Pydantic models serialized with ``.model_dump(mode="json")``

What is *not* safe
~~~~~~~~~~~~~~~~~~
- Raw ``datetime``, ``date``, ``Decimal``, ``UUID``, ``bytes``, or ``Enum``
  objects (serialize them to their JSON-safe representation first)
- SQLAlchemy model instances (pass the primary key and re-fetch in the job)
- File handles, sockets, or any non-serializable runtime handle
- Large binary blobs (store in object storage and pass a reference instead)

Helpers in this module
~~~~~~~~~~~~~~~~~~~~~~
:func:`validate_json_safe` checks whether an arbitrary value survives a
JSON round-trip and raises a clear :class:`JobPayloadSerializationError` if it
does not.

:func:`safe_payload` is a convenience wrapper that validates and returns the
dict, useful as a guard before enqueuing.

:func:`serialize_for_envelope` accepts a Pydantic model or plain dict and
returns a validated JSON-safe dictionary suitable for
:meth:`~src.app.core.worker.jobs.WorkerJob.enqueue`.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


class JobPayloadSerializationError(TypeError):
    """Raised when a job payload is not JSON-round-trip safe."""


def validate_json_safe(value: Any) -> None:
    """Raise :class:`JobPayloadSerializationError` if *value* cannot survive a JSON round-trip.

    This intentionally uses the standard library :mod:`json` module so the
    check matches what external monitoring tools would see, not a custom
    encoder.
    """
    try:
        json.dumps(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise JobPayloadSerializationError(
            f"Job payload is not JSON-serializable: {exc}. "
            "Convert non-primitive values (datetime, UUID, Decimal, bytes, "
            "SQLAlchemy models) to their JSON-safe representations before "
            "enqueuing."
        ) from exc


def safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate *payload* is JSON-round-trip safe and return it.

    Raises :class:`JobPayloadSerializationError` if validation fails.
    """
    if not isinstance(payload, dict):
        raise JobPayloadSerializationError(
            f"Job payload must be a dict, got {type(payload).__name__}"
        )
    validate_json_safe(payload)
    return payload


def serialize_for_envelope(source: BaseModel | dict[str, Any]) -> dict[str, Any]:
    """Convert *source* into a validated JSON-safe dictionary.

    Accepts either a Pydantic model (serialized via ``.model_dump(mode="json")``)
    or a plain dictionary.  The result is validated with :func:`validate_json_safe`
    before being returned.

    Usage::

        class MyPayload(BaseModel):
            user_id: str
            created_at: datetime

        await SendEmailJob.enqueue(
            pool,
            payload=serialize_for_envelope(MyPayload(user_id="u1", created_at=now)),
        )
    """
    if isinstance(source, BaseModel):
        payload = source.model_dump(mode="json")
    elif isinstance(source, dict):
        payload = dict(source)
    else:
        raise JobPayloadSerializationError(
            f"Expected a Pydantic model or dict, got {type(source).__name__}"
        )

    validate_json_safe(payload)
    return payload


__all__ = [
    "JobPayloadSerializationError",
    "safe_payload",
    "serialize_for_envelope",
    "validate_json_safe",
]
