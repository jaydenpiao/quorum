from __future__ import annotations

import base64
import html

from apps.api.app.tools.bootstrap_github_app import (
    build_manifest,
    build_registration_form,
    encode_private_key_for_secret,
    install_url,
    redacted_summary,
)

_PEM_BEGIN = "-----BEGIN " + "RSA PRIVATE KEY-----"
_PEM_END = "-----END " + "RSA PRIVATE KEY-----"


def test_build_manifest_matches_quorum_actuator_permissions() -> None:
    manifest = build_manifest(
        app_name="Quorum Actuator Test",
        homepage_url="https://github.com/jaydenpiao/quorum",
        redirect_url="http://127.0.0.1:8765/callback",
        description="Safe test app",
    )

    assert manifest["name"] == "Quorum Actuator Test"
    assert manifest["url"] == "https://github.com/jaydenpiao/quorum"
    assert manifest["redirect_url"] == "http://127.0.0.1:8765/callback"
    assert manifest["public"] is False
    assert manifest["default_events"] == []
    assert manifest["hook_attributes"] == {
        "active": False,
        "url": "https://example.invalid/quorum-disabled-webhook",
    }
    assert manifest["default_permissions"] == {
        "actions": "read",
        "checks": "read",
        "contents": "write",
        "issues": "write",
        "metadata": "read",
        "pull_requests": "write",
    }


def test_registration_form_posts_manifest_and_state_to_github() -> None:
    manifest = build_manifest(
        app_name="Quorum <Actuator>",
        homepage_url="https://github.com/jaydenpiao/quorum",
        redirect_url="http://127.0.0.1:8765/callback",
        description="Safe test app",
    )

    form = build_registration_form(
        manifest=manifest,
        state="state-value",
        github_new_app_url="https://github.com/settings/apps/new",
    )

    assert 'method="post"' in form
    assert 'action="https://github.com/settings/apps/new"' in form
    assert 'name="state"' in form
    assert 'value="state-value"' in form
    assert 'name="manifest"' in form
    assert html.escape("Quorum <Actuator>", quote=True) in form
    assert "document.forms[0].submit()" in form


def test_redacted_summary_never_includes_private_key_material() -> None:
    summary = redacted_summary(
        conversion={
            "id": 12345,
            "slug": "quorum-actuator-test",
            "html_url": "https://github.com/settings/apps/quorum-actuator-test",
            "pem": f"{_PEM_BEGIN}\nsuper-secret-body\n{_PEM_END}",
        },
        owner="jaydenpiao",
        repo="quorum-actuator-fixtures",
        keychain_service="quorum-github-app-private-key-b64",
        installation_id=67890,
    )

    rendered = str(summary)
    assert "super-secret-body" not in rendered
    assert "PRIVATE KEY" not in rendered
    assert summary == {
        "app_id": 12345,
        "app_slug": "quorum-actuator-test",
        "app_settings_url": "https://github.com/settings/apps/quorum-actuator-test",
        "install_url": "https://github.com/apps/quorum-actuator-test/installations/new",
        "target_repository": "jaydenpiao/quorum-actuator-fixtures",
        "installation_id": 67890,
        "keychain_service": "quorum-github-app-private-key-b64",
        "fly_secret_name": "QUORUM_GITHUB_APP_PRIVATE_KEY_B64",
    }


def test_install_url_uses_app_slug() -> None:
    assert (
        install_url("quorum-actuator-test")
        == "https://github.com/apps/quorum-actuator-test/installations/new"
    )


def test_encode_private_key_for_secret_is_single_line_base64() -> None:
    pem = f"{_PEM_BEGIN}\nsecret\n{_PEM_END}\n"

    encoded = encode_private_key_for_secret(pem)

    assert "\n" not in encoded
    assert base64.b64decode(encoded).decode("utf-8") == pem
