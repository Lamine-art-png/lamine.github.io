from . import compliance_pack_legacy_suite as _legacy


_REPLACED = "test_compliance_migration_preflight_classifies_clean_002_and_003"

for _name in dir(_legacy):
    if _name.startswith("test_") and _name != _REPLACED:
        globals()[_name] = getattr(_legacy, _name)


def test_compliance_migration_preflight_classifies_clean_002_and_003(tmp_path, monkeypatch):
    db_path = tmp_path / "preflight.db"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setattr(_legacy.settings, "DATABASE_URL", database_url)
    _legacy._bootstrap_legacy_baseline(db_path)
    assert _legacy.collect_report(database_url)["schema_classification"] == "A_clean_baseline_no_compliance_tables"

    cfg = _legacy._alembic_config(db_path)
    _legacy.command.upgrade(cfg, "002_california_compliance_pack")
    report_002 = _legacy.collect_report(database_url)
    assert report_002["current_alembic_revision"] == "002_california_compliance_pack"
    assert report_002["schema_classification"] == "B_migration_002_schema"
    assert report_002["tables"]["compliance_export_metadata"] is False
    assert report_002["parcel_identifier_exists"] is False

    _legacy.command.upgrade(cfg, "head")
    report_head = _legacy.collect_report(database_url)
    assert report_head["current_alembic_revision"] == "009_telemetry_recommendations"
    assert report_head["schema_classification"] == "C_migration_003_schema"
    assert report_head["tables"]["compliance_export_metadata"] is True
    assert report_head["parcel_identifier_exists"] is True
