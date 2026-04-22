"""Fly deploy + rollback orchestration.

These are the functions the executor dispatches to. They wrap
``FlyClient`` with the shape the ``_ACTION_DISPATCH`` /
``_ROLLBACK_DISPATCH`` tables expect (typed spec in, typed result out;
rollback takes the captured result and returns a summary dict).

Only one action type lives here today — ``fly.deploy``. Adding
``fly.restart`` or ``fly.scale`` later would follow the same shape.
"""

from __future__ import annotations

from typing import Any

from apps.api.app.services.actuators.fly.client import (
    FlyBinaryMissing,
    FlyClient,
    FlyClientError,
    FlyCommandFailed,
)
from apps.api.app.services.actuators.fly.specs import FlyDeploySpec, FlyDeployResult


class FlyActionError(RuntimeError):
    """Raised when a fly.* action fails in a way the executor should log as
    ``execution_failed``. Distinct from ``FlyClientError`` — wraps it so
    the executor's exception table doesn't need to know about the client
    module internals.
    """


class FlyRollbackImpossibleError(RuntimeError):
    """Raised when ``rollback_deploy`` can't determine a previous digest.

    The executor translates this into a ``rollback_impossible`` event so
    the proposal lands in ``ProposalStatus.rollback_impossible`` and a
    human reconciles.
    """

    def __init__(self, reason: str, actuator_state: dict[str, Any]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.actuator_state = actuator_state


def _extract_image_digest(release: dict[str, Any]) -> str:
    """Pull the image digest out of a ``fly releases --json`` entry.

    Fly's JSON shape is ``{"ImageRef": {"Digest": "sha256:..."} ...}``
    (capitalization may vary across flyctl versions). We look at both
    common casings; anything else returns "".
    """
    for outer_key in ("ImageRef", "imageRef", "image_ref", "image"):
        ref = release.get(outer_key)
        if isinstance(ref, dict):
            for inner_key in ("Digest", "digest"):
                digest = ref.get(inner_key)
                if isinstance(digest, str) and digest.startswith("sha256:"):
                    return digest
        elif isinstance(ref, str) and "@sha256:" in ref:
            return ref.split("@", 1)[1]
    return ""


def deploy(client: FlyClient, spec: FlyDeploySpec) -> FlyDeployResult:
    """Deploy ``spec.image_digest`` to ``spec.app``.

    Looks up the current release first so we have a ``previous_image_digest``
    to feed the rollback path. A missing or unreadable release list is
    not fatal — the deploy goes ahead with an empty previous digest
    (rollback will then emit ``rollback_impossible``).
    """
    previous_digest = ""
    try:
        current = client.releases(app=spec.app, limit=1)
        if current:
            previous_digest = _extract_image_digest(current[0])
    except FlyClientError:
        # Don't fail a deploy because we couldn't introspect prior state;
        # the deploy flow is authoritative. Rollback paths will notice.
        previous_digest = ""

    try:
        raw = client.deploy(app=spec.app, image_digest=spec.image_digest, strategy=spec.strategy)
    except FlyBinaryMissing as exc:
        raise FlyActionError(str(exc)) from exc
    except FlyCommandFailed as exc:
        raise FlyActionError(f"fly deploy failed: {exc}") from exc

    release_id = ""
    if isinstance(raw, dict):
        rid = raw.get("ReleaseId") or raw.get("releaseId") or raw.get("release_id")
        if isinstance(rid, str):
            release_id = rid

    return FlyDeployResult(
        app=spec.app,
        released_image_digest=spec.image_digest,
        previous_image_digest=previous_digest,
        release_id=release_id,
        strategy=spec.strategy,
    )


def rollback_deploy(client: FlyClient, result: FlyDeployResult) -> dict[str, Any]:
    """Redeploy the previous image digest that was live before this action.

    Raises ``FlyRollbackImpossibleError`` when there is no previous digest
    to redeploy (first-ever deploy, or introspection failed at forward
    time). The executor translates that into a ``rollback_impossible``
    event; no silent "rollback succeeded" when we actually can't undo.
    """
    if not result.previous_image_digest:
        raise FlyRollbackImpossibleError(
            reason=(
                "no previous image digest captured at deploy time; "
                "either this was the first deploy or the release list "
                "was unreadable — manual reconcile required"
            ),
            actuator_state=result.model_dump(mode="json"),
        )

    try:
        raw = client.deploy(
            app=result.app,
            image_digest=result.previous_image_digest,
            strategy=result.strategy,
        )
    except FlyBinaryMissing as exc:
        raise FlyRollbackImpossibleError(
            reason=f"fly binary unavailable during rollback: {exc}",
            actuator_state=result.model_dump(mode="json"),
        ) from exc
    except FlyCommandFailed as exc:
        raise FlyRollbackImpossibleError(
            reason=f"fly rollback deploy failed: {exc}",
            actuator_state=result.model_dump(mode="json"),
        ) from exc

    return {
        "rolled_back_to": result.previous_image_digest,
        "from": result.released_image_digest,
        "app": result.app,
        "raw": raw if isinstance(raw, dict) else {"raw": str(raw)[:500]},
    }
