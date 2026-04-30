"""Tests for the operator console static assets."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_app_js_served(client: TestClient) -> None:
    """GET /console-static/app.js returns 200 with JS content-type and a known symbol."""
    response = client.get("/console-static/app.js")
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    # Starlette may return application/javascript or text/javascript.
    assert "javascript" in content_type, f"Unexpected Content-Type: {content_type}"
    assert "no-store" in response.headers.get("cache-control", "")
    assert "loadState" in response.text
    assert "DEMO_TOKEN_FALLBACK" in response.text
    assert "ensureDemoToken" in response.text


def test_console_shell_references_external_stylesheet(client: TestClient) -> None:
    response = client.get("/console")

    assert response.status_code == 200
    assert "no-store" in response.headers.get("cache-control", "")
    assert "/console-static/styles.css" in response.text
    assert "Seed dog-food deploy demo" in response.text
    assert "Intents" in response.text
    assert "Findings" in response.text
    assert "Execute proposal" in response.text
    assert "Verify event chain" in response.text
    assert "Seed demo incident" not in response.text
    assert "POC console" not in response.text
    assert "<style>" not in response.text
    assert '<script defer src="/console-static/app.js"></script>' in response.text


def test_console_stylesheet_served(client: TestClient) -> None:
    response = client.get("/console-static/styles.css")

    assert response.status_code == 200
    assert "css" in response.headers.get("content-type", "")
    assert "no-store" in response.headers.get("cache-control", "")
    assert ".proposal-table" in response.text
    assert ".timeline" in response.text


def test_app_js_contains_execute_and_chain_verify_workflows(client: TestClient) -> None:
    response = client.get("/console-static/app.js")

    assert response.status_code == 200
    assert "/api/v1/events/verify" in response.text
    assert "/api/v1/proposals/" in response.text
    assert "btn-execute" in response.text
    assert "btn-verify-chain" in response.text
    assert "renderFindings" in response.text
    assert "renderIntents" in response.text


def test_app_js_contains_execute_actionability_gates(client: TestClient) -> None:
    response = client.get("/console-static/app.js")

    assert response.status_code == 200
    assert "proposalActionability" in response.text
    assert "controlPlaneFlyApp" in response.text
    assert "same control-plane app" in response.text
    assert "proposal is terminal" in response.text
    assert "waiting for human approval" in response.text
    assert "waiting for quorum" in response.text
    assert "actionable proposals" in response.text


def test_app_js_supports_proposal_deep_links(client: TestClient) -> None:
    response = client.get("/console-static/app.js")

    assert response.status_code == 200
    assert "function proposalIdFromLocation" in response.text
    assert "new URLSearchParams" in response.text
    assert "params.get('proposal_id')" in response.text
    assert "proposalIdFromLocation()" in response.text
    assert "proposalById(state, linkedProposalId)" in response.text


def test_app_js_updates_proposal_deep_link_without_reload(client: TestClient) -> None:
    response = client.get("/console-static/app.js")

    assert response.status_code == 200
    assert "function updateSelectedProposalUrl" in response.text
    assert "window.history.replaceState" in response.text
    assert "url.searchParams.set('proposal_id', proposalId)" in response.text
    assert "window.location.hash" in response.text
    assert "updateSelectedProposalUrl(id)" in response.text


def test_console_route_allows_proposal_query_with_existing_anchor(client: TestClient) -> None:
    response = client.get("/console?proposal_id=proposal_36ab7d5601e3")

    assert response.status_code == 200
    assert "/console-static/app.js" in response.text
    assert 'href="#proposals"' in response.text
    assert 'href="#overview"' in response.text
    assert 'href="#timeline"' in response.text
    assert 'href="#actions"' in response.text


def test_console_shell_exposes_actionable_metric(client: TestClient) -> None:
    response = client.get("/console")

    assert response.status_code == 200
    assert "Actionable proposals" in response.text
    assert 'id="metric-actionable-proposals"' in response.text


def test_app_js_counts_only_counted_votes_for_quorum(client: TestClient) -> None:
    response = client.get("/console-static/app.js")

    assert response.status_code == 200
    assert "function voteCountsForQuorum" in response.text
    assert "vote.counted !== false" in response.text
    assert "vote.decision === 'approve' && voteCountsForQuorum(vote)" in response.text
    assert "var approvedVotes = approvalCount(votes)" in response.text
    assert "approvedVotes < requiredVotes" in response.text


def test_app_js_renders_llm_vote_audit_metadata(client: TestClient) -> None:
    response = client.get("/console-static/app.js")

    assert response.status_code == 200
    assert "function renderVotes" in response.text
    assert "llm-voter" in response.text
    assert "llm_model" in response.text
    assert "system_prompt_sha256" in response.text
    assert "observed_event_cursor" in response.text
    assert "counted_reason" in response.text
    assert "counted LLM vote" in response.text
    assert "capped/non-counting LLM vote" in response.text


def test_app_js_renders_selected_proposal_rollback_and_actionability(client: TestClient) -> None:
    response = client.get("/console-static/app.js")

    assert response.status_code == 200
    assert "function renderInspector" in response.text
    assert "proposalById(state, _selectedProposalId)" in response.text
    assert "Rollback details" in response.text
    assert "renderRollback(rollback)" in response.text
    assert "updateExecuteActionability(actionability)" in response.text


def test_console_stylesheet_marks_llm_and_uncounted_votes(client: TestClient) -> None:
    response = client.get("/console-static/styles.css")

    assert response.status_code == 200
    assert ".vote-card.vote-llm" in response.text
    assert ".vote-card.vote-not-counted" in response.text
    assert ".vote-meta" in response.text
