import sqlalchemy as sa

from app.db.schema_contract import (
    HEAD_ALEMBIC_REVISION,
    HEAD_SCHEMA_REQUIREMENTS,
    schema_contract_gaps,
    schema_matches_head_contract,
)


def test_column_contract_detects_partial_existing_table():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("example", metadata, sa.Column("id", sa.String(), primary_key=True))
    metadata.create_all(engine)
    with engine.connect() as connection:
        gaps = schema_contract_gaps(connection, {"example": {"id", "required_value"}})
        assert gaps == {"example": ["required_value"]}
        assert schema_matches_head_contract(connection) is False


def test_column_contract_accepts_complete_shape():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("example", metadata, sa.Column("id", sa.String(), primary_key=True), sa.Column("required_value", sa.String()))
    metadata.create_all(engine)
    with engine.connect() as connection:
        assert schema_contract_gaps(connection, {"example": {"id", "required_value"}}) == {}


def test_head_contract_covers_security_platform_field_launch_and_intelligence_memory():
    assert HEAD_ALEMBIC_REVISION == "030_intelligence_state_memory"
    assert {"device_code_hash", "user_code", "status", "expires_at"}.issubset(
        HEAD_SCHEMA_REQUIREMENTS["platform_cli_device_authorizations"]
    )
    assert {"nonce_hash", "consumed_at"}.issubset(HEAD_SCHEMA_REQUIREMENTS["oauth_state_nonces"])
    assert {"key_version", "ciphertext_b64"}.issubset(HEAD_SCHEMA_REQUIREMENTS["connector_credentials"])
    assert {"status", "publish_attempts"}.issubset(HEAD_SCHEMA_REQUIREMENTS["task_outbox"])
    assert {"provenance_json", "freshness_json"}.issubset(HEAD_SCHEMA_REQUIREMENTS["intelligence_runs"])
    assert {"access_restriction_reason", "access_restricted_at"}.issubset(HEAD_SCHEMA_REQUIREMENTS["users"])
    assert {
        "user_id", "token_hash", "token_expires_at", "status", "submitted_at", "reviewed_at",
    }.issubset(HEAD_SCHEMA_REQUIREMENTS["account_access_appeals"])
    assert {"key", "value_json", "updated_at"}.issubset(HEAD_SCHEMA_REQUIREMENTS["field_runtime_flags"])
    assert {"worker_id", "git_sha", "last_heartbeat_at"}.issubset(HEAD_SCHEMA_REQUIREMENTS["field_worker_heartbeats"])

    assert {
        "scope_key", "revision", "state_json", "unknowns_json", "conflicts_json", "state_hash",
    }.issubset(HEAD_SCHEMA_REQUIREMENTS["field_states"])
    assert {
        "field_state_id", "revision", "state_hash", "previous_revision_hash", "evidence_ids_json",
    }.issubset(HEAD_SCHEMA_REQUIREMENTS["field_state_revisions"])
    assert {
        "field_state_revision_id", "evidence_graph_json", "science_trace_json", "decision_json",
        "snapshot_hash", "idempotency_key",
    }.issubset(HEAD_SCHEMA_REQUIREMENTS["decision_snapshots"])
    assert {
        "decision_snapshot_id", "state", "version", "requires_human_approval", "verification_status", "outcome",
    }.issubset(HEAD_SCHEMA_REQUIREMENTS["decision_lifecycles"])
    assert {
        "lifecycle_id", "sequence", "from_state", "to_state", "event_type", "actor_type", "idempotency_key",
    }.issubset(HEAD_SCHEMA_REQUIREMENTS["decision_lifecycle_events"])
