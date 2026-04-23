"""Opt-in live Fly.io integration tests.

These tests intentionally mutate ``quorum-staging`` and are skipped in
default CI by both the global ``-m 'not integration'`` addopt and the
``QUORUM_FLY_LIVE_TESTS=1`` guard below.
"""

from __future__ import annotations

import os
import re
import shutil
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from apps.api.app.services.actuators.fly import (
    FlyClient,
    FlyDeploySpec,
    deploy,
    rollback_deploy,
)

pytestmark = pytest.mark.integration

_APP = "quorum-staging"
_READY_URL = "https://quorum-staging.fly.dev/readiness"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class _LiveFlyConfig:
    binary: str
    previous_digest: str
    new_digest: str


def _require_digest_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} not set; skipping live Fly integration test")
    if not _SHA256_RE.fullmatch(value):
        raise AssertionError(f"{name} must be a full sha256 digest")
    return value


def _resolve_fly_binary() -> str:
    raw = os.environ.get("QUORUM_FLY_BINARY", "fly").strip() or "fly"
    if "/" in raw:
        if not Path(raw).is_file():
            pytest.skip(f"QUORUM_FLY_BINARY does not exist: {raw}")
        return raw
    resolved = shutil.which(raw)
    if resolved is None:
        pytest.skip(f"{raw!r} not found on PATH; set QUORUM_FLY_BINARY")
    return resolved


def _live_config() -> _LiveFlyConfig:
    if os.environ.get("QUORUM_FLY_LIVE_TESTS") != "1":
        pytest.skip("set QUORUM_FLY_LIVE_TESTS=1 to run live Fly tests")
    if not os.environ.get("FLY_API_TOKEN", "").strip():
        pytest.skip("FLY_API_TOKEN not set; skipping live Fly integration test")
    return _LiveFlyConfig(
        binary=_resolve_fly_binary(),
        previous_digest=_require_digest_env("QUORUM_FLY_STAGING_PREVIOUS_DIGEST"),
        new_digest=_require_digest_env("QUORUM_FLY_STAGING_NEW_DIGEST"),
    )


def _release_digest(release: dict[str, Any]) -> str:
    image_ref = release.get("ImageRef") or release.get("image_ref") or release.get("image")
    if isinstance(image_ref, dict):
        digest = image_ref.get("Digest") or image_ref.get("digest") or ""
        return str(digest)
    if isinstance(image_ref, str) and "@sha256:" in image_ref:
        return image_ref.rsplit("@", 1)[1]
    return ""


def _latest_release_digest(client: FlyClient) -> str:
    releases = client.releases(app=_APP, limit=1)
    assert releases, "expected at least one Fly release"
    digest = _release_digest(releases[0])
    assert _SHA256_RE.fullmatch(digest), f"could not parse release digest: {releases[0]!r}"
    return digest


def _wait_until_ready(timeout_seconds: float = 180.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(_READY_URL, timeout=10) as response:
                if response.status == 200:
                    return
                last_error = f"HTTP {response.status}"
        except OSError as exc:
            last_error = repr(exc)
        time.sleep(3)
    raise AssertionError(f"{_READY_URL} did not become ready: {last_error}")


def test_live_fly_deploy_captures_previous_digest_and_rolls_back() -> None:
    cfg = _live_config()
    client = FlyClient(binary=cfg.binary, timeout=600.0)

    client.deploy(app=_APP, image_digest=cfg.previous_digest, strategy="rolling")
    _wait_until_ready()
    baseline_digest = _latest_release_digest(client)

    result = deploy(
        client,
        FlyDeploySpec(
            app=_APP,
            image_digest=cfg.new_digest,
            strategy="rolling",
        ),
    )
    _wait_until_ready()

    assert result.released_image_digest == cfg.new_digest
    assert result.previous_image_digest == baseline_digest
    assert _latest_release_digest(client) != baseline_digest

    summary = rollback_deploy(client, result)
    _wait_until_ready()

    assert summary["rolled_back_to"] == baseline_digest
    assert _latest_release_digest(client) == baseline_digest
