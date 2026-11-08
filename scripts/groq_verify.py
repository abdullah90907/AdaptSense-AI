"""One guarded Groq investigation; credentials stay in this process only."""
import argparse
import getpass
import json
import os
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from app.main import app
from app.credentials import groq_key
from app.investigation import reference_value
from app.investigation_tools import EvidenceTools

ATTEMPT = Path("data/groq-verification-attempt.json")
RESULT = Path("data/groq-verification-result.json")


def verify_record(record, client, replay_id, forecast_id):
    retrieved = client.get(f'/investigations/{record["id"]}')
    retrieved.raise_for_status()
    assert retrieved.json()["state"] == record["state"]
    assert retrieved.json()["tool_trace"] == record["tool_trace"]
    checks = {"investigation_retrievable": True, "tool_trace_retrievable": True}
    replay = client.get(f"/replays/{replay_id}")
    forecast = client.get(f"/forecasts/{forecast_id}")
    replay.raise_for_status()
    forecast.raise_for_status()
    checks["source_records_retrievable"] = True
    if record["state"] == "completed":
        assert record["report"] == retrieved.json()["report"]
        assert record["report"]["status"] == replay.json()["assessment"]["status"]
        evidence = {t["evidence_id"]: t["result"] for t in record["tool_trace"]}
        citations = [c for finding in record["report"]["findings"] for c in finding["citations"]]
        assert all(reference_value(c["reference"], evidence) == c["value"] for c in citations)
        baseline = EvidenceTools(replay_id, forecast_id).execute("compare_baseline", {})["data"]
        called = next(t["result"]["data"] for t in record["tool_trace"] if t["tool"] == "compare_baseline")
        assert baseline == called
        checks.update({"report_retrievable": True, "status_matches_persisted_replay": True,
                       "citations_verified": len(citations), "baseline_recomputed_matches_tool": True,
                       "baseline_comparison": baseline})
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-key", action="store_true", help="Read an absent environment key through hidden console input")
    parser.add_argument("--final", action="store_true", help="Use the separately authorized final attempt audit files")
    args = parser.parse_args()
    attempt_path = Path("data/groq-live-final-attempt.json") if args.final else ATTEMPT
    result_path = Path("data/groq-live-final-result.json") if args.final else RESULT
    if attempt_path.exists():
        raise SystemExit("The single live attempt has already been reserved; refusing another investigation.")
    replay_id = json.loads(Path("data/phase2-replay-result.json").read_text())["id"]
    forecast_id = json.loads(Path("data/demo-result.json").read_text())["forecast"]["id"]
    EvidenceTools(replay_id, forecast_id)
    configured_key = groq_key()
    if configured_key:
        os.environ["GROQ_API_KEY"] = configured_key
    del configured_key
    if not os.environ.get("GROQ_API_KEY", "").strip():
        if not args.prompt_key:
            raise SystemExit("GROQ_API_KEY is absent. Use --prompt-key in an interactive terminal; no request made.")
        if not sys.stdin.isatty():
            raise SystemExit("Hidden input requires an interactive terminal; refusing unprotected input.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("Groq API key (hidden; not stored): ").strip()
        if not key:
            raise SystemExit("Empty key; no request made.")
        os.environ["GROQ_API_KEY"] = key
        del key
    os.environ["ADAPTSENSE_LLM_PROVIDER"] = "groq"
    request = {"replay_id": replay_id, "forecast_id": forecast_id,
               "question": "Investigate changing reliability in the Victoria electricity replay and optional saved Chronos forecast. Compare the seasonal-naive baseline and uncertainty, inspect additional tools if useful, and explain what is supported and what remains unknown."}
    with attempt_path.open("x") as stream:
        json.dump({"state": "reserved", "started_at": datetime.now(timezone.utc).isoformat(),
                   "request": request, "provider": "groq", "model": "openai/gpt-oss-20b"}, stream, indent=2)
    try:
        with TestClient(app) as client:
            response = client.post("/investigations", json=request)
            if response.status_code == 201:
                record = response.json()
            elif response.status_code == 502 and isinstance(response.json().get("detail"), dict):
                record_id = response.json()["detail"]["investigation_id"]
                saved = client.get(f"/investigations/{record_id}")
                saved.raise_for_status()
                record = {"id": record_id, **saved.json()}
            else:
                artifact = {"http_status": response.status_code, "detail": response.json(), "state": "api_preflight_failed"}
                result_path.write_text(json.dumps(artifact, indent=2))
                raise SystemExit("Live attempt stopped at API preflight; no retry.")
            verification = verify_record(record, client, replay_id, forecast_id)
            artifact = {"http_status": response.status_code, "investigation": record, "verification": verification}
            serialized = json.dumps(artifact, indent=2)
            if os.environ["GROQ_API_KEY"] in serialized:
                raise RuntimeError("Credential detected in output; refusing artifact export")
            result_path.write_text(serialized)
            print(json.dumps({"investigation_id": record["id"], "state": record["state"],
                              "execution_mode": record["execution_mode"], "model": record["model"],
                              "provider_requests": record.get("provider_request_count"),
                              "tools": [t["tool"] for t in record["tool_trace"]],
                              "error_code": record.get("error_code"), "verification": verification}, indent=2))
    finally:
        os.environ.pop("GROQ_API_KEY", None)


if __name__ == "__main__":
    main()

