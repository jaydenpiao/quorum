# GitHub automation

## Goal

Keep repo setup and routine git operations close to fully automated.

## Constraint in this environment

The GitHub integration available here can manipulate **existing repositories**:
- create files
- update files
- create branches
- open PRs
- merge PRs

But it does not expose a direct "create repository" action.

So this repo ships with scripts that an agent can run locally with a token.

## Fast path with GitHub CLI

```bash
./scripts/bootstrap_local_repo.sh
./scripts/create_public_github_repo.sh Quorum
```

This uses:

```bash
gh repo create Quorum --public --source . --remote origin --push
```

## Token path without gh

If `gh` is unavailable, the script falls back to the GitHub REST API using `GITHUB_TOKEN`.

Required token scope:
- `repo`

## Recommended repo settings after creation

- public visibility
- default branch: `main`
- squash merge enabled
- branch protection on `main`
- required CI checks
- optional auto-merge later

## Suggested automation after bootstrap

1. agent creates branch or worktree
2. agent makes patch
3. agent runs `./scripts/validate_merge.sh`
4. agent commits
5. agent pushes
6. agent opens PR
7. CI validates
8. merge via squash
