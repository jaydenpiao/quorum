"""Tests for ``HealthCheckKind.github_check_run`` (Phase 4 PR E).

The runner polls GitHub's check-runs API until every run is terminal,
or the wall-clock timeout expires. Tests fast-forward by injecting a
no-op ``sleep_fn`` so no real sleeping happens.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from apps.api.app.domain.models import HealthCheckKind, HealthCheckSpec
from apps.api.app.services.actuators.github import (
    GitHubAppClient,
    GitHubAppConfig,
    GitHubAppLimits,
    GitHubInstallation,
)
from apps.api.app.services.health_checks import HealthCheckRunner

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
def gh_client(private_pem: str, http_client: httpx.Client) -> GitHubAppClient:
    return GitHubAppClient(_config(), private_key_pem=private_pem, http_client=http_client)


@pytest.fixture
def runner(gh_client: GitHubAppClient) -> HealthCheckRunner:
    # Injected sleep is a no-op so tests don't actually sleep between polls.
    return HealthCheckRunner(github_client=gh_client, sleep_fn=lambda _: None)


def _spec(**overrides: object) -> HealthCheckSpec:
    defaults: dict[str, object] = {
        "name": "ci",
        "kind": HealthCheckKind.github_check_run,
        "github_owner": "jaydenpiao",
        "github_repo": "quorum",
        "github_commit_sha": "commit_sha_abc",
        "timeout_seconds": 15.0,
        "poll_interval_seconds": 0.5,
    }
    defaults.update(overrides)
    return HealthCheckSpec.model_validate(defaults)


def _token(mock: respx.MockRouter) -> None:
    mock.post("https://api.github.com/app/installations/7/access_tokens").mock(
        return_value=httpx.Response(
            200, json={"token": "ghs_t", "expires_at": "2099-01-01T00:00:00Z"}
        )
    )


def _runs_response(runs: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(200, json={"total_count": len(runs), "check_runs": runs})


# ---------------------------------------------------------------------------
# Spec boundary
# ---------------------------------------------------------------------------


def test_spec_rejects_missing_owner_repo() -> None:
    with pytest.raises(ValidationError):
        HealthCheckSpec.model_validate(
            {"name": "ci", "kind": "github_check_run", "timeout_seconds": 30.0}
        )


def test_spec_rejects_too_short_timeout() -> None:
    with pytest.raises(ValidationError):
        HealthCheckSpec.model_validate(
            {
                "name": "ci",
                "kind": "github_check_run",
                "github_owner": "o",
                "github_repo": "r",
                "timeout_seconds": 1.0,
            }
        )


def test_spec_allows_missing_commit_sha() -> None:
    """commit_sha can be injected via context at runtime, so it's not
    required on the spec."""
    spec = HealthCheckSpec.model_validate(
        {
            "name": "ci",
            "kind": "github_check_run",
            "github_owner": "o",
            "github_repo": "r",
            "timeout_seconds": 30.0,
        }
    )
    assert spec.github_commit_sha is None


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_all_runs_success_on_first_poll(runner: HealthCheckRunner) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get(
            "https://api.github.com/repos/jaydenpiao/quorum/commits/commit_sha_abc/check-runs"
        ).mock(
            return_value=_runs_response(
                [
                    {"name": "ci", "status": "completed", "conclusion": "success"},
                    {"name": "lint", "status": "completed", "conclusion": "success"},
                ]
            )
        )

        result = runner.run(_spec())

    assert result.passed is True
    assert "all passed" in result.detail


def test_neutral_and_skipped_count_as_passing(runner: HealthCheckRunner) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get(
            "https://api.github.com/repos/jaydenpiao/quorum/commits/commit_sha_abc/check-runs"
        ).mock(
            return_value=_runs_response(
                [
                    {"name": "ci", "status": "completed", "conclusion": "success"},
                    {"name": "flaky", "status": "completed", "conclusion": "neutral"},
                    {"name": "coverage", "status": "completed", "conclusion": "skipped"},
                ]
            )
        )

        result = runner.run(_spec())

    assert result.passed is True


# ---------------------------------------------------------------------------
# Polling: pending then terminal
# ---------------------------------------------------------------------------


def test_pending_then_success(runner: HealthCheckRunner) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get(
            "https://api.github.com/repos/jaydenpiao/quorum/commits/commit_sha_abc/check-runs"
        ).mock(
            side_effect=[
                _runs_response([{"name": "ci", "status": "in_progress", "conclusion": None}]),
                _runs_response([{"name": "ci", "status": "completed", "conclusion": "success"}]),
            ]
        )

        result = runner.run(_spec())

    assert result.passed is True


def test_pending_then_failure(runner: HealthCheckRunner) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get(
            "https://api.github.com/repos/jaydenpiao/quorum/commits/commit_sha_abc/check-runs"
        ).mock(
            side_effect=[
                _runs_response([{"name": "ci", "status": "queued", "conclusion": None}]),
                _runs_response([{"name": "ci", "status": "completed", "conclusion": "failure"}]),
            ]
        )

        result = runner.run(_spec())

    assert result.passed is False
    assert "conclusion='failure'" in result.detail


def test_empty_then_success(runner: HealthCheckRunner) -> None:
    """CI may not have registered check runs yet on the first poll."""
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get(
            "https://api.github.com/repos/jaydenpiao/quorum/commits/commit_sha_abc/check-runs"
        ).mock(
            side_effect=[
                _runs_response([]),
                _runs_response([]),
                _runs_response([{"name": "ci", "status": "completed", "conclusion": "success"}]),
            ]
        )

        result = runner.run(_spec())

    assert result.passed is True


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_timeout_with_no_runs_ever(
    gh_client: GitHubAppClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wall-clock expires, no check runs ever observed → fail with clear message."""
    runner = HealthCheckRunner(github_client=gh_client, sleep_fn=lambda _: None)

    # Fast-forward time so the first poll is already past the deadline.
    import apps.api.app.services.health_checks as hc_module

    times = iter([1000.0, 1100.0, 1200.0, 1300.0])
    monkeypatch.setattr(hc_module.time, "monotonic", lambda: next(times))

    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get(
            "https://api.github.com/repos/jaydenpiao/quorum/commits/commit_sha_abc/check-runs"
        ).mock(return_value=_runs_response([]))

        result = runner.run(_spec(timeout_seconds=15.0))

    assert result.passed is False
    assert "no check runs observed" in result.detail


def test_timeout_with_pending_runs(
    gh_client: GitHubAppClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = HealthCheckRunner(github_client=gh_client, sleep_fn=lambda _: None)

    import apps.api.app.services.health_checks as hc_module

    times = iter([1000.0, 1100.0, 1200.0, 1300.0])
    monkeypatch.setattr(hc_module.time, "monotonic", lambda: next(times))

    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get(
            "https://api.github.com/repos/jaydenpiao/quorum/commits/commit_sha_abc/check-runs"
        ).mock(
            return_value=_runs_response(
                [{"name": "ci", "status": "in_progress", "conclusion": None}]
            )
        )

        result = runner.run(_spec(timeout_seconds=15.0))

    assert result.passed is False
    assert "timeout" in result.detail
    assert "waiting on 'ci'" in result.detail


# ---------------------------------------------------------------------------
# Context-driven head_sha fallback
# ---------------------------------------------------------------------------


def test_commit_sha_from_context(runner: HealthCheckRunner) -> None:
    """When the spec omits github_commit_sha, the runner pulls it from context."""
    spec = _spec(github_commit_sha=None)
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get(
            "https://api.github.com/repos/jaydenpiao/quorum/commits/from_context_sha/check-runs"
        ).mock(
            return_value=_runs_response(
                [{"name": "ci", "status": "completed", "conclusion": "success"}]
            )
        )

        result = runner.run(spec, context={"head_sha": "from_context_sha"})

    assert result.passed is True


def test_missing_commit_sha_fails_fast(runner: HealthCheckRunner) -> None:
    """No commit_sha on spec, no head_sha in context → fail with actionable detail."""
    result = runner.run(_spec(github_commit_sha=None), context={})
    assert result.passed is False
    assert "no commit_sha" in result.detail


# ---------------------------------------------------------------------------
# Configuration edges
# ---------------------------------------------------------------------------


def test_no_github_client_fails(private_pem: str) -> None:
    # Runner constructed with no client.
    runner = HealthCheckRunner()
    result = runner.run(_spec())
    assert result.passed is False
    assert "requires a configured GitHub App client" in result.detail


def test_missing_installation_fails(private_pem: str, http_client: httpx.Client) -> None:
    empty_cfg = GitHubAppConfig(app_id=42, installations=[], limits=GitHubAppLimits())
    client = GitHubAppClient(empty_cfg, private_key_pem=private_pem, http_client=http_client)
    runner = HealthCheckRunner(github_client=client, sleep_fn=lambda _: None)
    result = runner.run(_spec())
    assert result.passed is False
    assert "no installation configured" in result.detail


# ---------------------------------------------------------------------------
# check_name filter
# ---------------------------------------------------------------------------


def test_check_name_filter_ignores_unrelated_runs(runner: HealthCheckRunner) -> None:
    """Only check runs whose name matches are considered."""
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get(
            "https://api.github.com/repos/jaydenpiao/quorum/commits/commit_sha_abc/check-runs"
        ).mock(
            return_value=_runs_response(
                [
                    {"name": "ci", "status": "completed", "conclusion": "success"},
                    # A failing check in a different workflow — filter ignores it.
                    {"name": "nightly", "status": "completed", "conclusion": "failure"},
                ]
            )
        )

        result = runner.run(_spec(github_check_name="ci"))

    assert result.passed is True


def test_api_error_surfaces_as_failure(runner: HealthCheckRunner) -> None:
    with respx.mock(assert_all_called=False) as mock:
        _token(mock)
        mock.get(
            "https://api.github.com/repos/jaydenpiao/quorum/commits/commit_sha_abc/check-runs"
        ).mock(return_value=httpx.Response(500, json={"message": "server error"}))

        result = runner.run(_spec())

    assert result.passed is False
    assert "500" in result.detail
