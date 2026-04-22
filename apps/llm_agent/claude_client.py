"""Claude SDK wrapper for the LLM adapter.

Thin — all it does is:

1. Hold an ``anthropic.Anthropic`` instance (with ``ANTHROPIC_API_KEY``
   loaded from env by the SDK).
2. Build request bodies with prompt caching + adaptive thinking wired
   in the right places so the system prompt actually caches.
3. Call ``messages.create()`` and return the raw response.

The wrapper is deliberately small so the unit tests can assert on the
body shape without mocking the full SDK; higher-level orchestration
(budget checks, tool dispatch, cursor advance) lives in ``loop.py``.

Per the claude-api skill:
- Prompt-caching uses top-level ``cache_control={"type": "ephemeral"}``
  on ``messages.create()``. This automatically caches the last cacheable
  block — the system prompt, given our ordering — without requiring
  per-block annotations.
- Adaptive thinking is enabled via ``thinking={"type": "adaptive"}``.
  No ``budget_tokens`` on Opus 4.7 (the field was removed; it would
  return a 400).
- Default output effort is ``high`` when the model supports it
  (Opus 4.6+, Sonnet 4.6+). Haiku 4.5 / Sonnet 4.5 don't accept the
  ``effort`` field and would 400; the wrapper simply omits the field
  there.
"""

from __future__ import annotations

from typing import Any, cast

import anthropic

from apps.llm_agent.config import LlmAgentConfig

# Default output cap. 4096 tokens is plenty for emitting a few findings
# + explanatory prose; operators can override per config if/when we
# expose that knob. Non-streaming, well under SDK HTTP timeouts.
DEFAULT_MAX_OUTPUT_TOKENS = 4096

# Models where ``output_config.effort`` is supported. Per the
# claude-api skill: Haiku 4.5 and Sonnet 4.5 and older reject the field.
_EFFORT_SUPPORTED_PREFIXES = (
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-sonnet-4-6",
)


class ClaudeClient:
    """Wrapper around ``anthropic.Anthropic`` with adapter-specific defaults.

    Injectable ``sdk`` kwarg lets tests swap in a stub or a pre-patched
    client; prod uses the real SDK with the env-var API key.
    """

    def __init__(
        self,
        config: LlmAgentConfig,
        system_prompt: str,
        *,
        sdk: anthropic.Anthropic | None = None,
    ) -> None:
        self._config = config
        self._system_prompt = system_prompt
        self._sdk = sdk or anthropic.Anthropic()

    @property
    def config(self) -> LlmAgentConfig:
        return self._config

    def supports_effort(self) -> bool:
        """Return True iff the configured model accepts ``output_config.effort``."""
        return self._config.model.startswith(_EFFORT_SUPPORTED_PREFIXES)

    def build_request(
        self,
        *,
        user_content: str,
        max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> dict[str, Any]:
        """Construct the body kwargs we pass to ``messages.create()``.

        Returns a plain ``dict`` (not a typed params object) so tests can
        compare it directly against an expected shape.
        """
        body: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": max_tokens,
            # ``system`` as a list so prompt caching picks up the single
            # text block as its cache prefix. Top-level ``cache_control``
            # auto-caches this last cacheable block.
            "system": [{"type": "text", "text": self._system_prompt}],
            "cache_control": {"type": "ephemeral"},
            # Adaptive thinking is the only on-mode on Opus 4.7; it works
            # on Opus 4.6 and Sonnet 4.6 as well. Emitting it on older
            # models would 400, but we default to Opus 4.7 and document
            # the constraint; the adapter does not transparently
            # downgrade.
            "thinking": {"type": "adaptive"},
            "messages": [
                {"role": "user", "content": user_content},
            ],
        }
        if self.supports_effort():
            body["output_config"] = {"effort": "high"}
        return body

    def call_messages(
        self,
        *,
        user_content: str,
        max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> anthropic.types.Message:
        """Build the request + invoke ``messages.create()``. Returns the raw Message."""
        body = self.build_request(user_content=user_content, max_tokens=max_tokens)
        # The SDK's overloaded ``messages.create`` resolves to an ``Any``
        # return when invoked with ``**body`` kwargs; cast to the concrete
        # Message type for callers.
        return cast(anthropic.types.Message, self._sdk.messages.create(**body))
