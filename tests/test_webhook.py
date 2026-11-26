from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from triage.api import app
from triage.domain import Evidence

PAYLOAD = {"alerts": [{
    "status": "firing",
    "startsAt": "2026-01-01T00:00:00Z",
    "fingerprint": "demo",
    "labels": {"alertname": "ShopRestarting"},
}]}


def test_webhook_auth_graph_and_report(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_DIR", str(tmp_path))
    monkeypatch.setenv("WEBHOOK_TOKEN", "demo")
    monkeypatch.setenv("TRIAGE_MODE", "rules")
    with TestClient(app) as client:
        assert client.post("/alerts", json=PAYLOAD).status_code == 401
        with patch("triage.api.collect", return_value=[
            Evidence("pods", PAYLOAD["alerts"][0]["startsAt"], "/pods", ("oom_killed",)),
        ]) as collect:
            headers = {"Authorization": "Bearer demo"}
            response = client.post("/alerts", json=PAYLOAD, headers=headers)
            assert response.status_code == 200
            assert client.post("/alerts", json=PAYLOAD, headers=headers).json() == response.json()
            collect.assert_called_once()
    report = tmp_path / response.json()["reports"][0]
    assert "exceeded its memory limit" in report.read_text()
    assert "awaiting human approval" in report.read_text()


@pytest.mark.parametrize("token", [None, "", "  "])
def test_webhook_token_required_at_startup(monkeypatch, token):
    if token is None:
        monkeypatch.delenv("WEBHOOK_TOKEN", raising=False)
    else:
        monkeypatch.setenv("WEBHOOK_TOKEN", token)
    with pytest.raises(RuntimeError, match="WEBHOOK_TOKEN must be set"), TestClient(app):
        pass
