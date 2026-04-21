"""Tests for the typed HealthCheckRunner.

Phase 2: HealthCheckKind.shell is removed entirely. All probes must be one of
the registered, typed kinds (always_pass, always_fail, http). Proposals that
specify an unknown kind are rejected at the pydantic boundary. There is no
subprocess path.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.api.app.domain.models import HealthCheckKind, HealthCheckSpec
from apps.api.app.services.health_checks import HealthCheckRunner


def test_always_pass() -> None:
    result = HealthCheckRunner().run(HealthCheckSpec(name="t", kind=HealthCheckKind.always_pass))
    assert result.passed is True
    assert result.name == "t"


def test_always_fail() -> None:
    result = HealthCheckRunner().run(HealthCheckSpec(name="t", kind=HealthCheckKind.always_fail))
    assert result.passed is False


def test_http_probe_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP probe returns passed=True when the URL returns the expected status."""

    class StubResponse:
        status_code = 200

    class StubClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> "StubClient":
            return self

        def __exit__(self, *args) -> None:
            return None

        def request(self, method: str, url: str, timeout: float = 5.0):
            assert method == "GET"
            assert url == "https://example.invalid/health"
            return StubResponse()

    import apps.api.app.services.health_checks as hc_module

    monkeypatch.setattr(hc_module.httpx, "Client", StubClient)

    spec = HealthCheckSpec(
        name="ok",
        kind=HealthCheckKind.http,
        url="https://example.invalid/health",
        expected_status=200,
    )
    result = HealthCheckRunner().run(spec)
    assert result.passed is True
    assert "200" in result.detail


def test_http_probe_status_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    class StubResponse:
        status_code = 500

    class StubClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> "StubClient":
            return self

        def __exit__(self, *args) -> None:
            return None

        def request(self, method: str, url: str, timeout: float = 5.0):
            return StubResponse()

    import apps.api.app.services.health_checks as hc_module

    monkeypatch.setattr(hc_module.httpx, "Client", StubClient)

    spec = HealthCheckSpec(
        name="bad",
        kind=HealthCheckKind.http,
        url="https://example.invalid/health",
        expected_status=200,
    )
    result = HealthCheckRunner().run(spec)
    assert result.passed is False


def test_http_requires_url() -> None:
    """An http probe without a URL is a validation error at boundary time."""
    with pytest.raises(ValidationError):
        HealthCheckSpec(name="x", kind=HealthCheckKind.http)


def test_http_rejects_non_http_url() -> None:
    """Only http and https schemes are accepted. file://, gopher://, etc. rejected."""
    for bad in [
        "file:///etc/passwd",
        "ftp://example.com/",
        "gopher://example.com/",
        "javascript:alert(1)",
        "data:text/html,<h1>x</h1>",
    ]:
        with pytest.raises(ValidationError):
            HealthCheckSpec(name="x", kind=HealthCheckKind.http, url=bad)


def test_shell_kind_rejected_at_boundary() -> None:
    """Phase 2 removes HealthCheckKind.shell entirely. Constructing one fails."""
    with pytest.raises(ValidationError):
        HealthCheckSpec(name="x", kind="shell")  # type: ignore[arg-type]


def test_http_metacharacter_in_url_rejected() -> None:
    """URLs containing shell meta-characters or injection-style payloads are rejected.

    Even though the runner never shells out, having such URLs in proposals is a
    smell we reject defensively.
    """
    for bad in [
        "https://example.com/;rm -rf /",
        "https://example.com/$(whoami)",
        "https://example.com/`id`",
        "https://example.com/\n/etc/passwd",
    ]:
        with pytest.raises(ValidationError):
            HealthCheckSpec(name="x", kind=HealthCheckKind.http, url=bad)
