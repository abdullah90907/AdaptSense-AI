"""Read-only analytical tools scoped to one saved replay."""
import hashlib
import json
from datetime import datetime

import numpy as np
from fastapi import HTTPException


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class EvidenceTools:
    def __init__(self, replay_id, forecast_id=None):
        from .main import get
        self.replay_id = replay_id
        self.replay = get(replay_id, "replay")
        self.forecast_id = forecast_id
        self.sources = [{"kind": "replay", "id": replay_id, "sha256": digest(self.replay)}]
        self.forecast = None
        if forecast_id:
            self.forecast = get(forecast_id, "forecast")
            original = get(self.forecast["series_id"], "series")
            actual = get(self.replay["request"]["series_id"], "series")
            lookup = {datetime.fromisoformat(r["timestamp"]): r["value"] for r in actual["readings"]}
            history = [r for r in original["readings"] if datetime.fromisoformat(r["timestamp"]) <= datetime.fromisoformat(self.forecast["cutoff"])][-2048:]
            if original["unit"] != actual["unit"] or not history or any(lookup.get(datetime.fromisoformat(r["timestamp"])) != r["value"] for r in history):
                raise HTTPException(422, "Forecast context and replay series must contain matching timestamp/value readings and units")
            self.sources.extend([{"kind": "forecast", "id": forecast_id, "sha256": digest(self.forecast)},
                                 {"kind": "series", "id": self.replay["request"]["series_id"], "sha256": digest(actual)}])

    def execute(self, name, arguments):
        from .main import evaluate, EvaluationRequest
        if name == "replay_summary":
            self.no_arguments(arguments)
            return {"data": {**self.replay["assessment"], "unit": self.replay["unit"],
                             "model": self.replay["model"], "revision": self.replay["revision"],
                             "limitations": self.replay["limitations"]},
                    "source_paths": ["/assessment", "/unit", "/model", "/revision", "/limitations"]}
        if name == "compare_baseline":
            self.no_arguments(arguments)
            result = {}
            for period in ("reference", "recent"):
                rows = self.rows(period)
                mae = float(np.mean([abs(r["actual"] - r["point"]) for r in rows]))
                naive = float(np.mean([abs(r["actual"] - r["baseline_point"]) for r in rows]))
                result[period] = {"model_mae": mae, "baseline_mae": naive,
                                  "skill": 1 - mae / naive if naive > 1e-9 else None,
                                  "model_better": mae < naive}
            result["model_delta_mae"] = result["recent"]["model_mae"] - result["reference"]["model_mae"]
            result["baseline_delta_mae"] = result["recent"]["baseline_mae"] - result["reference"]["baseline_mae"]
            return {"data": result, "source_paths": ["/origins"],
                    "calculation": "MAE recomputed from actual minus point/baseline_point; skill = 1 - model MAE / baseline MAE. Baseline comparison is descriptive, not causal."}
        if name == "inspect_leads":
            self.no_arguments(arguments)
            return {"data": {"leads": self.replay["assessment"]["per_lead"]}, "source_paths": ["/assessment/per_lead"]}
        if name == "inspect_windows":
            self.validate_selection(arguments)
            origins = [o for o in self.replay["origins"] if o["period"] == arguments["period"]]
            ranked = sorted(enumerate(origins), key=lambda item: item[1]["mae"], reverse=True)[:arguments["limit"]]
            return {"data": {"period": arguments["period"], "worst_windows": [
                {"cutoff": o["cutoff"], "start": o["evidence"][0]["timestamp"], "end": o["evidence"][-1]["timestamp"],
                 "mae": o["mae"], "baseline_mae": float(np.mean([r["baseline_absolute_error"] for r in o["evidence"]]))}
                for _, o in ranked]}, "source_paths": ["/origins"],
                "calculation": "Top completed forecast blocks ranked by MAE; largest error is not automatically an anomaly."}
        if name == "inspect_patterns":
            self.no_arguments(arguments)
            result = {}
            for period in ("reference", "recent"):
                rows = self.rows(period)
                actual = np.array([r["actual"] for r in rows])
                residual = np.array([r["actual"] - r["point"] for r in rows])
                result[period] = {"actual_mean": float(actual.mean()), "actual_std": float(actual.std()),
                                  "signed_bias_actual_minus_point": float(residual.mean()),
                                  "outside_interval_count": sum(not r["covered"] for r in rows), "count": len(rows)}
            return {"data": result, "source_paths": ["/origins"],
                    "calculation": "Descriptive actual mean/population standard deviation and signed residual mean; no causal or drift significance test."}
        if name == "inspect_forecast":
            self.no_arguments(arguments)
            if not self.forecast:
                return {"data": {"available": False, "reason": "No optional forecast_id was supplied"}, "source_paths": []}
            result = evaluate(self.forecast_id, EvaluationRequest(actual_series_id=self.replay["request"]["series_id"]))
            return {"data": {"available": True, "forecast_id": self.forecast_id, "cutoff": self.forecast["cutoff"],
                             **{key: value for key, value in result.items() if key != "evidence"}},
                    "source_paths": ["forecast:/predictions", "series:/readings"],
                    "calculation": "Existing Phase 1 evaluation against replay source actuals; its reliability heuristic is lead-time confounded."}
        raise ValueError("Unknown analytical tool")

    def rows(self, period):
        return [r for o in self.replay["origins"] if o["period"] == period for r in o["evidence"]]

    @staticmethod
    def no_arguments(arguments):
        if arguments != {}:
            raise ValueError("This tool accepts no arguments")

    @staticmethod
    def validate_selection(arguments):
        if not isinstance(arguments, dict) or set(arguments) != {"period", "limit"} or arguments["period"] not in ("reference", "recent") or type(arguments["limit"]) is not int or not 1 <= arguments["limit"] <= 5:
            raise ValueError("Expected period reference/recent and integer limit between one and five")


DESCRIPTIONS = {
    "replay_summary": "Read saved fixed-lead reliability decision, period metrics, uncertainty, threshold, provenance and limitations. Required before finishing.",
    "compare_baseline": "Recompute model and seasonal-naive MAE and skill from raw replay evidence. Required before finishing.",
    "inspect_leads": "Compare errors at each matched forecast lead to identify mixed lead-specific changes.",
    "inspect_windows": "Inspect the worst completed forecast windows in a chosen period, without labeling them anomalies.",
    "inspect_patterns": "Compute actual level/variability, signed bias and interval exceedance counts across periods.",
    "inspect_forecast": "Evaluate the optional saved forecast against replay source actuals using the existing forecast API logic; check for missing later actuals and the legacy horizon confound.",
}


def tool_definitions(final_schema):
    tools = []
    for name, description in DESCRIPTIONS.items():
        properties = {"period": {"type": "string", "enum": ["reference", "recent"]},
                      "limit": {"type": "integer", "minimum": 1, "maximum": 5}} if name == "inspect_windows" else {}
        tools.append({"type": "function", "name": name, "description": description, "strict": True,
                      "parameters": {"type": "object", "properties": properties,
                                     "required": list(properties), "additionalProperties": False}})
    tools.append({"type": "function", "name": "finish_investigation", "strict": True,
                  "description": "Submit the evidence-cited investigation after inspecting summary and baseline. All numeric prose must use evidence placeholders.",
                  "parameters": final_schema})
    return tools

