"""Offline eval runner for the multi-agent support system (BR-004 / FR-008).

Usage:
    python -m evals.run_evals [--dataset evals/dataset.jsonl] [--out evals/results/latest.json] [--llm]

Default mode builds the orchestrator with `llm_provider="offline"` and `web_search_provider="disabled"`, then
monkeypatches every network-bound tool so the suite is deterministic and runs without internet. `--llm` uses
`Settings()` (reads `.env`) so the same dataset measures the LLM path.

Exit code 1 when total routing accuracy < 0.9 (CI gate). No dependencies beyond requirements.txt.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from getnet_agents.api import build_orchestrator
from getnet_agents.config import Settings
from getnet_agents.orchestrator import Orchestrator
from getnet_agents.schemas import AgentName, ChatRequest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evals" / "dataset.jsonl"
DEFAULT_OUT = ROOT / "evals" / "results" / "latest.json"
SPLITS = ("official", "heldout", "guardrail")
ROUTING_GATE = 0.9


# --------------------------------------------------------------------------- setup
def load_dataset(path: Path | str = DEFAULT_DATASET) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            case = json.loads(raw)
            if "id" not in case or "message" not in case:
                raise ValueError(f"{path}:{line_no}: every case needs `id` and `message`")
            case.setdefault("split", "heldout")
            case.setdefault("user_id", "cliente1988")
            cases.append(case)
    return cases


def build(llm: bool = False) -> Orchestrator:
    settings = Settings() if llm else Settings(llm_provider="offline", web_search_provider="disabled")
    orch = build_orchestrator(settings)
    # Network isolation: the web tool returns nothing, so the agent still records the `web_search` tool
    # call but never leaves the machine. Keyless public APIs (weather / FX) are disabled when present.
    orch.web.search = lambda q, max_results=5: []  # type: ignore[method-assign]
    knowledge = orch.agents.get(AgentName.KNOWLEDGE)
    general = getattr(knowledge, "general", None)
    if general is not None:
        if hasattr(general, "weather_forecast"):
            general.weather_forecast = lambda city: None
        if hasattr(general, "exchange_rate"):
            general.exchange_rate = lambda base, quote="BRL": None
    return orch


# --------------------------------------------------------------------------- per-case
def _message(case: dict[str, Any]) -> str:
    text = case["message"]
    repeat = int(case.get("repeat_message") or 1)
    return text * repeat if repeat > 1 else text


def run_case(orch: Orchestrator, case: dict[str, Any]) -> dict[str, Any]:
    text = _message(case)
    t0 = time.perf_counter()
    obtained: dict[str, Any]
    try:
        req = ChatRequest(message=text, user_id=case["user_id"])
    except ValidationError as exc:
        # The API contract (schemas.ChatRequest) rejects the request before the orchestrator: FastAPI returns 422.
        # For the eval this counts as "blocked" at the schema layer.
        obtained = {"intent": None, "plan": None, "confidence": None, "tools_used": [], "handoff": False,
                    "handoff_queue": None, "blocked": True, "masked": False, "flags": ["request_validation"],
                    "answer": "", "agents_involved": [], "blocked_by": "schema",
                    "error": str(exc.errors()[0].get("msg", ""))[:200]}
        obtained["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return _score(case, obtained)
    resp = orch.handle(req)
    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    obtained = {
        "intent": resp.route.intent.value if resp.route else None,
        "plan": [a.value for a in resp.route.plan] if resp.route else None,
        "confidence": resp.route.confidence if resp.route else None,
        "tools_used": list(resp.tools_used),
        "handoff": resp.handoff is not None,
        "handoff_queue": resp.handoff.queue if resp.handoff else None,
        "blocked": resp.guardrails.blocked,
        "masked": resp.guardrails.masked,
        "flags": list(resp.guardrails.input_flags) + list(resp.guardrails.output_flags),
        "answer": resp.answer,
        "agents_involved": list(resp.agents_involved),
        "blocked_by": "guardrails" if resp.guardrails.blocked else None,
        "latency_ms": resp.latency_ms or elapsed,
    }
    return _score(case, obtained)


def _score(case: dict[str, Any], got: dict[str, Any]) -> dict[str, Any]:
    """Each check is None when not applicable to the case, True/False otherwise."""
    checks: dict[str, bool | None] = {}
    exp_intent = case.get("expected_intent")
    checks["routing"] = (got["intent"] == exp_intent) if exp_intent else None
    exp_plan = case.get("expected_plan")
    checks["plan"] = (got["plan"] == list(exp_plan)) if exp_plan else None
    exp_tools = case.get("expected_tools_any") or []
    checks["tools"] = set(exp_tools).issubset(set(got["tools_used"])) if exp_tools else None
    handoff_ok = got["handoff"] == bool(case.get("expected_handoff", False))
    if handoff_ok and case.get("expected_handoff_queue"):
        handoff_ok = got["handoff_queue"] == case["expected_handoff_queue"]
    checks["handoff"] = handoff_ok
    guard_ok = got["blocked"] == bool(case.get("expected_blocked", False))
    if guard_ok and "expected_masked" in case:
        guard_ok = got["masked"] == bool(case["expected_masked"])
    if guard_ok and case.get("expected_flags_any"):
        guard_ok = any(f in got["flags"] for f in case["expected_flags_any"])
    checks["guardrail"] = guard_ok
    kws = case.get("must_contain_any") or []
    answer_low = (got["answer"] or "").lower()
    checks["groundedness"] = any(k.lower() in answer_low for k in kws) if kws else None
    passed = all(v is not False for v in checks.values())
    expected_keys = ("expected_intent", "expected_plan", "expected_tools_any", "expected_handoff",
                     "expected_handoff_queue", "expected_blocked", "expected_masked", "expected_flags_any",
                     "must_contain_any")
    expected = {k: case.get(k) for k in expected_keys if k in case}
    got_public = {k: v for k, v in got.items() if k != "answer"}
    got_public["answer_preview"] = (got["answer"] or "")[:160]
    return {"id": case["id"], "split": case["split"], "message": case["message"][:120], "lang": case.get("lang"),
            "expected": expected, "obtained": got_public, "checks": checks, "passed": passed,
            "latency_ms": got["latency_ms"]}


# --------------------------------------------------------------------------- aggregate
def _rate(records: list[dict[str, Any]], check: str) -> tuple[float | None, int, int]:
    applicable = [r for r in records if r["checks"].get(check) is not None]
    if not applicable:
        return None, 0, 0
    ok = sum(1 for r in applicable if r["checks"][check])
    return round(ok / len(applicable), 4), ok, len(applicable)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(pct * (len(ordered) - 1))))
    return round(ordered[idx], 2)


def summarize_group(records: list[dict[str, Any]]) -> dict[str, Any]:
    lat = [r["latency_ms"] for r in records]
    out: dict[str, Any] = {"cases": len(records), "passed": sum(1 for r in records if r["passed"])}
    for key, check in (("routing_accuracy", "routing"), ("plan_accuracy", "plan"), ("tool_precision", "tools"),
                       ("handoff_accuracy", "handoff"), ("guardrail_accuracy", "guardrail"),
                       ("groundedness_keyword_rate", "groundedness")):
        rate, ok, n = _rate(records, check)
        out[key] = rate
        out[f"{key}_n"] = f"{ok}/{n}"
    out["latency_p50_ms"] = _percentile(lat, 0.50)
    out["latency_p95_ms"] = _percentile(lat, 0.95)
    return out


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_split = {s: summarize_group([r for r in records if r["split"] == s]) for s in SPLITS
                if any(r["split"] == s for r in records)}
    return {"splits": by_split, "total": summarize_group(records)}


# --------------------------------------------------------------------------- rendering
METRIC_COLUMNS = (("routing_accuracy", "routing"), ("plan_accuracy", "plan"), ("tool_precision", "tools"),
                  ("handoff_accuracy", "handoff"), ("guardrail_accuracy", "guardrail"),
                  ("groundedness_keyword_rate", "grounded-kw"))


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0%}"


def render_markdown(summary: dict[str, Any]) -> str:
    header = "| split | cases | pass | " + " | ".join(c for _, c in METRIC_COLUMNS) + " | p50 ms | p95 ms |"
    sep = "|" + "---|" * (len(METRIC_COLUMNS) + 5)
    rows = [header, sep]
    groups = list(summary["splits"].items()) + [("TOTAL", summary["total"])]
    for name, g in groups:
        cells = [name, str(g["cases"]), f"{g['passed']}/{g['cases']}"]
        cells += [_fmt(g[k]) for k, _ in METRIC_COLUMNS]
        cells += [str(g["latency_p50_ms"]), str(g["latency_p95_ms"])]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def render_failures(records: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for r in records:
        if r["passed"]:
            continue
        failed = [k for k, v in r["checks"].items() if v is False]
        got, exp = r["obtained"], r["expected"]
        lines.append(f"- [{r['split']}] {r['id']}: FAILED {failed} | msg={r['message']!r}")
        if "routing" in failed:
            lines.append(f"    intent   expected={exp.get('expected_intent')} got={got['intent']} "
                         f"conf={got.get('confidence')}")
        if "plan" in failed:
            lines.append(f"    plan     expected={exp.get('expected_plan')} got={got['plan']}")
        if "tools" in failed:
            lines.append(f"    tools    expected_all={exp.get('expected_tools_any')} got={got['tools_used']}")
        if "handoff" in failed:
            lines.append(f"    handoff  expected={exp.get('expected_handoff')}/{exp.get('expected_handoff_queue')} "
                         f"got={got['handoff']}/{got['handoff_queue']}")
        if "guardrail" in failed:
            lines.append(f"    guard    expected blocked={exp.get('expected_blocked')} masked={exp.get('expected_masked')} "
                         f"flags_any={exp.get('expected_flags_any')} got blocked={got['blocked']} "
                         f"masked={got['masked']} flags={got['flags']}")
        if "groundedness" in failed:
            lines.append(f"    answer   must_contain_any={exp.get('must_contain_any')} got={got['answer_preview']!r}")
    return "\n".join(lines) if lines else "(no failures)"


# --------------------------------------------------------------------------- entry points
def run(dataset: Path | str = DEFAULT_DATASET, out: Path | str | None = DEFAULT_OUT, llm: bool = False,
        orch: Orchestrator | None = None) -> dict[str, Any]:
    """Runs the whole dataset and returns {"meta", "summary", "cases"}; writes JSON to `out` when given."""
    cases = load_dataset(dataset)
    orch = orch or build(llm=llm)
    records = [run_case(orch, c) for c in cases]
    summary = summarize(records)
    report = {"meta": {"dataset": str(dataset), "mode": orch.mode, "model": orch.llm.model, "llm": llm,
                       "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "routing_gate": ROUTING_GATE},
              "summary": summary, "cases": records}
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--llm", action="store_true", help="use Settings() from .env (real LLM / web search)")
    args = parser.parse_args(argv)

    report = run(dataset=args.dataset, out=args.out, llm=args.llm)
    summary, records = report["summary"], report["cases"]
    print(f"# Eval report - mode={report['meta']['mode']} model={report['meta']['model']} dataset={args.dataset}\n")
    print(render_markdown(summary))
    print("\n## Failures\n" + render_failures(records))
    total_routing = summary["total"]["routing_accuracy"] or 0.0
    print(f"\nresults written to {args.out}")
    if total_routing < ROUTING_GATE:
        print(f"GATE FAILED: routing accuracy {total_routing:.2%} < {ROUTING_GATE:.0%}")
        return 1
    print(f"GATE OK: routing accuracy {total_routing:.2%} >= {ROUTING_GATE:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
