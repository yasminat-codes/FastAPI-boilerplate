from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient

from src.app.platform.webhooks import RAW_REQUEST_BODY_STATE_KEY, parse_raw_json_body, read_raw_request_body


def _build_webhook_probe_app() -> FastAPI:
    application = FastAPI()
    router = APIRouter()

    @router.post("/webhooks/probe")
    async def webhook_probe(request: Request) -> dict[str, object]:
        raw_body = await read_raw_request_body(request)
        cached_body = await read_raw_request_body(request)
        payload = parse_raw_json_body(raw_body)

        return {
            "same_body": raw_body == cached_body,
            "cached_on_state": getattr(request.state, RAW_REQUEST_BODY_STATE_KEY) == raw_body,
            "event_type": payload["type"],
        }

    application.include_router(router)
    return application


def test_raw_webhook_body_helpers_cache_exact_request_bytes() -> None:
    application = _build_webhook_probe_app()

    with TestClient(application) as client:
        response = client.post("/webhooks/probe", json={"type": "invoice.updated"})

    assert response.status_code == 200
    assert response.json() == {
        "same_body": True,
        "cached_on_state": True,
        "event_type": "invoice.updated",
    }
