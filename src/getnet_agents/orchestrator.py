"""Orchestrator (FR-006, BR-003): guardrails -> router -> plan execution -> escalation -> response.

One request, one synchronous pass, every step traced. Read this file top to bottom to understand the
whole system.
"""

from __future__ import annotations

import logging
import uuid

from .agents.base import BaseAgent
from .agents.escalation import EscalationAgent
from .agents.router import RouterAgent, detect_language
from .config import Settings
from .guardrails import PII_WARNING, check_input, check_output
from .llm import LLM
from .observability import AGENT_LATENCY, GUARDRAIL_FLAGS, LATENCY, LLM_FALLBACKS, REQUESTS, TOOL_CALLS, Timer, log_event
from .schemas import AgentMessage, AgentName, AgentResult, ChatRequest, ChatResponse, GuardrailReport, TraceStep

log = logging.getLogger("orchestrator")


class Orchestrator:
    def __init__(self, settings: Settings, llm: LLM, router: RouterAgent,
                 agents: dict[AgentName, BaseAgent], escalation: EscalationAgent) -> None:
        self.settings = settings
        self.llm = llm
        self.router = router
        self.agents = agents
        self.escalation = escalation
        self.mode = "offline" if llm.offline else llm.name

    # ------------------------------------------------------------------ public API
    def handle(self, req: ChatRequest) -> ChatResponse:
        request_id = uuid.uuid4().hex[:12]
        trace: list[TraceStep] = []
        guard = GuardrailReport()
        with Timer() as total:
            # 1. input guardrails ------------------------------------------------------------
            with Timer() as t:
                chk = check_input(req.message, max_chars=self.settings.max_message_chars)
            language = detect_language(req.message)
            guard.input_flags, guard.blocked, guard.masked = chk.flags, chk.blocked, chk.masked
            for flag in chk.flags:
                GUARDRAIL_FLAGS.labels(flag, "input").inc()
            trace.append(TraceStep(agent="guardrails", action="input_check", duration_ms=t.ms,
                                   detail={"flags": chk.flags, "blocked": chk.blocked}))
            if chk.blocked:
                REQUESTS.labels("blocked", self.mode, "blocked").inc()
                return self._response(request_id, req, chk.block_message(language), None, ["guardrails"], [], guard,
                                      trace, total)

            msg = AgentMessage(request_id=request_id, user_id=req.user_id, text=chk.text, language=language)

            # 2. routing ---------------------------------------------------------------------
            with Timer() as t:
                routed = self.router.handle(msg)
            route = routed.data["route"]
            msg.route, msg.language = route, route.language
            if routed.llm_fallback:
                LLM_FALLBACKS.labels("router").inc()
            trace.append(TraceStep(agent="router", action="route", duration_ms=t.ms,
                                   detail={"intent": route.intent, "plan": [a.value for a in route.plan],
                                           "confidence": route.confidence, "source": route.source,
                                           "language": route.language, "llm_fallback": routed.llm_fallback}))
            plan = list(route.plan)
            if route.confidence < self.settings.router_confidence_threshold and plan != [AgentName.ESCALATION]:
                msg.context["escalation_reason"] = "low_confidence"
                plan = [AgentName.ESCALATION]
                trace.append(TraceStep(agent="orchestrator", action="low_confidence_handoff", duration_ms=0.0,
                                       detail={"threshold": self.settings.router_confidence_threshold}))

            # 3. plan execution --------------------------------------------------------------
            results: list[AgentResult] = []
            for name in plan:
                res = self._run(self.agents[name], msg, trace)
                results.append(res)
                if res.needs_escalation and name != AgentName.ESCALATION:
                    msg.context["escalation_reason"] = res.escalation_reason
                    results.append(self._run(self.escalation, msg, trace))
                    break

            # 4. compose + output guardrails ---------------------------------------------------
            answer = "\n\n".join(r.answer.strip() for r in results if r.answer.strip())
            if any(f.startswith("pii_") for f in chk.flags):
                answer = f"{PII_WARNING[msg.language]}\n\n{answer}"
            answer, out_flags = check_output(answer)
            guard.output_flags = out_flags
            for flag in out_flags:
                GUARDRAIL_FLAGS.labels(flag, "output").inc()
            handoff = next((r.handoff for r in results if r.handoff), None)
            REQUESTS.labels(route.intent.value, self.mode, "handoff" if handoff else "answered").inc()
            return self._response(request_id, req, answer, route, ["router"] + [r.agent.value for r in results],
                                  results, guard, trace, total)

    # ------------------------------------------------------------------ helpers
    def _run(self, agent: BaseAgent, msg: AgentMessage, trace: list[TraceStep]) -> AgentResult:
        with Timer() as t:
            res = agent.handle(msg)
        AGENT_LATENCY.labels(agent.name.value).observe(t.ms / 1000)
        if res.llm_fallback:
            LLM_FALLBACKS.labels(agent.name.value).inc()
        for c in res.tool_calls:
            TOOL_CALLS.labels(c.name).inc()
        trace.append(TraceStep(agent=agent.name.value, action="handle", duration_ms=t.ms,
                               detail={"tools": [c.name for c in res.tool_calls], "sources": len(res.sources),
                                       "confidence": res.confidence, "needs_escalation": res.needs_escalation,
                                       "llm_fallback": res.llm_fallback}))
        msg.context.update(res.data)
        msg.history.append(res)
        return res

    def _response(self, request_id: str, req: ChatRequest, answer: str, route, agents: list[str],  # noqa: ANN001
                  results: list[AgentResult], guard: GuardrailReport, trace: list[TraceStep], total: Timer) -> ChatResponse:
        total.__exit__(None, None, None)
        LATENCY.observe(total.ms / 1000)
        resp = ChatResponse(
            request_id=request_id, user_id=req.user_id, answer=answer, route=route, agents_involved=agents,
            sources=[s for r in results for s in r.sources], tools_used=[c.name for r in results for c in r.tool_calls],
            handoff=next((r.handoff for r in results if r.handoff), None), guardrails=guard, trace=trace,
            latency_ms=total.ms, mode=self.mode, model=self.llm.model,
        )
        log_event(log, "chat.completed", request_id=request_id, user_id=req.user_id,
                  intent=route.intent.value if route else "blocked", plan=agents, latency_ms=total.ms,
                  tools=resp.tools_used, handoff=bool(resp.handoff), guardrail_flags=guard.input_flags + guard.output_flags,
                  mode=self.mode)
        return resp
