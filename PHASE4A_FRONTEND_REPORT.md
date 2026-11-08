# Phase 4A — Frontend report

Implemented React/TypeScript/Vite frontend in `frontend/`, connected to the existing local FastAPI backend. Final visual direction follows the requested revision: bright white/slate surfaces, clear blue forecast accents and warm neutral baseline colors. No green or purple theme. Includes chart entrance animation, page transitions, drawer motion, hover feedback and reduced-motion support.

## Working experience

- Existing Victoria 2014 readings, saved Chronos median forecasts, actuals and q10–q90 bands.
- Time ranges, hover/keyboard/slider inspection, independent chart-layer toggles.
- Saved chronological replay, matched-lead comparisons, uncertainty interval and decision-rule evidence.
- Reference/recent seasonal-naive comparisons and sortable forecast-window drilldown.
- Provenance/model-revision drawer, exact forecast rows and JSON export with full original values.
- Responsive navigation and layouts; internal scrolling for wide evidence tables.

Only minimal read-only API support was added: `GET /demo` discovers persisted demo IDs/provenance, and `GET /forecasts/{id}/evaluation` wraps existing evaluation logic. No forecasting or reliability calculation changed. Production assets can be served by FastAPI after building; Vite development uses a same-origin API proxy.

## Verification completed before the request to stop design testing

Production build passed. **41 backend tests and 5 frontend tests passed.** npm reported zero dependency vulnerabilities after updating Vitest to its patched version. Browser checks covered chart range/layer changes, keyboard inspection, baseline period selection, replay-origin drilldown, evidence sections, original forecast rows and JSON download. Desktop and mobile rendering were inspected; a mobile overflow and an incorrect decision-rule drawer target were fixed. The bright theme was visually reviewed. Further design testing stopped when requested.

Actual displayed evidence: saved forecast MAE **11.83398**, coverage **93.75%**; replay status **no_deterioration_detected**; recent model/baseline MAE **10.28217 / 10.25185**. The interface does not claim model superiority, anomalies or successful hosted investigations. Figures are rounded only for display; exports retain precision.

## Run

From the project root:

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

After `npm install --prefix frontend` and `npm run build --prefix frontend`, open `http://127.0.0.1:8765/`. For frontend development, also run `npm run dev --prefix frontend` and open `http://127.0.0.1:5174/`. Port 5173 was already occupied and was left alone. Start FastAPI after building so it mounts the compiled frontend.

## Limits

This phase browses existing saved evidence; it does not upload new datasets or issue new forecasts from the UI. AI investigation is marked as a later workspace and is not connected to hosted requests. Dataset dates use the documented UTC indexing convention and preserve the source's GW label without conversion. Quantile bands are estimates, not calibrated guarantees. Formal accessibility and cross-browser certification were not performed. Existing local-only/no-auth backend limitations remain.

No hosted LLM calls, training, checkpoint downloads, LifelineTwin modifications, commits or pushes. Phase 4A stops here.
