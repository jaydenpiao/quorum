"""Bootstrap a GitHub App registration for the Quorum actuator.

The GitHub App manifest flow still requires the owning GitHub account to
approve app creation in a browser. This helper handles the rest:

1. Serves a local auto-submit manifest form.
2. Captures GitHub's one-time callback code.
3. Exchanges the code for App metadata + the one-time PEM private key.
4. Stores a base64-encoded PEM in macOS Keychain without printing it.
5. Opens the installation URL and polls for the target repository install.

Usage:

    uv run python -m apps.api.app.tools.bootstrap_github_app \
        --owner jaydenpiao \
        --repo quorum-actuator-fixtures
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import queue
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Mapping
from getpass import getuser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from apps.api.app.services.actuators.github.auth import AppJWTSigner

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765
_DEFAULT_APP_NAME = "Quorum Actuator"
_DEFAULT_HOMEPAGE_URL = "https://github.com/jaydenpiao/quorum"
_DEFAULT_KEYCHAIN_SERVICE = "quorum-github-app-private-key-b64"
_FLY_SECRET_NAME = "QUORUM_GITHUB_APP_PRIVATE_KEY_B64"
_GITHUB_NEW_APP_URL = "https://github.com/settings/apps/new"
_GITHUB_API_URL = "https://api.github.com"


def build_manifest(
    *,
    app_name: str,
    homepage_url: str,
    redirect_url: str,
    description: str,
) -> dict[str, Any]:
    """Return the manifest GitHub will use to register the actuator App."""
    return {
        "name": app_name,
        "url": homepage_url,
        "description": description,
        "public": False,
        "redirect_url": redirect_url,
        "callback_urls": [redirect_url],
        "hook_attributes": {
            # Quorum v1 is pull-only; no inbound webhook endpoint is exposed.
            "active": False,
            "url": "https://example.invalid/quorum-disabled-webhook",
        },
        "default_events": [],
        "default_permissions": {
            "actions": "read",
            "checks": "read",
            "contents": "write",
            "issues": "write",
            "metadata": "read",
            "pull_requests": "write",
        },
    }


def install_url(app_slug: str) -> str:
    return f"https://github.com/apps/{urllib.parse.quote(app_slug)}/installations/new"


def build_registration_form(
    *,
    manifest: Mapping[str, Any],
    state: str,
    github_new_app_url: str = _GITHUB_NEW_APP_URL,
) -> str:
    """Return an HTML form that POSTs the manifest to GitHub.

    GitHub requires a POST to start the manifest flow, so a plain link is
    insufficient. The form auto-submits but also includes a manual button
    for browsers that block script execution.
    """
    manifest_json = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    escaped_manifest = html.escape(manifest_json, quote=True)
    escaped_state = html.escape(state, quote=True)
    escaped_action = html.escape(github_new_app_url, quote=True)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Register Quorum GitHub App</title>
  </head>
  <body>
    <form method="post" action="{escaped_action}">
      <input type="hidden" name="manifest" value="{escaped_manifest}">
      <input type="hidden" name="state" value="{escaped_state}">
      <button type="submit">Register Quorum GitHub App</button>
    </form>
    <script>document.forms[0].submit()</script>
  </body>
</html>
"""


def redacted_summary(
    *,
    conversion: Mapping[str, Any],
    owner: str,
    repo: str,
    keychain_service: str,
    installation_id: int | None,
) -> dict[str, Any]:
    """Return operator-safe metadata. Never include the manifest PEM."""
    app_id = conversion.get("id")
    app_slug = conversion.get("slug")
    settings_url = conversion.get("html_url")
    if not isinstance(app_id, int):
        raise ValueError("manifest conversion response missing integer 'id'")
    if not isinstance(app_slug, str) or not app_slug:
        raise ValueError("manifest conversion response missing non-empty 'slug'")
    if not isinstance(settings_url, str) or not settings_url:
        raise ValueError("manifest conversion response missing non-empty 'html_url'")

    return {
        "app_id": app_id,
        "app_slug": app_slug,
        "app_settings_url": settings_url,
        "install_url": install_url(app_slug),
        "target_repository": f"{owner}/{repo}",
        "installation_id": installation_id,
        "keychain_service": keychain_service,
        "fly_secret_name": _FLY_SECRET_NAME,
    }


def encode_private_key_for_secret(pem: str) -> str:
    """Return a single-line representation suitable for Keychain/Fly."""
    return base64.b64encode(pem.encode("utf-8")).decode("ascii")


def exchange_manifest_code(code: str, *, api_url: str = _GITHUB_API_URL) -> dict[str, Any]:
    url = f"{api_url.rstrip('/')}/app-manifests/{urllib.parse.quote(code)}/conversions"
    req = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return cast(dict[str, Any], json.loads(resp.read().decode("utf-8")))


def store_private_key_in_keychain(
    *,
    service: str,
    pem: str,
    account: str | None = None,
) -> None:
    """Store the base64-encoded PEM in macOS Keychain.

    Base64 keeps the value single-line so `security find-generic-password -w`
    returns exactly what Fly should receive in
    `QUORUM_GITHUB_APP_PRIVATE_KEY_B64`.
    """
    encoded = encode_private_key_for_secret(pem)
    subprocess.run(
        [
            "security",
            "add-generic-password",
            "-a",
            account or getuser(),
            "-s",
            service,
            "-w",
            encoded,
            "-U",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def repository_installation_id(
    *,
    app_id: int,
    private_key_pem: str,
    owner: str,
    repo: str,
    api_url: str = _GITHUB_API_URL,
) -> int | None:
    signer = AppJWTSigner(app_id, private_key_pem=private_key_pem)
    token = signer.mint_jwt()
    url = f"{api_url.rstrip('/')}/repos/{owner}/{repo}/installation"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = cast(dict[str, Any], json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise

    value = payload.get("id")
    if not isinstance(value, int):
        raise ValueError("repository installation response missing integer 'id'")
    return value


class _CallbackServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        manifest: Mapping[str, Any],
        state: str,
        github_new_app_url: str,
        result_queue: queue.Queue[tuple[str, str]],
    ) -> None:
        super().__init__(server_address, handler)
        self.manifest = manifest
        self.state = state
        self.github_new_app_url = github_new_app_url
        self.result_queue = result_queue


class _Handler(BaseHTTPRequestHandler):
    server: _CallbackServer

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/register":
            self._send_html(
                build_registration_form(
                    manifest=self.server.manifest,
                    state=self.server.state,
                    github_new_app_url=self.server.github_new_app_url,
                )
            )
            return

        if parsed.path == "/callback":
            params = urllib.parse.parse_qs(parsed.query)
            code = _single(params, "code")
            state = _single(params, "state")
            if state != self.server.state:
                self._send_html("State mismatch; close this tab and retry.", status=400)
                return
            if code is None:
                self._send_html("Missing code; close this tab and retry.", status=400)
                return
            self.server.result_queue.put((code, state))
            self._send_html("GitHub App manifest captured. You can close this tab.")
            return

        self._send_html("Not found", status=404)

    def _send_html(self, body: str, *, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _single(params: Mapping[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    return values[0]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bootstrap_github_app")
    parser.add_argument("--owner", default="jaydenpiao", help="target repo owner")
    parser.add_argument(
        "--repo",
        default="quorum-actuator-fixtures",
        help="target repo to install the app on",
    )
    parser.add_argument("--app-name", default=_DEFAULT_APP_NAME)
    parser.add_argument("--homepage-url", default=_DEFAULT_HOMEPAGE_URL)
    parser.add_argument(
        "--description",
        default="GitHub App used by Quorum's audited GitHub actuator.",
    )
    parser.add_argument("--host", default=_DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT)
    parser.add_argument("--keychain-service", default=_DEFAULT_KEYCHAIN_SERVICE)
    parser.add_argument("--github-new-app-url", default=_GITHUB_NEW_APP_URL)
    parser.add_argument("--github-api-url", default=_GITHUB_API_URL)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--install-timeout-seconds", type=float, default=600.0)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--no-open", action="store_true", help="print URLs without opening browser")
    parser.add_argument("--output", choices=["text", "json"], default="text")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    result_queue: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=1)
    state = secrets.token_urlsafe(24)
    redirect_url = f"http://{args.host}:{args.port}/callback"
    manifest = build_manifest(
        app_name=args.app_name,
        homepage_url=args.homepage_url,
        redirect_url=redirect_url,
        description=args.description,
    )
    server = _CallbackServer(
        (args.host, args.port),
        _Handler,
        manifest=manifest,
        state=state,
        github_new_app_url=args.github_new_app_url,
        result_queue=result_queue,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    register_url = f"http://{args.host}:{server.server_port}/register"

    if not args.no_open:
        webbrowser.open(register_url)

    _print(args, f"Open this URL to register the GitHub App: {register_url}")
    _print(args, "Approve the App creation in GitHub; this process is waiting for the callback.")

    try:
        code, _ = result_queue.get(timeout=args.timeout_seconds)
    except queue.Empty:
        server.shutdown()
        print("error: timed out waiting for GitHub manifest callback", file=sys.stderr)
        return 2
    finally:
        server.shutdown()

    conversion = exchange_manifest_code(code, api_url=args.github_api_url)
    pem = conversion.get("pem")
    if not isinstance(pem, str) or not pem:
        print("error: manifest conversion response did not include a PEM", file=sys.stderr)
        return 1
    store_private_key_in_keychain(service=args.keychain_service, pem=pem)

    app_id = conversion.get("id")
    app_slug = conversion.get("slug")
    if not isinstance(app_id, int) or not isinstance(app_slug, str):
        print("error: manifest conversion response missing app id or slug", file=sys.stderr)
        return 1

    target_install_url = install_url(app_slug)
    if not args.no_open:
        webbrowser.open(target_install_url)
    _print(args, f"Install the App on {args.owner}/{args.repo}: {target_install_url}")

    installation_id = _wait_for_installation(
        app_id=app_id,
        private_key_pem=pem,
        owner=args.owner,
        repo=args.repo,
        api_url=args.github_api_url,
        timeout_seconds=args.install_timeout_seconds,
        poll_seconds=args.poll_seconds,
    )

    summary = redacted_summary(
        conversion=conversion,
        owner=args.owner,
        repo=args.repo,
        keychain_service=args.keychain_service,
        installation_id=installation_id,
    )
    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print("GitHub App bootstrap summary:")
        for key, value in summary.items():
            print(f"  {key}: {value}")
    return 0 if installation_id is not None else 3


def _wait_for_installation(
    *,
    app_id: int,
    private_key_pem: str,
    owner: str,
    repo: str,
    api_url: str,
    timeout_seconds: float,
    poll_seconds: float,
) -> int | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        installation_id = repository_installation_id(
            app_id=app_id,
            private_key_pem=private_key_pem,
            owner=owner,
            repo=repo,
            api_url=api_url,
        )
        if installation_id is not None:
            return installation_id
        time.sleep(poll_seconds)
    return None


def _print(args: argparse.Namespace, message: str) -> None:
    if args.output == "text":
        print(message)
    else:
        print(message, file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
