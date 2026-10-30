# Feature Specification: Multi-Agent Support System for Getnet

**Feature ID**: 001-multi-agent-support
**Status**: Implemented
**Source**: challenge "AI Hardcore Engineer - Multi-Agent Support System"
**Method**: Spec-Driven Development (constitution → spec → plan → tasks → implementation → verification)

## 1. Problem statement
Getnet merchants send free-text messages (Portuguese or English) that mix product questions,
account-specific support, general questions and requests the system should not answer. One HTTP
endpoint must route each message to the right specialised agent(s), ground answers in Getnet public
content or in the customer data, and hand off to a human when it cannot resolve confidently.

## 2. User stories
- **US-1** As a merchant I ask about Getnet products (machines, Pix, anticipation, crediário, payment link) and get an answer grounded in getnet.net with sources.
- **US-2** As a merchant I ask a general question (weather, exchange rate) and get an answer from a web search, clearly marked as external.
- **US-3** As a merchant I ask about my own account (settlement dates, transactions, device status) and the system uses my data to answer.
- **US-4** As a merchant with a device problem I get troubleshooting steps **and** the system checks my device / opens a ticket.
- **US-5** As a merchant whose request cannot be resolved I am handed off to a human with a protocol number.
- **US-6** As Getnet I never want the system to process card numbers/CPF, follow prompt injections or answer unsafe requests.

## 3. Functional requirements
| ID | Requirement | Verified by |
|----|-------------|-------------|
| FR-001 | Expose `POST /chat` accepting `{"message": str, "user_id": str}` and returning a JSON object with at least `answer`, `route`, `agents_involved`, `sources`, `tools_used`, `handoff`, `trace`. | `tests/test_api.py` |
| FR-002 | Router Agent is the single entry point: classifies intent, detects language, outputs an ordered **plan** of agents and a confidence score. | `tests/test_router.py` |
| FR-003 | Knowledge Agent answers Getnet questions with RAG (ingestion → storage → retrieval → generation) over a corpus ingested from getnet.net, citing sources. | `tests/test_rag.py`, `tests/test_agents.py` |
| FR-004 | Knowledge Agent uses a web-search tool for general-purpose questions. | `tests/test_tools.py`, `tests/test_agents.py` |
| FR-005 | Customer Support Agent has ≥2 tools over customer data (profile, transactions, settlement forecast, device status, open ticket). | `tests/test_tools.py` |
| FR-006 | Agents communicate through a typed message envelope (`AgentMessage`/`AgentResult`) orchestrated sequentially; the Router may plan multi-agent sequences (e.g. support → knowledge). | `tests/test_orchestrator.py` |
| FR-007 | Unknown `user_id` → support agent explains and escalates instead of inventing data. | `tests/test_agents.py` |
| FR-008 | The 10 official example scenarios are routed to the expected agents. | `tests/test_scenarios.py`, `evals/` |
| FR-009 | Dockerfile + docker-compose run the API with `docker compose up --build`; `/health` reports mode and corpus size. | manual + `tests/test_api.py` |
| FR-010 | README documents build/config/run/test, architecture, workflow, RAG pipeline and LLM tool usage. | review |

## 4. Bonus requirements (implemented)
| ID | Requirement | Verified by |
|----|-------------|-------------|
| BR-001 | Fourth agent: **Human Escalation Agent** opens a ticket, notifies an optional webhook (Teams-style) and returns a handoff payload. | `tests/test_agents.py` |
| BR-002 | Guardrails: PII masking (CPF, card numbers with Luhn), prompt-injection block, unsafe-content block, length limit; output PII masking. | `tests/test_guardrails.py` |
| BR-003 | Human handoff when router confidence < threshold, when RAG finds nothing, when the LLM reports low groundedness, or on explicit request. | `tests/test_orchestrator.py` |
| BR-004 | Evaluation & observability: eval dataset + runner (routing accuracy, tool precision, groundedness, latency), structured logs, Prometheus `/metrics`, per-request trace. | `evals/run_evals.py`, `tests/test_observability.py` |

## 5. Non-functional requirements
| ID | Requirement |
|----|-------------|
| NFR-001 | Runs with **no API key and no network** in `offline` mode (deterministic router + extractive RAG + heuristic tool planner). |
| NFR-002 | Every LLM call: timeout ≤ 30 s, ≤ 2 retries, deterministic fallback; failures counted in metrics. |
| NFR-003 | Unit + integration tests run in < 10 s without network. |
| NFR-004 | No secrets in the repository; configuration via environment variables (`.env.example`). |
| NFR-005 | Answers in the language of the user (pt/en). |

## 6. Acceptance scenarios (official)
| # | Message | Expected plan | Expected evidence |
|---|---------|---------------|-------------------|
| 1 | What is the difference between the Get Clássica and the Get Smart? | knowledge | sources from KB |
| 2 | What is the weather forecast in Porto Alegre tomorrow? | knowledge (general_web) | web search tool call |
| 3 | When will the money from yesterday sales be deposited? | support | `get_settlement_forecast` |
| 4 | Do I need a bank account to receive my sales via Pix? | knowledge | sources from KB |
| 5 | My card machine will not connect to the internet, what should I do? | support → knowledge | `get_device_status` + KB |
| 6 | How does receivables advance (antecipação) work with Getnet? | knowledge | sources from KB |
| 7 | What is the euro exchange rate today? | knowledge (general_web) | web search tool call |
| 8 | My card machine is showing a transaction decline error. | support → knowledge | `get_transactions(status=declined)` + `get_device_status`; ISO 8583 code explained; ticket only for terminal-side errors |
| 9 | How many installments can I split a sale into with the crediário? | knowledge | sources from KB |
| 10 | Can I sell through WhatsApp using the Payment Link? | knowledge | sources from KB |

## 7. Out of scope
Authentication, persistence beyond process memory, multi-turn memory, voice, real Getnet APIs.
