.PHONY: dev test lint format validate typecheck coverage-html demo reset venv install sbom clean-worktrees

# Prefer the project's .venv if it exists; otherwise fall back to PATH tools.
VENV := .venv
ifneq ("$(wildcard $(VENV)/bin/python)","")
  PY := $(VENV)/bin/python
  PYTEST := $(VENV)/bin/pytest
  RUFF := $(VENV)/bin/ruff
  UVICORN := $(VENV)/bin/uvicorn
else
  PY := python3
  PYTEST := pytest
  RUFF := ruff
  UVICORN := uvicorn
endif

venv:
	python3.12 -m venv $(VENV) || python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e ".[dev]"

install: venv

dev:
	$(UVICORN) apps.api.app.main:app --reload --port 8080

test:
	$(PYTEST) -q

lint:
	$(RUFF) check .

format:
	$(RUFF) format .

validate:
	$(RUFF) check .
	$(RUFF) format --check .
	$(PYTEST) --cov-fail-under=60 -q

coverage-html:
	$(PYTEST) --cov=apps --cov-report=html

demo:
	$(PY) -m apps.api.app.demo_seed

typecheck:
	$(VENV)/bin/mypy

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
