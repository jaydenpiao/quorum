from __future__ import annotations

from collections import defaultdict
from typing import Any

from apps.api.app.domain.models import EventEnvelope, ProposalStatus, VoteDecision


class StateStore:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.intents: dict[str, dict[str, Any]] = {}
        self.findings: dict[str, dict[str, Any]] = {}
        self.proposals: dict[str, dict[str, Any]] = {}
        self.votes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.policy_decisions: dict[str, dict[str, Any]] = {}
        self.executions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.rollbacks: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.events: list[dict[str, Any]] = []

    def replay(self, events: list[EventEnvelope]) -> None:
        self.reset()
        for event in events:
            self.apply(event)

    def apply(self, event: EventEnvelope) -> None:
        payload = event.payload
        self.events.append(event.model_dump(mode="json"))

        if event.event_type == "intent_created":
            self.intents[event.entity_id] = payload

        elif event.event_type == "finding_created":
            self.findings[event.entity_id] = payload

        elif event.event_type == "proposal_created":
            self.proposals[event.entity_id] = payload

        elif event.event_type == "policy_evaluated":
            self.policy_decisions[payload["proposal_id"]] = payload

        elif event.event_type == "proposal_voted":
            self.votes[payload["proposal_id"]].append(payload)

        elif event.event_type == "proposal_approved":
            if payload["proposal_id"] in self.proposals:
                self.proposals[payload["proposal_id"]]["status"] = ProposalStatus.approved.value

        elif event.event_type == "proposal_blocked":
            if payload["proposal_id"] in self.proposals:
                self.proposals[payload["proposal_id"]]["status"] = ProposalStatus.blocked.value

        elif event.event_type == "execution_started":
            self.executions[payload["proposal_id"]].append(payload)

        elif event.event_type == "execution_succeeded":
            self.executions[payload["proposal_id"]].append(payload)
            if payload["proposal_id"] in self.proposals:
                self.proposals[payload["proposal_id"]]["status"] = ProposalStatus.executed.value

        elif event.event_type == "execution_failed":
            self.executions[payload["proposal_id"]].append(payload)
            if payload["proposal_id"] in self.proposals:
                self.proposals[payload["proposal_id"]]["status"] = ProposalStatus.failed.value

        elif event.event_type == "rollback_started":
            self.rollbacks[payload["proposal_id"]].append(payload)

        elif event.event_type == "rollback_completed":
            self.rollbacks[payload["proposal_id"]].append(payload)
            if payload["proposal_id"] in self.proposals:
                self.proposals[payload["proposal_id"]]["status"] = ProposalStatus.rolled_back.value

    def snapshot(self) -> dict[str, Any]:
        return {
            "intents": list(self.intents.values()),
            "findings": list(self.findings.values()),
            "proposals": list(self.proposals.values()),
            "votes": self.votes,
            "policy_decisions": self.policy_decisions,
            "executions": self.executions,
            "rollbacks": self.rollbacks,
            "event_count": len(self.events),
        }

    def proposal_vote_summary(self, proposal_id: str) -> dict[str, int]:
        votes = self.votes.get(proposal_id, [])
        return {
            "approve": sum(1 for v in votes if v["decision"] == VoteDecision.approve.value),
            "reject": sum(1 for v in votes if v["decision"] == VoteDecision.reject.value),
        }
