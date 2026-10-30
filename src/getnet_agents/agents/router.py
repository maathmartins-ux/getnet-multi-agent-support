"""Router Agent (FR-002): single entry point; classifies the message and plans the agent sequence.

Two classifiers:
- LLM (Claude Haiku by default) with a JSON contract — primary when a key is configured.
- Deterministic keyword heuristic — used offline and as the fallback when the LLM fails/returns garbage.
The heuristic is also the reference used by the eval suite, so both paths are measured.
"""

from __future__ import annotations

import re
import unicodedata

from ..llm import LLMError
from ..schemas import AgentMessage, AgentName, AgentResult, Intent, RouteDecision
from .base import BaseAgent

PLANS: dict[Intent, list[AgentName]] = {
    Intent.GETNET_PRODUCT: [AgentName.KNOWLEDGE],
    Intent.GENERAL_WEB: [AgentName.KNOWLEDGE],
    Intent.ACCOUNT: [AgentName.SUPPORT],
    Intent.DEVICE_ISSUE: [AgentName.SUPPORT, AgentName.KNOWLEDGE],
    Intent.HUMAN_REQUEST: [AgentName.ESCALATION],
    Intent.UNSUPPORTED: [AgentName.ESCALATION],
}

GENERAL_KW = ["weather", "forecast", "clima", "previsao do tempo", "tempo amanha", "chover", "euro", "dolar", "dollar",
              "exchange rate", "cambio", "cotacao", "bitcoin", "news", "noticia", "capital of", "who is", "quem e",
              "temperature", "temperatura"]
STRONG_GETNET_KW = ["getnet", "maquininha", "pix", "antecipa", "crediario", "link de pagamento", "payment link",
                    "get classica", "get smart", "get mobile", "superget"]
DEVICE_KW = ["machine", "maquina", "maquininha", "terminal", "pos ", "device", "aparelho", "pinpad"]
PROBLEM_KW = ["won t", "wont", "will not", "not connect", "no connect", "connect", "conecta", "conexao", "internet",
              "wifi", "wi fi", "chip", "error", "erro", "declin", "recusa", "negad", "nao funciona", "not working",
              "travou", "frozen", "stuck", "print", "imprim", "bateria", "battery", "broken", "quebr", "offline",
              "nao liga", "turn on", "reiniciar", "reboot", "update", "atualiza"]
ACCOUNT_KW = ["deposited", "deposit", "deposito", "depositado", "when will i receive", "when will the money",
              "when do i get", "quando recebo", "quando vou receber", "quando cai", "quando entra", "repasse",
              "settlement", "balance", "saldo", "my transactions", "minhas transacoes", "minhas vendas de",
              "extrato", "statement", "invoice", "fatura", "chargeback", "estorno", "refund", "reembolso",
              "my plan", "meu plano", "meu chamado", "my ticket", "protocolo", "my account", "minha conta",
              "yesterday", "ontem", "money from"]
HUMAN_KW = ["human", "humano", "atendente", "attendant", "real person", "pessoa de verdade", "gerente", "manager",
            "falar com alguem", "talk to someone", "speak to someone", "speak with someone", "operador", "operator"]
UNSUPPORTED_KW = ["income tax", "imposto de renda", "declaracao de imposto", "lawyer", "advogado", "medical",
                  "medico", "stone ", "pagseguro", "mercado pago", "cielo", "rede ", "sumup", "write me a poem",
                  "escreva um poema", "receita de bolo"]
PRODUCT_KW = STRONG_GETNET_KW + ["card machine", "cartao", "card", "receivables", "anticipation", "installment",
                                 "parcel", "whatsapp", "taxa", "fee", "rate", "plano", "plan", "ecommerce",
                                 "e commerce", "checkout", "conta digital", "boleto", "qr code", "tap", "nfc",
                                 "contactless", "debito", "credito", "debit", "credit", "vale", "voucher",
                                 "aluguel", "rent", "price", "preco", "quanto custa", "how much", "bank account",
                                 "conta bancaria", "receber", "receive", "sell", "vender", "venda", "sale"]

PT_HINTS = {"o", "a", "os", "as", "nao", "você", "voce", "como", "quando", "minha", "meu", "é", "da", "do", "para",
            "com", "que", "qual", "quais", "posso", "preciso", "quero", "de", "em", "uma", "um", "e"}
EN_HINTS = {"the", "what", "my", "is", "can", "do", "how", "when", "will", "i", "with", "to", "does", "need", "my",
            "should", "via", "into", "through", "and", "of", "it", "for"}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", text).strip() + " "


def detect_language(text: str) -> str:
    words = re.findall(r"[a-záàâãéêíóôõúç]+", text.lower())
    pt = sum(w in PT_HINTS for w in words) + sum(ch in "ãõçêôâ" for ch in text.lower()) * 2
    en = sum(w in EN_HINTS for w in words)
    return "en" if en > pt else "pt"


def heuristic_route(text: str) -> RouteDecision:
    n = _norm(text)
    lang = detect_language(text)
    has = lambda kws: any(k in n for k in kws)  # noqa: E731

    def decision(intent: Intent, conf: float, reason: str) -> RouteDecision:
        return RouteDecision(plan=PLANS[intent], intent=intent, confidence=conf, reason=reason, language=lang,
                             source="heuristic")

    if has(HUMAN_KW) and has([" falar ", " talk ", " speak ", " quero ", " want ", " call ", " transfer ", " prefiro "]):
        return decision(Intent.HUMAN_REQUEST, 0.95, "explicit request for a human")
    if has(UNSUPPORTED_KW):
        return decision(Intent.UNSUPPORTED, 0.8, "outside Getnet support scope")
    if has(DEVICE_KW) and has(PROBLEM_KW):
        return decision(Intent.DEVICE_ISSUE, 0.9, "card machine problem: check device, then troubleshooting")
    if has(GENERAL_KW) and not has(STRONG_GETNET_KW):
        return decision(Intent.GENERAL_WEB, 0.9, "general-purpose question: web search")
    if has(ACCOUNT_KW):
        return decision(Intent.ACCOUNT, 0.85, "needs the merchant own data")
    if has(PRODUCT_KW):
        return decision(Intent.GETNET_PRODUCT, 0.8, "Getnet product/service question: knowledge base")
    return decision(Intent.UNSUPPORTED, 0.3, "could not classify the request")


class RouterAgent(BaseAgent):
    name = AgentName.ROUTER

    def __init__(self, llm, *, model: str | None = None) -> None:  # noqa: ANN001
        super().__init__(llm)
        self.model = model

    def decide(self, text: str) -> tuple[RouteDecision, bool]:
        """Returns (decision, llm_fallback)."""
        heuristic = heuristic_route(text)
        if self.llm.offline:
            return heuristic, False
        try:
            js = self.llm.complete_json(self.system_prompt, f"Message: {text}", model=self.model, max_tokens=200)
            intent = Intent(js["intent"])
            plan = [AgentName(a) for a in js.get("plan") or PLANS[intent]]
            decision = RouteDecision(plan=plan, intent=intent, confidence=float(js.get("confidence", 0.5)),
                                     reason=str(js.get("reason", ""))[:200],
                                     language=js.get("language") if js.get("language") in ("pt", "en") else heuristic.language,
                                     source="llm")
            return decision, False
        except (LLMError, KeyError, ValueError, TypeError) as exc:
            self.log.warning("router LLM failed, using heuristic", extra={"extra_fields": {"error": str(exc)}})
            return heuristic, True

    def handle(self, msg: AgentMessage) -> AgentResult:
        decision, fallback = self.decide(msg.text)
        return AgentResult(agent=self.name, confidence=decision.confidence, data={"route": decision},
                           llm_fallback=fallback)
