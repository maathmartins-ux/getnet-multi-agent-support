"""FastAPI application (FR-001, FR-009): POST /chat, GET /health, GET /metrics."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from . import __version__
from .agents import EscalationAgent, KnowledgeAgent, RouterAgent, SupportAgent
from .config import Settings, get_settings
from .llm import build_llm
from .observability import configure_logging, log_event, metrics_payload
from .orchestrator import Orchestrator
from .rag.store import KnowledgeBase
from .schemas import AgentName, ChatRequest, ChatResponse
from .tools.crm import CRM
from .tools.general import GeneralTools
from .tools.web_search import WebSearchTool

BASE_DIR = Path(__file__).resolve().parents[2]
log = logging.getLogger("api")


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else BASE_DIR / p


def build_orchestrator(settings: Settings) -> Orchestrator:
    llm = build_llm(settings.effective_llm_provider, settings.anthropic_api_key, settings.anthropic_model,
                    timeout_s=settings.llm_timeout_s, max_retries=settings.llm_max_retries)
    kb = KnowledgeBase.from_directory(resolve(settings.knowledge_dir))
    crm = CRM.from_json(resolve(settings.crm_path))
    web = WebSearchTool(settings.web_search_provider, settings.tavily_api_key)
    router = RouterAgent(llm, model=settings.anthropic_router_model if not llm.offline else None)
    escalation = EscalationAgent(llm, crm, webhook_url=settings.handoff_webhook_url)
    agents = {
        AgentName.KNOWLEDGE: KnowledgeAgent(llm, kb, web, top_k=settings.rag_top_k, general=GeneralTools()),
        AgentName.SUPPORT: SupportAgent(llm, crm),
        AgentName.ESCALATION: escalation,
    }
    orch = Orchestrator(settings, llm, router, agents, escalation)
    orch.kb, orch.crm, orch.web = kb, crm, web  # exposed for /health and tests
    return orch


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_level)
        app.state.settings = settings
        app.state.orchestrator = build_orchestrator(settings)
        orch = app.state.orchestrator
        log_event(log, "startup", mode=orch.mode, model=orch.llm.model, kb_documents=len(orch.kb.documents),
                  kb_chunks=len(orch.kb.chunks), web_search=orch.web.provider, environment=settings.environment)
        yield

    app = FastAPI(
        title="Getnet Multi-Agent Support System",
        version=__version__,
        description="Router → Knowledge (RAG + web search) → Customer Support (tools) → Human Escalation. "
                    "Send `POST /chat` with `{message, user_id}`.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # noqa: ANN001
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"error": "internal_error", "detail": str(exc)[:200]})

    @app.post("/chat", response_model=ChatResponse, summary="Send a message to the multi-agent system")
    def chat(req: ChatRequest, request: Request) -> ChatResponse:
        return request.app.state.orchestrator.handle(req)

    @app.get("/health", summary="Liveness + runtime mode")
    def health(request: Request) -> dict:
        orch: Orchestrator = request.app.state.orchestrator
        return {"status": "ok", "version": __version__, "mode": orch.mode, "model": orch.llm.model,
                "kb_documents": len(orch.kb.documents), "kb_chunks": len(orch.kb.chunks),
                "web_search": orch.web.provider, "customers": len(orch.crm.customers)}

    @app.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
    def metrics() -> Response:
        payload, content_type = metrics_payload()
        return Response(content=payload, media_type=content_type)

    return app


app = create_app()
