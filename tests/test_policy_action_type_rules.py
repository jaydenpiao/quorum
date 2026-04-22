"""Policy-engine action_type_rules merge (Phase 4 PR B2).

Action-type rules tighten risk-level rules — never loosen them. The
merge is: MAX of ``votes_required``, OR of ``requires_human``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.app.domain.models import Proposal, RiskLevel
from apps.api.app.services.policy_engine import PolicyEngine


def _proposal(action_type: str, risk: RiskLevel = RiskLevel.low) -> Proposal:
    return Proposal(
        intent_id="intent_abc",
        agent_id="deploy-agent",
        title="t",
        action_type=action_type,
        target="svc",
        risk=risk,
        rationale="because",
        rollback_steps=["rollback step 1"],
    )


def _write_policy(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "policies.yaml"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tightening (MAX / OR)
# ---------------------------------------------------------------------------


def test_action_type_rule_raises_votes_required_above_risk(tmp_path: Path) -> None:
    path = _write_policy(
        tmp_path,
        """
risk_rules:
  low: {votes_required: 2, requires_human: false}
action_type_rules:
  github.open_pr: {votes_required: 3, requires_human: false}
""",
    )
    decision = PolicyEngine(path).evaluate(_proposal("github.open_pr"))
    assert decision.votes_required == 3
    assert decision.requires_human is False
    assert any("action_type 'github.open_pr'" in r for r in decision.reasons)


def test_action_type_rule_promotes_requires_human(tmp_path: Path) -> None:
    path = _write_policy(
        tmp_path,
        """
risk_rules:
  low: {votes_required: 2, requires_human: false}
action_type_rules:
  deploy.prod: {votes_required: 1, requires_human: true}
""",
    )
    decision = PolicyEngine(path).evaluate(_proposal("deploy.prod"))
    assert decision.requires_human is True


# ---------------------------------------------------------------------------
# Never loosens
# ---------------------------------------------------------------------------


def test_action_type_rule_cannot_lower_votes(tmp_path: Path) -> None:
    path = _write_policy(
        tmp_path,
        """
risk_rules:
  critical: {votes_required: 3, requires_human: true}
action_type_rules:
  github.open_pr: {votes_required: 1, requires_human: false}
""",
    )
    decision = PolicyEngine(path).evaluate(_proposal("github.open_pr", RiskLevel.critical))
    assert decision.votes_required == 3, "MAX must win"
    assert decision.requires_human is True, "requires_human already True at risk level"


def test_action_type_rule_cannot_unset_requires_human(tmp_path: Path) -> None:
    path = _write_policy(
        tmp_path,
        """
risk_rules:
  high: {votes_required: 2, requires_human: true}
action_type_rules:
  github.open_pr: {votes_required: 2, requires_human: false}
""",
    )
    decision = PolicyEngine(path).evaluate(_proposal("github.open_pr", RiskLevel.high))
    assert decision.requires_human is True


# ---------------------------------------------------------------------------
# Absence / unknown action_type
# ---------------------------------------------------------------------------


def test_unknown_action_type_falls_through_to_risk_level(tmp_path: Path) -> None:
    path = _write_policy(
        tmp_path,
        """
risk_rules:
  low: {votes_required: 2, requires_human: false}
action_type_rules:
  github.open_pr: {votes_required: 3, requires_human: false}
""",
    )
    decision = PolicyEngine(path).evaluate(_proposal("deploy.staging"))
    assert decision.votes_required == 2
    assert decision.requires_human is False
    assert not any("action_type 'deploy.staging'" in r for r in decision.reasons)


@pytest.mark.parametrize("missing", [None, "null", "{}"])
def test_missing_action_type_rules_section_is_fine(tmp_path: Path, missing: str | None) -> None:
    body = "risk_rules:\n  low: {votes_required: 1, requires_human: false}\n"
    if missing is not None:
        body += f"action_type_rules: {missing}\n"
    path = _write_policy(tmp_path, body)
    decision = PolicyEngine(path).evaluate(_proposal("github.open_pr"))
    assert decision.votes_required == 1


# ---------------------------------------------------------------------------
# Committed config sanity — the default policies.yaml actually loads.
# ---------------------------------------------------------------------------


def test_shipped_policies_yaml_includes_github_rule() -> None:
    decision = PolicyEngine("config/policies.yaml").evaluate(_proposal("github.open_pr"))
    assert decision.votes_required >= 2
    assert any("action_type 'github.open_pr'" in r for r in decision.reasons)
