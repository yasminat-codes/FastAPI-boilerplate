"""Circuit breaker pattern for outbound HTTP requests.

Provides a lightweight in-process circuit breaker that tracks consecutive
failures and opens the circuit to prevent cascading outages when a
downstream provider is unhealthy.

State machine: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
- CLOSED: Requests flow normally. Consecutive failures are counted.
- OPEN: Requests are rejected immediately. After a recovery timeout, transitions to HALF_OPEN.
- HALF_OPEN: One probe request is allowed through. Success closes the circuit; failure reopens it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog

from .exceptions import HttpCircuitOpenError, HttpClientError

logger = structlog.get_logger(__name__)


class CircuitState(StrEnum):
    """Circuit breaker state machine states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(slots=True)
class CircuitBreakerConfig:
    """Configuration for a circuit breaker instance.

    Attributes:
        failure_threshold: Consecutive failures before opening the circuit.
        recovery_timeout_seconds: Seconds to wait before transitioning from OPEN to HALF_OPEN.
        name: Human-readable name for logging and diagnostics.
    """

    failure_threshold: int = 5
    recovery_timeout_seconds: float = 30.0
    name: str = "default"


def build_circuit_breaker_config_from_settings(
    settings: Any,
    *,
    name: str = "default",
) -> CircuitBreakerConfig:
    """Build a CircuitBreakerConfig from the template settings object."""
    return CircuitBreakerConfig(
        failure_threshold=getattr(settings, "HTTP_CLIENT_CIRCUIT_BREAKER_FAILURE_THRESHOLD", 5),
        recovery_timeout_seconds=getattr(
            settings, "HTTP_CLIENT_CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS", 30.0
        ),
        name=name,
    )


@dataclass(slots=True)
class CircuitBreaker:
    """In-process circuit breaker for outbound HTTP calls.

    Thread-safe for single-process async usage. Not shared across processes.
    For distributed circuit breaking, use a Redis-backed implementation.
    """

    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)

    @property
    def state(self) -> CircuitState:
        """Return the current circuit state, checking for recovery timeout."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.config.recovery_timeout_seconds:
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "circuit_breaker_half_open",
                    name=self.config.name,
                    elapsed_seconds=round(elapsed, 2),
                )
        return self._state

    @property
    def failure_count(self) -> int:
        """Return the current consecutive failure count."""
        return self._failure_count

    def check(self) -> None:
        """Check whether a request should be allowed through.

        Raises:
            HttpCircuitOpenError: If the circuit is open.
        """
        current_state = self.state
        if current_state == CircuitState.OPEN:
            raise HttpCircuitOpenError(
                f"Circuit breaker '{self.config.name}' is open after "
                f"{self._failure_count} consecutive failures"
            )

    def record_success(self) -> None:
        """Record a successful response and reset the failure counter."""
        previous_state = self._state
        self._failure_count = 0
        self._state = CircuitState.CLOSED
        if previous_state != CircuitState.CLOSED:
            logger.info(
                "circuit_breaker_closed",
                name=self.config.name,
                previous_state=previous_state,
            )

    def record_failure(self, error: HttpClientError | None = None) -> None:
        """Record a failed response and potentially open the circuit."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning(
                "circuit_breaker_reopened",
                name=self.config.name,
                failure_count=self._failure_count,
                error=str(error) if error else None,
            )
        elif self._failure_count >= self.config.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "circuit_breaker_opened",
                name=self.config.name,
                failure_count=self._failure_count,
                threshold=self.config.failure_threshold,
                error=str(error) if error else None,
            )

    def reset(self) -> None:
        """Force-reset the circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "build_circuit_breaker_config_from_settings",
]
