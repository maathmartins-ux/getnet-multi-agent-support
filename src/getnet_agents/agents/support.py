"""Customer Support Agent (FR-005, FR-007): resolves account requests with tools over customer data.

LLM mode: Claude drives the tool loop (`llm.run_tools`) over handlers bound to the authenticated
`user_id` (anti-IDOR). Offline/fallback mode: a deterministic planner picks the tools from the intent
and renders a template answer — same tools, same data.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

from ..llm import LLMError
from ..schemas import AgentMessage, AgentName, AgentResult, Intent, ToolCall
from ..tools.crm import CRM, TOOL_SPECS
from .base import BaseAgent

NOT_FOUND = {
    "pt": "Não localizei uma conta Getnet com o identificador informado. Vou encaminhar seu caso para um atendente verificar seu cadastro.",
    "en": "I could not find a Getnet account with the identifier provided. I will forward your case to a human agent to verify your registration.",
}
METHOD_LABEL = {"pt": {"credit": "crédito à vista", "credit_installments": "crédito parcelado", "debit": "débito", "pix": "Pix"},
                "en": {"credit": "credit", "credit_installments": "credit in installments", "debit": "debit", "pix": "Pix"}}
# ISO 8583 issuer response codes most common in Brazil — the decline comes from the card issuer, not the terminal.
DECLINE_CODES = {
    "05": {"pt": "não autorizada pelo emissor (genérico) — peça ao cliente que contate o banco", "en": "do not honor (issuer) — ask the customer to contact their bank"},
    "51": {"pt": "saldo/limite insuficiente — ofereça outro cartão ou outro meio de pagamento (Pix, débito)", "en": "insufficient funds — offer another card or payment method (Pix, debit)"},
    "54": {"pt": "cartão vencido", "en": "expired card"},
    "55": {"pt": "senha incorreta — peça para digitar novamente", "en": "incorrect PIN — ask the customer to retry"},
    "57": {"pt": "transação não permitida para este cartão (ex.: cartão sem função crédito)", "en": "transaction not permitted for this card (e.g. no credit function)"},
    "61": {"pt": "valor acima do limite do cartão", "en": "exceeds card limit"},
    "62": {"pt": "cartão restrito/bloqueado pelo emissor", "en": "restricted/blocked card"},
    "91": {"pt": "emissor indisponível no momento — tente novamente em alguns minutos", "en": "issuer unavailable — retry in a few minutes"},
}
DECLINE_KW = ("declin", "recus", "negad", "nao passa", "não passa", "not approved", "nao autoriz", "não autoriz", "rejected")


def fmt_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def fmt_brl(value: float) -> str:
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class SupportAgent(BaseAgent):
    name = AgentName.SUPPORT

    def __init__(self, llm, crm: CRM) -> None:  # noqa: ANN001
        super().__init__(llm)
        self.crm = crm

    def _call(self, handlers: dict[str, Any], name: str, **kwargs: Any) -> tuple[Any, ToolCall]:
        t0 = time.perf_counter()
        result = handlers[name](**kwargs)
        return result, ToolCall(name=name, arguments=kwargs, result=result,
                                duration_ms=round((time.perf_counter() - t0) * 1000, 2))

    def handle(self, msg: AgentMessage) -> AgentResult:
        handlers = self.crm.bound_handlers(msg.user_id)  # user_id can never be chosen by the model
        profile, call = self._call(handlers, "get_customer_profile")
        calls = [call]
        if "error" in profile:
            return AgentResult(agent=self.name, answer=NOT_FOUND[msg.language], tool_calls=calls, confidence=0.2,
                               needs_escalation=True, escalation_reason="customer_not_found",
                               data={"customer": None})
        intent = msg.route.intent if msg.route else Intent.ACCOUNT
        if not self.llm.offline:
            try:
                user = (f"language: {msg.language}\nintent: {intent.value}\ntoday: {self.crm.today.isoformat()}\n"
                        f"merchant profile (already fetched): {profile}\nmessage: {msg.text}")
                run = self.llm.run_tools(self.system_prompt, user, TOOL_SPECS, handlers, max_turns=6)
                calls += run.tool_calls
                return AgentResult(agent=self.name, answer=run.text, tool_calls=calls, confidence=0.9,
                                   data=self._collect(profile, calls))
            except LLMError as exc:
                self.log.warning("support LLM failed, heuristic planner", extra={"extra_fields": {"error": str(exc)}})
                res = self._heuristic(msg, intent, profile, calls, handlers)
                res.llm_fallback = True
                return res
        return self._heuristic(msg, intent, profile, calls, handlers)

    # ---------------------------------------------------------------- deterministic planner
    def _heuristic(self, msg: AgentMessage, intent: Intent, profile: dict[str, Any], calls: list[ToolCall],
                   handlers: dict[str, Any]) -> AgentResult:
        lang, low = msg.language, msg.text.lower()
        if intent == Intent.DEVICE_ISSUE and any(k in low for k in DECLINE_KW):
            return self._declines(msg, profile, calls, handlers)
        if intent == Intent.DEVICE_ISSUE:
            return self._device(msg, profile, calls, handlers)
        return self._settlement(msg, profile, calls, handlers)

    def _declines(self, msg: AgentMessage, profile: dict[str, Any], calls: list[ToolCall], handlers: dict[str, Any]) -> AgentResult:
        lang = msg.language
        txs, c = self._call(handlers, "get_transactions", days=7, status="declined")
        calls.append(c)
        declined = txs.get("transactions", [])
        if lang == "pt":
            lines = [f"Olá, {profile['name'].split()[0]}! Uma transação negada quase sempre é decisão do banco emissor do cartão, "
                     "não um defeito da maquininha. Nos últimos 7 dias encontrei:"]
        else:
            lines = [f"Hi {profile['name'].split()[0]}! A declined transaction is almost always a decision of the card issuer, "
                     "not a card machine fault. In the last 7 days I found:"]
        if not declined:
            lines.append("- nenhuma transação negada registrada." if lang == "pt" else "- no declined transactions on record.")
        for t in declined:
            code = str(t.get("decline_reason", "")).split(" ")[0]
            meaning = DECLINE_CODES.get(code, {}).get(lang, t.get("decline_reason", ""))
            lines.append(f"- {fmt_date(t['date'])} · {t.get('brand', '')} {t['method']} · {fmt_brl(t['amount_brl'])} · "
                         + (f"código {code}: {meaning}" if lang == "pt" else f"code {code}: {meaning}"))
        lines.append("Se o erro aparecer para todos os cartões, aí sim pode ser a maquininha — veja os passos abaixo e, se persistir, abro um chamado técnico."
                     if lang == "pt" else
                     "If every card is declined, the machine itself may be at fault — follow the steps below and, if it persists, I will open a technical ticket.")
        return AgentResult(agent=self.name, answer="\n".join(lines), tool_calls=calls, confidence=0.85,
                           data={"customer": profile, "declined_transactions": declined})

    def _device(self, msg: AgentMessage, profile: dict[str, Any], calls: list[ToolCall], handlers: dict[str, Any]) -> AgentResult:
        lang = msg.language
        status, c = self._call(handlers, "get_device_status")
        calls.append(c)
        devices = status.get("devices", [])
        device = devices[0] if devices else None
        lines: list[str] = []
        ticket = None
        if device:
            bad = device.get("status") != "online" or device.get("last_error")
            if lang == "pt":
                lines.append(f"Verifiquei sua maquininha **{device['model']}** (série {device['serial']}): status "
                             f"**{device['status']}**, última conexão {device.get('last_seen', 'n/d')}, firmware {device.get('firmware')}"
                             + (f", último erro `{device['last_error']}`." if device.get("last_error") else "."))
            else:
                lines.append(f"I checked your **{device['model']}** card machine (serial {device['serial']}): status "
                             f"**{device['status']}**, last seen {device.get('last_seen', 'n/a')}, firmware {device.get('firmware')}"
                             + (f", last error `{device['last_error']}`." if device.get("last_error") else "."))
            if bad:
                ticket, c2 = self._call(handlers, "open_support_ticket", category="device", summary=msg.text, priority="normal")
                calls.append(c2)
                lines.append(f"Abri o chamado técnico **{ticket['ticket_id']}** para acompanhamento."
                             if lang == "pt" else f"I opened technical ticket **{ticket['ticket_id']}** to follow up.")
        else:
            lines.append("Não encontrei maquininhas vinculadas à sua conta." if lang == "pt"
                         else "I found no card machines linked to your account.")
        return AgentResult(agent=self.name, answer="\n".join(lines), tool_calls=calls, confidence=0.85,
                           data={"customer": profile, "device": device, "ticket": ticket})

    def _settlement(self, msg: AgentMessage, profile: dict[str, Any], calls: list[ToolCall], handlers: dict[str, Any]) -> AgentResult:
        lang, low = msg.language, msg.text.lower()
        forecast, c = self._call(handlers, "get_settlement_forecast", days=7)
        calls.append(c)
        items = forecast["items"]
        if any(k in low for k in ("yesterday", "ontem")):
            yday = (self.crm.today - timedelta(days=1)).isoformat()
            items = [i for i in items if i["sale_date"] == yday] or items
        pending = [i for i in items if i["status"] == "pending"]
        labels = METHOD_LABEL[lang]
        first = profile["name"].split()[0]
        if lang == "pt":
            lines = [f"Olá, {first}! Previsão de depósito das suas vendas (conta {profile.get('bank', 'n/d')}), "
                     "já considerando fins de semana e feriados nacionais:"]
            for i in items:
                inst = f" parcela {i['installment']}" if i["method"] == "credit_installments" else ""
                lines.append(f"- {fmt_date(i['sale_date'])} · {labels.get(i['method'], i['method'])}{inst} · {fmt_brl(i['amount_brl'])}"
                             f" → depósito em **{fmt_date(i['settlement_date'])}** ({i['rule']})"
                             + (" ✔ já depositado" if i["status"] == "settled" else ""))
            if not profile.get("anticipation_enabled") and any(i["method"].startswith("credit") for i in pending):
                lines.append("Dica: com a antecipação de recebíveis ativa, as vendas no crédito podem cair em D+1.")
        else:
            lines = [f"Hi {first}! Deposit forecast for your sales (account {profile.get('bank', 'n/a')}), "
                     "already adjusted for weekends and Brazilian national holidays:"]
            for i in items:
                inst = f" installment {i['installment']}" if i["method"] == "credit_installments" else ""
                lines.append(f"- {fmt_date(i['sale_date'])} · {labels.get(i['method'], i['method'])}{inst} · {fmt_brl(i['amount_brl'])}"
                             f" → deposit on **{fmt_date(i['settlement_date'])}** ({i['rule']})"
                             + (" ✔ already deposited" if i["status"] == "settled" else ""))
            if not profile.get("anticipation_enabled") and any(i["method"].startswith("credit") for i in pending):
                lines.append("Tip: with receivables anticipation enabled, credit sales can be deposited on D+1.")
        return AgentResult(agent=self.name, answer="\n".join(lines), tool_calls=calls, confidence=0.85,
                           data={"customer": profile, "settlement": forecast})

    @staticmethod
    def _collect(profile: dict[str, Any], calls: list[ToolCall]) -> dict[str, Any]:
        data: dict[str, Any] = {"customer": profile}
        for c in calls:
            if c.name == "get_device_status" and isinstance(c.result, dict):
                devices = c.result.get("devices") or []
                data["device"] = devices[0] if devices else None
            if c.name == "open_support_ticket":
                data["ticket"] = c.result
            if c.name == "get_settlement_forecast":
                data["settlement"] = c.result
            if c.name == "get_transactions" and isinstance(c.result, dict) and c.result.get("status_filter") == "declined":
                data["declined_transactions"] = c.result.get("transactions", [])
        return data
