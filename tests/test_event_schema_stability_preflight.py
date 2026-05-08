"""Static checks for the event-schema stability preflight."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_event_schema_stability.sh"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_event_schema_stability_script_is_shell_valid() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_event_schema_stability_script_passes_for_identical_refs() -> None:
    env = {
        **os.environ,
        "QUORUM_SCHEMA_STABILITY_ANCHOR_TAG": "HEAD",
        "QUORUM_SCHEMA_STABILITY_BASE_REF": "HEAD",
    }

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "schema-stability-ok" in output


def test_event_schema_stability_script_checks_schema_sensitive_paths() -> None:
    text = _text(SCRIPT)

    assert "QUORUM_SCHEMA_STABILITY_ANCHOR_TAG" in text
    assert "QUORUM_SCHEMA_STABILITY_BASE_REF" in text
    assert "v0.6.3" in text
    assert "git diff --name-only" in text
    assert "apps/api/app/domain/models.py" in text
    assert "apps/api/app/services/event_log.py" in text
    assert "apps/api/app/services/state_store.py" in text
    assert "apps/api/app/services/postgres_projector.py" in text
    assert "apps/api/app/db/models.py" in text
    assert "alembic/versions" in text
    assert "examples" in text
    assert "schema-stability-failed" in text
    assert "schema-stability-ok" in text
