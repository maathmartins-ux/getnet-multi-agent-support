"""Contracts shared by the API, the orchestrator and the agents (spec: data-model.md)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentName(StrEnum):
    ROUTER = "router"
    KNOWLEDGE = "knowledge"
    SUPPORT = "support"
    ESCALATION = "escalation"


class Intent(StrEnum):
    GETNET_PRODUCT = "getnet_product"  # answer from the Getnet knowledge base (RAG)
    GENERAL_WEB = "general_web"  # general-purpose question -> web search
    ACCOUNT = "account"  # needs customer data (settlement, transactions, profile)
    DEVICE_ISSUE = "device_issue"  # card machine problem -> device status + troubleshooting
    HUMAN_REQUEST = "human_request"  # user explicitly asks for a human
    UNSUPPORTED = "unsupported"  # outside scope / cannot be resolved -> handoff


# ----------------------------------------------------------------------------- API


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, examples=["How does Pix work with Getnet?"])
    user_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$", examples=["cliente1988"])


class RouteDecision(BaseModel):
    plan: list[AgentName]
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    language: Literal["pt", "en"] = "pt"
    source: Literal["llm", "heuristic"] = "heuristic"


class Source(BaseModel):
    title: str
    url: str | None = None
    score: float = 0.0
    snippet: str = ""
    kind: Literal["knowledge_base", "web"] = "knowledge_base"


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    duration_ms: float = 0.0


class Handoff(BaseModel):
    ticket_id: str
    queue: str
    priority: Literal["low", "normal", "high"] = "normal"
    reason: str
    status: str = "open"
    notified: bool = False


class GuardrailReport(BaseModel):
    input_flags: list[str] = Field(default_factory=list)
    output_flags: list[str] = Field(default_factory=list)
    blocked: bool = False
    masked: bool = False


class TraceStep(BaseModel):
    agent: str
    action: str
    duration_ms: float
    detail: dict[str, Any] = Field(default_factory=dict)


# ----------------------------------------------------------------------------- inter-agent contract


class AgentResult(BaseModel):
    agent: AgentName
    answer: str = ""
    sources: list[Source] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    handoff: Handoff | None = None
    confidence: float = 1.0
    needs_escalation: bool = False
    escalation_reason: str = ""
    data: dict[str, Any] = Field(default_factory=dict)  # merged into AgentMessage.context for the next agent
    llm_fallback: bool = False  # True when the LLM failed and the deterministic path was used


class AgentMessage(BaseModel):
    """Envelope passed from the orchestrator to each agent (FR-006)."""

    request_id: str
    user_id: str
    text: str
    language: Literal["pt", "en"] = "pt"
    route: RouteDecision | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    history: list[AgentResult] = Field(default_factory=list)


class ChatResponse(BaseModel):
    request_id: str
    user_id: str
    answer: str
    route: RouteDecision | None
    agents_involved: list[str]
    sources: list[Source]
    tools_used: list[str]
    handoff: Handoff | None
    guardrails: GuardrailReport
    trace: list[TraceStep]
    latency_ms: float
    mode: str
    model: str | None = None
