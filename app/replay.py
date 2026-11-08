import logging
import math
from datetime import datetime, timezone

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .model import MODEL_ID
from .reliability import assess

router = APIRouter()


def seasonal_naive(history, period, horizon):
    cycle = history[-period:]
    return [cycle[lead % period] for lead in range(horizon)]


class ReplayRequest(BaseModel):
    series_id: str
    first_cutoff: datetime
    context_length: int = Field(default=56, ge=32, le=2048)
    horizon: int = Field(default=7, ge=1, le=64)
    seasonal_period: int = Field(default=7, ge=1, le=2047)
    period_origins: int = Field(default=12, ge=12, le=32)


@router.post("/replays", status_code=201)
def replay(request: ReplayRequest):
    from .main import Series, get, save, validate_series, forecaster

    series = Series(**get(request.series_id, "series"))
    validate_series(series)
    if request.first_cutoff.tzinfo is None:
        raise HTTPException(422, "first_cutoff must include a timezone")
    index = next((i for i, r in enumerate(series.readings) if r.timestamp == request.first_cutoff), None)
    if index is None or index + 1 < request.context_length:
        raise HTTPException(422, "first_cutoff must match a reading with the requested context")
    if request.seasonal_period >= request.context_length:
        raise HTTPException(422, "seasonal_period must be smaller than context_length")
    required = index + 1 + 2 * request.period_origins * request.horizon
    if required > len(series.readings):
        raise HTTPException(422, f"Replay requires {required} readings for complete, nonoverlapping targets")
    values = [r.value for r in series.readings]
    initial = np.array(values[index + 1 - request.context_length:index + 1])
    season = request.seasonal_period
    scale = float(np.mean(np.abs(initial[season:] - initial[:-season])))
    origins = []
    for number in range(2 * request.period_origins):
        cutoff = index + number * request.horizon
        history = values[cutoff + 1 - request.context_length:cutoff + 1]
        try:
            quantiles, _ = forecaster.predict(history, request.horizon)
        except Exception as exc:
            logging.getLogger(__name__).exception("Replay inference failed")
            raise HTTPException(503, "Replay inference unavailable; no partial replay saved") from exc
        if len(quantiles) != request.horizon or any(len(q) != 3 or not all(math.isfinite(x) for x in q) or not q[0] <= q[1] <= q[2] for q in quantiles):
            raise HTTPException(503, "Invalid model quantiles; no partial replay saved")
        evidence = []
        for lead, (q, baseline) in enumerate(zip(quantiles, seasonal_naive(history, season, request.horizon))):
            reading = series.readings[cutoff + 1 + lead]
            evidence.append({"timestamp": reading.timestamp.isoformat(), "lead": lead + 1,
                             "actual": reading.value, "point": q[1], "q10": q[0], "q90": q[2],
                             "baseline_point": baseline, "absolute_error": abs(reading.value - q[1]),
                             "baseline_absolute_error": abs(reading.value - baseline),
                             "covered": q[0] <= reading.value <= q[2]})
        origins.append({"cutoff": series.readings[cutoff].timestamp.isoformat(),
                        "context_start": series.readings[cutoff + 1 - request.context_length].timestamp.isoformat(),
                        "period": "reference" if number < request.period_origins else "recent",
                        "mae": float(np.mean([r["absolute_error"] for r in evidence])), "evidence": evidence})
    return save("replay", {"schema_version": "2.0", "mode": "historical_replay",
                           "created_at": datetime.now(timezone.utc).isoformat(),
                           "request": request.model_dump(mode="json"), "model": MODEL_ID,
                           "revision": forecaster.revision, "unit": series.unit,
                           "baseline": "seasonal naive repeating the last observed seasonal cycle",
                           "assessment": assess(origins, request.period_origins, scale), "origins": origins,
                           "limitations": ["Retrospective replay, not a prospective production alarm.",
                                           "Equal lead mix and fixed context length control horizon and context-length confounding; seasonal regimes and weather remain possible explanations.",
                                           "Bootstrap uncertainty depends on block length and within-period stability; no repeated-testing correction.",
                                           "No causal attribution, model retraining, or guarantee of pretraining-data independence."]})


@router.get("/replays/{replay_id}")
def read_replay(replay_id: str):
    from .main import get
    return get(replay_id, "replay")
