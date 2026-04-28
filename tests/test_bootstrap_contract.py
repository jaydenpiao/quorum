"""Static checks for local bootstrap and validation commands."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"
PYPROJECT = ROOT / "pyproject.toml"
VALIDATE_SCRIPT = ROOT / "scripts" / "validate_merge.sh"
PREFLIGHT_SCRIPT = ROOT / "scripts" / "check_python_runtime.py"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


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
    assert "UV_RUN := $(UV) run --frozen --extra dev --python $(PYTHON_VERSION)" in text
    assert "$(UV) python install $(PYTHON_VERSION)" in text
    assert "$(UV_RUN) python scripts/check_python_runtime.py" in text
    assert "$(UV_RUN) pytest --cov-fail-under=60 -q" in text
    assert "$(PYTEST) -q" not in text


def test_validate_merge_script_runs_uv_preflight_and_checks() -> None:
    text = _text(VALIDATE_SCRIPT)

    assert "uv run --frozen --extra dev --python 3.12 --python-preference only-managed" in text
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
