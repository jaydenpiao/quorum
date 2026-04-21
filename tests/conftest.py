"""Shared pytest fixtures and environment setup.

Sets `QUORUM_API_KEYS` and `QUORUM_ALLOW_DEMO` *before* any test imports the
FastAPI app, so the auth registry is populated and the demo endpoint is
enabled when the TestClient exercises it.

Shared helpers (e.g. `AUTH`) live in `tests/_helpers.py` so tests import
them by regular module path instead of reaching into conftest.
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "QUORUM_API_KEYS",
    "test-operator:operator-key-dev,telemetry-agent:telemetry-key-dev,code-agent:code-key-dev",
)
os.environ.setdefault("QUORUM_ALLOW_DEMO", "1")
