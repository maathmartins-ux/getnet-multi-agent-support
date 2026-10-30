"""Shared fixtures. Everything runs offline: no LLM key, no web search, no network (NFR-001, NFR-003)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from getnet_agents.api import build_orchestrator, create_app
from getnet_agents.config import Settings
from getnet_agents.schemas import AgentMessage, RouteDecision
from getnet_agents.tools.crm import CRM

TODAY = date(2026, 10, 30)  # a Friday; 31/10 is Saturday and 02/11 (Finados) is a national holiday
USER = "cliente1988"


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(llm_provider="offline", web_search_provider="disabled", environment="test")


@pytest.fixture(scope="session")
def orchestrator(settings):
    return build_orchestrator(settings)


@pytest.fixture(scope="session")
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def crm(settings) -> CRM:
    """Fresh CRM pinned to a fixed date so settlement expectations are deterministic."""
    from getnet_agents.api import resolve

    return CRM.from_json(resolve(settings.crm_path), today=TODAY)


def make_msg(text: str, *, user_id: str = USER, route: RouteDecision | None = None, language: str | None = None,
             context: dict | None = None) -> AgentMessage:
    from getnet_agents.agents.router import heuristic_route

    route = route or heuristic_route(text)
    return AgentMessage(request_id="test-req", user_id=user_id, text=text, language=language or route.language,
                        route=route, context=context or {})
