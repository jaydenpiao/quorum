"""Static contract checks for the console proof smoke helper."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_console_proof.sh"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_console_proof_script_is_shell_valid() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_console_proof_embedded_python_compiles() -> None:
    text = _text()
    lines = text.splitlines()
    blocks: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        if "<<'PY'" not in lines[index]:
            index += 1
            continue
        start_line = index + 2
        index += 1
        block: list[str] = []
        while index < len(lines) and lines[index] != "PY":
            block.append(lines[index])
            index += 1
        blocks.append((start_line, "\n".join(block) + "\n"))
        index += 1

    assert blocks, "expected embedded Python validation blocks"
    for start_line, source in blocks:
        compile(source, f"{SCRIPT}:{start_line}", "exec")


def test_console_proof_script_documents_operator_inputs() -> None:
    text = _text()

    assert "QUORUM_CONSOLE_PROOF_API" in text
    assert "https://quorum-staging.fly.dev" in text
    assert "QUORUM_RELEASE_TAG" in text
    assert "v0.6.7" in text
    assert "QUORUM_CONSOLE_PROOF_PROPOSAL_ID" in text
    assert "QUORUM_CONSOLE_PROOF_EXPECT_AGENT" in text
    assert "deploy-llm-agent" in text
    assert "QUORUM_CONSOLE_PROOF_EXPECT_ACTION" in text
    assert "fly.deploy" in text
    assert "QUORUM_CONSOLE_PROOF_EXPECT_TARGET" in text
    assert "quorum-prod" in text


def test_console_proof_script_uses_only_read_surfaces() -> None:
    text = _text()

    assert "/api/v1/state" in text
    assert "/api/v1/events/verify" in text
    assert "/console-static/app.js" in text
    assert "/console?proposal_id=" in text
    assert "curl" in text
    assert " -X " not in text
    assert "POST" not in text
    assert "/api/v1/proposals/" not in text
    assert "/api/v1/votes" not in text
    assert "/api/v1/approvals" not in text


def test_console_proof_script_checks_required_console_contract() -> None:
    text = _text()

    assert "display_version" in text
    assert "proposalIdFromLocation" in text
    assert "updateSelectedProposalUrl" in text
    assert "renderInspector" in text
    assert "renderChecks" in text
    assert "renderRollback" in text
    assert "release-badge" in text
    assert "proposal-inspector" in text
    assert "metric-chain-status" in text
    assert "console-proof-ok:" in text


def test_console_proof_script_checks_selected_proposal_state() -> None:
    text = _text()

    for required in (
        "agent_id",
        "action_type",
        "target",
        "status",
        "policy_decisions",
        "votes_required",
        "votes",
        "human_approvals",
        "executions",
        "health_checks",
        "prod-readiness",
        "prod-api-health",
        "event-chain verification must return ok=true",
    ):
        assert required in text
