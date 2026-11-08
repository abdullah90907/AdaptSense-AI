"""Run from the project root: python -m scripts.demo."""
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
    with TestClient(app, raise_server_exceptions=True) as client:
        def post(url, payload):
            response = client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
        history = post("/series", {"name": "Victoria daily electricity demand, 2014", "unit": "GW (source units)", "readings": readings[:300]})
        forecast = post("/forecasts", {"series_id": history["id"], "cutoff": readings[299]["timestamp"], "horizon": 32})
        actual = post("/series", {"name": "Victoria actuals", "unit": "GW (source units)", "readings": readings})
        evaluation = post(f'/forecasts/{forecast["id"]}/evaluate', {"actual_series_id": actual["id"]})
        import psutil
        verification = {"elapsed_seconds": time.perf_counter() - started,
                        "process_rss_mb": psutil.Process().memory_info().rss / 1024 ** 2}
        Path("data/demo-result.json").write_text(json.dumps({"forecast": forecast, "evaluation": evaluation, "verification": verification}, indent=2))
        print(json.dumps({"metrics": evaluation["metrics"], "reliability": evaluation["reliability"], "revision": forecast["revision"]}, indent=2))


if __name__ == "__main__":
    main()
