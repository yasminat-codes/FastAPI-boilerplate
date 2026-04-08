"""Integration tests for Redis and queue initialization.

This module tests the initialization, connectivity verification, and cleanup of Redis
pools for caching, queuing, and rate limiting. It ensures that:

1. Redis pool configuration is correctly built from settings
2. Redis connectivity is verified during startup
3. Partial startup failures properly unwind already-initialized resources
4. Queue and rate limiter pools are initialized and cleaned up correctly
"""

from unittest.mock import AsyncMock, patch

import pytest
from arq.connections import RedisSettings
from redis.asyncio import ConnectionPool, Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff

from src.app.core.config import (
    RedisCacheSettings,
    RedisQueueSettings,
    RedisRateLimiterSettings,
    RedisSSLCertRequirements,
)
from src.app.core.redis import build_arq_redis_settings, build_redis_pool_kwargs, build_redis_retry
from src.app.core.setup import (
    close_redis_cache_pool,
    close_redis_queue_pool,
    close_redis_rate_limit_pool,
    create_redis_cache_pool,
    create_redis_queue_pool,
    create_redis_rate_limit_pool,
)
from src.app.core.utils import cache, queue
from src.app.core.utils.rate_limit import rate_limiter


class TestBuildRedisRetry:
    """Tests for build_redis_retry function."""

    def test_build_redis_retry_returns_none_when_attempts_zero(self) -> None:
        """build_redis_retry returns None when attempts is 0."""
        result = build_redis_retry(attempts=0, base_delay=0.1, max_delay=1.0)
        assert result is None

    def test_build_redis_retry_returns_retry_object_when_attempts_positive(self) -> None:
        """build_redis_retry returns Retry object when attempts > 0."""
        result = build_redis_retry(attempts=3, base_delay=0.1, max_delay=1.0)
        assert isinstance(result, Retry)
        assert result._retries == 3

    def test_build_redis_retry_uses_exponential_backoff(self) -> None:
        """build_redis_retry uses ExponentialBackoff with correct parameters."""
        result = build_redis_retry(attempts=3, base_delay=0.5, max_delay=5.0)
        assert isinstance(result, Retry)
        assert isinstance(result._backoff, ExponentialBackoff)


class TestBuildRedisPoolKwargs:
    """Tests for build_redis_pool_kwargs function."""

    def test_build_redis_pool_kwargs_includes_socket_timeouts(self) -> None:
        """build_redis_pool_kwargs includes socket connect and read timeouts."""
        kwargs = build_redis_pool_kwargs(
            connect_timeout=5.0,
            socket_timeout=5.0,
            retry_attempts=0,
            retry_base_delay=0.1,
            retry_max_delay=1.0,
            retry_on_timeout=True,
            max_connections=None,
            ssl_enabled=False,
            ssl_check_hostname=False,
            ssl_cert_reqs="none",
            ssl_ca_certs=None,
            ssl_certfile=None,
            ssl_keyfile=None,
        )

        assert kwargs["socket_connect_timeout"] == 5.0
        assert kwargs["socket_timeout"] == 5.0
        assert kwargs["retry_on_timeout"] is True

    def test_build_redis_pool_kwargs_includes_retry_when_attempts_positive(self) -> None:
        """build_redis_pool_kwargs includes retry config when attempts > 0."""
        kwargs = build_redis_pool_kwargs(
            connect_timeout=5.0,
            socket_timeout=5.0,
            retry_attempts=3,
            retry_base_delay=0.1,
            retry_max_delay=1.0,
            retry_on_timeout=True,
            max_connections=None,
            ssl_enabled=False,
            ssl_check_hostname=False,
            ssl_cert_reqs="none",
            ssl_ca_certs=None,
            ssl_certfile=None,
            ssl_keyfile=None,
        )

        assert "retry" in kwargs
        assert isinstance(kwargs["retry"], Retry)

    def test_build_redis_pool_kwargs_omits_retry_when_attempts_zero(self) -> None:
        """build_redis_pool_kwargs omits retry when attempts is 0."""
        kwargs = build_redis_pool_kwargs(
            connect_timeout=5.0,
            socket_timeout=5.0,
            retry_attempts=0,
            retry_base_delay=0.1,
            retry_max_delay=1.0,
            retry_on_timeout=True,
            max_connections=None,
            ssl_enabled=False,
            ssl_check_hostname=False,
            ssl_cert_reqs="none",
            ssl_ca_certs=None,
            ssl_certfile=None,
            ssl_keyfile=None,
        )

        assert "retry" not in kwargs

    def test_build_redis_pool_kwargs_includes_max_connections_when_provided(self) -> None:
        """build_redis_pool_kwargs includes max_connections when not None."""
        kwargs = build_redis_pool_kwargs(
            connect_timeout=5.0,
            socket_timeout=5.0,
            retry_attempts=0,
            retry_base_delay=0.1,
            retry_max_delay=1.0,
            retry_on_timeout=True,
            max_connections=50,
            ssl_enabled=False,
            ssl_check_hostname=False,
            ssl_cert_reqs="none",
            ssl_ca_certs=None,
            ssl_certfile=None,
            ssl_keyfile=None,
        )

        assert kwargs["max_connections"] == 50

    def test_build_redis_pool_kwargs_omits_max_connections_when_none(self) -> None:
        """build_redis_pool_kwargs omits max_connections when None."""
        kwargs = build_redis_pool_kwargs(
            connect_timeout=5.0,
            socket_timeout=5.0,
            retry_attempts=0,
            retry_base_delay=0.1,
            retry_max_delay=1.0,
            retry_on_timeout=True,
            max_connections=None,
            ssl_enabled=False,
            ssl_check_hostname=False,
            ssl_cert_reqs="none",
            ssl_ca_certs=None,
            ssl_certfile=None,
            ssl_keyfile=None,
        )

        assert "max_connections" not in kwargs

    def test_build_redis_pool_kwargs_includes_ssl_when_enabled(self) -> None:
        """build_redis_pool_kwargs includes SSL settings when ssl_enabled is True."""
        kwargs = build_redis_pool_kwargs(
            connect_timeout=5.0,
            socket_timeout=5.0,
            retry_attempts=0,
            retry_base_delay=0.1,
            retry_max_delay=1.0,
            retry_on_timeout=True,
            max_connections=None,
            ssl_enabled=True,
            ssl_check_hostname=True,
            ssl_cert_reqs="required",
            ssl_ca_certs="/path/to/ca.crt",
            ssl_certfile="/path/to/cert.crt",
            ssl_keyfile="/path/to/key.key",
        )

        assert kwargs["ssl_check_hostname"] is True
        assert kwargs["ssl_cert_reqs"] == "required"
        assert kwargs["ssl_ca_certs"] == "/path/to/ca.crt"
        assert kwargs["ssl_certfile"] == "/path/to/cert.crt"
        assert kwargs["ssl_keyfile"] == "/path/to/key.key"

    def test_build_redis_pool_kwargs_omits_ssl_when_disabled(self) -> None:
        """build_redis_pool_kwargs omits SSL settings when ssl_enabled is False."""
        kwargs = build_redis_pool_kwargs(
            connect_timeout=5.0,
            socket_timeout=5.0,
            retry_attempts=0,
            retry_base_delay=0.1,
            retry_max_delay=1.0,
            retry_on_timeout=True,
            max_connections=None,
            ssl_enabled=False,
            ssl_check_hostname=False,
            ssl_cert_reqs="none",
            ssl_ca_certs=None,
            ssl_certfile=None,
            ssl_keyfile=None,
        )

        assert "ssl_check_hostname" not in kwargs
        assert "ssl_cert_reqs" not in kwargs
        assert "ssl_ca_certs" not in kwargs


class TestBuildArqRedisSettings:
    """Tests for build_arq_redis_settings function."""

    def test_build_arq_redis_settings_creates_settings_object(self) -> None:
        """build_arq_redis_settings creates a RedisSettings object with correct values."""
        settings = build_arq_redis_settings(
            host="localhost",
            port=6379,
            database=0,
            username=None,
            password=None,
            ssl_enabled=False,
            ssl_keyfile=None,
            ssl_certfile=None,
            ssl_cert_reqs="none",
            ssl_ca_certs=None,
            ssl_check_hostname=False,
            connect_timeout=5,
            connect_retries=5,
            retry_delay=1,
            max_connections=None,
            retry_on_timeout=True,
        )

        assert isinstance(settings, RedisSettings)
        assert settings.host == "localhost"
        assert settings.port == 6379
        assert settings.database == 0
        assert settings.username is None
        assert settings.password is None
        assert settings.ssl is False
        assert settings.conn_timeout == 5
        assert settings.conn_retries == 5
        assert settings.conn_retry_delay == 1
        assert settings.max_connections is None
        assert settings.retry_on_timeout is True

    def test_build_arq_redis_settings_maps_ssl_parameter(self) -> None:
        """build_arq_redis_settings maps ssl_enabled to ssl parameter."""
        settings_with_ssl = build_arq_redis_settings(
            host="localhost",
            port=6379,
            database=0,
            username=None,
            password=None,
            ssl_enabled=True,
            ssl_keyfile="/path/to/key.key",
            ssl_certfile="/path/to/cert.crt",
            ssl_cert_reqs="required",
            ssl_ca_certs="/path/to/ca.crt",
            ssl_check_hostname=True,
            connect_timeout=5,
            connect_retries=5,
            retry_delay=1,
            max_connections=None,
            retry_on_timeout=True,
        )

        assert settings_with_ssl.ssl is True
        assert settings_with_ssl.ssl_keyfile == "/path/to/key.key"
        assert settings_with_ssl.ssl_certfile == "/path/to/cert.crt"
        assert settings_with_ssl.ssl_cert_reqs == "required"
        assert settings_with_ssl.ssl_ca_certs == "/path/to/ca.crt"
        assert settings_with_ssl.ssl_check_hostname is True

    def test_build_arq_redis_settings_includes_credentials(self) -> None:
        """build_arq_redis_settings includes username and password when provided."""
        settings = build_arq_redis_settings(
            host="redis.example.com",
            port=6379,
            database=1,
            username="admin",
            password="secret",
            ssl_enabled=False,
            ssl_keyfile=None,
            ssl_certfile=None,
            ssl_cert_reqs="none",
            ssl_ca_certs=None,
            ssl_check_hostname=False,
            connect_timeout=10,
            connect_retries=3,
            retry_delay=2,
            max_connections=50,
            retry_on_timeout=False,
        )

        assert settings.host == "redis.example.com"
        assert settings.port == 6379
        assert settings.database == 1
        assert settings.username == "admin"
        assert settings.password == "secret"


class TestRedisCachePoolInitialization:
    """Tests for cache pool creation and cleanup."""

    @pytest.mark.asyncio
    async def test_create_redis_cache_pool_success(self) -> None:
        """create_redis_cache_pool successfully initializes cache pool."""
        cache_settings = RedisCacheSettings(
            REDIS_CACHE_HOST="localhost",
            REDIS_CACHE_PORT=6379,
            REDIS_CACHE_DB=0,
            REDIS_CACHE_CONNECT_TIMEOUT=5.0,
            REDIS_CACHE_SOCKET_TIMEOUT=5.0,
            REDIS_CACHE_RETRY_ATTEMPTS=3,
            REDIS_CACHE_RETRY_BASE_DELAY=0.1,
            REDIS_CACHE_RETRY_MAX_DELAY=1.0,
        )

        mock_pool = AsyncMock(spec=ConnectionPool)
        mock_client = AsyncMock(spec=Redis)
        mock_client.ping = AsyncMock()

        with (
            patch("src.app.core.setup.redis.ConnectionPool.from_url") as mock_from_url,
            patch("src.app.core.setup.redis.Redis.from_pool") as mock_from_pool,
        ):
            mock_from_url.return_value = mock_pool
            mock_from_pool.return_value = mock_client

            await create_redis_cache_pool(cache_settings)

            assert cache.pool == mock_pool
            assert cache.client == mock_client
            mock_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_redis_cache_pool_ping_failure_cleans_up(self) -> None:
        """create_redis_cache_pool cleans up on ping failure."""
        cache_settings = RedisCacheSettings()

        mock_pool = AsyncMock(spec=ConnectionPool)
        mock_client = AsyncMock(spec=Redis)
        mock_client.ping = AsyncMock(side_effect=Exception("Connection failed"))
        mock_client.aclose = AsyncMock()

        with (
            patch("src.app.core.setup.redis.ConnectionPool.from_url") as mock_from_url,
            patch("src.app.core.setup.redis.Redis.from_pool") as mock_from_pool,
        ):
            mock_from_url.return_value = mock_pool
            mock_from_pool.return_value = mock_client

            with pytest.raises(Exception):
                await create_redis_cache_pool(cache_settings)

            mock_client.aclose.assert_called_once()
            mock_pool.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_redis_cache_pool_cleans_up_resources(self) -> None:
        """close_redis_cache_pool closes client and pool resources."""
        mock_client = AsyncMock(spec=Redis)
        mock_pool = AsyncMock(spec=ConnectionPool)

        cache.client = mock_client
        cache.pool = mock_pool

        await close_redis_cache_pool()

        assert cache.client is None
        assert cache.pool is None
        mock_client.aclose.assert_called_once()
        mock_pool.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_redis_cache_pool_handles_missing_resources(self) -> None:
        """close_redis_cache_pool handles case when resources are already None."""
        cache.client = None
        cache.pool = None

        # Should not raise an error
        await close_redis_cache_pool()

        assert cache.client is None
        assert cache.pool is None


class TestRedisQueuePoolInitialization:
    """Tests for queue pool creation and cleanup."""

    @pytest.mark.asyncio
    async def test_create_redis_queue_pool_success(self) -> None:
        """create_redis_queue_pool successfully initializes queue pool."""
        queue_settings = RedisQueueSettings(
            REDIS_QUEUE_HOST="localhost",
            REDIS_QUEUE_PORT=6379,
            REDIS_QUEUE_DB=0,
            REDIS_QUEUE_CONNECT_TIMEOUT=5,
            REDIS_QUEUE_CONNECT_RETRIES=5,
            REDIS_QUEUE_RETRY_DELAY=1,
        )

        mock_pool = AsyncMock()
        mock_pool.ping = AsyncMock()

        with patch("src.app.core.setup.create_pool") as mock_create_pool:
            mock_create_pool.return_value = mock_pool

            await create_redis_queue_pool(queue_settings)

            assert queue.pool == mock_pool
            mock_pool.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_redis_queue_pool_ping_failure_cleans_up(self) -> None:
        """create_redis_queue_pool cleans up on ping failure."""
        queue_settings = RedisQueueSettings()

        mock_pool = AsyncMock()
        mock_pool.ping = AsyncMock(side_effect=Exception("Connection failed"))
        mock_pool.aclose = AsyncMock()

        with patch("src.app.core.setup.create_pool") as mock_create_pool:
            mock_create_pool.return_value = mock_pool

            with pytest.raises(Exception):
                await create_redis_queue_pool(queue_settings)

            mock_pool.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_redis_queue_pool_cleans_up_resources(self) -> None:
        """close_redis_queue_pool closes pool resource."""
        mock_pool = AsyncMock()

        queue.pool = mock_pool

        await close_redis_queue_pool()

        assert queue.pool is None
        mock_pool.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_redis_queue_pool_handles_missing_resource(self) -> None:
        """close_redis_queue_pool handles case when pool is already None."""
        queue.pool = None

        # Should not raise an error
        await close_redis_queue_pool()

        assert queue.pool is None


class TestRedisRateLimiterPoolInitialization:
    """Tests for rate limiter pool creation and cleanup."""

    @pytest.mark.asyncio
    async def test_create_redis_rate_limit_pool_success(self) -> None:
        """create_redis_rate_limit_pool successfully initializes rate limiter."""
        rate_limit_settings = RedisRateLimiterSettings(
            REDIS_RATE_LIMIT_HOST="localhost",
            REDIS_RATE_LIMIT_PORT=6379,
            REDIS_RATE_LIMIT_DB=0,
            REDIS_RATE_LIMIT_CONNECT_TIMEOUT=5.0,
            REDIS_RATE_LIMIT_SOCKET_TIMEOUT=5.0,
            REDIS_RATE_LIMIT_RETRY_ATTEMPTS=3,
            REDIS_RATE_LIMIT_RETRY_BASE_DELAY=0.1,
            REDIS_RATE_LIMIT_RETRY_MAX_DELAY=1.0,
        )

        mock_client = AsyncMock(spec=Redis)
        mock_client.ping = AsyncMock()

        with patch.object(rate_limiter, "initialize") as mock_init:
            with patch.object(rate_limiter, "get_client", return_value=mock_client):
                await create_redis_rate_limit_pool(rate_limit_settings)

                mock_init.assert_called_once()
                mock_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_redis_rate_limit_pool_ping_failure_shuts_down(self) -> None:
        """create_redis_rate_limit_pool shuts down on ping failure."""
        rate_limit_settings = RedisRateLimiterSettings()

        mock_client = AsyncMock(spec=Redis)
        mock_client.ping = AsyncMock(side_effect=Exception("Connection failed"))

        with patch.object(rate_limiter, "initialize"):
            with patch.object(rate_limiter, "get_client", return_value=mock_client):
                with patch.object(rate_limiter, "shutdown") as mock_shutdown:
                    with pytest.raises(Exception):
                        await create_redis_rate_limit_pool(rate_limit_settings)

                    mock_shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_redis_rate_limit_pool_shuts_down(self) -> None:
        """close_redis_rate_limit_pool calls rate_limiter.shutdown."""
        with patch.object(rate_limiter, "shutdown") as mock_shutdown:
            await close_redis_rate_limit_pool()

            mock_shutdown.assert_called_once()


class TestRedisCacheSettingsMappingFromConfig:
    """Tests for Redis cache settings mapping from configuration."""

    def test_redis_cache_settings_builds_correct_url(self) -> None:
        """RedisCacheSettings builds correct Redis URL."""
        settings = RedisCacheSettings(
            REDIS_CACHE_HOST="cache.example.com",
            REDIS_CACHE_PORT=6380,
            REDIS_CACHE_DB=1,
            REDIS_CACHE_USERNAME="user",
            REDIS_CACHE_PASSWORD="pass",
            REDIS_CACHE_SSL=True,
        )

        assert "rediss://" in settings.REDIS_CACHE_URL
        assert "user:pass@" in settings.REDIS_CACHE_URL
        assert "cache.example.com:6380" in settings.REDIS_CACHE_URL
        assert "/1" in settings.REDIS_CACHE_URL

    def test_redis_cache_settings_url_without_auth(self) -> None:
        """RedisCacheSettings builds URL without credentials when not provided."""
        settings = RedisCacheSettings(
            REDIS_CACHE_HOST="localhost",
            REDIS_CACHE_PORT=6379,
            REDIS_CACHE_DB=0,
        )

        assert settings.REDIS_CACHE_URL == "redis://localhost:6379/0"

    def test_redis_cache_settings_url_with_password_only(self) -> None:
        """RedisCacheSettings includes password in URL when only password provided."""
        settings = RedisCacheSettings(
            REDIS_CACHE_HOST="localhost",
            REDIS_CACHE_PORT=6379,
            REDIS_CACHE_DB=0,
            REDIS_CACHE_PASSWORD="secret",
        )

        assert ":secret@" in settings.REDIS_CACHE_URL


class TestRedisQueueSettingsMappingFromConfig:
    """Tests for Redis queue settings mapping from configuration."""

    def test_redis_queue_settings_builds_correct_url(self) -> None:
        """RedisQueueSettings builds correct Redis URL."""
        settings = RedisQueueSettings(
            REDIS_QUEUE_HOST="queue.example.com",
            REDIS_QUEUE_PORT=6380,
            REDIS_QUEUE_DB=2,
            REDIS_QUEUE_USERNAME="admin",
            REDIS_QUEUE_PASSWORD="secret",
            REDIS_QUEUE_SSL=True,
        )

        assert "rediss://" in settings.REDIS_QUEUE_URL
        assert "admin:secret@" in settings.REDIS_QUEUE_URL
        assert "queue.example.com:6380" in settings.REDIS_QUEUE_URL
        assert "/2" in settings.REDIS_QUEUE_URL

    def test_redis_queue_settings_url_default_values(self) -> None:
        """RedisQueueSettings uses default values for unspecified settings."""
        settings = RedisQueueSettings()

        assert settings.REDIS_QUEUE_HOST == "localhost"
        assert settings.REDIS_QUEUE_PORT == 6379
        assert settings.REDIS_QUEUE_DB == 0
        assert "localhost:6379/0" in settings.REDIS_QUEUE_URL


class TestRedisRateLimiterSettingsMappingFromConfig:
    """Tests for Redis rate limiter settings mapping from configuration."""

    def test_redis_rate_limit_settings_builds_correct_url(self) -> None:
        """RedisRateLimiterSettings builds correct Redis URL."""
        settings = RedisRateLimiterSettings(
            REDIS_RATE_LIMIT_HOST="ratelimit.example.com",
            REDIS_RATE_LIMIT_PORT=6380,
            REDIS_RATE_LIMIT_DB=3,
            REDIS_RATE_LIMIT_USERNAME="ratelimit_user",
            REDIS_RATE_LIMIT_PASSWORD="ratelimit_pass",
            REDIS_RATE_LIMIT_SSL=True,
        )

        assert "rediss://" in settings.REDIS_RATE_LIMIT_URL
        assert "ratelimit_user:ratelimit_pass@" in settings.REDIS_RATE_LIMIT_URL
        assert "ratelimit.example.com:6380" in settings.REDIS_RATE_LIMIT_URL
        assert "/3" in settings.REDIS_RATE_LIMIT_URL

    def test_redis_rate_limit_settings_url_default_values(self) -> None:
        """RedisRateLimiterSettings uses default values."""
        settings = RedisRateLimiterSettings()

        assert settings.REDIS_RATE_LIMIT_HOST == "localhost"
        assert settings.REDIS_RATE_LIMIT_PORT == 6379
        assert settings.REDIS_RATE_LIMIT_DB == 0


class TestPartialStartupFailureUnwindsResources:
    """Tests for proper resource cleanup on partial startup failure."""

    @pytest.mark.asyncio
    async def test_queue_pool_failure_leaves_cache_pool_intact(self) -> None:
        """Queue pool failure doesn't affect initialized cache pool."""
        cache_settings = RedisCacheSettings()
        queue_settings = RedisQueueSettings()

        mock_cache_pool = AsyncMock(spec=ConnectionPool)
        mock_cache_client = AsyncMock(spec=Redis)
        mock_cache_client.ping = AsyncMock()

        mock_queue_pool = AsyncMock()
        mock_queue_pool.ping = AsyncMock(side_effect=Exception("Queue connection failed"))
        mock_queue_pool.aclose = AsyncMock()

        # Initialize cache pool
        with (
            patch("src.app.core.setup.redis.ConnectionPool.from_url") as mock_from_url,
            patch("src.app.core.setup.redis.Redis.from_pool") as mock_from_pool,
        ):
            mock_from_url.return_value = mock_cache_pool
            mock_from_pool.return_value = mock_cache_client

            await create_redis_cache_pool(cache_settings)

        # Try to initialize queue pool and fail
        with patch("src.app.core.setup.create_pool") as mock_create_pool:
            mock_create_pool.return_value = mock_queue_pool

            with pytest.raises(Exception):
                await create_redis_queue_pool(queue_settings)

        # Cache pool should still be initialized
        assert cache.pool == mock_cache_pool
        assert cache.client == mock_cache_client

        # Clean up
        cache.client = None
        cache.pool = None
        queue.pool = None

    @pytest.mark.asyncio
    async def test_rate_limiter_failure_leaves_cache_and_queue_intact(self) -> None:
        """Rate limiter failure doesn't affect initialized cache and queue pools."""
        cache_settings = RedisCacheSettings()
        queue_settings = RedisQueueSettings()
        rate_limit_settings = RedisRateLimiterSettings()

        mock_cache_pool = AsyncMock(spec=ConnectionPool)
        mock_cache_client = AsyncMock(spec=Redis)
        mock_cache_client.ping = AsyncMock()

        mock_queue_pool = AsyncMock()
        mock_queue_pool.ping = AsyncMock()

        mock_ratelimit_client = AsyncMock(spec=Redis)
        mock_ratelimit_client.ping = AsyncMock(side_effect=Exception("Rate limiter connection failed"))

        # Initialize cache
        with (
            patch("src.app.core.setup.redis.ConnectionPool.from_url") as mock_from_url,
            patch("src.app.core.setup.redis.Redis.from_pool") as mock_from_pool,
        ):
            mock_from_url.return_value = mock_cache_pool
            mock_from_pool.return_value = mock_cache_client

            await create_redis_cache_pool(cache_settings)

        # Initialize queue
        with patch("src.app.core.setup.create_pool") as mock_create_pool:
            mock_create_pool.return_value = mock_queue_pool

            await create_redis_queue_pool(queue_settings)

        # Try to initialize rate limiter and fail
        with patch.object(rate_limiter, "initialize"):
            with patch.object(rate_limiter, "get_client", return_value=mock_ratelimit_client):
                with patch.object(rate_limiter, "shutdown"):
                    with pytest.raises(Exception):
                        await create_redis_rate_limit_pool(rate_limit_settings)

        # Cache and queue pools should still be initialized
        assert cache.pool == mock_cache_pool
        assert cache.client == mock_cache_client
        assert queue.pool == mock_queue_pool

        # Clean up
        cache.client = None
        cache.pool = None
        queue.pool = None


class TestRedisPoolKwargsFromCacheSettings:
    """Tests for building Redis pool kwargs from cache settings."""

    def test_build_pool_kwargs_from_cache_settings(self) -> None:
        """Pool kwargs correctly built from RedisCacheSettings."""
        settings = RedisCacheSettings(
            REDIS_CACHE_CONNECT_TIMEOUT=10.0,
            REDIS_CACHE_SOCKET_TIMEOUT=5.0,
            REDIS_CACHE_RETRY_ATTEMPTS=5,
            REDIS_CACHE_RETRY_BASE_DELAY=0.2,
            REDIS_CACHE_RETRY_MAX_DELAY=2.0,
            REDIS_CACHE_RETRY_ON_TIMEOUT=False,
            REDIS_CACHE_MAX_CONNECTIONS=100,
            REDIS_CACHE_SSL=True,
            REDIS_CACHE_SSL_CHECK_HOSTNAME=True,
            REDIS_CACHE_SSL_CERT_REQS=RedisSSLCertRequirements.REQUIRED,
            REDIS_CACHE_SSL_CA_CERTS="/path/to/ca.crt",
            REDIS_CACHE_SSL_CERTFILE="/path/to/cert.crt",
            REDIS_CACHE_SSL_KEYFILE="/path/to/key.key",
        )

        kwargs = build_redis_pool_kwargs(
            connect_timeout=settings.REDIS_CACHE_CONNECT_TIMEOUT,
            socket_timeout=settings.REDIS_CACHE_SOCKET_TIMEOUT,
            retry_attempts=settings.REDIS_CACHE_RETRY_ATTEMPTS,
            retry_base_delay=settings.REDIS_CACHE_RETRY_BASE_DELAY,
            retry_max_delay=settings.REDIS_CACHE_RETRY_MAX_DELAY,
            retry_on_timeout=settings.REDIS_CACHE_RETRY_ON_TIMEOUT,
            max_connections=settings.REDIS_CACHE_MAX_CONNECTIONS,
            ssl_enabled=settings.REDIS_CACHE_SSL,
            ssl_check_hostname=settings.REDIS_CACHE_SSL_CHECK_HOSTNAME,
            ssl_cert_reqs=settings.REDIS_CACHE_SSL_CERT_REQS.value,
            ssl_ca_certs=settings.REDIS_CACHE_SSL_CA_CERTS,
            ssl_certfile=settings.REDIS_CACHE_SSL_CERTFILE,
            ssl_keyfile=settings.REDIS_CACHE_SSL_KEYFILE,
        )

        assert kwargs["socket_connect_timeout"] == 10.0
        assert kwargs["socket_timeout"] == 5.0
        assert kwargs["retry_on_timeout"] is False
        assert kwargs["max_connections"] == 100
        assert kwargs["ssl_check_hostname"] is True
        assert kwargs["ssl_cert_reqs"] == "required"


class TestArqRedisSettingsFromQueueSettings:
    """Tests for building ARQ Redis settings from queue settings."""

    def test_build_arq_settings_from_queue_settings(self) -> None:
        """ARQ Redis settings correctly built from RedisQueueSettings."""
        settings = RedisQueueSettings(
            REDIS_QUEUE_HOST="queue.example.com",
            REDIS_QUEUE_PORT=6380,
            REDIS_QUEUE_DB=2,
            REDIS_QUEUE_USERNAME="queue_user",
            REDIS_QUEUE_PASSWORD="queue_pass",
            REDIS_QUEUE_CONNECT_TIMEOUT=10,
            REDIS_QUEUE_CONNECT_RETRIES=5,
            REDIS_QUEUE_RETRY_DELAY=2,
            REDIS_QUEUE_MAX_CONNECTIONS=50,
            REDIS_QUEUE_RETRY_ON_TIMEOUT=False,
            REDIS_QUEUE_SSL=True,
            REDIS_QUEUE_SSL_CHECK_HOSTNAME=True,
            REDIS_QUEUE_SSL_CERT_REQS=RedisSSLCertRequirements.OPTIONAL,
            REDIS_QUEUE_SSL_CA_CERTS="/path/to/ca.crt",
            REDIS_QUEUE_SSL_CERTFILE="/path/to/cert.crt",
            REDIS_QUEUE_SSL_KEYFILE="/path/to/key.key",
        )

        arq_settings = build_arq_redis_settings(
            host=settings.REDIS_QUEUE_HOST,
            port=settings.REDIS_QUEUE_PORT,
            database=settings.REDIS_QUEUE_DB,
            username=settings.REDIS_QUEUE_USERNAME,
            password=settings.REDIS_QUEUE_PASSWORD,
            ssl_enabled=settings.REDIS_QUEUE_SSL,
            ssl_keyfile=settings.REDIS_QUEUE_SSL_KEYFILE,
            ssl_certfile=settings.REDIS_QUEUE_SSL_CERTFILE,
            ssl_cert_reqs=settings.REDIS_QUEUE_SSL_CERT_REQS.value,
            ssl_ca_certs=settings.REDIS_QUEUE_SSL_CA_CERTS,
            ssl_check_hostname=settings.REDIS_QUEUE_SSL_CHECK_HOSTNAME,
            connect_timeout=settings.REDIS_QUEUE_CONNECT_TIMEOUT,
            connect_retries=settings.REDIS_QUEUE_CONNECT_RETRIES,
            retry_delay=settings.REDIS_QUEUE_RETRY_DELAY,
            max_connections=settings.REDIS_QUEUE_MAX_CONNECTIONS,
            retry_on_timeout=settings.REDIS_QUEUE_RETRY_ON_TIMEOUT,
        )

        assert isinstance(arq_settings, RedisSettings)
        assert arq_settings.host == "queue.example.com"
        assert arq_settings.port == 6380
        assert arq_settings.database == 2
        assert arq_settings.username == "queue_user"
        assert arq_settings.password == "queue_pass"
        assert arq_settings.conn_timeout == 10
        assert arq_settings.conn_retries == 5
        assert arq_settings.conn_retry_delay == 2
        assert arq_settings.max_connections == 50
        assert arq_settings.retry_on_timeout is False
        assert arq_settings.ssl is True
        assert arq_settings.ssl_check_hostname is True
        assert arq_settings.ssl_cert_reqs == "optional"
