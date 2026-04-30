"""Static contract checks for the review LLM voter proof helper."""

from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prove_review_llm_vote.sh"


def test_review_voter_proof_script_is_shell_valid() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_review_voter_proof_script_embedded_python_compiles() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
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
        compile(source, f"{SCRIPT}:{start_line}", "exec")


def test_review_voter_proof_script_documents_operator_inputs() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "QUORUM_REVIEW_PROOF_API" in text
    assert "https://quorum-staging.fly.dev" in text
    assert "QUORUM_REVIEW_PROOF_PROPOSAL_ID" in text
    assert "QUORUM_REVIEW_PROOF_CREATE_FIXTURE" in text
    assert "QUORUM_REVIEW_PROOF_OUTPUT_DIR" in text
    assert "QUORUM_REVIEW_PROOF_TARGET" in text
    assert "jaydenpiao/quorum#122" in text
    assert "QUORUM_REVIEW_PROOF_REVIEW_AGENT_KEY" in text
    assert "QUORUM_REVIEW_PROOF_OPERATOR_KEY" in text


def test_review_voter_proof_script_uses_existing_api_and_adapter_paths() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "/api/v1/events/verify" in text
    assert "/api/v1/state" in text
    assert "/api/v1/events" in text
    assert "/api/v1/intents" in text
    assert "/api/v1/findings" in text
    assert "/api/v1/proposals" in text
    assert "/api/v1/votes" not in text
    assert "python -m apps.llm_agent.run" in text
    assert "--agent-id review-llm-agent" in text
    assert "--once" in text


def test_review_voter_proof_script_fails_closed_on_vote_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "review-llm-agent" in text
    assert "voter_kind" in text
    assert "llm_model" in text
    assert "system_prompt_sha256" in text
    assert "observed_event_cursor" in text
    assert "counted" in text
    assert "counted_reason" in text
    assert "llm_vote_counted" in text
    assert "github.comment_issue" in text
    assert "github.add_labels" in text
    assert "fly.deploy" in text
    assert "production" in text
    assert "prod" in text
    assert "self-vote" in text
    assert "event-chain verification" in text


def test_review_voter_proof_script_writes_json_and_markdown_artifacts() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "/tmp/quorum-review-proof." in text
    assert "proof.json" in text
    assert "proof.md" in text
    assert "captured_at" in text
    assert "event_chain" in text
    assert "proposal" in text
    assert "vote" in text
