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
    assert res.signal_summary['controller_events_read'] >= 20
    assert res.signal_summary['soil_readings_read'] >= 20
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
