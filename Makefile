.PHONY: help
help:
	@echo "FastAPI Template - Available Targets"
	@echo "====================================="
	@echo ""
	@echo "Quality Gates:"
	@echo "  lint              Run ruff linter on src and tests"
	@echo "  lint-fix          Fix ruff linting issues automatically"
	@echo "  type              Run mypy type checking"
	@echo "  test              Run pytest test suite"
	@echo "  test-quick        Run tests with minimal output"
	@echo "  test-fail-fast    Run tests, stop on first failure"
	@echo "  check             Run lint, type check, and tests (full quality gate)"
	@echo ""
	@echo "Development:"
	@echo "  install           Install project dependencies (uv sync)"
	@echo "  install-docs      Install dependencies including docs tools"
	@echo "  dev               Run development server with auto-reload"
	@echo "  worker            Run background worker"
	@echo ""
	@echo "Database:"
	@echo "  migrate           Apply database migrations"
	@echo "  migrate-create    Create new migration (use MSG='description')"
	@echo "  migrate-verify    Verify migration integrity"
	@echo ""
	@echo "Documentation:"
	@echo "  docs-build        Build documentation (strict mode)"
	@echo "  docs-serve        Serve documentation locally"
	@echo ""
	@echo "Maintenance:"
	@echo "  cleanup-tokens    Cleanup token blacklist"
	@echo "  format            Run code formatting (ruff format + fix)"
	@echo "  clean             Remove cache and build artifacts"
	@echo ""
	@echo "Docker:"
	@echo "  docker-up         Start Docker containers"
	@echo "  docker-up-d       Start Docker containers in background"
	@echo "  docker-down       Stop Docker containers"
	@echo "  docker-su         Create superuser in Docker"
	@echo ""
	@echo "CI/Pre-commit:"
	@echo "  pre-commit        Run pre-commit hooks on all files"
	@echo ""

# ============================================================================
# Quality Gates
# ============================================================================

.PHONY: lint
lint:
	uv run ruff check src tests

.PHONY: lint-fix
lint-fix:
	uv run ruff check src tests --fix

.PHONY: type
type:
	uv run mypy src --config-file pyproject.toml

.PHONY: test
test:
	uv run pytest

.PHONY: test-quick
test-quick:
	uv run pytest --tb=short -q

.PHONY: test-fail-fast
test-fail-fast:
	uv run pytest -x

.PHONY: check
check: lint type test
	@echo "All quality checks passed!"

# ============================================================================
# Development
# ============================================================================

.PHONY: install
install:
	uv sync

.PHONY: install-docs
install-docs:
	uv sync --group docs

.PHONY: dev
dev:
	uv run uvicorn src.app.main:app --reload

.PHONY: worker
worker:
	uv run arq src.app.workers.settings.WorkerSettings

# ============================================================================
# Database
# ============================================================================

.PHONY: migrate
migrate:
	uv run db-migrate upgrade head

.PHONY: migrate-create
migrate-create:
	@if [ -z "$(MSG)" ]; then \
		echo "Error: MSG variable required"; \
		echo "Usage: make migrate-create MSG='description'"; \
		exit 1; \
	fi
	uv run db-migrate revision --autogenerate -m "$(MSG)"

.PHONY: migrate-verify
migrate-verify:
	uv run db-migrate-verify

# ============================================================================
# Documentation
# ============================================================================

.PHONY: docs-build
docs-build:
	uv run mkdocs build --strict

.PHONY: docs-serve
docs-serve:
	uv run mkdocs serve

# ============================================================================
# Maintenance
# ============================================================================

.PHONY: cleanup-tokens
cleanup-tokens:
	uv run cleanup-token-blacklist

.PHONY: format
format:
	uv run ruff format src tests
	uv run ruff check src tests --fix

.PHONY: clean
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .coverage -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name .coverage -delete 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type f -name "*.egg-info" -delete 2>/dev/null || true
	rm -rf .eggs dist build 2>/dev/null || true
	@echo "Cache and build artifacts cleaned"

# ============================================================================
# Docker
# ============================================================================

.PHONY: docker-up
docker-up:
	docker compose up

.PHONY: docker-up-d
docker-up-d:
	docker compose up -d

.PHONY: docker-down
docker-down:
	docker compose down

.PHONY: docker-su
docker-su:
	docker compose run --rm create_superuser

# ============================================================================
# CI/Pre-commit
# ============================================================================

.PHONY: pre-commit
pre-commit:
	uv run pre-commit run --all-files
