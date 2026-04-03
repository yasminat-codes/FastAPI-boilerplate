import asyncio
from typing import cast

from arq.cli import watch_reload
from arq.typing import WorkerSettingsType
from arq.worker import check_health, run_worker

from ...core.config import SettingsProfile, settings
from ...core.logger import logging  # noqa: F401
from ...core.redis import build_arq_redis_settings
from .functions import on_job_end, on_job_start, shutdown, startup
from .jobs import worker_functions


def build_worker_settings(runtime_settings: SettingsProfile | None = None) -> WorkerSettingsType:
    """Build an ARQ worker settings class from the template configuration profile."""

    configured_settings = settings if runtime_settings is None else runtime_settings

    class ConfiguredWorkerSettings:
        functions = worker_functions
        queue_name = configured_settings.WORKER_QUEUE_NAME
        max_jobs = configured_settings.WORKER_MAX_JOBS
        max_tries = configured_settings.WORKER_JOB_MAX_TRIES
        keep_result = configured_settings.WORKER_KEEP_RESULT_SECONDS
        keep_result_forever = configured_settings.WORKER_KEEP_RESULT_FOREVER
        expires_extra_ms = configured_settings.WORKER_JOB_EXPIRES_EXTRA_MS
        ctx = {"settings": configured_settings}
        redis_settings = build_arq_redis_settings(
            host=configured_settings.REDIS_QUEUE_HOST,
            port=configured_settings.REDIS_QUEUE_PORT,
            database=configured_settings.REDIS_QUEUE_DB,
            username=configured_settings.REDIS_QUEUE_USERNAME,
            password=configured_settings.REDIS_QUEUE_PASSWORD,
            ssl_enabled=configured_settings.REDIS_QUEUE_SSL,
            ssl_keyfile=configured_settings.REDIS_QUEUE_SSL_KEYFILE,
            ssl_certfile=configured_settings.REDIS_QUEUE_SSL_CERTFILE,
            ssl_cert_reqs=configured_settings.REDIS_QUEUE_SSL_CERT_REQS.value,
            ssl_ca_certs=configured_settings.REDIS_QUEUE_SSL_CA_CERTS,
            ssl_check_hostname=configured_settings.REDIS_QUEUE_SSL_CHECK_HOSTNAME,
            connect_timeout=configured_settings.REDIS_QUEUE_CONNECT_TIMEOUT,
            connect_retries=configured_settings.REDIS_QUEUE_CONNECT_RETRIES,
            retry_delay=configured_settings.REDIS_QUEUE_RETRY_DELAY,
            max_connections=configured_settings.REDIS_QUEUE_MAX_CONNECTIONS,
            retry_on_timeout=configured_settings.REDIS_QUEUE_RETRY_ON_TIMEOUT,
        )
        on_startup = startup
        on_shutdown = shutdown
        on_job_start = on_job_start
        on_job_end = on_job_end
        handle_signals = True
        job_completion_wait = 30

    return cast("WorkerSettingsType", ConfiguredWorkerSettings)


WorkerSettings = build_worker_settings()


def start_arq_service(check: bool = False, burst: int | None = None, watch: str | None = None) -> None:
    worker_settings_ = cast("WorkerSettingsType", WorkerSettings)

    if check:
        exit(check_health(worker_settings_))
    else:
        kwargs = {} if burst is None else {"burst": burst}
        if watch:
            asyncio.run(watch_reload(watch, worker_settings_))
        else:
            run_worker(worker_settings_, **kwargs)


if __name__ == "__main__":
    start_arq_service()
    # python -m src.app.core.worker.settings
