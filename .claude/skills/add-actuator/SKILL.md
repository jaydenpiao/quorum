---
name: add-actuator
description: Use when adding a new actuator to Quorum (e.g., GitHub, Kubernetes, Terraform, Slack-notifier). Actuators are the adapters that turn approved proposals into real-world mutations. Ensures the actuator is registered with the executor, gated by policy + quorum, emits execution events, handles rollback, and ships with tests.
---

# Skill: add-actuator

An actuator is where the control plane stops being pure and touches real infrastructure. It is the highest-risk surface in the codebase. Every actuator must honor the same non-negotiables as any other execution path — policy, quorum, logging, health-check verification, rollback readiness.

## When to invoke this skill

You need an actuator when a proposal's `action_type` cannot be executed by any existing adapter. Examples:
- `github.open_pr` — opens a PR via the GitHub API (Phase 4 first actuator)
- `k8s.apply_manifest` — `kubectl apply` with server-side-apply
- `terraform.plan_and_apply` — runs `terraform plan`, gates on human approval, then applies
- `slack.notify` — sends a message to a channel (no mutation of prod infra; still an actuator)

Do **not** invoke this skill for:
- Adding a new `HealthCheckKind` (that's a health-check, not an actuator — they live in `services/health_checks.py`).
- Extending an existing actuator with a new action verb (same actuator, new method).

## Checklist

### 1. Module layout

Create `apps/api/app/services/actuators/<name>.py`. Keep each actuator in its own file. Interface:

```python
from apps.api.app.domain.models import Proposal, ExecutionRecord, HealthCheckResult

class GitHubActuator:
    def execute(self, proposal: Proposal) -> ExecutionRecord: ...
    def rollback(self, proposal: Proposal, execution: ExecutionRecord) -> None: ...
```

The actuator returns an `ExecutionRecord` — it does not emit events itself. The caller (`executor.py`) emits `execution_started` before calling and `execution_succeeded` or `execution_failed` based on the record.

### 2. Registration in executor

In `apps/api/app/services/executor.py`, map `action_type` → actuator. The executor dispatches. Unknown `action_type` values return a failed ExecutionRecord with `detail="no actuator registered"` — they do not raise.

### 3. Authentication

Actuators that hit external APIs read credentials from env, never from the proposal payload. GitHub → GitHub App with scoped install, not a PAT. Kubernetes → service account or kubeconfig mounted at a known path. Never print tokens to logs; scrub if they appear in error strings.

### 4. Policy gating

Every `action_type` the actuator handles must be known to `config/policies.yaml`. Add it to the risk rules if needed. Denied action types (e.g., `delete-database`) stay denied; the actuator is never consulted for them.

### 5. Rollback

Every actuator implements `rollback`. "Can't rollback" is a valid strategy — if you decide that, document why in the actuator's docstring and ensure `proposal.rollback_steps` is empty-or-manual. Never silently no-op a rollback for a destructive action.

### 6. Health checks

An actuator that opens a PR has a natural health check: "did CI pass on that PR?" Use `HealthCheckKind.github_check_run` (Phase 4) or `http` probes. Health checks are registered in `services/health_checks.py` and referenced by name from the proposal's `health_checks` list.

### 7. Sandboxing

If the actuator shells out (kubectl, terraform, gh), **never** `shell=True`. Build argv lists explicitly. Whitelist binaries via `config/system.yaml`. Timeouts on every subprocess call.

### 8. Tests

`tests/test_<name>_actuator.py` must cover:
- Happy path: successful execute returns `ExecutionStatus.succeeded`.
- Failure path: external API 500 returns `ExecutionStatus.failed` with the error in `detail`.
- Auth path: missing credential raises a clear error before any network call.
- Rollback: `rollback` is called after `execution_failed` and leaves the external system in the pre-execution state (or emits a clear "manual rollback required" message).
- Mocking: use `httpx.MockTransport` or `respx` for HTTP; never hit real APIs from tests.

### 9. Documentation

- Add the actuator to `docs/ARCHITECTURE.md` under "Actuators" (create the section if it doesn't exist yet).
- Add a row to `docs/REPO_MAP.md` for the new module.
- Add an example proposal to `examples/` showing the new `action_type` in use.

## Verification

```bash
ruff check . && ruff format --check . && pytest -q tests/test_<name>_actuator.py
```

Then end-to-end:
```bash
# With make dev running:
curl -sX POST http://127.0.0.1:8080/api/v1/intents -d '{"title":"test","description":"test"}' -H 'Content-Type: application/json'
# ... create proposal with the new action_type, vote, execute, verify events.jsonl
```

Read the resulting `data/events.jsonl` and confirm every state transition emitted an event.

## Anti-patterns

- **Actuator that emits its own events.** That bypasses the executor's contract. The executor is the single emission site for execution events.
- **Action without rollback plan.** Document and test the rollback path before landing the actuator. Every destructive action has at least a documented manual-rollback procedure.
- **Credentials in proposals.** Never. Credentials come from the environment the actuator runs in; proposals carry only references (e.g., "repo: foo/bar", not "token: ghp_...").
- **Skipping policy.** The actuator does not decide whether it may run. The policy engine does. Do not add fast-paths.
