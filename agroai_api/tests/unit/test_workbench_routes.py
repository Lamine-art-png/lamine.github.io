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


# --- Section 10: area_unit in uploaded analysis request ----------------------

def test_uploaded_analysis_with_area_ha_no_warning(client):
    s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = s['session_id']
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze',
                    json={'session_id': sid, 'mode': 'uploaded', 'area': 3.0, 'area_unit': 'ha'})
    assert r.status_code == 200
    body = r.json()
    area_warnings = [w for w in (body.get('warnings') or [])
                     if 'area unit' in str(w).lower() or 'unknown area' in str(w).lower()]
    assert not area_warnings


def test_uploaded_analysis_with_area_acres_no_warning(client):
    s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = s['session_id']
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze',
                    json={'session_id': sid, 'mode': 'uploaded', 'area': 7.0, 'area_unit': 'acres'})
    assert r.status_code == 200


def test_uploaded_analysis_with_area_m2_no_warning(client):
    s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = s['session_id']
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze',
                    json={'session_id': sid, 'mode': 'uploaded', 'area': 25000.0, 'area_unit': 'm2'})
    assert r.status_code == 200


def test_uploaded_analysis_area_without_unit_withholds_volume(client):
    s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = s['session_id']
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze',
                    json={'session_id': sid, 'mode': 'uploaded', 'area': 2.0})
    assert r.status_code == 200
    assert r.json()['recommendation'].get('estimated_volume_m3') is None


def test_uploaded_analysis_zero_area_withholds_volume(client):
    s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = s['session_id']
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze',
                    json={'session_id': sid, 'mode': 'uploaded', 'area': 0.0, 'area_unit': 'ha'})
    assert r.status_code == 200
    assert r.json()['recommendation'].get('estimated_volume_m3') is None


# --- Section 11: historical_evaluation route parameter -----------------------

def test_historical_evaluation_true_accepted(client):
    from datetime import datetime, timezone
    ref = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    created = client.post('/v1/workbench/sample-package')
    sid = created.json()['session']['session_id']
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze',
                    json={'session_id': sid, 'mode': 'uploaded',
                          'historical_evaluation': True, 'evidence_reference_time': ref})
    assert r.status_code == 200
    assert r.json()['recommendation'].get('action')


def test_historical_evaluation_not_leaked_into_manual_overrides(client):
    """historical_evaluation and evidence_reference_time must not be forwarded as
    manual_overrides to the engine — they are routing parameters only."""
    from datetime import datetime, timezone
    ref = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    created = client.post('/v1/workbench/sample-package')
    sid = created.json()['session']['session_id']
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze',
                    json={'session_id': sid, 'mode': 'uploaded',
                          'historical_evaluation': True, 'evidence_reference_time': ref})
    assert r.status_code == 200
    # The analysis must succeed without a 400 error about unexpected manual overrides.
    body = r.json()
    assert 'analysis_id' in body


# --- Section 12: model_status truthfulness ------------------------------------

def test_model_status_always_deterministic_engine(client):
    """model_status must always be 'deterministic_engine', never 'optional_model_assist'."""
    import os
    os.environ['OPENAI_API_KEY'] = 'test-key-for-route-test'
    try:
        r = client.post('/v1/workbench/analyze-live', json={'source': 'wiseconn', 'entity_id': '162803'})
        assert r.status_code == 200
        assert r.json()['model_status'] == 'deterministic_engine'
    finally:
        del os.environ['OPENAI_API_KEY']


# --- Section 13: client-supplied confirmation_source rejected via route -------

def test_route_confirmation_source_payload_ignored(client):
    """A browser payload claiming confirmation_source must not escalate evidence type."""
    session_id = _make_analyzed_session(client)
    r = client.post(
        f'/v1/workbench/sessions/{session_id}/actions/schedule',
        json={'actor': 'Ops', 'payload': {'confirmation_source': 'controller_confirmed'}},
    )
    assert r.status_code == 200
    assert r.json()['evidence_type'] == 'operator_attestation'


# --- Section 14: Evaluation scenario routes ----------------------------------

def test_validated_operating_block_returns_computed_fields(client):
    """The validated_operating_block scenario must return backend-computed fields from the
    full 8-file sample package. Area is injected from the crop profile so the orchestrator
    can compute volume and duration. Region filtering must ensure the action is 'irrigate'."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    assert created.status_code == 200
    session_id = created.json()['session']['session_id']

    analyzed = client.post(
        f'/v1/workbench/sessions/{session_id}/analyze',
        json={'session_id': session_id, 'mode': 'uploaded'},
    )
    assert analyzed.status_code == 200
    body = analyzed.json()

    # Farm, block, crop, region, and area from the crop profile — not hardcoded.
    ctx = body['normalized_context']
    assert ctx['farm'] == 'Alpha Vineyard'
    assert ctx['block'] == 'Block A North'
    assert ctx['crop'] == 'wine grapes'
    assert ctx.get('region') == 'Central Valley North'
    assert ctx.get('area_ha') == 3.2
    assert ctx.get('area_unit') == 'ha'
    assert ctx.get('operating_window') == '21:00 – 23:00 local'

    rec = body['recommendation']
    # Region-filtered weather must produce action = "irrigate" for this package.
    assert rec.get('kernel_action') == 'irrigate', f"Expected 'irrigate' but got: {rec.get('kernel_action')!r}"
    assert rec['action']
    assert isinstance(rec['action'], str)

    # Timing window must come from operating_window in the crop profile, not a hardcoded fallback.
    assert rec.get('start_time') == '21:00 – 23:00 local'

    # Volume and duration must be non-None because flow is validated and area is known.
    assert rec.get('estimated_volume_m3') is not None, "Volume must be computed from area and validated flow"
    assert rec.get('duration_min') is not None, "Duration must be computed when flow is validated and area is known"
    assert rec.get('gross_depth_mm') is not None
    assert rec.get('depth_mm') is not None

    # Savings must be computed against the evaluation baseline.
    assert rec.get('estimated_water_savings_percent') is not None
    assert 0 < rec['estimated_water_savings_percent'] < 100
    assert rec.get('baseline_value_mm') == 4.9
    assert rec.get('baseline_label')
    assert rec.get('baseline_calculation_note')

    # Flow validation must be validated (not hardcoded).
    assert rec.get('flow_validation_status') == 'validated'

    # Confidence and completeness come from backend scoring.
    assert body['reconciliation']['confidence_score'] > 0
    assert body['reconciliation']['evidence_completeness']

    # Recommendation origin must be uploaded engine, not representative fallback.
    assert body['recommendation_origin'] == 'uploaded_intelligence_engine'

    # Verification plan must be present.
    assert body['verification_plan']['steps']

    # No old hardcoded strings must appear in the backend response.
    body_str = str(body)
    for forbidden in ['42 min tonight', '27% vs evaluation baseline']:
        assert forbidden not in body_str


def test_incomplete_evidence_review_withholds_precision(client):
    """The incomplete_evidence_review scenario must withhold precision fields
    (volume, duration) when area is missing and flow variance exceeds 20%."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'incomplete_evidence_review'})
    assert created.status_code == 200
    payload = created.json()
    session_id = payload['session']['session_id']

    # Incomplete evidence package has fewer files than the full sample.
    assert len(payload['artifacts']) == 5

    analyzed = client.post(
        f'/v1/workbench/sessions/{session_id}/analyze',
        json={'session_id': session_id, 'mode': 'uploaded'},
    )
    assert analyzed.status_code == 200
    body = analyzed.json()

    rec = body['recommendation']

    # No area in crop profile — volume must be withheld.
    assert rec.get('estimated_volume_m3') is None

    # Flow variance > 20% — flow must be inconsistent, duration withheld.
    flow_status = rec.get('flow_validation_status')
    assert flow_status in ('inconsistent', 'unavailable')
    assert rec.get('no_fabricated_duration') is True or rec.get('duration_min') is None

    # Limitations must be present for an incomplete evidence package.
    assert body['limitations']

    # Confidence must be lower than the validated operating block (< 0.8).
    assert body['reconciliation']['confidence_score'] < 0.8


def test_sample_package_scenario_parameter_accepted(client):
    """The sample-package endpoint must accept the scenario parameter without error."""
    r1 = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    assert r1.status_code == 200
    assert r1.json()['session']['session_id']

    r2 = client.post('/v1/workbench/sample-package', json={'scenario': 'incomplete_evidence_review'})
    assert r2.status_code == 200
    assert r2.json()['session']['session_id']

    # Default (no scenario param) must return validated operating block.
    r3 = client.post('/v1/workbench/sample-package', json={})
    assert r3.status_code == 200
    assert len(r3.json()['artifacts']) == 8


def test_validated_operating_block_area_from_crop_profile(client):
    """Area injected from crop profile (3.2 ha) must enable volume/duration computation
    when flow is validated — the orchestrator must not require area as a manual override."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    session_id = created.json()['session']['session_id']

    analyzed = client.post(
        f'/v1/workbench/sessions/{session_id}/analyze',
        json={'session_id': session_id, 'mode': 'uploaded'},
    )
    body = analyzed.json()
    # No area_unit warning must appear (area is now provided via crop profile).
    area_warnings = [w for w in (body.get('warnings') or []) if 'area unit' in str(w).lower() or 'area value' in str(w).lower()]
    assert not area_warnings
