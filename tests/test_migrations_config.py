import tomllib
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from src.app.core.db.idempotency_key import IdempotencyKey
from src.app.core.db.token_blacklist import TokenBlacklist
from src.app.core.db.webhook_event import WebhookEvent
from src.app.core.db.workflow_execution import WorkflowExecution
from src.app.models.post import Post
from src.app.models.rate_limit import RateLimit
from src.app.models.tier import Tier
from src.scripts import migrations, verify_migrations

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "src" / "migrations"


def _resolve_script_directory(config_path: Path) -> Path:
    config = Config(str(config_path))
    return Path(ScriptDirectory.from_config(config).dir).resolve()


def test_root_alembic_config_resolves_repo_root_paths() -> None:
    script_directory = _resolve_script_directory(REPO_ROOT / "alembic.ini")

    assert script_directory == MIGRATIONS_DIR


def test_src_alembic_config_remains_compatible_from_repo_root() -> None:
    script_directory = _resolve_script_directory(REPO_ROOT / "src" / "alembic.ini")

    assert script_directory == MIGRATIONS_DIR


def test_db_migrate_console_script_is_registered() -> None:
    pyproject_data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    assert pyproject_data["project"]["scripts"]["db-migrate"] == "src.scripts.migrations:main"
    assert pyproject_data["project"]["scripts"]["db-migrate-verify"] == "src.scripts.verify_migrations:main"


def test_build_alembic_argv_uses_canonical_root_config() -> None:
    argv = migrations.build_alembic_argv(["upgrade", "head"])

    assert argv == ["-c", str(REPO_ROOT / "alembic.ini"), "upgrade", "head"]


def test_db_migrate_main_delegates_to_alembic_cli(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_main(argv: list[str], prog: str) -> None:
        captured["argv"] = argv
        captured["prog"] = prog

    monkeypatch.setattr(migrations.alembic_config, "main", fake_main)

    migrations.main(["heads"])

    assert captured == {
        "argv": ["-c", str(REPO_ROOT / "alembic.ini"), "heads"],
        "prog": migrations.PROGRAM_NAME,
    }


def test_build_verification_commands_uses_upgrade_then_check() -> None:
    assert verify_migrations.build_verification_commands() == (
        ("upgrade", "head"),
        ("check",),
    )


def test_db_migrate_verify_main_runs_each_verification_command(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    def fake_main(argv: list[str], prog: str) -> None:
        captured.append(
            {
                "argv": argv,
                "prog": prog,
            }
        )

    monkeypatch.setattr(verify_migrations.migrations.alembic_config, "main", fake_main)

    verify_migrations.main([])

    assert captured == [
        {
            "argv": ["-c", str(REPO_ROOT / "alembic.ini"), "upgrade", "head"],
            "prog": verify_migrations.PROGRAM_NAME,
        },
        {
            "argv": ["-c", str(REPO_ROOT / "alembic.ini"), "check"],
            "prog": verify_migrations.PROGRAM_NAME,
        },
    ]


def test_db_migrate_verify_rejects_cli_arguments() -> None:
    try:
        verify_migrations.main(["check"])
    except SystemExit as exc:
        assert exc.code == "db-migrate-verify does not accept additional arguments."
    else:
        raise AssertionError("Expected db-migrate-verify to reject CLI arguments")


def test_primary_key_columns_do_not_duplicate_unique_constraints() -> None:
    for column in (
        Tier.__table__.c.id,
        TokenBlacklist.__table__.c.id,
        RateLimit.__table__.c.id,
        Post.__table__.c.id,
        IdempotencyKey.__table__.c.id,
        WebhookEvent.__table__.c.id,
        WorkflowExecution.__table__.c.id,
    ):
        assert column.unique is not True
