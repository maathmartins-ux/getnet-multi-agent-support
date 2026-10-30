"""Router Agent (FR-002): language detection, deterministic intent classification, plan and confidence."""

from __future__ import annotations

import pytest

from getnet_agents.agents.router import PLANS, RouterAgent, detect_language, heuristic_route
from getnet_agents.llm import LLMError, OfflineLLM
from getnet_agents.schemas import AgentName, Intent, RouteDecision


@pytest.mark.parametrize("text,lang", [
    ("Quando o dinheiro das minhas vendas de ontem vai cair?", "pt"),
    ("Como funciona a antecipação de recebíveis?", "pt"),
    ("When will the money from yesterday's sales be deposited?", "en"),
    ("What's the difference between the Get Clássica and the Get Smart?", "en"),
    ("My card machine won't connect to the internet, what should I do?", "en"),
])
def test_detect_language(text, lang):
    """FR-002 / NFR-005: the router detects pt vs en so downstream agents answer in the user's language."""
    assert detect_language(text) == lang


@pytest.mark.parametrize("text,intent", [
    ("What's the difference between the Get Clássica and the Get Smart?", Intent.GETNET_PRODUCT),
    ("How does receivables advance (antecipação) work with Getnet?", Intent.GETNET_PRODUCT),
    ("Quais são as taxas do Pix na maquininha?", Intent.GETNET_PRODUCT),
    ("What's the weather forecast in Porto Alegre tomorrow?", Intent.GENERAL_WEB),
    ("Qual a cotação do dólar hoje?", Intent.GENERAL_WEB),
    ("When will the money from yesterday's sales be deposited?", Intent.ACCOUNT),
    ("Quando cai o repasse das vendas de ontem?", Intent.ACCOUNT),
    ("My card machine won't connect to the internet, what should I do?", Intent.DEVICE_ISSUE),
    ("Minha maquininha não conecta na internet", Intent.DEVICE_ISSUE),
    ("Quero falar com um atendente humano", Intent.HUMAN_REQUEST),
    ("I want to talk to a real person", Intent.HUMAN_REQUEST),
    ("Can you help me with my income tax return?", Intent.UNSUPPORTED),
])
def test_heuristic_intents(text, intent):
    """FR-002: the deterministic classifier assigns the expected intent to representative messages."""
    decision = heuristic_route(text)
    assert decision.intent == intent
    assert decision.plan == PLANS[intent]
    assert decision.source == "heuristic"
    assert 0.0 <= decision.confidence <= 1.0


def test_plans_are_ordered_agent_sequences():
    """FR-002 / FR-006: every intent maps to an ordered plan; device issues run support then knowledge."""
    assert PLANS[Intent.DEVICE_ISSUE] == [AgentName.SUPPORT, AgentName.KNOWLEDGE]
    assert PLANS[Intent.HUMAN_REQUEST] == [AgentName.ESCALATION]
    assert PLANS[Intent.GETNET_PRODUCT] == [AgentName.KNOWLEDGE]
    assert set(PLANS) == set(Intent)


def test_getnet_keywords_beat_general_keywords():
    """FR-002: a question mentioning Getnet products is never sent to web search even if it has general words."""
    decision = heuristic_route("Qual a taxa de câmbio aplicada pela Getnet em vendas internacionais?")
    assert decision.intent != Intent.GENERAL_WEB


def test_unclassifiable_message_has_low_confidence():
    """BR-003: a message the heuristic cannot classify gets confidence below the handoff threshold."""
    decision = heuristic_route("asdf qwerty zzz")
    assert decision.intent == Intent.UNSUPPORTED
    assert decision.confidence < 0.55
    assert decision.plan == [AgentName.ESCALATION]


def test_router_agent_offline_uses_heuristic():
    """FR-002 / NFR-001: with the offline LLM the RouterAgent returns the heuristic decision, no fallback."""
    agent = RouterAgent(OfflineLLM())
    decision, fallback = agent.decide("Quando cai o repasse das vendas de ontem?")
    assert isinstance(decision, RouteDecision)
    assert fallback is False
    assert decision.source == "heuristic"
    assert decision.intent == Intent.ACCOUNT


class _BrokenLLM:
    name, offline, model = "broken", False, "fake"

    def complete(self, *a, **k):
        raise LLMError("boom")

    def complete_json(self, *a, **k):
        raise LLMError("boom")

    def run_tools(self, *a, **k):
        raise LLMError("boom")


class _GarbageLLM(_BrokenLLM):
    def complete_json(self, *a, **k):
        return {"intent": "not_an_intent"}


class _GoodLLM(_BrokenLLM):
    def complete_json(self, *a, **k):
        return {"intent": "account", "plan": ["support"], "confidence": 0.91, "reason": "ok", "language": "en"}


def test_router_falls_back_when_llm_fails():
    """NFR-002: an LLM failure degrades to the heuristic and is reported as a fallback."""
    decision, fallback = RouterAgent(_BrokenLLM()).decide("Quando cai o repasse das vendas de ontem?")
    assert fallback is True
    assert decision.source == "heuristic" and decision.intent == Intent.ACCOUNT


def test_router_falls_back_on_invalid_llm_json():
    """NFR-002: an LLM reply that violates the contract (unknown intent) also falls back to the heuristic."""
    decision, fallback = RouterAgent(_GarbageLLM()).decide("Quando cai o repasse das vendas de ontem?")
    assert fallback is True and decision.source == "heuristic"


def test_router_uses_llm_decision_when_valid():
    """FR-002: a valid LLM JSON becomes the route with source `llm`."""
    decision, fallback = RouterAgent(_GoodLLM()).decide("When will I get my money?")
    assert fallback is False
    assert decision.source == "llm" and decision.intent == Intent.ACCOUNT
    assert decision.plan == [AgentName.SUPPORT] and decision.confidence == 0.91 and decision.language == "en"


def test_router_handle_returns_route_in_data():
    """FR-006: RouterAgent.handle wraps the decision in AgentResult.data['route'] for the orchestrator."""
    from tests.conftest import make_msg

    res = RouterAgent(OfflineLLM()).handle(make_msg("Quero falar com um atendente"))
    assert res.agent == AgentName.ROUTER
    assert isinstance(res.data["route"], RouteDecision)
    assert res.data["route"].intent == Intent.HUMAN_REQUEST
