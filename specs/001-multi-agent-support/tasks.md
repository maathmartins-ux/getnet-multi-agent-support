# Tasks — 001-multi-agent-support

Legend: `[x]` done · `[ ]` pending · each task names the requirement it closes.

## Phase 0 — Setup
- [x] T001 Repository, pyproject, requirements, Docker, Makefile, `.env.example` (NFR-004)
- [x] T002 Constitution + spec + plan + data model (SDD artefacts)

## Phase 1 — Contracts & core
- [x] T003 `schemas.py` contracts (FR-001, FR-006)
- [x] T004 `llm.py` — protocol, Anthropic implementation with tool loop, OfflineLLM (NFR-001, NFR-002)
- [x] T005 `guardrails.py` (BR-002)
- [x] T006 `observability.py` — JSON logs + metrics (BR-004)

## Phase 2 — RAG & tools
- [x] T007 `rag/store.py` chunking + BM25 (FR-003)
- [x] T008 `rag/ingest.py` URL ingestion CLI (FR-003)
- [x] T009 Knowledge corpus `data/knowledge/*.md` from getnet.net (FR-003)
- [x] T010 `tools/crm.py` — 5 customer tools + seed data (FR-005)
- [x] T011 `tools/web_search.py` — Tavily/DuckDuckGo (FR-004)

## Phase 3 — Agents & orchestration
- [x] T012 Router Agent + prompt (FR-002)
- [x] T013 Knowledge Agent + prompt (FR-003, FR-004)
- [x] T014 Customer Support Agent + prompt (FR-005, FR-007)
- [x] T015 Human Escalation Agent + prompt (BR-001, BR-003)
- [x] T016 Orchestrator (FR-006, BR-003)
- [x] T017 FastAPI app `/chat` `/health` `/metrics` (FR-001, FR-009)

## Phase 4 — Verification
- [ ] T018 Unit tests: router, guardrails, rag, tools (FR-002, BR-002, FR-003, FR-005)
- [ ] T019 Integration tests: API + 10 official scenarios (FR-001, FR-008)
- [ ] T020 Eval dataset + runner (BR-004)
- [ ] T021 Docker build + compose run verified (FR-009)

## Phase 5 — Docs
- [ ] T022 README (FR-010), testing strategy, observability/eval strategy, video script
