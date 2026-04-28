"""Static checks for local bootstrap and validation commands."""

from __future__ import annotations

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"
PYPROJECT = ROOT / "pyproject.toml"
GITLEAKS = ROOT / ".gitleaks.toml"
SECURITY_WORKFLOW = ROOT / ".github" / "workflows" / "security.yml"
VALIDATE_SCRIPT = ROOT / "scripts" / "validate_merge.sh"
PROOF_SCRIPT = ROOT / "scripts" / "prove_llm_prod_deploy.sh"
PREFLIGHT_SCRIPT = ROOT / "scripts" / "check_python_runtime.py"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
DOCKERFILE = ROOT / "Dockerfile"
README = ROOT / "README.md"
PINNED_UV_VERSION = "0.11.8"
GITLEAKS_VERSION = "8.30.1"
GITLEAKS_LINUX_X64_SHA256 = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pyproject_uses_dynamic_version_from_runtime_module() -> None:
    text = _text(PYPROJECT)

    assert 'dynamic = ["version"]' in text
    assert 'version = { attr = "apps.api.app.version.__version__" }' in text
    assert 'version = "0.1.0"' not in text


def test_makefile_uses_uv_managed_bootstrap_and_preflight() -> None:
    text = _text(MAKEFILE)

    assert "UV_SYNC := $(UV) sync --frozen --extra dev --python $(PYTHON_VERSION)" in text
    assert "--reinstall-package quorum" in text
    assert "UV_RUN := $(UV) run --frozen --extra dev --python $(PYTHON_VERSION)" in text
    assert "$(UV) python install $(PYTHON_VERSION)" in text
    assert "$(UV_RUN) python scripts/check_python_runtime.py" in text
    assert "$(UV_RUN) pytest --cov-fail-under=60 -q" in text
    assert "$(PYTEST) -q" not in text


def test_uv_tool_version_is_pinned_across_local_and_ci_bootstrap() -> None:
    pyproject = tomllib.loads(_text(PYPROJECT))
    makefile = _text(MAKEFILE)
    ci_workflow = _text(CI_WORKFLOW)
    release_workflow = _text(RELEASE_WORKFLOW)
    dockerfile = _text(DOCKERFILE)
    readme = _text(README)
    proof_script = _text(PROOF_SCRIPT)
    proof_uv_default = (
        f'UV_VERSION="${{QUORUM_PROOF_UV_VERSION:-${{QUORUM_UV_VERSION:-{PINNED_UV_VERSION}}}}}"'
    )

    assert pyproject["tool"]["uv"]["required-version"] == f"=={PINNED_UV_VERSION}"
    assert f"UV_VERSION := {PINNED_UV_VERSION}" in makefile
    assert "$(UVX) --from uv==$(UV_VERSION) uv" in makefile
    assert f"version: {PINNED_UV_VERSION}" in ci_workflow
    assert f"version: {PINNED_UV_VERSION}" in release_workflow
    assert f"ARG UV_VERSION={PINNED_UV_VERSION}" in dockerfile
    assert f"uvx --from uv=={PINNED_UV_VERSION} uv" in readme
    assert proof_uv_default in proof_script


def test_validate_merge_script_runs_uv_preflight_and_checks() -> None:
    text = _text(VALIDATE_SCRIPT)

    assert 'UV_VERSION="${QUORUM_UV_VERSION:-0.11.8}"' in text
    assert 'UV=("$UVX" --from "uv==${UV_VERSION}" uv)' in text
    assert (
        '"${UV[@]}" sync --frozen --extra dev --python 3.12 --python-preference only-managed'
        in text
    )
    assert "--reinstall-package quorum" in text
    assert (
        '"${UV[@]}" run --frozen --extra dev --python 3.12 --python-preference only-managed' in text
    )
    assert "python scripts/check_python_runtime.py" in text
    assert "pytest --cov-fail-under=60 -q" in text
    assert "python -m pytest -q" not in text


def test_python_runtime_preflight_script_exists_with_readline_probe() -> None:
    text = _text(PREFLIGHT_SCRIPT)

    assert "import readline" in text
    assert "subprocess.run" in text
    assert "segfault" in text.lower()


def test_pip_audit_installs_only_third_party_dependencies() -> None:
    text = _text(CI_WORKFLOW)

    assert "uv sync --frozen --extra dev --no-install-project" in text
    assert 'sysconfig.get_paths()["purelib"]' in text
    assert 'uv run --no-sync pip-audit --strict --path "$SITE_PACKAGES"' in text
    assert "continue-on-error: true" in text


def test_ci_and_release_reinstall_first_party_package_metadata() -> None:
    ci_text = _text(CI_WORKFLOW)
    release_text = _text(RELEASE_WORKFLOW)

    assert "uv sync --frozen --extra dev --reinstall-package quorum" in ci_text
    assert "uv sync --frozen --no-dev --reinstall-package quorum" in release_text


def test_gitleaks_allowlist_is_limited_to_known_demo_placeholder() -> None:
    text = _text(GITLEAKS)

    assert "Known-safe test fixtures and local demo placeholders" in text
    assert "operator-key-dev" in text
    assert "Never add real secrets here" in text


def test_security_workflow_uses_pinned_node_free_gitleaks_cli() -> None:
    text = _text(SECURITY_WORKFLOW)

    assert "gitleaks/gitleaks-action" not in text
    assert f"GITLEAKS_VERSION: {GITLEAKS_VERSION}" in text
    assert f"GITLEAKS_SHA256: {GITLEAKS_LINUX_X64_SHA256}" in text
    assert "gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" in text
    assert "sha256sum -c -" in text
    assert "gitleaks detect --source . --config .gitleaks.toml --verbose --redact" in text
