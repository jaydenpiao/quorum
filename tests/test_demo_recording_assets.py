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


def test_operator_proof_capture_script_is_shell_valid() -> None:
    script = ROOT / "scripts" / "capture_operator_proof.sh"

    result = subprocess.run(
        ["bash", "-n", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_operator_proof_capture_embedded_python_compiles() -> None:
    script = ROOT / "scripts" / "capture_operator_proof.sh"
    text = script.read_text(encoding="utf-8")
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

    assert blocks, "expected at least one embedded Python heredoc"
    for start_line, source in blocks:
        compile(source, f"{script}:{start_line}", "exec")


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
    assert "QUORUM_PROOF_STAGING_EVIDENCE" in text
    assert "QUORUM_PROOF_DEPLOY_STAGING" in text
    assert "QUORUM_PROOF_EXPECT_GUARD" in text
    assert "external-staging-finding" in text
    assert "external_staging_verification" in text
    assert "fly_platform_digest" in text
    assert "latest release is $current_digest after deploy; expected $staging_digest" not in text
    assert "quorum-prod" in text
    assert "quorum-staging" in text
    assert "prod-readiness" in text
    assert "prod-api-health" in text
    assert "https://quorum-prod.fly.dev/readiness" in text
    assert "https://quorum-prod.fly.dev/api/v1/health" in text
    assert "https://quorum-staging.fly.dev/readiness" in text
    assert "https://quorum-staging.fly.dev/api/v1/health" in text
    assert "/api/v1/events/verify" in text
    assert "/api/v1/findings" in text
    assert "/api/v1/approvals/" in text
    assert "/api/v1/proposals/$proposal_id/execute" in text
    assert "verified_guard_finding" in text


def test_operator_proof_capture_script_fails_closed_on_required_gates() -> None:
    text = (ROOT / "scripts" / "capture_operator_proof.sh").read_text(encoding="utf-8")

    assert "from datetime import UTC" not in text
    assert "timezone.utc" in text
    assert "QUORUM_PROOF_API" in text
    assert "QUORUM_PROOF_PROD_URL" in text
    assert "QUORUM_PROOF_PROPOSAL_ID" in text
    assert "QUORUM_RELEASE_TAG" in text
    assert "QUORUM_PROOF_GITHUB_REPO" in text
    assert "QUORUM_PROOF_OUTPUT_DIR" in text
    assert "/api/v1/events/verify" in text
    assert "/readiness" in text
    assert "/api/v1/health" in text
    assert "/api/v1/state" in text
    assert "display_version" in text
    assert "ok=true" in text
    assert "quorum-prod" in text
    assert "deploy-llm-agent" in text
    assert "fly.deploy" in text
    assert "executed" in text
    assert "execution_succeeded" in text
    assert "health_checks" in text
    assert "/console?proposal_id=" in text
    assert "console_url" in text
    assert "release_url" in text
    assert "sbom_asset_name" in text
    assert "sbom_asset_url" in text
    assert "sbom_asset_digest" in text
    assert "release_metadata" in text
    assert "api.github.com/repos" in text
    assert "proposal_event_id" in text
    assert "intent_event_id" in text
    assert "finding_event_ids" in text
    assert "image_push_event_ids" in text
    assert "policy_decision_event_id" in text
    assert "vote_event_ids" in text
    assert "human_approval_event_ids" in text
    assert "execution_started_event_id" in text
    assert "execution_succeeded_event_id" in text
    assert "health_check_event_ids" in text
    assert "provenance" in text
    assert "event_chain_last_hash" in text
    assert "proof.json" in text
    assert "proof.md" in text


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
    assert "Guard-only proof" in text
    assert "QUORUM_PROOF_EXPECT_GUARD=1" in text
    assert "staging success evidence is missing" in text
    assert "External staging verification" in text
    assert "QUORUM_PROOF_STAGING_EVIDENCE=external-staging-finding" in text
    assert "QUORUM_PROOF_DEPLOY_STAGING=1" in text
    assert "Fly-reported platform digest" in text


def test_demo_video_documents_review_voter_proof_helper() -> None:
    text = (ROOT / "docs" / "DEMO_VIDEO.md").read_text(encoding="utf-8")

    assert "Review-voter acceptance proof" in text
    assert "scripts/prove_review_llm_vote.sh" in text
    assert "QUORUM_REVIEW_PROOF_PROPOSAL_ID" in text
    assert "QUORUM_REVIEW_PROOF_CREATE_FIXTURE=1" in text
    assert "QUORUM_REVIEW_PROOF_TARGET" in text
    assert "review-llm-agent" in text
    assert "voter_kind=llm" in text
    assert "counted=true" in text
    assert "system_prompt_sha256" in text
    assert "observed_event_cursor" in text
    assert "github.comment_issue" in text
    assert "github.add_labels" in text
    assert "fly.deploy" in text
    assert "proof.json" in text
    assert "proof.md" in text
    assert "/console?proposal_id=" in text


def test_demo_video_documents_post_release_proof_acceptance_path() -> None:
    text = (ROOT / "docs" / "DEMO_VIDEO.md").read_text(encoding="utf-8")

    assert "Post-release proof acceptance" in text
    assert "scripts/check_console_proof.sh" in text
    assert "scripts/check_release_proof_archive.sh" in text
    assert "scripts/check_live_release.sh" in text
    assert "scripts/check_phase6_gate.sh" in text
    assert "QUORUM_RELEASE_TAG=v0.6.7" in text
    assert "console-proof-ok:" in text
    assert "release-proof-archive-ok:" in text
    assert "live-release-ok" in text
    assert "deploy-llm-agent" in text
    assert "fly.deploy" in text
    assert "quorum-prod" in text
    assert "event-chain verification" in text
    assert "signed tag object" in text
    assert "SBOM asset name/URL/digest" in text
    assert "handoff pointer" in text
    assert "repo-map pointer" in text
    assert "http://127.0.0.1:8080/console" in text
    assert "http://127.0.0.1:8081/console" in text
    assert "stale" in text


def test_readme_demo_seed_matches_auth_and_demo_gate_contract() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "QUORUM_ALLOW_DEMO=true" in text
    assert 'QUORUM_AUTH_HEADER="Authorization"' in text
    assert '"${QUORUM_AUTH_HEADER}: Bearer ${QUORUM_OPERATOR_KEY}"' in text
    assert "Authorization: Bearer" not in text
    assert "/api/v1/demo/incident" in text
