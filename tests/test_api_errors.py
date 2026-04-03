from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.app.api.errors import register_api_exception_handlers
from src.app.platform.exceptions import NotFoundException


def _build_test_app() -> FastAPI:
    application = FastAPI()
    register_api_exception_handlers(application)
    return application


def test_custom_exceptions_return_standardized_error_payloads() -> None:
    application = _build_test_app()

    @application.get("/missing")
    async def missing() -> None:
        raise NotFoundException("User not found")

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/missing")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "User not found"}}


def test_request_validation_errors_return_machine_readable_details() -> None:
    application = _build_test_app()

    class Payload(BaseModel):
        name: str

    @application.post("/payload")
    async def create_payload(payload: Payload) -> dict[str, str]:
        return payload.model_dump()

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.post("/payload", json={})

    body = response.json()

    assert response.status_code == 422
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"] == "Request validation failed."
    assert body["error"]["details"]


def test_unhandled_exceptions_return_internal_server_error_payload() -> None:
    application = _build_test_app()

    @application.get("/crash")
    async def crash() -> None:
        raise RuntimeError("boom")

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/crash")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_server_error",
            "message": "Internal server error.",
        }
    }
