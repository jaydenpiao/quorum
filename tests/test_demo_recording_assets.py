"""Static checks for recording/demo helper assets."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_github_fixture_demo_script_is_shell_valid() -> None:
    script = ROOT / "scripts" / "demo_github_fixture_flow.sh"

    result = subprocess.run(
        ["bash", "-n", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_llm_prod_deploy_proof_script_is_shell_valid() -> None:
    script = ROOT / "scripts" / "prove_llm_prod_deploy.sh"

    result = subprocess.run(
        ["bash", "-n", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_github_fixture_demo_script_drives_real_quorum_flow() -> None:
    text = (ROOT / "scripts" / "demo_github_fixture_flow.sh").read_text(encoding="utf-8")

    assert "/api/v1/intents" in text
    assert "/api/v1/findings" in text
    assert "/api/v1/proposals" in text
    assert "/api/v1/votes" in text
    assert "/api/v1/proposals/$proposal_id/execute" in text
    assert "github.comment_issue" in text
    assert "quorum-actuator-fixtures" in text
    assert "gh issue view" in text


def test_llm_prod_deploy_proof_script_gates_live_execution() -> None:
    text = (ROOT / "scripts" / "prove_llm_prod_deploy.sh").read_text(encoding="utf-8")

    assert "deploy-llm-agent" in text
    assert "--once" in text
    assert "QUORUM_PROOF_EXECUTE=1" in text
    assert "quorum-prod" in text
    assert "prod-readiness" in text
    assert "prod-api-health" in text
    assert "https://quorum-prod.fly.dev/readiness" in text
    assert "https://quorum-prod.fly.dev/api/v1/health" in text
    assert "/api/v1/events/verify" in text
    assert "/api/v1/approvals/" in text
    assert "/api/v1/proposals/$proposal_id/execute" in text


def test_demo_video_prefers_active_end_to_end_workflow() -> None:
    text = (ROOT / "docs" / "DEMO_VIDEO.md").read_text(encoding="utf-8")

    assert "active end-to-end Quorum workflow" in text
    assert "scripts/demo_github_fixture_flow.sh" in text
    assert "The one-click dog-food seed stays as a fallback." not in text
    assert "Fallback dog-food seed commands" in text


def test_demo_video_documents_live_llm_prod_deploy_proof() -> None:
    text = (ROOT / "docs" / "DEMO_VIDEO.md").read_text(encoding="utf-8")

    assert "LLM-authored prod deploy proof" in text
    assert "scripts/prove_llm_prod_deploy.sh" in text
    assert "scratch cursor" in text
    assert "deploy-llm-agent --once" in text
    assert "QUORUM_PROOF_EXECUTE=1" in text
    assert "fresh `image_push_completed`" in text
    assert "human approval" in text
    assert "Browser acceptance checklist" in text
    assert "agent identity" in text
    assert "rollback state" in text
    assert "verified event chain" in text


def test_readme_demo_seed_matches_auth_and_demo_gate_contract() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "QUORUM_ALLOW_DEMO=true" in text
    assert 'QUORUM_AUTH_HEADER="Authorization"' in text
    assert '"${QUORUM_AUTH_HEADER}: Bearer ${QUORUM_OPERATOR_KEY}"' in text
    assert "Authorization: Bearer" not in text
    assert "/api/v1/demo/incident" in text
