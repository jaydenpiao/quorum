from __future__ import annotations

from datetime import datetime, UTC
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


STRICT_INPUT = ConfigDict(extra="forbid", str_strip_whitespace=True)


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ProposalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    blocked = "blocked"
    executed = "executed"
    failed = "failed"
    rolled_back = "rolled_back"


class VoteDecision(str, Enum):
    approve = "approve"
    reject = "reject"


class ExecutionStatus(str, Enum):
    started = "started"
    succeeded = "succeeded"
    failed = "failed"
    rolled_back = "rolled_back"


class HealthCheckKind(str, Enum):
    always_pass = "always_pass"
    always_fail = "always_fail"
    http = "http"


class IntentCreate(BaseModel):
    model_config = STRICT_INPUT

    title: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=4000)
    environment: str = Field(default="local", max_length=64)
    requested_by: str = Field(default="operator", max_length=128)


class Intent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("intent"))
    title: str
    description: str
    environment: str = "local"
    requested_by: str = "operator"
    created_at: datetime = Field(default_factory=utc_now)


class FindingCreate(BaseModel):
    model_config = STRICT_INPUT

    intent_id: str = Field(max_length=128)
    # Optional because the server binds the authenticated agent if omitted;
    # if provided it must match the authenticated agent (enforced in routes).
    agent_id: str | None = Field(default=None, max_length=128)
    summary: str = Field(min_length=1, max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: new_id("finding"))
    intent_id: str
    agent_id: str
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    created_at: datetime = Field(default_factory=utc_now)


_UNSAFE_URL_CHARS = frozenset(";`$\n\r\t ")


class HealthCheckSpec(BaseModel):
    name: str
    kind: HealthCheckKind = HealthCheckKind.always_pass
    # Fields used only when kind == HealthCheckKind.http.
    url: str | None = None
    method: Literal["GET", "HEAD"] = "GET"
    expected_status: int = Field(default=200, ge=100, le=599)
    timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)

    @model_validator(mode="after")
    def _validate_http_fields(self) -> "HealthCheckSpec":
        if self.kind is HealthCheckKind.http:
            if not self.url:
                raise ValueError("http health check requires a url")
            if not (self.url.startswith("http://") or self.url.startswith("https://")):
                raise ValueError("http health check url must use http:// or https://")
            if any(c in _UNSAFE_URL_CHARS for c in self.url):
                raise ValueError("http health check url contains unsafe characters")
            if "$(" in self.url or "`" in self.url:
                raise ValueError("http health check url contains command-substitution syntax")
        return self


class ProposalCreate(BaseModel):
    model_config = STRICT_INPUT

    intent_id: str = Field(max_length=128)
    agent_id: str | None = Field(default=None, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    action_type: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=256)
    environment: str = Field(default="local", max_length=64)
    risk: RiskLevel = RiskLevel.low
    rationale: str = Field(min_length=1, max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    rollback_steps: list[str] = Field(default_factory=list, max_length=50)
    health_checks: list[HealthCheckSpec] = Field(default_factory=list, max_length=20)


class Proposal(BaseModel):
    id: str = Field(default_factory=lambda: new_id("proposal"))
    intent_id: str
    agent_id: str
    title: str
    action_type: str
    target: str
    environment: str = "local"
    risk: RiskLevel = RiskLevel.low
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list)
    rollback_steps: list[str] = Field(default_factory=list)
    health_checks: list[HealthCheckSpec] = Field(default_factory=list)
    status: ProposalStatus = ProposalStatus.pending
    created_at: datetime = Field(default_factory=utc_now)


class VoteCreate(BaseModel):
    model_config = STRICT_INPUT

    proposal_id: str = Field(max_length=128)
    agent_id: str | None = Field(default=None, max_length=128)
    decision: VoteDecision
    reason: str = Field(default="", max_length=2000)


class Vote(BaseModel):
    id: str = Field(default_factory=lambda: new_id("vote"))
    proposal_id: str
    agent_id: str
    decision: VoteDecision
    reason: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class PolicyDecision(BaseModel):
    proposal_id: str
    allowed: bool
    requires_human: bool
    votes_required: int
    reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class HealthCheckResult(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class ExecutionRequest(BaseModel):
    actor_id: str = "operator"


class ExecutionRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("exec"))
    proposal_id: str
    actor_id: str
    status: ExecutionStatus
    health_checks: list[HealthCheckResult] = Field(default_factory=list)
    detail: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class RollbackRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rollback"))
    proposal_id: str
    actor_id: str
    steps: list[str] = Field(default_factory=list)
    status: Literal["started", "completed"] = "started"
    created_at: datetime = Field(default_factory=utc_now)


class EventEnvelope(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt"))
    event_type: str
    entity_type: str
    entity_id: str
    ts: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any]
    # Tamper-evidence chain. prev_hash is None for the genesis event.
    # Both fields are populated by EventLog.append; callers should not set them.
    prev_hash: str | None = None
    hash: str | None = None
