from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from structlog.contextvars import bind_contextvars, clear_contextvars, get_contextvars

from src.app.platform.application import create_application
from src.app.platform.config import load_settings
from src.app.platform.request_context import (
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    build_correlation_headers,
    build_request_context,
    get_request_context,
    merge_correlation_headers,
)


@asynccontextmanager
async def noop_lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    yield


def build_test_application() -> FastAPI:
    router = APIRouter()

    @router.get("/request-context")
    async def request_context_probe(request: Request) -> dict[str, str | None]:
        request_context = get_request_context(request)
        assert request_context is not None

        log_context = get_contextvars()
        return {
            "request_id": request.state.request_id,
            "correlation_id": request.state.correlation_id,
            "context_request_id": request_context.request_id,
            "context_correlation_id": request_context.correlation_id,
            "log_request_id": log_context.get("request_id"),
            "log_correlation_id": log_context.get("correlation_id"),
        }

    @router.get("/request-context-error")
    async def request_context_error() -> None:
        raise HTTPException(status_code=418, detail="teapot")

    custom_settings = load_settings(_env_file=None)
    return create_application(router, custom_settings, lifespan=noop_lifespan)


def test_build_request_context_defaults_correlation_id_to_request_id() -> None:
    context = build_request_context({})

    assert context.request_id
    assert context.correlation_id == context.request_id


def test_build_correlation_headers_uses_bound_log_context() -> None:
    clear_contextvars()
    bind_contextvars(request_id="req-123", correlation_id="corr-456")

    try:
        headers = build_correlation_headers()
    finally:
        clear_contextvars()

    assert headers == {
        REQUEST_ID_HEADER: "req-123",
        CORRELATION_ID_HEADER: "corr-456",
    }


def test_merge_correlation_headers_preserves_other_header_values() -> None:
    clear_contextvars()
    bind_contextvars(request_id="req-123", correlation_id="corr-456")

    try:
        headers = merge_correlation_headers({"Authorization": "Bearer token"})
    finally:
        clear_contextvars()

    assert headers == {
        "Authorization": "Bearer token",
        REQUEST_ID_HEADER: "req-123",
        CORRELATION_ID_HEADER: "corr-456",
    }


def test_request_context_middleware_generates_headers_and_binds_context() -> None:
    application = build_test_application()

    with TestClient(application) as client:
        response = client.get("/request-context")

    payload = response.json()
    request_id = payload["request_id"]
    correlation_id = payload["correlation_id"]

    assert request_id
    assert correlation_id == request_id
    assert payload["context_request_id"] == request_id
    assert payload["context_correlation_id"] == correlation_id
    assert payload["log_request_id"] == request_id
    assert payload["log_correlation_id"] == correlation_id
    assert response.headers[REQUEST_ID_HEADER] == request_id
    assert response.headers[CORRELATION_ID_HEADER] == correlation_id


def test_request_context_middleware_preserves_supplied_headers() -> None:
    application = build_test_application()
    request_headers = {
        REQUEST_ID_HEADER: "req-123",
        CORRELATION_ID_HEADER: "corr-456",
    }

    with TestClient(application) as client:
        response = client.get("/request-context", headers=request_headers)

    payload = response.json()

    assert payload["request_id"] == "req-123"
    assert payload["correlation_id"] == "corr-456"
    assert payload["log_request_id"] == "req-123"
    assert payload["log_correlation_id"] == "corr-456"
    assert response.headers[REQUEST_ID_HEADER] == "req-123"
    assert response.headers[CORRELATION_ID_HEADER] == "corr-456"


def test_request_context_middleware_generates_request_id_when_only_correlation_id_is_supplied() -> None:
    application = build_test_application()

    with TestClient(application) as client:
        response = client.get("/request-context", headers={CORRELATION_ID_HEADER: "corr-789"})

    payload = response.json()

    assert payload["correlation_id"] == "corr-789"
    assert payload["request_id"]
    assert payload["request_id"] != "corr-789"
    assert response.headers[CORRELATION_ID_HEADER] == "corr-789"
    assert response.headers[REQUEST_ID_HEADER] == payload["request_id"]


def test_request_context_middleware_applies_headers_to_error_responses() -> None:
    application = build_test_application()
    request_headers = {
        REQUEST_ID_HEADER: "req-error",
        CORRELATION_ID_HEADER: "corr-error",
    }

    with TestClient(application) as client:
        response = client.get("/request-context-error", headers=request_headers)

    assert response.status_code == 418
    assert response.headers[REQUEST_ID_HEADER] == "req-error"
    assert response.headers[CORRELATION_ID_HEADER] == "corr-error"
