# Phase 4 backend integration

The frontend can discover saved datasets, submit experiments, follow progress, and open results through FastAPI. Dataset IDs connect forecasts, reliability replays, and adaptive experiments. Forecast evaluation and replay investigation remain available through their existing endpoints.

| Operation | API |
| --- | --- |
| Upload, select, or inspect a dataset | `POST /series`, `POST /series/csv`, `GET /series`, `GET /series/{id}`, `GET /demo` |
| Forecast and score against actuals | `POST /forecasts`, `GET /forecasts`, `GET /forecasts/{id}`, `POST /forecasts/{id}/evaluate` |
| Inspect reliability and evidence | `POST /replays`, `GET /replays`, `GET /replays/{id}`, and the existing optional investigation endpoints |
| Run, track, and reopen an adaptive experiment | `POST /adaptive-experiments?background=true`, `GET /adaptive-experiments/{id}/status`, `GET /adaptive-experiments`, `GET /adaptive-experiments/{id}` |
| Inspect adaptation or compare runs | `GET /adaptive-experiments/{id}/comparison`, optionally with `against=<id>` |

Lists provide cursor pagination and omit detailed readings and predictions. Forecast, replay, and experiment lists can be filtered by dataset. Background requests return HTTP 202 with a saved run ID. Progress counts scored origins. One adaptive run is accepted at a time per process, with HTTP 409 when busy. A failed run retains its recorded evidence. An unfinished run from a previous process is reported as interrupted.

The comparison checks dataset identity, horizon, and target timestamps before reporting differences between runs. It shows the best observed fixed forecast, error gaps, and the adaptation rule's separate recommendation for a hypothetical next origin. Evolutionary validation and later replay scores are visible together.

## Verification

**52 backend tests passed.** New tests exercise active polling, admission control, restart visibility, cursor pagination, and rejection of comparisons with unmatched evaluation targets.

A local HTTP run uploaded the Victoria CSV and used cached Chronos-Bolt Tiny inference. The 32-point forecast reproduced MAE 11.834, RMSE 14.127, and 93.75% interval coverage. The fixed-lead replay reported `no_deterioration_detected`. The background experiment returned HTTP 202 in about 8 ms and progressed through queued, running, and 36 completed origins. A second run used the same settings with evolution omitted. The comparison endpoint returned these results on 210 targets after warm-up, in source GW units.

| Model or policy | MAE | RMSE |
| --- | ---: | ---: |
| Weekly seasonal naive | **9.821** | **12.933** |
| Chronos-Bolt Tiny | 10.154 | 13.143 |
| Evolved RNN | 12.148 | 15.995 |
| Adaptive with two candidates | 10.135 | 13.128 |
| Adaptive with three candidates | 10.182 | 13.247 |

Adding the evolved model increased adaptive MAE by 0.047 on the matched targets. The next-origin rule recommended retaining Chronos based on the final six scored blocks. Seasonal naive had the lowest fixed MAE over the full evaluation window. The next-origin recommendation is unscored. Verification used `.tmp/phase4-backend-verified.db`, with experiment IDs `42e42ea0-ad72-4fcd-9579-cc927084d46f` and `a949967a-5848-4efb-8e0c-70e8435a5faa`.

## Run locally

From the project root with the existing environment and cached model:

```powershell
$env:HF_HUB_OFFLINE='1'
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Swagger UI is at `http://127.0.0.1:8765/docs`. For frontend development, keep one server worker. Background execution has no durable queue, cancellation, or resumption, and progress is reported by scored block rather than evolutionary generation. Forecast and reliability replay creation remain synchronous. Hosted investigation is optional and was not exercised live in this verification.
