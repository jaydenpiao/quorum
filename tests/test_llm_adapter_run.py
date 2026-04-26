"""CLI entrypoint behavior for the LLM adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

import apps.llm_agent.run as run_module
from apps.llm_agent.config import AgentProfile, LlmAgentConfig


class _DummyQuorum:
    agent_id = "deploy-llm-agent"

    def close(self) -> None:
        return None


class _CapturedMetrics:
    def __init__(self) -> None:
        self.ticks: list[dict[str, str]] = []

    def record_tick(self, *, agent_id: str, outcome: str) -> None:
        self.ticks.append({"agent_id": agent_id, "outcome": outcome})


def test_main_starts_metrics_server_when_port_is_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = AgentProfile(
        id="deploy-llm-agent",
        llm=LlmAgentConfig(system_prompt_ref="prompts/deploy-agent.md"),
    )
    started_ports: list[int] = []

    monkeypatch.setattr(run_module, "load_agent_profile", lambda _path, _agent_id: profile)
    monkeypatch.setattr(run_module, "read_prompt", lambda _path: "ROLE: deploy")
    monkeypatch.setattr(run_module, "LlmBudget", lambda **_kwargs: object())
    monkeypatch.setattr(run_module, "ClaudeClient", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(run_module, "QuorumApiClient", lambda **_kwargs: _DummyQuorum())
    monkeypatch.setattr(run_module, "run_tick", lambda **_kwargs: None)
    monkeypatch.setattr(
        run_module,
        "start_metrics_server",
        lambda port: started_ports.append(port),
    )

    rc = run_module.main(
        [
            "--agent-id",
            "deploy-llm-agent",
            "--config",
            "config/agents.yaml",
            "--quorum-url",
            "http://localhost:8080",
            "--cursor-dir",
            str(tmp_path),
            "--metrics-port",
            "9107",
            "--once",
        ]
    )

    assert rc == 0
    assert started_ports == [9107]


def test_main_does_not_start_metrics_server_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = AgentProfile(
        id="deploy-llm-agent",
        llm=LlmAgentConfig(system_prompt_ref="prompts/deploy-agent.md"),
    )
    started_ports: list[int] = []

    monkeypatch.setattr(run_module, "load_agent_profile", lambda _path, _agent_id: profile)
    monkeypatch.setattr(run_module, "read_prompt", lambda _path: "ROLE: deploy")
    monkeypatch.setattr(run_module, "LlmBudget", lambda **_kwargs: object())
    monkeypatch.setattr(run_module, "ClaudeClient", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(run_module, "QuorumApiClient", lambda **_kwargs: _DummyQuorum())
    monkeypatch.setattr(run_module, "run_tick", lambda **_kwargs: None)
    monkeypatch.setattr(
        run_module,
        "start_metrics_server",
        lambda port: started_ports.append(port),
    )

    rc = run_module.main(
        [
            "--agent-id",
            "deploy-llm-agent",
            "--config",
            "config/agents.yaml",
            "--quorum-url",
            "http://localhost:8080",
            "--cursor-dir",
            str(tmp_path),
            "--once",
        ]
    )

    assert rc == 0
    assert started_ports == []


def test_main_records_error_metric_on_tick_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = AgentProfile(
        id="deploy-llm-agent",
        llm=LlmAgentConfig(system_prompt_ref="prompts/deploy-agent.md"),
    )
    metrics = _CapturedMetrics()

    def fail_tick(**_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(run_module, "load_agent_profile", lambda _path, _agent_id: profile)
    monkeypatch.setattr(run_module, "read_prompt", lambda _path: "ROLE: deploy")
    monkeypatch.setattr(run_module, "LlmBudget", lambda **_kwargs: object())
    monkeypatch.setattr(run_module, "ClaudeClient", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(run_module, "QuorumApiClient", lambda **_kwargs: _DummyQuorum())
    monkeypatch.setattr(run_module, "run_tick", fail_tick)
    monkeypatch.setattr(run_module, "_metrics", metrics)

    with pytest.raises(RuntimeError, match="boom"):
        run_module.main(
            [
                "--agent-id",
                "deploy-llm-agent",
                "--config",
                "config/agents.yaml",
                "--quorum-url",
                "http://localhost:8080",
                "--cursor-dir",
                str(tmp_path),
                "--once",
            ]
        )

    assert metrics.ticks == [{"agent_id": "deploy-llm-agent", "outcome": "error"}]
