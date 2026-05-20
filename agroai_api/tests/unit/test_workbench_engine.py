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
    assert len(res.analysis_trace) == 8
    assert res.report_summary['executive_summary']
