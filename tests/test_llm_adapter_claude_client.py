"""Claude request-body builder + respx-mocked SDK call."""

from __future__ import annotations

import anthropic
import httpx
import pytest
import respx

from apps.llm_agent.claude_client import DEFAULT_MAX_OUTPUT_TOKENS, ClaudeClient
from apps.llm_agent.config import LlmAgentConfig


def _config(**overrides: object) -> LlmAgentConfig:
    defaults: dict[str, object] = {
        "system_prompt_ref": "prompts/telemetry-agent.md",
    }
    defaults.update(overrides)
    return LlmAgentConfig.model_validate(defaults)


# ---------------------------------------------------------------------------
# Body construction
# ---------------------------------------------------------------------------


def test_build_request_defaults() -> None:
    client = ClaudeClient(_config(), system_prompt="ROLE: telemetry")
    body = client.build_request(user_content='{"events":[]}')

    assert body["model"] == "claude-opus-4-7"  # default
    assert body["max_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS
    assert body["thinking"] == {"type": "adaptive"}
    # System prompt is a list with a single text block so prompt caching
    # sees a stable cache-prefix block boundary.
    assert body["system"] == [{"type": "text", "text": "ROLE: telemetry"}]
    # Top-level cache_control auto-caches the last cacheable block.
    assert body["cache_control"] == {"type": "ephemeral"}
    # Opus 4.7 supports effort → included by default.
    assert body["output_config"] == {"effort": "high"}
    # User message is minimal, no timestamps or UUIDs.
    assert body["messages"] == [{"role": "user", "content": '{"events":[]}'}]


def test_build_request_omits_effort_for_unsupported_models() -> None:
    client = ClaudeClient(
        _config(model="claude-haiku-4-5"),
        system_prompt="...",
    )
    body = client.build_request(user_content="x")
    assert "output_config" not in body, (
        "effort is rejected with 400 on haiku; adapter must not emit it"
    )


def test_build_request_custom_max_tokens() -> None:
    client = ClaudeClient(_config(), system_prompt="x")
    body = client.build_request(user_content="x", max_tokens=1024)
    assert body["max_tokens"] == 1024


def test_build_request_is_deterministic() -> None:
    """Same inputs → byte-identical body so prompt caching stays warm."""
    client = ClaudeClient(_config(), system_prompt="stable")
    b1 = client.build_request(user_content="u")
    b2 = client.build_request(user_content="u")
    assert b1 == b2


# ---------------------------------------------------------------------------
# Live-SDK invocation (respx-stubbed)
# ---------------------------------------------------------------------------


def _stub_response(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": "msg_01ABC",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-4-7",
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "content": [{"type": "text", "text": "ack"}],
        "usage": {
            "input_tokens": 123,
            "output_tokens": 4,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }
    body.update(overrides)
    return body


def test_call_messages_returns_sdk_message() -> None:
    sdk = anthropic.Anthropic(api_key="test-key-ignored")
    client = ClaudeClient(_config(), system_prompt="prompt", sdk=sdk)

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json=_stub_response())
        )

        result = client.call_messages(user_content='{"events":[]}')

    assert route.call_count == 1
    assert result.usage.input_tokens == 123
    assert result.usage.output_tokens == 4
    assert result.stop_reason == "end_turn"


def test_call_messages_sends_configured_model_in_body() -> None:
    sdk = anthropic.Anthropic(api_key="test-key-ignored")
    client = ClaudeClient(
        _config(model="claude-sonnet-4-6"),
        system_prompt="prompt",
        sdk=sdk,
    )

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json=_stub_response(model="claude-sonnet-4-6"))
        )
        client.call_messages(user_content="x")

    sent = route.calls.last.request
    import json as _json

    body = _json.loads(sent.content)
    assert body["model"] == "claude-sonnet-4-6"
    assert body["thinking"] == {"type": "adaptive"}
    # Top-level cache_control survives the SDK serialization.
    assert body["cache_control"] == {"type": "ephemeral"}


def test_supports_effort_flag() -> None:
    opus = ClaudeClient(_config(model="claude-opus-4-7"), system_prompt="x")
    sonnet = ClaudeClient(_config(model="claude-sonnet-4-6"), system_prompt="x")
    haiku = ClaudeClient(_config(model="claude-haiku-4-5"), system_prompt="x")
    assert opus.supports_effort()
    assert sonnet.supports_effort()
    assert not haiku.supports_effort()


def test_call_messages_propagates_rate_limit() -> None:
    """Anthropic SDK maps 429 → ``anthropic.RateLimitError``; surface it untouched."""
    sdk = anthropic.Anthropic(api_key="test-key-ignored", max_retries=0)
    client = ClaudeClient(_config(), system_prompt="x", sdk=sdk)

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                429,
                json={
                    "type": "error",
                    "error": {"type": "rate_limit_error", "message": "slow down"},
                },
            )
        )
        with pytest.raises(anthropic.RateLimitError):
            client.call_messages(user_content="x")


# ---------------------------------------------------------------------------
# Tools kwarg (PR 2)
# ---------------------------------------------------------------------------


def test_build_request_includes_tools_when_provided() -> None:
    client = ClaudeClient(_config(), system_prompt="x")
    tools = [{"name": "create_finding", "description": "…", "input_schema": {"type": "object"}}]
    body = client.build_request(user_content="x", tools=tools)
    assert body["tools"] == tools


def test_build_request_omits_tools_when_none() -> None:
    client = ClaudeClient(_config(), system_prompt="x")
    body = client.build_request(user_content="x")
    assert "tools" not in body, "empty tool list must not appear in body"


def test_build_request_omits_tools_when_empty_list() -> None:
    client = ClaudeClient(_config(), system_prompt="x")
    body = client.build_request(user_content="x", tools=[])
    assert "tools" not in body


def test_call_messages_forwards_tools_to_sdk() -> None:
    sdk = anthropic.Anthropic(api_key="test-key-ignored", max_retries=0)
    client = ClaudeClient(_config(), system_prompt="x", sdk=sdk)
    tools = [{"name": "create_finding", "description": "…", "input_schema": {"type": "object"}}]

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json=_stub_response())
        )
        client.call_messages(user_content="x", tools=tools)

    import json as _json

    sent = _json.loads(route.calls.last.request.content)
    assert sent["tools"] == tools
