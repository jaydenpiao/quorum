"""Static checks for the production container runtime contract."""

from __future__ import annotations

import re
from pathlib import Path


DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"
PYTHON_BASE = (
    "python:3.12-slim@sha256:4386a385d81dba9f72ed72a6fe4237755d7f5440c84b417650f38336bbc43117"
)
UV_VERSION = "0.11.7"
FLYCTL_VERSION = "0.4.39"
FLYCTL_SHA256 = "87c89a59106e65569fb1d91aa2404a4d472248d240d87a5edfcace920d382f10"


def _dockerfile_text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def test_python_base_image_is_digest_pinned_for_all_stages() -> None:
    text = _dockerfile_text()

    stage_to_image = {
        stage: image
        for image, stage in re.findall(
            r"^FROM\s+(\S+)\s+AS\s+([a-z0-9_-]+)$",
            text,
            re.MULTILINE,
        )
    }

    assert stage_to_image == {
        "flyctl": PYTHON_BASE,
        "builder": PYTHON_BASE,
        "runtime": PYTHON_BASE,
    }


def test_uv_bootstrap_version_is_pinned() -> None:
    text = _dockerfile_text()

    assert f"ARG UV_VERSION={UV_VERSION}" in text
    assert 'pip install --no-cache-dir "uv==${UV_VERSION}"' in text


def test_flyctl_download_is_pinned_and_checksum_verified() -> None:
    text = _dockerfile_text()

    assert f"ARG FLYCTL_VERSION={FLYCTL_VERSION}" in text
    assert f"ARG FLYCTL_SHA256={FLYCTL_SHA256}" in text
    assert "flyctl_${FLYCTL_VERSION}_Linux_x86_64.tar.gz" in text
    assert "sha256sum -c -" in text
    assert "tar -xzf /tmp/flyctl.tar.gz -C /usr/local/bin flyctl" in text


def test_runtime_image_contains_only_fly_binary_from_flyctl_stage() -> None:
    text = _dockerfile_text()

    assert "COPY --from=flyctl /usr/local/bin/fly /usr/local/bin/fly" in text


def test_flyctl_is_verified_as_non_root_user_with_home() -> None:
    text = _dockerfile_text()

    assert (
        re.search(
            r"useradd --system --gid quorum\s+--create-home --home-dir /home/quorum quorum",
            text,
        )
        is not None
    )
    assert "ENV HOME=/home/quorum" in text
    assert re.search(r"USER quorum\s+RUN fly version", text) is not None
