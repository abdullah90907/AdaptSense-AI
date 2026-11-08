# AdaptSense AI — Phase 3 report

## Implemented

Reviewed both previous reports and implementations before changes. Added a bounded evidence-aware investigator with `POST /investigations`, `GET /investigations/{id}`, and a configuration-check endpoint. Phase 1/2 endpoints remain compatible; app version is 0.3.0.

The lightweight agent loop uses the [OpenAI Responses function-calling API](https://developers.openai.com/api/docs/guides/function-calling), existing httpx, and a configurable [gpt-5.6-terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra) default at low reasoning effort. No new dependencies or model downloads. Tools inspect the requested replay summary, recompute model/seasonal-naive comparisons, compare fixed leads, compute descriptive level/variability/bias, rank worst completed windows, and optionally evaluate an existing saved forecast through Phase 1 logic. The model chooses tools and order; summary and baseline inspection are required before finishing.

Optional forecast contexts must match the replay source's timestamps, readings and units. Tools cannot select unrelated record IDs, write source data, train models, browse or execute code. Investigation records persist separately in SQLite.

## Evidence controls

Final status must match the persisted analytical status: supported deterioration, possible deterioration or none detected. The server supplies an appropriately qualified status summary. Findings cite exact scalar pointers into returned tool evidence. Numerical placeholders are rendered from those fields; numeric literals, invented references, invalid pointers and contradictory statuses are rejected. Each report retains the templates, resolved citations, tool arguments/results, original-record hashes, provider model/response metadata and available usage. Hypotheses are explicitly unverified possibilities with evidence needed to test them.

Bounds: four model turns, ten analytical calls, 2,500 output tokens per turn, 120-second deadline. No retries or provider/model fallback. Provider failures, incomplete replies, invalid reports or exhausted budgets produce a persisted failure and HTTP 502, without a successful report. Missing credentials return HTTP 503 before a hosted request. Credentials and raw provider error bodies are not saved or returned.

## Verification actually performed

**24 tests passed in 2.69 seconds**, including all six existing tests. New tests verify real analytical calculations and saved-forecast integration, report persistence, all status labels, evidence substitution, rejected invented numbers/references/status changes, context mismatch (including the cutoff reading), scope restrictions, missing-key API behavior, call/turn budgets, failure persistence, and HTTP-adapter request/success/error/timeout handling. Provider HTTP responses in tests use MockTransport; LLM replies use an explicitly scripted test double.

`python -m scripts.investigate_demo --controlled` completed through the actual FastAPI endpoint using six genuine analytical tools over the existing sourced electricity replay and forecast. It made three **scripted** model turns, produced six cited findings, and saved `data/phase3-controlled-result.json` plus a SQLite investigation record. No new forecasting run was needed: this phase examined persisted genuine Chronos inference, not fabricated predictions. All 18 saved report citations were independently resolved back to their tool evidence fields.

Verified findings include:

| Evidence | Actual value |
|---|---:|
| Replay reference/recent model MAE | 10.1047 / 10.2822 |
| Recent seasonal-naive MAE | 10.2519 |
| MAE change; practical threshold | 0.1775; 2.0209 |
| Bootstrap interval for MAE change | [-2.2431, 2.8935] |
| Reference/recent observed mean | 226.9418 / 213.0724 |
| Recent signed bias, actual minus point | -2.2983 |
| Worst recent seven-day window MAE | 30.3493, following Dec 24, 2014 cutoff |
| Optional Phase 1 forecast MAE; pending actuals | 11.8340; 0 |

These retain the source's demand units. Result: **no_deterioration_detected**; the model slightly underperformed seasonal naive in both periods. A high-error window was ranked, not declared an anomaly. No causal explanation, improvement or research outcome was asserted.

## Hosted execution and limits

**Genuine hosted-model execution was not performed.** No supported provider key was configured in the current environment, and no credential-provisioning tool was available. No paid or rate-limited request was attempted. The hosted adapter and tool loop pass controlled tests, but actual account/model access, hosted tool selection, output-schema acceptance, latency, cost and explanation quality remain unverified. The controlled script fixes tool choices and prose; it does not demonstrate autonomous LLM reasoning. An explicit `--hosted` demo is ready for one bounded run when `OPENAI_API_KEY` is configured.

Citations and numerical substitution do not formally verify qualitative interpretations, verbal arithmetic or causes. Those still require review; hypotheses require external measurements. Phase 2's bootstrap assumptions, seasonal confounding, limited sample size, repeated-testing limitation and pretraining-overlap caveat remain. No external weather/calendar data was fetched. The application is still local and unauthenticated, without streaming alerts. Selected evidence is sent to the configured hosted model when that mode is used; `store=false` is requested without claiming zero provider retention.

Research motivation remains Prof. Zimeng Lyu's work; this project does not implement ONE-NAS or online neuroevolution. No LifelineTwin changes, frontend, accounts, training, commits or pushes. Phase 3 backend implementation and controlled verification are complete; genuine hosted validation remains pending credentials. Stopped here.

