"""Thin ``flyctl`` subprocess wrapper.

We shell to the ``fly`` binary rather than calling Fly's Machines API
(or GraphQL) directly. Rationale:

- The Machines-API deploy flow spans two surfaces (GraphQL for releases
  + REST for machines) — reimplementing it is ~600 LOC.
- Subprocess adds ~30 MB to the runtime image but is trivially testable
  (``monkeypatch.setattr(subprocess, "run", ...)``), which matches how
  we stub the GitHub client with ``respx``.
- Blast radius is bounded by the ``FlyDeploySpec`` pydantic validators:
  ``app`` is a ``Literal`` of exactly two values, ``image_digest`` is
  a sha256, tags are rejected.

See ``docs/design/fly-deployment.md`` open question #2 — this is the
resolved answer, superseding the original "lean: Machines API" line.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any


class FlyClientError(RuntimeError):
    """Base for fly-client errors."""


class FlyBinaryMissing(FlyClientError):
    """The ``fly`` binary is not on PATH."""


class FlyCommandFailed(FlyClientError):
    """Non-zero exit from the ``fly`` CLI.

    Carries the argv for debugging, but the stringified message truncates
    stderr to 200 chars so secrets embedded in a stray error line (e.g.
    a token echoed by a misbehaving subcommand) don't end up in the
    event log.
    """

    def __init__(self, argv: list[str], returncode: int, stderr: str) -> None:
        trimmed = stderr.strip().splitlines()[0][:200] if stderr.strip() else ""
        super().__init__(f"fly exited with {returncode}: {trimmed}")
        self.argv = argv
        self.returncode = returncode
        self.stderr = stderr


class FlyClient:
    """Calls the ``fly`` CLI for deploy + release-list operations.

    ``binary`` defaults to ``"fly"`` (first on PATH) but can be pointed
    at an explicit path or a fixture script in tests. Every call
    captures stdout + stderr and returns structured output — the client
    itself never prints or reads from the TTY.
    """

    def __init__(self, binary: str = "fly", *, timeout: float = 300.0) -> None:
        self.binary = binary
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Deploys
    # ------------------------------------------------------------------

    def deploy(self, *, app: str, image_digest: str, strategy: str = "rolling") -> dict[str, Any]:
        """Deploy ``registry.fly.io/<app>@<image_digest>`` to ``app``.

        Returns a dict capturing the deploy — either ``fly``'s own JSON
        output if the subcommand emits it, or a synthetic payload that
        carries raw stdout for auditability. The event log is the
        canonical record; this dict is whatever Fly felt like telling us.
        """
        image_ref = f"registry.fly.io/{app}@{image_digest}"
        argv = [
            self.binary,
            "deploy",
            "--app",
            app,
            "--image",
            image_ref,
            "--strategy",
            strategy,
            "--yes",
        ]
        raw = self._run_and_parse(argv)
        if isinstance(raw, dict):
            return raw
        # `fly deploy` sometimes emits a bare list or a scalar — wrap it
        # so callers always get a dict and the event-log payload stays
        # typed.
        return {"raw": str(raw)[:2000]}

    # ------------------------------------------------------------------
    # Releases (used by the rollback path to find the previous digest)
    # ------------------------------------------------------------------

    def releases(self, *, app: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return the most recent ``limit`` releases for ``app``.

        Each entry is whatever ``fly releases --json`` emits; the
        rollback path picks out the image ref from the second-most-recent.
        """
        argv = [
            self.binary,
            "releases",
            "--app",
            app,
            "--json",
        ]
        raw = self._run_and_parse(argv)
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)][:limit]
        return []

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _run_and_parse(self, argv: list[str]) -> Any:
        try:
            completed = subprocess.run(  # noqa: S603 — argv is list, not shell
                argv,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise FlyBinaryMissing(
                f"fly binary not found at '{self.binary}' — install flyctl"
            ) from exc

        if completed.returncode != 0:
            raise FlyCommandFailed(argv, completed.returncode, completed.stderr)

        stdout = completed.stdout.strip()
        if not stdout:
            return {}
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            # `fly deploy` doesn't always emit JSON on stdout. Keep the
            # raw output for replay auditability.
            return {"raw": stdout[:2000]}
