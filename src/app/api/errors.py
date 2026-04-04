"""API exception handling and error response helpers."""

from __future__ import annotations

import re
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..platform.exceptions import CustomException
from ..platform.logger import logging
from .contracts import ApiErrorDetail, ApiErrorResponse

LOGGER = logging.getLogger(__name__)

STATUS_CODE_ERROR_CODES = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: "payload_too_large",
    status.HTTP_422_UNPROCESSABLE_ENTITY: "validation_error",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
    status.HTTP_408_REQUEST_TIMEOUT: "request_timeout",
    status.HTTP_504_GATEWAY_TIMEOUT: "request_timeout",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "internal_server_error",
}


def _camel_to_snake(value: str) -> str:
    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
    return normalized.removesuffix("_exception")


def _extract_error_message(detail: Any, *, default: str) -> str:
    if isinstance(detail, str) and detail.strip():
        return detail
    return default


def _resolve_error_code(exc: Exception, *, status_code: int) -> str:
    if isinstance(exc, RequestValidationError):
        return STATUS_CODE_ERROR_CODES[status.HTTP_422_UNPROCESSABLE_ENTITY]

    if isinstance(exc, HTTPException):
        if exc.__class__ is not HTTPException:
            exception_code = _camel_to_snake(exc.__class__.__name__)
            if exception_code:
                return exception_code

        return STATUS_CODE_ERROR_CODES.get(status_code, "http_error")

    return STATUS_CODE_ERROR_CODES[status.HTTP_500_INTERNAL_SERVER_ERROR]


def build_api_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload = ApiErrorResponse(error=ApiErrorDetail(code=code, message=message, details=details))
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(exclude_none=True),
        headers=headers,
    )


async def custom_exception_handler(_: Request, exc: CustomException) -> JSONResponse:
    return build_api_error_response(
        status_code=exc.status_code,
        code=_resolve_error_code(exc, status_code=exc.status_code),
        message=_extract_error_message(exc.detail, default="Request failed."),
    )


async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return build_api_error_response(
        status_code=exc.status_code,
        code=_resolve_error_code(exc, status_code=exc.status_code),
        message=_extract_error_message(exc.detail, default="Request failed."),
    )


async def request_validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [dict(item) for item in exc.errors()]
    return build_api_error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code=_resolve_error_code(exc, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY),
        message="Request validation failed.",
        details=details,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    LOGGER.exception("Unhandled API exception for %s %s", request.method, request.url.path)
    return build_api_error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=_resolve_error_code(exc, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR),
        message="Internal server error.",
    )


def register_api_exception_handlers(application: FastAPI) -> None:
    """Register the template's canonical exception-to-response mapping."""

    application.add_exception_handler(CustomException, cast(Any, custom_exception_handler))
    application.add_exception_handler(HTTPException, cast(Any, http_exception_handler))
    application.add_exception_handler(RequestValidationError, cast(Any, request_validation_exception_handler))
    application.add_exception_handler(Exception, cast(Any, unhandled_exception_handler))


__all__ = [
    "build_api_error_response",
    "register_api_exception_handlers",
]
