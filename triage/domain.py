from dataclasses import dataclass
from pathlib import Path

RUNBOOKS = Path(__file__).resolve().parents[1] / "runbooks"


@dataclass(frozen=True)
class Cause:
    title: str
    signals: tuple[str, ...]
    command: str
    rollback: str = "Reapply the previously reviewed configuration if recovery fails."


CAUSES = {
    "bad-deploy": Cause("New shop deployment serves errors", ("release_errors",),
                        "kubectl --context kind-oncall -n oncall rollout undo deployment/shop"),
    "slow-query": Cause("Slow database query", ("slow_queries",),
                        "./faultctl clear"),
    "db-leak": Cause("Database connections exhausted", ("pool_full",),
                     "./faultctl clear"),
    "oom": Cause("Shop container exceeded its memory limit", ("oom_killed",),
                 "./faultctl clear"),
    "crash-loop": Cause("Shop startup configuration is invalid", ("bad_config",),
                        "./faultctl clear"),
    "redis-down": Cause("Redis unavailable", ("redis_errors",),
                        "kubectl --context kind-oncall -n oncall scale deployment/redis --replicas=1",
                        "kubectl --context kind-oncall -n oncall scale deployment/redis --replicas=0"),
    "dependency-timeout": Cause("Upstream dependency timed out", ("upstream_timeouts",),
                                "./faultctl clear"),
    "cpu-throttle": Cause("Shop container CPU throttled", ("cpu_throttling",),
                          "./faultctl clear"),
}


@dataclass(frozen=True)
class Evidence:
    source: str
    timestamp: str
    link: str
    signals: tuple[str, ...] = ()
    detail: str = ""
    error: bool = False


def rank(evidence: list[Evidence]) -> list[tuple[str, float]]:
    observed = {signal for item in evidence if not item.error for signal in item.signals}
    return [(key, 0.9) for key, cause in CAUSES.items() if observed.intersection(cause.signals)]
