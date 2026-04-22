"""Tests for ``github.add_labels`` action + rollback (Phase 4 PR D)."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from apps.api.app.services.actuators.github import (
    AddLabelsResult,
    GitHubAddLabelsSpec,
    GitHubAppClient,
    GitHubAppConfig,
    GitHubAppLimits,
    GitHubInstallation,
    RollbackImpossibleError,
    add_labels,
    rollback_add_labels,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def private_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


@pytest.fixture
def http_client() -> Iterator[httpx.Client]:
    with httpx.Client() as c:
        yield c


def _config() -> GitHubAppConfig:
    return GitHubAppConfig(
        app_id=42,
        installations=[GitHubInstallation(owner="jaydenpiao", repo="quorum", installation_id=7)],
        limits=GitHubAppLimits(),
    )


@pytest.fixture
def client(private_pem: str, http_client: httpx.Client) -> GitHubAppClient:
    return GitHubAppClient(_config(), private_key_pem=private_pem, http_client=http_client)


def _spec(**overrides: object) -> GitHubAddLabelsSpec:
    defaults: dict[str, object] = {
        "owner": "jaydenpiao",
        "repo": "quorum",
        "issue_number": 42,
        "labels": ["bug", "needs-triage"],
    }
    defaults.update(overrides)
    return GitHubAddLabelsSpec.model_validate(defaults)


def _token(mock: respx.MockRouter) -> None:
    mock.post("https://api.github.com/app/installations/7/access_tokens").mock(
        return_value=httpx.Response(
            200, json={"token": "ghs_t", "expires_at": "2099-01-01T00:00:00Z"}
        )
    )


def _label_response(*names: str) -> httpx.Response:
    return httpx.Response(200, json=[{"name": n, "color": "aaaaaa"} for n in names])


# ---------------------------------------------------------------------------
# Spec boundary
# ---------------------------------------------------------------------------


def test_spec_rejects_empty_labels() -> None:
    with pytest.raises(ValidationError):
        GitHubAddLabelsSpec.model_validate(
            {"owner": "o", "repo": "r", "issue_number": 1, "labels": []}
        )


def test_spec_rejects_duplicate_labels() -> None:
    with pytest.raises(ValidationError):
        GitHubAddLabelsSpec.model_validate(
            {"owner": "o", "repo": "r", "issue_number": 1, "labels": ["bug", "bug"]}
        )


def test_spec_rejects_empty_label() -> None:
    """Whitespace is auto-stripped by ``str_strip_whitespace=True``; empty
    string passes that but fails the explicit validator below."""
    with pytest.raises(ValidationError):
        GitHubAddLabelsSpec.model_validate(
            {"owner": "o", "repo": "r", "issue_number": 1, "labels": [""]}
        )


def test_spec_rejects_overlong_label() -> None:
    with pytest.raises(ValidationError):
        GitHubAddLabelsSpec.model_validate(
            {"owner": "o", "repo": "r", "issue_number": 1, "labels": ["x" * 51]}
        )


# ---------------------------------------------------------------------------
# Action — list-then-diff so pre-existing labels aren't rolled back
# ---------------------------------------------------------------------------


def test_add_labels_captures_only_new_labels(client: GitHubAppClient) -> None:
    """One requested label is already on the issue; only the other is 'added'."""
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/issues/42/labels").mock(
            return_value=_label_response("needs-triage", "release-blocker")
        )
        add = mock.post("https://api.github.com/repos/jaydenpiao/quorum/issues/42/labels").mock(
            return_value=_label_response("needs-triage", "release-blocker", "bug")
        )

        result = add_labels(client, _spec(), proposal_id="proposal_abc")

    assert result.labels_added == ["bug"]
    assert result.labels_already_present == ["needs-triage"]
    assert add.call_count == 1
    # And the POST body carries only the diff (so GitHub doesn't echo
    # label-already-there errors back).
    assert add.calls[0].request.content == b'{"labels":["bug"]}'


def test_add_labels_skips_post_when_all_present(client: GitHubAppClient) -> None:
    """If every requested label is already there, we do no POST."""
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/issues/42/labels").mock(
            return_value=_label_response("bug", "needs-triage")
        )
        add = mock.post("https://api.github.com/repos/jaydenpiao/quorum/issues/42/labels")

        result = add_labels(client, _spec(), proposal_id="proposal_abc")

    assert result.labels_added == []
    assert sorted(result.labels_already_present) == ["bug", "needs-triage"]
    assert add.call_count == 0


def test_add_labels_all_new(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/issues/42/labels").mock(
            return_value=_label_response()
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/issues/42/labels").mock(
            return_value=_label_response("bug", "needs-triage")
        )

        result = add_labels(client, _spec(), proposal_id="proposal_abc")

    assert sorted(result.labels_added) == ["bug", "needs-triage"]
    assert result.labels_already_present == []


# ---------------------------------------------------------------------------
# Rollback — remove only the diff, idempotent on 404 per label
# ---------------------------------------------------------------------------


def _result(labels_added: list[str] | None = None) -> AddLabelsResult:
    return AddLabelsResult(
        owner="jaydenpiao",
        repo="quorum",
        issue_number=42,
        labels_added=labels_added if labels_added is not None else ["bug", "blocker"],
    )


def test_rollback_removes_only_labels_added(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        r_bug = mock.delete(
            "https://api.github.com/repos/jaydenpiao/quorum/issues/42/labels/bug"
        ).mock(return_value=httpx.Response(200, json=[]))
        r_blocker = mock.delete(
            "https://api.github.com/repos/jaydenpiao/quorum/issues/42/labels/blocker"
        ).mock(return_value=httpx.Response(200, json=[]))

        summary = rollback_add_labels(client, _result())

    assert sorted(summary["labels_removed"]) == ["blocker", "bug"]
    assert r_bug.call_count == 1
    assert r_blocker.call_count == 1


def test_rollback_idempotent_on_404(client: GitHubAppClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.delete("https://api.github.com/repos/jaydenpiao/quorum/issues/42/labels/bug").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )

        summary = rollback_add_labels(client, _result(labels_added=["bug"]))

    assert summary["labels_removed"] == ["bug"]


def test_rollback_empty_when_nothing_was_added(client: GitHubAppClient) -> None:
    """If labels_added is empty, rollback is a no-op with no HTTP."""
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        delete = mock.delete("https://api.github.com/repos/jaydenpiao/quorum/issues/42/labels/")

        summary = rollback_add_labels(client, _result(labels_added=[]))

    assert summary["labels_removed"] == []
    assert delete.call_count == 0


def test_rollback_impossible_when_install_missing(
    private_pem: str, http_client: httpx.Client
) -> None:
    empty_cfg = GitHubAppConfig(app_id=42, installations=[], limits=GitHubAppLimits())
    client = GitHubAppClient(empty_cfg, private_key_pem=private_pem, http_client=http_client)
    with pytest.raises(RollbackImpossibleError):
        rollback_add_labels(client, _result())
