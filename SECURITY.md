# Security Policy

Quorum is a control plane that gates real mutations to code and infrastructure. Security is the product, not a wrapper — we take vulnerability reports seriously.

## Supported versions

Quorum is pre-1.0 alpha. Only the `main` branch is supported. There are no backported fixes.

## Reporting a vulnerability

**Do not open a public GitHub issue for security reports.**

Report privately via one of:

1. **GitHub private vulnerability reporting** — https://github.com/jaydenpiao/quorum/security/advisories/new (preferred)
2. **Email** — jaydenpiao87@gmail.com

Please include:

- A description of the vulnerability.
- Steps to reproduce (or a proof-of-concept).
- The affected commit hash or release tag.
- Your assessment of impact (integrity, confidentiality, availability, scope).
- Whether you believe it is currently being exploited.

## What to expect

- **Acknowledgement** within **72 hours**.
- **Initial assessment** within **7 days**.
- **Coordinated disclosure**: we aim to publish a fix and advisory within **90 days** of the initial report. If the vulnerability is actively exploited or trivially weaponizable, we may accelerate disclosure.
- **Credit** in the advisory if you want it (opt-in).

## Scope

In-scope targets:

- The Quorum API (`apps/api/**`) — authentication bypass, policy bypass, event-log tampering, injection (shell, SQL, command), authorization flaws, information disclosure, memory exhaustion against a production deployment.
- The operator console (`apps/console/**`) — XSS, CSRF once sessions land (Phase 2), insecure cookie handling.
- Supply chain — malicious dependencies, CI/CD compromise, typosquatting of published artifacts.
- Docker/Fly deployment configs once they land (Phase 3+).

Out-of-scope:

- Issues that require physical access to a deployed host.
- Attacks that require the attacker to already have valid operator credentials *unless* the attack achieves privilege escalation or evades the event log.
- Denial-of-service via unauthenticated flooding (rate limiting is Phase 2; please flag it as a design issue, not a vulnerability).
- Findings in third-party dependencies without a Quorum-specific exploit chain — report those upstream and open an informational issue here.

## Known gaps

Phase 2 (closed — see `git log --grep 'Phase 2'`):

- ~~Shell-dispatch health checks~~ → replaced with registered typed probes (`http`, `always_pass`, `always_fail`) in PR #7.
- ~~Unauthenticated API~~ → bearer-token auth on every mutating route (PR #10).
- ~~Publicly reachable demo/reset endpoint~~ → gated behind `QUORUM_ALLOW_DEMO=1` + auth (PR #10).
- ~~No event-log tamper-evidence~~ → sha256 hash chain with startup verification and `GET /api/v1/events/verify` (PR #8).
- ~~No CORS, security headers, or rate limiting~~ → CORS pinned to allowlisted origins, CSP/HSTS/XFO/XCTO/Referrer-Policy/Permissions-Policy added, slowapi rate limit registered (PR #9).
- ~~Unbounded input payloads~~ → strict pydantic DTOs with `extra='forbid'` and per-field length bounds (PR #9).

Phase 2.5 (closed):

- ~~Server-side `actor_id` binding~~ → the authenticated agent is now authoritative for intent/finding/proposal/vote/execute; spoofed `agent_id` returns 403 (PR landing this).
- ~~argon2id-hashed keys in `config/agents.yaml` in place of the env-var registry; key-rotation tooling~~ → `api_key_hash` field added to `config/agents.yaml`; `apps/api/app/services/auth.py` consults the YAML registry (argon2id verify) after the env-var registry (constant-time compare); `python -m apps.api.app.tools.bootstrap_keys generate/rotate` generates and stores keys without ever persisting plaintext; env-var registry retained as fallback for dev parity.

Open:

- Sign the event hash chain with an ed25519 key so mutations across a compromised single-writer are still detectable.
- Human-approval workflow for high/critical risk proposals (Phase 4).
- Real actuators (GitHub App first) with scoped install tokens (Phase 4).

If you find a vulnerability outside this list — especially in the domain model, policy engine, quorum engine, executor, or the hash-chain verifier — please report it.

## Safe harbor

Good-faith research is welcome. We will not pursue legal action against researchers who:

- Give us reasonable time to fix before public disclosure.
- Avoid privacy violations, data destruction, and degradation of user experience.
- Do not exfiltrate data beyond what is necessary to demonstrate the issue.
- Only test against systems you own or are explicitly authorized to test.
