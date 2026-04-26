"""Prometheus metrics for the standalone LLM adapter process."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, REGISTRY
from prometheus_client import start_http_server as _start_http_server


class LlmMetrics:
    """Thin wrapper around the adapter's Prometheus counters."""

    def __init__(self, *, registry: CollectorRegistry = REGISTRY) -> None:
        self._tokens = Counter(
            "quorum_llm_tokens_total",
            "LLM adapter tokens reported by provider usage metadata.",
            ("agent_id", "model", "kind"),
            registry=registry,
        )
        self._ticks = Counter(
            "quorum_llm_ticks_total",
            "LLM adapter tick outcomes.",
            ("agent_id", "outcome"),
            registry=registry,
        )
        self._proposals = Counter(
            "quorum_llm_proposals_created_total",
            "LLM adapter proposals successfully created through the Quorum API.",
            ("agent_id", "action_type"),
            registry=registry,
        )

    def record_llm_call(
        self,
        *,
        agent_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
    ) -> None:
        self._inc_tokens(agent_id, model, "input", input_tokens)
        self._inc_tokens(agent_id, model, "output", output_tokens)
        self._inc_tokens(agent_id, model, "cache_read", cache_read_tokens)
        self._inc_tokens(agent_id, model, "cache_write", cache_write_tokens)

    def record_tick(self, *, agent_id: str, outcome: str) -> None:
        self._ticks.labels(agent_id=agent_id, outcome=outcome).inc()

    def record_proposal_created(self, *, agent_id: str, action_type: str) -> None:
        self._proposals.labels(agent_id=agent_id, action_type=action_type).inc()

    def _inc_tokens(self, agent_id: str, model: str, kind: str, value: int) -> None:
        if value < 0:
            raise ValueError("token counters cannot be negative")
        if value == 0:
            return
        self._tokens.labels(agent_id=agent_id, model=model, kind=kind).inc(value)


DEFAULT_METRICS = LlmMetrics()


def start_metrics_server(port: int) -> None:
    """Expose the default registry on ``/metrics`` from a sidecar HTTP server."""
    if port < 1 or port > 65535:
        raise ValueError("metrics port must be between 1 and 65535")
    _start_http_server(port, registry=REGISTRY)
