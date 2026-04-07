import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.app.platform.webhooks import (
    RAW_REQUEST_BODY_STATE_KEY as platform_raw_request_body_state_key,
)
from src.app.platform.webhooks import (
    InvalidWebhookSignatureError as platform_invalid_webhook_signature_error,
)
from src.app.platform.webhooks import (
    MissingWebhookSignatureError as platform_missing_webhook_signature_error,
)
from src.app.platform.webhooks import WebhookEventEnqueuer as platform_webhook_event_enqueuer
from src.app.platform.webhooks import (
    WebhookEventEnqueueRequest as platform_webhook_event_enqueue_request,
)
from src.app.platform.webhooks import (
    WebhookEventEnqueueResult as platform_webhook_event_enqueue_result,
)
from src.app.platform.webhooks import WebhookIngestionRequest as platform_webhook_ingestion_request
from src.app.platform.webhooks import WebhookIngestionResult as platform_webhook_ingestion_result
from src.app.platform.webhooks import (
    WebhookReplayDetectedError as platform_webhook_replay_detected_error,
)
from src.app.platform.webhooks import (
    WebhookReplayFingerprintMismatchError as platform_webhook_replay_fingerprint_mismatch_error,
)
from src.app.platform.webhooks import WebhookReplayKeyKind as platform_webhook_replay_key_kind
from src.app.platform.webhooks import WebhookReplayMatch as platform_webhook_replay_match
from src.app.platform.webhooks import (
    WebhookReplayProtectionError as platform_webhook_replay_protection_error,
)
from src.app.platform.webhooks import (
    WebhookReplayProtectionRequest as platform_webhook_replay_protection_request,
)
from src.app.platform.webhooks import (
    WebhookReplayProtectionResult as platform_webhook_replay_protection_result,
)
from src.app.platform.webhooks import WebhookReplayProtector as platform_webhook_replay_protector
from src.app.platform.webhooks import (
    WebhookSignatureVerificationContext as platform_webhook_signature_verification_context,
)
from src.app.platform.webhooks import (
    WebhookSignatureVerificationResult as platform_webhook_signature_verification_result,
)
from src.app.platform.webhooks import (
    WebhookSignatureVerifier as platform_webhook_signature_verifier,
)
from src.app.platform.webhooks import WebhookValidatedEvent as platform_webhook_validated_event
from src.app.platform.webhooks import (
    build_webhook_ingestion_request as platform_build_webhook_ingestion_request,
)
from src.app.platform.webhooks import ingest_webhook_event as platform_ingest_webhook_event
from src.app.platform.webhooks import parse_raw_json_body as platform_parse_raw_json_body
from src.app.platform.webhooks import read_raw_request_body as platform_read_raw_request_body
from src.app.platform.webhooks import validate_json_webhook_event as platform_validate_json_webhook_event
from src.app.platform.webhooks import (
    verify_webhook_signature as platform_verify_webhook_signature,
)
from src.app.webhooks import (
    RAW_REQUEST_BODY_STATE_KEY,
    InvalidWebhookSignatureError,
    MissingWebhookSignatureError,
    WebhookEventEnqueuer,
    WebhookEventEnqueueRequest,
    WebhookEventEnqueueResult,
    WebhookIngestionRequest,
    WebhookIngestionResult,
    WebhookReplayDetectedError,
    WebhookReplayFingerprintMismatchError,
    WebhookReplayKeyKind,
    WebhookReplayMatch,
    WebhookReplayProtectionError,
    WebhookReplayProtectionRequest,
    WebhookReplayProtectionResult,
    WebhookReplayProtector,
    WebhookSignatureVerificationContext,
    WebhookSignatureVerificationResult,
    WebhookSignatureVerifier,
    WebhookValidatedEvent,
    build_webhook_ingestion_request,
    ingest_webhook_event,
    parse_raw_json_body,
    read_raw_request_body,
    validate_json_webhook_event,
    verify_webhook_signature,
)


def test_platform_webhook_surface_reexports_canonical_ingestion_helpers() -> None:
    assert platform_raw_request_body_state_key == RAW_REQUEST_BODY_STATE_KEY
    assert platform_invalid_webhook_signature_error is InvalidWebhookSignatureError
    assert platform_missing_webhook_signature_error is MissingWebhookSignatureError
    assert platform_webhook_event_enqueue_request is WebhookEventEnqueueRequest
    assert platform_webhook_event_enqueue_result is WebhookEventEnqueueResult
    assert platform_webhook_event_enqueuer is WebhookEventEnqueuer
    assert platform_webhook_ingestion_request is WebhookIngestionRequest
    assert platform_webhook_ingestion_result is WebhookIngestionResult
    assert platform_webhook_replay_detected_error is WebhookReplayDetectedError
    assert (
        platform_webhook_replay_fingerprint_mismatch_error
        is WebhookReplayFingerprintMismatchError
    )
    assert platform_webhook_replay_key_kind is WebhookReplayKeyKind
    assert platform_webhook_replay_match is WebhookReplayMatch
    assert platform_webhook_replay_protection_error is WebhookReplayProtectionError
    assert platform_webhook_replay_protection_request is WebhookReplayProtectionRequest
    assert platform_webhook_replay_protection_result is WebhookReplayProtectionResult
    assert platform_webhook_replay_protector is WebhookReplayProtector
    assert platform_build_webhook_ingestion_request is build_webhook_ingestion_request
    assert platform_ingest_webhook_event is ingest_webhook_event
    assert platform_parse_raw_json_body is parse_raw_json_body
    assert platform_read_raw_request_body is read_raw_request_body
    assert platform_webhook_signature_verification_context is WebhookSignatureVerificationContext
    assert platform_webhook_signature_verification_result is WebhookSignatureVerificationResult
    assert platform_webhook_signature_verifier is WebhookSignatureVerifier
    assert platform_webhook_validated_event is WebhookValidatedEvent
    assert platform_validate_json_webhook_event is validate_json_webhook_event
    assert platform_verify_webhook_signature is verify_webhook_signature


def _build_webhook_probe_app() -> FastAPI:
    application = FastAPI()
    router = APIRouter()

    @router.post("/webhooks/probe")
    async def webhook_probe(
        webhook_request: WebhookIngestionRequest = Depends(build_webhook_ingestion_request),
    ) -> dict[str, object]:
        cached_body = await read_raw_request_body(webhook_request.request)
        payload = parse_raw_json_body(webhook_request.raw_body)

        return {
            "same_body": webhook_request.raw_body == cached_body,
            "cached_on_state": (
                getattr(webhook_request.request.state, RAW_REQUEST_BODY_STATE_KEY) == webhook_request.raw_body
            ),
            "event_type": payload["type"],
            "content_type": webhook_request.content_type,
            "media_type": webhook_request.media_type,
            "charset": webhook_request.charset,
            "payload_size_bytes": webhook_request.payload_size_bytes,
            "body_text": webhook_request.text(),
            "header_event": webhook_request.headers["X-Event-Type"],
        }

    application.include_router(router)
    return application


def test_raw_webhook_ingestion_dependency_preserves_exact_request_bytes() -> None:
    application = _build_webhook_probe_app()
    raw_body = b'{"type":"invoice.updated"}'

    with TestClient(application) as client:
        response = client.post(
            "/webhooks/probe",
            content=raw_body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Event-Type": "invoice.updated",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "same_body": True,
        "cached_on_state": True,
        "event_type": "invoice.updated",
        "content_type": "application/json; charset=utf-8",
        "media_type": "application/json",
        "charset": "utf-8",
        "payload_size_bytes": len(raw_body),
        "body_text": raw_body.decode("utf-8"),
        "header_event": "invoice.updated",
    }


def _build_webhook_request(*, headers: dict[str, str] | None = None) -> WebhookIngestionRequest:
    request_headers = {
        "Content-Type": "application/json",
        **(headers or {}),
    }
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/webhooks/provider",
        "raw_path": b"/webhooks/provider",
        "query_string": b"",
        "headers": [(name.lower().encode("utf-8"), value.encode("utf-8")) for name, value in request_headers.items()],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
    }
    request = Request(scope)

    return WebhookIngestionRequest(
        request=request,
        raw_body=b'{"type":"invoice.updated"}',
        content_type=request.headers.get("content-type"),
    )


def test_webhook_signature_context_exposes_transport_metadata_and_header_helpers() -> None:
    webhook_request = _build_webhook_request(
        headers={
            "X-Provider-Signature": "sha256=abc123",
            "X-Provider-Timestamp": "1712363040",
        }
    )
    context = WebhookSignatureVerificationContext(
        provider="provider",
        endpoint_key="billing-events",
        request=webhook_request,
        signature_max_age_seconds=300,
    )

    assert context.provider == "provider"
    assert context.endpoint_key == "billing-events"
    assert context.signature_max_age_seconds == 300
    assert context.content_type == "application/json"
    assert context.raw_body == b'{"type":"invoice.updated"}'
    assert context.get_header("X-Provider-Signature", required=True) == "sha256=abc123"
    assert context.first_header("X-Signature", "X-Provider-Signature", required=True) == "sha256=abc123"
    assert context.first_header("X-Provider-Timestamp", required=True) == "1712363040"


def test_webhook_signature_context_raises_specific_missing_header_error() -> None:
    webhook_request = _build_webhook_request()
    context = WebhookSignatureVerificationContext(
        provider="provider",
        endpoint_key="billing-events",
        request=webhook_request,
    )

    try:
        context.first_header("X-Provider-Signature", "X-Alt-Signature", required=True)
    except MissingWebhookSignatureError as exc:
        assert "X-Provider-Signature, X-Alt-Signature" in str(exc)
    else:
        raise AssertionError("missing signature headers should raise a typed verification error")


class ExampleWebhookSignatureVerifier:
    async def verify(
        self,
        context: WebhookSignatureVerificationContext,
    ) -> WebhookSignatureVerificationResult:
        signature = context.first_header("X-Provider-Signature", required=True)

        if signature != "sha256=expected":
            raise InvalidWebhookSignatureError("signature mismatch")

        return WebhookSignatureVerificationResult(
            provider=context.provider,
            endpoint_key=context.endpoint_key,
            signature=signature,
            algorithm="hmac-sha256",
            key_id="primary",
            signed_at=datetime(2026, 4, 6, 19, 15, tzinfo=UTC),
        )


def test_verify_webhook_signature_supports_protocol_based_verifiers() -> None:
    webhook_request = _build_webhook_request(headers={"X-Provider-Signature": "sha256=expected"})

    verification = asyncio.run(
        verify_webhook_signature(
            ExampleWebhookSignatureVerifier(),
            request=webhook_request,
            provider="provider",
            endpoint_key="billing-events",
            signature_max_age_seconds=300,
        )
    )

    assert verification.provider == "provider"
    assert verification.endpoint_key == "billing-events"
    assert verification.signature == "sha256=expected"
    assert verification.algorithm == "hmac-sha256"
    assert verification.key_id == "primary"
    assert verification.signed_at == datetime(2026, 4, 6, 19, 15, tzinfo=UTC)


def test_verify_webhook_signature_supports_function_verifiers() -> None:
    webhook_request = _build_webhook_request(headers={"X-Provider-Signature": "sha256=expected"})

    def verifier(context: WebhookSignatureVerificationContext) -> WebhookSignatureVerificationResult:
        return WebhookSignatureVerificationResult(
            provider=context.provider,
            endpoint_key=context.endpoint_key,
            signature=context.get_header("X-Provider-Signature", required=True),
        )

    verification = asyncio.run(
        verify_webhook_signature(
            verifier,
            request=webhook_request,
            provider="provider",
            endpoint_key="billing-events",
        )
    )

    assert verification.provider == "provider"
    assert verification.endpoint_key == "billing-events"
    assert verification.signature == "sha256=expected"
