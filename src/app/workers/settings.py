"""Canonical ARQ worker entrypoint."""

from ..core.worker.settings import WorkerSettings, start_arq_service

start_worker = start_arq_service

__all__ = ["WorkerSettings", "start_arq_service", "start_worker"]
