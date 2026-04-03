"""Repository-aware Alembic wrapper for the template's developer workflow."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from alembic import config as alembic_config

PROGRAM_NAME = "db-migrate"
REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = REPO_ROOT / "alembic.ini"


def build_alembic_argv(argv: Sequence[str] | None = None) -> list[str]:
    """Inject the canonical Alembic config into the forwarded CLI arguments."""

    command_args = list(sys.argv[1:] if argv is None else argv)
    return ["-c", str(ALEMBIC_CONFIG_PATH), *command_args]


def main(argv: Sequence[str] | None = None) -> None:
    """Run the Alembic CLI against the template's canonical configuration."""

    alembic_config.main(build_alembic_argv(argv), prog=PROGRAM_NAME)
