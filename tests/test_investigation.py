import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.investigation import validate_report
from app.investigation_tools import EvidenceTools
from app.llm import HostedLLM, ProviderError, get_provider
from scripts.controlled_investigator import ControlledLLM, call, controlled_final


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path / "investigations.db")
    monkeypatch.setenv("ADAPTSENSE_LLM_PROVIDER", "openai")
    monkeypatch.setattr("app.credentials.ENV_PATH", tmp_path / ".env")
    raw = json.loads(Path("data/phase2-replay-result.json").read_text())
    raw.pop("id")
    raw.pop("verification", None)
    rows = list(csv.DictReader(Path("data/elecdaily-source.csv").open()))
    start = datetime(2014, 1, 1, tzinfo=timezone.utc)
    readings = [{"timestamp": start + timedelta(days=i), "value": float(row["Demand"])} for i, row in enumerate(rows)]
    series = main.create_series(main.Series(name="real sourced measurements", unit=raw["unit"], readings=readings))
    raw["request"]["series_id"] = series["id"]
    replay = main.save("replay", raw)
    forecast = json.loads(Path("data/demo-result.json").read_text())["forecast"]
    forecast.pop("id")
    forecast["series_id"] = series["id"]
    forecast = main.save("forecast", forecast)
    provider = ControlledLLM()
    main.app.dependency_overrides[get_provider] = lambda: provider
    with TestClient(main.app) as client:
        yield client, {"replay_id": replay["id"], "forecast_id": forecast["id"]}, provider
    main.app.dependency_overrides.clear()


def test_complete_agent_with_real_analytical_tools(setup):
    client, body, provider = setup
    response = client.post("/investigations", json=body)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["execution_mode"] == "controlled_llm_test"
    assert result["state"] == "completed"
    assert provider.turn == 3
    assert result["report"]["status"] == "no_deterioration_detected"
    assert len(result["tool_trace"]) == 6
    baseline = result["tool_trace"][1]["result"]["data"]
    assert baseline["recent"]["model_mae"] == pytest.approx(10.2821737171)
    assert baseline["recent"]["baseline_mae"] == pytest.approx(10.2518534111)
    assert not baseline["recent"]["model_better"]
    forecast = result["tool_trace"][5]["result"]["data"]
    assert forecast["metrics"]["mae"] == pytest.approx(11.8339809929)
    assert forecast["reliability"]["method"] == "legacy_within_forecast_lead_comparison"
    assert result["report"]["validation"]["numbers_rendered_from_evidence"]
    assert len(result["sources"][0]["sha256"]) == 64
    assert client.get(f'/investigations/{result["id"]}').json()["report"] == result["report"]
    tools = EvidenceTools(body["replay_id"], body["forecast_id"])
    assert tools.execute("inspect_patterns", {})["data"]["recent"]["count"] == 140
    assert tools.execute("inspect_forecast", {})["data"]["pending"] == 0
    for item in result["tool_trace"]:
        assert "source_paths" in item["result"]
    assert "/investigations" in client.get("/openapi.json").json()["paths"]


@pytest.mark.parametrize("case", ["invented_number", "missing_reference", "invalid_path", "changed_status", "uncited_placeholder"])
def test_invalid_reports_fail_closed(setup, case):
    client, body, provider = setup
    original_respond = provider.respond
    def respond(*args):
        result = original_respond(*args)
        if provider.turn == 3:
            final = json.loads(result["output"][0]["arguments"])
            if case == "invented_number":
                final["findings"][0]["statement"] += " Improvement is 99%."
            elif case == "missing_reference":
                final["findings"][0]["references"].append("E99:/invented")
            elif case == "invalid_path":
                final["findings"][0]["references"].append("E1:/nonexistent")
            elif case == "changed_status":
                final["status"] = "deterioration_supported"
            else:
                final["findings"][0]["references"].remove("E1:/delta_mae")
            result["output"][0]["arguments"] = json.dumps(final)
        return result
    provider.respond = respond
    response = client.post("/investigations", json=body)
    assert response.status_code == 502
    detail = response.json()["detail"]
    failed = client.get(f'/investigations/{detail["investigation_id"]}').json()
    assert failed["state"] == "failed" and "report" not in failed
    assert failed["error_code"] == "invalid_agent_output"
    assert provider.turn == 3


def test_scope_missing_records_and_forecast_context(setup):
    client, body, provider = setup
    assert client.post("/investigations", json={**body, "replay_id": "missing"}).status_code == 404
    forecast = main.get(body["forecast_id"], "forecast")
    source = main.get(forecast["series_id"], "series")
    source["readings"][299]["value"] += 1
    altered = main.save("series", source)
    forecast["series_id"] = altered["id"]
    altered_forecast = main.save("forecast", forecast)
    assert client.post("/investigations", json={**body, "forecast_id": altered_forecast["id"]}).status_code == 422
    assert provider.turn == 0
    scoped = EvidenceTools(body["replay_id"])
    assert not scoped.execute("inspect_forecast", {})["data"]["available"]
    with pytest.raises(ValueError):
        scoped.execute("replay_summary", {"replay_id": "unrelated"})
    with pytest.raises(ValueError):
        scoped.execute("inspect_windows", {"period": "recent", "limit": 10000})
    with pytest.raises(ValueError):
        scoped.execute("delete_series", {})


def test_missing_key_never_calls_host(setup, monkeypatch):
    client, body, _ = setup
    main.app.dependency_overrides.clear()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    def unexpected(*args, **kwargs):
        pytest.fail("No network request is allowed without a configured key")
    monkeypatch.setattr("app.llm.httpx.Client", unexpected)
    config = client.get("/investigations/config").json()
    assert not config["configured"]
    assert client.post("/investigations", json=body).status_code == 503
    with pytest.raises(main.HTTPException) as exc:
        get_provider()
    assert exc.value.status_code == 503


class RepeatingLLM:
    mode = "controlled_llm_test"
    model = "repeating_test_double"
    def __init__(self, many=False):
        self.count = 0
        self.many = many
    def respond(self, *args):
        self.count += 1
        calls = [call("replay_summary", {}, f"r{self.count}-{i}") for i in range(11 if self.many else 1)]
        return {"id": "test", "status": "completed", "output": calls}


@pytest.mark.parametrize("many,code", [(False, "model_turn_budget_exhausted"), (True, "tool_budget_exhausted")])
def test_agent_budgets_stop_without_retry(setup, many, code):
    client, body, _ = setup
    provider = RepeatingLLM(many)
    main.app.dependency_overrides[get_provider] = lambda: provider
    response = client.post("/investigations", json=body)
    assert response.status_code == 502
    assert response.json()["detail"]["error_code"] == code
    assert provider.count == (1 if many else 4)


@pytest.mark.parametrize("status", ["deterioration_supported", "possible_deterioration", "no_deterioration_detected"])
def test_all_analytical_statuses_are_preserved(setup, status):
    client, body, _ = setup
    tools = EvidenceTools(body["replay_id"])
    trace = []
    selections = [("replay_summary", {}), ("compare_baseline", {}), ("inspect_patterns", {}),
                  ("inspect_leads", {}), ("inspect_windows", {"period": "recent", "limit": 1}), ("inspect_forecast", {})]
    for i, (name, arguments) in enumerate(selections):
        trace.append({"evidence_id": f"E{i + 1}", "tool": name, "result": tools.execute(name, arguments)})
    # Controlled status fixture; not an assertion that the real dataset deteriorated.
    trace[0]["result"]["data"]["status"] = status
    assert validate_report(controlled_final(status, False), trace, status)["status"] == status


@pytest.mark.parametrize("status_code,code", [(429, "provider_rate_limited"), (401, "provider_authentication_failed"), (500, "provider_http_error")])
def test_hosted_adapter_stops_on_errors(monkeypatch, status_code, code):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-controlled-test-key")
    original_client = httpx.Client
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        assert request.url == "https://api.openai.com/v1/responses"
        return httpx.Response(status_code, json={"error": "controlled"})
    monkeypatch.setattr("app.llm.httpx.Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(ProviderError) as exc:
        HostedLLM().respond([], [], "controlled test", 1)
    assert exc.value.code == code
    assert len(calls) == 1
    assert calls[0]["store"] is False
    assert calls[0]["max_output_tokens"] == 2500



def test_hosted_adapter_success_and_timeout_are_controlled(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-controlled-test-key")
    original_client = httpx.Client
    received = []
    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "controlled-http-response", "status": "completed",
                                       "output": [call("replay_summary", {}, "controlled-call")]})
    monkeypatch.setattr("app.llm.httpx.Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    provider = HostedLLM()
    response = provider.respond([], [], "controlled test", 1)
    assert response["output"][0]["name"] == "replay_summary"
    assert received[0]["tool_choice"] == "required"
    def timeout(request):
        raise httpx.ReadTimeout("controlled timeout")
    monkeypatch.setattr("app.llm.httpx.Client", lambda **kwargs: original_client(transport=httpx.MockTransport(timeout), **kwargs))
    with pytest.raises(ProviderError) as exc:
        provider.respond([], [], "controlled test", 1)
    assert exc.value.code == "provider_timeout"


def test_provider_failure_persists_no_success_report(setup):
    client, body, _ = setup
    provider = RepeatingLLM()
    def limited(*args):
        provider.count += 1
        raise ProviderError("provider_rate_limited")
    provider.respond = limited
    main.app.dependency_overrides[get_provider] = lambda: provider
    response = client.post("/investigations", json=body)
    assert response.status_code == 502
    assert provider.count == 1
    saved = client.get('/investigations/' + response.json()["detail"]["investigation_id"]).json()
    assert saved["error_code"] == "provider_rate_limited"
    assert "report" not in saved
    assert saved["tool_trace"] == []



def test_groq_chat_translation_and_schema_mock(monkeypatch):
    from app.investigation import FinalReport
    from app.investigation_tools import tool_definitions
    from app.llm import GroqLLM
    monkeypatch.setenv("GROQ_API_KEY", "gsk_controlled_not_real")
    original_client = httpx.Client
    received = []
    def handler(request):
        assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
        payload = json.loads(request.content)
        received.append(payload)
        assert payload["model"] == "openai/gpt-oss-20b"
        assert payload["max_completion_tokens"] == 2500
        assert payload["tool_choice"] == "required"
        assert payload["include_reasoning"] is False
        assert "input" not in payload and "reasoning" not in payload
        assert all(t["type"] == "function" and "strict" not in t["function"] for t in payload["tools"])
        assert "$ref" not in json.dumps(payload["tools"])
        return httpx.Response(200, json={"id": "mock-groq", "model": "openai/gpt-oss-20b", "choices": [{
            "finish_reason": "tool_calls", "message": {"role": "assistant", "tool_calls": [{
                "id": "mock-call", "type": "function", "function": {"name": "inspect_patterns", "arguments": "{}"}}]}}]})
    monkeypatch.setattr("app.llm.httpx.Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    messages = [{"role": "user", "content": "investigate"}, call("replay_summary", {}, "a"), call("compare_baseline", {}, "b"),
                {"type": "function_call_output", "call_id": "a", "output": "{}"},
                {"type": "function_call_output", "call_id": "b", "output": "{}"}]
    provider = GroqLLM()
    result = provider.respond(messages, tool_definitions(FinalReport.model_json_schema()), "instructions", 1)
    assert result["status"] == "completed"
    assert result["output"][0]["name"] == "inspect_patterns"
    assert provider.request_count == 1
    chat = received[0]["messages"]
    assert [m["role"] for m in chat] == ["system", "user", "assistant", "tool", "tool"]
    assert [c["id"] for c in chat[2]["tool_calls"]] == ["a", "b"]
    assert [m["tool_call_id"] for m in chat[3:]] == ["a", "b"]


@pytest.mark.parametrize("http_status,code", [(400, "provider_http_error"), (401, "provider_authentication_failed"), (429, "provider_rate_limited")])
def test_groq_provider_error_redaction_no_retry_mock(monkeypatch, http_status, code):
    from app.llm import GroqLLM
    dummy = "gsk_synthetic_only_not_a_real_credential"
    monkeypatch.setenv("GROQ_API_KEY", dummy)
    original_client = httpx.Client
    requests = []
    def handler(request):
        requests.append(request.url)
        return httpx.Response(http_status, json={"error": {"code": "tool_use_failed", "type": "invalid_request_error",
            "message": "Controlled failure; secret " + dummy, "failed_generation": "not persisted"}}, headers={"x-request-id": "mock-request"})
    monkeypatch.setattr("app.llm.httpx.Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    provider = GroqLLM()
    with pytest.raises(ProviderError) as exc:
        provider.respond([], [], "test", 1)
    assert exc.value.code == code
    assert exc.value.details["http_status"] == http_status
    assert exc.value.details["code"] == "tool_use_failed"
    assert dummy not in json.dumps(exc.value.details)
    assert "failed_generation" not in exc.value.details
    assert provider.request_count == len(requests) == 1


def test_groq_default_missing_key_no_fallback(setup, monkeypatch):
    from app.llm import GroqLLM
    client, body, _ = setup
    main.app.dependency_overrides.clear()
    monkeypatch.delenv("ADAPTSENSE_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-openai-key-not-a-fallback")
    assert client.get("/investigations/config").json()["provider"] == "groq_chat_completions"
    assert client.post("/investigations", json=body).status_code == 503
    monkeypatch.setenv("GROQ_API_KEY", "gsk_controlled_not_real")
    assert isinstance(get_provider(), GroqLLM)


@pytest.mark.parametrize("finish_reason", ["length", "stop"])
def test_groq_incomplete_or_non_tool_reply_mock(monkeypatch, finish_reason):
    from app.llm import GroqLLM
    monkeypatch.setenv("GROQ_API_KEY", "gsk_controlled_not_real")
    original_client = httpx.Client
    def handler(request):
        return httpx.Response(200, json={"choices": [{"finish_reason": finish_reason, "message": {"content": "controlled text"}}]})
    monkeypatch.setattr("app.llm.httpx.Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    result = GroqLLM().respond([], [], "test", 1)
    assert result["status"] == "incomplete" and result["finish_reason"] == finish_reason


def test_groq_full_http_tool_round_trip_is_offline_mock(setup, monkeypatch):
    from app.llm import GroqLLM
    client, body, _ = setup
    monkeypatch.setenv("GROQ_API_KEY", "gsk_controlled_not_real")
    provider = GroqLLM()
    main.app.dependency_overrides[get_provider] = lambda: provider
    original_client = httpx.Client
    transcript = []
    def handler(request):
        payload = json.loads(request.content)
        transcript.append(payload)
        if len(transcript) == 1:
            calls = [call("replay_summary", {}, "summary"), call("compare_baseline", {}, "baseline")]
        else:
            outputs = [json.loads(m["content"]) for m in payload["messages"] if m["role"] == "tool"]
            assert [o["evidence_id"] for o in outputs] == ["E1", "E2"]
            status = outputs[0]["data"]["status"]
            report = {"status": status, "findings": [
                {"statement": "The saved assessment is {{E1:/status}}.", "references": ["E1:/status"]},
                {"statement": "Recent model error is {{E2:/recent/model_mae}} against baseline error {{E2:/recent/baseline_mae}}.",
                 "references": ["E2:/recent/model_mae", "E2:/recent/baseline_mae"]}],
                "hypotheses": [], "next_checks": ["Review external measurements before proposing causes."]}
            calls = [call("finish_investigation", report, "finish")]
        return httpx.Response(200, json={"id": f"offline-mock-{len(transcript)}", "model": "controlled-http-mock",
            "choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": c["call_id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls]}}]})
    monkeypatch.setattr("app.llm.httpx.Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    response = client.post("/investigations", json=body)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["provider_request_count"] == 2
    assert saved["report"]["status"] == "no_deterioration_detected"
    assert saved["provider_responses"][-1]["tool_calls"][0]["name"] == "finish_investigation"
    assert saved["agent_submissions"][0]["status"] == "no_deterioration_detected"
    assert client.get(f'/investigations/{saved["id"]}').json()["tool_trace"] == saved["tool_trace"]

