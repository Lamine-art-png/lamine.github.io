from types import SimpleNamespace

from app.services.connector_object_retention import gc_candidate


def make_job(status, input_json=None, output_json=None):
    return SimpleNamespace(status=status, input_json=input_json or {}, output_json=output_json or {})


def test_terminal_object_is_candidate():
    assert gc_candidate(make_job("failed", {"object_uri": "object-one"})) == ("object-one", "terminal_job")


def test_failed_duplicate_cleanup_is_candidate():
    value = make_job("succeeded", output_json={"deduplicated": True, "redundant_object_deleted": False, "object_uri": "object-two"})
    assert gc_candidate(value) == ("object-two", "duplicate_cleanup_retry")


def test_successful_evidence_object_is_not_candidate():
    value = make_job("succeeded", output_json={"deduplicated": False, "object_uri": "object-three"})
    assert gc_candidate(value) is None
