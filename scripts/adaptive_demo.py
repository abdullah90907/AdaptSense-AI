"""Run the Victoria sequential experiment from the project root."""
import csv
import json
from argparse import ArgumentParser
from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient

from app.main import app


def main():
    parser = ArgumentParser()
    parser.add_argument("--evolution", action="store_true", help="Include the experimental recurrent candidate")
    args = parser.parse_args()
    source = Path("data/phase4b-victoria-actuals.csv")
    with source.open(newline="") as file:
        cutoff = list(csv.DictReader(file))[112 if args.evolution else 84]["timestamp"]
    with TestClient(app) as client:
        with source.open("rb") as file:
            series = client.post("/series/csv", params={"name": "Victoria daily demand 2014 (fpp2)",
                                                       "unit": "GW (source units)"}, files={"file": file})
        series.raise_for_status()
        start = perf_counter()
        request = {"series_id": series.json()["id"], "first_cutoff": cutoff}
        if args.evolution:
            request.update(origins=36, evolution={})
        response = client.post("/adaptive-experiments", json=request)
        response.raise_for_status()
        result = response.json()
        retrieved = client.get(f"/adaptive-experiments/{result['id']}")
        retrieved.raise_for_status()
        if retrieved.json() != result:
            raise RuntimeError("Retrieved experiment differs from the completed experiment")
        print(json.dumps({"id": result["id"], "elapsed_seconds": perf_counter() - start,
                          "summary": result["summary"],
                          **({"evolution": {key: value for key, value in result["models"]["evolved_rnn"].items()
                                            if key not in ("search_trace", "readout")}} if args.evolution else {}),
                          "switches": [{"cutoff": o["cutoff"], **o["decision"],
                                        "gain_vs_retaining": o["outcome"]["gain_vs_retaining"]}
                                       for o in result["origins"] if o["decision"]["reason"] == "switch"]},
                         indent=2))


if __name__ == "__main__":
    main()
