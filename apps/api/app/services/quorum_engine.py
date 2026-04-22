from __future__ import annotations

from typing import Any

from apps.api.app.domain.models import PolicyDecision, VoteDecision


class QuorumEngine:
    def is_approved(self, votes: list[dict[str, Any]], policy_decision: PolicyDecision) -> bool:
        approvals = {v["agent_id"] for v in votes if v["decision"] == VoteDecision.approve.value}
        return len(approvals) >= policy_decision.votes_required

    def is_blocked(self, votes: list[dict[str, Any]]) -> bool:
        rejects = {v["agent_id"] for v in votes if v["decision"] == VoteDecision.reject.value}
        return len(rejects) >= 2
