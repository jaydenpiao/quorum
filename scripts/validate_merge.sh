#!/usr/bin/env bash
set -euo pipefail

UV_VERSION="${QUORUM_UV_VERSION:-0.11.8}"
UVX="${QUORUM_UVX:-uvx}"
command -v "$UVX" >/dev/null 2>&1 || {
  printf "error: missing required command: %s\n" "$UVX" >&2
  exit 1
}
UV=("$UVX" --from "uv==${UV_VERSION}" uv)

"${UV[@]}" sync --frozen --extra dev --python 3.12 --python-preference only-managed \
  --reinstall-package quorum
"${UV[@]}" run --frozen --extra dev --python 3.12 --python-preference only-managed \
  python scripts/check_python_runtime.py
"${UV[@]}" run --frozen --extra dev --python 3.12 --python-preference only-managed \
  python -m compileall apps >/dev/null
"${UV[@]}" run --frozen --extra dev --python 3.12 --python-preference only-managed \
  pytest --cov-fail-under=60 -q
"${UV[@]}" run --frozen --extra dev --python 3.12 --python-preference only-managed \
  ruff check .
"${UV[@]}" run --frozen --extra dev --python 3.12 --python-preference only-managed \
  ruff format --check .
echo "Merge validation passed."
