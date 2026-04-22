.PHONY: dev test lint format validate typecheck coverage-html demo reset venv install

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
