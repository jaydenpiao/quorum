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

Rollback semantics for ``rollback_open_pr`` (PR C):

- ``get_pull_request`` first — if ``merged=True`` we cannot undo the
  merge; we raise ``RollbackImpossibleError`` with enough state for a
  human to find and revert manually.
- If the PR is still open, ``close_pull_request``. If already closed,
  skip (idempotent).
- Always attempt ``delete_ref`` for ``heads/<head_branch>``; the client
  swallows 404 / 422 so a re-run is idempotent.
- A client-side 404 on the GET means the PR itself is gone (rare —
  someone deleted it manually). Treat as already-rolled-back and
  proceed to the branch delete.
"""

from __future__ import annotations

from typing import Any

from apps.api.app.services.actuators.github.client import GitHubApiError, GitHubAppClient
from apps.api.app.services.actuators.github.specs import (
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


def open_pr(
    client: GitHubAppClient,
    spec: GitHubOpenPrSpec,
    *,
    proposal_id: str,
) -> OpenPrResult:
    """Create a branch + single commit + PR for ``spec``.

    Returns an ``OpenPrResult`` describing the created PR. Raises
    ``GitHubActionError`` for precondition failures (no matching install,
    protected base, limits exceeded) and ``GitHubApiError`` /
    ``GitHubAppAuthError`` on failures mid-flow.
    """
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

    # 1. Resolve the base branch — must exist and not be protected.
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

    # 2. Upload each file as a blob.
    tree_entries: list[dict[str, str]] = []
    for f in spec.files:
        blob_sha = client.create_blob(installation_id, owner, repo, f.content)
        tree_entries.append({"path": f.path, "mode": "100644", "type": "blob", "sha": blob_sha})

    # 3. Build a tree on top of the base tree.
    tree_sha = client.create_tree(
        installation_id,
        owner,
        repo,
        base_tree_sha=base_tree_sha,
        entries=tree_entries,
    )

    # 4. Commit the tree with the base commit as sole parent.
    commit_sha = client.create_commit(
        installation_id,
        owner,
        repo,
        message=spec.commit_message,
        tree_sha=tree_sha,
        parent_shas=[base_commit_sha],
    )

    # 5. Create the head ref pointing at the new commit.
    #
    # If the branch already exists (422 from GitHub), the rollback helper
    # is the correct place to reclaim it. We surface the raw error here —
    # the executor can translate it into a failed execution.
    client.create_ref(
        installation_id,
        owner,
        repo,
        ref=f"refs/heads/{head_branch}",
        sha=commit_sha,
    )

    # 6. Open the PR.
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
    """Reverse a successful ``open_pr`` action.

    Best-effort but well-defined: close the PR (if open), delete the
    branch (idempotent on 404/422). If the PR has been merged out-of-
    band we cannot roll back and raise ``RollbackImpossibleError``
    with enough state for a human to locate and revert the merge.

    Returns a summary dict describing what was actually done (closed/
    already_closed, deleted/already_gone/skipped).
    """
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
            # PR vanished — treat as already-rolled-back for the PR step,
            # but still try to clean up the branch below.
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

    # delete_ref already swallows 404 / 422, so a re-run is idempotent.
    client.delete_ref(installation_id, owner, repo, f"heads/{head_branch}")

    return {
        "pr_action": pr_action,
        "branch_deleted": head_branch,
        "owner": owner,
        "repo": repo,
        "pr_number": pr_number,
    }
