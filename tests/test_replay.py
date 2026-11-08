from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import main
from app.reliability import assess


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path / "replay.db")
    return TestClient(main.app)


def payload(n=224):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return {"name": "controlled rule test", "unit": "kWh", "readings": [
        {"timestamp": (start + timedelta(hours=i)).isoformat(), "value": i + 1.0} for i in range(n)]}


def request(client, data):
    sid = client.post("/series", json=data).json()["id"]
    return {"series_id": sid, "first_cutoff": data["readings"][31]["timestamp"],
            "context_length": 32, "horizon": 7, "seasonal_period": 7, "period_origins": 12}


def test_replay_controls_lead_and_context(client, monkeypatch):
    seen = []
    def predict(history, horizon):
        seen.append(list(history))
        # Error grows with lead, identically in both periods.
        points = [history[-1] + i + 1 + i for i in range(horizon)]
        return [[x - 1, x, x + 1] for x in points], points
    monkeypatch.setattr(main.forecaster, "predict", predict)
    data = payload()
    response = client.post("/replays", json=request(client, data))
    assert response.status_code == 201, response.text
    result = response.json()
    assert len(seen) == 24
    for i, history in enumerate(seen):
        assert history == list(np.arange(1 + 7 * i, 33 + 7 * i, dtype=float))
    assert result["assessment"]["status"] == "no_deterioration_detected"
    assert result["assessment"]["delta_mae_bootstrap_interval"] == [0, 0]
    assert [r["reference_mae"] for r in result["assessment"]["per_lead"]] == list(range(7))
    assert result["assessment"]["reference"]["baseline_mae"] == 7
    targets = [e["timestamp"] for o in result["origins"] for e in o["evidence"]]
    assert len(targets) == len(set(targets)) == 168
    assert client.get(f'/replays/{result["id"]}').json()["origins"] == result["origins"]


def origins(errors):
    return [{"mae": float(error), "evidence": [{"timestamp": str(i), "absolute_error": float(error),
             "baseline_absolute_error": 2.0, "covered": error <= 2}]} for i, error in enumerate(errors)]


def test_assessment_sustained_change_and_transient():
    result = assess(origins([1] * 12 + [5] * 12), 12, 1)
    assert result["status"] == "deterioration_supported"
    assert result["delta_mae"] == 4
    assert result["delta_mae_bootstrap_interval"] == [4, 4]
    result = assess(origins([1] * 12 + [1] * 11 + [40]), 12, 1)
    assert result["status"] == "possible_deterioration"
    assert not result["sustained"]
    assert result["delta_mae_bootstrap_interval"][0] <= 0
    result = assess(origins([0] * 24), 12, 0)
    assert result["status"] == "no_deterioration_detected"
    assert result["reference"]["skill_vs_baseline"] == 1
    assert result == assess(origins([0] * 24), 12, 0)


def test_replay_validation_and_failed_inference(client, monkeypatch):
    data = payload()
    body = request(client, data)
    for changes in [{"period_origins": 11}, {"horizon": 64}, {"seasonal_period": 32},
                    {"first_cutoff": "2024-01-02T07:00:00"}, {"first_cutoff": data["readings"][0]["timestamp"]}]:
        assert client.post("/replays", json={**body, **changes}).status_code == 422
    monkeypatch.setattr(main.forecaster, "predict", lambda h, n: ([[0, float("nan"), 1]] * n, []))
    assert client.post("/replays", json=body).status_code == 503
    with main.connection() as db:
        assert db.execute("SELECT count(*) FROM records WHERE kind='replay'").fetchone()[0] == 0
    assert client.get("/replays/missing").status_code == 404

