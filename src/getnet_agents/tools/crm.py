"""Customer data tools for the Customer Support Agent (FR-005) and ticketing for escalation (BR-001).

Backed by a JSON seed (`data/crm/customers.json`) loaded into memory. Transactions carry `days_ago`
so the demo stays meaningful on any date ("yesterday" always exists).

Security: `user_id` is NOT a parameter the LLM can fill. `TOOL_SPECS` omit it and `bound_handlers()`
forces the authenticated `user_id` on every call (prevents IDOR via prompt injection, BR-002).
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from ..llm import ToolSpec

# calendar days added to the sale date before rolling to the next business day
SETTLEMENT_RULES = {"debit": 1, "credit": 30, "credit_installments": 30, "pix": 0}
# Brazilian national holidays with fixed dates (movable ones — Carnaval, Sexta-feira Santa, Corpus Christi — are
# documented as a limitation; a production system would use a holiday calendar service).
BR_HOLIDAYS_FIXED = {(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25)}


def roll_to_business_day(d: date) -> date:
    while d.weekday() >= 5 or (d.month, d.day) in BR_HOLIDAYS_FIXED:
        d += timedelta(days=1)
    return d


class CRM:
    def __init__(self, customers: dict[str, dict[str, Any]], *, today: date | None = None) -> None:
        self.today = today or date.today()
        self.customers = {uid: self._resolve_dates(c) for uid, c in customers.items()}
        self.tickets: list[dict[str, Any]] = []

    @classmethod
    def from_json(cls, path: str | Path, *, today: date | None = None) -> "CRM":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data["customers"], today=today)

    def _resolve_dates(self, c: dict[str, Any]) -> dict[str, Any]:
        c = json.loads(json.dumps(c))  # deep copy
        for t in c.get("transactions", []):
            t["date"] = (self.today - timedelta(days=int(t.pop("days_ago", 0)))).isoformat()
        for d in c.get("devices", []):
            if "last_seen_hours_ago" in d:
                d["last_seen"] = f"{d.pop('last_seen_hours_ago')}h ago"
        return c

    # ---------------------------------------------------------------- tools
    def get_customer_profile(self, user_id: str) -> dict[str, Any]:
        c = self.customers.get(user_id)
        if not c:
            return {"error": "customer_not_found", "user_id": user_id}
        return {k: c[k] for k in ("name", "business", "segment", "plan", "bank", "anticipation_enabled") if k in c}

    def get_transactions(self, user_id: str, days: int = 7, status: str | None = None) -> dict[str, Any]:
        c = self.customers.get(user_id)
        if not c:
            return {"error": "customer_not_found", "user_id": user_id}
        since = (self.today - timedelta(days=days)).isoformat()
        txs = [t for t in c.get("transactions", []) if t["date"] >= since and (status is None or t["status"] == status)]
        return {"user_id": user_id, "since": since, "status_filter": status, "count": len(txs),
                "total_brl": round(sum(t["amount_brl"] for t in txs), 2), "transactions": txs}

    def get_settlement_forecast(self, user_id: str, days: int = 7) -> dict[str, Any]:
        """When each recent sale will be deposited: D+n by method, per installment, rolled to business days."""
        c = self.customers.get(user_id)
        if not c:
            return {"error": "customer_not_found", "user_id": user_id}
        anticipation = bool(c.get("anticipation_enabled"))
        rows = []
        for t in self.get_transactions(user_id, days, status="approved")["transactions"]:
            method, sale = t["method"], date.fromisoformat(t["date"])
            n = int(t.get("installments", 1)) if method == "credit_installments" else 1
            for k in range(1, n + 1):
                delay = 1 if (anticipation and method.startswith("credit")) else SETTLEMENT_RULES.get(method, 30) * k
                settle = roll_to_business_day(sale + timedelta(days=delay))
                rows.append({"transaction_id": t["id"], "sale_date": t["date"], "method": method,
                             "installment": f"{k}/{n}", "amount_brl": round(t["amount_brl"] / n, 2),
                             "settlement_date": settle.isoformat(),
                             "status": "settled" if settle <= self.today else "pending",
                             "rule": f"D+{delay}" + (" (anticipation)" if anticipation and method.startswith("credit") else "")
                                     + " → next business day"})
        return {"user_id": user_id, "today": self.today.isoformat(), "anticipation_enabled": anticipation,
                "bank": c.get("bank"), "items": rows}

    def get_device_status(self, user_id: str) -> dict[str, Any]:
        c = self.customers.get(user_id)
        if not c:
            return {"error": "customer_not_found", "user_id": user_id}
        return {"user_id": user_id, "devices": c.get("devices", [])}

    def open_support_ticket(self, user_id: str, category: str, summary: str,
                            priority: str = "normal", queue: str = "technical_support") -> dict[str, Any]:
        ticket = {"ticket_id": f"GN-{uuid.uuid4().hex[:8].upper()}", "user_id": user_id, "category": category,
                  "summary": summary[:300], "priority": priority, "queue": queue, "status": "open",
                  "created_at": self.today.isoformat()}
        self.tickets.append(ticket)
        return ticket

    def handlers(self) -> dict[str, Callable[..., Any]]:
        return {
            "get_customer_profile": self.get_customer_profile,
            "get_transactions": self.get_transactions,
            "get_settlement_forecast": self.get_settlement_forecast,
            "get_device_status": self.get_device_status,
            "open_support_ticket": self.open_support_ticket,
        }

    def bound_handlers(self, user_id: str) -> dict[str, Callable[..., Any]]:
        """Handlers with `user_id` forced to the authenticated user — whatever the model sends is overridden."""

        def bind(fn: Callable[..., Any]) -> Callable[..., Any]:
            def wrapped(**kwargs: Any) -> Any:
                kwargs["user_id"] = user_id
                return fn(**kwargs)
            return wrapped

        return {name: bind(fn) for name, fn in self.handlers().items()}


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec("get_customer_profile", "Get the merchant profile: name, business, segment, plan, bank, anticipation flag.",
             {"type": "object", "properties": {}}),
    ToolSpec("get_transactions", "List the merchant sales (card/Pix) in the last N days; filter by status to see declines.",
             {"type": "object", "properties": {"days": {"type": "integer", "default": 7},
                                               "status": {"type": "string", "enum": ["approved", "declined"]}}}),
    ToolSpec("get_settlement_forecast",
             "For each recent approved sale (per installment), when the money will be deposited: settlement date, D+n rule, anticipation.",
             {"type": "object", "properties": {"days": {"type": "integer", "default": 7}}}),
    ToolSpec("get_device_status", "Status of the merchant card machines: model, serial, connectivity, firmware, last error.",
             {"type": "object", "properties": {}}),
    ToolSpec("open_support_ticket", "Open a support ticket for the merchant and return its protocol id.",
             {"type": "object", "properties": {"category": {"type": "string", "enum": ["device", "settlement", "fraud", "other"]},
                                               "summary": {"type": "string"},
                                               "priority": {"type": "string", "enum": ["low", "normal", "high"]}},
              "required": ["category", "summary"]}),
]
