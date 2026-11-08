import csv
import io
import logging
import json
import math
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel, Field, field_validator

from .model import Forecaster, MODEL_ID

app = FastAPI(title="AdaptSense AI", version="0.3.0")
forecaster = Forecaster()
DB = Path(os.environ.get("ADAPTSENSE_DB", "data/adaptsense.db"))


def connection():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT, body TEXT)")
    db.execute("CREATE INDEX IF NOT EXISTS records_kind ON records(kind)")
    return db


def save(kind, body):
    key = str(uuid4())
    with closing(connection()) as db, db:
        db.execute("INSERT INTO records VALUES (?, ?, ?)", (key, kind, json.dumps(body)))
    return {"id": key, **body}


def update(key, kind, body):
    with closing(connection()) as db, db:
        db.execute("UPDATE records SET body=? WHERE id=? AND kind=?", (json.dumps(body), key, kind))


def get(key, kind):
    with closing(connection()) as db:
        row = db.execute("SELECT body FROM records WHERE id=? AND kind=?", (key, kind)).fetchone()
    if not row:
        raise HTTPException(404, f"Unknown {kind}")
    return json.loads(row[0])


class Reading(BaseModel):
    timestamp: datetime
    value: float = Field(allow_inf_nan=False, ge=0)

    @field_validator("timestamp")
    @classmethod
    def utc(cls, value):
        if value.tzinfo is None:
            raise ValueError("Use timezone-aware timestamps")
        return value.astimezone(timezone.utc)


class SourceProvenance(BaseModel):
    kind: Literal['csv_upload', 'json_upload', 'pasted_csv', 'pasted_json', 'demo', 'submitted_actuals']
    label: str = Field(min_length=1, max_length=255)
    sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    note: str = Field(default='User supplied; not independently verified.', max_length=500)
    verification: Literal['client_supplied'] = 'client_supplied'


class Series(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    unit: str = Field(min_length=1, max_length=40)
    readings: list[Reading] = Field(min_length=32, max_length=20000)
    provenance: SourceProvenance | None = None


def validate_series(series):
    times = [r.timestamp for r in series.readings]
    step = times[1] - times[0]
    if step.total_seconds() <= 0 or any(b - a != step for a, b in zip(times, times[1:])):
        raise HTTPException(422, "Readings must be sorted, unique and regularly spaced; no implicit imputation")
    return step


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_ID, "model_loaded": forecaster.pipeline is not None}


@app.get("/health/ready")
def readiness():
    try:
        with closing(connection()) as db:
            db.execute("SELECT id FROM records LIMIT 1").fetchone()
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(503, "Database unavailable") from exc
    return {"status": "ready"}


@app.post("/series", status_code=201)
def create_series(series: Series):
    validate_series(series)
    return save("series", series.model_dump(mode="json"))


@app.post("/series/csv", status_code=201)
async def upload_csv(name: str, unit: str, file: UploadFile = File(...)):
    raw = await file.read(2_000_001)
    if len(raw) > 2_000_000:
        raise HTTPException(413, "CSV limit is 2 MB")
    try:
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        series = Series(name=name, unit=unit, readings=[Reading(**r) for r in rows])
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "CSV requires timestamp,value columns with valid readings") from exc
    return create_series(series)


@app.get("/series/{series_id}")
def read_series(series_id: str):
    return get(series_id, "series")


class ForecastRequest(BaseModel):
    series_id: str
    cutoff: datetime
    horizon: int = Field(default=24, ge=1, le=64)


@app.post("/forecasts", status_code=201)
def forecast(request: ForecastRequest):
    series = Series(**get(request.series_id, "series"))
    step = validate_series(series)
    if request.cutoff.tzinfo is None:
        raise HTTPException(422, "cutoff must include a timezone")
    history = [r for r in series.readings if r.timestamp <= request.cutoff]
    if len(history) < 32 or history[-1].timestamp != request.cutoff:
        raise HTTPException(422, "cutoff must match a reading with at least 32 history points")
    try:
        targets = [history[-1].timestamp + step * lead for lead in range(1, request.horizon + 1)]
    except OverflowError as exc:
        raise HTTPException(422, "Forecast horizon exceeds the supported timestamp range") from exc
    values = [r.value for r in history]
    try:
        quantiles, mean = forecaster.predict(values, request.horizon)
    except Exception as exc:
        logging.getLogger(__name__).exception("Pretrained inference failed")
        raise HTTPException(503, "Pretrained inference unavailable; check model cache/network and server logs") from exc
    if len(quantiles) != request.horizon or any(len(row) != 3 or not all(math.isfinite(x) for x in row) or not row[0] <= row[1] <= row[2] for row in quantiles) or not all(map(math.isfinite, mean)):
        raise HTTPException(503, "Model returned invalid prediction intervals; no forecast was saved")
    scale = max(float(np.mean(np.abs(np.diff(values[-168:])))), 1e-6)
    return save("forecast", {
        "series_id": request.series_id, "model": MODEL_ID, "revision": forecaster.revision,
        "cutoff": history[-1].timestamp.isoformat(), "created_at": datetime.now(timezone.utc).isoformat(),
        "unit": series.unit, "context_count": min(len(values), 2048), "error_scale": scale,
        "source_provenance": series.provenance.model_dump(mode="json") if series.provenance else None,
        "history_mean": float(np.mean(values[-168:])),
        "history_std": float(np.std(values[-168:])),
        "predictions": [{"timestamp": target.isoformat(),
                         "point": q[1], "q10": q[0], "q50": q[1], "q90": q[2]}
                        for target, q in zip(targets, quantiles)],
    })


@app.get("/forecasts/{forecast_id}")
def read_forecast(forecast_id: str):
    return get(forecast_id, "forecast")


class EvaluationRequest(BaseModel):
    actual_series_id: str


@app.post("/forecasts/{forecast_id}/evaluate")
def evaluate(forecast_id: str, request: EvaluationRequest):
    run = get(forecast_id, "forecast")
    actual = Series(**get(request.actual_series_id, "series"))
    validate_series(actual)
    if actual.unit != run["unit"]:
        raise HTTPException(422, "Actual and forecast units must match")
    lookup = {r.timestamp.isoformat(): r.value for r in actual.readings}
    evidence = []
    for p in run["predictions"]:
        if p["timestamp"] in lookup:
            y = lookup[p["timestamp"]]
            evidence.append({**p, "actual": y, "absolute_error": abs(y - p["q50"]),
                             "outside_q10_q90": y < p["q10"] or y > p["q90"]})
    if not evidence:
        raise HTTPException(422, "No actual readings match the forecast timestamps")
    errors = np.array([e["absolute_error"] for e in evidence])
    n = len(errors)
    window = n // 2
    baseline = float(errors[:window].mean()) if window else None
    recent = float(errors[-window:].mean()) if window else None
    sufficient = window >= 8
    degraded = sufficient and recent > max(1.5 * baseline, baseline + run["error_scale"])
    observed_mean = float(np.mean([e["actual"] for e in evidence]))
    shift = abs(observed_mean - run["history_mean"]) / max(run["history_std"], run["error_scale"])
    return {"forecast_id": forecast_id, "matched": n, "pending": len(run["predictions"]) - n,
            "metrics": {"mae": float(errors.mean()), "rmse": float(np.sqrt(np.mean(errors ** 2))),
                        "scaled_mae": float(errors.mean() / run["error_scale"]),
                        "q10_q90_coverage": float(np.mean([not e["outside_q10_q90"] for e in evidence]))},
            "reliability": {"status": "insufficient_evidence" if not sufficient else "degraded" if degraded else "no_degradation_detected",
                            "method": "legacy_within_forecast_lead_comparison", "advisory": "Lead-time confounded; use /replays for fixed-lead period evidence.",
                            "baseline_mae": baseline, "recent_mae": recent, "window_size": window,
                            "rule": "At least 8 errors per half; recent MAE > max(1.5 * baseline MAE, baseline MAE + historical mean absolute first difference)"},
            "change": {"mean_shift_in_historical_std": shift, "flag": shift > 3,
                       "interpretation": "Descriptive level change; seasonality or external events may explain it. Not a causal conclusion."},
            "evidence": evidence,
            "limitations": "Quantiles are model estimates, not calibrated guarantees. Reliability compares early and late leads in this forecast; horizon effects may contribute. Actual series identity is caller supplied."}


from .replay import router as replay_router
app.include_router(replay_router)

from .adaptive import router as adaptive_router
app.include_router(adaptive_router)


from .investigation import router as investigation_router
if os.getenv("ADAPTSENSE_ENABLE_INVESTIGATION", "1") == "1":
    app.include_router(investigation_router)


from .demo import router as demo_router
app.include_router(demo_router)

from .catalog import router as catalog_router
app.include_router(catalog_router)

from fastapi.staticfiles import StaticFiles
_frontend_dist = Path(__file__).resolve().parents[1] / 'frontend' / 'dist'
if _frontend_dist.is_dir():
    app.mount('/', StaticFiles(directory=_frontend_dist, html=True), name='frontend')

