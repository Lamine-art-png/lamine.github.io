from io import BytesIO

def test_workbench_session_upload_analyze_report(client):
    s = client.post('/v1/workbench/sessions', json={'mode':'uploaded'}).json()
    sid = s['session_id']
    up = client.post(f'/v1/workbench/sessions/{sid}/upload', files={'file': ('controller_events.csv', BytesIO(b'timestamp,duration\n2026-01-01T00:00:00,36\n'), 'text/csv')})
    assert up.status_code == 200
    an = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id':sid,'mode':'uploaded'})
    assert an.status_code == 200
    rp = client.get(f'/v1/workbench/sessions/{sid}/report')
    assert rp.status_code == 200

def test_reject_unsupported(client):
    s = client.post('/v1/workbench/sessions', json={'mode':'uploaded'}).json()
    sid = s['session_id']
    up = client.post(f'/v1/workbench/sessions/{sid}/upload', files={'file': ('bad.exe', BytesIO(b'123'), 'application/octet-stream')})
    assert up.status_code == 400

def test_analyze_live(client):
    r = client.post('/v1/workbench/analyze-live', json={'source':'wiseconn','entity_id':'162803'})
    assert r.status_code == 200

def test_sample_package_route(client):
    created = client.post('/v1/workbench/sample-package')
    assert created.status_code == 200
    payload = created.json()
    sid = payload['session']['session_id']
    assert len(payload['artifacts']) == 8

    analyzed = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id': sid, 'mode': 'uploaded'})
    assert analyzed.status_code == 200
    result = analyzed.json()
    assert result['data_sources']['rows_parsed'] >= 70
    assert result['signal_summary']['flow_meter_records_read'] >= 10
    assert result['analysis_trace'][0]['title'] == 'Ingested source files'

def test_schema_exposes_rich_workbench_fields(client):
    r = client.get('/v1/workbench/schema')
    assert r.status_code == 200
    body = r.json()
    assert 'controller_events.csv' in body['expected_fields']
    assert 'analysis_trace' in body['output_schema']
