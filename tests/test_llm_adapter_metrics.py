"""Prometheus metrics for the LLM adapter."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, generate_latest

from apps.llm_agent.metrics import LlmMetrics


def _render(registry: CollectorRegistry) -> str:
    return generate_latest(registry).decode("utf-8")


def test_metrics_record_llm_token_counts() -> None:
    registry = CollectorRegistry()
    metrics = LlmMetrics(registry=registry)

    metrics.record_llm_call(
        agent_id="deploy-llm-agent",
        model="claude-opus-4-7",
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=30,
        cache_write_tokens=40,
    )

    rendered = _render(registry)
    assert (
        'quorum_llm_tokens_total{agent_id="deploy-llm-agent",kind="input",'
        'model="claude-opus-4-7"} 100.0'
    ) in rendered
    assert (
        'quorum_llm_tokens_total{agent_id="deploy-llm-agent",kind="output",'
        'model="claude-opus-4-7"} 20.0'
    ) in rendered
    assert (
        'quorum_llm_tokens_total{agent_id="deploy-llm-agent",kind="cache_read",'
        'model="claude-opus-4-7"} 30.0'
    ) in rendered
    assert (
        'quorum_llm_tokens_total{agent_id="deploy-llm-agent",kind="cache_write",'
        'model="claude-opus-4-7"} 40.0'
    ) in rendered


def test_metrics_record_tick_outcomes_and_proposals() -> None:
    registry = CollectorRegistry()
    metrics = LlmMetrics(registry=registry)

    metrics.record_tick(agent_id="deploy-llm-agent", outcome="acted")
    metrics.record_tick(agent_id="deploy-llm-agent", outcome="skipped_idle")
    metrics.record_proposal_created(
        agent_id="deploy-llm-agent",
        action_type="fly.deploy",
    )

    rendered = _render(registry)
    assert 'quorum_llm_ticks_total{agent_id="deploy-llm-agent",outcome="acted"} 1.0' in rendered
    assert (
        'quorum_llm_ticks_total{agent_id="deploy-llm-agent",outcome="skipped_idle"} 1.0' in rendered
    )
    assert (
        'quorum_llm_proposals_created_total{action_type="fly.deploy",'
        'agent_id="deploy-llm-agent"} 1.0'
    ) in rendered
