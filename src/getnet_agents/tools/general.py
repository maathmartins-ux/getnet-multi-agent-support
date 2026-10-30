"""Structured tools for the two general-purpose scenarios (weather, exchange rate) — FR-004.

Web search snippets rarely contain *tomorrow's* forecast or the *current* rate, so the Knowledge Agent
tries these keyless public APIs first and falls back to `web_search`. All failures return None.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

log = logging.getLogger(__name__)

CURRENCY_ALIASES = {"euro": "EUR", "eur": "EUR", "dolar": "USD", "dólar": "USD", "dollar": "USD", "usd": "USD",
                    "libra": "GBP", "pound": "GBP", "gbp": "GBP", "bitcoin": "BTC", "btc": "BTC", "iene": "JPY",
                    "yen": "JPY", "peso": "ARS", "franco": "CHF"}
WEATHER_KW = ("weather", "forecast", "clima", "tempo", "chover", "chuva", "rain", "temperature", "temperatura", "previsão", "previsao")


def detect_currency(text: str) -> str | None:
    low = text.lower()
    for alias, code in CURRENCY_ALIASES.items():
        if re.search(rf"\b{alias}\b", low):
            return code
    return None


def detect_city(text: str) -> str | None:
    """Best-effort: capitalised words after in/em/de/para/no/na, or any capitalised run (not sentence start)."""
    m = re.search(r"\b(?:in|em|de|para|no|na|at)\s+((?:[A-ZÀ-Ú][\wÀ-ú'-]+)(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ú][\wÀ-ú'-]+)*)", text)
    if m:
        return m.group(1)
    runs = re.findall(r"(?<!^)(?<![.!?]\s)\b((?:[A-ZÀ-Ú][\wÀ-ú'-]+)(?:\s+[A-ZÀ-Ú][\wÀ-ú'-]+)*)", text)
    return runs[0] if runs else None


def is_weather_question(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in WEATHER_KW)


class GeneralTools:
    def __init__(self, client: httpx.Client | None = None, timeout_s: float = 6.0) -> None:
        self._client = client or httpx.Client(timeout=timeout_s, follow_redirects=True)

    def exchange_rate(self, base: str, quote: str = "BRL") -> dict[str, Any] | None:
        pair = f"{base.upper()}-{quote.upper()}"
        try:
            r = self._client.get(f"https://economia.awesomeapi.com.br/json/last/{pair}")
            r.raise_for_status()
            d = next(iter(r.json().values()))
            return {"pair": pair, "bid": round(float(d["bid"]), 4), "ask": round(float(d["ask"]), 4),
                    "timestamp": d.get("create_date"), "source": "AwesomeAPI (economia.awesomeapi.com.br)"}
        except Exception as exc:  # noqa: BLE001
            log.warning("awesomeapi failed, trying frankfurter", extra={"extra_fields": {"error": str(exc)}})
        try:
            r = self._client.get("https://api.frankfurter.dev/v1/latest", params={"base": base.upper(), "symbols": quote.upper()})
            r.raise_for_status()
            d = r.json()
            rate = float(d["rates"][quote.upper()])
            return {"pair": pair, "bid": rate, "ask": rate, "timestamp": d.get("date"), "source": "Frankfurter (ECB reference)"}
        except Exception as exc:  # noqa: BLE001
            log.warning("frankfurter failed", extra={"extra_fields": {"error": str(exc)}})
            return None

    def weather_forecast(self, city: str) -> dict[str, Any] | None:
        try:
            g = self._client.get("https://geocoding-api.open-meteo.com/v1/search",
                                 params={"name": city, "count": 1, "language": "pt", "format": "json"})
            g.raise_for_status()
            hit = (g.json().get("results") or [None])[0]
            if not hit:
                return None
            f = self._client.get("https://api.open-meteo.com/v1/forecast",
                                 params={"latitude": hit["latitude"], "longitude": hit["longitude"],
                                         "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                                         "timezone": "auto", "forecast_days": 3})
            f.raise_for_status()
            daily = f.json()["daily"]
            days = [{"date": daily["time"][i], "tmax": daily["temperature_2m_max"][i], "tmin": daily["temperature_2m_min"][i],
                     "precip_prob": daily["precipitation_probability_max"][i]} for i in range(len(daily["time"]))]
            return {"city": hit.get("name", city), "country": hit.get("country"), "days": days, "source": "Open-Meteo"}
        except Exception as exc:  # noqa: BLE001
            log.warning("open-meteo failed", extra={"extra_fields": {"error": str(exc)}})
            return None
