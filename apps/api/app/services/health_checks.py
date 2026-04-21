from __future__ import annotations

import httpx

from apps.api.app.domain.models import HealthCheckKind, HealthCheckResult, HealthCheckSpec


class HealthCheckRunner:
    """Runs typed health checks.

    Registered kinds only — there is no subprocess path. Adding a new probe
    type means extending `HealthCheckKind` and adding a branch here, not
    shelling out to user-supplied strings.
    """

    def run(self, spec: HealthCheckSpec) -> HealthCheckResult:
        if spec.kind is HealthCheckKind.always_pass:
            return HealthCheckResult(name=spec.name, passed=True, detail="simulated pass")

        if spec.kind is HealthCheckKind.always_fail:
            return HealthCheckResult(name=spec.name, passed=False, detail="simulated fail")

        if spec.kind is HealthCheckKind.http:
            return self._run_http(spec)

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
                detail=f"http {spec.method} {url} -> {response.status_code} (expected {spec.expected_status})",
            )
        except httpx.HTTPError as exc:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                detail=f"http {spec.method} {url} failed: {type(exc).__name__}: {exc}",
            )
