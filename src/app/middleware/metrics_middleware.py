"""ASGI middleware that records Prometheus request metrics.

Records ``http_requests_total``, ``http_request_duration_seconds``, and
``http_requests_in_progress`` on every HTTP request when the metrics
subsystem is enabled.
"""

from __future__ import annotations

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..core.metrics import TemplateMetrics, get_path_template_label


class MetricsMiddleware:
    """Record Prometheus metrics for each HTTP request.

    This middleware is only added to the middleware stack when metrics are
    enabled.  It delegates to the global ``TemplateMetrics`` instance and
    respects the ``include_path_labels`` configuration.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        metrics: TemplateMetrics,
        include_path_labels: bool = False,
    ) -> None:
        self.app = app
        self.metrics = metrics
        self.include_path_labels = include_path_labels

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method: str = scope.get("method", "UNKNOWN")
        path: str = scope.get("path", "/")
        path_label = get_path_template_label(path, include_path_labels=self.include_path_labels)

        self.metrics.http_requests_in_progress.labels(method=method).inc()
        start = time.perf_counter()

        status_code = 500  # default if response never starts

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start
            self.metrics.http_requests_in_progress.labels(method=method).dec()
            self.metrics.http_requests_total.labels(
                method=method,
                path_template=path_label,
                status_code=status_code,
            ).inc()
            self.metrics.http_request_duration_seconds.labels(
                method=method,
                path_template=path_label,
            ).observe(duration)


__all__ = ["MetricsMiddleware"]
