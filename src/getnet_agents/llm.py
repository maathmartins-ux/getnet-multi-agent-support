"""LLM abstraction.

`LLM` is the only interface agents see. Two implementations:
- `AnthropicLLM`  – Claude via the official SDK (>= 2.3), with timeout, bounded retries and a tool-use loop.
- `OfflineLLM`    – no network; agents detect `llm.offline` and take their deterministic path.

Every agent wraps LLM calls in try/except and falls back to its deterministic path (NFR-002), so an
outage degrades quality but never availability. Degradation is visible: `llm_errors_total` and
`llm_fallbacks_total` increase and the API response reports `mode: "<provider>-fallback"`.

API notes (anthropic-version 2026-10-21, SDK 2.x): sampling parameters (`temperature`, `top_p`, `top_k`)
are rejected, adaptive thinking is on by default and consumes `max_tokens`, depth is controlled with
`output_config.effort`, forced `tool_choice` is not supported (we use `auto` + prompt), and
`stop_reason` must be checked for `max_tokens` / `refusal` before reading content.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .observability import LLM_ERRORS
from .schemas import ToolCall

log = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 8192  # adaptive thinking shares this budget with the visible answer
JSON_MAX_TOKENS = 2048


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

    def complete(self, system: str, user: str, *, max_tokens: int = DEFAULT_MAX_TOKENS,
                 model: str | None = None, effort: str | None = None) -> str: ...

    def complete_json(self, system: str, user: str, *, model: str | None = None,
                      max_tokens: int = JSON_MAX_TOKENS, effort: str | None = None) -> dict[str, Any]: ...

    def run_tools(self, system: str, user: str, tools: list[ToolSpec],
                  handlers: dict[str, Callable[..., Any]], *, max_turns: int = 5,
                  max_tokens: int = DEFAULT_MAX_TOKENS, effort: str | None = None) -> ToolRunResult: ...


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """Parse the first JSON object in a model reply (tolerates ```json fences and prose around it)."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(cleaned)
        if not match:
            raise LLMError(f"no JSON object in reply: {text[:120]!r}") from None
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


def _text_of(resp: Any) -> str:
    return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text").strip()


def _check_stop(resp: Any) -> None:
    """Raise on stop reasons that mean the content cannot be trusted (NFR-002 -> deterministic fallback)."""
    if resp.stop_reason == "max_tokens":
        raise LLMError("response truncated (max_tokens); raise max_tokens or lower effort")
    if resp.stop_reason == "refusal":
        details = getattr(resp, "stop_details", None)
        raise LLMError(f"model refused the request ({getattr(details, 'category', None)})")


class AnthropicLLM:
    name = "anthropic"
    offline = False

    def __init__(self, api_key: str, model: str, *, timeout_s: float = 30.0, max_retries: int = 2) -> None:
        import anthropic  # imported lazily so offline mode never needs the SDK configured

        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=max_retries)
        self.model = model

    def _request(self, **kwargs: Any) -> Any:
        """Single place that talks to the SDK: builds `output_config`, counts errors, never leaks exceptions."""
        effort = kwargs.pop("effort", None)
        if effort:
            kwargs["output_config"] = {"effort": effort}
        try:
            return self._client.messages.create(**kwargs)
        except Exception as exc:
            LLM_ERRORS.labels(type(exc).__name__).inc()
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc

    # -- plain completion -------------------------------------------------------------------------
    def complete(self, system: str, user: str, *, max_tokens: int = DEFAULT_MAX_TOKENS,
                 model: str | None = None, effort: str | None = None) -> str:
        resp = self._request(model=model or self.model, system=system, max_tokens=max_tokens,
                             messages=[{"role": "user", "content": user}], effort=effort)
        _check_stop(resp)
        return _text_of(resp)

    def complete_json(self, system: str, user: str, *, model: str | None = None,
                      max_tokens: int = JSON_MAX_TOKENS, effort: str | None = None) -> dict[str, Any]:
        text = self.complete(system + "\n\nReply with a single JSON object and nothing else.", user,
                             max_tokens=max_tokens, model=model, effort=effort)
        return extract_json(text)

    # -- tool-use loop (tool_choice auto; the prompt names the tools to call) ----------------------
    def run_tools(self, system: str, user: str, tools: list[ToolSpec],
                  handlers: dict[str, Callable[..., Any]], *, max_turns: int = 5,
                  max_tokens: int = DEFAULT_MAX_TOKENS, effort: str | None = None) -> ToolRunResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        calls: list[ToolCall] = []
        for _ in range(max_turns):
            resp = self._request(model=self.model, system=system, max_tokens=max_tokens,
                                 tools=[t.to_anthropic() for t in tools], messages=messages, effort=effort)
            _check_stop(resp)
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                return ToolRunResult(text=_text_of(resp), tool_calls=calls)
            results: list[dict[str, Any]] = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                t0 = time.perf_counter()
                handler = handlers.get(block.name)
                try:
                    output = handler(**dict(block.input)) if handler else {"error": f"unknown tool {block.name}"}
                except Exception as exc:  # noqa: BLE001 - tool errors are reported to the model, not raised
                    output = {"error": str(exc)}
                calls.append(ToolCall(name=block.name, arguments=dict(block.input), result=output,
                                      duration_ms=round((time.perf_counter() - t0) * 1000, 2)))
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(output, ensure_ascii=False, default=str),
                                "is_error": isinstance(output, dict) and "error" in output})
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
