import argparse
import json
import time
from pathlib import Path
from statistics import mean
from typing import Any

from triage.domain import Evidence
from triage.engine import State, investigate

TABLE = ("| Mode | Top 1 | Top 3 | Confident and wrong | Mean ms | Mean alert-to-report ms | "
         "Live calls | Tokens | Cost | Model used |\n"
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "replay.json"


def score(rows: list[tuple[str, State, float]]) -> str:
    hypotheses = [state["hypotheses"] for _, state, _ in rows]
    correct = [bool(ranks and ranks[0][0] == expected)
               for (expected, _, _), ranks in zip(rows, hypotheses, strict=True)]
    top_three = [expected in [key for key, _ in ranks[:3]]
                 for (expected, _, _), ranks in zip(rows, hypotheses, strict=True)]
    false_confidence = [bool(ranks and ranks[0][1] >= 0.8 and not hit)
                        for ranks, hit in zip(hypotheses, correct, strict=True)]
    used = sum(state["model_status"] == "used" for _, state, _ in rows)
    tokens = sum(state["tokens"] for _, state, _ in rows)
    alert_latencies = [state["alert_to_report_ms"] for _, state, _ in rows
                       if state.get("alert_to_report_ms") is not None]
    alert_ms = f"{mean(alert_latencies):.2f}" if alert_latencies else "—"
    return (f"{mean(correct):.0%} | {mean(top_three):.0%} | "
            f"{mean(false_confidence):.0%} | {mean(ms for _, _, ms in rows):.2f} | {alert_ms} | "
            f"{mean(state.get('tool_calls', 0) for _, state, _ in rows):.1f} | {tokens} | $0.00 | {used}/{len(rows)}")


def run_case(case: dict[str, Any], mode: str, graph: bool) -> tuple[str, State, float]:
    evidence = [Evidence("fixture", "2026-01-01T00:00:00Z", f"fixtures/replay.json#{case['id']}",
                         tuple(case["signals"]), case["detail"])]
    started = time.monotonic()
    state = investigate(case["id"], lambda: evidence, mode, graph=graph)
    return case["expected"], state, (time.monotonic() - started) * 1000


def main() -> None:
    parser = argparse.ArgumentParser(description="Score saved incident evidence")
    parser.add_argument("--graph", action="store_true")
    parser.add_argument("--mode", choices=("rules", "model", "hybrid"))
    parser.add_argument("--require-model", action="store_true")
    args = parser.parse_args()
    cases = json.loads(FIXTURES.read_text())
    print(TABLE)
    incomplete = False
    for mode in (args.mode,) if args.mode else ("rules", "model", "hybrid"):
        rows = [run_case(case, mode, args.graph) for case in cases]
        print(f"| {mode} | {score(rows)} |")
        if mode != "rules" and any(state["model_status"] != "used" for _, state, _ in rows):
            incomplete = True
    if args.require_model and incomplete:
        raise SystemExit("The model was unavailable on at least one fixture")


if __name__ == "__main__":
    main()
