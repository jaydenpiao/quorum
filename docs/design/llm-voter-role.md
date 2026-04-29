# Design: LLM Voter Role

Status: design only - no LLM voting behavior is implemented.

This document resolves the voter-role open question from
`docs/design/llm-adapter.md`. Quorum's shipped LLM agents remain
proposer-only. This design describes the safety contract required
before a future implementation may let an LLM-backed agent cast votes.

As of the capability-gate hardening pass, server-side
`config/agents.yaml` flags are enforced before mutation:
`can_propose=false` blocks proposal creation and `can_vote=false`
blocks vote creation. The shipped LLM agents keep `can_vote: false`
until a separate voter implementation intentionally changes
capabilities, policy, tests, and console copy.

## Goal

Allow an LLM-backed agent to contribute review signal on narrowly
scoped proposals without weakening Quorum's core guarantees: policy
first, quorum before mutation, human approval for protected work, and a
complete audit trail.

## Non-Goals

- No implementation.
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
proposals. A future voter implementation needs a separate explicit
vote allow-list or policy capability so proposal authority and vote
authority cannot drift together accidentally.

The implementation must also opt the target LLM agent into
`can_vote: true`; without that config change, the API rejects the vote
before it reaches the event log.

## Policy Expectations

Policy must decide whether an LLM vote counts, not the adapter process.
The future implementation should make these policy properties explicit:

- action type is eligible for LLM voting
- max counted LLM votes for that action type
- whether a human/non-LLM vote is required
- whether protected environments override the LLM vote cap to zero
- whether the proposal author is disqualified from voting

For protected/high-risk actions, the effective rule is: an LLM vote may
be recorded for audit only if desired, but it cannot be enough to make
the proposal executable.

## Audit Metadata

Every LLM-emitted vote must carry enough audit metadata to explain the
decision later:

- `agent_id`
- `model`
- `system_prompt_sha256`
- observed proposal ID and event cursor
- concise rationale
- whether the vote counted after policy caps

The implementation should prefer existing event/audit shapes where
possible. If extra metadata cannot fit without ambiguity, add a small
design review before changing schemas.

## Console Visibility

The console should make LLM votes visibly different from human or
non-LLM agent votes:

- show source as `llm-voter`
- show model and `system_prompt_sha256`
- show whether the vote counted or was capped by policy
- keep the existing executable-state explanation so a capped LLM vote
  cannot make the operator think a proposal is ready

## Future Acceptance Criteria

A future implementation PR is not complete unless tests prove:

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
