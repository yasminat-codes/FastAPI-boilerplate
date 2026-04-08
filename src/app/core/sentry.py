"""Hardened Sentry SDK integration with filtering, scrubbing, and tagging helpers.

This module provides:
- Hardened SDK initialization for both API and worker processes
- Event filtering by exception type and logger name
- Recursive field scrubbing reusing the template's log-redaction patterns
- Automatic request/correlation ID tag injection on every event
- Context-aware transaction sampling for health, webhook, and worker endpoints
- Release tracking with optional prefix namespacing
- Typed context helpers for users, requests, and background jobs
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .config import SentrySettings
from .log_redaction import normalize_redaction_field_name, should_redact_field
from .request_context import get_current_correlation_id, get_current_request_id

# ---------------------------------------------------------------------------
# Default scrub field names — exact match after normalisation
# ---------------------------------------------------------------------------
DEFAULT_SENTRY_SCRUB_FIELDS: frozenset[str] = frozenset({
    "password",
    "secret",
    "token",
    "authorization",
    "cookie",
    "session",
    "api_key",
    "apikey",
    "dsn",
    "private_key",
    "privatekey",
    "credit_card",
    "creditcard",
    "ssn",
    "access_token",
    "refresh_token",
    "bearer",
    "x-api-key",
    "api-key",
    "auth",
    "passwd",
})

# Substring patterns matched against normalised field names
DEFAULT_SENTRY_SCRUB_SUBSTRINGS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "authorization",
    "credential",
    "cookie",
    "bearer",
    "private",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------
@dataclass
class SentryConfig:
    """Configuration object built from ``SentrySettings`` for SDK initialisation."""

    enabled: bool
    dsn: str | None
    environment: str
    release: str | None
    debug: bool
    attach_stacktrace: bool
    send_default_pii: bool
    max_breadcrumbs: int
    traces_sample_rate: float
    profiles_sample_rate: float
    flush_timeout_seconds: int
    server_name: str | None
    error_sample_rate: float
    health_endpoint_sample_rate: float
    webhook_sample_rate: float | None
    worker_sample_rate: float | None
    ignored_exceptions: list[str] = field(default_factory=list)
    ignored_loggers: list[str] = field(default_factory=list)
    scrub_fields: set[str] = field(default_factory=set)
    scrub_replacement: str = "[Filtered]"

    @classmethod
    def from_settings(cls, settings: SentrySettings) -> SentryConfig:
        """Build a ``SentryConfig`` from application settings."""
        return cls(
            enabled=settings.SENTRY_ENABLE,
            dsn=settings.SENTRY_DSN.get_secret_value() if settings.SENTRY_DSN else None,
            environment=settings.SENTRY_ENVIRONMENT,
            release=resolve_sentry_release(settings),
            debug=settings.SENTRY_DEBUG,
            attach_stacktrace=settings.SENTRY_ATTACH_STACKTRACE,
            send_default_pii=settings.SENTRY_SEND_DEFAULT_PII,
            max_breadcrumbs=settings.SENTRY_MAX_BREADCRUMBS,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            profiles_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
            flush_timeout_seconds=settings.SENTRY_FLUSH_TIMEOUT_SECONDS,
            server_name=settings.SENTRY_SERVER_NAME,
            error_sample_rate=settings.SENTRY_ERROR_SAMPLE_RATE,
            health_endpoint_sample_rate=settings.SENTRY_HEALTH_ENDPOINT_SAMPLE_RATE,
            webhook_sample_rate=settings.SENTRY_WEBHOOK_SAMPLE_RATE,
            worker_sample_rate=settings.SENTRY_WORKER_SAMPLE_RATE,
            ignored_exceptions=list(settings.SENTRY_IGNORED_EXCEPTIONS),
            ignored_loggers=list(settings.SENTRY_IGNORED_LOGGERS),
            scrub_fields=set(settings.SENTRY_SCRUB_FIELDS),
            scrub_replacement=settings.SENTRY_SCRUB_REPLACEMENT,
        )


# ---------------------------------------------------------------------------
# Release helper
# ---------------------------------------------------------------------------
def resolve_sentry_release(settings: SentrySettings) -> str | None:
    """Resolve Sentry release string, with optional prefix namespacing.

    If ``SENTRY_RELEASE_PREFIX`` is set the release is formatted as
    ``<prefix>@<version>``, which namespaces releases when multiple services
    report into the same Sentry project.
    """
    if settings.SENTRY_RELEASE is None:
        return None

    if not settings.SENTRY_RELEASE_PREFIX:
        return settings.SENTRY_RELEASE

    return f"{settings.SENTRY_RELEASE_PREFIX}@{settings.SENTRY_RELEASE}"


# ---------------------------------------------------------------------------
# SDK state check
# ---------------------------------------------------------------------------
def is_sentry_enabled() -> bool:
    """Return whether the Sentry SDK is currently initialised."""
    try:
        import sentry_sdk  # noqa: F811

        client = sentry_sdk.get_client()
        return client.is_active()
    except (ImportError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Event scrubbing internals
# ---------------------------------------------------------------------------
def _build_scrub_field_sets(scrub_fields: set[str]) -> tuple[set[str], tuple[str, ...]]:
    """Build normalised exact-match and substring-match sets for field scrubbing."""
    normalised_exact = {normalize_redaction_field_name(f) for f in scrub_fields}
    return normalised_exact, DEFAULT_SENTRY_SCRUB_SUBSTRINGS


def _scrub_event_data(
    data: Any,
    *,
    exact_fields: set[str],
    substring_fields: tuple[str, ...],
    replacement: str,
    field_name: str | None = None,
) -> Any:
    """Recursively scrub sensitive values from event data."""
    if field_name is not None and should_redact_field(
        field_name,
        exact_fields=exact_fields,
        substring_fields=substring_fields,
    ):
        return replacement

    if isinstance(data, dict):
        return {
            key: _scrub_event_data(
                value,
                exact_fields=exact_fields,
                substring_fields=substring_fields,
                replacement=replacement,
                field_name=str(key),
            )
            for key, value in data.items()
        }

    if isinstance(data, list):
        return [
            _scrub_event_data(
                item,
                exact_fields=exact_fields,
                substring_fields=substring_fields,
                replacement=replacement,
            )
            for item in data
        ]

    if isinstance(data, tuple):
        return tuple(
            _scrub_event_data(
                item,
                exact_fields=exact_fields,
                substring_fields=substring_fields,
                replacement=replacement,
            )
            for item in data
        )

    return data


# ---------------------------------------------------------------------------
# Event filter
# ---------------------------------------------------------------------------
class SentryEventFilter:
    """Filter and scrub Sentry events before they leave the process.

    Used as the ``before_send`` and ``before_send_transaction`` callbacks
    during SDK initialisation.
    """

    def __init__(self, config: SentryConfig) -> None:
        self.config = config
        self._ignored_exceptions: frozenset[str] = frozenset(config.ignored_exceptions)
        self._ignored_loggers: frozenset[str] = frozenset(config.ignored_loggers)
        self._scrub_exact, self._scrub_substrings = _build_scrub_field_sets(config.scrub_fields)

    # -- callbacks ---------------------------------------------------------

    def before_send(self, event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
        """Filter and scrub an error event before sending to Sentry."""
        # Drop events from ignored exception types
        exc_info = hint.get("exc_info")
        if exc_info is not None:
            exc_type = exc_info[0]
            if exc_type is not None:
                exc_type_name = exc_type.__name__
                if exc_type_name in self._ignored_exceptions:
                    return None

        # Drop events from ignored loggers
        event_logger = event.get("logger")
        if event_logger is not None and event_logger in self._ignored_loggers:
            return None

        event = self._scrub_event(event)
        event = self._inject_context_tags(event)
        return event

    def before_send_transaction(
        self, event: dict[str, Any], hint: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Filter a transaction event before sending to Sentry."""
        event = self._scrub_event(event)
        event = self._inject_context_tags(event)
        return event

    # -- internals ---------------------------------------------------------

    def _scrub_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of *event* with sensitive fields replaced."""
        return {
            key: _scrub_event_data(
                value,
                exact_fields=self._scrub_exact,
                substring_fields=self._scrub_substrings,
                replacement=self.config.scrub_replacement,
                field_name=key,
            )
            for key, value in event.items()
        }

    @staticmethod
    def _inject_context_tags(event: dict[str, Any]) -> dict[str, Any]:
        """Inject current request/correlation IDs as event tags."""
        request_id = get_current_request_id()
        correlation_id = get_current_correlation_id()

        if request_id or correlation_id:
            tags = dict(event.get("tags") or {})
            if request_id:
                tags["request_id"] = request_id
            if correlation_id:
                tags["correlation_id"] = correlation_id
            event = {**event, "tags": tags}

        return event


# ---------------------------------------------------------------------------
# Traces sampler
# ---------------------------------------------------------------------------
_HEALTH_FRAGMENTS = ("/health", "/ready", "/readiness", "/liveness", "/status")


def traces_sampler(sampling_context: dict[str, Any], config: SentryConfig) -> float:
    """Context-aware transaction sampling.

    - Health and readiness endpoints sample at ``SENTRY_HEALTH_ENDPOINT_SAMPLE_RATE`` (default 0).
    - Webhook endpoints sample at ``SENTRY_WEBHOOK_SAMPLE_RATE`` when configured.
    - Everything else falls back to ``SENTRY_TRACES_SAMPLE_RATE``.
    """
    transaction_context = sampling_context.get("transaction_context") or {}
    transaction_name: str = transaction_context.get("name", "")

    if any(fragment in transaction_name for fragment in _HEALTH_FRAGMENTS):
        return config.health_endpoint_sample_rate

    if config.webhook_sample_rate is not None and "/webhook" in transaction_name:
        return config.webhook_sample_rate

    return config.traces_sample_rate


# ---------------------------------------------------------------------------
# SDK initialisation — API process
# ---------------------------------------------------------------------------
def init_sentry(settings: SentrySettings | None = None) -> None:
    """Initialise the Sentry SDK for an API process with hardened defaults.

    Includes FastAPI, Logging, and (if available) ARQ integrations, plus
    event filtering, field scrubbing, and context-aware transaction sampling.
    """
    if settings is None:
        from .config import settings as default_settings
        settings = default_settings

    if not settings.SENTRY_ENABLE:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logger.warning("sentry_sdk is not installed — skipping Sentry initialisation")
        return

    config = SentryConfig.from_settings(settings)
    event_filter = SentryEventFilter(config)

    integrations: list[Any] = [
        FastApiIntegration(transaction_style="endpoint"),
        LoggingIntegration(level=logging.INFO, event_level=logging.WARNING),
    ]

    try:
        from sentry_sdk.integrations.arq import ArqIntegration

        integrations.append(ArqIntegration())
    except ImportError:
        pass

    def _traces_sampler(ctx: dict[str, Any]) -> float:
        return traces_sampler(ctx, config)

    sentry_sdk.init(
        dsn=config.dsn,
        environment=config.environment,
        release=config.release,
        debug=config.debug,
        attach_stacktrace=config.attach_stacktrace,
        send_default_pii=config.send_default_pii,
        max_breadcrumbs=config.max_breadcrumbs,
        sample_rate=config.error_sample_rate,
        traces_sampler=_traces_sampler,
        profiles_sample_rate=config.profiles_sample_rate,
        server_name=config.server_name,
        integrations=integrations,
        before_send=event_filter.before_send,  # type: ignore[arg-type]
        before_send_transaction=event_filter.before_send_transaction,  # type: ignore[arg-type]
    )

    # Tag the process type so API vs worker events are distinguishable
    scope = sentry_sdk.get_current_scope()
    scope.set_tag("process_type", "api")

    logger.info("Sentry initialised for API process", extra={"environment": config.environment})


# ---------------------------------------------------------------------------
# SDK initialisation — worker process
# ---------------------------------------------------------------------------
def init_sentry_for_worker(settings: SentrySettings | None = None) -> None:
    """Initialise the Sentry SDK for an ARQ worker process.

    Uses the ARQ integration as primary and tags the scope with
    ``process_type=worker`` so events are distinguishable from API traffic.
    """
    if settings is None:
        from .config import settings as default_settings

        settings = default_settings

    if not settings.SENTRY_ENABLE:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.arq import ArqIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logger.warning("sentry_sdk is not installed — skipping Sentry initialisation")
        return

    config = SentryConfig.from_settings(settings)
    event_filter = SentryEventFilter(config)

    integrations: list[Any] = [
        ArqIntegration(),
        LoggingIntegration(level=logging.INFO, event_level=logging.WARNING),
    ]

    worker_traces_rate = (
        config.worker_sample_rate if config.worker_sample_rate is not None else config.traces_sample_rate
    )

    sentry_sdk.init(
        dsn=config.dsn,
        environment=config.environment,
        release=config.release,
        debug=config.debug,
        attach_stacktrace=config.attach_stacktrace,
        send_default_pii=config.send_default_pii,
        max_breadcrumbs=config.max_breadcrumbs,
        sample_rate=config.error_sample_rate,
        traces_sample_rate=worker_traces_rate,
        profiles_sample_rate=config.profiles_sample_rate,
        server_name=config.server_name,
        integrations=integrations,
        before_send=event_filter.before_send,  # type: ignore[arg-type]
        before_send_transaction=event_filter.before_send_transaction,  # type: ignore[arg-type]
    )

    scope = sentry_sdk.get_current_scope()
    scope.set_tag("process_type", "worker")

    logger.info("Sentry initialised for worker process", extra={"environment": config.environment})


# ---------------------------------------------------------------------------
# SDK shutdown
# ---------------------------------------------------------------------------
async def shutdown_sentry(settings: SentrySettings | None = None) -> None:
    """Flush pending Sentry events and shut down the SDK.

    Uses the configurable ``SENTRY_FLUSH_TIMEOUT_SECONDS`` so production
    deployments can balance shutdown speed against event delivery.
    """
    if settings is None:
        from .config import settings as default_settings
        settings = default_settings

    if not settings.SENTRY_ENABLE:
        return

    try:
        import sentry_sdk
    except ImportError:
        return

    sentry_sdk.flush(timeout=settings.SENTRY_FLUSH_TIMEOUT_SECONDS)
    logger.info("Sentry shutdown complete", extra={"flush_timeout": settings.SENTRY_FLUSH_TIMEOUT_SECONDS})


# ---------------------------------------------------------------------------
# Scope helpers — tags, user, request context, job context
# ---------------------------------------------------------------------------
def set_sentry_tags(tags: dict[str, str]) -> None:
    """Set scope-level tags on the current Sentry scope."""
    if not is_sentry_enabled():
        return
    import sentry_sdk

    scope = sentry_sdk.get_current_scope()
    for key, value in tags.items():
        scope.set_tag(key, value)


def set_sentry_user(
    user_id: str,
    *,
    username: str | None = None,
    email: str | None = None,
    tenant_id: str | None = None,
    org_id: str | None = None,
) -> None:
    """Set user context on the current Sentry scope.

    Tenant and organisation identifiers are stored as scope tags rather than
    inside the user dict so Sentry can index and filter on them.
    """
    if not is_sentry_enabled():
        return
    import sentry_sdk

    scope = sentry_sdk.get_current_scope()
    user_data: dict[str, Any] = {"id": user_id}
    if username:
        user_data["username"] = username
    if email:
        user_data["email"] = email
    scope.set_user(user_data)

    if tenant_id:
        scope.set_tag("tenant_id", tenant_id)
    if org_id:
        scope.set_tag("org_id", org_id)


def set_sentry_request_context(
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Set request-level tags on the current Sentry scope."""
    if not is_sentry_enabled():
        return
    import sentry_sdk

    scope = sentry_sdk.get_current_scope()
    if request_id:
        scope.set_tag("request_id", request_id)
    if correlation_id:
        scope.set_tag("correlation_id", correlation_id)


def set_sentry_job_context(
    job_id: str,
    *,
    job_name: str | None = None,
    queue_name: str | None = None,
    correlation_id: str | None = None,
    retry_count: int | None = None,
) -> None:
    """Set background-job context on the current Sentry scope."""
    if not is_sentry_enabled():
        return
    import sentry_sdk

    scope = sentry_sdk.get_current_scope()
    job_data: dict[str, Any] = {"id": job_id}
    if job_name:
        job_data["name"] = job_name
    if queue_name:
        job_data["queue"] = queue_name
    if retry_count is not None:
        job_data["retry_count"] = retry_count
    scope.set_context("job", job_data)

    if correlation_id:
        scope.set_tag("correlation_id", correlation_id)


# ---------------------------------------------------------------------------
# Capture helpers
# ---------------------------------------------------------------------------
def capture_sentry_exception(
    error: Exception,
    extra_context: dict[str, Any] | None = None,
) -> str | None:
    """Capture an exception to Sentry with optional extra context."""
    if not is_sentry_enabled():
        return None
    import sentry_sdk

    if extra_context:
        scope = sentry_sdk.get_current_scope()
        scope.set_context("extra", extra_context)

    return sentry_sdk.capture_exception(error)


def capture_sentry_message(
    message: str,
    level: str = "info",
    extra: dict[str, Any] | None = None,
) -> str | None:
    """Capture a message to Sentry."""
    if not is_sentry_enabled():
        return None
    import sentry_sdk

    if extra:
        scope = sentry_sdk.get_current_scope()
        scope.set_context("extra", extra)

    return sentry_sdk.capture_message(message, level=level)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
__all__ = [
    "DEFAULT_SENTRY_SCRUB_FIELDS",
    "DEFAULT_SENTRY_SCRUB_SUBSTRINGS",
    "SentryConfig",
    "SentryEventFilter",
    "capture_sentry_exception",
    "capture_sentry_message",
    "init_sentry",
    "init_sentry_for_worker",
    "is_sentry_enabled",
    "resolve_sentry_release",
    "set_sentry_job_context",
    "set_sentry_request_context",
    "set_sentry_tags",
    "set_sentry_user",
    "shutdown_sentry",
    "traces_sampler",
]
