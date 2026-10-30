# Data model — 001-multi-agent-support

| Entity | Fields | Notes |
|--------|--------|-------|
| `ChatRequest` | `message` (1–4000 chars), `user_id` (`[A-Za-z0-9_.-]{1,64}`) | API input |
| `RouteDecision` | `plan: [AgentName]`, `intent`, `confidence`, `reason`, `language`, `source` (llm/heuristic) | produced by Router |
| `AgentMessage` | `request_id`, `user_id`, `text`, `language`, `route`, `context{}`, `history[]` | envelope passed between agents |
| `AgentResult` | `agent`, `answer`, `sources[]`, `tool_calls[]`, `handoff`, `confidence`, `needs_escalation`, `data{}` | agent output; `data` is merged into `context` |
| `Source` | `title`, `url`, `score`, `snippet`, `kind` (knowledge_base/web) | citations |
| `ToolCall` | `name`, `arguments`, `result`, `duration_ms` | tool trace |
| `Handoff` | `ticket_id`, `queue`, `priority`, `reason`, `status` | human handoff |
| `TraceStep` | `agent`, `action`, `duration_ms`, `detail{}` | per-step trace |
| `ChatResponse` | `request_id`, `user_id`, `answer`, `route`, `agents_involved`, `sources`, `tools_used`, `handoff`, `guardrails`, `trace`, `latency_ms`, `mode`, `model` | API output |
| Customer (CRM) | `name`, `business`, `segment`, `plan`, `devices[]`, `settlement{}`, `transactions[]`, `tickets[]` | `data/crm/customers.json` (`days_ago` resolved at load) |
| Chunk (KB) | `id`, `doc_title`, `url`, `heading`, `text`, `keywords` | in-memory, built from `data/knowledge/*.md` |

Intents: `getnet_product`, `general_web`, `account`, `device_issue`, `human_request`, `unsupported`.
