import argparse
import json
import re
import subprocess
import time
from typing import cast

from triage.domain import CAUSES
from triage.engine import State
from triage.evaluate import score

KUBECTL = ["kubectl", "--context", "kind-oncall", "-n", "oncall"]
ALERTS = {
    "bad-deploy": "ShopHighErrorRate",
    "slow-query": "ShopHighLatency",
    "db-leak": "ShopDatabasePoolExhausted",
    "oom": "ShopRestarting",
    "crash-loop": "ShopRestarting",
    "redis-down": "ShopHighErrorRate",
    "dependency-timeout": "ShopHighErrorRate",
    "cpu-throttle": "ShopCPUThrottled",
}


def kubectl(*args: str) -> str:
    return subprocess.run([*KUBECTL, *args], check=True, stdout=subprocess.PIPE,
                          text=True, timeout=30).stdout


def rollout(name: str) -> None:
    kubectl("rollout", "status", f"deployment/{name}", "--timeout=25s")


def reports() -> set[str]:
    names = kubectl("exec", "deployment/triage", "--", "ls", "-1", "/reports").splitlines()
    return {name for name in names if re.fullmatch(r"[a-f0-9]{20}\.md", name)}


def wait_for_report(previous: set[str], started: float, timeout: int,
                    alert: str) -> tuple[State, float]:
    while time.monotonic() - started < timeout:
        fresh = sorted(reports() - previous)
        for name in fresh:
            previous.add(name)
            doc = kubectl("exec", "deployment/triage", "--", "cat", f"/reports/{name}")
            if match := re.search(r"^<!-- triage-eval (.+) -->$", doc, re.MULTILINE):
                state = cast(State, json.loads(match[1]))
                if state.get("alert_name") == alert:
                    return state, (time.monotonic() - started) * 1000
        time.sleep(2)
    return {"hypotheses": [], "model_status": "no report", "tokens": 0}, timeout * 1000


def fault(action: str, name: str | None = None) -> None:
    subprocess.run(["./faultctl", action, *([name] if name else [])], check=True, timeout=30)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score injected faults on the kind demo")
    parser.add_argument("--mode", choices=("rules", "model", "hybrid"), default="rules")
    parser.add_argument("--fault", choices=tuple(CAUSES), action="append")
    parser.add_argument("--timeout", type=int, default=75)
    parser.add_argument("--require-top1", action="store_true")
    args = parser.parse_args()
    rollout("triage")
    kubectl("set", "env", "deployment/triage", f"TRIAGE_MODE={args.mode}")
    rollout("triage")
    rows = []
    try:
        for index, name in enumerate(args.fault or CAUSES):
            fault("clear")
            rollout("redis")
            rollout("shop")
            if index:
                # The metric evidence uses a two-minute lookback.
                time.sleep(125)
            previous = reports()
            started = time.monotonic()
            fault("inject", name)
            state, elapsed_ms = wait_for_report(previous, started, args.timeout, ALERTS[name])
            print(f"{name}: {state['hypotheses']} ({elapsed_ms / 1000:.1f}s, "
                  f"{state['model_status']})", flush=True)
            rows.append((name, state, elapsed_ms))
    finally:
        fault("clear")
    print("| Mode | Top 1 | Top 3 | Confident and wrong | Mean ms | Live calls | Tokens | Cost | Model used |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    print(f"| {args.mode} | {score(rows)} |")
    if any(state["model_status"] == "no report" for _, state, _ in rows):
        raise SystemExit("At least one injected fault produced no report")
    if args.require_top1 and any(
        not state["hypotheses"] or state["hypotheses"][0][0] != expected
        for expected, state, _ in rows
    ):
        raise SystemExit("At least one injected fault was ranked incorrectly")


if __name__ == "__main__":
    main()
