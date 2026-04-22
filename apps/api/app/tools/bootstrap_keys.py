"""Key bootstrap and rotation tool for Quorum API agents.

Usage
-----
Generate a new key for an agent (replaces any existing hash):

    python -m apps.api.app.tools.bootstrap_keys generate --agent-id <id>

Rotate (alias for generate):

    python -m apps.api.app.tools.bootstrap_keys rotate --agent-id <id>

Optional flags:

    --config PATH       Path to agents.yaml  (default: config/agents.yaml
                        relative to the repo root inferred from this file)
    --output json       Emit JSON instead of human text; useful for scripts
                        that need to capture the plaintext key.

Security notes
--------------
- The plaintext key is generated server-side with `secrets.token_urlsafe(32)`.
  It is printed ONCE to stdout and is never stored anywhere.
- The argon2id hash is written to the YAML file at `api_key_hash`.
- PyYAML is used for in-place updates; YAML comments will be stripped.
  If comment preservation matters, use ruamel.yaml manually.
- Do NOT pass a plaintext key on the command line — that would expose it in
  shell history. This tool always generates a fresh server-side key.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

import yaml
from argon2 import PasswordHasher


# ---------------------------------------------------------------------------
# Default config path: repo-root/config/agents.yaml
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = str(Path(__file__).parents[5] / "config" / "agents.yaml")


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def _generate_and_write(agent_id: str, config_path: str) -> tuple[str, str]:
    """Generate a new key, hash it, write to YAML, and return (plaintext, hash).

    The plaintext is returned exactly once — caller must print it and then
    discard it. It is never written to disk.
    """
    plaintext = secrets.token_urlsafe(32)
    ph = PasswordHasher()
    stored_hash = ph.hash(plaintext)

    # Read the current YAML. PyYAML strips comments — documented in module docstring.
    path = Path(config_path)
    try:
        data = yaml.safe_load(path.read_text())
    except (FileNotFoundError, yaml.YAMLError) as exc:
        print(f"ERROR: cannot read {config_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict) or "agents" not in data:
        print(f"ERROR: {config_path} does not contain an 'agents' list.", file=sys.stderr)
        sys.exit(1)

    found = False
    for agent in data["agents"]:
        if agent.get("id") == agent_id:
            agent["api_key_hash"] = stored_hash
            found = True
            break

    if not found:
        print(
            f"ERROR: agent '{agent_id}' not found in {config_path}.",
            file=sys.stderr,
        )
        sys.exit(1)

    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return plaintext, stored_hash


# ---------------------------------------------------------------------------
# CLI output formatters
# ---------------------------------------------------------------------------


def _print_human(agent_id: str, plaintext: str, stored_hash: str) -> None:
    border = "=" * 60
    print(border)
    print("  QUORUM KEY BOOTSTRAP — SAVE THIS PLAINTEXT KEY")
    print("  It will NOT be shown again.")
    print(border)
    print(f"  Agent ID  : {agent_id}")
    print(f"  PLAINTEXT KEY: {plaintext}")
    print("  Hash (argon2id) written to agents.yaml:")
    print(f"  {stored_hash[:40]}...")
    print(border)


def _print_json(agent_id: str, plaintext: str, stored_hash: str) -> None:
    payload = {
        "agent_id": agent_id,
        "plaintext_key": plaintext,
        "hash_prefix": stored_hash[:20] + "...",
    }
    print(json.dumps(payload))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="bootstrap_keys",
        description="Generate or rotate argon2id API keys for Quorum agents.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for cmd in ("generate", "rotate"):
        sub = subparsers.add_parser(cmd, help=f"{cmd} a key for an agent")
        sub.add_argument("--agent-id", required=True, help="Agent ID as in agents.yaml")
        sub.add_argument(
            "--config",
            default=_DEFAULT_CONFIG,
            help="Path to agents.yaml (default: config/agents.yaml in repo root)",
        )
        sub.add_argument(
            "--output",
            choices=["human", "json"],
            default="human",
            help="Output format (default: human)",
        )

    args = parser.parse_args(argv)

    plaintext, stored_hash = _generate_and_write(args.agent_id, args.config)

    if args.output == "json":
        _print_json(args.agent_id, plaintext, stored_hash)
    else:
        _print_human(args.agent_id, plaintext, stored_hash)


if __name__ == "__main__":
    main()
