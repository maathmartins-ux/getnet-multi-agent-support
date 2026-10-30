"""Knowledge Agent (FR-003, FR-004): RAG over the Getnet corpus + web search for general questions."""

from __future__ import annotations

import re
import time

from ..llm import LLMError
from ..observability import RAG_EMPTY
from ..rag.store import KnowledgeBase, Retrieved, tokenize
from ..schemas import AgentMessage, AgentName, AgentResult, Intent, Source, ToolCall
from ..tools.general import GeneralTools, detect_city, detect_currency, is_weather_question
from ..tools.web_search import WebSearchTool
from .base import BaseAgent

NO_KB = {
    "pt": "Não encontrei essa informação na base de conhecimento oficial da Getnet. Vou encaminhar sua dúvida para um atendente.",
    "en": "I could not find that information in the official Getnet knowledge base. I will forward your question to a human agent.",
}
NO_WEB = {
    "pt": "Não consegui consultar a web agora para responder a essa pergunta. Tente novamente em alguns instantes.",
    "en": "I could not reach the web to answer that question right now. Please try again in a moment.",
}
HEADERS = {
    "pt": ("Com base no conteúdo oficial da Getnet:", "Fontes", "Resultado de busca na web (conteúdo externo, não oficial da Getnet):"),
    "en": ("Based on official Getnet content:", "Sources", "Web search result (external content, not official Getnet material):"),
}


class KnowledgeAgent(BaseAgent):
    name = AgentName.KNOWLEDGE

    def __init__(self, llm, kb: KnowledgeBase, web: WebSearchTool, *, top_k: int = 4,  # noqa: ANN001
                 general: GeneralTools | None = None) -> None:
        super().__init__(llm)
        self.kb = kb
        self.web = web
        self.general = general or GeneralTools()
        self.top_k = top_k

    # ------------------------------------------------------------------ dispatch
    def handle(self, msg: AgentMessage) -> AgentResult:
        intent = msg.route.intent if msg.route else Intent.GETNET_PRODUCT
        if intent == Intent.GENERAL_WEB:
            return self._general(msg)
        return self._getnet(msg)

    # ------------------------------------------------------------------ RAG path
    def _getnet(self, msg: AgentMessage) -> AgentResult:
        hits = self.kb.retrieve(msg.text, top_k=self.top_k)
        if not hits:
            RAG_EMPTY.inc()
            return AgentResult(agent=self.name, answer=NO_KB[msg.language], confidence=0.1,
                               needs_escalation=True, escalation_reason="no_knowledge")
        sources = [Source(title=h.chunk.doc_title, url=h.chunk.url, score=h.score,
                          snippet=h.chunk.text[:220], kind="knowledge_base") for h in hits]
        fallback = False
        if not self.llm.offline:
            try:
                js = self.llm.complete_json(self.system_prompt, self._rag_prompt(msg, hits), max_tokens=900)
                answer = str(js["answer"]).strip()
                conf = max(0.0, min(1.0, float(js.get("confidence", 0.7))))
                used = [int(i) for i in js.get("used_sources", []) if isinstance(i, (int, float))]
                if used:
                    sources = [s for i, s in enumerate(sources, start=1) if i in used] or sources
                low = conf < 0.4
                return AgentResult(agent=self.name, answer=answer, sources=sources, confidence=conf,
                                   needs_escalation=low, escalation_reason="low_groundedness" if low else "")
            except (LLMError, KeyError, ValueError, TypeError) as exc:
                self.log.warning("knowledge LLM failed, extractive fallback", extra={"extra_fields": {"error": str(exc)}})
                fallback = True
        return AgentResult(agent=self.name, answer=self._extractive(hits, msg.language, msg.text), sources=sources,
                           confidence=0.7, llm_fallback=fallback)

    def _rag_prompt(self, msg: AgentMessage, hits: list[Retrieved]) -> str:
        passages = "\n\n".join(f"[{i}] ({h.chunk.doc_title} — {h.chunk.heading})\n{h.chunk.text}"
                               for i, h in enumerate(hits, start=1))
        ctx = ""
        if msg.history:
            facts = "\n".join(f"- {r.agent.value}: {r.answer[:400]}" for r in msg.history if r.answer)
            ctx = ("\n\nCustomer context already shown to the user by previous agents (do not repeat it, "
                   f"only reference the protocol/device status when useful):\n{facts}")
        return (f"User language: {msg.language}\nUser question: {msg.text}{ctx}\n\n"
                f"Retrieved passages:\n{passages}")

    def _extractive(self, hits: list[Retrieved], lang: str, query: str = "") -> str:
        """Offline answer: for each top chunk keep the 2 whole sentences with the highest term overlap."""
        header, sources_label, _ = HEADERS[lang]
        qtokens = set(tokenize(query))
        parts = [header, ""]
        for i, h in enumerate(hits[:3], start=1):
            text = re.sub(r"\s+", " ", h.chunk.text.replace("\n", " ")).strip()
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
            ranked = sorted(enumerate(sentences), key=lambda kv: (-len(qtokens & set(tokenize(kv[1]))), kv[0]))
            chosen = sorted(ranked[:2], key=lambda kv: kv[0])
            excerpt = " ".join(s for _, s in chosen) or text[:300]
            label = h.chunk.doc_title if h.chunk.heading.lower().startswith("summary") else h.chunk.heading
            parts.append(f"**{label}** — {excerpt} [{i}]")
            parts.append("")
        parts.append(f"{sources_label}: " + "; ".join(
            f"[{i}] {h.chunk.doc_title}" + (f" ({h.chunk.url})" if h.chunk.url else "") for i, h in enumerate(hits[:3], start=1)))
        return "\n".join(parts).strip()

    # ------------------------------------------------------------------ web path
    def _general(self, msg: AgentMessage) -> AgentResult:
        structured = self._structured(msg)
        if structured is not None:
            return structured
        t0 = time.perf_counter()
        results = self.web.search(msg.text, max_results=5)
        call = ToolCall(name="web_search", arguments={"query": msg.text, "provider": self.web.provider},
                        result=[r.__dict__ for r in results], duration_ms=round((time.perf_counter() - t0) * 1000, 2))
        if not results:
            return AgentResult(agent=self.name, answer=NO_WEB[msg.language], tool_calls=[call], confidence=0.3)
        sources = [Source(title=r.title, url=r.url, snippet=r.snippet[:220], kind="web") for r in results]
        fallback = False
        if not self.llm.offline:
            try:
                listing = "\n\n".join(f"[{i}] {r.title}\n{r.url}\n{r.snippet}" for i, r in enumerate(results, start=1))
                js = self.llm.complete_json(self.system_prompt, f"User language: {msg.language}\nUser question: {msg.text}\n\n"
                                            f"Web search results:\n{listing}", max_tokens=600)
                return AgentResult(agent=self.name, answer=str(js["answer"]).strip(), sources=sources,
                                   tool_calls=[call], confidence=float(js.get("confidence", 0.6)))
            except (LLMError, KeyError, ValueError, TypeError) as exc:
                self.log.warning("knowledge web LLM failed, listing fallback", extra={"extra_fields": {"error": str(exc)}})
                fallback = True
        _, _, web_header = HEADERS[msg.language]
        lines = [web_header, ""] + [f"- **{r.title}** — {r.snippet[:200]} ({r.url})" for r in results[:3]]
        return AgentResult(agent=self.name, answer="\n".join(lines), sources=sources, tool_calls=[call],
                           confidence=0.5, llm_fallback=fallback)

    # ------------------------------------------------------------------ structured general tools
    def _structured(self, msg: AgentMessage) -> AgentResult | None:
        """Weather / exchange-rate via keyless public APIs; None -> caller falls back to web search."""
        lang = msg.language
        currency = detect_currency(msg.text)
        if currency and not is_weather_question(msg.text):
            t0 = time.perf_counter()
            data = self.general.exchange_rate(currency, "BRL")
            call = ToolCall(name="exchange_rate", arguments={"base": currency, "quote": "BRL"}, result=data,
                            duration_ms=round((time.perf_counter() - t0) * 1000, 2))
            if not data:
                return None
            bid = f"{data['bid']:.4f}".replace(".", ",") if lang == "pt" else f"{data['bid']:.4f}"
            answer = (f"Cotação {data['pair']} agora: **R$ {bid}** (compra) / R$ {f"{data['ask']:.4f}".replace('.', ',')} (venda), "
                      f"fonte {data['source']}, atualizado em {data.get('timestamp')}. Informação externa, não oficial da Getnet."
                      if lang == "pt" else
                      f"{data['pair']} right now: **R$ {bid}** (bid) / R$ {data['ask']:.4f} (ask), source {data['source']}, "
                      f"updated {data.get('timestamp')}. External information, not official Getnet content.")
            src = Source(title=data["source"], url="https://economia.awesomeapi.com.br/", snippet=answer[:200], kind="web")
            return AgentResult(agent=self.name, answer=answer, sources=[src], tool_calls=[call], confidence=0.9)
        if is_weather_question(msg.text):
            city = detect_city(msg.text)
            if not city:
                return None
            t0 = time.perf_counter()
            data = self.general.weather_forecast(city)
            call = ToolCall(name="weather_forecast", arguments={"city": city}, result=data,
                            duration_ms=round((time.perf_counter() - t0) * 1000, 2))
            if not data:
                return None
            lines = [f"Previsão para **{data['city']}**{', ' + data['country'] if data.get('country') else ''} (fonte {data['source']}, não oficial da Getnet):"
                     if lang == "pt" else
                     f"Forecast for **{data['city']}**{', ' + data['country'] if data.get('country') else ''} (source {data['source']}, not official Getnet content):"]
            for d in data["days"][:3]:
                lines.append(f"- {d['date']}: {d['tmin']}°C – {d['tmax']}°C, "
                             + (f"chance de chuva {d['precip_prob']}%" if lang == "pt" else f"rain chance {d['precip_prob']}%"))
            src = Source(title="Open-Meteo", url="https://open-meteo.com/", snippet=lines[0][:200], kind="web")
            return AgentResult(agent=self.name, answer="\n".join(lines), sources=[src], tool_calls=[call], confidence=0.9)
        return None
