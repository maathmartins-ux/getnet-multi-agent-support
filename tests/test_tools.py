"""Tools (FR-004, FR-005, BR-002): CRM over customer data, business-day settlement, web search, general APIs."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from getnet_agents.tools.crm import CRM, TOOL_SPECS, roll_to_business_day
from getnet_agents.tools.general import GeneralTools, detect_city, detect_currency, is_weather_question
from getnet_agents.tools.web_search import WebResult, WebSearchTool
from tests.conftest import TODAY, USER

# ----------------------------------------------------------------------------- CRM


def test_crm_loads_seed_and_resolves_dates(crm: CRM):
    """FR-005: the JSON seed is loaded and `days_ago` becomes an ISO date relative to `today`."""
    assert set(crm.customers) >= {"cliente1988", "cliente2042"}
    tx = {t["id"]: t for t in crm.customers[USER]["transactions"]}
    assert tx["TX-9001"]["date"] == "2026-10-29"
    assert "days_ago" not in tx["TX-9001"]
    assert crm.customers[USER]["devices"][0]["last_seen"] == "5h ago"


def test_get_customer_profile(crm: CRM):
    """FR-005: profile tool returns the merchant fields and an explicit error for unknown ids."""
    p = crm.get_customer_profile(USER)
    assert p["name"] == "Maria Oliveira" and p["anticipation_enabled"] is False
    assert "transactions" not in p
    assert crm.get_customer_profile("ghost") == {"error": "customer_not_found", "user_id": "ghost"}


def test_get_transactions_window_and_status_filter(crm: CRM):
    """FR-005: transactions are filtered by a day window and optional status."""
    all_tx = crm.get_transactions(USER, days=7)
    assert all_tx["count"] == 5
    assert all_tx["total_brl"] == round(320.5 + 89.9 + 45.0 + 1200.0 + 150.0, 2)
    declined = crm.get_transactions(USER, days=7, status="declined")
    assert declined["count"] == 1 and declined["transactions"][0]["id"] == "TX-9005"
    assert crm.get_transactions(USER, days=1)["count"] == 3  # only yesterday's sales
    assert "error" in crm.get_transactions("ghost")


def test_roll_to_business_day_weekend_and_holiday():
    """FR-005: settlement dates skip weekends and Brazilian national holidays (02/11 Finados)."""
    assert roll_to_business_day(date(2026, 10, 31)) == date(2026, 11, 3)  # Sat -> Sun -> holiday -> Tue
    assert roll_to_business_day(date(2026, 10, 30)) == date(2026, 10, 30)  # Friday stays
    assert roll_to_business_day(date(2026, 12, 25)) == date(2026, 12, 28)  # Christmas (Fri) -> Monday


def test_settlement_forecast_rules(crm: CRM):
    """FR-005: D+n by method, rolled to business day; status settled/pending relative to today."""
    fc = crm.get_settlement_forecast(USER, days=7)
    assert fc["today"] == TODAY.isoformat() and fc["anticipation_enabled"] is False
    by_id = {}
    for row in fc["items"]:
        by_id.setdefault(row["transaction_id"], []).append(row)
    assert "TX-9005" not in by_id  # declined sales never settle
    debit = by_id["TX-9002"][0]
    assert debit["settlement_date"] == "2026-10-30" and debit["status"] == "settled" and debit["rule"].startswith("D+1")
    pix = by_id["TX-9003"][0]
    assert pix["settlement_date"] == "2026-10-29" and pix["status"] == "settled"
    credit = by_id["TX-9001"][0]
    assert credit["settlement_date"] == "2026-11-30"  # 28/11 is Saturday -> Monday 30/11
    assert credit["status"] == "pending" and credit["rule"].startswith("D+30")


def test_settlement_forecast_installments_one_row_each(crm: CRM):
    """FR-005: a 6x credit sale produces one settlement row per installment with split amounts."""
    rows = [r for r in crm.get_settlement_forecast(USER, days=7)["items"] if r["transaction_id"] == "TX-9004"]
    assert [r["installment"] for r in rows] == [f"{k}/6" for k in range(1, 7)]
    assert all(r["amount_brl"] == 200.0 for r in rows)
    assert len({r["settlement_date"] for r in rows}) == 6
    assert rows[0]["rule"].startswith("D+30") and rows[1]["rule"].startswith("D+60")
    assert date.fromisoformat(rows[0]["settlement_date"]) == roll_to_business_day(date(2026, 11, 27))


def test_settlement_forecast_with_anticipation(crm: CRM):
    """FR-005: merchants with anticipation enabled get credit sales at D+1."""
    rows = crm.get_settlement_forecast("cliente2042", days=7)["items"]
    assert rows and all(r["rule"].startswith("D+1 (anticipation)") for r in rows if r["method"].startswith("credit"))


def test_get_device_status(crm: CRM):
    """FR-005: device tool exposes model, status and last error."""
    st = crm.get_device_status(USER)
    dev = st["devices"][0]
    assert dev["model"] == "Get Clássica" and dev["status"] == "offline" and dev["last_error"] == "NETWORK_TIMEOUT"
    assert crm.get_device_status("cliente2042")["devices"][0]["status"] == "online"


def test_open_support_ticket(crm: CRM):
    """FR-005 / BR-001: tickets get a GN- protocol, are stored and keep queue/priority."""
    t = crm.open_support_ticket(USER, category="device", summary="x" * 500, priority="high", queue="human_support")
    assert t["ticket_id"].startswith("GN-") and len(t["ticket_id"]) == 11
    assert t["status"] == "open" and t["priority"] == "high" and t["queue"] == "human_support"
    assert len(t["summary"]) == 300
    assert t["created_at"] == TODAY.isoformat()
    assert crm.tickets[-1] is t


def test_handlers_cover_every_tool_spec(crm: CRM):
    """FR-005: every tool exposed to the LLM has a handler, and specs never expose `user_id`."""
    handlers = crm.handlers()
    assert {s.name for s in TOOL_SPECS} == set(handlers)
    assert len(TOOL_SPECS) >= 2
    for spec in TOOL_SPECS:
        assert "user_id" not in spec.input_schema.get("properties", {})
        assert spec.to_anthropic()["name"] == spec.name


def test_bound_handlers_force_server_side_user_id(crm: CRM):
    """BR-002 (anti-IDOR): whatever user_id the model sends, the authenticated one wins."""
    bound = crm.bound_handlers("cliente1988")
    assert bound["get_customer_profile"](user_id="cliente2042")["name"] == "Maria Oliveira"
    assert bound["get_customer_profile"]()["name"] == "Maria Oliveira"
    assert bound["get_device_status"](user_id="cliente2042")["devices"][0]["model"] == "Get Clássica"
    ticket = bound["open_support_ticket"](user_id="cliente2042", category="other", summary="s")
    assert ticket["user_id"] == "cliente1988"


# ----------------------------------------------------------------------------- web search


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_web_search_disabled_returns_empty():
    """FR-004 / NFR-001: the disabled provider never touches the network and returns no results."""
    tool = WebSearchTool("disabled", client=_client(lambda req: pytest.fail("network call attempted")))
    assert tool.search("euro rate") == []
    assert tool.provider == "disabled"


def test_web_search_auto_picks_provider():
    """FR-004: auto -> tavily when a key exists, otherwise DuckDuckGo (keyless)."""
    assert WebSearchTool("auto", "key").provider == "tavily"
    assert WebSearchTool("auto", None).provider == "duckduckgo"


def test_web_search_tavily_parses_results():
    """FR-004: Tavily JSON is mapped to WebResult(title, url, snippet)."""
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "api.tavily.com"
        assert json.loads(req.content)["query"] == "euro rate"
        return httpx.Response(200, json={"results": [{"title": "T", "url": "https://x", "content": "c" * 600}]})

    out = WebSearchTool("tavily", "key", client=_client(handler)).search("euro rate", max_results=3)
    assert out == [WebResult(title="T", url="https://x", snippet="c" * 500)]


def test_web_search_duckduckgo_parses_html():
    """FR-004: the keyless DuckDuckGo HTML page is parsed and redirect wrappers are unwrapped."""
    page = ('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">Title &amp; One</a>'
            '<a class="result__snippet">Snip <b>bold</b></a>'
            '<a class="result__a" href="https://example.org/b">Two</a><a class="result__snippet">S2</a>')
    out = WebSearchTool("duckduckgo", client=_client(lambda r: httpx.Response(200, text=page))).search("q", max_results=1)
    assert out == [WebResult(title="Title & One", url="https://example.com/a", snippet="Snip bold")]


def test_web_search_failure_degrades_to_empty():
    """NFR-002: provider errors are swallowed and reported as an empty result, never raised."""
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    assert WebSearchTool("tavily", "key", client=_client(boom)).search("q") == []
    assert WebSearchTool("duckduckgo", client=_client(lambda r: httpx.Response(500))).search("q") == []


# ----------------------------------------------------------------------------- general tools


def test_detect_currency_and_city():
    """FR-004: the general-purpose scenarios are parsed into structured parameters."""
    assert detect_currency("What's the euro exchange rate today?") == "EUR"
    assert detect_currency("Qual a cotação do dólar hoje?") == "USD"
    assert detect_currency("How much is a Get Smart?") is None
    assert detect_city("What's the weather forecast in Porto Alegre tomorrow?") == "Porto Alegre"
    assert detect_city("Vai chover em São Paulo amanhã?") == "São Paulo"
    assert is_weather_question("What's the weather forecast in Porto Alegre tomorrow?") is True
    assert is_weather_question("What's the euro exchange rate today?") is False


def test_exchange_rate_primary_and_fallback():
    """FR-004 / NFR-002: AwesomeAPI is used first; on failure Frankfurter; on both failing -> None."""
    def ok(req: httpx.Request) -> httpx.Response:
        assert "EUR-BRL" in str(req.url)
        return httpx.Response(200, json={"EURBRL": {"bid": "6.0612", "ask": "6.0698", "create_date": "2026-10-30 13:21:00"}})

    rate = GeneralTools(client=_client(ok)).exchange_rate("eur")
    assert rate["pair"] == "EUR-BRL" and rate["bid"] == 6.0612 and rate["ask"] == 6.0698
    assert rate["source"].startswith("AwesomeAPI")

    def fallback(req: httpx.Request) -> httpx.Response:
        if "awesomeapi" in req.url.host:
            return httpx.Response(503)
        return httpx.Response(200, json={"base": "EUR", "date": "2026-10-30", "rates": {"BRL": 6.05}})

    rate = GeneralTools(client=_client(fallback)).exchange_rate("EUR")
    assert rate["bid"] == 6.05 and rate["source"].startswith("Frankfurter")

    assert GeneralTools(client=_client(lambda r: httpx.Response(500))).exchange_rate("EUR") is None


def test_weather_forecast_shape_and_failure():
    """FR-004 / NFR-002: Open-Meteo geocoding + forecast become a compact daily list; failures -> None."""
    def ok(req: httpx.Request) -> httpx.Response:
        if "geocoding" in req.url.host:
            return httpx.Response(200, json={"results": [{"name": "Porto Alegre", "country": "Brasil",
                                                           "latitude": -30.03, "longitude": -51.23}]})
        return httpx.Response(200, json={"daily": {"time": ["2026-10-30", "2026-10-31"],
                                                   "temperature_2m_max": [24.1, 22.0],
                                                   "temperature_2m_min": [15.0, 14.2],
                                                   "precipitation_probability_max": [40, 80]}})

    wx = GeneralTools(client=_client(ok)).weather_forecast("Porto Alegre")
    assert wx["city"] == "Porto Alegre" and wx["country"] == "Brasil" and wx["source"] == "Open-Meteo"
    assert wx["days"][1] == {"date": "2026-10-31", "tmax": 22.0, "tmin": 14.2, "precip_prob": 80}

    no_city = GeneralTools(client=_client(lambda r: httpx.Response(200, json={"results": []})))
    assert no_city.weather_forecast("Xyzzy") is None
    assert GeneralTools(client=_client(lambda r: httpx.Response(500))).weather_forecast("Porto Alegre") is None
