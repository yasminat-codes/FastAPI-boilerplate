"""Integration tests for database connectivity and migrations."""

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.config import DatabaseSSLMode, load_settings
from src.app.core.db import database as database_module
from src.app.core.db.database import (
    build_database_connect_args,
    build_database_engine_kwargs,
    build_database_ssl_context,
)
from src.app.core.db.sessions import (
    DatabaseSessionScope,
    database_transaction,
    open_database_session,
)


class TestDatabaseEngineConfiguration:
    """Test database engine configuration respects settings."""

    def test_engine_kwargs_include_all_pool_settings(self) -> None:
        """Engine kwargs should include pool_size, overflow, pre_ping, recycle."""
        settings = load_settings(
            _env_file=None,
            DATABASE_POOL_SIZE=15,
            DATABASE_MAX_OVERFLOW=25,
            DATABASE_POOL_PRE_PING=True,
            DATABASE_POOL_USE_LIFO=False,
            DATABASE_POOL_RECYCLE=3600,
            DATABASE_POOL_TIMEOUT=45,
        )

        kwargs = build_database_engine_kwargs(settings)

        assert kwargs["pool_size"] == 15
        assert kwargs["max_overflow"] == 25
        assert kwargs["pool_pre_ping"] is True
        assert kwargs["pool_use_lifo"] is False
        assert kwargs["pool_recycle"] == 3600
        assert kwargs["pool_timeout"] == 45

    def test_engine_kwargs_always_include_pool_reset_on_return_rollback(self) -> None:
        """Engine should always reset pool connections on return with rollback."""
        settings = load_settings(_env_file=None)

        kwargs = build_database_engine_kwargs(settings)

        assert kwargs["pool_reset_on_return"] == "rollback"

    def test_engine_kwargs_include_connect_args_from_settings(self) -> None:
        """Engine kwargs should include all connect_args built from settings."""
        settings = load_settings(
            _env_file=None,
            DATABASE_CONNECT_TIMEOUT=5.0,
            DATABASE_COMMAND_TIMEOUT=30.0,
        )

        kwargs = build_database_engine_kwargs(settings)

        assert "connect_args" in kwargs
        assert kwargs["connect_args"]["timeout"] == 5.0
        assert kwargs["connect_args"]["command_timeout"] == 30.0

    def test_connect_args_include_timeouts(self) -> None:
        """Connect args should include connection and command timeouts."""
        settings = load_settings(
            _env_file=None,
            DATABASE_CONNECT_TIMEOUT=8.5,
            DATABASE_COMMAND_TIMEOUT=120.0,
        )

        connect_args = build_database_connect_args(settings)

        assert connect_args["timeout"] == 8.5
        assert connect_args["command_timeout"] == 120.0

    def test_connect_args_include_server_settings_when_configured(self) -> None:
        """Connect args should include server_settings when timeouts are set."""
        settings = load_settings(
            _env_file=None,
            DATABASE_STATEMENT_TIMEOUT_MS=5000,
            DATABASE_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS=2000,
        )

        connect_args = build_database_connect_args(settings)

        assert "server_settings" in connect_args
        assert connect_args["server_settings"]["statement_timeout"] == "5000"
        assert (
            connect_args["server_settings"]["idle_in_transaction_session_timeout"]
            == "2000"
        )

    def test_connect_args_omit_server_settings_when_no_timeouts(self) -> None:
        """Connect args should not include server_settings if no timeouts configured."""
        settings = load_settings(
            _env_file=None,
            DATABASE_STATEMENT_TIMEOUT_MS=None,
            DATABASE_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS=None,
        )

        connect_args = build_database_connect_args(settings)

        assert "server_settings" not in connect_args or not connect_args[
            "server_settings"
        ]


class TestDatabaseSSLConfiguration:
    """Test SSL context building from settings."""

    def test_ssl_context_disabled_returns_false(self) -> None:
        """SSL disabled should return False."""
        settings = load_settings(_env_file=None, DATABASE_SSL_MODE=DatabaseSSLMode.DISABLE)

        ssl_context = build_database_ssl_context(settings)

        assert ssl_context is False

    def test_ssl_context_require_creates_context_without_verification(self) -> None:
        """SSL require should create context with verification disabled."""
        settings = load_settings(_env_file=None, DATABASE_SSL_MODE=DatabaseSSLMode.REQUIRE)

        ssl_context = build_database_ssl_context(settings)

        assert ssl_context is not False
        assert ssl_context.check_hostname is False

    def test_ssl_context_verify_ca_enables_ca_verification(self) -> None:
        """SSL verify-ca should enable CA verification."""
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as f:
            ca_file = f.name

        try:
            settings = load_settings(
                _env_file=None,
                DATABASE_SSL_MODE=DatabaseSSLMode.VERIFY_CA,
                DATABASE_SSL_CA_FILE=ca_file,
            )

            with patch("src.app.core.db.database.ssl.create_default_context") as mock_ctx:
                mock_ssl_context = Mock()
                mock_ctx.return_value = mock_ssl_context

                ssl_context = build_database_ssl_context(settings)

                assert ssl_context is not False
                mock_ctx.assert_called_once_with(cafile=ca_file)
        finally:
            Path(ca_file).unlink(missing_ok=True)

    def test_ssl_context_includes_client_cert_when_provided(self) -> None:
        """SSL context should include client certificate when provided."""
        import tempfile

        with (
            tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as ca_file,
            tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as cert_file,
            tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as key_file,
        ):
            ca_path = ca_file.name
            cert_path = cert_file.name
            key_path = key_file.name

        try:
            settings = load_settings(
                _env_file=None,
                DATABASE_SSL_MODE=DatabaseSSLMode.VERIFY_CA,
                DATABASE_SSL_CA_FILE=ca_path,
                DATABASE_SSL_CERT_FILE=cert_path,
                DATABASE_SSL_KEY_FILE=key_path,
            )

            with patch("src.app.core.db.database.ssl.create_default_context") as mock_ctx:
                mock_ssl_context = Mock()
                mock_ctx.return_value = mock_ssl_context

                ssl_context = build_database_ssl_context(settings)

                assert ssl_context is not False
                mock_ssl_context.load_cert_chain.assert_called_once_with(
                    certfile=cert_path,
                    keyfile=key_path,
                )
        finally:
            Path(ca_path).unlink(missing_ok=True)
            Path(cert_path).unlink(missing_ok=True)
            Path(key_path).unlink(missing_ok=True)

    def test_connect_args_include_ssl_context(self) -> None:
        """Connect args should include ssl context from settings."""
        settings = load_settings(_env_file=None, DATABASE_SSL_MODE=DatabaseSSLMode.REQUIRE)

        connect_args = build_database_connect_args(settings)

        assert "ssl" in connect_args
        assert connect_args["ssl"] is not False


class TestAsyncGetDbDependency:
    """Test async_get_db dependency yields and closes sessions properly."""

    @pytest.mark.asyncio
    async def test_async_get_db_yields_session_from_local_session_factory(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """async_get_db should yield session from local_session factory."""
        session = SimpleNamespace(info={})

        @asynccontextmanager
        async def mock_session_factory():
            yield session

        monkeypatch.setattr(
            database_module,
            "local_session",
            mock_session_factory,
        )

        yielded_sessions: list[SimpleNamespace] = []

        async for opened_session in database_module.async_get_db():
            yielded_sessions.append(opened_session)

        assert len(yielded_sessions) == 1
        assert yielded_sessions[0] is session

    @pytest.mark.asyncio
    async def test_async_get_db_tags_session_with_api_request_scope(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """async_get_db should tag session with API_REQUEST scope."""
        session = SimpleNamespace(info={})

        @asynccontextmanager
        async def mock_session_factory():
            yield session

        monkeypatch.setattr(
            database_module,
            "local_session",
            mock_session_factory,
        )

        async for _opened_session in database_module.async_get_db():
            pass

        assert session.info["database_session_scope"] == DatabaseSessionScope.API_REQUEST.value

    @pytest.mark.asyncio
    async def test_async_get_job_db_tags_session_with_background_job_scope(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """async_get_job_db should tag session with BACKGROUND_JOB scope."""
        session = SimpleNamespace(info={})

        @asynccontextmanager
        async def mock_session_factory():
            yield session

        monkeypatch.setattr(
            database_module,
            "local_session",
            mock_session_factory,
        )

        async for _opened_session in database_module.async_get_job_db():
            pass

        assert (
            session.info["database_session_scope"]
            == DatabaseSessionScope.BACKGROUND_JOB.value
        )

    @pytest.mark.asyncio
    async def test_async_get_script_db_tags_session_with_script_scope(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """async_get_script_db should tag session with SCRIPT scope."""
        session = SimpleNamespace(info={})

        @asynccontextmanager
        async def mock_session_factory():
            yield session

        monkeypatch.setattr(
            database_module,
            "local_session",
            mock_session_factory,
        )

        async for _opened_session in database_module.async_get_script_db():
            pass

        assert session.info["database_session_scope"] == DatabaseSessionScope.SCRIPT.value

    @pytest.mark.asyncio
    async def test_async_get_db_closes_session_after_yield(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """async_get_db should close session after context exit."""
        session = AsyncMock()
        session.info = {}

        @asynccontextmanager
        async def mock_session_factory():
            yield session

        monkeypatch.setattr(
            database_module,
            "local_session",
            mock_session_factory,
        )

        yielded_sessions = []
        async for opened_session in database_module.async_get_db():
            yielded_sessions.append(opened_session)

        # Verify the session was yielded and the context manager was properly exited
        assert len(yielded_sessions) == 1
        assert yielded_sessions[0] is session


class TestSessionScopeHelpers:
    """Test session scope helpers work correctly for different scopes."""

    @pytest.mark.asyncio
    async def test_open_database_session_attaches_scope_metadata(self) -> None:
        """open_database_session should attach scope metadata to session.info."""
        session = SimpleNamespace(info={})

        @asynccontextmanager
        async def session_factory():
            yield session

        async with open_database_session(session_factory, DatabaseSessionScope.API_REQUEST):
            pass

        assert session.info["database_session_scope"] == DatabaseSessionScope.API_REQUEST.value
        assert "recommended_boundary" in session.info["database_session_policy"].lower() or (
            "request" in session.info["database_session_policy"].lower()
        )

    @pytest.mark.asyncio
    async def test_open_database_session_with_background_job_scope(self) -> None:
        """open_database_session should work with BACKGROUND_JOB scope."""
        session = SimpleNamespace(info={})

        @asynccontextmanager
        async def session_factory():
            yield session

        async with open_database_session(
            session_factory,
            DatabaseSessionScope.BACKGROUND_JOB,
        ):
            pass

        assert (
            session.info["database_session_scope"]
            == DatabaseSessionScope.BACKGROUND_JOB.value
        )
        assert "background" in session.info["database_session_policy"].lower()

    @pytest.mark.asyncio
    async def test_open_database_session_with_script_scope(self) -> None:
        """open_database_session should work with SCRIPT scope."""
        session = SimpleNamespace(info={})

        @asynccontextmanager
        async def session_factory():
            yield session

        async with open_database_session(session_factory, DatabaseSessionScope.SCRIPT):
            pass

        assert session.info["database_session_scope"] == DatabaseSessionScope.SCRIPT.value
        assert "script" in session.info["database_session_policy"].lower()


class TestTransactionHelpers:
    """Test transaction helpers commit and rollback properly."""

    @pytest.mark.asyncio
    async def test_database_transaction_commits_on_success(self) -> None:
        """database_transaction should commit on successful execution."""
        session = AsyncMock(spec=AsyncSession)

        async with database_transaction(session):
            pass

        session.commit.assert_awaited_once_with()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_database_transaction_rolls_back_on_exception(self) -> None:
        """database_transaction should rollback when exception is raised."""
        session = AsyncMock(spec=AsyncSession)

        with pytest.raises(ValueError, match="test error"):
            async with database_transaction(session):
                raise ValueError("test error")

        session.rollback.assert_awaited_once_with()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_database_transaction_re_raises_exception_after_rollback(self) -> None:
        """database_transaction should re-raise exception after rollback."""
        session = AsyncMock(spec=AsyncSession)

        class CustomError(Exception):
            pass

        with pytest.raises(CustomError, match="original error"):
            async with database_transaction(session):
                raise CustomError("original error")

        session.rollback.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_database_transaction_commit_is_awaited(self) -> None:
        """database_transaction should await session.commit()."""
        session = AsyncMock(spec=AsyncSession)

        async with database_transaction(session):
            assert not session.commit.called

        assert session.commit.await_count == 1

    @pytest.mark.asyncio
    async def test_database_transaction_rollback_is_awaited(self) -> None:
        """database_transaction should await session.rollback()."""
        session = AsyncMock(spec=AsyncSession)

        with pytest.raises(RuntimeError):
            async with database_transaction(session):
                raise RuntimeError("intentional")

        assert session.rollback.await_count == 1


class TestEngineInitializationRetry:
    """Test engine initialization retry logic on transient failures."""

    @pytest.mark.asyncio
    async def test_initialize_database_engine_uses_custom_settings(self) -> None:
        """initialize_database_engine should accept custom settings."""
        settings = load_settings(
            _env_file=None,
            DATABASE_STARTUP_RETRY_ATTEMPTS=1,
            DATABASE_STARTUP_RETRY_BASE_DELAY=0.1,
        )

        fake_engine = Mock()

        @asynccontextmanager
        async def successful_connection():
            yield

        fake_engine.connect = Mock(return_value=successful_connection())

        with patch.object(database_module, "async_engine", fake_engine):
            await database_module.initialize_database_engine(settings)

        fake_engine.connect.assert_called()

    @pytest.mark.asyncio
    async def test_initialize_database_engine_retries_on_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """initialize_database_engine should retry on connection failure."""

        @asynccontextmanager
        async def failing_connection():
            raise RuntimeError("connection failed")
            yield

        @asynccontextmanager
        async def successful_connection():
            yield

        settings = load_settings(
            _env_file=None,
            DATABASE_STARTUP_RETRY_ATTEMPTS=2,
            DATABASE_STARTUP_RETRY_BASE_DELAY=0.1,
            DATABASE_STARTUP_RETRY_MAX_DELAY=0.2,
        )

        fake_engine = Mock()
        fake_engine.connect = Mock(
            side_effect=[
                failing_connection(),
                successful_connection(),
            ]
        )
        sleep_mock = AsyncMock()

        with (
            patch.object(database_module, "async_engine", fake_engine),
            patch("src.app.core.db.database.anyio.sleep", new=sleep_mock),
        ):
            await database_module.initialize_database_engine(settings)

        assert fake_engine.connect.call_count == 2
        sleep_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initialize_database_engine_uses_exponential_backoff(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """initialize_database_engine should use exponential backoff for retries."""

        settings = load_settings(
            _env_file=None,
            DATABASE_STARTUP_RETRY_ATTEMPTS=3,
            DATABASE_STARTUP_RETRY_BASE_DELAY=0.1,
            DATABASE_STARTUP_RETRY_MAX_DELAY=0.5,
        )

        fake_engine = Mock()
        sleep_calls: list[float] = []

        @asynccontextmanager
        async def failing_connection():
            raise RuntimeError("connection failed")
            yield

        async def mock_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        call_count = [0]

        def connection_side_effect():
            call_count[0] += 1
            if call_count[0] <= 4:
                return failing_connection()
            return failing_connection()

        fake_engine.connect = Mock(side_effect=connection_side_effect)
        sleep_mock = AsyncMock(side_effect=mock_sleep)

        with (
            patch.object(database_module, "async_engine", fake_engine),
            patch("src.app.core.db.database.anyio.sleep", new=sleep_mock),
        ):
            with pytest.raises(RuntimeError, match="connection failed"):
                await database_module.initialize_database_engine(settings)

        assert len(sleep_calls) == 3

    @pytest.mark.asyncio
    async def test_initialize_database_engine_raises_after_exhausting_retries(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """initialize_database_engine should raise after retry budget exhausted."""

        settings = load_settings(
            _env_file=None,
            DATABASE_STARTUP_RETRY_ATTEMPTS=1,
            DATABASE_STARTUP_RETRY_BASE_DELAY=0.1,
        )

        @asynccontextmanager
        async def failing_connection():
            raise RuntimeError("permanent failure")
            yield

        fake_engine = Mock()

        def connection_side_effect():
            return failing_connection()

        fake_engine.connect = Mock(side_effect=connection_side_effect)

        with (
            patch.object(database_module, "async_engine", fake_engine),
        ):
            with pytest.raises(RuntimeError, match="permanent failure"):
                await database_module.initialize_database_engine(settings)

        assert fake_engine.connect.call_count == 2

    @pytest.mark.asyncio
    async def test_initialize_database_engine_uses_default_settings_when_none(
        self,
    ) -> None:
        """initialize_database_engine should use default settings when None passed."""

        @asynccontextmanager
        async def successful_connection():
            yield

        fake_engine = Mock()
        fake_engine.connect = Mock(return_value=successful_connection())

        with patch.object(database_module, "async_engine", fake_engine):
            await database_module.initialize_database_engine(db_settings=None)

        fake_engine.connect.assert_called()


class TestDatabaseEngineKwargsPropagation:
    """Test that initialize_database_engine applies correct kwargs."""

    def test_database_engine_kwargs_from_settings_are_complete(self) -> None:
        """DATABASE_ENGINE_KWARGS should contain all required pool and connection settings."""
        engine_kwargs = database_module.DATABASE_ENGINE_KWARGS

        assert "pool_size" in engine_kwargs
        assert "max_overflow" in engine_kwargs
        assert "pool_pre_ping" in engine_kwargs
        assert "pool_use_lifo" in engine_kwargs
        assert "pool_recycle" in engine_kwargs
        assert "pool_timeout" in engine_kwargs
        assert "pool_reset_on_return" in engine_kwargs
        assert "connect_args" in engine_kwargs

    def test_database_engine_kwargs_connect_args_are_present(self) -> None:
        """DATABASE_ENGINE_KWARGS connect_args should include all connection settings."""
        engine_kwargs = database_module.DATABASE_ENGINE_KWARGS
        connect_args = engine_kwargs["connect_args"]

        assert "timeout" in connect_args
        assert "command_timeout" in connect_args
        assert "ssl" in connect_args

    def test_build_database_engine_kwargs_respects_all_settings_fields(self) -> None:
        """build_database_engine_kwargs should include all PostgresSettings fields."""
        settings = load_settings(
            _env_file=None,
            DATABASE_POOL_SIZE=12,
            DATABASE_MAX_OVERFLOW=18,
            DATABASE_POOL_PRE_PING=False,
            DATABASE_POOL_USE_LIFO=True,
            DATABASE_POOL_RECYCLE=1200,
            DATABASE_POOL_TIMEOUT=20,
            DATABASE_CONNECT_TIMEOUT=3.0,
            DATABASE_COMMAND_TIMEOUT=45.0,
        )

        kwargs = build_database_engine_kwargs(settings)

        assert kwargs["pool_size"] == 12
        assert kwargs["max_overflow"] == 18
        assert kwargs["pool_pre_ping"] is False
        assert kwargs["pool_use_lifo"] is True
        assert kwargs["pool_recycle"] == 1200
        assert kwargs["pool_timeout"] == 20


class TestMigrationConfigValidation:
    """Test migration config validates properly."""

    def test_alembic_ini_root_path_exists(self) -> None:
        """Root alembic.ini file should exist."""
        repo_root = Path(__file__).resolve().parents[1]
        alembic_ini = repo_root / "alembic.ini"

        assert alembic_ini.exists(), f"alembic.ini not found at {alembic_ini}"

    def test_alembic_ini_src_path_exists(self) -> None:
        """src/alembic.ini file should exist."""
        repo_root = Path(__file__).resolve().parents[1]
        alembic_ini = repo_root / "src" / "alembic.ini"

        assert alembic_ini.exists(), f"src/alembic.ini not found at {alembic_ini}"

    def test_migrations_directory_exists(self) -> None:
        """Migrations directory should exist."""
        repo_root = Path(__file__).resolve().parents[1]
        migrations_dir = repo_root / "src" / "migrations"

        assert migrations_dir.exists(), f"Migrations directory not found at {migrations_dir}"

    def test_migrations_versions_directory_exists(self) -> None:
        """Migrations versions directory should exist."""
        repo_root = Path(__file__).resolve().parents[1]
        versions_dir = repo_root / "src" / "migrations" / "versions"

        assert versions_dir.exists(), f"Migrations versions dir not found at {versions_dir}"

    def test_alembic_config_can_be_loaded(self) -> None:
        """Alembic configuration files should be loadable."""
        from alembic.config import Config

        repo_root = Path(__file__).resolve().parents[1]
        alembic_ini = repo_root / "alembic.ini"

        config = Config(str(alembic_ini))
        assert config is not None


class TestDatabaseUrlConfiguration:
    """Test database URL configuration from settings."""

    def test_database_url_uses_async_driver(self) -> None:
        """DATABASE_URL should use async PostgreSQL driver."""
        settings = load_settings(_env_file=None)

        assert settings.DATABASE_URL.startswith("postgresql+asyncpg://")

    def test_database_sync_url_uses_sync_driver(self) -> None:
        """DATABASE_SYNC_URL should use sync PostgreSQL driver."""
        settings = load_settings(_env_file=None)

        assert settings.DATABASE_SYNC_URL.startswith("postgresql://")

    def test_database_url_includes_credentials(self) -> None:
        """DATABASE_URL should include username, password, host, port, database."""
        settings = load_settings(
            _env_file=None,
            POSTGRES_USER="testuser",
            POSTGRES_PASSWORD="testpass",
            POSTGRES_SERVER="testhost",
            POSTGRES_PORT=5432,
            POSTGRES_DB="testdb",
        )

        url = settings.DATABASE_URL
        assert "testuser" in url
        assert "testhost" in url
        assert "5432" in url
        assert "testdb" in url
