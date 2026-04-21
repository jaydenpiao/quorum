from __future__ import annotations

from pathlib import Path
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

        if not proposal.rollback_steps:
            reasons.append("proposal has no rollback steps")

        return PolicyDecision(
            proposal_id=proposal.id,
            allowed=allowed,
            requires_human=requires_human,
            votes_required=votes_required,
            reasons=reasons,
        )

    @property
    def auto_rollback_enabled(self) -> bool:
        rollback = self.config.get("rollback", {})
        return bool(rollback.get("auto_on_failed_health_checks", True))
