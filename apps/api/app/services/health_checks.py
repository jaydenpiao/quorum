from __future__ import annotations

import subprocess

from apps.api.app.domain.models import HealthCheckResult, HealthCheckSpec, HealthCheckKind


class HealthCheckRunner:
    def run(self, spec: HealthCheckSpec) -> HealthCheckResult:
        if spec.kind == HealthCheckKind.always_pass:
            return HealthCheckResult(name=spec.name, passed=True, detail="simulated pass")

        if spec.kind == HealthCheckKind.always_fail:
            return HealthCheckResult(name=spec.name, passed=False, detail="simulated fail")

        if spec.kind == HealthCheckKind.shell:
            if not spec.command:
                return HealthCheckResult(
                    name=spec.name, passed=False, detail="missing shell command"
                )
            completed = subprocess.run(
                spec.command,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
            )
            detail = (completed.stdout + completed.stderr).strip()
            return HealthCheckResult(
                name=spec.name,
                passed=completed.returncode == 0,
                detail=detail or f"exit_code={completed.returncode}",
            )

        return HealthCheckResult(name=spec.name, passed=False, detail="unknown check type")
