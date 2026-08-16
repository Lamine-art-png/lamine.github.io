"""Add workspace-scoped Assurance V2 mappings, review, and package provenance.

Revision ID: 030_assurance_intelligence_v2
Revises: 029_platform_cli_device_auth
Create Date: 2026-08-16

The migration is additive. Historical Assurance and Compliance records are
preserved, while the legacy ``tenant_id`` columns become nullable so new Portal
rows can use the authoritative Organization/Workspace identity domain.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "030_assurance_intelligence_v2"
down_revision = "029_platform_cli_device_auth"
branch_labels = None
depends_on = None


SCOPED_TABLES = (
    "assurance_passports",
    "assurance_passport_sections",
    "assurance_evidence_artifacts",
    "assurance_checklist_items",
    "assurance_risk_scores",
    "input_applications",
    "pesticide_applications",
    "fertilizer_applications",
    "harvest_lots",
    "traceability_events",
    "buyer_requirements",
    "assurance_exports",
)


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _tables() -> set[str]:
    return set(_inspector().get_table_names())


def _columns(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {column["name"] for column in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {index["name"] for index in _inspector().get_indexes(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(table) as batch:
                batch.add_column(column)
        else:
            op.add_column(table, column)


def _drop_column(table: str, column: str) -> None:
    if column not in _columns(table):
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.drop_column(column)
    else:
        op.drop_column(table, column)


def _create_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def _drop_index(name: str, table: str) -> None:
    if name in _indexes(table):
        op.drop_index(name, table_name=table)


def _make_legacy_tenant_nullable(table: str) -> None:
    if "tenant_id" not in _columns(table):
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.alter_column("tenant_id", existing_type=sa.String(), nullable=True)
    else:
        op.alter_column(table, "tenant_id", existing_type=sa.String(), nullable=True)


def _restore_legacy_tenant_required_when_safe(table: str) -> None:
    if "tenant_id" not in _columns(table):
        return
    null_count = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {table} WHERE tenant_id IS NULL")).scalar()
    if null_count:
        # A downgrade must never delete Portal-era customer rows merely to make
        # an obsolete legacy constraint fit. The V2-only columns are removed,
        # but nullable ownership remains as the safe compatibility posture.
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.alter_column("tenant_id", existing_type=sa.String(), nullable=False)
    else:
        op.alter_column(table, "tenant_id", existing_type=sa.String(), nullable=False)


def _add_scope(table: str) -> None:
    _make_legacy_tenant_nullable(table)
    _add_column(table, sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT", name=f"fk_{table}_organization_id"), nullable=True))
    _add_column(table, sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT", name=f"fk_{table}_workspace_id"), nullable=True))
    _create_index(f"ix_{table}_organization_id", table, ["organization_id"])
    _create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])


def upgrade() -> None:
    for table in SCOPED_TABLES:
        _add_scope(table)

    _create_index(
        "uq_assurance_section_workspace_type", "assurance_passport_sections",
        ["organization_id", "workspace_id", "passport_id", "section_type"], unique=True,
    )
    _create_index(
        "uq_assurance_checklist_workspace_requirement", "assurance_checklist_items",
        ["organization_id", "workspace_id", "passport_id", "rule_pack_id", "requirement_key"], unique=True,
    )
    _create_index(
        "uq_harvest_lot_workspace_code", "harvest_lots",
        ["organization_id", "workspace_id", "passport_id", "lot_code"], unique=True,
    )

    _add_column("assurance_passports", sa.Column("entity_type", sa.String(), nullable=False, server_default="farm"))
    _add_column("assurance_passports", sa.Column("entity_id", sa.String(), nullable=True))
    _create_index("ix_assurance_passports_entity_type", "assurance_passports", ["entity_type"])
    _create_index("ix_assurance_passports_entity_id", "assurance_passports", ["entity_id"])

    evidence_columns = (
        sa.Column("canonical_evidence_id", sa.String(), sa.ForeignKey("evidence_records.id", ondelete="RESTRICT", name="fk_assurance_evidence_canonical_id"), nullable=True),
        sa.Column("field_observation_id", sa.String(), sa.ForeignKey("field_observations.id", ondelete="RESTRICT", name="fk_assurance_evidence_observation_id"), nullable=True),
        sa.Column("source_kind", sa.String(), nullable=False, server_default="legacy"),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("mapping_status", sa.String(), nullable=False, server_default="mapped"),
        sa.Column("event_timestamp", sa.DateTime(), nullable=True),
        sa.Column("ingestion_timestamp", sa.DateTime(), nullable=True),
        sa.Column("reporting_period", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("data_quality", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("stale_after", sa.DateTime(), nullable=True),
        sa.Column("unresolved_issue", sa.Text(), nullable=True),
    )
    for column in evidence_columns:
        _add_column("assurance_evidence_artifacts", column)
        if column.name not in {"confidence", "unresolved_issue"}:
            _create_index(f"ix_assurance_evidence_artifacts_{column.name}", "assurance_evidence_artifacts", [column.name])
    _create_index(
        "uq_assurance_evidence_canonical_mapping",
        "assurance_evidence_artifacts",
        ["organization_id", "workspace_id", "passport_id", "source_kind", "source_id", "evidence_type"],
        unique=True,
    )

    for column in (
        sa.Column("blocking", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.true()),
    ):
        _add_column("assurance_checklist_items", column)
    _create_index("ix_assurance_checklist_items_blocking", "assurance_checklist_items", ["blocking"])
    _create_index("ix_assurance_checklist_items_review_required", "assurance_checklist_items", ["review_required"])

    for column in (
        sa.Column("package_type", sa.String(), nullable=False, server_default="assurance_passport"),
        sa.Column("package_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("package_status", sa.String(), nullable=False, server_default="draft_only"),
        sa.Column("generated_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_assurance_exports_generated_by"), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("rule_pack_versions", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("evidence_references", sa.JSON(), nullable=False, server_default="[]"),
    ):
        _add_column("assurance_exports", column)
    for name in ("package_type", "package_status", "generated_by_user_id", "idempotency_key"):
        _create_index(f"ix_assurance_exports_{name}", "assurance_exports", [name])
    _create_index(
        "uq_assurance_package_version",
        "assurance_exports",
        ["organization_id", "passport_id", "package_type", "package_version"],
        unique=True,
    )

    if "assurance_review_events" not in _tables():
        op.create_table(
            "assurance_review_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("passport_id", sa.String(), sa.ForeignKey("assurance_passports.id", ondelete="CASCADE"), nullable=False),
            sa.Column("evidence_artifact_id", sa.String(), sa.ForeignKey("assurance_evidence_artifacts.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("checklist_item_id", sa.String(), sa.ForeignKey("assurance_checklist_items.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("actor_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_label", sa.String(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("previous_state", sa.JSON(), nullable=False),
            sa.Column("next_state", sa.JSON(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for name in ("tenant_id", "organization_id", "workspace_id", "passport_id", "evidence_artifact_id", "checklist_item_id", "action", "actor_user_id", "created_at"):
            _create_index(f"ix_assurance_review_events_{name}", "assurance_review_events", [name])

    if "assurance_audit_events" not in _tables():
        op.create_table(
            "assurance_audit_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("passport_id", sa.String(), sa.ForeignKey("assurance_passports.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("actor_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_system", sa.String(), nullable=False, server_default="assurance"),
            sa.Column("subject_type", sa.String(), nullable=True),
            sa.Column("subject_id", sa.String(), nullable=True),
            sa.Column("rule_pack_versions", sa.JSON(), nullable=False),
            sa.Column("details_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for name in ("tenant_id", "organization_id", "workspace_id", "passport_id", "event_type", "actor_user_id", "source_system", "subject_type", "subject_id", "created_at"):
            _create_index(f"ix_assurance_audit_events_{name}", "assurance_audit_events", [name])
        _create_index("ix_assurance_audit_passport_time", "assurance_audit_events", ["passport_id", "created_at"])


def downgrade() -> None:
    for table in ("assurance_audit_events", "assurance_review_events"):
        if table in _tables():
            op.drop_table(table)

    export_columns = (
        "evidence_references", "rule_pack_versions", "idempotency_key", "generated_by_user_id",
        "package_status", "package_version", "package_type",
    )
    evidence_columns = (
        "unresolved_issue", "stale_after", "data_quality", "confidence", "reporting_period",
        "ingestion_timestamp", "event_timestamp", "mapping_status", "source_id", "source_kind",
        "field_observation_id", "canonical_evidence_id",
    )
    checklist_columns = ("review_required", "explanation", "blocking")

    _drop_index("uq_assurance_package_version", "assurance_exports")
    for name in ("package_type", "package_status", "generated_by_user_id", "idempotency_key"):
        _drop_index(f"ix_assurance_exports_{name}", "assurance_exports")
    for column in export_columns:
        _drop_column("assurance_exports", column)

    _drop_index("uq_assurance_evidence_canonical_mapping", "assurance_evidence_artifacts")
    for name in evidence_columns:
        _drop_index(f"ix_assurance_evidence_artifacts_{name}", "assurance_evidence_artifacts")
    for column in evidence_columns:
        _drop_column("assurance_evidence_artifacts", column)
    for column in checklist_columns:
        _drop_index(f"ix_assurance_checklist_items_{column}", "assurance_checklist_items")
        _drop_column("assurance_checklist_items", column)

    for column in ("entity_id", "entity_type"):
        _drop_index(f"ix_assurance_passports_{column}", "assurance_passports")
        _drop_column("assurance_passports", column)

    for name, table in (
        ("uq_assurance_section_workspace_type", "assurance_passport_sections"),
        ("uq_assurance_checklist_workspace_requirement", "assurance_checklist_items"),
        ("uq_harvest_lot_workspace_code", "harvest_lots"),
    ):
        _drop_index(name, table)

    for table in reversed(SCOPED_TABLES):
        for column in ("workspace_id", "organization_id"):
            _drop_index(f"ix_{table}_{column}", table)
            _drop_column(table, column)
        _restore_legacy_tenant_required_when_safe(table)
