"""Human Escalation Agent (BR-001, BR-003): opens a ticket, notifies a webhook, returns a handoff."""

from __future__ import annotations

import logging
import time

import httpx

from ..llm import LLMError
from ..observability import HANDOFFS
from ..schemas import AgentMessage, AgentName, AgentResult, Handoff, Intent, ToolCall
from ..tools.crm import CRM
from .base import BaseAgent

log = logging.getLogger(__name__)

HIGH_PRIORITY_KW = ["fraud", "fraude", "golpe", "scam", "stolen", "roub", "chargeback", "urgent", "urgente", "hack"]
SLA = {"high": {"pt": "até 2 horas úteis", "en": "within 2 business hours"},
       "normal": {"pt": "até 1 dia útil", "en": "within 1 business day"},
       "low": {"pt": "até 2 dias úteis", "en": "within 2 business days"}}
REASON_TEXT = {
    "pt": {"low_confidence": "não consegui identificar com segurança o que você precisa",
           "no_knowledge": "não encontrei a resposta na base oficial",
           "low_groundedness": "não encontrei uma resposta confiável na base oficial",
           "customer_not_found": "não localizei seu cadastro",
           "human_request": "você pediu para falar com um atendente",
           "unsupported": "esse assunto está fora do que consigo resolver por aqui"},
    "en": {"low_confidence": "I could not confidently identify what you need",
           "no_knowledge": "I could not find the answer in the official knowledge base",
           "low_groundedness": "I could not find a reliable answer in the official knowledge base",
           "customer_not_found": "I could not locate your registration",
           "human_request": "you asked to speak with a human agent",
           "unsupported": "this topic is outside what I can resolve here"},
}


class EscalationAgent(BaseAgent):
    name = AgentName.ESCALATION

    def __init__(self, llm, crm: CRM, *, webhook_url: str | None = None,
                 client: httpx.Client | None = None) -> None:
        super().__init__(llm)
        self.crm = crm
        self.webhook_url = webhook_url
        self._client = client or httpx.Client(timeout=5.0)

    def handle(self, msg: AgentMessage) -> AgentResult:
        lang = msg.language
        reason = msg.context.get("escalation_reason") or (msg.route.intent.value if msg.route else "unknown")
        if reason == Intent.HUMAN_REQUEST.value:
            reason = "human_request"
        low = msg.text.lower()
        priority = "high" if any(k in low for k in HIGH_PRIORITY_KW) else "normal"
        queue = "account_verification" if reason == "customer_not_found" else "human_support"
        category = "fraud" if priority == "high" else "other"

        t0 = time.perf_counter()
        ticket = self.crm.open_support_ticket(msg.user_id, category=category, summary=msg.text,
                                              priority=priority, queue=queue)
        calls = [ToolCall(name="open_support_ticket", arguments={"category": category, "priority": priority, "queue": queue},
                          result=ticket, duration_ms=round((time.perf_counter() - t0) * 1000, 2))]
        notified = self._notify(ticket, msg, reason)
        if self.webhook_url:
            calls.append(ToolCall(name="notify_human_channel", arguments={"webhook": "configured"}, result={"notified": notified}))
        HANDOFFS.labels(reason).inc()

        handoff = Handoff(ticket_id=ticket["ticket_id"], queue=queue, priority=priority, reason=reason, notified=notified)
        answer = self._template(msg, handoff, reason)
        if not self.llm.offline:
            try:
                answer = self.llm.complete(self.system_prompt, f"language: {lang}\nuser message: {msg.text}\n"
                                           f"reason: {reason}\nprotocol: {handoff.ticket_id}\nqueue: {queue}\n"
                                           f"priority: {priority}\nexpected response: {SLA[priority][lang]}", max_tokens=200) or answer
            except LLMError:
                pass
        return AgentResult(agent=self.name, answer=answer, handoff=handoff, tool_calls=calls, confidence=1.0,
                           data={"ticket": ticket})

    def _template(self, msg: AgentMessage, h: Handoff, reason: str) -> str:
        lang = msg.language
        why = REASON_TEXT[lang].get(reason, REASON_TEXT[lang]["low_confidence"])
        if lang == "pt":
            return (f"Como {why}, encaminhei seu atendimento para um especialista humano. "
                    f"Protocolo **{h.ticket_id}** (fila {h.queue}, prioridade {h.priority}); retorno previsto {SLA[h.priority]['pt']}."
                    + (" Para casos urgentes, use também os canais oficiais da Getnet." if h.priority == "high" else ""))
        return (f"Since {why}, I have forwarded your request to a human specialist. "
                f"Protocol **{h.ticket_id}** (queue {h.queue}, priority {h.priority}); expected response {SLA[h.priority]['en']}."
                + (" For urgent cases, please also use the official Getnet channels." if h.priority == "high" else ""))

    def _notify(self, ticket: dict, msg: AgentMessage, reason: str) -> bool:
        """Best-effort Teams/Slack-style webhook (MessageCard). Never raises."""
        if not self.webhook_url:
            return False
        card = {"@type": "MessageCard", "@context": "https://schema.org/extensions",
                "summary": f"Handoff {ticket['ticket_id']}", "themeColor": "D7000F",
                "title": f"Human handoff needed — {ticket['ticket_id']} ({ticket['priority']})",
                "sections": [{"facts": [{"name": "user_id", "value": msg.user_id}, {"name": "reason", "value": reason},
                                        {"name": "request_id", "value": msg.request_id}],
                              "text": msg.text[:500]}]}
        try:
            resp = self._client.post(self.webhook_url, json=card)
            return resp.status_code < 300
        except Exception as exc:  # noqa: BLE001
            log.warning("handoff webhook failed", extra={"extra_fields": {"error": str(exc)}})
            return False
