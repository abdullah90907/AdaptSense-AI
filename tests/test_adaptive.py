from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app import main
from app.adaptive import KIND


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path / "adaptive.db")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    readings = [{"timestamp": (start + timedelta(days=i)).isoformat(), "value": float(i)}
                for i in range(46)]
    with TestClient(main.app) as client:
        series = client.post("/series", json={"name": "Linear", "unit": "GW", "readings": readings}).json()
        yield client, {"series_id": series["id"], "first_cutoff": readings[31]["timestamp"],
                       "context_length": 32, "horizon": 2, "seasonal_period": 2,
                       "origins": 7, "lookback_origins": 3}, readings


def test_predictions_committed_before_scoring_and_policy_measured(experiment, monkeypatch):
    client, body, readings = experiment
    histories, commits = [], []
    update = main.update

    def predict(history, horizon):
        histories.append(history)
        error = 5 if len(histories) <= 3 else 0
        points = [history[-1] + lead + error for lead in range(1, horizon + 1)]
        return [[p - 1, p, p + 1] for p in points], points

    def track_commit(key, kind, record):
        update(key, kind, record)
        stored = main.get(key, kind)
        if stored["state"] == "running":
            origin = stored["origins"][-1]
            commits.append((len(stored["origins"]), "outcome" in origin))
            assert origin["predictions"]

    monkeypatch.setattr(main.forecaster, "predict", predict)
    monkeypatch.setattr(main, "update", track_commit)
    response = client.post("/adaptive-experiments", json=body)
    assert response.status_code == 201, response.text
    result = response.json()
    assert commits == [(i, scored) for i in range(1, 8) for scored in (False, True)]
    assert histories == [list(range(i, i + 32)) for i in range(0, 14, 2)]
    assert [origin["decision"]["selected_model"] for origin in result["origins"]] == [
        "chronos", "chronos", "chronos", "seasonal_naive", "seasonal_naive", "chronos", "chronos",
    ]
    targets = [p["timestamp"] for origin in result["origins"] for p in origin["predictions"]]
    assert targets == [reading["timestamp"] for reading in readings[32:]]
    summary = result["summary"]
    assert summary["scored_targets"] == 8
    assert summary["metrics"]["adaptive"] == {"mae": 1, "rmse": pytest.approx(2 ** 0.5)}
    assert summary["adaptive_mae_gain_vs_fixed"] == {"chronos": -1, "seasonal_naive": 1}
    assert summary["switch_outcomes"] == {"count": 2, "improved": 1, "worsened": 1, "tied": 0,
                                         "mean_mae_gain_vs_retaining": 0}
    assert client.get(f"/adaptive-experiments/{result['id']}").json() == result


def test_invalid_request_and_inference_failure(experiment, monkeypatch):
    client, body, _ = experiment
    assert client.post("/adaptive-experiments", json={**body, "horizon": 3}).status_code == 422
    assert client.post("/adaptive-experiments", json={**body, "lookback_origins": 7}).status_code == 422
    assert client.get("/adaptive-experiments/missing").status_code == 404

    outputs = iter([[[0, 1, 2]] * 2, [[0, float("nan"), 2]] * 2])
    monkeypatch.setattr(main.forecaster, "predict", lambda *_: (next(outputs), []))
    response = client.post("/adaptive-experiments", json=body)
    assert response.status_code == 503
    result = main.get(response.json()["detail"]["experiment_id"], KIND)
    assert result["state"] == "failed"
    assert result["failed_origin"] == 2
    assert len(result["origins"]) == 1
    assert "outcome" in result["origins"][0]
    assert "summary" not in result


def test_background_progress_history_and_comparison(experiment, monkeypatch):
    client, body, _ = experiment
    entered, release = Event(), Event()

    def predict(history, horizon):
        entered.set()
        assert release.wait(10)
        return [[0, history[-1], 100]] * horizon, []

    monkeypatch.setattr(main.forecaster, "predict", predict)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, "/adaptive-experiments?background=true", json=body)
        try:
            assert entered.wait(10)
            listed = client.get("/adaptive-experiments", params={"series_id": body["series_id"]}).json()["items"]
            assert len(listed) == 1
            key = listed[0]["id"]
            status_url = f"/adaptive-experiments/{key}/status"
            active = client.get(status_url).json()
            assert active["state"] == "running"
            assert active["progress"] == {"scored_origins": 0, "total_origins": 7}
            assert client.post("/adaptive-experiments?background=true", json=body).status_code == 409
            assert client.get(f"/adaptive-experiments/{key}/comparison").status_code == 409
        finally:
            release.set()
        accepted = future.result(timeout=10)
    assert accepted.status_code == 202
    assert accepted.json() == {"id": key, "state": "queued", "status_url": status_url}
    assert client.get(status_url).json()["progress"]["scored_origins"] == 7
    second = client.post("/adaptive-experiments", json=body).json()["id"]
    different = client.post("/adaptive-experiments", json={**body, "lookback_origins": 4}).json()["id"]
    comparison = client.get(f"/adaptive-experiments/{key}/comparison", params={"against": second}).json()
    assert comparison["against"]["mae_delta_this_minus_other"] == {"chronos": 0, "seasonal_naive": 0, "adaptive": 0}
    assert comparison["lowest_observed_fixed_mae_models"] == ["chronos"]
    assert comparison["next_origin_recommendation"]["selected_model"] == "chronos"
    assert client.get(f"/adaptive-experiments/{key}/comparison", params={"against": different}).status_code == 422
    first_page = client.get("/adaptive-experiments?limit=1").json()
    assert first_page["items"][0]["id"] == different
    assert client.get("/adaptive-experiments", params={"before": first_page["next_before"]}).json()["items"][0]["id"] == second


def test_history_surfaces_interrupted_run_and_dataset_metadata(experiment):
    client, body, readings = experiment
    saved = main.save(KIND, {"state": "running", "worker": "old-process", "created_at": readings[0]["timestamp"],
                             "request": body, "origins": [{"predictions": []}]})
    listing = client.get("/adaptive-experiments").json()["items"][0]
    status = client.get(f"/adaptive-experiments/{saved['id']}/status").json()
    assert listing["state"] == status["state"] == "interrupted"
    assert listing["progress"] == status["progress"] == {"scored_origins": 0, "total_origins": 7}
    dataset = client.get("/series").json()["items"][0]
    assert dataset["id"] == body["series_id"]
    assert dataset["observations"] == 46
    assert datetime.fromisoformat(dataset["last_timestamp"]) == datetime.fromisoformat(readings[-1]["timestamp"])
    assert "readings" not in dataset
