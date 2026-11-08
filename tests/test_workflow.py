from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from app import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path / "test.db")
    return TestClient(main.app)


def series(n=96):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return {"name": "test", "unit": "kWh", "readings": [
        {"timestamp": (start + timedelta(hours=i)).isoformat(), "value": 10.0}
        for i in range(n)]}


def test_cutoff_and_evaluation(client, monkeypatch):
    seen = []
    def predict(values, horizon):
        seen.append(values)
        return [[9, 10, 11]] * horizon, [10] * horizon
    monkeypatch.setattr(main.forecaster, "predict", predict)
    payload = series()
    for r in payload["readings"][64:]:
        r["value"] = 1000
    sid = client.post("/series", json=payload).json()["id"]
    response = client.post("/forecasts", json={"series_id": sid, "cutoff": payload["readings"][63]["timestamp"], "horizon": 32})
    assert response.status_code == 201
    assert seen == [[10.0] * 64]
    run = response.json()
    result = client.post(f'/forecasts/{run["id"]}/evaluate', json={"actual_series_id": sid}).json()
    assert result["matched"] == 32
    assert result["metrics"]["mae"] == 990
    assert result["metrics"]["q10_q90_coverage"] == 0
    assert result["change"]["flag"]
    assert client.get(f'/forecasts/{run["id"]}').json()["predictions"] == run["predictions"]


def test_forecast_timestamp_overflow_rejected_before_inference(client, monkeypatch):
    def unexpected_inference(*args):
        pytest.fail("Invalid forecast targets must be rejected before inference")

    monkeypatch.setattr(main.forecaster, "predict", unexpected_inference)
    payload = series(32)
    cutoff = datetime(9999, 12, 31, 23, tzinfo=timezone.utc)
    for i, reading in enumerate(payload["readings"]):
        reading["timestamp"] = (cutoff - timedelta(hours=31 - i)).isoformat()
    sid = client.post("/series", json=payload).json()["id"]
    response = client.post("/forecasts", json={"series_id": sid, "cutoff": cutoff.isoformat(), "horizon": 1})
    assert response.status_code == 422
    assert "timestamp range" in response.json()["detail"]


def test_validation(client):
    payload = series()
    payload["readings"][10]["timestamp"] = payload["readings"][9]["timestamp"]
    assert client.post("/series", json=payload).status_code == 422
    payload = series()
    payload["readings"][0]["value"] = -1
    assert client.post("/series", json=payload).status_code == 422
    assert client.get("/forecasts/missing").status_code == 404


def test_degradation_partial_and_csv(client, monkeypatch):
    monkeypatch.setattr(main.forecaster, "predict", lambda v, h: ([[9, 10, 11]] * h, [10] * h))
    payload = series()
    sid = client.post("/series", json=payload).json()["id"]
    run = client.post("/forecasts", json={"series_id": sid, "cutoff": payload["readings"][63]["timestamp"], "horizon": 32}).json()
    for r in payload["readings"][80:]:
        r["value"] = 100
    actual = client.post("/series", json=payload).json()["id"]
    result = client.post(f'/forecasts/{run["id"]}/evaluate', json={"actual_series_id": actual}).json()
    assert result["reliability"]["status"] == "degraded"
    partial = client.post("/series", json={**payload, "readings": payload["readings"][:68]}).json()["id"]
    result = client.post(f'/forecasts/{run["id"]}/evaluate', json={"actual_series_id": partial}).json()
    assert result["pending"] == 28
    assert result["reliability"]["status"] == "insufficient_evidence"
    csv = "timestamp,value\n" + "\n".join(f'{r["timestamp"]},{r["value"]}' for r in payload["readings"])
    assert client.post("/series/csv?name=test&unit=kWh", files={"file": ("readings.csv", csv)}).status_code == 201
