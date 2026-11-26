from triage.domain import Evidence
from triage.engine import State, investigate
from triage.evaluate import score


def test_scoring_counts_top_one_top_three_and_confident_errors():
    runs: list[tuple[str, State, float]] = [
        ("oom", {"hypotheses": [("oom", 0.9)], "model_status": "disabled", "tokens": 0}, 10),
        ("oom", {"hypotheses": [("db-leak", 0.8), ("oom", 0.7)],
                 "model_status": "used", "tokens": 10}, 20),
        ("oom", {"hypotheses": [("db-leak", 0.79), ("slow-query", 0.7),
                                ("bad-deploy", 0.6), ("oom", 0.5)],
                 "model_status": "used", "tokens": 15}, 30),
        ("oom", {"hypotheses": [], "model_status": "disabled", "tokens": 0}, 40),
    ]
    assert score(runs).split(" | ") == [
        "25%", "50%", "25%", "25.00", "—", "0.0", "25", "$0.00", "2/4",
    ]


def test_langgraph_matches_sequential_report_and_hypotheses():
    records = [
        Evidence("pods", "2026-01-01T00:00:00Z", "/pods", ("oom_killed",)),
        Evidence("logs", "2026-01-01T00:00:01Z", "/logs", error=True),
    ]

    def collect() -> list[Evidence]:
        return records

    sequential = investigate("parity", collect, "rules")
    graph = investigate("parity", collect, "rules", graph=True)
    assert sequential["hypotheses"] == graph["hypotheses"] == [("oom", 0.9)]
    assert sequential["report"] == graph["report"]
