# Implementation Plan — 001-multi-agent-support

## Technical context
- **Language**: Python 3.11+ (3.12 in Docker). **API**: FastAPI + Uvicorn. **Validation**: Pydantic v2.
- **LLM**: Anthropic Claude (`claude-sonnet-5-5` for generation, `claude-haiku-5-5` for routing) behind an `LLM` protocol with an `OfflineLLM` implementation.
- **RAG**: markdown corpus → heading/paragraph chunks → BM25 (pure Python, accent-insensitive, bilingual keyword boost) → top-k with relative score threshold → grounded generation with citations.
- **Tools**: in-process Python functions exposed to the LLM as Anthropic tool definitions; executed through a handler registry (`tools/crm.py`, `tools/web_search.py`).
- **Observability**: stdlib JSON logging, `prometheus-client`, per-request trace returned in the response.
- **Testing**: pytest (unit + integration with `TestClient`), eval runner over `evals/dataset.jsonl`.

## Architecture decisions (ADRs)
| ADR | Decision | Why | Alternatives rejected |
|-----|----------|-----|-----------------------|
| ADR-1 | Orchestrator + typed envelope, sequential plan | Deterministic, traceable, trivial to test; the Router decides the plan, the orchestrator executes it | Event bus / queue (overkill for one process; harder to trace), LangGraph (hides control flow) |
| ADR-2 | BM25 instead of embeddings | Zero model download (image stays small), deterministic, auditable scores, strong on product names; retriever is a protocol so a vector store can replace it | Chroma + sentence-transformers (≈2 GB image, non-deterministic), hosted embeddings (another key) |
| ADR-3 | `OfflineLLM` degraded mode | Evaluator can run everything with `docker compose up` and no key; same code path exercised in CI | Mocks only in tests (would leave the runtime untested) |
| ADR-4 | Prompts as versioned markdown files | Reviewable in PRs, diffable, loaded at startup | Inline strings |
| ADR-5 | Guardrails as pure functions before/after the pipeline | Testable without LLM; cheap | LLM-based moderation only |
| ADR-6 | Handoff on low confidence | Spec BR-003; wrong confident answers cost more than a human ticket | Always answer |

## Message workflow
```
POST /chat ─► Guardrails(in) ─► Router ─► [plan] ─► Agent₁ ─► Agent₂ … ─► Guardrails(out) ─► JSON
                 │ blocked                              │ needs_escalation
                 └──────────► safe reply                └──────────► Escalation Agent ─► ticket + webhook
```

## RAG pipeline
1. **Ingestion** — `rag/ingest.py` fetches URLs (getnet.net) → cleans HTML → markdown with frontmatter (`title,url,lang,keywords,fetched_at`). A curated snapshot lives in `data/knowledge/` so the system is reproducible offline.
2. **Storage** — `rag/store.py` chunks by `##` headings and paragraphs (~700 chars) and builds an in-memory BM25 index at startup (milliseconds for this corpus).
3. **Retrieval** — accent-insensitive tokens, bilingual stopwords, keyword boost from frontmatter; top-k with relative threshold.
4. **Generation** — Knowledge prompt forces citations `[n]`, JSON output with `confidence`; low confidence or empty retrieval → escalation.

## Project structure
```
src/getnet_agents/
  api.py            FastAPI app, /chat /health /metrics
  orchestrator.py   executes the Router plan, tracing, guardrails, handoff
  schemas.py        contracts (ChatRequest, AgentMessage, AgentResult, ChatResponse …)
  llm.py            LLM protocol, AnthropicLLM (tool loop), OfflineLLM
  guardrails.py     input/output guardrails
  observability.py  JSON logging + Prometheus metrics
  agents/           router.py knowledge.py support.py escalation.py
  rag/              store.py (chunking + BM25) ingest.py (fetch URLs)
  tools/            crm.py (5 customer tools) web_search.py (Tavily/DuckDuckGo)
  prompts/          router.md knowledge.md support.md escalation.md
```
