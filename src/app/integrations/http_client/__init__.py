"""Shared outbound HTTP client layer for integration adapters.

This package provides a reusable async HTTP client built on httpx with
template-owned defaults for timeouts, connection pooling, correlation
propagation, structured logging, retry, circuit breaking, rate-limit
handling, authentication, and instrumentation.

Integration adapters should build on ``TemplateHttpClient`` rather than
constructing raw httpx clients, so they inherit the template's production
defaults and observability contract.
"""

from .auth import (
    ApiKeyAuth,
    BasicAuth,
    BearerTokenAuth,
    CustomAuth,
    TokenProvider,
)
from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    build_circuit_breaker_config_from_settings,
)
from .client import (
    HttpClientConfig,
    RequestHook,
    ResponseHook,
    TemplateHttpClient,
    build_config_from_settings,
    raise_for_status,
)
from .exceptions import (
    HttpAuthenticationError,
    HttpAuthorizationError,
    HttpCircuitOpenError,
    HttpClientBadRequestError,
    HttpClientError,
    HttpConflictError,
    HttpConnectionError,
    HttpNotFoundError,
    HttpRateLimitError,
    HttpResponseSummary,
    HttpServerError,
    HttpTimeoutError,
    NonRetryableHttpError,
    classify_status_code,
)
from .instrumentation import (
    InstrumentationRequestHook,
    InstrumentationResponseHook,
    MetricsCollector,
    TracingHook,
)
from .logging import (
    LoggingRequestHook,
    LoggingResponseHook,
)
from .rate_limit import (
    RateLimitInfo,
    compute_rate_limit_delay,
    parse_rate_limit_headers,
)
from .retry import (
    IDEMPOTENT_METHODS,
    HttpRetryPolicy,
    build_retry_policy_from_settings,
    is_retryable_error,
    resolve_retry_delay,
    should_retry_method,
)

__all__ = [
    # Auth
    "ApiKeyAuth",
    "BasicAuth",
    "BearerTokenAuth",
    "CustomAuth",
    "TokenProvider",
    # Circuit breaker
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "build_circuit_breaker_config_from_settings",
    # Client
    "HttpClientConfig",
    "RequestHook",
    "ResponseHook",
    "TemplateHttpClient",
    "build_config_from_settings",
    "raise_for_status",
    # Exceptions
    "HttpAuthenticationError",
    "HttpAuthorizationError",
    "HttpCircuitOpenError",
    "HttpClientBadRequestError",
    "HttpClientError",
    "HttpConflictError",
    "HttpConnectionError",
    "HttpNotFoundError",
    "HttpRateLimitError",
    "HttpResponseSummary",
    "HttpServerError",
    "HttpTimeoutError",
    "NonRetryableHttpError",
    "classify_status_code",
    # Instrumentation
    "InstrumentationRequestHook",
    "InstrumentationResponseHook",
    "MetricsCollector",
    "TracingHook",
    # Logging
    "LoggingRequestHook",
    "LoggingResponseHook",
    # Rate limit
    "RateLimitInfo",
    "compute_rate_limit_delay",
    "parse_rate_limit_headers",
    # Retry
    "HttpRetryPolicy",
    "IDEMPOTENT_METHODS",
    "build_retry_policy_from_settings",
    "is_retryable_error",
    "resolve_retry_delay",
    "should_retry_method",
]
