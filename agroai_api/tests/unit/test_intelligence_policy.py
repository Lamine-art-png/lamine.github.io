from app.services.intelligence_policy import action_requires_human_approval, classify_action_kind


def test_start_zone_paraphrase_is_physical_and_requires_approval():
    kind = classify_action_kind("Start Zone 4")
    assert kind == "physical_execution"
    assert action_requires_human_approval(kind) is True


def test_run_zone_with_duration_is_physical_and_requires_approval():
    kind = classify_action_kind("Run Zone 4 for 20 minutes")
    assert kind == "physical_execution"
    assert action_requires_human_approval(kind) is True


def test_open_valve_is_physical_and_requires_approval():
    kind = classify_action_kind("Open valve 2")
    assert kind == "physical_execution"
    assert action_requires_human_approval(kind) is True


def test_chemical_application_is_typed_and_requires_approval():
    kind = classify_action_kind("Apply fungicide to the affected rows")
    assert kind == "chemical_application"
    assert action_requires_human_approval(kind) is True


def test_external_submission_is_typed_and_requires_approval():
    kind = classify_action_kind("Submit the report to regulator")
    assert kind == "external_submission"
    assert action_requires_human_approval(kind) is True


def test_inspection_is_side_effect_free():
    kind = classify_action_kind("Inspect valve 2 for obstruction")
    assert kind == "inspection"
    assert action_requires_human_approval(kind) is False


def test_data_collection_is_side_effect_free():
    kind = classify_action_kind("Measure flow at the meter")
    assert kind == "data_collection"
    assert action_requires_human_approval(kind) is False


def test_unknown_action_defaults_to_operational_and_requires_approval():
    kind = classify_action_kind("Optimize Block A now")
    assert kind == "operational_recommendation"
    assert action_requires_human_approval(kind) is True
