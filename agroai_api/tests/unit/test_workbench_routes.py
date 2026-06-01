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


def test_analyze_live_returns_truthful_status_fields(client):
    r = client.post('/v1/workbench/analyze-live', json={'source': 'wiseconn', 'entity_id': '162803'})
    assert r.status_code == 200
    body = r.json()
    # Truthful status fields are present and consistent with a live request.
    assert body['analysis_mode'] == 'live'
    assert body['context_origin'] == 'live'
    assert body['recommendation_origin'] == 'live_intelligence_engine'
    assert 'live_inputs_used' in body
    assert 'warnings' in body
    # No provider credentials in the test env => assembler degrades, not fabricates.
    assert body['uploaded_artifacts_used'] == []


def test_uploaded_analysis_status_fields(client):
    created = client.post('/v1/workbench/sample-package')
    session_id = created.json()['session']['session_id']
    analyzed = client.post(
        f'/v1/workbench/sessions/{session_id}/analyze',
        json={'session_id': session_id, 'mode': 'uploaded'},
    )
    assert analyzed.status_code == 200
    body = analyzed.json()
    assert body['analysis_mode'] == 'uploaded'
    assert body['context_origin'] == 'uploaded'
    assert body['recommendation_origin'] == 'uploaded_intelligence_engine'
    assert len(body['uploaded_artifacts_used']) == 8

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
    assert result['analysis_trace'][0]['title'] == 'Source records ingested'

def test_schema_exposes_rich_workbench_fields(client):
    r = client.get('/v1/workbench/schema')
    assert r.status_code == 200
    body = r.json()
    assert 'controller_events.csv' in body['expected_fields']
    assert 'analysis_trace' in body['output_schema']


def test_evidence_chain_action_persistence(client):
    created = client.post('/v1/workbench/sample-package')
    session_id = created.json()['session']['session_id']
    analyzed = client.post(
        f'/v1/workbench/sessions/{session_id}/analyze',
        json={'session_id': session_id, 'mode': 'uploaded'},
    )
    assert analyzed.status_code == 200
    scheduled = client.post(
        f'/v1/workbench/sessions/{session_id}/actions/schedule',
        json={'actor': 'Operations user', 'evidence_summary': 'Approved test schedule.'},
    )
    assert scheduled.status_code == 200
    chain = client.get(f'/v1/workbench/sessions/{session_id}/evidence-chain')
    assert chain.status_code == 200
    body = chain.json()
    assert body['evidence_chain'][0]['status'] == 'Complete'
    assert body['evidence_chain'][1]['status'] == 'Complete'


# --- Section 3: Explicit live targets required --------------------------------

def test_analyze_live_missing_source_returns_422(client):
    r = client.post('/v1/workbench/analyze-live', json={'entity_id': '162803'})
    assert r.status_code == 422


def test_analyze_live_missing_entity_id_returns_422(client):
    r = client.post('/v1/workbench/analyze-live', json={'source': 'wiseconn'})
    assert r.status_code == 422


def test_analyze_live_empty_source_returns_422(client):
    r = client.post('/v1/workbench/analyze-live', json={'source': '', 'entity_id': '162803'})
    assert r.status_code == 422


def test_analyze_live_empty_entity_id_returns_422(client):
    r = client.post('/v1/workbench/analyze-live', json={'source': 'wiseconn', 'entity_id': ''})
    assert r.status_code == 422


def test_analyze_live_explicit_wiseconn_succeeds(client):
    r = client.post('/v1/workbench/analyze-live', json={'source': 'wiseconn', 'entity_id': '162803'})
    assert r.status_code == 200
    assert r.json()['analysis_mode'] == 'live'


def test_analyze_live_explicit_talgil_succeeds_or_degrades(client):
    r = client.post('/v1/workbench/analyze-live', json={'source': 'talgil', 'entity_id': 'trial-11'})
    assert r.status_code == 200
    body = r.json()
    assert body['analysis_mode'] == 'live'
    assert body['recommendation_origin'] == 'live_intelligence_engine'


# --- Section 9: Evidence chain ordering --------------------------------------

def _make_analyzed_session(client):
    created = client.post('/v1/workbench/sample-package')
    session_id = created.json()['session']['session_id']
    client.post(f'/v1/workbench/sessions/{session_id}/analyze', json={'session_id': session_id, 'mode': 'uploaded'})
    return session_id


def test_cannot_apply_before_schedule_returns_409(client):
    session_id = _make_analyzed_session(client)
    r = client.post(f'/v1/workbench/sessions/{session_id}/actions/applied', json={'actor': 'Ops'})
    assert r.status_code == 409
    assert 'scheduled' in r.json()['detail'].lower()


def test_cannot_observe_before_applied_returns_409(client):
    session_id = _make_analyzed_session(client)
    client.post(f'/v1/workbench/sessions/{session_id}/actions/schedule', json={'actor': 'Ops'})
    r = client.post(f'/v1/workbench/sessions/{session_id}/actions/observe', json={'actor': 'Ops'})
    assert r.status_code == 409


def test_cannot_verify_before_observed_returns_409(client):
    session_id = _make_analyzed_session(client)
    client.post(f'/v1/workbench/sessions/{session_id}/actions/schedule', json={'actor': 'Ops'})
    client.post(f'/v1/workbench/sessions/{session_id}/actions/applied', json={'actor': 'Ops'})
    r = client.post(f'/v1/workbench/sessions/{session_id}/actions/verify', json={'actor': 'Ops'})
    assert r.status_code == 409


def test_valid_evidence_sequence_succeeds(client):
    session_id = _make_analyzed_session(client)
    assert client.post(f'/v1/workbench/sessions/{session_id}/actions/schedule', json={'actor': 'Ops'}).status_code == 200
    assert client.post(f'/v1/workbench/sessions/{session_id}/actions/applied', json={'actor': 'Ops'}).status_code == 200
    assert client.post(f'/v1/workbench/sessions/{session_id}/actions/observe', json={'actor': 'Ops'}).status_code == 200
    assert client.post(f'/v1/workbench/sessions/{session_id}/actions/verify', json={'actor': 'Ops'}).status_code == 200


def test_override_without_reason_fails(client):
    session_id = _make_analyzed_session(client)
    r = client.post(f'/v1/workbench/sessions/{session_id}/actions/applied', json={'actor': 'Ops'})
    assert r.status_code == 409


def test_override_with_reason_succeeds_and_is_audit_logged(client):
    session_id = _make_analyzed_session(client)
    r = client.post(
        f'/v1/workbench/sessions/{session_id}/actions/applied',
        json={'actor': 'Ops', 'override_reason': 'Emergency irrigation event, schedule step skipped on-site.'},
    )
    assert r.status_code == 200
    audit = r.json()['audit_event']
    assert audit['evidence_type'] == 'operator_attestation'
    chain_r = client.get(f'/v1/workbench/sessions/{session_id}/evidence-chain')
    audit_events = chain_r.json()['audit_events']
    override_event = next((e for e in audit_events if 'override' in str(e.get('event', '')).lower()), None)
    assert override_event is not None


def test_evidence_action_records_operator_attestation_type(client):
    session_id = _make_analyzed_session(client)
    r = client.post(
        f'/v1/workbench/sessions/{session_id}/actions/schedule',
        json={'actor': 'Ops', 'evidence_summary': 'Schedule approved.'},
    )
    assert r.status_code == 200
    body = r.json()
    assert body['evidence_type'] == 'operator_attestation'
    chain = client.get(f'/v1/workbench/sessions/{session_id}/evidence-chain').json()
    scheduled_step = next(s for s in chain['evidence_chain'] if s['key'] == 'scheduled')
    assert scheduled_step['evidence_type'] == 'operator_attestation'
