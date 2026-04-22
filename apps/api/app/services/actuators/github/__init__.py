"""GitHub App actuator (Phase 4 PR A — auth scaffold).

This PR lands the auth plumbing only: App JWT signer, installation-token
cache with TTL + on-demand refresh, config loader. No ``action_type``
dispatch, no executor wiring — those land in PR B.

Public re-exports below are what PR B will import.
"""

from apps.api.app.services.actuators.github.auth import (
    AppJWTSigner,
    CachedToken,
    GitHubAppAuthError,
    InstallationTokenCache,
)
from apps.api.app.services.actuators.github.client import GitHubAppClient
from apps.api.app.services.actuators.github.specs import (
    GitHubAppConfig,
    GitHubAppLimits,
    GitHubInstallation,
    load_github_config,
)

__all__ = [
    "AppJWTSigner",
    "CachedToken",
    "GitHubAppAuthError",
    "GitHubAppClient",
    "GitHubAppConfig",
    "GitHubAppLimits",
    "GitHubInstallation",
    "InstallationTokenCache",
    "load_github_config",
]
