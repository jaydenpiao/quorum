#!/usr/bin/env bash
set -euo pipefail

python -m venv .venv || true
source .venv/bin/activate
pip install -e ".[dev]"
python -m apps.api.app.demo_seed
uvicorn apps.api.app.main:app --reload --port 8080
