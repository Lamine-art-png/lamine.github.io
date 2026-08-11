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


def test_head_contract_covers_security_queue_provenance_appeals_field_intelligence_and_platform_api():
    assert HEAD_ALEMBIC_REVISION == "027_merge_fi_and_platform_api"
    assert {"nonce_hash", "consumed_at"}.issubset(HEAD_SCHEMA_REQUIREMENTS["oauth_state_nonces"])
    assert {"key_version", "ciphertext_b64"}.issubset(HEAD_SCHEMA_REQUIREMENTS["connector_credentials"])
    assert {"status", "publish_attempts"}.issubset(HEAD_SCHEMA_REQUIREMENTS["task_outbox"])
    assert {"provenance_json", "freshness_json"}.issubset(HEAD_SCHEMA_REQUIREMENTS["intelligence_runs"])
    assert {"access_restriction_reason", "access_restricted_at"}.issubset(HEAD_SCHEMA_REQUIREMENTS["users"])
    # Field Intelligence launch tail
    assert {"key", "value_json", "updated_at"}.issubset(HEAD_SCHEMA_REQUIREMENTS["field_runtime_flags"])
    assert {"worker_id", "git_sha", "last_heartbeat_at"}.issubset(
        HEAD_SCHEMA_REQUIREMENTS["field_worker_heartbeats"]
    )
    # Platform API operations tail
    assert {"id", "organization_id", "application_type", "status"}.issubset(
        HEAD_SCHEMA_REQUIREMENTS["platform_api_applications"]
    )
    assert {"id", "organization_id", "plan_id", "status", "status_slot"}.issubset(
        HEAD_SCHEMA_REQUIREMENTS["platform_api_subscriptions"]
    )
    assert {
        "user_id",
        "token_hash",
        "token_expires_at",
        "status",
        "submitted_at",
        "reviewed_at",
    }.issubset(HEAD_SCHEMA_REQUIREMENTS["account_access_appeals"])
