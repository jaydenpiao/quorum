"""GitHub actuator action functions.

Each function takes a ``GitHubAppClient`` plus a typed spec and returns a
typed result record. They are pure orchestration — all HTTP lives in
``client.py``, all input validation lives in ``specs.py``. The executor
takes the result record and wraps it in ``execution_started`` /
``execution_succeeded`` / ``execution_failed`` event envelopes per
``AGENTS.md`` logging rules.

Safety posture for ``open_pr``:

- The head branch name is **derived** from ``proposal_id``
  (``quorum/<proposal_id>``). Callers cannot override it, so rollback
  can deterministically find the branch later.
- The base branch must exist, must not be GitHub-flagged ``protected``,
  and must not match any reserved name (enforced statically in the
  spec validator).
- File count + per-file byte cap are enforced at the spec boundary
  (``MAX_FILES_PER_PR`` / ``MAX_FILE_BYTES``) **and** cross-checked
  against ``config.limits`` here so operators can tighten — but not
  loosen — the defaults.

Rollback semantics for ``rollback_open_pr``:

- ``get_pull_request`` first — if ``merged=True`` we cannot undo the
  merge; we raise ``RollbackImpossibleError``.
- If the PR is still open, ``close_pull_request``. If already closed,
  skip (idempotent).
- Always attempt ``delete_ref`` for ``heads/<head_branch>``; the client
  swallows 404 / 422 so a re-run is idempotent.

PR D adds three more actions + rollbacks (``comment_issue``, ``close_pr``,
``add_labels``). Each follows the same posture: typed spec, list-then-diff
where rollback needs to know which side-effects *we* introduced, and
idempotent rollback paths so re-runs are safe.
"""

from __future__ import annotations

from typing import Any

from apps.api.app.services.actuators.github.client import GitHubApiError, GitHubAppClient
from apps.api.app.services.actuators.github.specs import (
    AddLabelsResult,
    ClosePrResult,
    CommentIssueResult,
    GitHubAddLabelsSpec,
    GitHubClosePrSpec,
    GitHubCommentIssueSpec,
    GitHubOpenPrSpec,
    OpenPrResult,
    derive_head_branch,
)


class GitHubActionError(RuntimeError):
    """Raised for action-level precondition or orchestration failures.

    Distinct from ``GitHubApiError`` (raw API error) so callers can tell
    "we rejected this before hitting GitHub" from "GitHub rejected it".
    """


class RollbackImpossibleError(RuntimeError):
    """Raised when an actuator rollback cannot complete and a human must take over.

    Carries an ``actuator_state`` dict of the known last-good state so
    the executor can attach it to the ``rollback_impossible`` event
    payload for operator review.
    """

    def __init__(self, reason: str, *, actuator_state: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.actuator_state = actuator_state or {}


# ---------------------------------------------------------------------------
# github.open_pr
# ---------------------------------------------------------------------------


def open_pr(
    client: GitHubAppClient,
    spec: GitHubOpenPrSpec,
    *,
    proposal_id: str,
) -> OpenPrResult:
    """Create a branch + single commit + PR for ``spec``."""
    installation = client.config.installation_for(spec.owner, spec.repo)
    if installation is None:
        raise GitHubActionError(
            f"no installation configured for {spec.owner}/{spec.repo}; add it to config/github.yaml"
        )

    limits = client.config.limits
    if len(spec.files) > limits.max_files_per_pr:
        raise GitHubActionError(
            f"file count {len(spec.files)} exceeds configured max_files_per_pr "
            f"({limits.max_files_per_pr})"
        )
    for f in spec.files:
        if len(f.content.encode("utf-8")) > limits.max_file_bytes:
            raise GitHubActionError(
                f"file '{f.path}' exceeds configured max_file_bytes ({limits.max_file_bytes})"
            )

    head_branch = derive_head_branch(proposal_id)
    installation_id = installation.installation_id
    owner = spec.owner
    repo = spec.repo

    try:
        base = client.get_branch(installation_id, owner, repo, spec.base)
    except GitHubApiError as exc:
        if exc.status_code == 404:
            raise GitHubActionError(f"base branch '{spec.base}' does not exist") from exc
        raise

    if bool(base.get("protected")):
        raise GitHubActionError(
            f"base branch '{spec.base}' is protected; open PRs against a feature branch"
        )

    commit_block = base.get("commit") or {}
    base_commit_sha = commit_block.get("sha")
    base_tree_sha = (commit_block.get("commit") or {}).get("tree", {}).get("sha")
    if not isinstance(base_commit_sha, str) or not base_commit_sha:
        raise GitHubActionError(
            f"branch '{spec.base}' response missing commit sha; cannot build tree"
        )
    if not isinstance(base_tree_sha, str) or not base_tree_sha:
        raise GitHubActionError(
            f"branch '{spec.base}' response missing tree sha; cannot build tree"
        )

    tree_entries: list[dict[str, str]] = []
    for f in spec.files:
        blob_sha = client.create_blob(installation_id, owner, repo, f.content)
        tree_entries.append({"path": f.path, "mode": "100644", "type": "blob", "sha": blob_sha})

    tree_sha = client.create_tree(
        installation_id,
        owner,
        repo,
        base_tree_sha=base_tree_sha,
        entries=tree_entries,
    )

    commit_sha = client.create_commit(
        installation_id,
        owner,
        repo,
        message=spec.commit_message,
        tree_sha=tree_sha,
        parent_shas=[base_commit_sha],
    )

    client.create_ref(
        installation_id,
        owner,
        repo,
        ref=f"refs/heads/{head_branch}",
        sha=commit_sha,
    )

    pr = client.create_pull_request(
        installation_id,
        owner,
        repo,
        title=spec.title,
        head=head_branch,
        base=spec.base,
        body=spec.body,
    )

    pr_number = pr.get("number")
    pr_url = pr.get("html_url")
    if not isinstance(pr_number, int):
        raise GitHubActionError("pull-request response missing 'number'")
    if not isinstance(pr_url, str) or not pr_url:
        raise GitHubActionError("pull-request response missing 'html_url'")

    return OpenPrResult(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        pr_url=pr_url,
        head_branch=head_branch,
        head_sha=commit_sha,
        base_branch=spec.base,
        commit_sha=commit_sha,
        files_written=[f.path for f in spec.files],
    )


def rollback_open_pr(
    client: GitHubAppClient,
    result: OpenPrResult,
) -> dict[str, Any]:
    """Reverse a successful ``open_pr`` action."""
    installation = client.config.installation_for(result.owner, result.repo)
    if installation is None:
        raise RollbackImpossibleError(
            f"no installation configured for {result.owner}/{result.repo}; "
            "config/github.yaml must list this repo before rollback can run",
            actuator_state=result.model_dump(mode="json"),
        )

    installation_id = installation.installation_id
    owner = result.owner
    repo = result.repo
    pr_number = result.pr_number
    head_branch = result.head_branch

    pr_state: str | None = None
    pr_merged: bool = False
    pr_present = True
    try:
        pr = client.get_pull_request(installation_id, owner, repo, pr_number)
        pr_state = pr.get("state") if isinstance(pr.get("state"), str) else None
        pr_merged = bool(pr.get("merged"))
    except GitHubApiError as exc:
        if exc.status_code == 404:
            pr_present = False
        else:
            raise

    if pr_merged:
        raise RollbackImpossibleError(
            f"pull request #{pr_number} has been merged; rollback cannot undo a merge",
            actuator_state={
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "pr_url": result.pr_url,
                "head_branch": head_branch,
                "merged": True,
            },
        )

    pr_action: str
    if not pr_present:
        pr_action = "skipped_missing"
    elif pr_state == "closed":
        pr_action = "already_closed"
    else:
        client.close_pull_request(installation_id, owner, repo, pr_number)
        pr_action = "closed"

    client.delete_ref(installation_id, owner, repo, f"heads/{head_branch}")

    return {
        "pr_action": pr_action,
        "branch_deleted": head_branch,
        "owner": owner,
        "repo": repo,
        "pr_number": pr_number,
    }


# ---------------------------------------------------------------------------
# github.comment_issue
# ---------------------------------------------------------------------------


def _require_install(client: GitHubAppClient, owner: str, repo: str, action_name: str) -> int:
    inst = client.config.installation_for(owner, repo)
    if inst is None:
        raise GitHubActionError(
            f"no installation configured for {owner}/{repo}; "
            f"add it to config/github.yaml before running {action_name}"
        )
    return inst.installation_id


def comment_issue(
    client: GitHubAppClient,
    spec: GitHubCommentIssueSpec,
    *,
    proposal_id: str,  # noqa: ARG001 — kept for API symmetry with open_pr
) -> CommentIssueResult:
    """Post a comment to an issue or PR."""
    installation_id = _require_install(
        client, spec.owner, spec.repo, action_name="github.comment_issue"
    )
    resp = client.create_issue_comment(
        installation_id, spec.owner, spec.repo, spec.issue_number, spec.body
    )

    comment_id = resp.get("id")
    comment_url = resp.get("html_url")
    if not isinstance(comment_id, int):
        raise GitHubActionError("issue-comment response missing 'id'")
    if not isinstance(comment_url, str) or not comment_url:
        raise GitHubActionError("issue-comment response missing 'html_url'")

    return CommentIssueResult(
        owner=spec.owner,
        repo=spec.repo,
        issue_number=spec.issue_number,
        comment_id=comment_id,
        comment_url=comment_url,
    )


def rollback_comment_issue(
    client: GitHubAppClient,
    result: CommentIssueResult,
) -> dict[str, Any]:
    """Delete the comment we created. Idempotent on 404."""
    installation = client.config.installation_for(result.owner, result.repo)
    if installation is None:
        raise RollbackImpossibleError(
            f"no installation configured for {result.owner}/{result.repo}",
            actuator_state=result.model_dump(mode="json"),
        )

    client.delete_issue_comment(
        installation.installation_id, result.owner, result.repo, result.comment_id
    )

    return {
        "comment_deleted": result.comment_id,
        "owner": result.owner,
        "repo": result.repo,
        "issue_number": result.issue_number,
    }


# ---------------------------------------------------------------------------
# github.close_pr
# ---------------------------------------------------------------------------


def close_pr(
    client: GitHubAppClient,
    spec: GitHubClosePrSpec,
    *,
    proposal_id: str,  # noqa: ARG001 — kept for API symmetry
) -> ClosePrResult:
    """Close an open PR (without merging)."""
    installation_id = _require_install(client, spec.owner, spec.repo, action_name="github.close_pr")

    pr = client.get_pull_request(installation_id, spec.owner, spec.repo, spec.pr_number)
    state = pr.get("state") if isinstance(pr.get("state"), str) else None
    merged = bool(pr.get("merged"))
    pr_url = pr.get("html_url") if isinstance(pr.get("html_url"), str) else None

    if merged:
        raise GitHubActionError(
            f"pull request #{spec.pr_number} is merged; cannot close a merged PR"
        )
    if state != "open":
        raise GitHubActionError(
            f"pull request #{spec.pr_number} is not open (state={state!r}); nothing to close"
        )
    if not pr_url:
        raise GitHubActionError(f"pull request #{spec.pr_number} response missing 'html_url'")

    client.close_pull_request(installation_id, spec.owner, spec.repo, spec.pr_number)

    return ClosePrResult(
        owner=spec.owner,
        repo=spec.repo,
        pr_number=spec.pr_number,
        pr_url=pr_url,
        previous_state="open",
    )


def rollback_close_pr(
    client: GitHubAppClient,
    result: ClosePrResult,
) -> dict[str, Any]:
    """Reopen a previously-open PR that we closed.

    If the PR was merged between close and rollback (GitHub rejects
    reopen on merged PRs), surface as ``RollbackImpossibleError``.
    """
    installation = client.config.installation_for(result.owner, result.repo)
    if installation is None:
        raise RollbackImpossibleError(
            f"no installation configured for {result.owner}/{result.repo}",
            actuator_state=result.model_dump(mode="json"),
        )

    installation_id = installation.installation_id

    # Pre-check merged so we raise a clean RollbackImpossibleError
    # rather than relying on the 422 from PATCH state=open.
    try:
        pr = client.get_pull_request(installation_id, result.owner, result.repo, result.pr_number)
    except GitHubApiError as exc:
        if exc.status_code == 404:
            raise RollbackImpossibleError(
                f"pull request #{result.pr_number} no longer exists; cannot reopen",
                actuator_state=result.model_dump(mode="json"),
            ) from exc
        raise

    if bool(pr.get("merged")):
        raise RollbackImpossibleError(
            f"pull request #{result.pr_number} was merged after close; reopen is impossible",
            actuator_state={**result.model_dump(mode="json"), "merged": True},
        )

    state = pr.get("state") if isinstance(pr.get("state"), str) else None
    if state == "open":
        return {
            "pr_action": "already_open",
            "owner": result.owner,
            "repo": result.repo,
            "pr_number": result.pr_number,
        }

    try:
        client.reopen_pull_request(installation_id, result.owner, result.repo, result.pr_number)
    except GitHubApiError as exc:
        # 422 typically means GitHub refused the reopen (e.g. a race
        # where the PR was merged after our pre-check). Treat as
        # impossible so the operator takes over.
        if exc.status_code == 422:
            raise RollbackImpossibleError(
                f"pull request #{result.pr_number} reopen refused by GitHub "
                f"({exc.message}); manual reconcile required",
                actuator_state=result.model_dump(mode="json"),
            ) from exc
        raise

    return {
        "pr_action": "reopened",
        "owner": result.owner,
        "repo": result.repo,
        "pr_number": result.pr_number,
    }


# ---------------------------------------------------------------------------
# github.add_labels
# ---------------------------------------------------------------------------


def add_labels(
    client: GitHubAppClient,
    spec: GitHubAddLabelsSpec,
    *,
    proposal_id: str,  # noqa: ARG001 — kept for API symmetry
) -> AddLabelsResult:
    """Add labels to an issue or PR.

    We pre-list existing labels so the result captures only labels that
    **we** added. Rollback removes only those, leaving pre-existing
    labels untouched.
    """
    installation_id = _require_install(
        client, spec.owner, spec.repo, action_name="github.add_labels"
    )

    existing = set(
        client.list_issue_labels(installation_id, spec.owner, spec.repo, spec.issue_number)
    )
    to_add = [lbl for lbl in spec.labels if lbl not in existing]
    already_present = [lbl for lbl in spec.labels if lbl in existing]

    if to_add:
        client.add_issue_labels(installation_id, spec.owner, spec.repo, spec.issue_number, to_add)

    return AddLabelsResult(
        owner=spec.owner,
        repo=spec.repo,
        issue_number=spec.issue_number,
        labels_added=to_add,
        labels_already_present=already_present,
    )


def rollback_add_labels(
    client: GitHubAppClient,
    result: AddLabelsResult,
) -> dict[str, Any]:
    """Remove only the labels we added. Idempotent on 404 per label."""
    installation = client.config.installation_for(result.owner, result.repo)
    if installation is None:
        raise RollbackImpossibleError(
            f"no installation configured for {result.owner}/{result.repo}",
            actuator_state=result.model_dump(mode="json"),
        )

    installation_id = installation.installation_id
    for label in result.labels_added:
        client.remove_issue_label(
            installation_id, result.owner, result.repo, result.issue_number, label
        )

    return {
        "labels_removed": list(result.labels_added),
        "owner": result.owner,
        "repo": result.repo,
        "issue_number": result.issue_number,
    }
