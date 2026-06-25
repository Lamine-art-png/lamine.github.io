"""Add enterprise tables for ingestion, models, and API keys

Revision ID: 001
Revises:
Create Date: 2025-01-15

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _column_names(table_name: str) -> set[str]:
    if not _table_exists(table_name):
        return set()
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _create_table_if_missing(table_name: str, *columns: sa.Column, **kwargs: object) -> None:
    if not _table_exists(table_name):
        op.create_table(table_name, *columns, **kwargs)


def _create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: list[str],
    **kwargs: object,
) -> None:
    if not _table_exists(table_name) or _index_exists(table_name, index_name):
        return
    if not set(columns).issubset(_column_names(table_name)):
        return
    op.create_index(index_name, table_name, columns, **kwargs)


def upgrade() -> None:
    # Adopt existing Render preview databases whose base tables were created
    # before alembic_version was stamped, while still supporting clean databases.
    _create_table_if_missing(
        'tenants',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('tier', sa.String(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    _create_index_if_missing('ix_tenants_id', 'tenants', ['id'])

    _create_table_if_missing(
        'blocks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('area_ha', sa.Float(), nullable=False),
        sa.Column('crop_type', sa.String(), nullable=True),
        sa.Column('soil_type', sa.String(), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('water_budget_allocated', sa.Float(), nullable=True),
        sa.Column('water_budget_used', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    _create_index_if_missing('ix_blocks_id', 'blocks', ['id'])
    _create_index_if_missing('ix_blocks_tenant_id', 'blocks', ['tenant_id'])

    # Create ingestion_runs table
    _create_table_if_missing(
        'ingestion_runs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('field_id', sa.String(), nullable=True),
        sa.Column('source_type', sa.String(), nullable=False),
        sa.Column('source_uri', sa.String(), nullable=False),
        sa.Column('source_checksum', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('data_type', sa.String(), nullable=False),
        sa.Column('rows_total', sa.Integer(), server_default='0'),
        sa.Column('rows_accepted', sa.Integer(), server_default='0'),
        sa.Column('rows_rejected', sa.Integer(), server_default='0'),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_details', sa.Text(), nullable=True),
        sa.Column('batch_id', sa.String(), nullable=True),
        sa.Column('triggered_by', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['field_id'], ['blocks.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    _create_index_if_missing('ix_ingestion_runs_id', 'ingestion_runs', ['id'])
    _create_index_if_missing('ix_ingestion_runs_tenant_id', 'ingestion_runs', ['tenant_id'])
    _create_index_if_missing('ix_ingestion_runs_field_id', 'ingestion_runs', ['field_id'])
    _create_index_if_missing('ix_ingestion_runs_status', 'ingestion_runs', ['status'])
    _create_index_if_missing('ix_ingestion_runs_started_at', 'ingestion_runs', ['started_at'])
    _create_index_if_missing('ix_ingestion_runs_batch_id', 'ingestion_runs', ['batch_id'])
    _create_index_if_missing('ix_ingestion_status_time', 'ingestion_runs', ['status', 'started_at'])
    _create_index_if_missing('ix_ingestion_tenant_time', 'ingestion_runs', ['tenant_id', 'started_at'])
    _create_index_if_missing('ix_ingestion_batch', 'ingestion_runs', ['batch_id', 'started_at'])

    # Create api_keys table
    _create_table_if_missing(
        'api_keys',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('key_hash', sa.String(), nullable=False),
        sa.Column('key_prefix', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('role', sa.String(), server_default='analyst', nullable=False),
        sa.Column('field_restrictions', sa.JSON(), nullable=True),
        sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('usage_count', sa.String(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_by', sa.String(), nullable=True),
        sa.Column('revoke_reason', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_hash')
    )
    _create_index_if_missing('ix_api_keys_id', 'api_keys', ['id'])
    _create_index_if_missing('ix_api_keys_tenant_id', 'api_keys', ['tenant_id'])
    _create_index_if_missing('ix_api_keys_key_hash', 'api_keys', ['key_hash'], unique=True)
    _create_index_if_missing('ix_api_keys_active', 'api_keys', ['active'])
    _create_index_if_missing('ix_api_keys_created_at', 'api_keys', ['created_at'])
    _create_index_if_missing('ix_api_keys_expires_at', 'api_keys', ['expires_at'])
    _create_index_if_missing('ix_apikey_tenant_active', 'api_keys', ['tenant_id', 'active'])
    _create_index_if_missing('ix_apikey_expires', 'api_keys', ['expires_at', 'active'])

    # Create model_runs table
    _create_table_if_missing(
        'model_runs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('model_name', sa.String(), nullable=False),
        sa.Column('version', sa.String(), nullable=False),
        sa.Column('algorithm', sa.String(), nullable=False),
        sa.Column('dataset_hash', sa.String(), nullable=False),
        sa.Column('dataset_size', sa.String(), server_default='0'),
        sa.Column('train_start_date', sa.DateTime(), nullable=True),
        sa.Column('train_end_date', sa.DateTime(), nullable=True),
        sa.Column('crop_type', sa.String(), nullable=True),
        sa.Column('region', sa.String(), nullable=True),
        sa.Column('season', sa.String(), nullable=True),
        sa.Column('hyperparameters', sa.JSON(), nullable=False),
        sa.Column('mae', sa.Float(), nullable=True),
        sa.Column('rmse', sa.Float(), nullable=True),
        sa.Column('r2_score', sa.Float(), nullable=True),
        sa.Column('metrics_json', sa.JSON(), nullable=True),
        sa.Column('feature_importances', sa.JSON(), nullable=True),
        sa.Column('artifact_backend', sa.String(), nullable=False),
        sa.Column('artifact_path', sa.String(), nullable=False),
        sa.Column('artifact_checksum', sa.String(), nullable=True),
        sa.Column('artifact_size_bytes', sa.String(), nullable=True),
        sa.Column('status', sa.String(), server_default='training', nullable=False),
        sa.Column('promoted_at', sa.DateTime(), nullable=True),
        sa.Column('promoted_by', sa.String(), nullable=True),
        sa.Column('training_started_at', sa.DateTime(), nullable=False),
        sa.Column('training_completed_at', sa.DateTime(), nullable=True),
        sa.Column('training_duration_seconds', sa.String(), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    _create_index_if_missing('ix_model_runs_id', 'model_runs', ['id'])
    _create_index_if_missing('ix_model_runs_model_name', 'model_runs', ['model_name'])
    _create_index_if_missing('ix_model_runs_version', 'model_runs', ['version'])
    _create_index_if_missing('ix_model_runs_dataset_hash', 'model_runs', ['dataset_hash'])
    _create_index_if_missing('ix_model_runs_crop_type', 'model_runs', ['crop_type'])
    _create_index_if_missing('ix_model_runs_region', 'model_runs', ['region'])
    _create_index_if_missing('ix_model_runs_status', 'model_runs', ['status'])
    _create_index_if_missing('ix_model_runs_promoted_at', 'model_runs', ['promoted_at'])
    _create_index_if_missing('ix_model_runs_training_started_at', 'model_runs', ['training_started_at'])
    _create_index_if_missing('ix_modelrun_status_name', 'model_runs', ['status', 'model_name'])
    _create_index_if_missing('ix_modelrun_crop_region', 'model_runs', ['crop_type', 'region'])
    _create_index_if_missing('ix_modelrun_version', 'model_runs', ['model_name', 'version'])

    # Create invitation_tokens table
    _create_table_if_missing(
        'invitation_tokens',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('token_hash', sa.String(), nullable=False),
        sa.Column('role', sa.String(), server_default='analyst', nullable=False),
        sa.Column('max_uses', sa.String(), server_default='1'),
        sa.Column('uses_count', sa.String(), server_default='0'),
        sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('redeemed_at', sa.DateTime(), nullable=True),
        sa.Column('redeemed_by', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash')
    )
    _create_index_if_missing('ix_invitation_tokens_id', 'invitation_tokens', ['id'])
    _create_index_if_missing('ix_invitation_tokens_tenant_id', 'invitation_tokens', ['tenant_id'])
    _create_index_if_missing('ix_invitation_tokens_token_hash', 'invitation_tokens', ['token_hash'], unique=True)
    _create_index_if_missing('ix_invitation_tokens_active', 'invitation_tokens', ['active'])
    _create_index_if_missing('ix_invitation_tokens_expires_at', 'invitation_tokens', ['expires_at'])
    _create_index_if_missing('ix_invitation_tenant_active', 'invitation_tokens', ['tenant_id', 'active'])


def downgrade() -> None:
    op.drop_table('invitation_tokens')
    op.drop_table('model_runs')
    op.drop_table('api_keys')
    op.drop_table('ingestion_runs')
