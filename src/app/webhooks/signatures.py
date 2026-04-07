"""Provider-agnostic webhook signature verification contracts."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, cast, runtime_checkable

from starlette.datastructures import Headers

from .ingestion import WebhookIngestionRequest


class WebhookSignatureVerificationError(ValueError):
    """Base error raised when webhook signature verification fails."""


class MissingWebhookSignatureError(WebhookSignatureVerificationError):
    """Raised when required signature material is absent from the request."""


class InvalidWebhookSignatureError(WebhookSignatureVerificationError):
    """Raised when a provider signature does not match the raw payload."""


class StaleWebhookSignatureError(WebhookSignatureVerificationError):
    """Raised when a timestamped signature falls outside the accepted age window."""


@dataclass(slots=True, frozen=True)
class WebhookSignatureVerificationContext:
    """Provider-neutral input contract for webhook signature verification."""

    provider: str
    endpoint_key: str
    request: WebhookIngestionRequest
    signature_max_age_seconds: int | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def headers(self) -> Headers:
        return self.request.headers

    @property
    def raw_body(self) -> bytes:
        return self.request.raw_body

    @property
    def content_type(self) -> str | None:
        return self.request.content_type

    def get_header(self, name: str, *, required: bool = False) -> str | None:
        """Return a single header value, optionally failing when it is absent."""

        value = self.headers.get(name)
        if value is None and required:
            raise MissingWebhookSignatureError(f"Missing required webhook signature header: {name}")
        return value

    def first_header(self, *names: str, required: bool = False) -> str | None:
        """Return the first present header from a list of acceptable names."""

        for name in names:
            value = self.headers.get(name)
            if value is not None:
                return value

        if required:
            rendered_names = ", ".join(names)
            raise MissingWebhookSignatureError(
                f"Missing required webhook signature header: {rendered_names}"
            )

        return None


@dataclass(slots=True, frozen=True)
class WebhookSignatureVerificationResult:
    """Metadata recorded after a provider-specific signature check succeeds."""

    provider: str
    endpoint_key: str
    verified_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    signature: str | None = None
    algorithm: str | None = None
    key_id: str | None = None
    signed_at: datetime | None = None


@runtime_checkable
class WebhookSignatureVerifier(Protocol):
    """Async verifier contract for provider-specific webhook adapters."""

    async def verify(
        self,
        context: WebhookSignatureVerificationContext,
    ) -> WebhookSignatureVerificationResult: ...


WebhookSignatureVerificationOutcome = WebhookSignatureVerificationResult | Awaitable[WebhookSignatureVerificationResult]
WebhookSignatureVerifierCallable = Callable[[WebhookSignatureVerificationContext], WebhookSignatureVerificationOutcome]
WebhookSignatureVerifierLike = WebhookSignatureVerifier | WebhookSignatureVerifierCallable


async def verify_webhook_signature(
    verifier: WebhookSignatureVerifierLike,
    *,
    request: WebhookIngestionRequest,
    provider: str,
    endpoint_key: str,
    signature_max_age_seconds: int | None = None,
) -> WebhookSignatureVerificationResult:
    """Run a provider-specific verifier against the canonical webhook context."""

    context = WebhookSignatureVerificationContext(
        provider=provider,
        endpoint_key=endpoint_key,
        request=request,
        signature_max_age_seconds=signature_max_age_seconds,
    )
    verification = _call_webhook_signature_verifier(verifier, context)
    if inspect.isawaitable(verification):
        return await verification

    return verification


def _call_webhook_signature_verifier(
    verifier: WebhookSignatureVerifierLike,
    context: WebhookSignatureVerificationContext,
) -> WebhookSignatureVerificationOutcome:
    if isinstance(verifier, WebhookSignatureVerifier):
        return verifier.verify(context)

    verifier_callable = cast(WebhookSignatureVerifierCallable, verifier)
    return verifier_callable(context)


__all__ = [
    "InvalidWebhookSignatureError",
    "MissingWebhookSignatureError",
    "StaleWebhookSignatureError",
    "WebhookSignatureVerificationContext",
    "WebhookSignatureVerificationError",
    "WebhookSignatureVerificationResult",
    "WebhookSignatureVerifier",
    "verify_webhook_signature",
]
