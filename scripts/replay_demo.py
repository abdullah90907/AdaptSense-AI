"""Real-data fixed-lead replay; run with python -m scripts.replay_demo."""
import csv
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from app.main import app


def main():
    started = time.perf_counter()
    rows = list(csv.DictReader(Path("data/elecdaily-source.csv").open()))
    start = datetime(2014, 1, 1, tzinfo=timezone.utc)
    readings = [{"timestamp": (start + timedelta(days=i)).isoformat(), "value": float(row["Demand"])} for i, row in enumerate(rows)]
    with TestClient(app) as client:
        series = client.post("/series", json={"name": "Victoria daily demand 2014 (fpp2)", "unit": "GW (source units)", "readings": readings})
        series.raise_for_status()
        # Two equal 140-day periods ending at the dataset's final observation.
        result = client.post("/replays", json={"series_id": series.json()["id"], "first_cutoff": readings[84]["timestamp"],
                                               "context_length": 56, "horizon": 7, "seasonal_period": 7, "period_origins": 20})
        result.raise_for_status()
        report = result.json()
        report["verification"] = {"elapsed_seconds": time.perf_counter() - started}
        Path("data/phase2-replay-result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({"id": report["id"], "assessment": report["assessment"], "verification": report["verification"]}, indent=2))


if __name__ == "__main__":
    main()
