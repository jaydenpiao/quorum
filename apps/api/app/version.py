"""Canonical Quorum version."""

from __future__ import annotations

import re

__version__ = "0.6.6"

_ALPHA_VERSION_RE = re.compile(r"^(\d+\.\d+\.\d+)a(\d+)$")


def _format_display_version(version: str) -> str:
    alpha_match = _ALPHA_VERSION_RE.fullmatch(version)
    if alpha_match is not None:
        return f"v{alpha_match.group(1)}-alpha.{alpha_match.group(2)}"
    return f"v{version}"


display_version = _format_display_version(__version__)
