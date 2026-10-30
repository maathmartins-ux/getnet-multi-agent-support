"""Web search tool used by the Knowledge Agent for general-purpose questions (FR-004).

Providers: Tavily (key) -> DuckDuckGo HTML (no key) -> disabled. Failures return an empty list and
are logged; the agent then answers honestly that it could not search.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)


@dataclass
class WebResult:
    title: str
    url: str
    snippet: str


class WebSearchTool:
    name = "web_search"

    def __init__(self, provider: str = "auto", tavily_api_key: str | None = None,
                 client: httpx.Client | None = None, timeout_s: float = 8.0) -> None:
        if provider == "auto":
            provider = "tavily" if tavily_api_key else "duckduckgo"
        self.provider = provider
        self._key = tavily_api_key
        self._client = client or httpx.Client(timeout=timeout_s, follow_redirects=True)

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        if self.provider == "disabled":
            return []
        try:
            if self.provider == "tavily":
                return self._tavily(query, max_results)
            return self._duckduckgo(query, max_results)
        except Exception as exc:  # noqa: BLE001 - search is best-effort
            log.warning("web search failed", extra={"extra_fields": {"provider": self.provider, "error": str(exc)}})
            return []

    def _tavily(self, query: str, max_results: int) -> list[WebResult]:
        resp = self._client.post("https://api.tavily.com/search",
                                 json={"api_key": self._key, "query": query, "max_results": max_results})
        resp.raise_for_status()
        return [WebResult(title=r.get("title", ""), url=r.get("url", ""), snippet=r.get("content", "")[:500])
                for r in resp.json().get("results", [])]

    _DDG_RESULT = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>', re.DOTALL)

    def _duckduckgo(self, query: str, max_results: int) -> list[WebResult]:
        resp = self._client.get("https://html.duckduckgo.com/html/", params={"q": query},
                                headers={"User-Agent": "Mozilla/5.0 (compatible; getnet-agents/1.0)"})
        resp.raise_for_status()
        results: list[WebResult] = []
        for m in self._DDG_RESULT.finditer(resp.text):
            clean = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s)).strip()
            url = html.unescape(m.group("url"))
            if "uddg=" in url:  # DDG redirect wrapper
                url = httpx.URL(url).params.get("uddg", url)
            results.append(WebResult(title=clean(m.group("title")), url=url, snippet=clean(m.group("snippet"))))
            if len(results) >= max_results:
                break
        return results
