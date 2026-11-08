import logging
import math
from datetime import datetime, timezone
from statistics import mean
from threading import BoundedSemaphore
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response
from pydantic import BaseModel, Field

from .evolution import EvolutionConfig, evolve, minimum_history
from .model import MODEL_ID, MODEL_REVISION
from .replay import seasonal_naive

router = APIRouter()
KIND = "adaptive_experiment"
MODELS = ("chronos", "seasonal_naive")
RUN_SLOT = BoundedSemaphore(1)
PROCESS_ID = uuid4().hex


class AdaptiveRequest(BaseModel):
    series_id: str
    first_cutoff: datetime
    context_length: int = Field(default=56, ge=32, le=2048)
    horizon: int = Field(default=7, ge=1, le=64)
    seasonal_period: int = Field(default=7, ge=1, le=2047)
    origins: int = Field(default=40, ge=5, le=64)
    lookback_origins: int = Field(default=6, ge=3, le=32)
    minimum_relative_gain: float = Field(default=0.05, ge=0, lt=1)
    evolution: EvolutionConfig | None = None


def decision(current, completed, request, models=MODELS):
    window = completed[-request.lookback_origins:]
    result = {"previous_model": current, "selected_model": current,
              "reason": "warming_up", "evidence_cutoffs": [origin["cutoff"] for origin in window]}
    if len(window) < request.lookback_origins:
        return result
    recent_mae = {model: mean(o["outcome"]["mae"][model] for o in window) for model in models}
    candidates = []
    for model in sorted((m for m in models if m != current), key=recent_mae.get):
        wins = sum(o["outcome"]["mae"][model] < o["outcome"]["mae"][current] for o in window)
        gain = (1 - recent_mae[model] / recent_mae[current]) if recent_mae[current] > 0 else None
        qualifies = gain is not None and gain > 0 and gain >= request.minimum_relative_gain and 2 * wins > len(window)
        candidates.append((model, wins, gain, qualifies))
    challenger, wins, gain, switch = next((row for row in candidates if row[3]), candidates[0])
    if len(models) > 2:
        result["challenger_model"] = challenger
    return {**result, "selected_model": challenger if switch else current,
            "reason": "switch" if switch else "retain", "recent_mae": recent_mae,
            "challenger_relative_gain": gain, "challenger_block_wins": wins}


def summarize(origins, models=MODELS):
    errors = {model: [] for model in (*models, "adaptive")}
    gains = []
    selection_counts = dict.fromkeys(models, 0)
    for origin in origins:
        choice = origin["decision"]
        selected = choice["selected_model"]
        selection_counts[selected] += 1
        for prediction, actual in zip(origin["predictions"], origin["outcome"]["actuals"], strict=True):
            for model in errors:
                point = prediction[selected if model == "adaptive" else model]
                errors[model].append(abs(actual - point))
        if choice["reason"] == "switch":
            gains.append(origin["outcome"]["gain_vs_retaining"])
    metrics = {model: {"mae": mean(values), "rmse": math.hypot(*(e / math.sqrt(len(values)) for e in values))}
               for model, values in errors.items()}
    return {"scored_origins": len(origins), "scored_targets": len(errors["adaptive"]),
            "metrics": metrics, "selected_origins": selection_counts,
            "adaptive_mae_gain_vs_fixed": {model: metrics[model]["mae"] - metrics["adaptive"]["mae"]
                                          for model in models},
            "switch_outcomes": {"count": len(gains), "improved": sum(g > 0 for g in gains),
                                "worsened": sum(g < 0 for g in gains), "tied": sum(g == 0 for g in gains),
                                "mean_mae_gain_vs_retaining": mean(gains) if gains else None}}


def prepare(request):
    from .main import Series, get, validate_series

    series = Series(**get(request.series_id, "series"))
    step = validate_series(series)
    if request.first_cutoff.tzinfo is None:
        raise HTTPException(422, "first_cutoff must include a timezone")
    index = next((i for i, r in enumerate(series.readings) if r.timestamp == request.first_cutoff), None)
    if index is None or index + 1 < request.context_length:
        raise HTTPException(422, "first_cutoff must match a reading with the requested context")
    if request.seasonal_period >= request.context_length or request.lookback_origins >= request.origins:
        raise HTTPException(422, "seasonal_period must be smaller than context_length and lookback_origins smaller than origins")
    required = index + 1 + request.origins * request.horizon
    if required > len(series.readings):
        raise HTTPException(422, f"Experiment requires {required} readings for complete, nonoverlapping targets")
    if any(r.value > 3.4e38 for r in series.readings[:required]):
        raise HTTPException(422, "Readings exceed the supported Chronos float32 input range")
    if request.evolution:
        minimum = minimum_history(request.context_length, request.horizon, request.evolution.validation_origins)
        if index + 1 < minimum:
            raise HTTPException(422, f"Evolution requires at least {minimum} readings through the first cutoff")

    available = [reading.value for reading in series.readings[:index + 1]]
    origins = []
    record = {"schema_version": "1.0", "mode": "sequential_historical_simulation", "state": "running",
              "created_at": datetime.now(timezone.utc).isoformat(), "request": request.model_dump(mode="json", exclude_none=True),
              "unit": series.unit, "models": {"chronos": {"id": MODEL_ID, "revision": MODEL_REVISION},
                                              "seasonal_naive": {"period": request.seasonal_period}},
              "policy": "Start with Chronos. Switch when the challenger has a positive relative MAE gain "
                        "at least as large as the configured minimum and wins a strict majority of recent scored blocks.",
              "origins": origins}
    return series, step, index, available, record


def execute(request, prepared, key):
    from .main import forecaster, update

    series, step, index, available, record = prepared
    origins = record["origins"]
    evolved = None
    models = MODELS
    if request.evolution is not None:
        try:
            evolved, evidence = evolve(available, request.context_length, request.horizon, request.seasonal_period,
                                       request.evolution)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        models = (*MODELS, "evolved_rnn")
        record["schema_version"] = "1.1"
        record["models"]["evolved_rnn"] = {"id": "adaptsense-reservoir-rnn-v1", **evidence,
                                          "validation_start": series.readings[evidence["validation_start_index"]].timestamp.isoformat(),
                                          "frozen_at_cutoff": series.readings[index].timestamp.isoformat()}
        record["policy"] += " Among qualifying challengers, prefer the lowest recent MAE."
    current = "chronos"
    for number in range(request.origins):
        cutoff = index + number * request.horizon
        cutoff_time = series.readings[cutoff].timestamp
        history = available[-request.context_length:]
        choice = decision(current, origins, request, models)
        try:
            quantiles, _ = forecaster.predict(history, request.horizon)
            if len(quantiles) != request.horizon or any(
                len(q) != 3 or not all(math.isfinite(x) for x in q) or not q[0] <= q[1] <= q[2] for q in quantiles
            ):
                raise ValueError("Invalid model quantiles")
            if evolved is not None:
                evolved_points = evolved.predict(history, request.horizon)
                if len(evolved_points) != request.horizon or not all(map(math.isfinite, evolved_points)):
                    raise ValueError("Invalid evolved predictions")
        except Exception as exc:
            logging.getLogger(__name__).exception("Adaptive experiment inference failed")
            record.update(state="failed", failed_origin=number + 1, error="inference_unavailable")
            update(key, KIND, record)
            raise HTTPException(503, {"experiment_id": key, "error": record["error"]}) from exc

        baseline = seasonal_naive(history, request.seasonal_period, request.horizon)
        predictions = [{"lead": lead, "timestamp": (cutoff_time + step * lead).isoformat(),
                        "chronos": q[1], "q10": q[0], "q90": q[2], "seasonal_naive": naive}
                       for lead, (q, naive) in enumerate(zip(quantiles, baseline), start=1)]
        if evolved is not None:
            for prediction, point in zip(predictions, evolved_points, strict=True):
                prediction["evolved_rnn"] = point
        origin = {"cutoff": cutoff_time.isoformat(), "decision": choice, "predictions": predictions}
        origins.append(origin)
        update(key, KIND, record)

        actuals = [reading.value for reading in series.readings[cutoff + 1:cutoff + 1 + request.horizon]]
        scores = {model: mean(abs(p[model] - actual) for p, actual in zip(predictions, actuals, strict=True))
                  for model in models}
        current = choice["selected_model"]
        origin["outcome"] = {"actuals": actuals, "mae": scores,
                             "gain_vs_retaining": scores[choice["previous_model"]] - scores[current]}
        update(key, KIND, record)
        available.extend(actuals)

    record.update(state="completed", summary=summarize(origins[request.lookback_origins:], models))
    update(key, KIND, record)
    return {"id": key, **record}


def run_saved(request, prepared, key, background):
    from .main import update

    record = prepared[-1]
    try:
        if background:
            record["state"] = "running"
            update(key, KIND, record)
        return execute(request, prepared, key)
    except Exception as exc:
        if record["state"] != "failed":
            logging.getLogger(__name__).exception("Adaptive experiment stopped")
            record.update(state="failed", error="experiment_failed")
            update(key, KIND, record)
        if not background:
            if isinstance(exc, HTTPException) and exc.status_code == 503:
                raise
            raise HTTPException(503, {"experiment_id": key, "error": record["error"]}) from exc
    finally:
        RUN_SLOT.release()


@router.post("/adaptive-experiments", status_code=201, responses={202: {"description": "Experiment accepted for processing"}})
def run_adaptive_experiment(request: AdaptiveRequest, tasks: BackgroundTasks, response: Response,
                            background: bool = False):
    from .main import save

    prepared = prepare(request)
    record = prepared[-1]
    if not RUN_SLOT.acquire(blocking=False):
        raise HTTPException(409, "An adaptive experiment is already running", headers={"Retry-After": "5"})
    try:
        record["worker"] = PROCESS_ID
        if background:
            record["state"] = "queued"
        key = save(KIND, record)["id"]
    except Exception:
        RUN_SLOT.release()
        raise
    response.headers["Location"] = f"/adaptive-experiments/{key}"
    if background:
        response.status_code = 202
        tasks.add_task(run_saved, request, prepared, key, True)
        return {"id": key, "state": "queued", "status_url": f"/adaptive-experiments/{key}/status"}
    result = run_saved(request, prepared, key, False)
    result.pop("worker")
    return result


@router.get("/adaptive-experiments/{experiment_id}")
def read_adaptive_experiment(experiment_id: str):
    from .main import get
    record = get(experiment_id, KIND)
    worker = record.pop("worker", None)
    if record["state"] in ("queued", "running") and worker != PROCESS_ID:
        record.update(state="interrupted", error="worker_restarted")
    return {"id": experiment_id, **record}


@router.get("/adaptive-experiments/{experiment_id}/status")
def experiment_status(experiment_id: str):
    return status_summary(read_adaptive_experiment(experiment_id))


def status_summary(record):
    origins = record["origins"]
    request = record["request"]
    return {"id": record["id"], "state": record["state"], "series_id": request["series_id"],
            "created_at": record["created_at"],
            "progress": {"scored_origins": len(origins) - bool(origins and "outcome" not in origins[-1]),
                         "total_origins": request["origins"]},
            "evolution_enabled": bool(request.get("evolution") is not None),
            "error": record.get("error"), "summary": record.get("summary")}


@router.get("/adaptive-experiments/{experiment_id}/comparison")
def compare_experiment(experiment_id: str, against: str | None = None):
    record = read_adaptive_experiment(experiment_id)
    if record["state"] != "completed":
        raise HTTPException(409, "Comparison requires a completed experiment")
    request = AdaptiveRequest(**record["request"])
    origins = record["origins"]
    models = tuple(record["models"])
    evaluated = origins[request.lookback_origins:]
    metrics = record["summary"]["metrics"]
    best = min(models, key=lambda model: metrics[model]["mae"])
    tied = [model for model in models if metrics[model]["mae"] == metrics[best]["mae"]]
    result = {"id": experiment_id, "unit": record["unit"], "summary": record["summary"],
              "evaluation": {"first_target": evaluated[0]["predictions"][0]["timestamp"],
                             "last_target": evaluated[-1]["predictions"][-1]["timestamp"]},
              "lowest_observed_fixed_mae_models": tied,
              "mae_above_best_fixed": {model: row["mae"] - metrics[best]["mae"] for model, row in metrics.items()},
              "decision_settings": {"lookback_origins": request.lookback_origins,
                                    "minimum_relative_gain": request.minimum_relative_gain},
              "next_origin_recommendation": decision(origins[-1]["decision"]["selected_model"], origins, request, models),
              "interpretation": "Observed errors describe this historical window. The next-origin recommendation uses the recent scored blocks and has no measured outcome."}
    if "evolved_rnn" in models:
        evolved = record["models"]["evolved_rnn"]
        result["evolution_evidence"] = {
            "validation_mae": evolved["validation_mae"],
            "validation_seasonal_naive_mae": evolved["validation_seasonal_naive_mae"],
            "evaluation_mae": metrics["evolved_rnn"]["mae"],
            "evaluation_seasonal_naive_mae": metrics["seasonal_naive"]["mae"],
        }
    if against is not None:
        other = read_adaptive_experiment(against)
        if other["state"] != "completed":
            raise HTTPException(409, "Comparison requires completed experiments")
        other_request = AdaptiveRequest(**other["request"])
        other_evaluated = other["origins"][other_request.lookback_origins:]
        targets = [p["timestamp"] for origin in evaluated for p in origin["predictions"]]
        other_targets = [p["timestamp"] for origin in other_evaluated for p in origin["predictions"]]
        if (request.series_id != other_request.series_id or request.horizon != other_request.horizon
                or targets != other_targets):
            raise HTTPException(422, "Experiments must share the same dataset, horizon and evaluated target timestamps")
        other_metrics = other["summary"]["metrics"]
        result["against"] = {"id": against, "summary": other["summary"],
                             "mae_delta_this_minus_other": {model: metrics[model]["mae"] - other_metrics[model]["mae"]
                                                           for model in metrics if model in other_metrics}}
    return result
