"""NFR-002 contract tests for the Anthropic client — run without a key or network.

A spy replaces `client.messages.create` and validates every kwarg against the *installed* SDK signature,
so a parameter the SDK removed (e.g. `temperature`, gone in anthropic 2.x and rejected by the
2026-10-21 API on every model) fails here instead of silently degrading to offline mode in production.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import anthropic
import pytest

from getnet_agents.llm import AnthropicLLM, LLMError, ToolSpec

FORBIDDEN = {"temperature", "top_p", "top_k"}


def _fake_response(text: str = "ok", stop_reason: str = "end_turn", content: list | None = None) -> Any:
    blocks = content if content is not None else [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, stop_details=None)


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> tuple[AnthropicLLM, list[dict[str, Any]]]:
    client = AnthropicLLM("sk-test", "claude-opus-5-5", timeout_s=1, max_retries=0)
    seen: list[dict[str, Any]] = []
    signature = inspect.signature(anthropic.resources.messages.Messages.create)

    def spy(**kwargs: Any) -> Any:
        signature.bind(client._client.messages, **kwargs)  # raises TypeError on unknown kwargs
        assert not FORBIDDEN & kwargs.keys(), f"sampling params are rejected by the API: {FORBIDDEN & kwargs.keys()}"
        seen.append(kwargs)
        return spy.next_response.pop(0) if spy.next_response else _fake_response()

    spy.next_response = []
    monkeypatch.setattr(client._client.messages, "create", spy)
    return client, seen


def test_complete_sends_only_supported_kwargs(llm) -> None:
    client, seen = llm
    assert client.complete("sys", "hi", effort="low") == "ok"
    assert seen[0]["output_config"] == {"effort": "low"}
    assert seen[0]["model"] == "claude-opus-5-5" and seen[0]["max_tokens"] > 0


def test_complete_json_parses_fenced_json(llm) -> None:
    client, _ = llm
    client._client.messages.create.next_response.append(_fake_response('```json\n{"intent": "account"}\n```'))
    assert client.complete_json("sys", "msg") == {"intent": "account"}


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
def test_bad_stop_reasons_raise_llm_error(llm, stop_reason: str) -> None:
    client, _ = llm
    client._client.messages.create.next_response.append(_fake_response("partial", stop_reason=stop_reason))
    with pytest.raises(LLMError):
        client.complete("sys", "hi")


def test_run_tools_executes_handler_and_returns_text(llm) -> None:
    client, seen = llm
    tool_use = SimpleNamespace(type="tool_use", id="tu_1", name="get_device_status", input={})
    client._client.messages.create.next_response += [
        _fake_response(stop_reason="tool_use", content=[tool_use]),
        _fake_response("device is offline"),
    ]
    tools = [ToolSpec("get_device_status", "status", {"type": "object", "properties": {}})]
    result = client.run_tools("sys", "msg", tools, {"get_device_status": lambda **_: {"status": "offline"}})
    assert result.text == "device is offline"
    assert [c.name for c in result.tool_calls] == ["get_device_status"]
    tool_result_turn = seen[1]["messages"][2]  # user -> assistant(tool_use) -> user(tool_result) -> assistant(text)
    assert tool_result_turn["role"] == "user" and tool_result_turn["content"][0]["type"] == "tool_result"
    assert "tool_choice" not in seen[0]  # forced tool_choice is rejected on current models; we rely on auto


def test_sdk_errors_become_llm_error(llm) -> None:
    client, _ = llm

    def boom(**_: Any) -> Any:
        raise anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]

    client._client.messages.create = boom
    with pytest.raises(LLMError):
        client.complete("sys", "hi")
