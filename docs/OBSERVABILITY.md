# Observability (BR-004)

One page: what the service emits today, how to read it, what to alert on, and how to grow it.
Everything below is implemented in `src/getnet_agents/observability.py`, `orchestrator.py` and `api.py`
unless marked **suggested**.

## 1. Structured logs (JSON, stdout)

`configure_logging()` installs a single `JsonFormatter` on the root logger (12-factor: one JSON object per
line on stdout; the container runtime ships it). Base fields on every line: `ts` (UTC, ms), `level`, `logger`,
`msg`, plus `exc` when there is a traceback. `log_event(logger, msg, **fields)` merges extra fields at top level.

| event (`msg`) | emitted by | fields |
|---|---|---|
| `startup` | `api.py` lifespan | `mode`, `model`, `kb_documents`, `kb_chunks`, `web_search`, `environment` |
| `chat.completed` | `orchestrator.py` `_response()` | `request_id`, `user_id`, `intent` (`blocked` when guardrails stopped the request), `plan` (agents involved, in order), `latency_ms`, `tools` (tool names, in order), `handoff` (bool), `guardrail_flags` (input + output flags), `mode` |
| `unhandled error` | `api.py` exception handler | `exc` (traceback); the HTTP response carries `x-request-id` |
| `router LLM failed, using heuristic` | `agents/router.py` | `error` — WARNING; always paired with `llm_fallbacks_total{agent="router"}` |
| `knowledge LLM failed, extractive fallback` / `knowledge web LLM failed, listing fallback` | `agents/knowledge.py` | `error` |
| `support LLM failed, heuristic planner` | `agents/support.py` | `error` |
| `handoff webhook failed` | `agents/escalation.py` | `error` — the handoff still happens (`notified=false`) |
| `web search failed`, `awesomeapi failed...`, `frankfurter failed`, `open-meteo failed` | `tools/*` | `provider`/`error` — best-effort tools, never raise |

`chat.completed` is the one line you need per request: it is the compact form of the trace below. Correlate
with the HTTP layer through the `x-request-id` response header (middleware in `api.py`; the body also carries
`request_id`). **Suggested:** pass the header value into `Orchestrator.handle` so both ids are the same.

PII policy: the message text is never logged; guardrails mask card/CPF before any agent sees it
(`guardrails.check_input`), and the only free text that leaves the process is the ticket `summary`.

## 2. Prometheus metrics (`GET /metrics`)

| metric | type | labels | what it answers |
|---|---|---|---|
| `chat_requests_total` | counter | `intent`, `mode`, `outcome` (`answered`, `handoff`, `blocked`) | traffic mix per intent; handoff and block rates |
| `chat_request_latency_seconds` | histogram (buckets 0.05 .. 30 s) | – | end-to-end p50/p95/p99 via `histogram_quantile` |
| `agent_step_latency_seconds` | histogram | `agent` (`knowledge`, `support`, `escalation`) | which agent is slow (LLM vs tools vs RAG) |
| `guardrail_flags_total` | counter | `flag` (`pii_card`, `pii_cpf`, `prompt_injection`, `unsafe_content`, `too_long`, `output_pii`), `stage` (`input`, `output`) | attack/PII pressure; `output_pii` > 0 means an agent leaked data the output filter had to mask |
| `handoffs_total` | counter | `reason` (`human_request`, `unsupported`, `low_confidence`, `no_knowledge`, `low_groundedness`, `customer_not_found`) | why humans are being pulled in |
| `llm_fallbacks_total` | counter | `agent` (`router`, `knowledge`, `support`) | LLM errors absorbed by the deterministic path (quality silently degraded) |
| `tool_calls_total` | counter | `tool` (`get_customer_profile`, `get_settlement_forecast`, `get_transactions`, `get_device_status`, `open_support_ticket`, `web_search`, `notify_human_channel`) | tool usage; sudden drop of `web_search` = provider outage |
| `rag_empty_retrievals_total` | counter | – | Getnet questions the knowledge base could not answer (coverage gap -> `no_knowledge` handoff) |

Useful PromQL:

```promql
# handoff rate, 15 min
sum(rate(chat_requests_total{outcome="handoff"}[15m])) / sum(rate(chat_requests_total[15m]))
# p95 end-to-end latency
histogram_quantile(0.95, sum(rate(chat_request_latency_seconds_bucket[5m])) by (le))
# LLM degradation per agent
sum(increase(llm_fallbacks_total[15m])) by (agent)
```

## 3. Per-request trace

Every `ChatResponse` carries `trace: list[TraceStep]` (`agent`, `action`, `duration_ms`, `detail`), built in
`Orchestrator.handle`:

1. `guardrails / input_check` — `flags`, `blocked`
2. `router / route` — `intent`, `plan`, `confidence`, `source` (`llm` | `heuristic`), `language`, `llm_fallback`
3. `orchestrator / low_confidence_handoff` (only when confidence < `router_confidence_threshold`) — `threshold`
4. one `handle` step per agent executed — `tools`, `sources`, `confidence`, `needs_escalation`, `llm_fallback`

Plus `agents_involved`, `tools_used`, `sources`, `guardrails`, `latency_ms`, `mode`, `model`. This is the
same data the eval runner (`evals/run_evals.py`) scores, so a production trace can be replayed as an eval case.

## 4. Suggested alerts

| alert | expression (sketch) | why |
|---|---|---|
| Handoff rate > 30 % for 15 min | `handoff rate (above) > 0.30` | router or KB regression; humans flooded |
| LLM fallbacks rising | `sum(increase(llm_fallbacks_total[10m])) > 5` | provider outage/quota; answers degrade to templates silently |
| p95 latency > 5 s for 10 min | `histogram_quantile(0.95, ...) > 5` | LLM/tool timeouts (`llm_timeout_s` is 30 s, so users wait) |
| RAG empty retrievals | `increase(rag_empty_retrievals_total[1h]) > 20` | knowledge gap; feed the questions back into `data/knowledge` |
| Output PII masked | `increase(guardrail_flags_total{flag="output_pii"}[1h]) > 0` | an agent echoed PII; investigate the prompt/tool output |
| Prompt-injection burst | `increase(guardrail_flags_total{flag="prompt_injection"}[15m]) > 20` | abuse pattern; consider rate limiting the `user_id` |
| 5xx | `unhandled error` log count > 0 in 5 min | bug or dependency failure |
| No traffic | `rate(chat_requests_total[15m]) == 0` during business hours | API down or upstream broken |

## 5. Suggested Grafana dashboard (6 panels)

1. **Traffic by intent** — stacked `rate(chat_requests_total[5m]) by (intent)`.
2. **Outcome split** — `answered` / `handoff` / `blocked` share, with the 30 % handoff threshold line.
3. **Latency** — p50/p95/p99 from `chat_request_latency_seconds`, plus `agent_step_latency_seconds` p95 by agent.
4. **Degradation** — `llm_fallbacks_total` by agent and `rag_empty_retrievals_total` (both should be flat at 0).
5. **Handoff reasons** — `handoffs_total` by `reason` (bar gauge): human_request is healthy, `low_confidence` and `no_knowledge` are backlog for routing/KB work.
6. **Guardrails & tools** — `guardrail_flags_total` by flag/stage and `tool_calls_total` by tool.

Local stack: add Prometheus (`scrape /metrics` on port 8000) and Grafana to `docker-compose.yml`; import the
panels above from the PromQL in section 2.

## 6. Evolving to OpenTelemetry / Langfuse

- **OpenTelemetry (traces + metrics):** wrap `Orchestrator.handle` in a root span and each `_run` in a child span
  (`agent`, `intent`, `tools` as attributes); the existing `TraceStep` list maps 1:1 to spans, so the change is
  additive. Use `opentelemetry-instrumentation-fastapi` for HTTP spans and export via OTLP to Tempo/Jaeger.
  Keep Prometheus by exporting the same counters through the OTel Prometheus exporter, or scrape both during
  migration.
- **Langfuse (LLM observability):** instrument `llm.py` (`complete`, `complete_json`, `run_tools`) with
  `@observe()` to capture prompt, completion, model, tokens and cost per agent call; link the Langfuse trace id
  to `request_id`. The eval dataset (`evals/dataset.jsonl`) can be uploaded as a Langfuse dataset so the same
  cases run against production prompts; `must_contain_any` becomes a scorer, and the LLM-judge for
  groundedness replaces the keyword proxy.
- **Order of work:** (1) propagate `x-request-id` into logs/trace; (2) OTel spans; (3) Langfuse on `llm.py`;
  (4) move alerts from PromQL sketches to Alertmanager rules checked into the repo.
