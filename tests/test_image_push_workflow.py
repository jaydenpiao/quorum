"""Static checks for the image-push GitHub Actions workflow."""

from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "image-push.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_image_push_publishes_staging_and_prod_tags() -> None:
    text = _workflow_text()

    assert "registry.fly.io/quorum-staging:${{ github.sha }}" in text
    assert "registry.fly.io/quorum-prod:${{ github.sha }}" in text


def test_image_push_skips_docs_only_pushes() -> None:
    text = _workflow_text()

    assert "paths-ignore:" in text
    assert "'**/*.md'" in text
    assert "'docs/**'" in text


def test_image_push_records_staging_and_prod_digests() -> None:
    text = _workflow_text()

    assert "STAGING_DIGEST=$(docker buildx imagetools inspect" in text
    assert "PROD_DIGEST=$(docker buildx imagetools inspect" in text
    assert "registry.fly.io/quorum-staging:${{ github.sha }}" in text
    assert "registry.fly.io/quorum-prod:${{ github.sha }}" in text
    assert "staging digest" in text
    assert "prod digest" in text


def test_image_push_optionally_posts_quorum_evidence() -> None:
    text = _workflow_text()

    assert "QUORUM_IMAGE_PUSH_API_URL" in text
    assert "QUORUM_IMAGE_PUSH_API_KEY" in text
    assert "/api/v1/image-pushes" in text
    assert "image_push_completed" in text
    assert "image_push_completed evidence post failed" in text
    assert "staging_image_ref" in text
    assert "prod_image_ref" in text
