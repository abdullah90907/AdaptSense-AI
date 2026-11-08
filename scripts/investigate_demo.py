"""Explicit controlled or hosted investigation over the existing real-data replay."""
import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient
from app.main import app
from app.llm import get_provider
from .controlled_investigator import ControlledLLM


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--controlled", action="store_true", help="Scripted LLM replies; real analytical tools; no network")
    mode.add_argument("--hosted", action="store_true", help="One bounded hosted investigation; requires OPENAI_API_KEY")
    args = parser.parse_args()
    replay = json.loads(Path("data/phase2-replay-result.json").read_text())
    forecast = json.loads(Path("data/demo-result.json").read_text())["forecast"]
    if args.controlled:
        provider = ControlledLLM()
        app.dependency_overrides[get_provider] = lambda: provider
    try:
        with TestClient(app) as client:
            response = client.post("/investigations", json={"replay_id": replay["id"], "forecast_id": forecast["id"]})
            if response.status_code != 201:
                print(json.dumps({"http_status": response.status_code, "detail": response.json()}, indent=2))
                raise SystemExit(1)
            result = response.json()
            filename = "data/phase3-controlled-result.json" if args.controlled else "data/phase3-hosted-result.json"
            Path(filename).write_text(json.dumps(result, indent=2))
            print(json.dumps({"id": result["id"], "execution_mode": result["execution_mode"],
                              "state": result["state"], "report": result["report"]}, indent=2))
    finally:
        app.dependency_overrides.pop(get_provider, None)


if __name__ == "__main__":
    main()
