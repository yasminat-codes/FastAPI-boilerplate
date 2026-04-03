"""Canonical exception surface."""

from ..core.exceptions.cache_exceptions import (
    CacheIdentificationInferenceError,
    InvalidRequestError,
    MissingClientError,
)
from ..core.exceptions.http_exceptions import (
    BadRequestException,
    CustomException,
    DuplicateValueException,
    ForbiddenException,
    NotFoundException,
    RateLimitException,
    UnauthorizedException,
    UnprocessableEntityException,
)

__all__ = [
    "BadRequestException",
    "CacheIdentificationInferenceError",
    "CustomException",
    "DuplicateValueException",
    "ForbiddenException",
    "InvalidRequestError",
    "MissingClientError",
    "NotFoundException",
    "RateLimitException",
    "UnauthorizedException",
    "UnprocessableEntityException",
]
