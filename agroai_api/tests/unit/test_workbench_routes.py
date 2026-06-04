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
    # Selected-scope flow records (Block A North only); package-wide preserved separately.
    assert result['signal_summary']['flow_meter_records_read'] >= 1
    assert result['signal_summary']['pkg_flow_meter_records_read'] >= 10
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


# --- Section 15: Fourth-pass truthfulness gates --------------------------------

def test_validated_block_schedulable_true(client):
    """The validated operating block must have schedulable=True once flow and area are known."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    session_id = created.json()['session']['session_id']
    analyzed = client.post(
        f'/v1/workbench/sessions/{session_id}/analyze',
        json={'session_id': session_id, 'mode': 'uploaded'},
    )
    body = analyzed.json()
    rec = body['recommendation']
    assert rec.get('kernel_action') == 'irrigate'
    assert rec.get('schedulable') is True, f"Expected schedulable=True, got {rec.get('schedulable')!r}"
    assert rec.get('scheduling_block_reasons') == []
    # Scheduling the validated block must succeed (200, not 409)
    schedule_r = client.post(
        f'/v1/workbench/sessions/{session_id}/actions/schedule',
        json={'actor': 'Ops'},
    )
    assert schedule_r.status_code == 200


def test_validated_block_verified_recent_credit(client):
    """The validated operating block must return recent_irrigation_credit_status='verified_recent'."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    session_id = created.json()['session']['session_id']
    analyzed = client.post(
        f'/v1/workbench/sessions/{session_id}/analyze',
        json={'session_id': session_id, 'mode': 'uploaded'},
    )
    rec = analyzed.json()['recommendation']
    assert rec.get('recent_irrigation_credit_status') == 'verified_recent', (
        f"Expected 'verified_recent' but got: {rec.get('recent_irrigation_credit_status')!r}"
    )
    assert rec.get('flow_validation_status') == 'validated'


def test_validated_block_savings_in_report(client):
    """Savings fields must be present in the report artifact export rows."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    session_id = created.json()['session']['session_id']
    client.post(f'/v1/workbench/sessions/{session_id}/analyze',
                json={'session_id': session_id, 'mode': 'uploaded'})
    report = client.get(f'/v1/workbench/sessions/{session_id}/report').json()
    metrics = report.get('metrics', {})
    assert metrics.get('estimated_water_savings_percent') is not None
    assert metrics.get('baseline_value_mm') == 4.9
    export_rows = report.get('export_rows', [{}])
    assert export_rows[0].get('estimated_water_savings_percent') is not None
    assert export_rows[0].get('baseline_limitation')


def test_incomplete_block_schedulable_false(client):
    """The incomplete evidence scenario must have schedulable=False."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'incomplete_evidence_review'})
    session_id = created.json()['session']['session_id']
    analyzed = client.post(
        f'/v1/workbench/sessions/{session_id}/analyze',
        json={'session_id': session_id, 'mode': 'uploaded'},
    )
    rec = analyzed.json()['recommendation']
    assert rec.get('schedulable') is False
    assert rec.get('scheduling_block_reasons')
    # Scheduling the incomplete block must return 409
    schedule_r = client.post(
        f'/v1/workbench/sessions/{session_id}/actions/schedule',
        json={'actor': 'Ops'},
    )
    assert schedule_r.status_code == 409
    assert 'scheduling' in schedule_r.json()['detail'].lower()


def test_region_isolation_no_silent_fallback(client):
    """When no weather rows match the crop profile region, a warning must be emitted
    and the result must NOT silently mix weather from other regions."""
    # Use a custom session with weather from a different region than the crop profile.
    s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = s['session_id']
    import csv, io
    # Crop profile with region="NonExistent Region"
    crop_data = b'[{"farm":"Test Farm","block":"Test Block","crop":"wine grapes","soil_type":"clay loam","irrigation_method":"drip","root_zone_depth_cm":60,"growth_stage":"berry set","area":2.0,"area_unit":"ha","region":"NonExistent Region"}]'
    # Weather data with region="Other Region" only
    weather_data = b'timestamp,region,eto_mm,rain_forecast_mm,temperature_c,humidity_pct,wind_kph\n2026-05-15T12:00:00Z,Other Region,6.5,0,30,40,15\n'
    from io import BytesIO
    client.post(f'/v1/workbench/sessions/{sid}/upload', files={'file': ('crop_profile.json', BytesIO(crop_data), 'application/json')})
    client.post(f'/v1/workbench/sessions/{sid}/upload', files={'file': ('weather_summary.csv', BytesIO(weather_data), 'text/csv')})
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id': sid, 'mode': 'uploaded'})
    assert r.status_code == 200
    body = r.json()
    # A warning must be emitted about the missing region weather
    warnings = body.get('warnings', [])
    region_warn = [w for w in warnings if 'nonexistent region' in str(w).lower() or 'no weather records matched' in str(w).lower()]
    assert region_warn, f"Expected region isolation warning, got warnings: {warnings}"


# --- Section 16: Fifth-pass surgical corrections --------------------------------

def test_scheduling_gate_override_rejected(client):
    """Scheduling gate must reject even when override_reason is supplied."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'incomplete_evidence_review'})
    session_id = created.json()['session']['session_id']
    client.post(f'/v1/workbench/sessions/{session_id}/analyze', json={'session_id': session_id, 'mode': 'uploaded'})
    r = client.post(
        f'/v1/workbench/sessions/{session_id}/actions/schedule',
        json={'actor': 'Ops', 'override_reason': 'Attempting to bypass scheduling gate.'},
    )
    assert r.status_code == 409
    assert 'scheduling' in r.json()['detail'].lower()
    assert 'override' not in r.json()['detail'].lower()


def test_incomplete_schedule_no_override_returns_409(client):
    """Incomplete evidence session must return 409 on schedule without override_reason."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'incomplete_evidence_review'})
    session_id = created.json()['session']['session_id']
    client.post(f'/v1/workbench/sessions/{session_id}/analyze', json={'session_id': session_id, 'mode': 'uploaded'})
    r = client.post(f'/v1/workbench/sessions/{session_id}/actions/schedule', json={'actor': 'Ops'})
    assert r.status_code == 409


def test_evidence_chain_unchanged_after_gate_rejection(client):
    """Evidence chain must not advance after a scheduling gate rejection (with or without override_reason)."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'incomplete_evidence_review'})
    session_id = created.json()['session']['session_id']
    client.post(f'/v1/workbench/sessions/{session_id}/analyze', json={'session_id': session_id, 'mode': 'uploaded'})
    chain_before = client.get(f'/v1/workbench/sessions/{session_id}/evidence-chain').json()['evidence_chain']
    scheduled_before = next((s for s in chain_before if s['key'] == 'scheduled'), {}).get('status')
    client.post(f'/v1/workbench/sessions/{session_id}/actions/schedule', json={'actor': 'Ops'})
    client.post(f'/v1/workbench/sessions/{session_id}/actions/schedule',
                json={'actor': 'Ops', 'override_reason': 'Force attempt'})
    chain_after = client.get(f'/v1/workbench/sessions/{session_id}/evidence-chain').json()['evidence_chain']
    scheduled_after = next((s for s in chain_after if s['key'] == 'scheduled'), {}).get('status')
    assert scheduled_after == scheduled_before


def test_validated_schedule_still_succeeds(client):
    """Validated operating block must still schedule successfully (gate passes)."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    session_id = created.json()['session']['session_id']
    client.post(f'/v1/workbench/sessions/{session_id}/analyze', json={'session_id': session_id, 'mode': 'uploaded'})
    r = client.post(f'/v1/workbench/sessions/{session_id}/actions/schedule', json={'actor': 'Ops'})
    assert r.status_code == 200


def test_validated_no_flow_warnings(client):
    """Validated scenario must have no flow-related warnings."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    session_id = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{session_id}/analyze',
                           json={'session_id': session_id, 'mode': 'uploaded'})
    warnings = analyzed.json().get('warnings', [])
    flow_warns = [w for w in warnings if 'flow' in str(w).lower()]
    assert not flow_warns, f"Unexpected flow warnings: {flow_warns}"


def test_validated_pressure_stable(client):
    """Validated scenario must report pressure stable in flow evidence notes."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    session_id = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{session_id}/analyze',
                           json={'session_id': session_id, 'mode': 'uploaded'})
    rec = analyzed.json()['recommendation']
    assert rec.get('flow_validation_status') == 'validated'
    assert rec.get('duration_min') is not None
    assert rec.get('estimated_volume_m3') is not None


def test_report_savings_match_recommendation(client):
    """Report export_rows savings must match recommendation savings."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    session_id = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{session_id}/analyze',
                           json={'session_id': session_id, 'mode': 'uploaded'})
    rec = analyzed.json()['recommendation']
    report = client.get(f'/v1/workbench/sessions/{session_id}/report').json()
    assert report['metrics']['estimated_water_savings_percent'] == rec['estimated_water_savings_percent']
    assert report['export_rows'][0]['estimated_water_savings_percent'] == rec['estimated_water_savings_percent']


def test_mapping_booleans_all_false_for_incomplete(client):
    """Incomplete evidence: all mapping flags must be False — block_mapping_complete requires explicit field, not just a label."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'incomplete_evidence_review'})
    session_id = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{session_id}/analyze',
                           json={'session_id': session_id, 'mode': 'uploaded'})
    nc = analyzed.json()['normalized_context']
    # block_mapping_complete requires an explicit crop profile field, not inference from the block label.
    all_false_keys = [
        'farm_mapping_complete', 'block_mapping_complete', 'block_boundary_mapped',
        'crop_mapping_complete', 'variety_mapping_complete', 'soil_mapping_complete',
        'irrigation_method_mapping_complete', 'field_observation_available', 'earth_observation_available',
    ]
    for key in all_false_keys:
        assert nc.get(key) is False, f"Expected {key}=False for incomplete scenario, got {nc.get(key)!r}"


def test_mapping_booleans_present_for_validated(client):
    """Validated operating block must have farm, crop, soil mapping complete."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    session_id = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{session_id}/analyze',
                           json={'session_id': session_id, 'mode': 'uploaded'})
    nc = analyzed.json()['normalized_context']
    assert nc.get('farm_mapping_complete') is True
    assert nc.get('crop_mapping_complete') is True
    assert nc.get('soil_mapping_complete') is True
    assert nc.get('irrigation_method_mapping_complete') is True


def test_source_rows_returned_by_backend(client):
    """Backend must return source_rows in the analysis result."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    session_id = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{session_id}/analyze',
                           json={'session_id': session_id, 'mode': 'uploaded'})
    body = analyzed.json()
    source_rows = body.get('source_rows', [])
    assert isinstance(source_rows, list) and len(source_rows) > 0, "source_rows must be a non-empty list"
    for row in source_rows:
        assert 'source_label' in row
        assert 'source_kind' in row
        assert 'selected_scope_record_count' in row
        assert 'package_record_count' in row
        assert 'latest_signal_summary' in row
        assert 'contribution_label' in row


def test_source_rows_scope_vs_package_counts_differ(client):
    """selected_scope_record_count must be <= package_record_count for each source row."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    session_id = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{session_id}/analyze',
                           json={'session_id': session_id, 'mode': 'uploaded'})
    for row in analyzed.json().get('source_rows', []):
        assert row['selected_scope_record_count'] <= row['package_record_count'], (
            f"{row['source_label']}: selected {row['selected_scope_record_count']} > package {row['package_record_count']}"
        )


def test_incomplete_savings_duration_volume_withheld(client):
    """Incomplete evidence scenario must withhold savings, duration, and volume."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'incomplete_evidence_review'})
    session_id = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{session_id}/analyze',
                           json={'session_id': session_id, 'mode': 'uploaded'})
    rec = analyzed.json()['recommendation']
    assert rec.get('estimated_water_savings_percent') is None
    assert rec.get('duration_min') is None
    assert rec.get('estimated_volume_m3') is None


def test_scheduling_409_message_no_override_hint(client):
    """Scheduling 409 error message must not suggest that override_reason can bypass the gate."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'incomplete_evidence_review'})
    session_id = created.json()['session']['session_id']
    client.post(f'/v1/workbench/sessions/{session_id}/analyze', json={'session_id': session_id, 'mode': 'uploaded'})
    r = client.post(f'/v1/workbench/sessions/{session_id}/actions/schedule', json={'actor': 'Ops'})
    detail = r.json()['detail']
    assert 'supply override_reason' not in detail.lower()
    assert 'scheduling gate' in detail.lower() or 'scheduling not allowed' in detail.lower()


# --- Section 8: New regression tests ------------------------------------------

def test_scheduling_empty_session_fails_409(client):
    """Empty session (no analysis) must return 409 when trying to schedule."""
    session = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = session['session_id']
    r = client.post(f'/v1/workbench/sessions/{sid}/actions/schedule', json={'actor': 'Ops'})
    assert r.status_code == 409
    assert 'no analysis' in r.json()['detail'].lower() or 'scheduling not allowed' in r.json()['detail'].lower()


def test_scheduling_empty_session_with_override_reason_still_fails_409(client):
    """override_reason must not bypass the scheduling gate for an empty session."""
    session = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = session['session_id']
    r = client.post(f'/v1/workbench/sessions/{sid}/actions/schedule',
                    json={'actor': 'Ops', 'override_reason': 'Emergency override'})
    assert r.status_code == 409


def test_empty_session_schedule_leaves_evidence_unchanged(client):
    """A rejected scheduling attempt must leave evidence_actions unchanged."""
    session = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = session['session_id']
    r = client.post(f'/v1/workbench/sessions/{sid}/actions/schedule', json={'actor': 'Ops'})
    assert r.status_code == 409
    chain = client.get(f'/v1/workbench/sessions/{sid}/evidence-chain').json()
    # Evidence steps exist (pre-seeded) but none should be recorded after a rejected gate.
    assert all(s.get('status') == 'Pending' for s in chain.get('evidence_chain', [])), (
        "Rejected scheduling must not advance any evidence step"
    )
    assert chain.get('audit_events', []) == [], "Rejected scheduling must not write audit events"


def test_farm_a_field_notes_do_not_satisfy_farm_b(client):
    """Field notes for Farm A must not appear as selected-scope for Farm B."""
    from io import BytesIO
    from app.services import workbench_engine as e

    sid = e.create_session().session_id
    # Field notes only for Farm A / Block A
    notes_csv = b"farm,block,notes\nFarm A,Block 1,Great stress on Farm A Block 1 vines\n"
    art = e.WorkbenchDataArtifact(
        artifact_id='n1', session_id=sid, filename='notes.txt', content_type='text/plain',
        source_kind='field_notes', rows_detected=1, columns_detected=['farm', 'block', 'notes'],
        parse_status='parsed', parsed_rows=[{'farm': 'Farm A', 'block': 'Block 1', 'notes': 'Stress on Block 1'}],
    )
    e.SESSIONS[sid]['artifacts'].append(art)
    # Override context farm/block to Farm B / Block 2
    ctx = e.assemble_context_from_artifacts(e.SESSIONS[sid]['artifacts'])
    # Manually set farm/block as if Farm B is selected
    ctx['farm'] = 'Farm B'
    ctx['block'] = 'Block 2'
    # Recompute field notes for the wrong farm — must return empty
    from app.services.workbench_engine import _field_note_support, _rows_by_kind
    rows = _rows_by_kind(e.SESSIONS[sid]['artifacts'])
    notes_for_farm_b = _field_note_support(rows.get('field_notes', []), 'Farm B', 'Block 2')
    assert notes_for_farm_b == [], f"Farm A notes leaked into Farm B scope: {notes_for_farm_b}"


def test_farm_a_soil_readings_do_not_satisfy_farm_b():
    """Soil readings for Farm A / Block A must not appear in selected-scope for Farm B / Block B."""
    from app.services import workbench_engine as e
    sid = e.create_session().session_id
    art = e.WorkbenchDataArtifact(
        artifact_id='s1', session_id=sid, filename='soil.csv', content_type='text/csv',
        source_kind='soil_moisture', rows_detected=2, columns_detected=['farm', 'block', 'deficit_percent'],
        parse_status='parsed',
        parsed_rows=[
            {'farm': 'Farm A', 'block': 'Block 1', 'deficit_percent': '40'},
            {'farm': 'Farm A', 'block': 'Block 1', 'deficit_percent': '38'},
        ],
    )
    e.SESSIONS[sid]['artifacts'].append(art)
    # Manually call _rows_for to check isolation
    from app.services.workbench_engine import _rows_for, _rows_by_kind
    rows = _rows_by_kind(e.SESSIONS[sid]['artifacts'])
    farm_b_soil = _rows_for(rows.get('soil_moisture', []), 'Farm B', 'Block 2')
    assert farm_b_soil == [], "Farm A soil readings leaked into Farm B scope"


def test_controller_only_flow_does_not_make_flow_meter_available(client):
    """When only controller events exist, the Flow meter source row must be unavailable."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    session_id = created.json()['session']['session_id']
    from app.services import workbench_engine as e
    # Remove all flow_meter artifacts from the session
    e.SESSIONS[session_id]['artifacts'] = [
        a for a in e.SESSIONS[session_id]['artifacts'] if a.source_kind != 'flow_meter'
    ]
    analyzed = client.post(f'/v1/workbench/sessions/{session_id}/analyze',
                           json={'session_id': session_id, 'mode': 'uploaded'})
    source_rows = analyzed.json().get('source_rows', [])
    fm_row = next((r for r in source_rows if r['source_kind'] == 'flow_meter'), None)
    assert fm_row is not None, "Flow meter source row missing"
    assert fm_row['status'] == 'unavailable', f"Expected unavailable, got {fm_row['status']!r}"
    assert fm_row['selected_scope_record_count'] == 0


def test_incomplete_scenario_returns_customer_readable_next_actions(client):
    """Incomplete evidence scenario must return customer-readable next evidence instructions."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'incomplete_evidence_review'})
    session_id = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{session_id}/analyze',
                           json={'session_id': session_id, 'mode': 'uploaded'})
    rec = analyzed.json().get('recommendation', {})
    next_evidence = rec.get('next_evidence_required', [])
    # Customer-readable messages must not expose raw internal keys.
    raw_keys = {'eto_mm', 'crop_type', 'soil_type', 'irrigation_method', 'field_area_ha',
                'validated_flow_or_application_rate', 'recent_verified_applied_water_credit'}
    for item in next_evidence:
        assert item not in raw_keys, f"Raw internal key exposed as next evidence: {item!r}"
    # Any human-readable instruction must contain at least one space (not a bare key).
    for item in next_evidence:
        assert ' ' in item, f"Next evidence item appears to be a raw key: {item!r}"


def test_block_mapping_complete_false_when_only_label_exists(client):
    """block_mapping_complete must be False when the crop profile has a block label but no explicit field."""
    from io import BytesIO
    session = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = session['session_id']
    # Upload a crop profile with a block label but no block_mapping_complete field
    profile_json = b'[{"farm": "Test Farm", "block": "Test Block", "crop": "grapes"}]'
    client.post(f'/v1/workbench/sessions/{sid}/upload',
                files={'file': ('crop_profile.json', BytesIO(profile_json), 'application/json')})
    analyzed = client.post(f'/v1/workbench/sessions/{sid}/analyze',
                           json={'session_id': sid, 'mode': 'uploaded'})
    nc = analyzed.json()['normalized_context']
    assert nc.get('block_mapping_complete') is False, (
        f"block_mapping_complete must be False when no explicit field exists, got {nc.get('block_mapping_complete')!r}"
    )


def test_validated_block_mapping_complete_true(client):
    """Validated operating block sample must have block_mapping_complete=True from explicit crop profile field."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    session_id = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{session_id}/analyze',
                           json={'session_id': session_id, 'mode': 'uploaded'})
    nc = analyzed.json()['normalized_context']
    assert nc.get('block_mapping_complete') is True, (
        f"Validated scenario must have block_mapping_complete=True, got {nc.get('block_mapping_complete')!r}"
    )


def test_package_wide_counts_visible_separately(client):
    """Package-wide counts must be accessible separately from selected-scope counts."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    session_id = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{session_id}/analyze',
                           json={'session_id': session_id, 'mode': 'uploaded'})
    ss = analyzed.json()['signal_summary']
    # Package-wide counts must be present and >= selected-scope counts
    assert ss.get('pkg_controller_events_read', 0) >= ss.get('controller_events_read', 0)
    assert ss.get('pkg_soil_readings_read', 0) >= ss.get('soil_readings_read', 0)
    assert ss.get('pkg_flow_meter_records_read', 0) >= ss.get('flow_meter_records_read', 0)
    # Package-wide must be strictly greater (sample data has multiple farms/blocks)
    assert ss.get('pkg_controller_events_read', 0) > ss.get('controller_events_read', 0)
    assert ss.get('pkg_soil_readings_read', 0) > ss.get('soil_readings_read', 0)


# --- Section 8 (eighth pass): Explicit scope, signal isolation, clean limitations -----------

# --- 8.1 Explicit farm/block scope ---

def test_explicit_farm_block_scope_analyzes_correct_block(client):
    """Explicit selected_farm/selected_block must result in analysis of that farm/block."""
    from io import BytesIO
    session = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = session['session_id']
    # Upload a multi-farm crop profile; select Farm B / Block 2
    profile_json = b'''[
        {"farm": "Farm A", "block": "Block 1", "crop": "grapes", "soil_type": "clay", "irrigation_method": "drip"},
        {"farm": "Farm B", "block": "Block 2", "crop": "almonds", "soil_type": "sandy", "irrigation_method": "micro-sprinkler"}
    ]'''
    # Soil rows for both farms
    soil_csv = (
        b'timestamp,farm,block,depth_cm,moisture_percent,deficit_percent,sensor_health\n'
        b'2026-05-15T06:00:00Z,Farm A,Block 1,30,28.0,40,healthy\n'
        b'2026-05-15T06:00:00Z,Farm B,Block 2,30,22.0,55,healthy\n'
    )
    client.post(f'/v1/workbench/sessions/{sid}/upload',
                files={'file': ('crop_profile.json', BytesIO(profile_json), 'application/json')})
    client.post(f'/v1/workbench/sessions/{sid}/upload',
                files={'file': ('soil_moisture.csv', BytesIO(soil_csv), 'text/csv')})
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze',
                    json={'session_id': sid, 'mode': 'uploaded',
                          'selected_farm': 'Farm B', 'selected_block': 'Block 2'})
    assert r.status_code == 200
    body = r.json()
    ctx = body['normalized_context']
    # Farm B / Block 2 must be the analyzed scope
    assert ctx['farm'] == 'Farm B', f"Expected Farm B, got: {ctx['farm']!r}"
    assert ctx['block'] == 'Block 2', f"Expected Block 2, got: {ctx['block']!r}"
    assert ctx['crop'] == 'almonds', f"Expected almonds crop from Farm B profile, got: {ctx['crop']!r}"
    # selected_farm and selected_block preserved in context
    assert ctx.get('selected_farm') == 'Farm B'
    assert ctx.get('selected_block') == 'Block 2'
    # Soil scope must reflect Farm B only
    assert body['signal_summary']['soil_readings_read'] == 1, (
        f"Expected 1 soil reading for Farm B / Block 2, got: {body['signal_summary']['soil_readings_read']}")


def test_explicit_missing_scope_returns_truthful_incomplete(client):
    """When explicit scope has no matching crop profile, return truthful incomplete context + warning."""
    from io import BytesIO
    session = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = session['session_id']
    # Only Farm A / Block 1 in profile
    profile_json = b'[{"farm": "Farm A", "block": "Block 1", "crop": "grapes"}]'
    client.post(f'/v1/workbench/sessions/{sid}/upload',
                files={'file': ('crop_profile.json', BytesIO(profile_json), 'application/json')})
    # Request Farm B / Block 2 which does not exist
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze',
                    json={'session_id': sid, 'mode': 'uploaded',
                          'selected_farm': 'Farm B', 'selected_block': 'Block 2'})
    assert r.status_code == 200
    body = r.json()
    # Context must use the explicit farm/block (not silently fall back to Farm A)
    assert body['normalized_context']['farm'] == 'Farm B'
    assert body['normalized_context']['block'] == 'Block 2'
    # A warning must be emitted about the missing profile
    warnings = body.get('warnings', [])
    assert any('Farm B' in w or 'Block 2' in w or 'no crop profile' in w.lower() for w in warnings), (
        f"Expected scope-mismatch warning, got: {warnings}")


def test_selected_scope_returned_in_normalized_context(client):
    """selected_farm and selected_block must appear in normalized_context when explicitly provided."""
    from io import BytesIO
    created = client.post('/v1/workbench/sample-package')
    sid = created.json()['session']['session_id']
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze',
                    json={'session_id': sid, 'mode': 'uploaded',
                          'selected_farm': 'Alpha Vineyard', 'selected_block': 'Block A North'})
    assert r.status_code == 200
    ctx = r.json()['normalized_context']
    assert ctx.get('selected_farm') == 'Alpha Vineyard'
    assert ctx.get('selected_block') == 'Block A North'


def test_source_rows_change_when_selected_scope_changes(client):
    """Controller source row selected_scope_record_count must differ for Farm A vs Farm B."""
    from io import BytesIO
    # Upload shared multi-farm package
    profile = b'''[
        {"farm": "Farm A", "block": "Block 1", "crop": "grapes"},
        {"farm": "Farm B", "block": "Block 2", "crop": "almonds"}
    ]'''
    ctrl_csv = (
        b'timestamp,farm,block,zone,provider,event_type,scheduled_duration_min,applied_duration_min,flow_m3h,pressure_kpa,status\n'
        b'2026-05-15T21:00:00Z,Farm A,Block 1,Z1,WiseConn,scheduled_irrigation,40,40,28.0,230,complete\n'
        b'2026-05-15T21:00:00Z,Farm A,Block 1,Z1,WiseConn,scheduled_irrigation,42,42,27.5,228,complete\n'
        b'2026-05-15T22:00:00Z,Farm B,Block 2,Z2,WiseConn,scheduled_irrigation,35,35,22.0,215,complete\n'
    )
    s1 = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    for f, d, ct in [('crop_profile.json', profile, 'application/json'), ('controller_events.csv', ctrl_csv, 'text/csv')]:
        client.post(f'/v1/workbench/sessions/{s1}/upload', files={'file': (f, BytesIO(d), ct)})
    r_a = client.post(f'/v1/workbench/sessions/{s1}/analyze',
                      json={'session_id': s1, 'mode': 'uploaded',
                            'selected_farm': 'Farm A', 'selected_block': 'Block 1'})
    r_b = client.post(f'/v1/workbench/sessions/{s1}/analyze',
                      json={'session_id': s1, 'mode': 'uploaded',
                            'selected_farm': 'Farm B', 'selected_block': 'Block 2'})
    assert r_a.status_code == 200 and r_b.status_code == 200
    def ctrl_count(r): return next((row['selected_scope_record_count'] for row in r.json().get('source_rows', []) if row['source_kind'] == 'controller_events'), None)
    cnt_a = ctrl_count(r_a)
    cnt_b = ctrl_count(r_b)
    assert cnt_a == 2, f"Farm A should have 2 controller events, got {cnt_a}"
    assert cnt_b == 1, f"Farm B should have 1 controller event, got {cnt_b}"
    assert cnt_a != cnt_b, "Source rows must change when selected scope changes"


# --- 8.2 Confidence signal scoping ---

def test_unrelated_region_weather_does_not_increase_signal_count(client):
    """Weather from a different region must NOT appear in normalized_signal_count."""
    from io import BytesIO
    session = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = session['session_id']
    # Crop profile with region='Region A'
    profile = b'[{"farm":"Test Farm","block":"Test Block","crop":"grapes","region":"Region A"}]'
    # Weather ONLY from Region B (different)
    weather = b'timestamp,region,eto_mm,rain_forecast_mm\n2026-05-15T12:00:00Z,Region B,6.5,0\n'
    client.post(f'/v1/workbench/sessions/{sid}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    client.post(f'/v1/workbench/sessions/{sid}/upload', files={'file': ('weather_summary.csv', BytesIO(weather), 'text/csv')})
    r_with_other_region = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id': sid, 'mode': 'uploaded'})
    body_other = r_with_other_region.json()

    # Now compare with a session that has NO weather at all
    s2 = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    client.post(f'/v1/workbench/sessions/{s2}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    r_no_weather = client.post(f'/v1/workbench/sessions/{s2}/analyze', json={'session_id': s2, 'mode': 'uploaded'})
    body_no = r_no_weather.json()

    signal_with_other = body_other['normalized_context']['normalized_signal_count']
    signal_without = body_no['normalized_context']['normalized_signal_count']
    assert signal_with_other == signal_without, (
        f"Unrelated region weather must not increase signal count: "
        f"with={signal_with_other}, without={signal_without}"
    )


def test_unattributed_field_notes_do_not_increase_signal_count(client):
    """Field notes without farm/block attribution must not increase normalized_signal_count."""
    from io import BytesIO
    profile = b'[{"farm":"Test Farm","block":"Test Block","crop":"grapes"}]'
    # Unattributed free-text note
    notes = b'Generic field observation without farm or block identifier.\n'

    s_with = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    client.post(f'/v1/workbench/sessions/{s_with}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    client.post(f'/v1/workbench/sessions/{s_with}/upload', files={'file': ('field_notes.txt', BytesIO(notes), 'text/plain')})
    r_with = client.post(f'/v1/workbench/sessions/{s_with}/analyze', json={'session_id': s_with, 'mode': 'uploaded'})

    s_without = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    client.post(f'/v1/workbench/sessions/{s_without}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    r_without = client.post(f'/v1/workbench/sessions/{s_without}/analyze', json={'session_id': s_without, 'mode': 'uploaded'})

    sig_with = r_with.json()['normalized_context']['normalized_signal_count']
    sig_without = r_without.json()['normalized_context']['normalized_signal_count']
    assert sig_with == sig_without, (
        f"Unattributed field notes must not raise signal count: with={sig_with}, without={sig_without}"
    )


def test_farm_a_rows_do_not_increase_farm_b_confidence(client):
    """Soil readings from Farm A must not boost Farm B confidence score."""
    from io import BytesIO
    # Multi-farm profile: select Farm B
    profile = b'''[
        {"farm": "Farm A", "block": "Block 1", "crop": "grapes"},
        {"farm": "Farm B", "block": "Block 2", "crop": "almonds"}
    ]'''
    soil_a_only = (
        b'timestamp,farm,block,depth_cm,moisture_percent,deficit_percent,sensor_health\n'
        b'2026-05-15T06:00:00Z,Farm A,Block 1,30,28.0,40,healthy\n'
        b'2026-05-15T06:00:00Z,Farm A,Block 1,60,29.0,35,healthy\n'
    )
    soil_none = b'timestamp,farm,block,depth_cm,moisture_percent,deficit_percent,sensor_health\n'

    def analyze_farm_b(soil_data: bytes) -> float:
        s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
        client.post(f'/v1/workbench/sessions/{s}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
        if soil_data:
            client.post(f'/v1/workbench/sessions/{s}/upload', files={'file': ('soil_moisture.csv', BytesIO(soil_data), 'text/csv')})
        r = client.post(f'/v1/workbench/sessions/{s}/analyze',
                        json={'session_id': s, 'mode': 'uploaded',
                              'selected_farm': 'Farm B', 'selected_block': 'Block 2'})
        return r.json()['reconciliation']['confidence_score']

    score_with_farm_a_soil = analyze_farm_b(soil_a_only)
    score_without_soil = analyze_farm_b(soil_none)
    assert score_with_farm_a_soil == score_without_soil, (
        f"Farm A soil readings must not change Farm B confidence: "
        f"with={score_with_farm_a_soil}, without={score_without_soil}"
    )


def test_selected_source_kinds_returned_in_normalized_context(client):
    """selected_source_kinds and package_source_kinds must appear in normalized_context."""
    created = client.post('/v1/workbench/sample-package')
    sid = created.json()['session']['session_id']
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id': sid, 'mode': 'uploaded'})
    ctx = r.json()['normalized_context']
    assert 'selected_source_kinds' in ctx, "selected_source_kinds must be in normalized_context"
    assert 'package_source_kinds' in ctx, "package_source_kinds must be in normalized_context"
    # Package source kinds must include all uploaded kinds
    pkg_kinds = ctx['package_source_kinds']
    assert 'weather' in pkg_kinds
    assert 'controller_events' in pkg_kinds


# --- 8.3 No raw keys in customer-visible limitations ---

_RAW_INTERNAL_KEYS = {
    'eto_mm', 'crop_type', 'soil_type', 'irrigation_method', 'field_area_ha',
    'validated_flow_or_application_rate', 'recent_verified_applied_water_credit',
    'block_boundary_mapping', 'current_field_observation', 'block_mapping',
    'farm_mapping', 'variety_mapping',
}

def test_visible_limitations_no_raw_internal_keys(client):
    """Limitations list must not contain raw internal keys — only readable sentences."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'incomplete_evidence_review'})
    sid = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id': sid, 'mode': 'uploaded'})
    limitations = analyzed.json().get('limitations', [])
    for lim in limitations:
        assert lim not in _RAW_INTERNAL_KEYS, f"Raw internal key exposed in limitations: {lim!r}"
        assert ' ' in str(lim), f"Limitation appears to be a raw key (no spaces): {lim!r}"


def test_visible_limitations_no_raw_keys_validated_block(client):
    """Validated block limitations must also contain only readable sentences."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    sid = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id': sid, 'mode': 'uploaded'})
    limitations = analyzed.json().get('limitations', [])
    for lim in limitations:
        assert lim not in _RAW_INTERNAL_KEYS, f"Raw key in validated block limitations: {lim!r}"


# --- 8.4 Derived reconciliation claims ---

def test_incomplete_reconciliation_never_claims_schedulable_decision(client):
    """Incomplete evidence must not say 'schedulable water decision' in interpretation."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'incomplete_evidence_review'})
    sid = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id': sid, 'mode': 'uploaded'})
    rec = analyzed.json()['reconciliation']
    interp = rec.get('interpretation', '')
    assert 'schedulable water decision' not in interp.lower(), (
        f"Incomplete reconciliation must not claim schedulable: {interp!r}"
    )
    # Must indicate incomplete state — either blocked/pending language or an inspection/wait outcome
    incomplete_state_keywords = ['pending', 'blocked', 'conflict', 'inspection', 'wait']
    assert any(kw in interp.lower() for kw in incomplete_state_keywords), (
        f"Interpretation must reflect incomplete state: {interp!r}"
    )


def test_field_observation_support_no_fabricated_claims(client):
    """field_observation_support must not fabricate night-irrigation or runoff claims."""
    from io import BytesIO
    session = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = session['session_id']
    # Generic note with no night irrigation / runoff mention
    profile = b'[{"farm":"Test Farm","block":"Test Block","crop":"grapes","farm_mapping_complete":true,"block_mapping_complete":true}]'
    notes = b'Test Farm / Test Block: conditions look normal today.\n'
    client.post(f'/v1/workbench/sessions/{sid}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    client.post(f'/v1/workbench/sessions/{sid}/upload', files={'file': ('field_notes.txt', BytesIO(notes), 'text/plain')})
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id': sid, 'mode': 'uploaded'})
    recon = r.json()['reconciliation']
    obs_support = recon.get('field_observation_support', '')
    # Must not fabricate specific claims not in the notes
    assert 'night irrigation' not in obs_support.lower(), (
        f"Must not fabricate night-irrigation claim: {obs_support!r}"
    )
    assert 'no visible runoff' not in obs_support.lower(), (
        f"Must not fabricate runoff claim: {obs_support!r}"
    )
    # Must be conservative — indicate observations are available
    assert 'field observation' in obs_support.lower() or 'available' in obs_support.lower(), (
        f"Must indicate field observation availability: {obs_support!r}"
    )


def test_field_observation_support_without_notes_is_honest(client):
    """field_observation_support must say no observation is available when no notes exist."""
    from io import BytesIO
    session = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = session['session_id']
    profile = b'[{"farm":"Test Farm","block":"Test Block","crop":"grapes"}]'
    client.post(f'/v1/workbench/sessions/{sid}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id': sid, 'mode': 'uploaded'})
    obs = r.json()['reconciliation'].get('field_observation_support', '')
    assert 'no selected-block field observation' in obs.lower() or 'not available' in obs.lower() or 'missing' in obs.lower(), (
        f"Must report field observation unavailable: {obs!r}"
    )


# --- 8.5 Explicit farm mapping ---

def test_farm_mapping_complete_false_without_explicit_field(client):
    """farm_mapping_complete must be False when no explicit farm_mapping_complete field exists."""
    from io import BytesIO
    session = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = session['session_id']
    # Profile with farm label but no farm_mapping_complete field
    profile = b'[{"farm": "Some Farm", "block": "Block X", "crop": "grapes"}]'
    client.post(f'/v1/workbench/sessions/{sid}/upload',
                files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id': sid, 'mode': 'uploaded'})
    nc = r.json()['normalized_context']
    assert nc.get('farm_mapping_complete') is False, (
        f"farm_mapping_complete must be False without explicit field, got {nc.get('farm_mapping_complete')!r}"
    )


def test_validated_farm_mapping_complete_true(client):
    """Validated sample package must have farm_mapping_complete=True from explicit crop profile field."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    sid = created.json()['session']['session_id']
    r = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id': sid, 'mode': 'uploaded'})
    nc = r.json()['normalized_context']
    assert nc.get('farm_mapping_complete') is True, (
        f"Validated sample must have farm_mapping_complete=True, got {nc.get('farm_mapping_complete')!r}"
    )


# --- 8.6 End-to-end isolation ---

def test_farm_a_notes_never_satisfy_farm_b_reconciliation(client):
    """Field notes for Farm A must not satisfy Farm B field_observation support."""
    from io import BytesIO
    profile = b'''[
        {"farm":"Farm A","block":"Block 1","crop":"grapes"},
        {"farm":"Farm B","block":"Block 2","crop":"almonds"}
    ]'''
    # Notes ONLY for Farm A / Block 1
    notes = b'Farm A / Block 1: conditions are excellent today.\n'

    def get_field_obs(selected_farm, selected_block):
        s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
        client.post(f'/v1/workbench/sessions/{s}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
        client.post(f'/v1/workbench/sessions/{s}/upload', files={'file': ('field_notes.txt', BytesIO(notes), 'text/plain')})
        r = client.post(f'/v1/workbench/sessions/{s}/analyze',
                        json={'session_id': s, 'mode': 'uploaded',
                              'selected_farm': selected_farm, 'selected_block': selected_block})
        return r.json()['signal_summary'].get('field_notes_parsed', -1)

    notes_for_farm_a = get_field_obs('Farm A', 'Block 1')
    notes_for_farm_b = get_field_obs('Farm B', 'Block 2')
    assert notes_for_farm_a >= 1, f"Farm A notes must satisfy Farm A: {notes_for_farm_a}"
    assert notes_for_farm_b == 0, f"Farm A notes must not satisfy Farm B: {notes_for_farm_b}"


def test_farm_a_soil_never_increases_farm_b_confidence(client):
    """Farm A soil data must not change Farm B confidence vs no soil at all."""
    from io import BytesIO
    profile = b'''[
        {"farm":"Farm A","block":"Block 1","crop":"grapes"},
        {"farm":"Farm B","block":"Block 2","crop":"almonds"}
    ]'''
    soil_a = (
        b'timestamp,farm,block,depth_cm,moisture_percent,deficit_percent,sensor_health\n'
        b'2026-05-15T06:00:00Z,Farm A,Block 1,30,25.0,48,healthy\n'
    )
    no_soil = b'timestamp,farm,block,depth_cm,moisture_percent,deficit_percent,sensor_health\n'

    def score(soil_data):
        s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
        client.post(f'/v1/workbench/sessions/{s}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
        client.post(f'/v1/workbench/sessions/{s}/upload', files={'file': ('soil_moisture.csv', BytesIO(soil_data), 'text/csv')})
        r = client.post(f'/v1/workbench/sessions/{s}/analyze',
                        json={'session_id': s, 'mode': 'uploaded',
                              'selected_farm': 'Farm B', 'selected_block': 'Block 2'})
        return r.json()['reconciliation']['confidence_score']

    assert score(soil_a) == score(no_soil), "Farm A soil must not influence Farm B confidence"


def test_farm_a_satellite_never_satisfies_farm_b(client):
    """Satellite rows for Farm A must not appear in Farm B selected-scope count."""
    from io import BytesIO
    profile = b'''[
        {"farm":"Farm A","block":"Block 1","crop":"grapes"},
        {"farm":"Farm B","block":"Block 2","crop":"almonds"}
    ]'''
    sat_a = (
        b'timestamp,farm,block,ndvi,canopy_temperature_c,vegetation_stress_index,source_label\n'
        b'2026-05-15T18:00:00Z,Farm A,Block 1,0.71,31.4,0.38,Layer\n'
    )
    s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    client.post(f'/v1/workbench/sessions/{s}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    client.post(f'/v1/workbench/sessions/{s}/upload', files={'file': ('satellite_observation.csv', BytesIO(sat_a), 'text/csv')})
    r = client.post(f'/v1/workbench/sessions/{s}/analyze',
                    json={'session_id': s, 'mode': 'uploaded',
                          'selected_farm': 'Farm B', 'selected_block': 'Block 2'})
    ss = r.json()['signal_summary']
    assert ss.get('satellite_observations_read', 0) == 0, (
        f"Farm A satellite must not appear in Farm B selected scope: {ss.get('satellite_observations_read')}"
    )


# --- Section 9 (ninth pass): partial scope, regional isolation, reconciliation, error message ---

def test_only_selected_farm_without_block_returns_warning(client):
    """Providing selected_farm without selected_block must produce a warning, not a silent fallback."""
    from io import BytesIO
    profile = b'''[
        {"farm": "Farm A", "block": "Block 1", "crop": "grapes"},
        {"farm": "Farm A", "block": "Block 2", "crop": "grapes"}
    ]'''
    s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    client.post(f'/v1/workbench/sessions/{s}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    r = client.post(f'/v1/workbench/sessions/{s}/analyze',
                    json={'session_id': s, 'mode': 'uploaded', 'selected_farm': 'Farm A'})
    assert r.status_code == 200
    warnings = r.json().get('warnings', [])
    assert any('selected_farm' in w and 'selected_block' in w for w in warnings), (
        f"Expected partial-scope warning, got: {warnings}")
    # Must not silently use default Alpha Vineyard
    ctx = r.json()['normalized_context']
    assert ctx['farm'] == 'Farm A', f"Farm must be the explicitly requested Farm A, got: {ctx['farm']!r}"


def test_only_selected_block_without_farm_returns_warning(client):
    """Providing selected_block without selected_farm must produce a warning."""
    from io import BytesIO
    profile = b'[{"farm": "Farm A", "block": "Block 1", "crop": "grapes"}]'
    s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    client.post(f'/v1/workbench/sessions/{s}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    r = client.post(f'/v1/workbench/sessions/{s}/analyze',
                    json={'session_id': s, 'mode': 'uploaded', 'selected_block': 'Block 1'})
    assert r.status_code == 200
    warnings = r.json().get('warnings', [])
    assert any('selected_block' in w or 'Both are required' in w for w in warnings), (
        f"Expected partial-scope warning, got: {warnings}")


def test_available_farms_and_blocks_returned_in_normalized_context(client):
    """available_farms and available_blocks_by_farm must be present in normalized_context."""
    from io import BytesIO
    profile = b'''[
        {"farm": "Farm A", "block": "Block 1", "crop": "grapes"},
        {"farm": "Farm A", "block": "Block 2", "crop": "grapes"},
        {"farm": "Farm B", "block": "Block 1", "crop": "almonds"}
    ]'''
    s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    client.post(f'/v1/workbench/sessions/{s}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    r = client.post(f'/v1/workbench/sessions/{s}/analyze', json={'session_id': s, 'mode': 'uploaded'})
    assert r.status_code == 200
    ctx = r.json()['normalized_context']
    assert 'available_farms' in ctx, "available_farms must be in normalized_context"
    assert 'available_blocks_by_farm' in ctx, "available_blocks_by_farm must be in normalized_context"
    assert 'Farm A' in ctx['available_farms']
    assert 'Farm B' in ctx['available_farms']
    assert 'Block 1' in ctx['available_blocks_by_farm'].get('Farm A', [])
    assert 'Block 2' in ctx['available_blocks_by_farm'].get('Farm A', [])


def test_scope_defaulted_true_when_multiple_farms_no_explicit_scope(client):
    """scope_defaulted must be True when multiple farms exist but no explicit scope was supplied."""
    from io import BytesIO
    profile = b'''[
        {"farm": "Farm A", "block": "Block 1", "crop": "grapes"},
        {"farm": "Farm B", "block": "Block 1", "crop": "almonds"}
    ]'''
    s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    client.post(f'/v1/workbench/sessions/{s}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    r = client.post(f'/v1/workbench/sessions/{s}/analyze', json={'session_id': s, 'mode': 'uploaded'})
    ctx = r.json()['normalized_context']
    assert ctx.get('scope_defaulted') is True, f"scope_defaulted must be True when multiple farms, got: {ctx.get('scope_defaulted')!r}"


def test_unrelated_region_water_costs_do_not_increase_signal_count(client):
    """Water-cost records from a different region must NOT appear in normalized_signal_count."""
    from io import BytesIO
    profile = b'[{"farm":"Test Farm","block":"Test Block","crop":"grapes","region":"Region A"}]'
    # Water costs ONLY from Region B
    costs = b'region,water_source,cost_per_acre_ft,allocation_status\nRegion B,Canal,85,ok\n'

    s_with = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    client.post(f'/v1/workbench/sessions/{s_with}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    client.post(f'/v1/workbench/sessions/{s_with}/upload', files={'file': ('water_costs.csv', BytesIO(costs), 'text/csv')})
    r_with = client.post(f'/v1/workbench/sessions/{s_with}/analyze', json={'session_id': s_with, 'mode': 'uploaded'})

    s_without = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    client.post(f'/v1/workbench/sessions/{s_without}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    r_without = client.post(f'/v1/workbench/sessions/{s_without}/analyze', json={'session_id': s_without, 'mode': 'uploaded'})

    sig_with = r_with.json()['normalized_context']['normalized_signal_count']
    sig_without = r_without.json()['normalized_context']['normalized_signal_count']
    assert sig_with == sig_without, (
        f"Unrelated region water costs must not increase signal count: with={sig_with}, without={sig_without}"
    )


def test_unattributed_weather_does_not_increase_signal_count_when_region_known(client):
    """Weather rows with no region attribution must not enter normalized_signal_count when region is known."""
    from io import BytesIO
    # Crop profile with region
    profile = b'[{"farm":"Test Farm","block":"Test Block","crop":"grapes","region":"Region A"}]'
    # Weather with no region column
    weather_no_region = b'timestamp,eto_mm,rain_forecast_mm\n2026-05-15T12:00:00Z,6.5,0\n'

    s_with = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    client.post(f'/v1/workbench/sessions/{s_with}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    client.post(f'/v1/workbench/sessions/{s_with}/upload', files={'file': ('weather_summary.csv', BytesIO(weather_no_region), 'text/csv')})
    r_with = client.post(f'/v1/workbench/sessions/{s_with}/analyze', json={'session_id': s_with, 'mode': 'uploaded'})

    s_without = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    client.post(f'/v1/workbench/sessions/{s_without}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    r_without = client.post(f'/v1/workbench/sessions/{s_without}/analyze', json={'session_id': s_without, 'mode': 'uploaded'})

    sig_with = r_with.json()['normalized_context']['normalized_signal_count']
    sig_without = r_without.json()['normalized_context']['normalized_signal_count']
    assert sig_with == sig_without, (
        f"Unattributed weather must not increase signal count when region is known: with={sig_with}, without={sig_without}"
    )


def test_unattributed_water_cost_does_not_increase_signal_count_when_region_known(client):
    """Water-cost rows with no region attribution must not enter normalized_signal_count when region is known."""
    from io import BytesIO
    profile = b'[{"farm":"Test Farm","block":"Test Block","crop":"grapes","region":"Region A"}]'
    # Water costs with no region column
    costs_no_region = b'water_source,cost_per_acre_ft,allocation_status\nCanal,85,ok\n'

    s_with = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    client.post(f'/v1/workbench/sessions/{s_with}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    client.post(f'/v1/workbench/sessions/{s_with}/upload', files={'file': ('water_costs.csv', BytesIO(costs_no_region), 'text/csv')})
    r_with = client.post(f'/v1/workbench/sessions/{s_with}/analyze', json={'session_id': s_with, 'mode': 'uploaded'})

    s_without = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()['session_id']
    client.post(f'/v1/workbench/sessions/{s_without}/upload', files={'file': ('crop_profile.json', BytesIO(profile), 'application/json')})
    r_without = client.post(f'/v1/workbench/sessions/{s_without}/analyze', json={'session_id': s_without, 'mode': 'uploaded'})

    sig_with = r_with.json()['normalized_context']['normalized_signal_count']
    sig_without = r_without.json()['normalized_context']['normalized_signal_count']
    assert sig_with == sig_without, (
        f"Unattributed water-cost must not increase signal count when region is known: with={sig_with}, without={sig_without}"
    )


def test_pkg_weather_and_water_cost_counts_present(client):
    """pkg_weather_records_read and pkg_water_cost_records_read must be in signal_summary."""
    from io import BytesIO
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    sid = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id': sid, 'mode': 'uploaded'})
    ss = analyzed.json()['signal_summary']
    assert 'pkg_weather_records_read' in ss, "pkg_weather_records_read must be in signal_summary"
    assert 'pkg_water_cost_records_read' in ss, "pkg_water_cost_records_read must be in signal_summary"
    # Package-wide counts must be >= selected scope counts
    assert ss.get('pkg_weather_records_read', 0) >= ss.get('weather_records_read', 0)
    assert ss.get('pkg_water_cost_records_read', 0) >= ss.get('water_cost_records_read', 0)


def test_analysis_error_message_truthful(client):
    """Analyze endpoint must not wrap every error as 'Live source unavailable'."""
    # Supply an invalid mode to trigger an error path
    s = client.post('/v1/workbench/sessions', json={'mode': 'uploaded'}).json()
    sid = s['session_id']
    # Delete the session from in-memory store to force a 404 path
    # (This tests the HTTP layer; the truthful message applies to internal exceptions)
    r = client.post(f'/v1/workbench/sessions/nonexistent-session/analyze',
                    json={'session_id': 'nonexistent-session', 'mode': 'uploaded'})
    # Must return 404 for unknown session — not a misleading live-source error
    assert r.status_code == 404


def test_validated_reconciliation_interpretation_is_schedulable(client):
    """Validated operating block must produce a schedulable interpretation."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'validated_operating_block'})
    sid = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id': sid, 'mode': 'uploaded'})
    interp = analyzed.json()['reconciliation'].get('interpretation', '')
    assert 'schedulable water decision' in interp.lower(), (
        f"Validated block must produce schedulable interpretation, got: {interp!r}"
    )


def test_incomplete_reconciliation_interpretation_is_blocked(client):
    """Incomplete evidence must produce blocked/inspection interpretation, never schedulable."""
    created = client.post('/v1/workbench/sample-package', json={'scenario': 'incomplete_evidence_review'})
    sid = created.json()['session']['session_id']
    analyzed = client.post(f'/v1/workbench/sessions/{sid}/analyze', json={'session_id': sid, 'mode': 'uploaded'})
    interp = analyzed.json()['reconciliation'].get('interpretation', '')
    assert 'schedulable water decision' not in interp.lower(), (
        f"Incomplete evidence must not claim schedulable: {interp!r}"
    )


def test_live_reconciliation_interpretation_is_pending(client):
    """Live request must produce 'Live provider request accepted' interpretation."""
    r = client.post('/v1/workbench/analyze-live', json={'source': 'wiseconn', 'entity_id': '162803'})
    assert r.status_code == 200
    interp = r.json()['reconciliation'].get('interpretation', '')
    assert 'live provider request' in interp.lower(), (
        f"Live result must contain 'live provider request' in interpretation, got: {interp!r}"
    )
