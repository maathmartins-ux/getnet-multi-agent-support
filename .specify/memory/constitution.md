# Constitution — Getnet Multi-Agent Support System

> Spec-Driven Development (SDD): the specification is the source of truth. Code, tests and docs
> are derived from `specs/001-multi-agent-support/`. Any behaviour change starts by editing the spec.

## Article I — Spec first
1. Every functional requirement has an ID (`FR-xxx`), every non-functional one `NFR-xxx`, every bonus `BR-xxx`.
2. Tests reference the requirement they verify (`# FR-003` in the test name or docstring).
3. `tasks.md` is the executable plan; a task is done only when its test passes.

## Article II — Reliability over cleverness
1. The system must answer with **zero external dependencies** (no API key, no network) in a degraded
   but honest mode. The LLM is an accelerator, not a single point of failure.
2. Every LLM call has a timeout, bounded retries and a deterministic fallback.
3. The system must never invent customer data or Getnet facts: answers are grounded in retrieved
   chunks or tool results, otherwise they hand off to a human.

## Article III — Observability by default
1. Every request carries a `request_id`; every agent step is traced with latency and emitted as a
   structured JSON log line and as Prometheus metrics.
2. The trace is returned in the API response so evaluators can see the orchestration without a dashboard.

## Article IV — Safety
1. Input guardrails run **before** routing (PII masking, prompt-injection, unsafe content).
2. Output guardrails run **after** generation (PII leak masking).
3. Low confidence => human handoff, never a confident-sounding guess.

## Article V — Simplicity
1. Standard library first; dependencies only when they buy reliability (FastAPI, Pydantic, httpx, anthropic, prometheus-client).
2. One module per responsibility, no framework magic. A reader must be able to follow one request end to end in `orchestrator.py`.
