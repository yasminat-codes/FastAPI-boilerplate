"""Backward-compatibility shim for integration contract exceptions.

The canonical integration error hierarchy now lives in ``errors.py``.
This module re-exports the subset of exceptions used by the settings
and configuration layer so existing imports continue to resolve.
"""

from __future__ import annotations

from .errors import (
    IntegrationConfigError,
    IntegrationCredentialError,
    IntegrationDisabledError,
    IntegrationError,
    IntegrationModeError,
    IntegrationNotFoundError,
    IntegrationProductionValidationError,
)

__all__ = [
    "IntegrationConfigError",
    "IntegrationCredentialError",
    "IntegrationDisabledError",
    "IntegrationError",
    "IntegrationModeError",
    "IntegrationNotFoundError",
    "IntegrationProductionValidationError",
]
