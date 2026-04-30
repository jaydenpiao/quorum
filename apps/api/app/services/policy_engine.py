from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

from apps.api.app.domain.models import PolicyDecision, Proposal


class PolicyEngine:
    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self.config = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))

    def evaluate(self, proposal: Proposal) -> PolicyDecision:
        reasons: list[str] = []
        allowed = True
        requires_human = False

        denied = set(self.config.get("denied_action_types", []))
        if proposal.action_type in denied:
            allowed = False
            reasons.append(f"action_type '{proposal.action_type}' is denied")

        risk_rules = self.config.get("risk_rules", {})
        risk_cfg = risk_rules.get(proposal.risk.value, {})
        votes_required = int(risk_cfg.get("votes_required", 2))
        requires_human = bool(risk_cfg.get("requires_human", False))

        protected_envs = set(self.config.get("protected_environments", []))
        env_overrides = self.config.get("environment_overrides", {})
        if proposal.environment in protected_envs:
            override = env_overrides.get(proposal.environment, {})
            votes_required = max(
                votes_required, int(override.get("minimum_votes_required", votes_required))
            )
            if override.get("force_human_approval", False):
                requires_human = True
            reasons.append(f"environment '{proposal.environment}' is protected")

        # Per-action_type overrides: tighten (never loosen) risk-level rules.
        # MAX of votes_required; OR of requires_human. Absent action_type → skip.
        action_type_rules = self.config.get("action_type_rules", {}) or {}
        action_cfg = action_type_rules.get(proposal.action_type)
        if isinstance(action_cfg, dict):
            votes_required = max(votes_required, int(action_cfg.get("votes_required", 0)))
            if bool(action_cfg.get("requires_human", False)):
                requires_human = True
            reasons.append(f"action_type '{proposal.action_type}' rule applied")

        if not proposal.rollback_steps:
            reasons.append("proposal has no rollback steps")

        return PolicyDecision(
            proposal_id=proposal.id,
            allowed=allowed,
            requires_human=requires_human,
            votes_required=votes_required,
            reasons=reasons,
        )

    def llm_vote_cap_for(self, proposal: Proposal) -> int:
        caps = self.config.get("llm_vote_caps", {}) or {}
        default_cap = int(caps.get("default_max_counted", 0))
        action_rules = caps.get("action_type_rules", {}) or {}
        action_cfg = action_rules.get(proposal.action_type)
        if isinstance(action_cfg, dict):
            return int(action_cfg.get("max_counted", default_cap))
        return default_cap

    def llm_vote_counting_decision(
        self,
        proposal: Proposal,
        existing_votes: list[dict[str, Any]],
    ) -> tuple[bool, str]:
        protected_envs = set(self.config.get("protected_environments", []))
        if proposal.environment in protected_envs or proposal.risk.value in {"high", "critical"}:
            return False, "llm_vote_not_counted_for_protected_or_high_risk"

        cap = self.llm_vote_cap_for(proposal)
        if cap <= 0:
            return False, "llm_vote_not_counted_for_action"

        counted_llm_votes = sum(
            1
            for vote in existing_votes
            if vote.get("voter_kind") == "llm" and vote.get("counted", True)
        )
        if counted_llm_votes >= cap:
            return False, "llm_vote_cap_reached"

        return True, "llm_vote_counted"

    @property
    def auto_rollback_enabled(self) -> bool:
        rollback = self.config.get("rollback", {})
        return bool(rollback.get("auto_on_failed_health_checks", True))
