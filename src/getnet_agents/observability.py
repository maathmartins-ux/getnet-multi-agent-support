"""Structured JSON logging + Prometheus metrics (BR-004)."""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUESTS = Counter("chat_requests_total", "Chat requests", ["intent", "mode", "outcome"])
LATENCY = Histogram("chat_request_latency_seconds", "End-to-end latency",
                    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30))
AGENT_LATENCY = Histogram("agent_step_latency_seconds", "Per-agent latency", ["agent"],
                          buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30))
GUARDRAIL_FLAGS = Counter("guardrail_flags_total", "Guardrail flags raised", ["flag", "stage"])
HANDOFFS = Counter("handoffs_total", "Human handoffs", ["reason"])
LLM_ERRORS = Counter("llm_errors_total", "Anthropic SDK/API errors by exception type", ["error_type"])
LLM_FALLBACKS = Counter("llm_fallbacks_total", "LLM failures that degraded to the deterministic path", ["agent"])
TOOL_CALLS = Counter("tool_calls_total", "Tool invocations", ["tool"])
RAG_EMPTY = Counter("rag_empty_retrievals_total", "Knowledge queries with no chunk above threshold")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel("WARNING")
    logging.getLogger("uvicorn.access").setLevel("WARNING")


def log_event(logger: logging.Logger, msg: str, **fields: Any) -> None:
    logger.info(msg, extra={"extra_fields": fields})


class Timer:
    def __enter__(self) -> Timer:
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self.ms = round((time.perf_counter() - self._t0) * 1000, 2)


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
