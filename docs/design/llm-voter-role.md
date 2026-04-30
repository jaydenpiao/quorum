# Design: LLM Voter Role

Status: implementation series in progress. The API/policy/read-model
support for structured LLM vote metadata and policy-owned vote caps is
implemented, and the adapter has a separate `review-llm-agent` role
with a `cast_vote` tool. Console polish is still a follow-up PR.

This document resolves the voter-role open question from
`docs/design/llm-adapter.md`. Quorum's telemetry/deploy LLM agents
remain proposer-only; review voting is isolated in `review-llm-agent`.
This document describes the safety contract for that role.

Server-side `config/agents.yaml` flags are enforced before mutation:
`can_propose=false` blocks proposal creation and `can_vote=false`
blocks vote creation. The shipped `telemetry-llm-agent` and
`deploy-llm-agent` keep `can_vote: false`; `review-llm-agent` has
`can_vote: true`, `can_propose: false`, and a narrow
`allowed_vote_action_types` list.

## Goal

Allow an LLM-backed agent to contribute review signal on narrowly
scoped proposals without weakening Quorum's core guarantees: policy
first, quorum before mutation, human approval for protected work, and a
complete audit trail.

## Non-Goals

- No new event types.
- No new mutation routes.
- No proposal schema changes.
- No autonomous execution.
- No LLM voter for `fly.deploy` in the first implementation.

## Safety Contract

- LLM votes may count only under explicit per-action trust caps.
- LLM votes must never be sufficient alone for protected/high-risk
  actions.
- Default policy posture is zero counted LLM votes unless an action
  type opts in.
- Any proposal with `requires_human=true` still requires a human
  approval outcome before execution, regardless of LLM votes.
- An LLM voter must not vote on a proposal authored by the same
  `agent_id`; self-review does not count toward quorum.
- A failed model call, missing prompt hash, policy ambiguity, or
  unsupported action type must produce no vote.

## First Allowed Surface

The first implementation should be limited to low-risk GitHub actions:

- `github.add_labels`
- `github.comment_issue`

The first implementation should not count LLM votes for:

- `fly.deploy`
- `github.open_pr`
- `github.close_pr`
- any protected/high-risk action whose quorum could be carried by LLM
  votes without a human vote

`allowed_action_types` remains the server-side action allow-list for
proposals. Vote authority is controlled separately with
`allowed_vote_action_types` so proposal authority and vote authority
cannot drift together accidentally.

The implementation opts only `review-llm-agent` into `can_vote: true`;
without that config change, the API rejects the vote before it reaches
the event log.

## Policy Expectations

Policy decides whether an LLM vote counts, not the adapter process.
`config/policies.yaml` now defaults LLM votes to zero counted votes and
opts in only specific low-risk actions via `llm_vote_caps`:

- default maximum counted LLM votes is `0`
- `github.add_labels` may count at most one LLM vote
- `github.comment_issue` may count at most one LLM vote
- protected environments and high/critical risk override the effective
  LLM vote cap to zero

For protected/high-risk actions, the effective rule is: an LLM vote may
be recorded for audit only if desired, but it cannot be enough to make
the proposal executable.

## Audit Metadata

Every LLM-emitted vote must carry enough audit metadata to explain the
decision later:

- `agent_id`
- `voter_kind`
- `llm_model`
- `system_prompt_sha256`
- `observed_event_cursor`
- concise rationale
- `counted`
- `counted_reason`

The implementation reuses the existing `proposal_voted` event type and
`POST /api/v1/votes` route. Non-LLM callers remain backward-compatible
and cannot spoof LLM metadata; configured LLM callers must provide the
model, prompt hash, and observed cursor. The server sets `voter_kind`,
`counted`, and `counted_reason` before appending the event.

## Console Visibility

The console should make LLM votes visibly different from human or
non-LLM agent votes:

- show source as `llm-voter`
- show model and `system_prompt_sha256`
- show whether the vote counted or was capped by policy
- keep the existing executable-state explanation so a capped LLM vote
  cannot make the operator think a proposal is ready

## Acceptance Criteria

The implementation series is not complete unless tests prove:

- Configured LLM agents with `can_vote=false` cannot append vote
  events.
- LLM votes are ignored by default.
- LLM votes count only for explicitly allowed action types.
- Protected/high-risk proposals cannot become executable from LLM
  votes alone.
- Same-agent self-votes do not count.
- `requires_human=true` still blocks execution until human approval is
  granted.
- Console copy distinguishes counted, capped, and non-counting LLM
  votes.
