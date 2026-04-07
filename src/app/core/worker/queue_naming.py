"""Queue naming conventions for the template worker platform.

The template uses a hierarchical queue naming scheme so that jobs are grouped
by purpose and operators can identify queue traffic at a glance in Redis
monitoring tools.

Naming scheme
-------------
``<prefix>:<scope>:<purpose>``

- **prefix** – shared namespace prefix, defaults to ``arq``.
- **scope** – logical boundary such as ``platform``, ``webhooks``, ``client``,
  or a provider name.
- **purpose** – what kind of work the queue carries, e.g. ``default``,
  ``email``, ``sync``, ``ingest``.

Examples::

    arq:platform:default     # template-internal default queue
    arq:webhooks:ingest      # webhook intake processing
    arq:client:email         # client-specific email delivery
    arq:client:reports       # client-specific report generation
    arq:integrations:sync    # outbound integration sync jobs

Rules enforced by this module
-----------------------------
1. Queue names must contain only lowercase ASCII letters, digits, colons, and
   hyphens.
2. Queue names must have at least two colon-separated segments.
3. Queue names must not exceed 128 characters.
4. The ``platform`` scope is reserved for template-internal queues.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

_VALID_QUEUE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9:\-]*[a-z0-9]$")
_MAX_QUEUE_NAME_LENGTH = 128
_MIN_SEGMENTS = 2

# Reserved scopes that should only be used by the template itself.
RESERVED_SCOPES: frozenset[str] = frozenset({"platform"})


class QueueNameError(ValueError):
    """Raised when a queue name violates the template naming conventions."""


def validate_queue_name(name: str) -> str:
    """Validate *name* against the template queue naming rules.

    Returns the validated name on success, raises :class:`QueueNameError` on
    violation.
    """
    if not name or not name.strip():
        raise QueueNameError("Queue name must not be empty")

    if len(name) > _MAX_QUEUE_NAME_LENGTH:
        raise QueueNameError(f"Queue name exceeds {_MAX_QUEUE_NAME_LENGTH} characters: {name!r}")

    if not _VALID_QUEUE_NAME_RE.match(name):
        raise QueueNameError(
            f"Queue name contains invalid characters: {name!r}. "
            "Only lowercase ASCII letters, digits, colons, and hyphens are allowed."
        )

    segments = name.split(":")
    if len(segments) < _MIN_SEGMENTS:
        raise QueueNameError(
            f"Queue name must have at least {_MIN_SEGMENTS} colon-separated segments: {name!r}"
        )

    return name


def is_reserved_scope(scope: str) -> bool:
    """Return whether *scope* is reserved for template-internal use."""
    return scope.lower() in RESERVED_SCOPES


@dataclass(frozen=True, slots=True)
class QueueNamespace:
    """Helper for building consistent queue names within a scope.

    Usage::

        webhooks = QueueNamespace(prefix="arq", scope="webhooks")
        webhooks.queue("ingest")    # -> "arq:webhooks:ingest"
        webhooks.queue("retry")     # -> "arq:webhooks:retry"
    """

    prefix: str = "arq"
    scope: str = "client"

    # Well-known scopes provided for discoverability.
    SCOPE_PLATFORM: ClassVar[str] = "platform"
    SCOPE_WEBHOOKS: ClassVar[str] = "webhooks"
    SCOPE_CLIENT: ClassVar[str] = "client"
    SCOPE_INTEGRATIONS: ClassVar[str] = "integrations"

    def queue(self, purpose: str) -> str:
        """Build and validate a queue name for *purpose* within this namespace."""
        name = f"{self.prefix}:{self.scope}:{purpose}"
        return validate_queue_name(name)

    def __post_init__(self) -> None:
        if not self.prefix or not self.prefix.strip():
            raise QueueNameError("Queue namespace prefix must not be empty")
        if not self.scope or not self.scope.strip():
            raise QueueNameError("Queue namespace scope must not be empty")


# Pre-built namespaces for common scopes.
platform_queues = QueueNamespace(prefix="arq", scope="platform")
webhook_queues = QueueNamespace(prefix="arq", scope="webhooks")
client_queues = QueueNamespace(prefix="arq", scope="client")
integration_queues = QueueNamespace(prefix="arq", scope="integrations")

# The template default queue name follows the convention.
DEFAULT_QUEUE_NAME: str = platform_queues.queue("default")

__all__ = [
    "DEFAULT_QUEUE_NAME",
    "QueueNameError",
    "QueueNamespace",
    "RESERVED_SCOPES",
    "client_queues",
    "integration_queues",
    "is_reserved_scope",
    "platform_queues",
    "validate_queue_name",
    "webhook_queues",
]
