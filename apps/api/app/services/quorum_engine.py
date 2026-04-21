from __future__ import annotations

from apps.api.app.domain.models import PolicyDecision, VoteDecision


class QuorumEngine:
    def is_approved(self, votes: list[dict], policy_decision: PolicyDecision) -> bool:
        approvals = {v["agent_id"] for v in votes if v["decision"] == VoteDecision.approve.value}
        return len(approvals) >= policy_decision.votes_required

    def is_blocked(self, votes: list[dict]) -> bool:
        rejects = {v["agent_id"] for v in votes if v["decision"] == VoteDecision.reject.value}
        return len(rejects) >= 2
