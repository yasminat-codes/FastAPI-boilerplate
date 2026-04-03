# Execution System

This document defines how work gets done in this repository.

It exists so every session follows the same build discipline, quality gates, and promotion flow.

## Repository Mode

This repository is a reusable production-ready FastAPI template.

- It is not a client implementation.
- It is not a one-off build.
- All work must improve the template itself.
- New code must be generic, reusable, documented, and production-oriented.

## Core Rule

No task is considered complete until all of these are true:

- The implementation is finished.
- Relevant documentation is updated.
- Relevant checklist items are updated in [TEMPLATE_ROADMAP.md](/Users/yasmineseidu/coding/fastapi-template/TEMPLATE_ROADMAP.md).
- Full required quality checks pass.
- The change is reviewed against the template guardrails.
- The branch is ready to merge cleanly to `main`.

## Required Session Workflow

Every session should follow this order:

1. Read [TEMPLATE_ROADMAP.md](/Users/yasmineseidu/coding/fastapi-template/TEMPLATE_ROADMAP.md).
2. Read this file.
3. Confirm the next task being executed.
4. Inspect the relevant code before changing anything.
5. Implement only the scope needed for that roadmap task.
6. Add or update tests.
7. Run the required quality gates.
8. Update docs and roadmap checkboxes.
9. Summarize results, including anything not yet passing.
10. Only treat the work as complete when the full gate passes.

## What We Must Do

- Build reusable template primitives.
- Keep architecture production-minded.
- Prefer extension points over embedded assumptions.
- Make operational behavior observable.
- Add resilience by default where the template owns the behavior.
- Keep local developer experience usable.
- Keep CI and local workflows aligned.

## What We Must Not Do

- Do not add client-specific requirements.
- Do not hardcode external services that only fit one company.
- Do not mark roadmap items done without implementing and verifying them.
- Do not skip tests because the change feels small.
- Do not skip docs for structural changes.
- Do not push half-verified work to `main`.

## Definition Of Done

A task is done only when all applicable items below are true:

- [ ] Code is implemented.
- [ ] Tests were added or updated where needed.
- [ ] Docs were added or updated where needed.
- [ ] `TEMPLATE_ROADMAP.md` checkboxes were updated.
- [ ] Lint passes.
- [ ] Type checks pass.
- [ ] Test suite passes.
- [ ] Any task-specific verification passes.
- [ ] No known template guardrail violations remain.
- [ ] The branch is ready for merge to `main`.

## Required Quality Gates

Unless a task truly does not touch the relevant layer, run all of the following:

- [ ] `uv run ruff check src tests`
- [ ] `uv run mypy src --config-file pyproject.toml`
- [ ] `uv run pytest`

Also run any task-specific checks that become relevant, including when added later:

- [ ] Migration verification
- [ ] Docker or image build verification
- [ ] Integration or webhook test suite
- [ ] Worker or queue test suite
- [ ] Documentation build verification (`uv run mkdocs build --strict`)

## Failure Policy

If any required gate fails:

- The task is not complete.
- The roadmap item is not checked off as done.
- The failure must be fixed or explicitly documented as a blocker.
- We do not treat the branch as ready for `main`.

## Main Branch Promotion Rule

The default promotion flow for this repository is:

1. Work on a branch.
2. Complete the implementation.
3. Run the full required quality gates.
4. Update docs and roadmap.
5. Re-run gates if needed after doc or code changes.
6. Confirm the branch is clean and ready.
7. Only then merge or push the final approved result to `main`.

`main` should represent verified template state, not work in progress.

## Session Completion Checklist

Before ending a session, confirm:

- [ ] The task worked on is clearly identified.
- [ ] The current status is reflected in `TEMPLATE_ROADMAP.md`.
- [ ] Any unfinished work is explicitly called out.
- [ ] All quality gate results are reported.
- [ ] If ready, the branch is in a `main`-mergeable state.

## Current Status Report

As of April 1, 2026, the template foundation has been advanced in these areas:

- The codebase has been reorganized around `platform`, `api`, `domain`, `integrations`, `workflows`, and `workers` boundaries.
- Startup has been hardened with fail-fast production settings, migrations-only database startup, and removal of automatic schema creation.
- The worker layer now exposes reusable job primitives, shared job envelopes, and shared job logging instead of shipping a demo task flow by default.
- The local quality baseline is green for linting, typing, tests, and strict MkDocs documentation builds.
- GitHub Actions now verify linting, type-checking, tests, and strict documentation builds as part of the template baseline.

Use `TEMPLATE_ROADMAP.md` as the detailed source of truth for item-level progress and remaining work.

## Short Prompt For Future Sessions

Use this at the start of future sessions if needed:

```text
Read `/Users/yasmineseidu/coding/fastapi-template/TEMPLATE_ROADMAP.md` and `/Users/yasmineseidu/coding/fastapi-template/EXECUTION_SYSTEM.md` first.

This repo is a reusable production-ready FastAPI template, not a client build.
Follow the roadmap.
Work only on the next requested or unchecked task.
Keep all changes template-oriented and reusable.
Add or update tests as needed.
Run full quality gates before considering work complete:
- uv run ruff check src tests
- uv run mypy src --config-file pyproject.toml
- uv run pytest

Update roadmap checkboxes when tasks are completed.
Do not treat work as done or ready for main until implementation, docs, and verification are all complete.
```
