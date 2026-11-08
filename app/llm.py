"""Explicit hosted-provider adapters, with bounded requests and no retries."""
import os
import re

import httpx
from fastapi import HTTPException
from .credentials import groq_key

DEFAULT_MODEL = "gpt-5.6-terra"
GROQ_MODEL = "openai/gpt-oss-20b"


def safe_error_text(value, key=""):
    text = str(value)
    if key:
        text = text.replace(key, "[REDACTED]")
    return re.sub(r"\b(?:gsk_|sk-)[A-Za-z0-9_-]+", "[REDACTED]", text)[:700]


class ProviderError(Exception):
    def __init__(self, code, details=None):
        super().__init__(code)
        self.code = code
        self.details = details or {}


def post_json(url, body, key, timeout_seconds):
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout_seconds, connect=min(10, timeout_seconds))) as client:
            response = client.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
    except httpx.TimeoutException:
        raise ProviderError("provider_timeout") from None
    except httpx.HTTPError:
        raise ProviderError("provider_network_error") from None
    if response.status_code >= 400:
        details = {"http_status": response.status_code}
        try:
            error = response.json().get("error", {})
            if isinstance(error, dict):
                for field in ("code", "type", "message"):
                    if field in error:
                        details[field] = safe_error_text(error[field], key)
        except (ValueError, AttributeError):
            pass
        for header in ("x-request-id", "retry-after"):
            if header in response.headers:
                details[header] = safe_error_text(response.headers[header], key)
        code = "provider_rate_limited" if response.status_code == 429 else (
            "provider_authentication_failed" if response.status_code in (401, 403) else "provider_http_error")
        raise ProviderError(code, details)
    try:
        result = response.json()
    except ValueError:
        raise ProviderError("provider_invalid_json") from None
    if not isinstance(result, dict):
        raise ProviderError("provider_invalid_response")
    return result


class HostedLLM:
    mode = "hosted_openai"

    def __init__(self):
        self.key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.model = os.environ.get("ADAPTSENSE_LLM_MODEL", DEFAULT_MODEL)
        if not self.key:
            raise HTTPException(503, "OPENAI_API_KEY is not configured; no hosted request was attempted")

    def respond(self, messages, tools, instructions, timeout_seconds):
        body = {"model": self.model, "input": messages, "instructions": instructions,
                "tools": tools, "tool_choice": "required", "parallel_tool_calls": True,
                "reasoning": {"effort": "low"}, "max_output_tokens": 2500, "store": False}
        return post_json("https://api.openai.com/v1/responses", body, self.key, timeout_seconds)


def chat_messages(messages, instructions):
    converted = [{"role": "system", "content": instructions}]
    pending = []

    def flush():
        if pending:
            converted.append({"role": "assistant", "content": None, "tool_calls": list(pending)})
            pending.clear()

    for item in messages:
        if item.get("type") == "function_call":
            pending.append({"id": item["call_id"], "type": "function", "function": {
                "name": item["name"], "arguments": item["arguments"]}})
        else:
            flush()
            if item.get("type") == "function_call_output":
                converted.append({"role": "tool", "tool_call_id": item["call_id"], "content": item["output"]})
            elif item.get("role") in ("user", "assistant"):
                converted.append({"role": item["role"], "content": item["content"]})
            else:
                raise ProviderError("unsupported_conversation_item")
    flush()
    return converted


def groq_tools(tools):
    result = []
    for tool in tools:
        schema = tool["parameters"]
        definitions = schema.get("$defs", {})

        def expand(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    return expand(definitions[value["$ref"].split("/")[-1]])
                return {k: expand(v) for k, v in value.items() if k != "$defs"}
            return [expand(v) for v in value] if isinstance(value, list) else value

        # Provider schema guidance does not replace our local argument/report validation.
        result.append({"type": "function", "function": {"name": tool["name"],
                       "description": tool["description"], "parameters": expand(schema)}})
    return result


class GroqLLM:
    mode = "hosted_groq"

    def __init__(self):
        self.key = groq_key()
        self.model = GROQ_MODEL
        self.request_count = 0
        if not self.key:
            raise HTTPException(503, "GROQ_API_KEY is not configured; no hosted request was attempted")

    def respond(self, messages, tools, instructions, timeout_seconds):
        body = {"model": self.model, "messages": chat_messages(messages, instructions),
                "tools": groq_tools(tools), "tool_choice": "required", "parallel_tool_calls": True,
                "reasoning_effort": "low", "include_reasoning": False, "max_completion_tokens": 2500}
        self.request_count += 1
        result = post_json("https://api.groq.com/openai/v1/chat/completions", body, self.key, timeout_seconds)
        try:
            choice = result["choices"][0]
            finish = choice["finish_reason"]
            calls = choice["message"].get("tool_calls") or []
            output = [{"type": "function_call", "call_id": call["id"],
                       "name": call["function"]["name"], "arguments": call["function"]["arguments"]}
                      for call in calls if call["type"] == "function"]
        except (KeyError, IndexError, TypeError, AttributeError):
            raise ProviderError("provider_invalid_response") from None
        return {"id": result.get("id"), "model": result.get("model"), "usage": result.get("usage"),
                "status": "completed" if finish == "tool_calls" and output else "incomplete",
                "finish_reason": finish, "output": output}


def provider_config():
    name = os.environ.get("ADAPTSENSE_LLM_PROVIDER", "groq").lower()
    if name == "groq":
        return {"provider": "groq_chat_completions", "model": GROQ_MODEL,
                "configured": bool(groq_key())}
    if name == "openai":
        return {"provider": "openai_responses", "model": os.environ.get("ADAPTSENSE_LLM_MODEL", DEFAULT_MODEL),
                "configured": bool(os.environ.get("OPENAI_API_KEY", "").strip())}
    raise HTTPException(503, "Unsupported ADAPTSENSE_LLM_PROVIDER; no automatic fallback")


def get_provider():
    config = provider_config()
    return GroqLLM() if config["provider"] == "groq_chat_completions" else HostedLLM()


