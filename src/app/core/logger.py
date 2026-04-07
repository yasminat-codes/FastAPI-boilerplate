"""Logging configuration for the application.

Production default: structured logs go to stdout/stderr only.
File logging is opt-in via ``FILE_LOG_ENABLED=true`` for environments
that still need on-disk log files.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

import structlog
from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer
from structlog.types import EventDict, Processor

from ..core.config import settings
from .log_redaction import normalize_redaction_field_name, redact_log_event_dict

# ---------------------------------------------------------------------------
# Standard log-shape context vocabulary
# ---------------------------------------------------------------------------
# API request context keys (bound by RequestContextMiddleware):
#   request_id, correlation_id, client_host, status_code, path, method
#
# Worker / job context keys (bound by bind_job_log_context):
#   job_id, job_name, correlation_id, tenant_id, organization_id,
#   retry_count, job_metadata
#
# Cross-cutting context keys (bound by callers as needed):
#   workflow_id        – links a log entry to a workflow execution
#   provider_event_id  – links a log entry to a provider webhook event
#
# All of these keys flow through structlog contextvars and appear
# automatically in every log entry once bound for the current scope.
# ---------------------------------------------------------------------------

#: Context keys that the per-handler filter processors will manage.
FILTERABLE_CONTEXT_KEYS = (
    "request_id",
    "correlation_id",
    "path",
    "method",
    "client_host",
    "status_code",
)


def drop_color_message_key(_, __, event_dict: EventDict) -> EventDict:
    """Uvicorn adds `color_message` which duplicates `event`.

    Remove it to avoid double logging.
    """
    event_dict.pop("color_message", None)
    return event_dict


def _build_handler_filter(*, include_request_id: bool, include_correlation_id: bool, include_path: bool,
                          include_method: bool, include_client_host: bool,
                          include_status_code: bool) -> Processor:
    """Return a structlog processor that strips context keys according to per-handler include flags."""

    include_map = {
        "request_id": include_request_id,
        "correlation_id": include_correlation_id,
        "path": include_path,
        "method": include_method,
        "client_host": include_client_host,
        "status_code": include_status_code,
    }

    def _filter(_, __, event_dict: EventDict) -> EventDict:
        for key, included in include_map.items():
            if not included:
                event_dict.pop(key, None)
        return event_dict

    return _filter


# Build per-handler filter processors from settings
file_log_filter_processor = _build_handler_filter(
    include_request_id=settings.FILE_LOG_INCLUDE_REQUEST_ID,
    include_correlation_id=settings.FILE_LOG_INCLUDE_CORRELATION_ID,
    include_path=settings.FILE_LOG_INCLUDE_PATH,
    include_method=settings.FILE_LOG_INCLUDE_METHOD,
    include_client_host=settings.FILE_LOG_INCLUDE_CLIENT_HOST,
    include_status_code=settings.FILE_LOG_INCLUDE_STATUS_CODE,
)

console_log_filter_processor = _build_handler_filter(
    include_request_id=settings.CONSOLE_LOG_INCLUDE_REQUEST_ID,
    include_correlation_id=settings.CONSOLE_LOG_INCLUDE_CORRELATION_ID,
    include_path=settings.CONSOLE_LOG_INCLUDE_PATH,
    include_method=settings.CONSOLE_LOG_INCLUDE_METHOD,
    include_client_host=settings.CONSOLE_LOG_INCLUDE_CLIENT_HOST,
    include_status_code=settings.CONSOLE_LOG_INCLUDE_STATUS_CODE,
)


def redact_sensitive_log_fields(_, __, event_dict: EventDict) -> EventDict:
    """Scrub common secrets, tokens, and PII-like fields from structured logs."""

    if not settings.LOG_REDACTION_ENABLED:
        return event_dict

    exact_fields = {
        normalize_redaction_field_name(field_name) for field_name in settings.LOG_REDACTION_EXACT_FIELDS
    }
    substring_fields = tuple(
        normalize_redaction_field_name(field_name) for field_name in settings.LOG_REDACTION_SUBSTRING_FIELDS
    )
    return redact_log_event_dict(
        event_dict,
        exact_fields=exact_fields,
        substring_fields=substring_fields,
        replacement=settings.LOG_REDACTION_REPLACEMENT,
    )


# Shared processors for all loggers
timestamper = structlog.processors.TimeStamper(fmt="iso")
SHARED_PROCESSORS: list[Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.stdlib.PositionalArgumentsFormatter(),
    structlog.stdlib.ExtraAdder(),
    redact_sensitive_log_fields,
    drop_color_message_key,
    timestamper,
    structlog.processors.StackInfoRenderer(),
]


# Configure structlog globally
structlog.configure(
    processors=SHARED_PROCESSORS + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)


def build_formatter(*, json_output: bool, pre_chain: list[Processor]) -> structlog.stdlib.ProcessorFormatter:
    """Build a ProcessorFormatter with the specified renderer and processors."""
    renderer = JSONRenderer() if json_output else ConsoleRenderer()

    processors = [structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer]

    if json_output:
        pre_chain = pre_chain + [structlog.processors.format_exc_info]

    return structlog.stdlib.ProcessorFormatter(foreign_pre_chain=pre_chain, processors=processors)


# ---------------------------------------------------------------------------
# Console handler — always enabled, production default output channel
# ---------------------------------------------------------------------------
console_handler = logging.StreamHandler()
console_handler.setLevel(settings.CONSOLE_LOG_LEVEL.value)
console_handler.setFormatter(
    build_formatter(
        json_output=settings.CONSOLE_LOG_FORMAT_JSON, pre_chain=SHARED_PROCESSORS + [console_log_filter_processor]
    )
)


# ---------------------------------------------------------------------------
# File handler — opt-in via FILE_LOG_ENABLED=true
# ---------------------------------------------------------------------------
file_handler: RotatingFileHandler | None = None
if settings.FILE_LOG_ENABLED:
    LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(LOG_DIR, exist_ok=True)

    file_handler = RotatingFileHandler(
        filename=os.path.join(LOG_DIR, "app.log"),
        maxBytes=settings.FILE_LOG_MAX_BYTES,
        backupCount=settings.FILE_LOG_BACKUP_COUNT,
    )
    file_handler.setLevel(settings.FILE_LOG_LEVEL.value)
    file_handler.setFormatter(
        build_formatter(
            json_output=settings.FILE_LOG_FORMAT_JSON, pre_chain=SHARED_PROCESSORS + [file_log_filter_processor]
        )
    )


# ---------------------------------------------------------------------------
# Root logger configuration
# ---------------------------------------------------------------------------
root_logger = logging.getLogger()
root_logger.setLevel(settings.LOG_LEVEL.value)
root_logger.handlers.clear()  # avoid duplicate logs
root_logger.addHandler(console_handler)
if file_handler is not None:
    root_logger.addHandler(file_handler)

# Uvicorn logger integration
for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    logger.propagate = True
    logger.setLevel(settings.UVICORN_LOG_LEVEL.value)
