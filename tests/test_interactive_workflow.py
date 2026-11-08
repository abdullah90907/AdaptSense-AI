from datetime import datetime,timedelta,timezone

import pytest
from fastapi.testclient import TestClient
from app import main


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DB',tmp_path/'workflow.db')
    with TestClient(main.app) as client:
        yield client


def payload(n=40):
    return {'name':'Controlled workflow test','unit':'kWh','readings':[{'timestamp':(datetime(2024,1,1,tzinfo=timezone.utc)+timedelta(hours=i)).isoformat(),'value':10+i} for i in range(n)],
        'provenance':{'kind':'csv_upload','label':'controlled.csv','sha256':'a'*64,'note':'Controlled API fixture, not a measured model result.'}}


def test_provenance_and_partial_actuals_preserve_forecast(client,monkeypatch):
    seen=[]
    def predict(values,horizon):
        seen.append(list(values))
        return [[9,10,11]]*horizon,[10]*horizon
    monkeypatch.setattr(main.forecaster,'predict',predict)
    history=payload()
    source=client.post('/series',json=history).json()
    assert source['provenance']['verification']=='client_supplied'
    run=client.post('/forecasts',json={'series_id':source['id'],'cutoff':history['readings'][-1]['timestamp'],'horizon':4})
    assert run.status_code==201
    forecast=run.json()
    assert seen==[[r['value'] for r in history['readings']]]
    assert forecast['source_provenance']['sha256']=='a'*64
    actuals=client.post('/series',json=payload(41)).json()
    evaluated=client.post(f'/forecasts/{forecast["id"]}/evaluate',json={'actual_series_id':actuals['id']}).json()
    assert evaluated['matched']==1 and evaluated['pending']==3
    assert evaluated['metrics']['mae']==40
    assert evaluated['reliability']['status']=='insufficient_evidence'
    assert client.get(f'/forecasts/{forecast["id"]}').json()['predictions']==forecast['predictions']


def test_invalid_output_does_not_save_a_forecast(client,monkeypatch):
    source=client.post('/series',json=payload()).json()
    monkeypatch.setattr(main.forecaster,'predict',lambda v,h:([[12,10,9]]*h,[10]*h))
    result=client.post('/forecasts',json={'series_id':source['id'],'cutoff':payload()['readings'][-1]['timestamp'],'horizon':2})
    assert result.status_code==503
    with main.connection() as db:
        assert db.execute("select count(*) from records where kind='forecast'").fetchone()[0]==0


def test_provenance_cannot_claim_server_verification(client):
    source=payload()
    source['provenance']['verification']='verified'
    assert client.post('/series',json=source).status_code==422
    source=payload()
    source['provenance']['sha256']='invalid'
    assert client.post('/series',json=source).status_code==422
