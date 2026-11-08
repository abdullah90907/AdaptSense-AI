from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import main
from app.adaptive import AdaptiveRequest, decision
from app.evolution import EvolutionConfig, evolve


def test_search_mutates_and_reconstructs_frozen_winner():
    time = np.arange(100)
    values = 50 + 4 * np.sin(time * 2 * np.pi / 7) + time / 6
    model, evidence = evolve(values, 32, 7, 7, EvolutionConfig())
    repeated, repeated_evidence = evolve(values, 32, 7, 7, EvolutionConfig())
    trace = evidence["search_trace"]
    assert len(trace) > 6
    assert any(row["generation"] > 0 for row in trace)
    assert evidence["validation_mae"] == min(row["validation_mae"] for row in trace)
    assert evidence == repeated_evidence
    assert model.predict(values[-32:], 7) == repeated.predict(values[-32:], 7)
    assert len(model.predict(values[-32:], 7)) == 7
    with pytest.raises(ValueError, match="16 complete fitting windows"):
        evolve(values[:40], 32, 7, 7, EvolutionConfig())


def test_api_evolution_uses_only_prefix_and_compares_common_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path / "evolution.db")
    monkeypatch.setattr(main.forecaster, "predict", lambda h, n: ([[48, 50, 52]] * n, [50] * n))
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with TestClient(main.app) as client:
        def run(future_offset):
            readings = [{"timestamp": (start + timedelta(days=i)).isoformat(),
                         "value": 50 + i / 4 + i % 7 + (future_offset if i >= 100 else 0)} for i in range(135)]
            series = client.post("/series", json={"name": "test", "unit": "GW", "readings": readings}).json()
            response = client.post("/adaptive-experiments", json={
                "series_id": series["id"], "first_cutoff": readings[99]["timestamp"],
                "context_length": 32, "origins": 5, "lookback_origins": 3, "evolution": {}})
            assert response.status_code == 201, response.text
            result = response.json()
            assert client.get(f"/adaptive-experiments/{result['id']}").json() == result
            return result

        first, shifted = run(0), run(1000)
    assert first["models"]["evolved_rnn"] == shifted["models"]["evolved_rnn"]
    assert first["origins"][0]["predictions"] == shifted["origins"][0]["predictions"]
    assert first["origins"][0]["outcome"] != shifted["origins"][0]["outcome"]
    assert first["summary"]["scored_targets"] == 14
    assert set(first["summary"]["metrics"]) == {"chronos", "seasonal_naive", "evolved_rnn", "adaptive"}
    for model, metrics in first["summary"]["metrics"].items():
        errors = [abs(actual - p[model if model != "adaptive" else origin["decision"]["selected_model"]])
                  for origin in first["origins"][3:]
                  for actual, p in zip(origin["outcome"]["actuals"], origin["predictions"])]
        assert metrics["mae"] == pytest.approx(np.mean(errors))


def test_policy_can_select_evolved_candidate():
    request = AdaptiveRequest(series_id="test", first_cutoff="2024-01-01T00:00:00Z", lookback_origins=3)
    completed = [{"cutoff": str(i), "outcome": {"mae": {"chronos": 5, "seasonal_naive": 3, "evolved_rnn": 1}}}
                 for i in range(3)]
    result = decision("chronos", completed, request, ("chronos", "seasonal_naive", "evolved_rnn"))
    assert result["selected_model"] == "evolved_rnn"
