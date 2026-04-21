"""Shared test helpers. Not auto-discovered by pytest (prefix _) but importable."""

from __future__ import annotations

TEST_OPERATOR_KEY = "operator-key-dev"
TEST_TELEMETRY_KEY = "telemetry-key-dev"
TEST_CODE_KEY = "code-key-dev"

AUTH = {"Authorization": f"Bearer {TEST_OPERATOR_KEY}"}
