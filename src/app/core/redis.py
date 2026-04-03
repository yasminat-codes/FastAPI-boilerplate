"""Reusable Redis runtime builders for cache, rate limiting, and queues."""

from typing import Any

from arq.connections import RedisSettings
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff


def build_redis_retry(*, attempts: int, base_delay: float, max_delay: float) -> Retry | None:
    if attempts == 0:
        return None

    return Retry(ExponentialBackoff(base=base_delay, cap=max_delay), retries=attempts)


def build_redis_pool_kwargs(
    *,
    connect_timeout: float,
    socket_timeout: float,
    retry_attempts: int,
    retry_base_delay: float,
    retry_max_delay: float,
    retry_on_timeout: bool,
    max_connections: int | None,
    ssl_enabled: bool,
    ssl_check_hostname: bool,
    ssl_cert_reqs: str,
    ssl_ca_certs: str | None,
    ssl_certfile: str | None,
    ssl_keyfile: str | None,
) -> dict[str, Any]:
    connection_kwargs: dict[str, Any] = {
        "socket_connect_timeout": connect_timeout,
        "socket_timeout": socket_timeout,
        "retry_on_timeout": retry_on_timeout,
    }

    retry = build_redis_retry(
        attempts=retry_attempts,
        base_delay=retry_base_delay,
        max_delay=retry_max_delay,
    )
    if retry is not None:
        connection_kwargs["retry"] = retry

    if max_connections is not None:
        connection_kwargs["max_connections"] = max_connections

    if ssl_enabled:
        connection_kwargs.update(
            {
                "ssl_check_hostname": ssl_check_hostname,
                "ssl_cert_reqs": ssl_cert_reqs,
                "ssl_ca_certs": ssl_ca_certs,
                "ssl_certfile": ssl_certfile,
                "ssl_keyfile": ssl_keyfile,
            }
        )

    return connection_kwargs


def build_arq_redis_settings(
    *,
    host: str,
    port: int,
    database: int,
    username: str | None,
    password: str | None,
    ssl_enabled: bool,
    ssl_keyfile: str | None,
    ssl_certfile: str | None,
    ssl_cert_reqs: str,
    ssl_ca_certs: str | None,
    ssl_check_hostname: bool,
    connect_timeout: int,
    connect_retries: int,
    retry_delay: int,
    max_connections: int | None,
    retry_on_timeout: bool,
) -> RedisSettings:
    return RedisSettings(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        ssl=ssl_enabled,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile,
        ssl_cert_reqs=ssl_cert_reqs,
        ssl_ca_certs=ssl_ca_certs,
        ssl_check_hostname=ssl_check_hostname,
        conn_timeout=connect_timeout,
        conn_retries=connect_retries,
        conn_retry_delay=retry_delay,
        max_connections=max_connections,
        retry_on_timeout=retry_on_timeout,
    )


__all__ = [
    "build_arq_redis_settings",
    "build_redis_pool_kwargs",
    "build_redis_retry",
]
