# Groq agent verification

## Integration

Reviewed Phase 3 and its report. Groq Chat Completions is now the default hosted adapter, pinned to the requested `openai/gpt-oss-20b`; the explicit OpenAI option remains without fallback. Existing forecasting, replay, reliability rules, SQLite records and read-only tools are preserved. The adapter groups assistant tool calls, returns matched tool-result IDs, and normalizes hosted calls into the existing bounded agent loop. Local schema/citation/status validation is unchanged.

Credentials come from `GROQ_API_KEY` or hidden terminal input and remain in process memory. Errors retain sanitized HTTP status/provider code/type/message and request metadata, excluding raw bodies, failed-generation text and private reasoning. Bounds remain four model turns, ten analytical calls, 2,500 completion tokens per turn and 120 seconds. No retries or provider switching. The live runner reserves an exclusive attempt marker before sending the single investigation request.

References: [Groq local tool calling](https://console.groq.com/docs/tool-use/local-tool-calling), [GPT-OSS 20B model](https://console.groq.com/docs/model/openai/gpt-oss-20b).

## Offline verification

**32 tests passed in 1.72 seconds.** Existing regressions plus Groq wire-format/schema translation, multi-call grouping, result IDs, missing-key/no-fallback behavior, incomplete replies, redacted provider errors, request counts, and a complete HTTP-mocked tool loop. These use controlled responses and are not live-model results.

## Live verification

**One genuine attempt failed authentication. No retry or provider switch was made.** The interactive hidden-input runner reserved the attempt and sent one request to Groq at 17:14:13 Asia/Karachi on October 26, 2026.

- Investigation ID: `9796191f-b373-46ad-98e7-94a1423abe5d`.
- Provider/model: Groq / `openai/gpt-oss-20b`.
- HTTP requests attempted: **1**; completed model responses: **0**.
- Provider result: **HTTP 401**, code `invalid_api_key`, type `invalid_request_error`, message `Invalid API Key`.
- Provider request ID: `req_01m5w23v6febfb5yss6y3xgsss`.
- Persisted state: `failed`; local API returned HTTP 502 with the saved failure ID.
- Actual analytical tool calls: **none**. Authentication failed before model-controlled tool selection.
- Elapsed investigation time: **0.55 seconds**.

The failure and its empty tool trace were retrieved through `GET /investigations/{id}`; the original replay and forecast remain retrievable. The exclusive attempt marker remains in place. Details and verification: `data/groq-verification-result.json`; reservation: `data/groq-verification-attempt.json`. No successful report or hosted explanation was generated or substituted.

## Evidence and diagnosis

A separate **local-only** evidence check confirms the persisted replay remains `no_deterioration_detected`. Recent model MAE is **10.2821737171**, against seasonal-naive MAE **10.2518534111**; the model slightly underperformed the baseline. These are existing analytical measurements, not conclusions produced by Groq. Because authentication failed, final hosted findings, citation quality and autonomous tool choice could not be validated.

The error identifies credential authentication as the immediate blocker. It does not establish whether the entered credential was mistyped, revoked, or otherwise invalid; it does not test model access or tool-schema compatibility. A valid replacement credential and separately authorized future attempt are needed to verify those remaining points. No additional authentication probe or live investigation was launched.

Credentials were not placed in project code, shell command arguments, reports or saved evidence. Sanitized provider error metadata excludes the credential and raw response body. A local database check found no Groq credential prefix in persisted records.

## Remaining limitations and stop point

The integration and controlled regression checks pass, but genuine hosted investigation success remains **unverified**. The existing qualitative-interpretation, retrospective replay, seasonal-confounding and local-service limitations remain. No new forecast inference, training, checkpoint download, frontend, accounts, LifelineTwin changes, commits or pushes. Stopped after the single genuine failed attempt and local diagnostics.

