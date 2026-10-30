"""Individual agents in offline mode (FR-003, FR-004, FR-005, FR-007, BR-001, NFR-005)."""

from __future__ import annotations

import httpx
import pytest

from getnet_agents.agents.escalation import EscalationAgent
from getnet_agents.agents.knowledge import KnowledgeAgent
from getnet_agents.agents.router import heuristic_route
from getnet_agents.agents.support import SupportAgent, fmt_brl, fmt_date
from getnet_agents.llm import OfflineLLM
from getnet_agents.schemas import AgentName, Intent, RouteDecision
from getnet_agents.tools.web_search import WebResult
from tests.conftest import USER, make_msg

WEB_RESULTS = [WebResult(title="Previsão Porto Alegre", url="https://example.com/wx", snippet="Amanhã 24°C, 40% chuva."),
               WebResult(title="Euro hoje", url="https://example.com/eur", snippet="EUR R$ 6,06.")]


def _knowledge(orchestrator) -> KnowledgeAgent:
    return orchestrator.agents[AgentName.KNOWLEDGE]


# ----------------------------------------------------------------------------- Knowledge Agent


def test_knowledge_rag_answers_with_sources(orchestrator):
    """FR-003: Getnet questions are answered extractively from the corpus, citing sources."""
    res = _knowledge(orchestrator).handle(make_msg("What's the difference between the Get Clássica and the Get Smart?"))
    assert res.agent == AgentName.KNOWLEDGE
    assert res.sources and all(s.kind == "knowledge_base" and s.url for s in res.sources)
    assert res.needs_escalation is False and res.tool_calls == []
    assert "Based on official Getnet content" in res.answer and "Sources" in res.answer
    assert any("Get Smart" in s.title or "Get Smart" in s.snippet for s in res.sources)


def test_knowledge_answers_in_portuguese(orchestrator):
    """NFR-005: Portuguese questions get the Portuguese extractive template."""
    res = _knowledge(orchestrator).handle(make_msg("Como funciona a antecipação de recebíveis na Getnet?"))
    assert res.answer.startswith("Com base no conteúdo oficial da Getnet")
    assert "Fontes:" in res.answer


def test_knowledge_no_hits_requests_escalation(orchestrator):
    """BR-003: when retrieval finds nothing the agent asks for a handoff instead of inventing an answer."""
    route = RouteDecision(plan=[AgentName.KNOWLEDGE], intent=Intent.GETNET_PRODUCT, confidence=0.8, language="pt")
    res = _knowledge(orchestrator).handle(make_msg("xyzzy plugh", route=route))
    assert res.needs_escalation is True and res.escalation_reason == "no_knowledge"
    assert res.sources == [] and res.confidence < 0.5
    assert "Não encontrei" in res.answer


def test_knowledge_general_web_search(orchestrator, monkeypatch):
    """FR-004: general questions go through the web-search tool and cite web sources."""
    agent = _knowledge(orchestrator)
    monkeypatch.setattr(agent.web, "search", lambda query, max_results=5: WEB_RESULTS)
    if hasattr(agent, "general"):  # structured tools would short-circuit the plain search path
        monkeypatch.setattr(agent.general, "weather_forecast", lambda city: None, raising=False)
        monkeypatch.setattr(agent.general, "exchange_rate", lambda base, quote="BRL": None, raising=False)
    res = agent.handle(make_msg("What's the weather forecast in Porto Alegre tomorrow?"))
    assert "web_search" in [c.name for c in res.tool_calls]
    assert res.sources and all(s.kind == "web" for s in res.sources)
    assert "example.com/wx" in res.answer
    assert "external content" in res.answer.lower()


def test_knowledge_general_web_unavailable(orchestrator, monkeypatch):
    """FR-004 / NFR-002: when search returns nothing the agent says so honestly (no fabricated answer)."""
    agent = _knowledge(orchestrator)
    monkeypatch.setattr(agent.web, "search", lambda query, max_results=5: [])
    if hasattr(agent, "general"):
        monkeypatch.setattr(agent.general, "exchange_rate", lambda base, quote="BRL": None, raising=False)
        monkeypatch.setattr(agent.general, "weather_forecast", lambda city: None, raising=False)
    res = agent.handle(make_msg("What's the euro exchange rate today?"))
    assert res.sources == [] and res.confidence <= 0.5
    assert "could not reach the web" in res.answer
    assert [c.name for c in res.tool_calls] == ["web_search"]


def test_knowledge_weather_tool(orchestrator, monkeypatch):
    """FR-004: scenario 2 uses the structured weather tool when it returns data."""
    agent = _knowledge(orchestrator)
    if not hasattr(agent, "general"):
        pytest.xfail("KnowledgeAgent.general (GeneralTools) not wired yet")
    monkeypatch.setattr(agent.web, "search", lambda query, max_results=5: WEB_RESULTS)
    monkeypatch.setattr(agent.general, "weather_forecast", lambda city: {
        "city": "Porto Alegre", "country": "Brasil", "source": "Open-Meteo",
        "days": [{"date": "2026-10-31", "tmax": 24.1, "tmin": 15.0, "precip_prob": 40}]})
    res = agent.handle(make_msg("What's the weather forecast in Porto Alegre tomorrow?"))
    assert "weather_forecast" in [c.name for c in res.tool_calls]
    assert "Porto Alegre" in res.answer


def test_knowledge_exchange_rate_tool_and_fallback(orchestrator, monkeypatch):
    """FR-004: scenario 7 uses the exchange-rate tool; when it returns None, web search is the fallback."""
    agent = _knowledge(orchestrator)
    if not hasattr(agent, "general"):
        pytest.xfail("KnowledgeAgent.general (GeneralTools) not wired yet")
    monkeypatch.setattr(agent.web, "search", lambda query, max_results=5: WEB_RESULTS)
    monkeypatch.setattr(agent.general, "exchange_rate", lambda base, quote="BRL": {
        "pair": "EUR-BRL", "bid": 6.06, "ask": 6.07, "timestamp": "2026-10-30T13:21:00", "source": "AwesomeAPI"})
    res = agent.handle(make_msg("What's the euro exchange rate today?"))
    assert "exchange_rate" in [c.name for c in res.tool_calls]
    assert "6,06" in res.answer or "6.06" in res.answer

    monkeypatch.setattr(agent.general, "exchange_rate", lambda base, quote="BRL": None)
    res = agent.handle(make_msg("What's the euro exchange rate today?"))
    assert "web_search" in [c.name for c in res.tool_calls]


# ----------------------------------------------------------------------------- Support Agent


def test_support_unknown_user_escalates_without_inventing(crm):
    """FR-007: unknown user_id -> explanation + escalation request, no data fabricated."""
    agent = SupportAgent(OfflineLLM(), crm)
    res = agent.handle(make_msg("When will the money from yesterday's sales be deposited?", user_id="ghost"))
    assert res.needs_escalation is True and res.escalation_reason == "customer_not_found"
    assert [c.name for c in res.tool_calls] == ["get_customer_profile"]
    assert res.data == {"customer": None}
    assert "could not find" in res.answer.lower()
    assert "R$" not in res.answer


def test_support_settlement_forecast_for_yesterday(crm):
    """FR-005: account questions call the settlement tool and render only yesterday's sales when asked."""
    agent = SupportAgent(OfflineLLM(), crm)
    res = agent.handle(make_msg("When will the money from yesterday's sales be deposited?"))
    assert [c.name for c in res.tool_calls] == ["get_customer_profile", "get_settlement_forecast"]
    assert res.answer.startswith("Hi Maria!")
    assert "29/10/2026" in res.answer and "28/10/2026" not in res.answer
    assert "30/11/2026" in res.answer  # credit D+30 rolled to Monday
    assert "anticipation" in res.answer.lower()  # upsell tip for merchants without anticipation
    assert res.data["settlement"]["user_id"] == USER and res.data["customer"]["name"] == "Maria Oliveira"


def test_support_device_issue_opens_ticket_when_offline(crm):
    """FR-005: device issues check the terminal and open a technical ticket when it is unhealthy."""
    agent = SupportAgent(OfflineLLM(), crm)
    res = agent.handle(make_msg("My card machine won't connect to the internet, what should I do?"))
    names = [c.name for c in res.tool_calls]
    assert "get_device_status" in names and "open_support_ticket" in names
    assert res.data["device"]["status"] == "offline"
    assert res.data["ticket"]["ticket_id"].startswith("GN-") and res.data["ticket"]["category"] == "device"
    assert "NETWORK_TIMEOUT" in res.answer and res.data["ticket"]["ticket_id"] in res.answer


def test_support_device_online_no_ticket(crm):
    """FR-005: a healthy device is reported without opening a ticket."""
    agent = SupportAgent(OfflineLLM(), crm)
    res = agent.handle(make_msg("Minha maquininha não conecta na internet", user_id="cliente2042"))
    assert "open_support_ticket" not in [c.name for c in res.tool_calls]
    assert res.data["ticket"] is None and res.data["device"]["status"] == "online"
    assert "Get Smart" in res.answer and res.answer.startswith("Verifiquei")


def test_support_formatters():
    """FR-005: dates and amounts are rendered in Brazilian format."""
    assert fmt_date("2026-11-30") == "30/11/2026"
    assert fmt_brl(1200.0) == "R$ 1.200,00"
    assert fmt_brl(89.9) == "R$ 89,90"


# ----------------------------------------------------------------------------- Escalation Agent


def _escalation(crm, **kw) -> EscalationAgent:
    return EscalationAgent(OfflineLLM(), crm, **kw)


def test_escalation_opens_ticket_and_returns_handoff(crm):
    """BR-001: explicit human request -> ticket in the human queue, handoff payload, protocol in the answer."""
    res = _escalation(crm).handle(make_msg("Quero falar com um atendente humano"))
    assert res.handoff is not None
    assert res.handoff.queue == "human_support" and res.handoff.priority == "normal"
    assert res.handoff.reason == "human_request" and res.handoff.notified is False
    assert [c.name for c in res.tool_calls] == ["open_support_ticket"]
    assert res.handoff.ticket_id in res.answer and "atendente" in res.answer
    assert crm.tickets[-1]["ticket_id"] == res.handoff.ticket_id


def test_escalation_high_priority_for_fraud(crm):
    """BR-001: fraud keywords raise priority to high and use the fraud category."""
    res = _escalation(crm).handle(make_msg("Quero falar com um atendente, sofri uma fraude na maquininha"))
    assert res.handoff.priority == "high"
    assert crm.tickets[-1]["category"] == "fraud"
    assert "2 horas" in res.answer


def test_escalation_customer_not_found_queue(crm):
    """FR-007 / BR-001: customer_not_found reason routes to the account verification queue."""
    res = _escalation(crm).handle(make_msg("Where is my money?", user_id="ghost",
                                           context={"escalation_reason": "customer_not_found"}))
    assert res.handoff.queue == "account_verification" and res.handoff.reason == "customer_not_found"
    assert "could not locate your registration" in res.answer


def test_escalation_webhook_notifies(crm):
    """BR-001: with a webhook configured a MessageCard is posted and `notified` reflects the HTTP outcome."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["body"] = req.read().decode()
        return httpx.Response(200)

    agent = _escalation(crm, webhook_url="https://hooks.example.com/teams",
                        client=httpx.Client(transport=httpx.MockTransport(handler)))
    res = agent.handle(make_msg("I want to talk to a real person"))
    assert res.handoff.notified is True
    assert seen["url"] == "https://hooks.example.com/teams" and "MessageCard" in seen["body"]
    assert [c.name for c in res.tool_calls] == ["open_support_ticket", "notify_human_channel"]


def test_escalation_webhook_failure_never_raises(crm):
    """NFR-002: webhook errors are logged, the handoff still happens with notified=False."""
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    agent = _escalation(crm, webhook_url="https://hooks.example.com/teams",
                        client=httpx.Client(transport=httpx.MockTransport(boom)))
    res = agent.handle(make_msg("I want to talk to a real person"))
    assert res.handoff is not None and res.handoff.notified is False


def test_escalation_reason_for_unclassified(crm):
    """BR-003: low-confidence routing yields the low_confidence explanation."""
    route = heuristic_route("asdf qwerty zzz")
    res = _escalation(crm).handle(make_msg("asdf qwerty zzz", route=route, context={"escalation_reason": "low_confidence"}))
    assert res.handoff.reason == "low_confidence"
    assert "não consegui identificar" in res.answer
