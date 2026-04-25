"""Tests for the Fly.io actuator: specs, client subprocess layer, actions.

Three layers match the actuator module layout:

- ``FlyDeploySpec`` / ``FlyDeployResult`` validators (pydantic boundary).
- ``FlyClient`` — mock ``subprocess.run`` and assert argv + output
  translation.
- ``deploy`` / ``rollback_deploy`` — mock the client itself (a simpler
  stub) and assert orchestration behavior: previous-digest capture,
  rollback-impossible when no prior digest, happy rollback round-trip.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest
from pydantic import ValidationError

from apps.api.app.services.actuators.fly import (
    FlyActionError,
    FlyBinaryMissing,
    FlyClient,
    FlyCommandFailed,
    FlyDeployResult,
    FlyDeploySpec,
    FlyRollbackImpossibleError,
    deploy,
    rollback_deploy,
)

# ---------------------------------------------------------------------------
# Spec validation
# ---------------------------------------------------------------------------


def test_spec_accepts_valid_sha256_digest() -> None:
    spec = FlyDeploySpec(
        app="quorum-staging",
        image_digest="sha256:" + "a" * 64,
    )
    assert spec.app == "quorum-staging"
    assert spec.strategy == "rolling"


@pytest.mark.parametrize(
    "bad_digest",
    [
        "latest",
        "v1.2.3",
        "sha256:" + "a" * 63,  # too short
        "sha256:" + "a" * 65,  # too long
        "sha256:" + "A" * 64,  # uppercase hex rejected
        "sha256:" + "g" * 64,  # non-hex char
        "md5:" + "a" * 64,  # wrong algorithm prefix
    ],
)
def test_spec_rejects_non_sha256_digests(bad_digest: str) -> None:
    with pytest.raises(ValidationError):
        FlyDeploySpec(app="quorum-staging", image_digest=bad_digest)


def test_spec_rejects_unknown_app() -> None:
    with pytest.raises(ValidationError):
        FlyDeploySpec(
            app="quorum-adhoc",  # type: ignore[arg-type]
            image_digest="sha256:" + "a" * 64,
        )


def test_spec_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        FlyDeploySpec(
            app="quorum-prod",
            image_digest="sha256:" + "a" * 64,
            extra_knob="dangerous",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# FlyClient: subprocess.run mocked
# ---------------------------------------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_client_deploy_calls_fly_with_full_image_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_argv: list[list[str]] = []

    def fake_run(argv: list[str], **_: Any) -> _FakeCompleted:
        captured_argv.append(argv)
        return _FakeCompleted(stdout="{}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    client = FlyClient(binary="/usr/local/bin/fly")
    result = client.deploy(
        app="quorum-staging",
        image_digest="sha256:" + "a" * 64,
        strategy="immediate",
    )

    assert result == {}
    assert len(captured_argv) == 1
    argv = captured_argv[0]
    assert argv[0] == "/usr/local/bin/fly"
    assert argv[1] == "deploy"
    assert "--app" in argv and argv[argv.index("--app") + 1] == "quorum-staging"
    image_ref = argv[argv.index("--image") + 1]
    assert image_ref == "registry.fly.io/quorum-staging@sha256:" + "a" * 64
    assert argv[argv.index("--strategy") + 1] == "immediate"
    assert "--yes" in argv


def test_client_releases_parses_json_list(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = (
        '[{"ImageRef": {"Digest": "sha256:' + "b" * 64 + '"}},'
        '{"ImageRef": {"Digest": "sha256:' + "c" * 64 + '"}},'
        '{"ImageRef": {"Digest": "sha256:' + "d" * 64 + '"}}]'
    )
    captured_argv: list[list[str]] = []

    def fake_run(argv: list[str], **_: Any) -> _FakeCompleted:
        captured_argv.append(argv)
        return _FakeCompleted(stdout=payload)

    monkeypatch.setattr(subprocess, "run", fake_run)

    client = FlyClient()
    releases = client.releases(app="quorum-prod", limit=2)
    assert len(releases) == 2
    assert captured_argv == [
        ["fly", "releases", "--app", "quorum-prod", "--json"],
    ]
    assert releases[0]["ImageRef"]["Digest"] == "sha256:" + "b" * 64


def test_client_raises_binary_missing_on_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise FileNotFoundError(2, "no such file")

    monkeypatch.setattr(subprocess, "run", fake_run)

    client = FlyClient()
    with pytest.raises(FlyBinaryMissing):
        client.deploy(app="quorum-staging", image_digest="sha256:" + "a" * 64)


def test_client_raises_command_failed_on_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_a: Any, **_k: Any) -> _FakeCompleted:
        return _FakeCompleted(returncode=1, stderr="fly: authentication required")

    monkeypatch.setattr(subprocess, "run", fake_run)

    client = FlyClient()
    with pytest.raises(FlyCommandFailed) as excinfo:
        client.deploy(app="quorum-staging", image_digest="sha256:" + "a" * 64)
    assert excinfo.value.returncode == 1
    assert "authentication required" in str(excinfo.value)


def test_client_returns_raw_when_deploy_stdout_is_not_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_a: Any, **_k: Any) -> _FakeCompleted:
        return _FakeCompleted(stdout="Deployed v42 to quorum-staging")

    monkeypatch.setattr(subprocess, "run", fake_run)

    client = FlyClient()
    result = client.deploy(app="quorum-staging", image_digest="sha256:" + "a" * 64)
    assert result == {"raw": "Deployed v42 to quorum-staging"}


# ---------------------------------------------------------------------------
# Actions: deploy + rollback_deploy — stub the client directly
# ---------------------------------------------------------------------------


class _StubClient:
    """Drop-in for FlyClient; records calls and replays scripted responses."""

    def __init__(
        self,
        *,
        releases_response: list[dict[str, Any]] | None = None,
        deploy_response: dict[str, Any] | None = None,
        deploy_raises: Exception | None = None,
    ) -> None:
        self._releases = releases_response or []
        self._deploy_response = deploy_response or {}
        self._deploy_raises = deploy_raises
        self.deploy_calls: list[dict[str, Any]] = []
        self.releases_calls: list[dict[str, Any]] = []

    def deploy(self, *, app: str, image_digest: str, strategy: str = "rolling") -> dict[str, Any]:
        self.deploy_calls.append({"app": app, "image_digest": image_digest, "strategy": strategy})
        if self._deploy_raises is not None:
            raise self._deploy_raises
        return self._deploy_response

    def releases(self, *, app: str, limit: int = 5) -> list[dict[str, Any]]:
        self.releases_calls.append({"app": app, "limit": limit})
        return self._releases


def _spec(digest_suffix: str = "a" * 64) -> FlyDeploySpec:
    return FlyDeploySpec(
        app="quorum-staging",
        image_digest=f"sha256:{digest_suffix}",
        strategy="rolling",
    )


def test_deploy_records_previous_digest_from_releases() -> None:
    prior = "sha256:" + "b" * 64
    client = _StubClient(
        releases_response=[{"ImageRef": {"Digest": prior}}],
        deploy_response={"ReleaseId": "rel_123"},
    )

    result = deploy(client, _spec())  # type: ignore[arg-type]

    assert isinstance(result, FlyDeployResult)
    assert result.app == "quorum-staging"
    assert result.released_image_digest == "sha256:" + "a" * 64
    assert result.previous_image_digest == prior
    assert result.release_id == "rel_123"
    assert client.deploy_calls[0]["image_digest"] == "sha256:" + "a" * 64


def test_deploy_rejects_same_app_self_deploy_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLY_APP_NAME", "quorum-staging")
    client = _StubClient(
        releases_response=[{"ImageRef": {"Digest": "sha256:" + "b" * 64}}],
        deploy_response={"ReleaseId": "rel_123"},
    )

    with pytest.raises(FlyActionError) as excinfo:
        deploy(client, _spec())  # type: ignore[arg-type]

    assert "refusing same-app fly.deploy" in str(excinfo.value)
    assert client.releases_calls == []
    assert client.deploy_calls == []


def test_deploy_tolerates_unreadable_releases() -> None:
    client = _StubClient(
        releases_response=[{"nothing": "useful"}],
        deploy_response={},
    )
    result = deploy(client, _spec())  # type: ignore[arg-type]
    assert result.previous_image_digest == ""


def test_deploy_wraps_command_failure_as_action_error() -> None:
    client = _StubClient(
        deploy_raises=FlyCommandFailed(["fly", "deploy"], 1, "no"),
    )
    with pytest.raises(FlyActionError):
        deploy(client, _spec())  # type: ignore[arg-type]


def test_deploy_wraps_binary_missing_as_action_error() -> None:
    client = _StubClient(deploy_raises=FlyBinaryMissing("fly not on PATH"))
    with pytest.raises(FlyActionError):
        deploy(client, _spec())  # type: ignore[arg-type]


def test_rollback_deploy_redeploys_previous_digest() -> None:
    prior = "sha256:" + "b" * 64
    client = _StubClient(deploy_response={"ReleaseId": "rel_prev"})

    result = FlyDeployResult(
        app="quorum-staging",
        released_image_digest="sha256:" + "a" * 64,
        previous_image_digest=prior,
        strategy="rolling",
    )

    summary = rollback_deploy(client, result)  # type: ignore[arg-type]
    assert summary["rolled_back_to"] == prior
    assert summary["from"] == "sha256:" + "a" * 64
    assert summary["app"] == "quorum-staging"
    assert client.deploy_calls[0]["image_digest"] == prior


def test_rollback_deploy_without_previous_is_impossible() -> None:
    client = _StubClient()
    result = FlyDeployResult(
        app="quorum-staging",
        released_image_digest="sha256:" + "a" * 64,
        previous_image_digest="",  # no prior release
    )
    with pytest.raises(FlyRollbackImpossibleError) as excinfo:
        rollback_deploy(client, result)  # type: ignore[arg-type]
    assert "no previous image digest" in excinfo.value.reason


def test_rollback_deploy_wraps_client_failure_as_impossible() -> None:
    client = _StubClient(
        deploy_raises=FlyCommandFailed(["fly", "deploy"], 1, "boom"),
    )
    result = FlyDeployResult(
        app="quorum-staging",
        released_image_digest="sha256:" + "a" * 64,
        previous_image_digest="sha256:" + "b" * 64,
    )
    with pytest.raises(FlyRollbackImpossibleError) as excinfo:
        rollback_deploy(client, result)  # type: ignore[arg-type]
    assert "fly rollback deploy failed" in excinfo.value.reason
