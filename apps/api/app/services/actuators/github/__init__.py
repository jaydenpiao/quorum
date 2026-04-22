"""GitHub App actuator.

Layers of scope:

- **PR A** — auth scaffold: App JWT signing, installation-token cache,
  single-retry-on-401 wrapper, config loader.
- **PR B1** — the first action: ``github.open_pr``. Typed spec
  (``GitHubOpenPrSpec``) + result (``OpenPrResult``), Git Data REST
  methods, ``open_pr`` orchestration.
- **PR B2** — executor dispatch on ``action_type``.
- **PR C** (this PR) — ``rollback_open_pr`` + ``RollbackImpossibleError``,
  plus the ``rollback_impossible`` event type in the domain layer.
"""

from apps.api.app.services.actuators.github.actions import (
    GitHubActionError,
    RollbackImpossibleError,
    open_pr,
    rollback_open_pr,
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
    "RollbackImpossibleError",
    "derive_head_branch",
    "load_github_config",
    "open_pr",
    "rollback_open_pr",
]
