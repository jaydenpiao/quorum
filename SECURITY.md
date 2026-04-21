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

## Known gaps (pre-Phase 2)

These are tracked issues, not secrets. The project's current Phase 2 work plan addresses them directly:

- `apps/api/app/services/health_checks.py` uses `subprocess.run(..., shell=True)` with command strings from proposal payloads. Shell injection. **Do not deploy pre-Phase-2 Quorum on any reachable network.**
- All API routes are unauthenticated. `POST /api/v1/demo/incident` resets state and has no auth.
- The event log has no tamper-evidence (no hash chain, no signatures). Corruption of `data/events.jsonl` is not detectable at startup.
- No rate limiting, no CORS policy, no security headers on the FastAPI app.

If you find a vulnerability *beyond* these — especially in the domain model, policy engine, quorum engine, executor, or future actuators — please report it.

## Safe harbor

Good-faith research is welcome. We will not pursue legal action against researchers who:

- Give us reasonable time to fix before public disclosure.
- Avoid privacy violations, data destruction, and degradation of user experience.
- Do not exfiltrate data beyond what is necessary to demonstrate the issue.
- Only test against systems you own or are explicitly authorized to test.
