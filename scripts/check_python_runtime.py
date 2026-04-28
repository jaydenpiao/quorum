"""Preflight checks for the local Python runtime used by repo commands.

This catches interpreter/bootstrap problems early, before developers hit
opaque pytest or readline crashes during normal validation.
"""

from __future__ import annotations

import shlex
import subprocess
import sys


def _format_command(args: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in args)


def _probe_readline() -> None:
    command = [sys.executable, "-c", "import readline; print(readline.__name__)"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return

    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    detail = stderr or stdout or f"exit code {result.returncode}"
    hint = ""
    if result.returncode in {-11, 139}:
        hint = (
            "The interpreter segfaulted while importing readline. "
            "This repo should be run with the uv-managed Python 3.12 environment, "
            "not an ambient Anaconda-derived venv."
        )

    lines = [
        "Python runtime preflight failed.",
        f"Interpreter: {sys.executable}",
        f"Probe: {_format_command(command)}",
        f"Failure: {detail}",
    ]
    if hint:
        lines.append(hint)
    lines.append("Run `make install` to rebuild `.venv` with uv-managed Python 3.12.")
    raise SystemExit("\n".join(lines))


def main() -> None:
    _probe_readline()
    print(f"python-runtime-ok: {sys.version.splitlines()[0]}")


if __name__ == "__main__":
    main()
