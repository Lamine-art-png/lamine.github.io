from app.services import workbench_engine as e

def test_create_session():
    s = e.create_session()
    assert s.session_id

def test_detect_source_kind_and_schema():
    assert e.detect_source_kind('weather_summary.csv', ['eto','rain']) == 'weather'
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
