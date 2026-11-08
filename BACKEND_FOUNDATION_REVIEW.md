# AdaptSense backend foundation review

## Current implementation

| Area | Inspected behavior |
| --- | --- |
| Ingest and forecast | FastAPI accepts regular, nonnegative CSV or JSON series and normalizes timezone-aware timestamps to UTC. The pinned Chronos-Bolt Tiny checkpoint loads lazily on CPU. Inference uses up to 2,048 observations through the requested cutoff and returns median, q10 and q90. |
| Evaluation | Exact timestamp and unit matching supports partial actuals. MAE, RMSE and interval coverage are computed on demand from saved inputs and predictions. The legacy early-versus-late error flag mixes forecast leads and is unsuitable for drift decisions. |
| Replay | Equal reference and recent periods use fixed context and the same lead mix. Each origin sees only its history. Nonoverlapping target blocks and a seasonal-naive forecast make the comparison reproducible. Replay runs fresh inference for every origin on every request. |
| Reliability | A moving-block bootstrap compares origin MAEs. The decision also uses a practical threshold and checks both halves of the recent period. The interval is descriptive and its assumptions, block length and false-alert rate have limited validation. Chronos quantiles are uncalibrated model estimates. |
| Persistence and investigation | SQLite stores JSON snapshots of series, forecasts, replays and investigation traces. Evaluations are computed on request. Offline tests exercise evidence tools, numeric citations and provider failure handling. Qualitative interpretation still requires review. Hosted investigation was outside this verification. |

## Verification and changes

**45 backend tests passed.** Fresh inference from the existing checkpoint cache exercised CSV ingest, forecast, evaluation, replay and retrieval through FastAPI TestClient. The Victoria 2014 fixture supplied 365 daily readings. For the 32-step forecast after the 300th reading, all 32 timestamps matched, with MAE **11.834**, RMSE **14.127** and q10–q90 coverage **30/32 (93.75%)**. Errors are in the dataset's source GW units.

| Replay measure | Reference | Recent |
| --- | ---: | ---: |
| Origins / observations | 20 / 140 | 20 / 140 |
| Chronos MAE | 10.105 | 10.282 |
| Weekly seasonal-naive MAE | 9.861 | 10.252 |
| Chronos q10–q90 coverage | 82.14% | 83.57% |

The replay returned `no_deterioration_detected`. The Chronos MAE increase was 0.178 against a 2.021 threshold, with a 95% bootstrap interval of [−2.243, 2.894]. Seasonal naive had lower MAE in both periods. Independent checks matched every replay target and seasonal-naive value to the source rows, recomputed forecast metrics and replay MAEs, and confirmed the stored predictions and origins could be retrieved. The test database is `.tmp/backend-foundation-verified.db`. Forecast ID `0460bda3-ee76-4279-8a79-225cc9d73438` and replay ID `ee043eca-9e62-4d6a-b26f-2608692401d1`.

Forecasts now reject target timestamps beyond the supported date range with HTTP 422 before inference, covered by a regression test. SQLite connections now close deterministically after the transaction exits. The changes use existing dependencies and preserve the API shapes and forecasting calculations.

## Research references

- The EXAMM-Extended README documents recurrent architecture search, configurable recurrent skips and population diversity strategies. Those ideas inform a future experiment where accuracy and model cost are measured together. [EXAMM-Extended README](https://github.com/zimenglyu/EXAMM-Extended#readme)
- The ONE-NAS README and paper describe evolving recurrent structures and weights as observations arrive. Their online evaluation setup motivates testing decisions on later observations. AdaptSense currently runs frozen inference and retrospective replay. [ONE-NAS README](https://github.com/zimenglyu/ONENAS#readme) · [ONE-NAS paper](https://arxiv.org/abs/2302.10347)

The research review covered documentation and repository listings. The AdaptSense review covered local implementation and tests. A local research clone would be useful only for a separate reproduction experiment. At that point, clone a pinned ONE-NAS revision outside this project and start with `scripts/one-nas/coal_mpi.sh`, the root `CMakeLists.txt`, and the runner, windowing and evaluation sources those files select under `mpi/`, `onenas/` and `time_series/`. Inspect EXAMM-Extended's `CMakeLists.txt` and corresponding `examm/` and `rnn/` sources only if mutation or weight inheritance becomes part of the experiment. Confirm licensing before reuse.

## Recommended Phase 2

1. **Record predictions before scoring.** Build a local append-and-score workflow and exercise it by feeding the Victoria readings in timestamp order. Save model revision, context, cutoff, lead and target before ingesting each target. Attach actuals idempotently using a stable series ID and timestamp. Test duplicates, missing or delayed readings and restart recovery. Compare identical historical configurations against replay.
2. **Measure matched-lead skill and propose actions.** Score Chronos and the existing seasonal naive at the same origins, then compare paired errors and coverage on completed windows. Expose sample counts and uncertainty and report insufficient evidence for thin windows. Run any candidate change in parallel and use a later evaluation period before recommending promotion. Calibrate repeated alerting across more periods and series before treating it as operational.

Keep SQLite for the local, single-writer workflow. Add indexed observation and scored-prediction tables when incremental scoring needs them. Current UUID/JSON snapshots remain suitable for immutable experiment artifacts, while incremental joins, deduplication and queries across runs need explicit keys. Compare an additional simple candidate, such as persistence, only when it answers a specific question. Defer hosted orchestration and evolutionary experiments until the sequential evaluation can show whether an alternative improves future error, coverage or inference cost.

Verification covers one dataset and checkpoint in the local CPU environment. It establishes chronological application inputs, with pretraining overlap unknown. Streaming workloads, concurrent writers, prospective alert rates and gains from adaptation remain unmeasured.
