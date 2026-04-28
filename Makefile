.PHONY: dev test lint format validate typecheck coverage-html demo reset venv install sbom clean-worktrees preflight

VENV := .venv
UV_VERSION := 0.11.8
UVX ?= uvx
UV := $(UVX) --from uv==$(UV_VERSION) uv
PYTHON_VERSION := 3.12
UV_SYNC := $(UV) sync --frozen --extra dev --python $(PYTHON_VERSION) --python-preference only-managed --reinstall-package quorum
UV_RUN := $(UV) run --frozen --extra dev --python $(PYTHON_VERSION) --python-preference only-managed

venv:
	rm -rf $(VENV)
	$(UV) python install $(PYTHON_VERSION)
	$(UV) venv --python $(PYTHON_VERSION) --python-preference only-managed $(VENV)
	$(UV_SYNC)

install: venv
	$(MAKE) preflight

preflight:
	$(UV_RUN) python scripts/check_python_runtime.py

dev:
	$(MAKE) preflight
	$(UV_RUN) python -m uvicorn apps.api.app.main:app --reload --port 8080

test:
	$(MAKE) preflight
	$(UV_RUN) pytest --cov-fail-under=60 -q

lint:
	$(MAKE) preflight
	$(UV_RUN) ruff check .

format:
	$(MAKE) preflight
	$(UV_RUN) ruff format .

validate:
	$(MAKE) preflight
	$(UV_RUN) ruff check .
	$(UV_RUN) ruff format --check .
	$(UV_RUN) pytest --cov-fail-under=60 -q

coverage-html:
	$(MAKE) preflight
	$(UV_RUN) pytest --cov=apps --cov-report=html

demo:
	$(MAKE) preflight
	$(UV_RUN) python -m apps.api.app.demo_seed

typecheck:
	$(MAKE) preflight
	$(UV_RUN) mypy

reset:
	rm -f data/events.jsonl data/state_snapshot.json

sbom:
	@command -v syft >/dev/null || { echo "syft not installed; brew install syft"; exit 1; }
	syft packages dir:. -o spdx-json=quorum-dev.spdx.json
	@echo "wrote quorum-dev.spdx.json"

# Clean up subagent worktrees that remain locked after dispatch completion
# (SESSION_HANDOFF.md gotcha #7). `git worktree remove --force` alone
# refuses when a lock file is present — Claude subagents register a lock
# so the parent session can't accidentally stomp them. We pass `-f -f`
# (two --force) per the `git worktree remove` docs to override locks.
# Safe to run repeatedly; re-running after a clean tree is a no-op.
clean-worktrees:
	@git worktree list --porcelain \
		| awk '/^worktree /{path=$$2} /^branch /{print path}' \
		| grep -E '(\.claude/worktrees/|/\.worktrees/)' \
		| while read wt; do \
			echo "removing worktree $$wt"; \
			git worktree remove -f -f "$$wt" 2>/dev/null || true; \
		done
	@git worktree prune
	@echo "git worktree list (after):"
	@git worktree list
