# Spec-Driven Development (SDD) — what it is and how it was applied here

## What it is

Spec-Driven Development inverts the usual order of AI-assisted coding: instead of prompting an agent with a vague request and reviewing whatever comes out, you first write a **specification** (what the system must do, with testable requirements), then a **plan** (how, with explicit architecture decisions), then a list of **tasks** derived from both, and only then let the coding agent implement — one task at a time, each closed by a test that traces back to a requirement. The spec, not the chat history, is the source of truth; a behaviour change starts by editing the spec.

The practice crystallised in 2025 around three tools, compared by Thoughtworks' Birgitta Böckeler on Martin Fowler's site:

| Tool | Approach | Artefacts |
|---|---|---|
| **GitHub Spec Kit** (open source CLI) | Agent-agnostic workflow with a project *constitution* of guiding principles, then `/specify → /plan → /tasks → /implement` | `constitution.md`, `spec.md`, `plan.md`, `data-model.md`, `tasks.md` |
| **AWS Kiro** (IDE + CLI) | Requirements → design → tasks, with "steering" files and agent hooks | `requirements.md`, `design.md`, `tasks.md` |
| **Tessl** | "Spec-as-source": the spec is the maintained artefact, code is regenerated from it | spec files per module |

Böckeler distinguishes three maturity levels — *spec-first* (write the spec, then code), *spec-anchored* (keep the spec alive and consistent with the code), *spec-as-source* (only the spec is edited). The Thoughtworks Technology Radar lists the technique under **Assess**, noting that the workflows are opinionated and that generated spec files can be hard to review.

References (checked 2026-10-30):

- Birgitta Böckeler, "Understanding Spec-Driven Development: Kiro, spec-kit, and Tessl", martinfowler.com — <https://www.martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html>
- Thoughtworks Technology Radar, "Spec-driven development" (Assess) — <https://www.thoughtworks.com/radar/techniques/spec-driven-development>
- GitHub Spec Kit — <https://github.com/github/spec-kit>
- AWS Kiro — <https://kiro.dev/>
- Tessl — <https://tessl.io/>

## How it was applied in this project

This repository follows the Spec Kit shape (`.specify/` + `specs/<feature>/`), at the **spec-first → spec-anchored** level: the spec was written before any code, and every test and module names the requirement it satisfies, so the spec stays checkable against the code.

```
1. .specify/memory/constitution.md
   Five articles: spec first · reliability over cleverness (offline mode, timeouts,
   never invent data) · observability by default · safety (guardrails, handoff) · simplicity.
        │
2. specs/001-multi-agent-support/spec.md
   Problem statement, 6 user stories, FR-001…FR-010, BR-001…BR-004, NFR-001…NFR-005,
   the 10 official acceptance scenarios, out-of-scope list. Each requirement has a "Verified by" column.
        │
3. specs/001-multi-agent-support/plan.md  +  data-model.md
   Tech context, 6 ADRs (orchestrator + typed envelope, BM25 over embeddings, OfflineLLM,
   prompts as markdown, guardrails as pure functions, handoff on low confidence), workflow,
   RAG pipeline, project structure. data-model.md = the entities that became schemas.py.
        │
4. specs/001-multi-agent-support/tasks.md
   22 tasks in 5 phases (Setup → Contracts & core → RAG & tools → Agents & orchestration →
   Verification → Docs). Every task names the requirement it closes, e.g. "T016 Orchestrator (FR-006, BR-003)".
        │
5. Implementation, one task at a time → 6. Verification (pytest + evals) → 7. Docs
```

### The role of `tasks.md`

`tasks.md` is the **executable plan** and the contract between the human and the coding agent:

- It turns the spec into a dependency-ordered checklist small enough that each item is one focused change with one obvious test.
- A task is marked `[x]` only when its test passes (Constitution, Article I.3) — not when the code "looks done".
- Because every task carries requirement IDs, the file doubles as the traceability matrix: `FR → task → module → test` (rendered in the README, Section 11).
- When scope changed during implementation (e.g. adding `tools/general.py` for weather/exchange-rate structured lookups), the change entered through the spec/plan first and then appeared as a task, keeping the spec anchored.

### Evidence in the repository

- `git log --oneline --reverse`: the first commit is `spec: constitution, feature spec, plan, data model and tasks (SDD phase 1)`; code commits follow.
- Module docstrings cite requirements (`orchestrator.py`: "FR-006, BR-003"; `guardrails.py`: "BR-002"; `tools/crm.py`: "FR-005 … BR-001").
- Tests are named or documented by requirement; `spec.md` lists the test file that verifies each FR/BR.

### What SDD bought here, concretely

- **Scope control**: the out-of-scope list (auth, persistence, multi-turn) was written before coding, so nothing half-built leaked into the delivery.
- **Reviewability**: an evaluator can read `spec.md` (one page) and check each requirement against a named test instead of reverse-engineering intent from code.
- **Reliable agent output**: the coding agent worked on bounded tasks with a known acceptance test, which is where LLM-generated code is most dependable.
- **Honest limitations**: gaps found while researching the corpus (`data/knowledge/SOURCES.md`) and architectural trade-offs (ADRs) are recorded as decisions, not hidden.
