"""Deterministic Responses-shaped test double, never a hosted LLM."""
import json


def call(name, arguments, call_id):
    return {"type": "function_call", "name": name, "arguments": json.dumps(arguments), "call_id": call_id}


def controlled_final(status, forecast_available):
    findings = [
        {"statement": "The saved assessment is {{E1:/status}}. The error change is {{E1:/delta_mae}}, with uncertainty from {{E1:/delta_mae_bootstrap_interval/0}} to {{E1:/delta_mae_bootstrap_interval/1}} against a practical threshold of {{E1:/practical_delta_threshold}}. This does not establish a cause or distribution stability.",
         "references": ["E1:/status", "E1:/delta_mae", "E1:/delta_mae_bootstrap_interval/0", "E1:/delta_mae_bootstrap_interval/1", "E1:/practical_delta_threshold"]},
        {"statement": "Reference model and seasonal-naive errors are {{E2:/reference/model_mae}} and {{E2:/reference/baseline_mae}}; recent errors are {{E2:/recent/model_mae}} and {{E2:/recent/baseline_mae}}. Whether the model beats the recent baseline: {{E2:/recent/model_better}}.",
         "references": ["E2:/reference/model_mae", "E2:/reference/baseline_mae", "E2:/recent/model_mae", "E2:/recent/baseline_mae", "E2:/recent/model_better"]},
        {"statement": "Actual means are {{E3:/reference/actual_mean}} and {{E3:/recent/actual_mean}}. Signed recent bias is {{E3:/recent/signed_bias_actual_minus_point}}. These describe the observations and do not explain their causes.",
         "references": ["E3:/reference/actual_mean", "E3:/recent/actual_mean", "E3:/recent/signed_bias_actual_minus_point"]},
        {"statement": "The largest recent window error is {{E5:/worst_windows/0/mae}}, following cutoff {{E5:/worst_windows/0/cutoff}}. Ranking a window by error does not establish an anomaly.",
         "references": ["E5:/worst_windows/0/mae", "E5:/worst_windows/0/cutoff"]},
        {"statement": "The leading forecast step has a descriptive error change of {{E4:/leads/0/delta_mae}}. Per-lead effects should be inspected alongside the aggregate assessment.",
         "references": ["E4:/leads/0/delta_mae"]},
    ]
    if forecast_available:
        findings.append({"statement": "The optional saved forecast has mean absolute error {{E6:/metrics/mae}} with {{E6:/pending}} pending readings. Its legacy within-forecast reliability comparison is confounded by lead time.",
                         "references": ["E6:/metrics/mae", "E6:/pending"]})
    return {"status": status, "findings": findings, "hypotheses": [],
            "next_checks": ["Review the worst completed windows and obtain aligned weather and calendar measurements before evaluating possible external explanations."]}


class ControlledLLM:
    mode = "controlled_llm_test"
    model = "scripted_responses_test_double"

    def __init__(self):
        self.turn = 0

    def respond(self, messages, tools, instructions, timeout_seconds):
        self.turn += 1
        if self.turn == 1:
            output = [call("replay_summary", {}, "c1"), call("compare_baseline", {}, "c2"), call("inspect_patterns", {}, "c3")]
        elif self.turn == 2:
            output = [call("inspect_leads", {}, "c4"), call("inspect_windows", {"period": "recent", "limit": 3}, "c5"), call("inspect_forecast", {}, "c6")]
        else:
            observed = {item["evidence_id"]: item for message in messages if message.get("type") == "function_call_output"
                        for item in [json.loads(message["output"]) ]}
            report = controlled_final(observed["E1"]["data"]["status"], observed["E6"].get("data", {}).get("available", False))
            output = [call("finish_investigation", report, "c7")]
        return {"id": f"controlled_response_{self.turn}", "model": self.model, "status": "completed", "output": output,
                "usage": None}
