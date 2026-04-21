# Contributing to Quorum

Thanks for your interest in Quorum — a control plane for safe, auditable, policy-gated, quorum-based execution by AI agents operating on code and infrastructure.

Quorum is explicitly designed to be **AI-readable and AI-maintainable**. Contributions from humans and from AI agents (via PRs they open on behalf of operators) are both welcome. The bar is the same.

## Before you start

Read these first:

1. [`AGENTS.md`](AGENTS.md) — repo-wide operating rules and the "Definition of done" checklist.
2. [`INIT.md`](INIT.md) — mission and immediate priorities.
3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the control-plane design.
4. [`docs/REPO_MAP.md`](docs/REPO_MAP.md) — where things live.
5. [`docs/PARALLEL_DEVELOPMENT.md`](docs/PARALLEL_DEVELOPMENT.md) — current single-threaded mode vs future worktree mode.

## Local development

Requirements: Python 3.12+, `uv` (recommended), or any venv tool.

```bash
# Option A — uv (recommended)
uv sync --extra dev
uv run make validate

# Option B — venv + pip
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
make validate
```

Run the dev server:

```bash
make dev     # uvicorn on http://127.0.0.1:8080
```

Open the operator console at http://127.0.0.1:8080/console and seed a demo:

```bash
curl -sX POST http://127.0.0.1:8080/api/v1/demo/incident | python3 -m json.tool
```

Run the "am I green?" check before opening a PR:

```bash
make validate    # ruff check + ruff format --check + pytest
```

## Branch and PR workflow

- Branch from `main`. Use the naming convention in [`docs/PARALLEL_DEVELOPMENT.md`](docs/PARALLEL_DEVELOPMENT.md): `agent/<role>/<task>` or `chore/<topic>` or `fix/<topic>` or `feat/<topic>`.
- Keep PRs small and focused. One coherent vertical slice per PR.
- All CI checks must pass. If you can't make CI green, say so in the PR description — don't silence checks.
- Reference the issue or plan file your PR resolves, if any.
- Use squash-merge.

## Commit messages

Short, imperative, explain the **why**:

- `fix: reject shell-injection payload in HealthCheckSpec`
- `feat: hash-chain EventEnvelope for tamper-evident audit log`
- `docs: add event-flow diagram for rollback path`

## Developer Certificate of Origin (DCO)

We use the [Developer Certificate of Origin (DCO)](https://developercertificate.org/) instead of a CLA. By adding a `Signed-off-by` line to each commit, you certify that you wrote or otherwise have the right to submit the code:

```bash
git commit -s -m "feat: your change"
```

That line says you have the right to contribute the work, and that you accept the Apache-2.0 license for it.

If a commit lands without `Signed-off-by`, you can add it via `git commit --amend -s` (before pushing) or open a follow-up PR.

## Code style

- **Python 3.12+** with `ruff` (checked and formatted). Line length 100.
- **Types matter.** Use Pydantic models for boundaries. `Literal`/`Enum` for closed sets.
- **No metaprogramming, no hidden globals.** See [`AGENTS.md`](AGENTS.md#coding-rules).
- **Tests are required** for any change to the core state machine (`apps/api/app/domain/**`, `services/**`, `api/routes.py`).
- **Docs are part of the patch.** If behavior changes, `docs/ARCHITECTURE.md` and related docs change in the same PR. See [`AGENTS.md`](AGENTS.md#docs-rules).

## Safety rules (hard no)

From [`AGENTS.md`](AGENTS.md#safety-rules), these are product primitives, not style:

- No execution path without a proposal.
- No silent policy bypass.
- No mutation without event logging.
- No success declared before health verification.

PRs that violate these will be asked to restructure — not merged with a "fix later" note.

## Shared-core changes

These files require extra care (see [`docs/PARALLEL_DEVELOPMENT.md`](docs/PARALLEL_DEVELOPMENT.md#shared-core-rule)):

- `apps/api/app/domain/models.py`
- `apps/api/app/services/event_log.py`
- `apps/api/app/services/state_store.py`
- `config/policies.yaml`

Changes to any of these need:

- An explicit migration note for event-log format changes.
- Docs updated in the same PR.
- CODEOWNERS review (enforced by `.github/CODEOWNERS`).

## Reporting bugs

- **Security issues** → see [`SECURITY.md`](SECURITY.md). Don't file security bugs in public issues.
- **Everything else** → open a GitHub issue with: what happened, what you expected, steps to reproduce, commit hash.

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).

## Questions

Open a GitHub Discussion or tag a maintainer in an issue. For the current phase of the project, that means `@jaydenpiao`.
