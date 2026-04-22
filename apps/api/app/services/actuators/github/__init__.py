"""GitHub App actuator.

Layers of scope:

- **PR A** — auth scaffold: App JWT signing, installation-token cache,
  single-retry-on-401 wrapper, config loader.
- **PR B1** — the first action: ``github.open_pr``. Typed spec + result,
  Git Data REST methods, ``open_pr`` orchestration.
- **PR B2** — executor dispatch on ``action_type``.
- **PR C** — ``rollback_open_pr`` + ``RollbackImpossibleError``, plus
  the ``rollback_impossible`` event type in the domain layer.
- **PR D** (this PR) — three more actions to round out the v1 taxonomy:
  ``comment_issue``, ``close_pr``, ``add_labels``. Each ships with its
  typed spec, typed result, orchestration function, idempotent rollback
  function, and new client REST methods.
"""

from apps.api.app.services.actuators.github.actions import (
    GitHubActionError,
    RollbackImpossibleError,
    add_labels,
    close_pr,
    comment_issue,
    open_pr,
    rollback_add_labels,
    rollback_close_pr,
    rollback_comment_issue,
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
    AddLabelsResult,
    ClosePrResult,
    CommentIssueResult,
    GitHubAddLabelsSpec,
    GitHubAppConfig,
    GitHubAppLimits,
    GitHubClosePrSpec,
    GitHubCommentIssueSpec,
    GitHubFileSpec,
    GitHubInstallation,
    GitHubOpenPrSpec,
    OpenPrResult,
    derive_head_branch,
    load_github_config,
)

__all__ = [
    "AddLabelsResult",
    "AppJWTSigner",
    "CachedToken",
    "ClosePrResult",
    "CommentIssueResult",
    "GitHubActionError",
    "GitHubAddLabelsSpec",
    "GitHubApiError",
    "GitHubAppAuthError",
    "GitHubAppClient",
    "GitHubAppConfig",
    "GitHubAppLimits",
    "GitHubClosePrSpec",
    "GitHubCommentIssueSpec",
    "GitHubFileSpec",
    "GitHubInstallation",
    "GitHubOpenPrSpec",
    "InstallationTokenCache",
    "OpenPrResult",
    "RollbackImpossibleError",
    "add_labels",
    "close_pr",
    "comment_issue",
    "derive_head_branch",
    "load_github_config",
    "open_pr",
    "rollback_add_labels",
    "rollback_close_pr",
    "rollback_comment_issue",
    "rollback_open_pr",
]
