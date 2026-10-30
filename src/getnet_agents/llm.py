"""LLM abstraction.

`LLM` is the only interface agents see. Two implementations:
- `AnthropicLLM`  – Claude via the official SDK, with timeout, bounded retries and a tool-use loop.
- `OfflineLLM`    – no network; agents detect `llm.offline` and take their deterministic path.

Every agent wraps LLM calls in try/except and falls back to its deterministic path (NFR-002), so an
outage degrades quality but never availability.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .schemas import ToolCall

log = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_anthropic(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


@dataclass
class ToolRunResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMError(RuntimeError):
    """Raised when the provider fails after retries; agents catch it and degrade."""


class LLM(Protocol):
    name: str
    offline: bool
    model: str | None

    def complete(self, system: str, user: str, *, max_tokens: int = 800, temperature: float = 0.2,
                 model: str | None = None) -> str: ...

    def complete_json(self, system: str, user: str, *, model: str | None = None,
                      max_tokens: int = 800) -> dict[str, Any]: ...

    def run_tools(self, system: str, user: str, tools: list[ToolSpec],
                  handlers: dict[str, Callable[..., Any]], *, max_turns: int = 5,
                  max_tokens: int = 1000) -> ToolRunResult: ...


_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def extract_json(text: str) -> dict[str, Any]:
    """Parse the first JSON object in a model reply (tolerates ```json fences and prose around it)."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.S)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(cleaned)
        if not match:
            raise LLMError(f"no JSON object in reply: {text[:120]!r}")
        return json.loads(match.group(0))


class OfflineLLM:
    """Deterministic stand-in: agents never call it for generation, they branch on `.offline`."""

    name = "offline"
    offline = True
    model = None

    def complete(self, system: str, user: str, **_: Any) -> str:
        raise LLMError("offline mode: no LLM available")

    def complete_json(self, system: str, user: str, **_: Any) -> dict[str, Any]:
        raise LLMError("offline mode: no LLM available")

    def run_tools(self, system: str, user: str, tools: list[ToolSpec],
                  handlers: dict[str, Callable[..., Any]], **_: Any) -> ToolRunResult:
        raise LLMError("offline mode: no LLM available")


class AnthropicLLM:
    name = "anthropic"
    offline = False

    def __init__(self, api_key: str, model: str, *, timeout_s: float = 30.0, max_retries: int = 2) -> None:
        import anthropic  # imported lazily so offline mode never needs the SDK configured

        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=max_retries)
        self.model = model

    # -- plain completion -------------------------------------------------------------------------
    def complete(self, system: str, user: str, *, max_tokens: int = 800, temperature: float = 0.2,
                 model: str | None = None) -> str:
        try:
            resp = self._client.messages.create(
                model=model or self.model, system=system, max_tokens=max_tokens, temperature=temperature,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # noqa: BLE001 - any SDK/network error degrades the same way
            raise LLMError(str(exc)) from exc
        return "".join(getattr(b, "text", "") for b in resp.content).strip()

    def complete_json(self, system: str, user: str, *, model: str | None = None,
                      max_tokens: int = 800) -> dict[str, Any]:
        text = self.complete(system + "\n\nReply with a single JSON object and nothing else.", user,
                             max_tokens=max_tokens, temperature=0.0, model=model)
        return extract_json(text)

    # -- tool-use loop ----------------------------------------------------------------------------
    def run_tools(self, system: str, user: str, tools: list[ToolSpec],
                  handlers: dict[str, Callable[..., Any]], *, max_turns: int = 5,
                  max_tokens: int = 1000) -> ToolRunResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        calls: list[ToolCall] = []
        for _ in range(max_turns):
            try:
                resp = self._client.messages.create(
                    model=self.model, system=system, max_tokens=max_tokens, temperature=0.1,
                    tools=[t.to_anthropic() for t in tools], messages=messages,
                )
            except Exception as exc:  # noqa: BLE001
                raise LLMError(str(exc)) from exc
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                text = "".join(getattr(b, "text", "") for b in resp.content).strip()
                return ToolRunResult(text=text, tool_calls=calls)
            results: list[dict[str, Any]] = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                t0 = time.perf_counter()
                handler = handlers.get(block.name)
                try:
                    output = handler(**block.input) if handler else {"error": f"unknown tool {block.name}"}
                except Exception as exc:  # noqa: BLE001 - tool errors are reported to the model, not raised
                    output = {"error": str(exc)}
                call = ToolCall(name=block.name, arguments=dict(block.input), result=output,
                                duration_ms=round((time.perf_counter() - t0) * 1000, 2))
                calls.append(call)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(output, ensure_ascii=False, default=str)})
            messages.append({"role": "user", "content": results})
        raise LLMError("tool loop exceeded max_turns")


def build_llm(provider: str, api_key: str | None, model: str, *, timeout_s: float, max_retries: int) -> LLM:
    if provider == "anthropic":
        if not api_key:
            raise ValueError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        return AnthropicLLM(api_key, model, timeout_s=timeout_s, max_retries=max_retries)
    if provider == "offline":
        return OfflineLLM()
    raise ValueError(f"unknown LLM provider: {provider}")
