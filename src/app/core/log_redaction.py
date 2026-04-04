"""Shared log-redaction helpers for structured logging."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from structlog.types import EventDict


def normalize_redaction_field_name(value: str) -> str:
    """Normalize field names for case-insensitive redaction matching."""

    return "".join(character for character in value.casefold() if character.isalnum())


def should_redact_field(
    field_name: str,
    *,
    exact_fields: set[str],
    substring_fields: tuple[str, ...],
) -> bool:
    """Return whether a field name should have its value redacted."""

    normalized_field_name = normalize_redaction_field_name(field_name)
    if normalized_field_name in exact_fields:
        return True

    return any(fragment in normalized_field_name for fragment in substring_fields)


def redact_log_data(
    value: Any,
    *,
    exact_fields: set[str],
    substring_fields: tuple[str, ...],
    replacement: str,
    field_name: str | None = None,
) -> Any:
    """Recursively redact sensitive values from structured log payloads."""

    if field_name is not None and should_redact_field(
        field_name,
        exact_fields=exact_fields,
        substring_fields=substring_fields,
    ):
        return replacement

    if isinstance(value, Mapping):
        return {
            key: redact_log_data(
                nested_value,
                exact_fields=exact_fields,
                substring_fields=substring_fields,
                replacement=replacement,
                field_name=str(key),
            )
            for key, nested_value in value.items()
        }

    if isinstance(value, tuple):
        return tuple(
            redact_log_data(
                item,
                exact_fields=exact_fields,
                substring_fields=substring_fields,
                replacement=replacement,
            )
            for item in value
        )

    if isinstance(value, list):
        return [
            redact_log_data(
                item,
                exact_fields=exact_fields,
                substring_fields=substring_fields,
                replacement=replacement,
            )
            for item in value
        ]

    if isinstance(value, set):
        return {
            redact_log_data(
                item,
                exact_fields=exact_fields,
                substring_fields=substring_fields,
                replacement=replacement,
            )
            for item in value
        }

    return value


def redact_log_event_dict(
    event_dict: EventDict,
    *,
    exact_fields: set[str],
    substring_fields: tuple[str, ...],
    replacement: str,
) -> EventDict:
    """Return a redacted copy of a structlog event dictionary."""

    return {
        key: redact_log_data(
            value,
            exact_fields=exact_fields,
            substring_fields=substring_fields,
            replacement=replacement,
            field_name=key,
        )
        for key, value in event_dict.items()
    }


__all__ = [
    "normalize_redaction_field_name",
    "redact_log_data",
    "redact_log_event_dict",
    "should_redact_field",
]
