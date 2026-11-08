import json
from contextlib import closing

from fastapi import APIRouter, Query

from .adaptive import KIND, PROCESS_ID

router = APIRouter()
SERIES_FILTER = "json_extract(body, '$.series_id')"
REQUEST_FILTER = "json_extract(body, '$.request.series_id')"


def list_records(kind, fields, limit, before, series_filter=None, series_id=None):
    from .main import connection

    conditions = ["kind = ?"]
    arguments = [kind]
    if before is not None:
        conditions.append("rowid < ?")
        arguments.append(before)
    if series_id is not None and series_filter is not None:
        conditions.append(f"{series_filter} = ?")
        arguments.append(series_id)
    where = " AND ".join(conditions)
    with closing(connection()) as db:
        rows = db.execute(f"SELECT rowid, id, {fields} FROM records WHERE {where} "
                          "ORDER BY rowid DESC LIMIT ?", (*arguments, limit + 1)).fetchall()
    items = [{"id": key, **json.loads(body)} for _, key, body in rows[:limit]]
    return {"items": items, "next_before": rows[limit - 1][0] if len(rows) > limit else None}


@router.get("/series")
def list_series(limit: int = Query(20, ge=1, le=100), before: int | None = Query(None, ge=1)):
    return list_records("series", """json_object(
        'name', json_extract(body, '$.name'), 'unit', json_extract(body, '$.unit'),
        'observations', json_array_length(body, '$.readings'),
        'first_timestamp', json_extract(body, '$.readings[0].timestamp'),
        'last_timestamp', json_extract(body, '$.readings[#-1].timestamp'),
        'provenance', json_extract(body, '$.provenance'))""", limit, before)


@router.get("/forecasts")
def list_forecasts(series_id: str | None = None, limit: int = Query(20, ge=1, le=100),
                   before: int | None = Query(None, ge=1)):
    return list_records("forecast", """json_object(
        'series_id', json_extract(body, '$.series_id'), 'unit', json_extract(body, '$.unit'),
        'model', json_extract(body, '$.model'), 'cutoff', json_extract(body, '$.cutoff'),
        'created_at', json_extract(body, '$.created_at'), 'horizon', json_array_length(body, '$.predictions'))""",
                        limit, before, SERIES_FILTER, series_id)


@router.get("/replays")
def list_replays(series_id: str | None = None, limit: int = Query(20, ge=1, le=100),
                 before: int | None = Query(None, ge=1)):
    return list_records("replay", """json_object(
        'series_id', json_extract(body, '$.request.series_id'), 'unit', json_extract(body, '$.unit'),
        'created_at', json_extract(body, '$.created_at'), 'model', json_extract(body, '$.model'),
        'status', json_extract(body, '$.assessment.status'))""", limit, before, REQUEST_FILTER, series_id)


@router.get("/adaptive-experiments")
def list_experiments(series_id: str | None = None, limit: int = Query(20, ge=1, le=100),
                     before: int | None = Query(None, ge=1)):
    page = list_records(KIND, """json_object(
        'series_id', json_extract(body, '$.request.series_id'), 'unit', json_extract(body, '$.unit'),
        'created_at', json_extract(body, '$.created_at'), 'state', json_extract(body, '$.state'),
        'worker', json_extract(body, '$.worker'), 'error', json_extract(body, '$.error'),
        'summary', json_extract(body, '$.summary'),
        'evolution_enabled', json_type(body, '$.request.evolution') = 'object',
        'progress', json_object(
            'total_origins', json_extract(body, '$.request.origins'),
            'scored_origins', json_array_length(body, '$.origins') -
                (json_array_length(body, '$.origins') > 0 AND
                 json_type(body, '$.origins[#-1].outcome') IS NULL)))""", limit, before, REQUEST_FILTER, series_id)
    for item in page["items"]:
        worker = item.pop("worker")
        if item["state"] in ("queued", "running") and worker != PROCESS_ID:
            item.update(state="interrupted", error="worker_restarted")
        item["evolution_enabled"] = bool(item["evolution_enabled"])
    return page
