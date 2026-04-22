"""GitHub App actuator.

Two layers of scope so far:

- **PR A** — auth scaffold: App JWT signing, installation-token cache,
  single-retry-on-401 wrapper, config loader.
- **PR B1** (this PR) — the first action: ``github.open_pr``. Adds the
  typed spec (``GitHubOpenPrSpec``) + result (``OpenPrResult``), the Git
  Data REST methods on ``GitHubAppClient``, and the ``open_pr``
  orchestration function in ``actions``. Not yet wired into the
  executor — PR B2 dispatches on ``action_type``.
"""

from apps.api.app.services.actuators.github.actions import (
    GitHubActionError,
    open_pr,
)
from apps.api.app.services.actuators.github.auth import (
    AppJWTSigner,
    CachedToken,
    GitHubAppAuthError,
    InstallationTokenCache,
)
from apps.api.app.services.actuators.github.client import (
    GitHubApiError,
    GitHubAppClient,
)
from apps.api.app.services.actuators.github.specs import (
    GitHubAppConfig,
    GitHubAppLimits,
    GitHubFileSpec,
    GitHubInstallation,
    GitHubOpenPrSpec,
    OpenPrResult,
    derive_head_branch,
    load_github_config,
)

__all__ = [
    "AppJWTSigner",
    "CachedToken",
    "GitHubActionError",
    "GitHubApiError",
    "GitHubAppAuthError",
    "GitHubAppClient",
    "GitHubAppConfig",
    "GitHubAppLimits",
    "GitHubFileSpec",
    "GitHubInstallation",
    "GitHubOpenPrSpec",
    "InstallationTokenCache",
    "OpenPrResult",
    "derive_head_branch",
    "load_github_config",
    "open_pr",
]
