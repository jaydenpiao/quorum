#!/usr/bin/env bash
set -euo pipefail

python -m compileall apps >/dev/null
python -m pytest -q
python -m ruff check .
echo "Merge validation passed."
