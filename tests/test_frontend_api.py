import json
from datetime import datetime, timedelta, timezone
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from app import main
from app import demo
from scripts.seed_demo import seed_demo


def test_readonly_discovery_and_evaluation(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB', tmp_path/'demo.db')
    monkeypatch.setattr(demo, 'DEMO_DIR', tmp_path)
    readings=[{'timestamp':datetime(2014,1,1,tzinfo=timezone.utc)+timedelta(days=i),'value':10} for i in range(64)]
    series=main.create_series(main.Series(name='controlled API test',unit='GW (source units)',readings=readings))
    forecast=main.save('forecast',{'series_id':series['id'],'unit':series['unit'],'cutoff':readings[31]['timestamp'].isoformat(),
        'error_scale':1,'history_mean':10,'history_std':1,'predictions':[{'timestamp':r['timestamp'].isoformat(),'point':11,'q50':11,'q10':9,'q90':12} for r in readings[32:48]]})
    replay=main.save('replay',{'request':{'series_id':series['id']}})
    (tmp_path/'demo-result.json').write_text(json.dumps({'forecast':{'id':forecast['id']}}))
    (tmp_path/'phase2-replay-result.json').write_text(json.dumps({'id':replay['id']}))
    with main.connection() as db:
        before=db.execute('select count(*) from records').fetchone()[0]
    with TestClient(main.app) as client:
        response=client.get('/demo')
        assert response.status_code==200
        result=response.json()
        assert result['provenance']['observations']==64
        assert 'GROQ' not in response.text and 'API_KEY' not in response.text
        for part in ('history', 'actuals'):
            download=client.get('/demo/readings.csv',params={'part':part})
            assert download.status_code==200
            assert 'attachment' in download.headers['content-disposition']
            assert len(download.text.splitlines())==65
            assert download.text.splitlines()[0]=='timestamp,value'
        assert client.get('/demo/readings.csv?part=unknown').status_code==422
        evaluated=client.get(f'/forecasts/{forecast["id"]}/evaluation',params={'actual_series_id':series['id']})
        assert evaluated.status_code==200
        assert evaluated.json()==client.post(f'/forecasts/{forecast["id"]}/evaluate',json={'actual_series_id':series['id']}).json()
        assert evaluated.json()['metrics']['mae']==1
        assert client.get('/forecasts/missing/evaluation',params={'actual_series_id':series['id']}).status_code==404
        assert client.get('/.env').status_code==404
    with main.connection() as db:
        assert db.execute('select count(*) from records').fetchone()[0]==before


def test_missing_demo_fails_without_substitution(tmp_path, monkeypatch):
    monkeypatch.setattr(demo,'DEMO_DIR',tmp_path)
    with TestClient(main.app) as client:
        response=client.get('/demo')
        assert response.status_code==404
        assert 'unavailable' in response.json()['detail']


def test_portable_victoria_seed_preserves_real_comparison(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path / "fresh.db")
    assert seed_demo() == 7
    assert seed_demo() == 0
    with TestClient(main.app) as client:
        assert client.get("/health/ready").json() == {"status": "ready"}
        ids = client.get("/demo").json()
        result = client.get(f"/adaptive-experiments/{ids['experiment_id']}/comparison",
                            params={"against": ids["comparison_id"]}).json()
        assert result["lowest_observed_fixed_mae_models"] == ["seasonal_naive"]
        assert result["summary"]["scored_targets"] == 210
        assert result["against"]["mae_delta_this_minus_other"]["adaptive"] == pytest.approx(0.0470097927567)
        assert client.get("/.env").status_code == 404
        assert client.get("/victoria-demo.json.gz").status_code == 404
    with closing(main.connection()) as db, db:
        assert db.execute("SELECT DISTINCT kind FROM records WHERE kind = 'investigation'").fetchall() == []
        db.execute("UPDATE records SET body = '{}' WHERE id = ?", (ids["experiment_id"],))
    with pytest.raises(ValueError, match="conflicts"):
        seed_demo()
    assert main.get(ids["experiment_id"], "adaptive_experiment") == {}


def test_readiness_hides_unavailable_database_details(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path)
    with TestClient(main.app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}

