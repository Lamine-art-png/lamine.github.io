"""Add SaaS portal v2 request, onboarding, and conversation tables.

Revision ID: 007_saas_portal_v2
Revises: 006_saas_auth_billing_foundation
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa

revision = "007_saas_portal_v2"
down_revision = "006_saas_auth_billing_foundation"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _create_index(name: str, table: str, columns: list[str], unique: bool = False) -> None:
    existing = {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    if not _has_table("saas_requests"):
        op.create_table(
            "saas_requests",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=True),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=True),
            sa.Column("type", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("priority", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("email", sa.String(), nullable=True),
            sa.Column("company", sa.String(), nullable=True),
            sa.Column("role", sa.String(), nullable=True),
            sa.Column("subject", sa.String(), nullable=False),
            sa.Column("message", sa.String(), nullable=False),
            sa.Column("source_page", sa.String(), nullable=True),
            sa.Column("notification_status", sa.String(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, columns in {
        "ix_saas_requests_id": ["id"],
        "ix_saas_requests_organization_id": ["organization_id"],
        "ix_saas_requests_workspace_id": ["workspace_id"],
        "ix_saas_requests_user_id": ["user_id"],
        "ix_saas_requests_type": ["type"],
        "ix_saas_requests_status": ["status"],
        "ix_saas_requests_priority": ["priority"],
        "ix_saas_requests_created_at": ["created_at"],
    }.items():
        _create_index(name, "saas_requests", columns)

    if not _has_table("conversations"):
        op.create_table(
            "conversations",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, columns in {
        "ix_conversations_id": ["id"],
        "ix_conversations_organization_id": ["organization_id"],
        "ix_conversations_workspace_id": ["workspace_id"],
        "ix_conversations_user_id": ["user_id"],
        "ix_conversations_status": ["status"],
        "ix_conversations_created_at": ["created_at"],
    }.items():
        _create_index(name, "conversations", columns)

    if not _has_table("conversation_messages"):
        op.create_table(
            "conversation_messages",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("conversation_id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=True),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("content", sa.String(), nullable=False),
            sa.Column("artifacts_json", sa.JSON(), nullable=True),
            sa.Column("citations_json", sa.JSON(), nullable=True),
            sa.Column("missing_data_json", sa.JSON(), nullable=True),
            sa.Column("recommended_actions_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, columns in {
        "ix_conversation_messages_id": ["id"],
        "ix_conversation_messages_conversation_id": ["conversation_id"],
        "ix_conversation_messages_organization_id": ["organization_id"],
        "ix_conversation_messages_user_id": ["user_id"],
        "ix_conversation_messages_role": ["role"],
        "ix_conversation_messages_created_at": ["created_at"],
    }.items():
        _create_index(name, "conversation_messages", columns)

    if not _has_table("onboarding_states"):
        op.create_table(
            "onboarding_states",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("current_step", sa.String(), nullable=False),
            sa.Column("selected_plan", sa.String(), nullable=True),
            sa.Column("organization_type", sa.String(), nullable=True),
            sa.Column("acres_or_sites", sa.String(), nullable=True),
            sa.Column("primary_goal", sa.String(), nullable=True),
            sa.Column("completed_steps_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "user_id", name="uq_onboarding_org_user"),
        )
    for name, columns in {
        "ix_onboarding_states_id": ["id"],
        "ix_onboarding_states_organization_id": ["organization_id"],
        "ix_onboarding_states_workspace_id": ["workspace_id"],
        "ix_onboarding_states_user_id": ["user_id"],
        "ix_onboarding_states_created_at": ["created_at"],
    }.items():
        _create_index(name, "onboarding_states", columns)


def downgrade() -> None:
    op.drop_table("onboarding_states")
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
    op.drop_table("saas_requests")
