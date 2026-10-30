"""BR-004 / FR-008: regression gate over the eval dataset (offline, deterministic, no network).

Runs `evals.run_evals.run` in-process (not a subprocess) against `evals/dataset.jsonl` and asserts the
quality floors agreed in the spec: routing >= 0.9 on the official scenarios, >= 0.8 on held-out paraphrases,
and every guardrail case behaving exactly as expected.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from evals.run_evals import DEFAULT_DATASET, build, run

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    out = tmp_path_factory.mktemp("evals") / "regression.json"
    orch = build(llm=False)
    assert orch.mode == "offline", "regression suite must not depend on an LLM provider"
    return run(dataset=DEFAULT_DATASET, out=out, llm=False, orch=orch)


def _failures(report: dict, split: str, check: str) -> list[str]:
    return [f"{c['id']}: expected={c['expected']} obtained={c['obtained']}"
            for c in report["cases"] if c["split"] == split and c["checks"].get(check) is False]


def test_dataset_covers_every_split(report: dict) -> None:
    splits = report["summary"]["splits"]
    assert splits["official"]["cases"] == 10, "spec section 6 defines exactly 10 official scenarios"
    assert splits["heldout"]["cases"] >= 20
    assert splits["guardrail"]["cases"] >= 5


def test_official_routing_accuracy(report: dict) -> None:
    acc = report["summary"]["splits"]["official"]["routing_accuracy"]
    assert acc >= 0.9, f"official routing accuracy {acc:.2%} < 90%\n" + "\n".join(_failures(report, "official", "routing"))


def test_heldout_routing_accuracy(report: dict) -> None:
    acc = report["summary"]["splits"]["heldout"]["routing_accuracy"]
    assert acc >= 0.8, f"heldout routing accuracy {acc:.2%} < 80%\n" + "\n".join(_failures(report, "heldout", "routing"))


def test_guardrail_accuracy_is_perfect(report: dict) -> None:
    acc = report["summary"]["splits"]["guardrail"]["guardrail_accuracy"]
    assert acc == 1.0, "guardrail failures:\n" + "\n".join(_failures(report, "guardrail", "guardrail"))


def test_total_routing_gate(report: dict) -> None:
    """Same gate `python -m evals.run_evals` enforces with its exit code."""
    assert report["summary"]["total"]["routing_accuracy"] >= 0.9


def test_results_json_written(report: dict) -> None:
    assert report["meta"]["mode"] == "offline"
    assert len(report["cases"]) == report["summary"]["total"]["cases"]
