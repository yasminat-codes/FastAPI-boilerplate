"""Migration verification command for CI and schema-drift checks."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from . import migrations

PROGRAM_NAME = "db-migrate-verify"
DEFAULT_VERIFICATION_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("upgrade", "head"),
    ("check",),
)


def build_verification_commands() -> tuple[tuple[str, ...], ...]:
    """Return the default command sequence used to verify migrations."""

    return DEFAULT_VERIFICATION_COMMANDS


def run_verification_command(argv: Sequence[str]) -> None:
    """Run a single Alembic verification command via the canonical config."""

    migrations.alembic_config.main(
        migrations.build_alembic_argv(argv),
        prog=PROGRAM_NAME,
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Apply migrations and fail if model metadata would autogenerate new drift."""

    command_args = list(sys.argv[1:] if argv is None else argv)
    if command_args:
        raise SystemExit(f"{PROGRAM_NAME} does not accept additional arguments.")

    for command in build_verification_commands():
        run_verification_command(command)
