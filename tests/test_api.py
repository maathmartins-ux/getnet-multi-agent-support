"""HTTP API (FR-001, FR-009): POST /chat contract, GET /health, GET /metrics, validation."""

from __future__ import annotations

CHAT_KEYS = {"request_id", "user_id", "answer", "route", "agents_involved", "sources", "tools_used", "handoff",
             "guardrails", "trace", "latency_ms", "mode", "model"}


def test_chat_contract(client):
    """FR-001: POST /chat accepts {message, user_id} and returns the documented JSON shape."""
    r = client.post("/chat", json={"message": "How does receivables advance (antecipação) work with Getnet?",
                                   "user_id": "cliente1988"})
    assert r.status_code == 200
    body = r.json()
    assert CHAT_KEYS <= set(body)
    assert body["user_id"] == "cliente1988" and body["answer"]
    assert set(body["route"]) >= {"plan", "intent", "confidence", "language", "source"}
    assert body["route"]["intent"] == "getnet_product" and body["route"]["plan"] == ["knowledge"]
    assert body["agents_involved"] == ["router", "knowledge"]
    assert body["sources"] and {"title", "url", "score", "snippet", "kind"} <= set(body["sources"][0])
    assert body["tools_used"] == [] and body["handoff"] is None
    assert set(body["guardrails"]) == {"input_flags", "output_flags", "blocked", "masked"}
    assert body["mode"] == "offline" and body["model"] is None
    assert isinstance(body["latency_ms"], (int, float))


def test_chat_handoff_payload(client):
    """FR-001 / BR-001: handoff carries ticket_id, queue, priority and reason."""
    r = client.post("/chat", json={"message": "Quero falar com um atendente humano", "user_id": "cliente1988"})
    body = r.json()
    assert body["handoff"] is not None
    assert {"ticket_id", "queue", "priority", "reason", "status", "notified"} <= set(body["handoff"])
    assert body["handoff"]["ticket_id"].startswith("GN-")
    assert body["route"]["plan"] == ["escalation"]
    assert "open_support_ticket" in body["tools_used"]


def test_chat_validation_errors(client):
    """FR-001: malformed requests are rejected with 422 before any agent runs."""
    assert client.post("/chat", json={"message": "", "user_id": "cliente1988"}).status_code == 422
    assert client.post("/chat", json={"message": "oi"}).status_code == 422
    assert client.post("/chat", json={"message": "oi", "user_id": "bad id!"}).status_code == 422
    assert client.post("/chat", json={"message": "x" * 4001, "user_id": "cliente1988"}).status_code == 422
    assert client.post("/chat", content="not json", headers={"content-type": "application/json"}).status_code == 422


def test_health(client):
    """FR-009: /health reports status, mode and corpus size."""
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["mode"] == "offline"
    assert body["kb_documents"] >= 10 and body["kb_chunks"] > 50
    assert body["web_search"] == "disabled" and body["customers"] >= 2
    assert "version" in body


def test_metrics_endpoint(client):
    """BR-004: /metrics exposes Prometheus text including the request counter."""
    client.post("/chat", json={"message": "Quais as taxas do Pix?", "user_id": "cliente1988"})
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "chat_requests_total" in r.text
    assert "chat_request_latency_seconds" in r.text


def test_openapi_documents_chat(client):
    """FR-001 / FR-010: the OpenAPI schema documents POST /chat with the ChatResponse model."""
    schema = client.get("/openapi.json").json()
    assert "/chat" in schema["paths"] and "post" in schema["paths"]["/chat"]
    assert "ChatResponse" in schema["components"]["schemas"]
