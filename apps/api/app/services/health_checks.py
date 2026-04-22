"""Typed health-check runner.

Registered kinds only — there is no subprocess path. Adding a new probe
type means extending ``HealthCheckKind`` and adding a branch here, not
shelling out to user-supplied strings.

Kinds:

- ``always_pass`` / ``always_fail`` — simulation, for demos and tests.
- ``http`` — single synchronous request, pass iff status matches.
- ``github_check_run`` — poll a commit's check-runs via the
  ``GitHubAppClient`` until every run is terminal. Used by
  ``github.open_pr`` to block the execution on CI.

Threading actuator results into the runner: the executor passes the
serialized actuator result as ``context`` to ``run()``. The only kind
that reads it today is ``github_check_run``, which falls back to
``context["head_sha"]`` when ``spec.github_commit_sha`` is unset —
this is the mechanism the operator uses to attach a check-runs probe
to an ``open_pr`` proposal without knowing the SHA in advance.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from apps.api.app.domain.models import HealthCheckKind, HealthCheckResult, HealthCheckSpec
from apps.api.app.services.actuators.github import GitHubApiError, GitHubAppClient


# Conclusions that count as "this CI run passed". Everything else is a
# failure (or still-running, which means we keep polling).
_PASSING_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})
_TERMINAL_CONCLUSIONS = _PASSING_CONCLUSIONS | frozenset(
    {
        "failure",
        "timed_out",
        "cancelled",
        "action_required",
        "startup_failure",
        "stale",
    }
)


class HealthCheckRunner:
    """Runs typed health checks.

    The runner is sync because ``EventLog.append`` and the executor are
    sync; flipping the whole chain async is a cross-cutting refactor
    (see sync-vs-async note in ``docs/design/postgres-projection.md``).
    """

    def __init__(
        self,
        *,
        github_client: GitHubAppClient | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._github_client = github_client
        # Injected so tests fast-forward the polling loop without
        # actually sleeping. Prod uses ``time.sleep``.
        self._sleep = sleep_fn

    def run(
        self,
        spec: HealthCheckSpec,
        *,
        context: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        if spec.kind is HealthCheckKind.always_pass:
            return HealthCheckResult(name=spec.name, passed=True, detail="simulated pass")

        if spec.kind is HealthCheckKind.always_fail:
            return HealthCheckResult(name=spec.name, passed=False, detail="simulated fail")

        if spec.kind is HealthCheckKind.http:
            return self._run_http(spec)

        if spec.kind is HealthCheckKind.github_check_run:
            return self._run_github_check_run(spec, context or {})

        return HealthCheckResult(name=spec.name, passed=False, detail="unknown check type")

    def _run_http(self, spec: HealthCheckSpec) -> HealthCheckResult:
        url = spec.url or ""
        try:
            with httpx.Client(follow_redirects=False) as client:
                response = client.request(spec.method, url, timeout=spec.timeout_seconds)
            passed = response.status_code == spec.expected_status
            return HealthCheckResult(
                name=spec.name,
                passed=passed,
                detail=(
                    f"http {spec.method} {url} -> {response.status_code} "
                    f"(expected {spec.expected_status})"
                ),
            )
        except httpx.HTTPError as exc:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                detail=f"http {spec.method} {url} failed: {type(exc).__name__}: {exc}",
            )

    def _run_github_check_run(
        self, spec: HealthCheckSpec, context: dict[str, Any]
    ) -> HealthCheckResult:
        if self._github_client is None:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                detail="github_check_run requires a configured GitHub App client",
            )

        owner = spec.github_owner or ""
        repo = spec.github_repo or ""
        commit_sha = spec.github_commit_sha or _string_field(context, "head_sha")
        check_name = spec.github_check_name
        if not owner or not repo:
            # Caught by the spec validator too, but this guards against
            # reflection shims that bypass pydantic construction.
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                detail="github_check_run missing owner or repo",
            )
        if not commit_sha:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                detail=(
                    "github_check_run has no commit_sha; set github_commit_sha on the "
                    "spec or run alongside an actuator that emits head_sha in its result"
                ),
            )

        installation = self._github_client.config.installation_for(owner, repo)
        if installation is None:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                detail=f"github_check_run: no installation configured for {owner}/{repo}",
            )

        deadline = time.monotonic() + spec.timeout_seconds
        observed_any = False
        last_pending_detail = ""

        while True:
            try:
                runs = self._github_client.list_commit_check_runs(
                    installation.installation_id, owner, repo, commit_sha
                )
            except GitHubApiError as exc:
                return HealthCheckResult(
                    name=spec.name,
                    passed=False,
                    detail=(f"github_check_run list failed: {exc.status_code}: {exc.message}"),
                )

            if check_name:
                runs = [r for r in runs if r.get("name") == check_name]

            if runs:
                observed_any = True

            terminal, failed_run, pending_run = _classify_runs(runs)
            if failed_run is not None:
                return HealthCheckResult(
                    name=spec.name,
                    passed=False,
                    detail=(
                        f"github_check_run '{failed_run.get('name', '?')}' "
                        f"conclusion={failed_run.get('conclusion')!r}"
                    ),
                )
            if runs and terminal:
                # Every run is complete and none failed → pass.
                names = ", ".join(str(r.get("name", "?")) for r in runs)
                return HealthCheckResult(
                    name=spec.name,
                    passed=True,
                    detail=f"github_check_run all passed: {names}",
                )

            if pending_run is not None:
                last_pending_detail = (
                    f"waiting on '{pending_run.get('name', '?')}' "
                    f"(status={pending_run.get('status')!r})"
                )

            # Sleep until next poll or deadline, whichever is sooner.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._sleep(min(spec.poll_interval_seconds, remaining))

        if not observed_any:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                detail=(
                    f"github_check_run: no check runs observed for {commit_sha} "
                    f"within {spec.timeout_seconds:.0f}s"
                ),
            )
        return HealthCheckResult(
            name=spec.name,
            passed=False,
            detail=(
                f"github_check_run: timeout after {spec.timeout_seconds:.0f}s "
                f"({last_pending_detail or 'still running'})"
            ),
        )


def _string_field(context: dict[str, Any], key: str) -> str:
    value = context.get(key)
    if isinstance(value, str) and value:
        return value
    return ""


def _classify_runs(
    runs: list[dict[str, Any]],
) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None]:
    """Return ``(all_terminal, first_failed, first_pending)`` over the run list.

    - ``all_terminal`` is True iff every run has reached a terminal state.
    - ``first_failed`` is the first run whose conclusion is in the
      non-passing terminal set, or None.
    - ``first_pending`` is the first still-running run, or None.
    """
    all_terminal = True
    first_failed: dict[str, Any] | None = None
    first_pending: dict[str, Any] | None = None
    for run in runs:
        status = run.get("status")
        conclusion = run.get("conclusion")
        if status == "completed" and isinstance(conclusion, str):
            if conclusion not in _PASSING_CONCLUSIONS and first_failed is None:
                if conclusion in _TERMINAL_CONCLUSIONS:
                    first_failed = run
        else:
            all_terminal = False
            if first_pending is None:
                first_pending = run
    return all_terminal, first_failed, first_pending
