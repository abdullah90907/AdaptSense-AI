# Phase 4B — Interactive forecasting workflow

## Added

A new forecasting workspace preserves the existing bright design and saved-evidence explorer. Users can upload or paste CSV/JSON, review exact first/last readings and cadence, name the series, retain its original unit, and choose a horizon of 1–64 steps. Validation reports timezone, calendar, ordering, duplicate, gap, size and value errors before submission.

The Run button reuses `POST /series` and `POST /forecasts`. Progress reflects actual saving/inference stages with elapsed time; controls prevent duplicate submissions and there are no automatic retries. Results show the saved median, q10/q90 estimates, original context and model revision. Fresh forecasts show pending actuals, not invented accuracy metrics.

Later actuals reuse the existing evaluation API. One new reading is supported by merging it with unchanged historical context before saving an actuals snapshot. Conflicting saved observations, unit mismatches in JSON metadata, off-grid timestamps and gaps are rejected by the UI. Identical history may be included in a later snapshot. Forecasts are not regenerated when actuals arrive. Saved run URLs restore their records without inference; JSON exports retain full values and provenance.

Backend changes are limited to optional client-supplied provenance, stricter validation of model output intervals, and sourced demo CSV downloads. Forecast/evaluation calculations and chronological replay algorithms are unchanged. Provenance hashes identify submitted content; they do not establish independent source authenticity.

## Actual verification

**44 backend tests and 20 frontend tests passed; production build passed.** Tests cover parsing, timestamps, missing/gapped/invalid readings, partial actuals, conflicts, provenance, API contracts, and regression behavior. Controlled inference fixtures are separate from the genuine run below.

Verified the production application through the browser:

1. Uploaded 300 sourced Victoria daily-demand observations as CSV; preview showed January 1–October 27, 2014, with original values and units.
2. Ran **one genuine cached Chronos-Bolt Tiny CPU forecast**, horizon 32. Hugging Face networking was disabled (`HF_HUB_OFFLINE=1`). No training or downloads occurred. Initially all 32 forecast steps had pending actuals and no accuracy metrics.
3. Pasted one separately supplied JSON actual: **1 matched / 31 pending**, MAE **6.8535464344**.
4. Submitted the complete later-actual CSV: **32 matched / 0 pending**, MAE **11.8339809929**, RMSE **14.1266614512**, q10–q90 coverage **93.75%**. These describe this historical split, not general model performance.
5. Reloaded the saved URL and exported the result. Independently recomputed metrics, compared export values, confirmed the input hash and immutable predictions, and verified every previous database record was unchanged. Exactly one new forecast and three source/actuals snapshots were created; no new replay or investigation records.

Forecast ID: `ba401e8f-3442-4c1d-a06f-84c75aae2ebc`. Full evidence/checks: `data/phase4b-verification.json`. Source: the existing `fpp2::elecdaily` Victoria example, attributed in README; its GW source label and daily UTC indexing convention are preserved.

## Run and limits

Build with `npm run build --prefix frontend`, then start:

```powershell
$env:HF_HUB_OFFLINE='1'
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/` and select **New forecast**. The existing development command and proxy remain compatible.

Inputs remain regular, finite, nonnegative univariate readings: at least 32 history points, 2 MB per imported text/file, 20,000 readings per saved snapshot, millisecond timestamp precision. The model uses at most the latest 2,048 context points. Combined history/actuals snapshots must fit the server's limit. No missing-value repair or unit conversion occurs. Quantiles are not calibrated guarantees; single-origin evaluation does not establish period-level deterioration. Source/meter identity and CSV units remain caller supplied. CPU requests are synchronous; there is no background job queue or cancellation guarantee.

Potential next steps for review: a recent-runs library, custom-data replay controls, and background execution for larger demonstrations. None were implemented here.

No hosted LLM calls, accounts, unrelated models, LifelineTwin changes, commits or pushes. Phase 4B stops here.
