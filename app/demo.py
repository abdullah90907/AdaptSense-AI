"""Read-only discovery of the existing demonstration records."""
import hashlib
import json
from contextlib import closing
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()
DEMO_DIR = Path(__file__).resolve().parents[1] / 'data'


@router.get('/demo')
def demo_catalog():
    from .main import connection, get
    try:
        manifest = json.loads((DEMO_DIR / 'victoria-demo-manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        manifest = {}
    try:
        replay_id = json.loads((DEMO_DIR / 'phase2-replay-result.json').read_text())['id']
        forecast_id = json.loads((DEMO_DIR / 'demo-result.json').read_text())['forecast']['id']
        replay = get(replay_id, 'replay')
        get(forecast_id, 'forecast')
    except (OSError, ValueError, KeyError, HTTPException):
        try:
            replay_id, forecast_id = manifest['replay_id'], manifest['forecast_id']
            replay = get(replay_id, 'replay')
            get(forecast_id, 'forecast')
        except (KeyError, HTTPException):
            raise HTTPException(404, 'Saved demo evidence unavailable. Run python -m scripts.seed_demo.') from None
    series_id = replay['request']['series_id']
    series = get(series_id, 'series')
    csv_path = DEMO_DIR / 'elecdaily-source.csv'
    pair = (manifest.get('experiment_id'), manifest.get('comparison_id'))
    with closing(connection()) as db:
        found, = db.execute("SELECT count(*) FROM records WHERE kind='adaptive_experiment' AND id IN (?, ?)", pair).fetchone()
    featured = {'experiment_id': pair[0], 'comparison_id': pair[1]} if found == 2 else {}
    return {'series_id': series_id, 'forecast_id': forecast_id, 'replay_id': replay_id, **featured,
            'provenance': {'title': 'Victoria electricity demand', 'region': 'Victoria, Australia',
                'period': '2014', 'observations': len(series['readings']), 'unit': series['unit'],
                'dataset': 'fpp2::elecdaily', 'attribution': 'Australian Energy Market Operator & Australian Bureau of Meteorology',
                'documentation_url': 'https://vincentarelbundock.github.io/Rdatasets/doc/fpp2/elecdaily.html',
                'source_url': 'https://raw.githubusercontent.com/vincentarelbundock/Rdatasets/master/csv/fpp2/elecdaily.csv',
                'source_sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest() if csv_path.exists() else None,
                'time_convention': 'Daily dates indexed at 00:00 UTC; this is a regular indexing convention, not a claim of a UTC meter boundary.',
                'unit_note': 'Demand values and the GW label are preserved from source documentation; no energy conversion is applied.',
                'model_note': 'Saved frozen Chronos-Bolt Tiny inference; no new model run occurs when browsing.'}}

@router.get('/forecasts/{forecast_id}/evaluation')
def read_evaluation(forecast_id: str, actual_series_id: str):
    from .main import evaluate, EvaluationRequest
    return evaluate(forecast_id, EvaluationRequest(actual_series_id=actual_series_id))

@router.get('/demo/readings.csv')
def demo_readings_csv(part: str = 'history'):
    import csv
    import io
    from fastapi.responses import Response
    from .main import get
    if part not in ('history', 'actuals'):
        raise HTTPException(422, 'part must be history or actuals')
    catalog = demo_catalog()
    series = get(catalog['series_id'], 'series')
    readings = series['readings'][:300] if part == 'history' else series['readings']
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=['timestamp', 'value'])
    writer.writeheader()
    writer.writerows({'timestamp': r['timestamp'], 'value': r['value']} for r in readings)
    return Response(output.getvalue(), media_type='text/csv', headers={
        'Content-Disposition': f'attachment; filename="victoria-2014-{part}.csv"'})
