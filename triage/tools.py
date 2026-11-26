import json
import os
import ssl
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from prometheus_client import Counter, Histogram

from triage.domain import Evidence

METRIC_QUERIES = {
    "release_errors": 'increase(shop_fault_events_total{signal="release_errors"}[2m]) > 0',
    "slow_queries": 'increase(shop_fault_events_total{signal="slow_queries"}[2m]) > 0',
    "pool_full": 'increase(shop_fault_events_total{signal="pool_full"}[2m]) > 0',
    "redis_errors": 'increase(shop_fault_events_total{signal="redis_errors"}[2m]) > 0',
    "upstream_timeouts": 'increase(shop_fault_events_total{signal="upstream_timeouts"}[2m]) > 0',
    "cpu_throttling": (
        'rate(container_cpu_cfs_throttled_periods_total{namespace="oncall",container="shop"}[1m])'
        ' / rate(container_cpu_cfs_periods_total{namespace="oncall",container="shop"}[1m]) > 0.5'
    ),
}
K8S_PATHS = {
    "pods": "/api/v1/namespaces/oncall/pods?labelSelector=app%3Dshop",
    "events": "/api/v1/namespaces/oncall/events?fieldSelector=involvedObject.kind%3DPod",
    "deploys": "/apis/apps/v1/namespaces/oncall/replicasets?labelSelector=app%3Dshop",
}
CALLS = Counter("triage_tool_calls_total", "Evidence tool calls", ["tool", "status"])
LATENCY = Histogram("triage_tool_duration_seconds", "Evidence tool duration", ["tool"])


def fetch(url: str, headers: dict[str, str] | None = None,
          context: ssl.SSLContext | None = None) -> Any:
    with urlopen(Request(url, headers=headers or {}), timeout=3, context=context) as response:
        payload = response.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError("Evidence response exceeded size limit")
    return json.loads(payload)


def query_prometheus() -> list[Evidence]:
    host = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
    timestamp = datetime.now(UTC).isoformat()
    records = []
    for signal, query in METRIC_QUERIES.items():
        link = f"{host}/api/v1/query?{urlencode({'query': query, 'time': timestamp})}"
        try:
            result = fetch(link)
            if result["status"] != "success":
                raise ValueError("Prometheus query failed")
            signals = (signal,) if result["data"]["result"] else ()
            records.append(Evidence("prometheus", timestamp, link, signals, signal))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            records.append(Evidence("prometheus", timestamp, link,
                                    detail=f"{signal}: {type(exc).__name__}", error=True))
    return records


def query_logs() -> list[Evidence]:
    host = os.getenv("LOKI_URL", "http://loki:3100")
    params = {"query": '{app="shop"}', "start": time.time_ns() - 120_000_000_000, "limit": 30}
    link = f"{host}/loki/api/v1/query_range?{urlencode(params)}"
    result = fetch(link)
    return [Evidence("loki", datetime.fromtimestamp(int(ts) / 1e9, UTC).isoformat(),
                     link, detail=line[:1000])
            for stream in result["data"]["result"] for ts, line in stream["values"]]


def kubernetes(resource: str) -> list[Evidence]:
    path = K8S_PATHS[resource]
    mount = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    token = (mount / "token").read_text().strip()
    context = ssl.create_default_context(cafile=str(mount / "ca.crt"))
    link = f"https://kubernetes.default.svc{path}"
    result = fetch(link, {"Authorization": f"Bearer {token}"}, context)
    records = []
    for item in result["items"]:
        metadata = item["metadata"]
        timestamp = metadata["creationTimestamp"]
        detail = metadata["name"]
        signals = []
        if resource == "pods":
            for status in item.get("status", {}).get("containerStatuses", []):
                for state in ("state", "lastState"):
                    current = status.get(state, {})
                    ended = current.get("terminated", {})
                    if ended.get("reason") == "OOMKilled":
                        signals.append("oom_killed")
                        timestamp = ended.get("finishedAt", timestamp)
                    if ended.get("exitCode") == 78:
                        signals.append("bad_config")
                        timestamp = ended.get("finishedAt", timestamp)
        elif resource == "events":
            timestamp = item.get("lastTimestamp") or timestamp
            detail = item.get("message", detail)[:1000]
        else:
            detail += f" revision {metadata.get('annotations', {}).get('deployment.kubernetes.io/revision', '?')}"
        records.append(Evidence(resource, timestamp, link, tuple(set(signals)), detail))
    return records


def recent_deploys() -> list[Evidence]:
    return kubernetes("deploys")


TOOLS: dict[str, Callable[[], list[Evidence]]] = {
    "query_prometheus": query_prometheus,
    "query_logs": query_logs,
    "k8s_get": lambda: kubernetes("pods"),
    "k8s_events": lambda: kubernetes("events"),
    "recent_deploys": recent_deploys,
}


def call(name: str) -> list[Evidence]:
    tool = TOOLS[name]
    with LATENCY.labels(name).time():
        try:
            result = tool()
            status = "failed" if any(item.error for item in result) else "ok"
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result = [Evidence(name, datetime.now(UTC).isoformat(), "",
                               detail=type(exc).__name__, error=True)]
            status = "failed"
    CALLS.labels(name, status).inc()
    return result


def collect() -> list[Evidence]:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(TOOLS)) as executor:
        return [entry for batch in executor.map(call, TOOLS) for entry in batch]
