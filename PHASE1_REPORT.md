# AdaptSense AI — Phase 1 report

Implemented independently in this directory. No LifelineTwin files were accessed or modified. No frontend, accounts, training, commits, or pushes.

## Working backend

FastAPI endpoints support JSON/CSV readings, SQLite persistence, frozen CPU Chronos-Bolt Tiny inference, immutable forecast retrieval, and evaluation against separately uploaded later actuals. Forecasts contain median points, q10/q90 estimates, cutoff, checkpoint revision, historical context count, and history-only error scale. Evaluation provides MAE, RMSE, scaled MAE, interval coverage, timestamp-level residual evidence, descriptive level shifts, and an explicit reliability status.

Checkpoint: `amazon/chronos-bolt-tiny`, revision `a0e552de83495b5c28c14c71c374f3e33280b340`. Only this checkpoint was downloaded. Inputs are restricted to 2,048 historical points and horizons of 1–64; CPU threads are capped at four. Model inference is serialized.

## Verification performed

- Python 3.13.3, Windows CPU; tested dependency versions captured in `requirements-lock.txt`.
- `pytest`: **3 passed**. Checks cutoff isolation (future values never reach the predictor), exact error/coverage calculations, forecast persistence, invalid/negative/duplicate inputs, CSV ingestion, missing IDs, partial actuals, insufficient evidence, and controlled reliability degradation. These rule tests use a deterministic predictor and are not model benchmarks.
- `python -m scripts.demo`: **passed with genuine pretrained inference** through FastAPI TestClient. Used the bundled, sourced 365-day Victoria demand example; forecast issued from 300 observations before actuals were uploaded. Forecast 32 subsequent days: MAE **11.8339809929**, RMSE **14.1266614512**, scaled MAE **0.8792123992**, q10–q90 coverage **0.9375**. These are one example's observations, not general performance claims. Units preserve the source's GW label.
- Early/late 16-point MAEs: **13.9444407272 / 9.7235212586**; status **no_degradation_detected**. No real-data deterioration was manufactured.
- First demo execution, including checkpoint retrieval: **66.66 seconds**; process resident memory at completion **402.88 MB** (not peak system memory). Saved predictions and evidence: `data/demo-result.json`.
- Uvicorn startup and real HTTP health/OpenAPI smoke check on loopback port 8765. Port 8000 was occupied; the existing listener was left alone.

Restricted-runtime temporary-file and network access initially prevented installation/tests; execution succeeded with project-local temporary files and approved dependency/model network access.

## Limitations

Reliability is a transparent heuristic comparing early and late forecast errors, requiring at least eight observations per half. It is not a calibrated drift test, and forecast lead time can confound the comparison. Quantile exceedances and three-standard-deviation mean shifts are investigation signals, not diagnoses or causal explanations. No LLM agent is implemented; evidence is structured for later use.

Only regular, finite, nonnegative univariate readings are accepted; missing values require caller-side handling. A caller must associate the correct meter and units with actual readings. SQLite provides local persistence; evaluation is computed on request. This local service has no authentication or production hardening. Internet is needed for initial checkpoint retrieval; cached weights support later inference. No custom training/fine-tuning occurs. Public-demo overlap with pretraining data cannot be ruled out.

Research references and dataset attribution are in `README.md`. Inspired by Prof. Zimeng Lyu's work on nonstationary forecasting; this implementation does **not** implement ONE-NAS, neuroevolution, or online model training.

Phase 1 stops here.
