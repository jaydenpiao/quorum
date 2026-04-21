"""Shared pytest fixtures and environment setup.

Sets `QUORUM_API_KEYS` and `QUORUM_ALLOW_DEMO` *before* any test imports the
FastAPI app, so the auth registry is populated and the demo endpoint is
enabled when the TestClient exercises it.
"""

from __future__ import annotations

import os

# Registered test agents — matched against incoming Bearer tokens.
os.environ.setdefault(
    "QUORUM_API_KEYS",
    "test-operator:operator-key-dev,telemetry-agent:telemetry-key-dev,code-agent:code-key-dev",
)
os.environ.setdefault("QUORUM_ALLOW_DEMO", "1")

TEST_OPERATOR_KEY = "operator-key-dev"
TEST_TELEMETRY_KEY = "telemetry-key-dev"
TEST_CODE_KEY = "code-key-dev"

AUTH = {"Authorization": f"Bearer {TEST_OPERATOR_KEY}"}
