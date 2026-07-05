"""Account recovery tokens and auth versioning.

Revision ID: 010_account_recovery
Revises: 009_telemetry_recommendations
"""
from alembic import op
import sqlalchemy as sa

revision = "010_account_recovery"
down_revision = "009_telemetry_recommendations"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table):
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _index(name, table, columns, unique=False):
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def upgrade():
    if "users" in _tables() and "auth_version" not in _columns("users"):
        op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default=sa.text("0")))

    if "account_recovery_tokens" not in _tables():
        op.create_table(
            "account_recovery_tokens",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    _index("ix_account_recovery_user", "account_recovery_tokens", ["user_id"])
    _index("ix_account_recovery_hash", "account_recovery_tokens", ["token_hash"], unique=True)
    _index("ix_account_recovery_expires", "account_recovery_tokens", ["expires_at"])
    _index("ix_account_recovery_created", "account_recovery_tokens", ["created_at"])
    _index("ix_account_recovery_user_created", "account_recovery_tokens", ["user_id", "created_at"])


def downgrade():
    if "account_recovery_tokens" in _tables():
        op.drop_table("account_recovery_tokens")
    if "users" in _tables() and "auth_version" in _columns("users"):
        op.drop_column("users", "auth_version")
