#!/usr/bin/env bash
set -euo pipefail

uv run --frozen --extra dev --python 3.12 --python-preference only-managed \
  python scripts/check_python_runtime.py
uv run --frozen --extra dev --python 3.12 --python-preference only-managed \
  python -m compileall apps >/dev/null
uv run --frozen --extra dev --python 3.12 --python-preference only-managed \
  pytest --cov-fail-under=60 -q
uv run --frozen --extra dev --python 3.12 --python-preference only-managed \
  ruff check .
uv run --frozen --extra dev --python 3.12 --python-preference only-managed \
  ruff format --check .
echo "Merge validation passed."
