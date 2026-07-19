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


def test_head_contract_covers_security_queue_and_provenance_layers():
    assert HEAD_ALEMBIC_REVISION == "021_platform_api_hardening"
    assert {"nonce_hash", "consumed_at"}.issubset(HEAD_SCHEMA_REQUIREMENTS["oauth_state_nonces"])
    assert {"key_version", "ciphertext_b64"}.issubset(HEAD_SCHEMA_REQUIREMENTS["connector_credentials"])
    assert {"status", "publish_attempts"}.issubset(HEAD_SCHEMA_REQUIREMENTS["task_outbox"])
    assert {"provenance_json", "freshness_json"}.issubset(HEAD_SCHEMA_REQUIREMENTS["intelligence_runs"])
