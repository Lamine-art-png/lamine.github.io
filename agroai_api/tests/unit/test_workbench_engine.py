from app.services import workbench_engine as e

def test_create_session():
    s = e.create_session()
    assert s.session_id

def test_detect_source_kind_and_schema():
    assert e.detect_source_kind('weather_summary.csv', ['eto','rain']) == 'weather'
    assert e.detect_source_kind('flow_meter.csv', ['planned_m3','actual_m3']) == 'flow_meter'
    assert e.detect_source_kind('crop_profile.json', ['root_zone_depth_cm']) == 'crop_profile'
    schema = e.infer_schema(['ET0','Rainfall','Runtime'])
    assert schema['ET0'] == 'eto'
    assert schema['Rainfall'] == 'rain'

def test_parse_csv_json_txt():
    rows, cols, _ = e.parse_uploaded_file('a.csv', b'timestamp,eto\n2026-01-01,6.4\n')
    assert len(rows) == 1 and 'eto' in cols
    rowsj, _, _ = e.parse_uploaded_file('a.json', b'[{"rain":0}]')
    assert rowsj[0]['rain'] == 0
    rowst, _, _ = e.parse_uploaded_file('a.txt', b'note 1\nnote2')
    assert len(rowst) == 2

def test_analyze_uploaded_low_confidence():
    s = e.create_session()
    art = e.WorkbenchDataArtifact(artifact_id='1', session_id=s.session_id, filename='notes.txt', content_type='text/plain', source_kind='field_notes', rows_detected=1, columns_detected=['notes'], parse_status='parsed', parsed_rows=[{'notes':'dry'}])
    e.SESSIONS[s.session_id]['artifacts'].append(art)
    res = e.analyze_session(s.session_id)
    assert res.reconciliation.missing_inputs
    assert res.model_status in ('deterministic_engine','optional_model_assist')

def test_sample_package_analysis_uses_rich_sources():
    sample = e.create_sample_package_session()
    sid = sample['session'].session_id
    res = e.analyze_session(sid)

    assert res.data_sources['file_count'] == 8
    assert res.data_sources['rows_parsed'] >= 70
    assert 'flow_meter' in res.data_sources['source_kinds_detected']
    assert res.normalized_context['farm'] == 'Alpha Vineyard'
    assert res.normalized_context['block'] == 'Block A North'
    # Selected-scope counts: only Block A North records.
    assert res.signal_summary['controller_events_read'] >= 1
    assert res.signal_summary['soil_readings_read'] >= 1
    # Package-wide counts: all records across all farms/blocks.
    assert res.signal_summary['pkg_controller_events_read'] >= 20
    assert res.signal_summary['pkg_soil_readings_read'] >= 20
    assert res.reconciliation.flow_meter_agreement
    assert res.recommendation['action']
    assert res.recommendation.get('duration_min') != 42
    assert res.recommendation.get('calibration_pack_version')
    assert len(res.analysis_trace) == 8
    assert res.report_summary['executive_summary']


def test_incomplete_context_does_not_fabricate_duration():
    s = e.create_session()
    art = e.WorkbenchDataArtifact(artifact_id='1', session_id=s.session_id, filename='weather.csv', content_type='text/csv', source_kind='weather', rows_detected=1, columns_detected=['eto_mm'], parse_status='parsed', parsed_rows=[{'eto_mm': '6.4'}])
    e.SESSIONS[s.session_id]['artifacts'].append(art)
    res = e.analyze_session(s.session_id)
    assert res.recommendation.get('duration_min') is None
    assert res.recommendation.get('no_fabricated_duration') is True


# --- Section 5: Flow-meter-only evidence -------------------------------------

def _controller_row(flow_m3h=28.0, block='Block A', farm='Farm X', ts='2026-05-29T10:00:00', pressure='300', status='complete'):
    return {'farm': farm, 'block': block, 'flow_m3h': str(flow_m3h), 'pressure_kpa': pressure, 'status': status, 'timestamp': ts}


def _flow_meter_row(flow_m3h=25.0, block='Block A', farm='Farm X', ts='2026-05-29T10:00:00', variance='3.0', actual_m3='120'):
    return {'farm': farm, 'block': block, 'flow_m3h': str(flow_m3h), 'actual_m3': actual_m3, 'variance_percent': variance, 'timestamp': ts}


def test_flow_meter_only_validates_when_no_controller_rows():
    result = e._flow_evidence([], [_flow_meter_row()])
    assert result['status'] == 'validated'
    assert result['value_m3h'] == 25.0
    assert result['provenance'] == 'flow_meter'


def test_controller_only_validates():
    result = e._flow_evidence([_controller_row()], [])
    assert result['status'] == 'validated'
    assert result['provenance'] == 'controller_event'


def test_no_positive_flow_returns_unavailable():
    result = e._flow_evidence([], [])
    assert result['status'] == 'unavailable'


def test_negative_flow_controller_returns_unavailable():
    result = e._flow_evidence([_controller_row(flow_m3h=-5)], [])
    assert result['status'] == 'unavailable'


def test_negative_flow_meter_returns_unavailable():
    result = e._flow_evidence([], [_flow_meter_row(flow_m3h=-3)])
    assert result['status'] == 'unavailable'


def test_inconsistent_flow_variance_returns_inconsistent():
    result = e._flow_evidence([], [_flow_meter_row(variance='25.0')])
    assert result['status'] == 'inconsistent'


def test_severe_pressure_controller_returns_inconsistent():
    result = e._flow_evidence([_controller_row(pressure='80')], [])
    assert result['status'] == 'inconsistent'


# --- Section 6: Area normalization -------------------------------------------

def test_hectares_accepted():
    ha, warnings = e.normalize_area_ha(2.5, 'ha')
    assert ha == 2.5
    assert not warnings


def test_acres_converted_correctly():
    ha, warnings = e.normalize_area_ha(1.0, 'acres')
    assert abs(ha - 0.404686) < 1e-4
    assert not warnings


def test_square_meters_converted_correctly():
    ha, warnings = e.normalize_area_ha(10000.0, 'm2')
    assert abs(ha - 1.0) < 1e-5
    assert not warnings


def test_zero_area_rejected():
    ha, warnings = e.normalize_area_ha(0, 'ha')
    assert ha is None
    assert warnings


def test_negative_area_rejected():
    ha, warnings = e.normalize_area_ha(-1.5, 'ha')
    assert ha is None
    assert warnings


def test_missing_area_unit_withholds():
    ha, warnings = e.normalize_area_ha(2.0, None)
    assert ha is None
    assert any('unit' in w.lower() for w in warnings)


def test_unknown_area_unit_rejected():
    ha, warnings = e.normalize_area_ha(2.0, 'furlongs')
    assert ha is None
    assert any('unknown' in w.lower() for w in warnings)


def test_area_without_unit_withholds_volume_in_analysis():
    s = e.create_session()
    res = e.analyze_session(s.session_id, mode='live', live_source='wiseconn', live_entity_id='162803',
                             manual_overrides={'area': 2.0})
    assert res.recommendation.get('estimated_volume_m3') is None


def test_area_with_valid_unit_flows_to_context():
    s = e.create_session()
    res = e.analyze_session(s.session_id, mode='live', live_source='wiseconn', live_entity_id='162803',
                             manual_overrides={'area': 5.0, 'area_unit': 'acres'})
    # A valid area + unit must not produce any area-unit warnings.
    area_warnings = [w for w in (res.warnings or []) if 'area unit' in str(w).lower() or 'unknown area' in str(w).lower()]
    assert not area_warnings


# --- Section 7: Historical evaluation mode -----------------------------------

def test_ordinary_uploaded_session_does_not_auto_set_reference_time():
    """Ordinary uploaded sessions must not auto-set evidence_reference_time from artifact timestamps."""
    s = e.create_session()
    # Use old timestamps that would be stale under wall-clock UTC but NOT under an
    # old reference time — confirming no auto-reference is injected.
    art = e.WorkbenchDataArtifact(
        artifact_id='x', session_id=s.session_id, filename='weather.csv',
        content_type='text/csv', source_kind='weather',
        rows_detected=1, columns_detected=['eto_mm'],
        parse_status='parsed',
        parsed_rows=[{'eto_mm': '6.4', 'timestamp': '2019-01-01T00:00:00'}],
    )
    e.SESSIONS[s.session_id]['artifacts'].append(art)
    # The assembled context metrics must NOT contain evidence_reference_time.
    ctx = e.assemble_context_from_artifacts(e.SESSIONS[s.session_id]['artifacts'])
    assert ctx['metrics'].get('evidence_reference_time') is None


def test_sample_package_session_sets_reference_time():
    """Sample package sessions must inject evidence_reference_time so stale timestamps
    are evaluated against the package's own reference, not wall-clock UTC."""
    sample = e.create_sample_package_session()
    sid = sample['session'].session_id
    assert e.SESSIONS[sid].get('is_sample_package') is True
    res = e.analyze_session(sid)
    # Sample package has fixed old timestamps — analysis must still return a result.
    assert res.recommendation.get('action')


def test_explicit_historical_evaluation_uses_supplied_reference():
    """When historical_evaluation=True and evidence_reference_time is set, that
    reference is used for recency checks (not wall-clock UTC)."""
    from datetime import datetime, timezone, timedelta
    ref = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    evidence_ts = (ref - timedelta(hours=6)).isoformat()
    sample = e.create_sample_package_session()
    sid = sample['session'].session_id
    e.SESSIONS[sid]['is_sample_package'] = False  # clear sample flag to test explicit path
    # Add flow artifact with evidence_ts that is 6 h before the explicit reference.
    art = e.WorkbenchDataArtifact(
        artifact_id='y', session_id=sid, filename='controller_events.csv',
        content_type='text/csv', source_kind='controller_events',
        rows_detected=1, columns_detected=['flow_m3h', 'timestamp', 'block', 'farm', 'pressure_kpa', 'status'],
        parse_status='parsed',
        parsed_rows=[{'flow_m3h': '25', 'timestamp': evidence_ts,
                      'block': 'Block A North', 'farm': 'Alpha Vineyard',
                      'pressure_kpa': '300', 'status': 'complete'}],
    )
    e.SESSIONS[sid]['artifacts'].append(art)
    res = e.analyze_session(sid, historical_evaluation=True, evidence_reference_time=ref.isoformat())
    assert res.recommendation.get('flow_validation_status') == 'validated'


def test_historical_evaluation_without_reference_time_degrades_safely():
    """historical_evaluation=True without evidence_reference_time must not crash;
    recency falls back to wall-clock UTC."""
    s = e.create_session()
    res = e.analyze_session(s.session_id, historical_evaluation=True)
    assert res.recommendation.get('action')


# --- Section 8: Model-assist claim removed ------------------------------------

def test_model_status_is_always_deterministic():
    """model_status must never claim model-assist solely because OPENAI_API_KEY exists."""
    import os
    os.environ['OPENAI_API_KEY'] = 'test-key'
    try:
        s = e.create_session()
        res = e.analyze_session(s.session_id)
        assert res.model_status == 'deterministic_engine'
    finally:
        del os.environ['OPENAI_API_KEY']


def test_analysis_summary_is_always_deterministic():
    """generate_analysis_summary must never mention model-assist."""
    import os
    os.environ['OPENAI_API_KEY'] = 'test-key'
    recon_stub = type('R', (), {
        'conflicts_detected': [],
        'confidence_label': 'Medium',
    })()
    try:
        summary = e.generate_analysis_summary(recon_stub, {'action': 'Irrigate'})
        assert 'model-assisted' not in summary.lower()
        assert 'OPENAI_API_KEY' not in summary
    finally:
        del os.environ['OPENAI_API_KEY']


# --- Section 9: Client-supplied confirmation_source is ignored ----------------

def test_client_supplied_controller_confirmed_is_not_accepted():
    """Browser payloads must not be able to self-assert controller_confirmed."""
    sample = e.create_sample_package_session()
    sid = sample['session'].session_id
    e.analyze_session(sid)
    result = e.record_evidence_action(
        sid, 'scheduled', 'Ops',
        payload={'confirmation_source': 'controller_confirmed'},
    )
    assert result['evidence_type'] == 'operator_attestation'


def test_client_supplied_flow_meter_confirmed_is_not_accepted():
    """Browser payloads must not be able to self-assert flow_meter_confirmed."""
    sample = e.create_sample_package_session()
    sid = sample['session'].session_id
    e.analyze_session(sid)
    result = e.record_evidence_action(
        sid, 'scheduled', 'Ops',
        payload={'confirmation_source': 'flow_meter_confirmed'},
    )
    assert result['evidence_type'] == 'operator_attestation'
