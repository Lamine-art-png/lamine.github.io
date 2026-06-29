"""Add SaaS portal v2 request, onboarding, and conversation tables.

Revision ID: 007_saas_portal_v2
Revises: 006_saas_auth_billing_foundation
Create Date: 2026-06-28
"""
from alembic import op

revision = "007_saas_portal_v2"
down_revision = "006_saas_auth_billing_foundation"
branch_labels = None
depends_on = None


# Render starts the web service with:
#   alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
#
# The first SaaS Portal v2 migration used SQLAlchemy inspection, foreign-key
# constraints, and index creation. On a live Render/Postgres database that can
# wait on locks before Uvicorn binds a port, which makes Render fail the deploy
# with "port scan timed out" even though the Python build itself is valid.
#
# Keep this migration intentionally fast and dependency-light: create the new
# portal tables only, without FK/index DDL. The SQLAlchemy models still describe
# relationships for the app layer. Indexes/constraints can be added later in a
# dedicated online migration after the service is healthy.


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS saas_requests (
            id VARCHAR PRIMARY KEY,
            organization_id VARCHAR,
            workspace_id VARCHAR,
            user_id VARCHAR,
            type VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            priority VARCHAR NOT NULL,
            name VARCHAR,
            email VARCHAR,
            company VARCHAR,
            role VARCHAR,
            subject VARCHAR NOT NULL,
            message VARCHAR NOT NULL,
            source_page VARCHAR,
            notification_status VARCHAR NOT NULL,
            metadata_json JSON,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id VARCHAR PRIMARY KEY,
            organization_id VARCHAR NOT NULL,
            workspace_id VARCHAR,
            user_id VARCHAR NOT NULL,
            title VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_messages (
            id VARCHAR PRIMARY KEY,
            conversation_id VARCHAR NOT NULL,
            organization_id VARCHAR NOT NULL,
            user_id VARCHAR,
            role VARCHAR NOT NULL,
            content VARCHAR NOT NULL,
            artifacts_json JSON,
            citations_json JSON,
            missing_data_json JSON,
            recommended_actions_json JSON,
            created_at TIMESTAMP NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS onboarding_states (
            id VARCHAR PRIMARY KEY,
            organization_id VARCHAR NOT NULL,
            workspace_id VARCHAR,
            user_id VARCHAR NOT NULL,
            current_step VARCHAR NOT NULL,
            selected_plan VARCHAR,
            organization_type VARCHAR,
            acres_or_sites VARCHAR,
            primary_goal VARCHAR,
            completed_steps_json JSON,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            UNIQUE (organization_id, user_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS onboarding_states")
    op.execute("DROP TABLE IF EXISTS conversation_messages")
    op.execute("DROP TABLE IF EXISTS conversations")
    op.execute("DROP TABLE IF EXISTS saas_requests")
