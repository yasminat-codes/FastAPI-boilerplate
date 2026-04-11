# Contributing to FastAPI Template

Thank you for contributing. This guide covers setup, quality gates, and the workflow for making changes.

## Quick Start

1. Clone the repository and install dependencies:

```sh
git clone <repository-url>
cd fastapi-template
uv sync
```

2. Verify the setup with quality gates:

```sh
uv run ruff check src tests
uv run mypy src
uv run pytest
```

If all three pass, you're ready to start.

## Quality Gates

Your code must pass all three gates before merging to main:

### 1. Ruff (linting and formatting)

```sh
uv run ruff check src tests
```

Ruff checks for style issues, import ordering, and code quality. To fix issues automatically:

```sh
uv run ruff check --fix src tests
uv run ruff format src tests
```

### 2. MyPy (type checking)

```sh
uv run mypy src
```

Type annotations are required in app code. If you're adding new modules or touching existing ones, ensure types are correct.

### 3. Pytest (tests)

```sh
uv run pytest
```

Write tests for new features and bug fixes. Run tests locally before pushing.

### 4. MkDocs (documentation)

If you change behavior or add features, update the relevant documentation:

```sh
uv run mkdocs build --strict
```

The `--strict` flag catches missing references and broken links. Run this after touching any markdown files or docs that reference code.

## Branch Workflow

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Make your changes
3. Run quality gates locally (all three must pass)
4. Push to your branch
5. Open a pull request to main

Quality gates are enforced—PRs cannot merge until all gates pass.

## What Belongs in the Template

This is a **shared template for starting FastAPI projects**, not a specific application.

- Do add: Generic patterns, reusable modules, database helpers, auth scaffolding, observability hooks
- Do not add: Client-specific business logic, hardcoded configurations, proprietary code, external service integrations beyond optional modules

When in doubt, ask in the PR.

## Commit Message Conventions

Use a prefix to categorize commits:

- `build:` - Dependency updates, tooling, pyproject.toml
- `fix:` - Bug fixes in existing code
- `feat:` - New features (avoid in template; use sparingly)
- `docs:` - Documentation, README, mkdocs
- `refactor:` - Code reorganization without behavior change
- `test:` - Test additions or fixes
- `ci:` - CI/CD, pre-commit, workflows

Example:

```
docs: add database migration guide

fix: correct mypy issue in auth module

build: upgrade fastapi to 0.110.0
```

Keep the subject line under 72 characters. Write the message as an imperative statement (e.g., "add" not "adds").

## Pre-Commit Hooks

Pre-commit hooks are already configured. They run automatically on `git commit` and enforce code quality early:

- End-of-file fixers, trailing whitespace cleanup
- YAML validation, docstring checks
- Ruff formatting and import sorting
- **Gitleaks secret scanning** - detects hardcoded credentials, API keys, tokens
- Markdown formatting with mdformat

Hooks may auto-fix issues (ruff, docformatter, etc.) or block your commit if manual fixes are needed. Fix any failures and commit again.

To skip hooks (not recommended): `git commit --no-verify`

## Pull Request Process

1. Fill out the PR template (see [PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md))
2. Reference any related issues
3. Describe what changed and why
4. Confirm you've added tests and docs if needed
5. Ensure all quality gates pass in CI

Reviewers will check:

- Code follows template conventions
- Tests cover the changes
- No client-specific logic
- Type hints are complete
- Documentation is updated if behavior changed

## Documentation

If you modify behavior, update docs:

- Edit files in `docs/` (if it exists) or relevant sections in README
- Update docstrings for modified functions
- Run `uv run mkdocs build --strict` to verify links and syntax
- Document any new environment variables or configuration

## Code of Conduct

Maintain a respectful, inclusive environment. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

Questions? Open an issue or discussion. Thank you for making this template better.
