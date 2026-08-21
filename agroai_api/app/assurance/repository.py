"""Legacy-tenant and Portal-workspace persistence for Assurance Passports."""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.assurance.models import (
    AssuranceChecklistItem,
    AssuranceAuditEvent,
    AssuranceEvidenceArtifact,
    AssuranceExport,
    AssurancePassport,
    AssurancePassportSection,
    AssuranceRiskScore,
    AssuranceReviewEvent,
    FertilizerApplication,
    HarvestLot,
    InputApplication,
    PesticideApplication,
    RulePack,
    TraceabilityEvent,
)
from app.assurance.rule_packs import (
    ASSURANCE_DISCLAIMER,
    CUSTOMER_RULE_PACK_IDS,
    DEFAULT_RULE_PACKS,
    checklist_for,
    rule_pack_versions,
    validate_rule_pack_ids,
)
from app.models.field_intelligence import FieldObservation, FieldObservationAsset
from app.models.operational_records import DataSource, EvidenceRecord, GeneratedArtifact, IngestionJob, IntelligenceRun
from app.services.assurance_artifacts import stage_assurance_artifact
from app.models.compliance import (
    ComplianceEvidence,
    ComplianceJurisdiction,
    ComplianceMeasurement,
    ComplianceMeter,
    ComplianceParcel,
    ComplianceWaterBudget,
    ComplianceWell,
)


TRUTH_LABELS = {"measured", "reported", "estimated", "calculated", "AI-inferred"}
SECTION_TYPES = ["farm_summary", "water_proof", "input_proof", "operational_proof", "traceability_proof", "readiness_score", "risk_score"]
REVIEW_ACTIONS = {
    "accept_mapping": "accepted",
    "reject_mapping": "rejected",
    "correct_metadata": "reviewer_required",
    "request_additional_proof": "reviewer_required",
    "mark_not_applicable": "not_applicable",
    "reopen": "unreviewed",
}
PACKAGE_TYPES = {
    "assurance_passport",
    "water_evidence_pack",
    "buyer_proof_pack",
    "input_application_record_pack",
    "operational_execution_pack",
}


def _dt(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _iso(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _checksum(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _as_dict(row: Any) -> dict[str, Any]:
    data = {column.name: _iso(getattr(row, column.name)) for column in row.__table__.columns}
    if "metadata_json" in data:
        data["metadata"] = data.pop("metadata_json") or {}
    return data


class AssuranceRepository:
    def __init__(
        self,
        db: Session,
        tenant_id: str | None = None,
        *,
        organization_id: str | None = None,
        workspace_id: str | None = None,
        actor_user_id: str | None = None,
    ):
        if bool(tenant_id) == bool(organization_id):
            raise ValueError("exactly one legacy tenant_id or organization_id is required")
        if organization_id and not workspace_id:
            raise ValueError("workspace_id is required for Portal Assurance")
        self.db = db
        self.tenant_id = tenant_id
        self.organization_id = organization_id
        self.workspace_id = workspace_id
        self.actor_user_id = actor_user_id
        self.owner_id = str(organization_id or tenant_id)

    @classmethod
    def for_workspace(
        cls,
        db: Session,
        *,
        organization_id: str,
        workspace_id: str,
        actor_user_id: str,
    ) -> "AssuranceRepository":
        return cls(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
        )

    def _scope_values(self) -> dict[str, str | None]:
        return {
            "tenant_id": self.tenant_id,
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
        }

    def _scope_query(self, model: Any):
        query = self.db.query(model)
        if self.organization_id:
            return query.filter(
                model.organization_id == self.organization_id,
                model.workspace_id == self.workspace_id,
            )
        return query.filter(model.tenant_id == self.tenant_id)

    def _audit(
        self,
        passport_id: str,
        event_type: str,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        details: dict[str, Any] | None = None,
        source_system: str = "assurance",
    ) -> None:
        passport = self._passport(passport_id)
        self.db.add(AssuranceAuditEvent(
            id=f"aae-{uuid.uuid4().hex[:16]}",
            **self._scope_values(),
            passport_id=passport_id,
            event_type=event_type,
            actor_user_id=self.actor_user_id,
            source_system=source_system,
            subject_type=subject_type,
            subject_id=subject_id,
            rule_pack_versions=rule_pack_versions(passport.rule_pack_ids),
            details_json=details or {},
        ))

    def ensure_rule_packs(self) -> None:
        for pack_id, pack in DEFAULT_RULE_PACKS.items():
            if self.db.query(RulePack).filter_by(id=pack_id).first():
                continue
            self.db.add(RulePack(
                id=pack_id,
                scope=pack["scope"],
                version=pack["version"],
                status=pack["status"],
                required_evidence_types=pack["required_evidence_types"],
                checklist=pack["checklist"],
                validation_rules=pack["validation_rules"],
                scoring_weights=pack["scoring_weights"],
                disclaimer_text=pack["disclaimer_text"],
            ))
        self.db.commit()

    def _passport(self, passport_id: str) -> AssurancePassport:
        row = self._scope_query(AssurancePassport).filter(AssurancePassport.id == passport_id).first()
        if not row:
            raise KeyError("Passport not found")
        return row

    def create_passport(self, payload: dict[str, Any]) -> dict[str, Any]:
        selected_pack_ids = payload.get("rule_pack_ids")
        if selected_pack_ids is None:
            selected_pack_ids = CUSTOMER_RULE_PACK_IDS if self.organization_id else [
                "waterops_generic_v0_1",
                "eudr_supplier_readiness_v0_1",
                "buyer_input_records_v0_1",
                "farm_finance_risk_pack_v0_1",
            ]
        pack_ids = validate_rule_pack_ids(selected_pack_ids)
        passport = AssurancePassport(
            id=payload.get("id") or f"ap-{uuid.uuid4().hex[:12]}",
            **self._scope_values(),
            entity_type=payload.get("entity_type") or "farm",
            entity_id=payload.get("entity_id"),
            farm_name=payload["farm_name"],
            farm_location=payload.get("farm_location"),
            crop=payload.get("crop"),
            season=payload.get("season"),
            reporting_period=str(payload.get("reporting_period") or datetime.utcnow().year),
            status="draft",
            rule_pack_ids=pack_ids,
            jurisdiction_id=payload.get("jurisdiction_id"),
            parcel_ids=payload.get("parcel_ids") or [],
            metadata_json=payload.get("metadata") or {},
        )
        self.db.add(passport)
        self.db.flush()
        for section_type in SECTION_TYPES:
            self.db.add(AssurancePassportSection(
                id=f"aps-{uuid.uuid4().hex[:12]}",
                **self._scope_values(),
                passport_id=passport.id,
                section_type=section_type,
                status="pending",
                readiness_score=0.0,
                payload={},
            ))
        for item in checklist_for(pack_ids):
            self.db.add(AssuranceChecklistItem(
                id=f"aci-{uuid.uuid4().hex[:12]}",
                **self._scope_values(),
                passport_id=passport.id,
                rule_pack_id=item["rule_pack_id"],
                requirement_key=item["key"],
                section_type=item["section"],
                status="missing",
                severity=item.get("severity", "required"),
                blocking=bool(item.get("blocking", True)),
                explanation=item.get("explanation"),
                review_required=bool(item.get("review_required", True)),
                evidence_artifact_ids=[],
                notes="Evidence not attached yet.",
            ))
        self.db.flush()
        self._audit(
            passport.id,
            "passport_created",
            subject_type="passport",
            subject_id=passport.id,
            details={"rule_pack_ids": pack_ids, "entity_type": passport.entity_type, "entity_id": passport.entity_id},
        )
        self.db.commit()
        return self.get_passport(passport.id)

    def list_passports(self) -> list[dict[str, Any]]:
        rows = self._scope_query(AssurancePassport).order_by(AssurancePassport.updated_at.desc()).all()
        return [
            {
                **_as_dict(row),
                "readiness": self.readiness(row.id, persist=False),
            }
            for row in rows
        ]

    def get_passport(self, passport_id: str) -> dict[str, Any]:
        passport = self._passport(passport_id)
        return {
            "passport": _as_dict(passport),
            "sections": [_as_dict(row) for row in self._scope_query(AssurancePassportSection).filter_by(passport_id=passport_id).all()],
            "evidence": [self.evidence_payload(row) for row in self._scope_query(AssuranceEvidenceArtifact).filter_by(passport_id=passport_id).all()],
            "input_applications": [_as_dict(row) for row in self._scope_query(InputApplication).filter_by(passport_id=passport_id).all()],
            "harvest_lots": [_as_dict(row) for row in self._scope_query(HarvestLot).filter_by(passport_id=passport_id).all()],
            "traceability_events": [_as_dict(row) for row in self._scope_query(TraceabilityEvent).filter_by(passport_id=passport_id).all()],
            "latest_readiness": self.readiness(passport_id, persist=False),
            "disclaimer": ASSURANCE_DISCLAIMER,
        }

    def add_evidence(self, passport_id: str, payload: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        """Preserve the historical metadata-upload API as a legacy mapping.

        V2 portal callers use :meth:`map_evidence`, which references an existing
        canonical EvidenceRecord or Field Observation rather than copying it.
        """
        self._passport(passport_id)
        truth_label = payload.get("truth_label", "reported")
        if truth_label not in TRUTH_LABELS:
            raise ValueError(f"truth_label must be one of {sorted(TRUTH_LABELS)}")
        compliance_evidence_id = payload.get("compliance_evidence_id")
        if compliance_evidence_id:
            exists = self.db.query(ComplianceEvidence).filter_by(id=compliance_evidence_id, tenant_id=self.owner_id).first()
            if not exists:
                raise ValueError("compliance_evidence_id does not belong to authenticated tenant")
        row = AssuranceEvidenceArtifact(
            id=payload.get("id") or f"aev-{uuid.uuid4().hex[:12]}",
            **self._scope_values(),
            passport_id=passport_id,
            compliance_evidence_id=compliance_evidence_id,
            workbench_artifact_id=payload.get("workbench_artifact_id"),
            source_kind=payload.get("source_kind") or "legacy",
            source_id=payload.get("source_id") or compliance_evidence_id or payload.get("workbench_artifact_id"),
            evidence_type=payload["evidence_type"],
            proof_domain=payload.get("proof_domain") or payload["evidence_type"],
            file_ref=payload["file_ref"],
            filename=payload.get("filename"),
            content_type=payload.get("content_type"),
            checksum=payload.get("checksum"),
            truth_label=truth_label,
            review_status=payload.get("review_status", "pending_review"),
            mapping_status=payload.get("mapping_status", "mapped"),
            source_system=payload.get("source_system", "uploaded"),
            event_timestamp=_dt(payload.get("event_timestamp")),
            ingestion_timestamp=_dt(payload.get("ingestion_timestamp")) or datetime.utcnow(),
            reporting_period=payload.get("reporting_period"),
            confidence=payload.get("confidence"),
            data_quality=payload.get("data_quality", "unknown"),
            stale_after=_dt(payload.get("stale_after")),
            unresolved_issue=payload.get("unresolved_issue"),
            metadata_json=payload.get("metadata") or {},
        )
        self.db.add(row)
        self.db.flush()
        self._sync_checklist_for_evidence(passport_id, row)
        self._audit(
            passport_id,
            "evidence_mapping_created",
            subject_type="evidence_mapping",
            subject_id=row.id,
            details={"source_kind": row.source_kind, "source_id": row.source_id, "evidence_type": row.evidence_type},
        )
        if commit:
            self.db.commit()
        return self.evidence_payload(row)

    def _sync_checklist_for_evidence(self, passport_id: str, evidence: AssuranceEvidenceArtifact) -> None:
        items = self._scope_query(AssuranceChecklistItem).filter_by(passport_id=passport_id).all()
        specs = checklist_for(self._passport(passport_id).rule_pack_ids)
        for item in items:
            for spec in specs:
                if spec["rule_pack_id"] != item.rule_pack_id or spec["key"] != item.requirement_key:
                    continue
                if evidence.evidence_type in spec.get("evidence_types", []):
                    ids = list(item.evidence_artifact_ids or [])
                    if evidence.id not in ids:
                        ids.append(evidence.id)
                    item.evidence_artifact_ids = ids
                    item.status = "unreviewed" if item.review_required else "mapped"
                    item.notes = "Evidence mapped for reviewer evaluation."
                    item.updated_at = datetime.utcnow()

    def evidence_candidates(self) -> dict[str, Any]:
        if not self.organization_id:
            return {"canonical_evidence": [], "field_observations": []}
        evidence_rows = self.db.query(EvidenceRecord).filter(
            EvidenceRecord.tenant_id == self.organization_id,
            EvidenceRecord.workspace_id == self.workspace_id,
        ).order_by(EvidenceRecord.created_at.desc()).limit(500).all()
        observation_rows = self.db.query(FieldObservation).filter(
            FieldObservation.tenant_id == self.organization_id,
            FieldObservation.workspace_id == self.workspace_id,
            FieldObservation.status != "deleted",
        ).order_by(FieldObservation.created_at.desc()).limit(500).all()
        return {
            "canonical_evidence": [self._canonical_evidence_payload(row) for row in evidence_rows],
            "field_observations": [self._field_observation_payload(row) for row in observation_rows],
        }

    def _canonical_evidence_payload(self, row: EvidenceRecord) -> dict[str, Any]:
        source = self.db.get(DataSource, row.data_source_id) if row.data_source_id else None
        return {
            "source_kind": "canonical_evidence",
            "source_id": row.id,
            "evidence_type": row.evidence_type,
            "title": row.title,
            "summary": row.summary,
            "occurred_at": _iso(row.occurred_at),
            "ingested_at": _iso(row.created_at),
            "confidence": row.confidence,
            "quality_status": row.quality_status,
            "citation_label": row.citation_label,
            "field_id": row.field_id,
            "block_id": row.block_id,
            "data_source": {
                "id": source.id,
                "source_type": source.source_type,
                "provider": source.provider,
                "filename": source.filename,
                "content_type": source.content_type,
                "content_sha256": source.content_sha256,
            } if source and source.tenant_id == self.organization_id and source.workspace_id == self.workspace_id else None,
        }

    def _field_observation_payload(self, row: FieldObservation) -> dict[str, Any]:
        assets = self.db.query(FieldObservationAsset).filter(
            FieldObservationAsset.tenant_id == self.organization_id,
            FieldObservationAsset.workspace_id == self.workspace_id,
            FieldObservationAsset.observation_id == row.id,
            FieldObservationAsset.status == "stored",
        ).all()
        return {
            "source_kind": "field_observation",
            "source_id": row.id,
            "evidence_type": "field_observation",
            "title": row.summary or row.event_type or "Field observation",
            "summary": row.summary,
            "occurred_at": _iso(row.occurred_at or row.observed_at),
            "ingested_at": _iso(row.created_at),
            "confidence": row.confidence,
            "quality_status": "review_required" if row.status == "needs_review" else "usable",
            "field_id": row.field_id,
            "block_id": row.block_id,
            "event_type": row.event_type,
            # Reference the authoritative media rows; do not duplicate binary
            # bytes or leak their private object keys into Assurance payloads.
            "assets": [
                {"id": asset.id, "kind": asset.kind, "filename": asset.filename, "content_type": asset.content_type, "checksum": asset.content_sha256}
                for asset in assets
            ],
        }

    def map_evidence(self, passport_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._passport(passport_id)
        if not self.organization_id:
            raise ValueError("canonical evidence mapping requires Portal workspace scope")
        source_kind = str(payload.get("source_kind") or "")
        source_id = str(payload.get("source_id") or "")
        if source_kind == "canonical_evidence":
            source = self.db.query(EvidenceRecord).filter(
                EvidenceRecord.id == source_id,
                EvidenceRecord.tenant_id == self.organization_id,
                EvidenceRecord.workspace_id == self.workspace_id,
            ).first()
            if not source:
                raise KeyError("Evidence source not found")
            source_payload = self._canonical_evidence_payload(source)
            canonical_id, observation_id = source.id, None
            file_ref = f"evidence_record://{source.id}"
            source_system = "evidence_records"
        elif source_kind == "field_observation":
            source = self.db.query(FieldObservation).filter(
                FieldObservation.id == source_id,
                FieldObservation.tenant_id == self.organization_id,
                FieldObservation.workspace_id == self.workspace_id,
                FieldObservation.status != "deleted",
            ).first()
            if not source:
                raise KeyError("Evidence source not found")
            source_payload = self._field_observation_payload(source)
            canonical_id, observation_id = None, source.id
            file_ref = f"field_observation://{source.id}"
            source_system = "field_intelligence"
        else:
            raise ValueError("source_kind must be canonical_evidence or field_observation")

        evidence_type = str(payload.get("evidence_type") or source_payload["evidence_type"])
        existing = self._scope_query(AssuranceEvidenceArtifact).filter_by(
            passport_id=passport_id,
            source_kind=source_kind,
            source_id=source_id,
            evidence_type=evidence_type,
        ).first()
        if existing:
            return self.evidence_payload(existing)
        truth_label = str(payload.get("truth_label") or ("AI-inferred" if source_kind == "field_observation" else "reported"))
        if truth_label not in TRUTH_LABELS:
            raise ValueError(f"truth_label must be one of {sorted(TRUTH_LABELS)}")
        occurred_at = _dt(source_payload.get("occurred_at"))
        stale_after = _dt(payload.get("stale_after")) or (occurred_at + timedelta(days=365) if occurred_at else None)
        row = AssuranceEvidenceArtifact(
            id=f"aev-{uuid.uuid4().hex[:12]}",
            **self._scope_values(),
            passport_id=passport_id,
            canonical_evidence_id=canonical_id,
            field_observation_id=observation_id,
            source_kind=source_kind,
            source_id=source_id,
            evidence_type=evidence_type,
            proof_domain=payload.get("proof_domain") or evidence_type,
            file_ref=file_ref,
            checksum=(source_payload.get("data_source") or {}).get("content_sha256") if source_kind == "canonical_evidence" else None,
            truth_label=truth_label,
            review_status="pending_review",
            mapping_status="mapped",
            source_system=source_system,
            event_timestamp=occurred_at,
            ingestion_timestamp=_dt(source_payload.get("ingested_at")),
            reporting_period=payload.get("reporting_period"),
            confidence=source_payload.get("confidence"),
            data_quality=source_payload.get("quality_status") or "unknown",
            stale_after=stale_after,
            unresolved_issue=payload.get("unresolved_issue"),
            metadata_json={
                "mapping_note": payload.get("mapping_note"),
                "requirement_keys": payload.get("requirement_keys") or [],
            },
        )
        self.db.add(row)
        self.db.flush()
        requirement_keys = set(payload.get("requirement_keys") or [])
        if requirement_keys:
            items = self._scope_query(AssuranceChecklistItem).filter(
                AssuranceChecklistItem.passport_id == passport_id,
                AssuranceChecklistItem.requirement_key.in_(requirement_keys),
            ).all()
            if len({item.requirement_key for item in items}) != len(requirement_keys):
                raise ValueError("One or more requirement_keys do not belong to this passport")
            for item in items:
                ids = list(item.evidence_artifact_ids or [])
                if row.id not in ids:
                    ids.append(row.id)
                item.evidence_artifact_ids = ids
                item.status = "unreviewed" if item.review_required else "mapped"
                item.notes = "Canonical evidence mapped for reviewer evaluation."
        else:
            self._sync_checklist_for_evidence(passport_id, row)
        self._audit(
            passport_id,
            "evidence_mapping_created",
            subject_type="evidence_mapping",
            subject_id=row.id,
            details={"source_kind": source_kind, "source_id": source_id, "evidence_type": evidence_type},
        )
        self.db.commit()
        return self.evidence_payload(row)

    def evidence_payload(self, row: AssuranceEvidenceArtifact) -> dict[str, Any]:
        payload = _as_dict(row)
        source: dict[str, Any] | None = None
        if row.canonical_evidence_id and self.organization_id:
            canonical = self.db.query(EvidenceRecord).filter(
                EvidenceRecord.id == row.canonical_evidence_id,
                EvidenceRecord.tenant_id == self.organization_id,
                EvidenceRecord.workspace_id == self.workspace_id,
            ).first()
            source = self._canonical_evidence_payload(canonical) if canonical else None
        elif row.field_observation_id and self.organization_id:
            observation = self.db.query(FieldObservation).filter(
                FieldObservation.id == row.field_observation_id,
                FieldObservation.tenant_id == self.organization_id,
                FieldObservation.workspace_id == self.workspace_id,
            ).first()
            source = self._field_observation_payload(observation) if observation else None
        payload["source"] = source
        payload["provenance"] = {
            "source_kind": row.source_kind,
            "source_id": row.source_id,
            "source_system": row.source_system,
            "event_timestamp": _iso(row.event_timestamp),
            "ingestion_timestamp": _iso(row.ingestion_timestamp),
            "truth_label": row.truth_label,
            "confidence": row.confidence,
            "data_quality": row.data_quality,
        }
        return payload

    def add_input_application(self, passport_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._passport(passport_id)
        app_type = payload.get("application_type", "input")
        row = InputApplication(
            id=payload.get("id") or f"inp-{uuid.uuid4().hex[:12]}",
            **self._scope_values(),
            passport_id=passport_id,
            application_type=app_type,
            applied_at=_dt(payload.get("applied_at")),
            block_id=payload.get("block_id"),
            parcel_id=payload.get("parcel_id"),
            product_name=payload["product_name"],
            quantity=payload.get("quantity"),
            unit=payload.get("unit"),
            operator=payload.get("operator"),
            truth_label=payload.get("truth_label", "reported"),
            evidence_artifact_id=payload.get("evidence_artifact_id"),
            metadata_json=payload.get("metadata") or {},
        )
        self.db.add(row)
        self.db.flush()
        if app_type == "pesticide":
            self.db.add(PesticideApplication(
                id=f"pest-{uuid.uuid4().hex[:12]}",
                **self._scope_values(),
                passport_id=passport_id,
                input_application_id=row.id,
                active_ingredient=payload.get("active_ingredient"),
                target_pest=payload.get("target_pest"),
                reentry_interval_hours=payload.get("reentry_interval_hours"),
                preharvest_interval_days=payload.get("preharvest_interval_days"),
                label_reference=payload.get("label_reference"),
                metadata_json=payload.get("pesticide_metadata") or {},
            ))
        if app_type == "fertilizer":
            self.db.add(FertilizerApplication(
                id=f"fert-{uuid.uuid4().hex[:12]}",
                **self._scope_values(),
                passport_id=passport_id,
                input_application_id=row.id,
                nutrient_profile=payload.get("nutrient_profile") or {},
                nitrogen_kg=payload.get("nitrogen_kg"),
                phosphorus_kg=payload.get("phosphorus_kg"),
                potassium_kg=payload.get("potassium_kg"),
                metadata_json=payload.get("fertilizer_metadata") or {},
            ))
        self._audit(
            passport_id,
            "input_application_created",
            subject_type="input_application",
            subject_id=row.id,
            details={"application_type": app_type, "truth_label": row.truth_label},
        )
        if not payload.get("evidence_artifact_id"):
            self.add_evidence(passport_id, {
                "evidence_type": "input_application_record",
                "proof_domain": "input_proof",
                "file_ref": f"input_application://{row.id}",
                "truth_label": row.truth_label,
                "source_system": "assurance_api",
                "metadata": {"input_application_id": row.id, "product_name": row.product_name},
            }, commit=False)
        self.db.commit()
        return _as_dict(row)

    def add_harvest_lot(self, passport_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._passport(passport_id)
        row = HarvestLot(
            id=payload.get("id") or f"lot-{uuid.uuid4().hex[:12]}",
            **self._scope_values(),
            passport_id=passport_id,
            lot_code=payload["lot_code"],
            crop=payload.get("crop"),
            variety=payload.get("variety"),
            harvested_at=_dt(payload.get("harvested_at")),
            block_id=payload.get("block_id"),
            parcel_id=payload.get("parcel_id"),
            quantity=payload.get("quantity"),
            unit=payload.get("unit"),
            destination=payload.get("destination"),
            metadata_json=payload.get("metadata") or {},
        )
        self.db.add(row)
        self.db.flush()
        self._audit(passport_id, "harvest_lot_created", subject_type="harvest_lot", subject_id=row.id)
        self.db.commit()
        return _as_dict(row)

    def add_traceability_event(self, passport_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._passport(passport_id)
        lot_id = payload.get("harvest_lot_id")
        if lot_id and not self._scope_query(HarvestLot).filter_by(id=lot_id, passport_id=passport_id).first():
            raise ValueError("harvest_lot_id does not belong to this passport")
        row = TraceabilityEvent(
            id=payload.get("id") or f"trace-{uuid.uuid4().hex[:12]}",
            **self._scope_values(),
            passport_id=passport_id,
            harvest_lot_id=lot_id,
            event_type=payload["event_type"],
            occurred_at=_dt(payload.get("occurred_at")),
            location=payload.get("location"),
            actor=payload.get("actor"),
            evidence_artifact_id=payload.get("evidence_artifact_id"),
            payload=payload.get("payload") or {},
        )
        self.db.add(row)
        self.db.flush()
        self._audit(
            passport_id,
            "traceability_event_created",
            subject_type="traceability_event",
            subject_id=row.id,
            details={"event_type": row.event_type, "harvest_lot_id": row.harvest_lot_id},
        )
        if not payload.get("evidence_artifact_id"):
            self.add_evidence(passport_id, {
                "evidence_type": "traceability_record",
                "proof_domain": "traceability_proof",
                "file_ref": f"traceability_event://{row.id}",
                "truth_label": "reported",
                "source_system": "assurance_api",
                "metadata": {"traceability_event_id": row.id, "event_type": row.event_type},
            }, commit=False)
        self.db.commit()
        return _as_dict(row)

    def _passport_scope_missing(self, passport: AssurancePassport) -> list[str]:
        missing: list[str] = []
        if not passport.parcel_ids:
            missing.append("parcel_ids")
        if not passport.reporting_period:
            missing.append("reporting_period")
        return missing

    def _linked_water_budget_ids(self, passport_id: str) -> set[str]:
        evidence = self._scope_query(AssuranceEvidenceArtifact).filter_by(passport_id=passport_id).all()
        linked_ids: set[str] = set()
        for row in evidence:
            metadata = row.metadata_json or {}
            for key in ("water_budget_id", "compliance_water_budget_id"):
                if metadata.get(key):
                    linked_ids.add(str(metadata[key]))
            for key in ("water_budget_ids", "compliance_water_budget_ids"):
                values = metadata.get(key) or []
                if isinstance(values, (str, int)):
                    values = [values]
                linked_ids.update(str(value) for value in values if value)
        return linked_ids

    def _scoped_compliance_assets(self, passport: AssurancePassport) -> dict[str, Any]:
        parcel_ids = [str(parcel_id) for parcel_id in (passport.parcel_ids or []) if parcel_id]
        scope_missing = self._passport_scope_missing(passport)
        parcels = []
        if parcel_ids:
            parcels = self.db.query(ComplianceParcel).filter(
                ComplianceParcel.tenant_id == self.owner_id,
                ComplianceParcel.id.in_(parcel_ids),
            ).all()

        jurisdictions = []
        if passport.jurisdiction_id:
            jurisdictions = self.db.query(ComplianceJurisdiction).filter_by(
                tenant_id=self.owner_id,
                id=passport.jurisdiction_id,
            ).all()

        wells = []
        if parcel_ids:
            wells = self.db.query(ComplianceWell).filter(
                ComplianceWell.tenant_id == self.owner_id,
                ComplianceWell.parcel_id.in_(parcel_ids),
            ).all()
        well_ids = [row.id for row in wells]

        meters = []
        if well_ids:
            meters = self.db.query(ComplianceMeter).filter(
                ComplianceMeter.tenant_id == self.owner_id,
                ComplianceMeter.well_id.in_(well_ids),
            ).all()
        meter_ids = [row.id for row in meters]

        measurements = []
        asset_filters = []
        if parcel_ids:
            asset_filters.append((ComplianceMeasurement.related_asset_type == "parcel") & ComplianceMeasurement.related_asset_id.in_(parcel_ids))
        if well_ids:
            asset_filters.append((ComplianceMeasurement.related_asset_type == "well") & ComplianceMeasurement.related_asset_id.in_(well_ids))
        if meter_ids:
            asset_filters.append((ComplianceMeasurement.related_asset_type == "meter") & ComplianceMeasurement.related_asset_id.in_(meter_ids))
        if passport.reporting_period and asset_filters:
            measurements = self.db.query(ComplianceMeasurement).filter(
                ComplianceMeasurement.tenant_id == self.owner_id,
                ComplianceMeasurement.reporting_period == str(passport.reporting_period),
                or_(*asset_filters),
            ).all()

        water_budgets = []
        linked_budget_ids = self._linked_water_budget_ids(passport.id)
        if passport.reporting_period and linked_budget_ids:
            water_budgets = self.db.query(ComplianceWaterBudget).filter(
                ComplianceWaterBudget.tenant_id == self.owner_id,
                ComplianceWaterBudget.id.in_(linked_budget_ids),
                ComplianceWaterBudget.reporting_period == str(passport.reporting_period),
            ).all()

        return {
            "scope_missing": scope_missing,
            "parcels": parcels,
            "jurisdictions": jurisdictions,
            "wells": wells,
            "meters": meters,
            "measurements": measurements,
            "water_budgets": water_budgets,
        }

    def _jurisdiction_payload(self, row: ComplianceJurisdiction) -> dict[str, Any]:
        return {"id": row.id, "organization_id": row.tenant_id, "country": row.country, "jurisdiction_level": row.jurisdiction_level, "authority_name": row.authority_name, "state": row.state, "county": row.county, "basin": row.basin, "subbasin": row.subbasin, "gsa": row.gsa, "district": row.district, "jurisdiction_pack": row.jurisdiction_pack, "reporting_year": row.reporting_year, "reporting_deadline": _iso(row.reporting_deadline), "workflow_type": row.workflow_type}

    def _parcel_payload(self, row: ComplianceParcel) -> dict[str, Any]:
        return {"id": row.id, "organization_id": row.tenant_id, "apn": row.apn, "parcel_identifier": row.parcel_identifier, "country": row.country, "state": row.state, "county": row.county, "geometry_ref": row.geometry_ref, "geometry": row.geometry}

    def _well_payload(self, row: ComplianceWell) -> dict[str, Any]:
        return {"id": row.id, "organization_id": row.tenant_id, "parcel_id": row.parcel_id, "well_identifier": row.well_identifier, "latitude": row.latitude, "longitude": row.longitude, "well_capacity": row.well_capacity, "capacity_unit": row.capacity_unit}

    def _meter_payload(self, row: ComplianceMeter) -> dict[str, Any]:
        return {"id": row.id, "organization_id": row.tenant_id, "well_id": row.well_id, "meter_identifier": row.meter_identifier, "manufacturer": row.manufacturer, "serial_number": row.serial_number, "measurement_method": row.measurement_method, "calibration_date": _iso(row.calibration_date), "calibration_document_ref": row.calibration_document_ref}

    def _measurement_payload(self, row: ComplianceMeasurement) -> dict[str, Any]:
        return {"id": row.id, "organization_id": row.tenant_id, "asset_type": row.related_asset_type, "asset_id": row.related_asset_id, "measurement_type": row.measurement_type, "value": row.value, "unit": row.unit, "method": row.method, "truth_label": row.truth_label, "source_system": row.source_system, "source_timestamp": _iso(row.source_timestamp), "ingestion_timestamp": _iso(row.ingestion_timestamp), "quality_status": row.quality_status, "reporting_period": row.reporting_period, "confidence": row.confidence, "correction_lineage": row.correction_lineage or []}

    def _water_budget_payload(self, row: ComplianceWaterBudget) -> dict[str, Any]:
        return {"id": row.id, "organization_id": row.tenant_id, "allocation_af": row.allocation, "extraction_af": row.extraction, "irrigation_application_af": row.irrigation_application, "remaining_balance_af": row.remaining_balance, "projected_balance_af": row.projected_balance, "threshold_status": row.threshold_status, "water_source": row.water_source, "reporting_period": row.reporting_period}

    def _proof_counts(self, passport_id: str, scoped_assets: dict[str, Any] | None = None) -> dict[str, int]:
        evidence = self._scope_query(AssuranceEvidenceArtifact).filter_by(passport_id=passport_id).all()
        counts: dict[str, int] = {}
        for row in evidence:
            if (
                row.mapping_status in {"rejected", "conflicting"}
                or row.unresolved_issue
                or (row.stale_after and row.stale_after < datetime.utcnow())
            ):
                continue
            counts[row.evidence_type] = counts.get(row.evidence_type, 0) + 1
        if scoped_assets and not scoped_assets["scope_missing"]:
            if scoped_assets["parcels"]:
                counts["farm_boundary"] = counts.get("farm_boundary", 0) + len(scoped_assets["parcels"])
            if scoped_assets["measurements"]:
                counts["water_measurement"] = counts.get("water_measurement", 0) + len(scoped_assets["measurements"])
            if scoped_assets["water_budgets"]:
                counts["water_budget"] = counts.get("water_budget", 0) + len(scoped_assets["water_budgets"])
        return counts

    def readiness(self, passport_id: str, *, persist: bool = True) -> dict[str, Any]:
        passport = self._passport(passport_id)
        scoped_assets = self._scoped_compliance_assets(passport)
        counts = self._proof_counts(passport_id, scoped_assets)
        items = self._scope_query(AssuranceChecklistItem).filter_by(passport_id=passport_id).all()
        mappings = self._scope_query(AssuranceEvidenceArtifact).filter_by(passport_id=passport_id).all()
        mappings_by_id = {row.id: row for row in mappings}
        missing: list[dict[str, Any]] = []
        requirements: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        satisfied = 0
        accepted = 0
        pending_review = 0
        specs = checklist_for(passport.rule_pack_ids)
        for item in items:
            spec = next((entry for entry in specs if entry["rule_pack_id"] == item.rule_pack_id and entry["key"] == item.requirement_key), {})
            linked = [mappings_by_id[value] for value in (item.evidence_artifact_ids or []) if value in mappings_by_id]
            usable = [row for row in linked if row.mapping_status not in {"rejected"}]
            stale = [row for row in usable if row.stale_after and row.stale_after < datetime.utcnow()]
            conflicting = [row for row in usable if row.unresolved_issue or row.mapping_status == "conflicting"]
            accepted_rows = [row for row in usable if row.mapping_status == "accepted" or row.review_status == "accepted"]
            not_applicable = any(row.mapping_status == "not_applicable" for row in linked) or item.status == "not_applicable"
            is_satisfied = bool(usable and not stale and not conflicting) or not_applicable or item.status == "satisfied"
            if not is_satisfied and spec.get("record_type") == "input_application":
                is_satisfied = self._scope_query(InputApplication).filter_by(passport_id=passport_id).count() > 0
            if not is_satisfied and spec.get("evidence_types"):
                is_satisfied = any(counts.get(evidence_type, 0) > 0 for evidence_type in spec["evidence_types"])
            if not_applicable:
                requirement_status = "not_applicable"
            elif conflicting:
                requirement_status = "conflicting"
            elif stale:
                requirement_status = "stale"
            elif accepted_rows:
                requirement_status = "accepted"
            elif is_satisfied and (linked or spec.get("record_type")):
                requirement_status = "reviewer_required" if item.review_required else "mapped"
            elif is_satisfied:
                requirement_status = "present"
            elif any(row.mapping_status == "rejected" for row in linked):
                requirement_status = "rejected"
            else:
                requirement_status = "missing"
            if is_satisfied:
                satisfied += 1
                if requirement_status == "accepted":
                    accepted += 1
                elif requirement_status not in {"not_applicable", "mapped", "present"}:
                    pending_review += 1
                item.status = requirement_status
            else:
                missing_item = {
                    "rule_pack_id": item.rule_pack_id,
                    "requirement_key": item.requirement_key,
                    "section_type": item.section_type,
                    "severity": item.severity,
                    "blocking": bool(item.blocking),
                    "status": requirement_status,
                    "explanation": item.explanation or spec.get("explanation"),
                    "needed_evidence_types": spec.get("evidence_types", []),
                }
                missing.append(missing_item)
                if requirement_status in {"stale", "conflicting", "rejected"}:
                    warnings.append(missing_item)
            requirements.append({
                "id": item.id,
                "rule_pack_id": item.rule_pack_id,
                "rule_pack_version": spec.get("rule_pack_version"),
                "requirement_key": item.requirement_key,
                "title": spec.get("title") or item.requirement_key.replace("_", " ").title(),
                "domain": spec.get("domain") or item.section_type,
                "section_type": item.section_type,
                "status": requirement_status,
                "severity": item.severity,
                "blocking": bool(item.blocking),
                "review_required": bool(item.review_required),
                "explanation": item.explanation or spec.get("explanation"),
                "needed_evidence_types": spec.get("evidence_types", []),
                "optional_evidence_types": spec.get("optional_evidence_types", []),
                "evidence_mapping_ids": list(item.evidence_artifact_ids or []),
            })
        total = max(len(items), 1)
        readiness_score = round(satisfied / total * 100, 1)
        blocking_issues = [m for m in missing if m["blocking"]]
        risk_score = max(0.0, min(100.0, 100.0 - readiness_score + len(blocking_issues) * 5 + len(warnings) * 5))
        risk_level = "low" if risk_score < 25 else "medium" if risk_score < 60 else "high"
        scope_missing = scoped_assets["scope_missing"]
        status_value = "needs_scope_review" if scope_missing else "ready_for_review" if not blocking_issues else "missing_proof"
        review_status = "needs_review" if scope_missing or blocking_issues or pending_review else "ready_for_review"
        payload = {
            "passport_id": passport_id,
            "tenant_id": self.tenant_id,
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
            "status": status_value,
            "review_status": review_status,
            "readiness_score": readiness_score,
            "risk_score": round(risk_score, 1),
            "risk_level": risk_level,
            "satisfied_count": satisfied,
            "accepted_count": accepted,
            "pending_review_count": pending_review,
            "checklist_count": len(items),
            "missing_evidence": missing,
            "blocking_issues": blocking_issues,
            "warnings": warnings,
            "requirements": requirements,
            "proof_counts": counts,
            "rule_pack_ids": passport.rule_pack_ids,
            "rule_pack_versions": rule_pack_versions(passport.rule_pack_ids),
            "language": "audit readiness",
            "score_explanation": {
                "numerator": satisfied,
                "denominator": len(items),
                "formula": "requirements with usable mapped evidence or an explicit not-applicable review decision / selected requirements",
                "does_not_mean": "Certification, regulatory approval, or legal compliance determination.",
            },
            "scope": {
                "readiness_package_only": True,
                "authority_submission": False,
                "live_source_complete": False,
                "scope_status": "needs_scope_review" if scope_missing else "scoped",
                "review_status": review_status,
                "missing_scope": scope_missing,
                "parcel_ids": passport.parcel_ids or [],
                "jurisdiction_id": passport.jurisdiction_id,
                "reporting_period": passport.reporting_period,
                "scoped_record_counts": {
                    "parcels": len(scoped_assets["parcels"]),
                    "jurisdictions": len(scoped_assets["jurisdictions"]),
                    "wells": len(scoped_assets["wells"]),
                    "meters": len(scoped_assets["meters"]),
                    "measurements": len(scoped_assets["measurements"]),
                    "water_budgets": len(scoped_assets["water_budgets"]),
                },
            },
            "disclaimer": ASSURANCE_DISCLAIMER,
        }
        if persist:
            self.db.add(AssuranceRiskScore(
                id=f"risk-{uuid.uuid4().hex[:12]}",
                **self._scope_values(),
                passport_id=passport_id,
                score_type="audit_readiness_risk",
                score=payload["risk_score"],
                risk_level=risk_level,
                factors={"missing_evidence": missing, "proof_counts": counts},
            ))
            for section_type in SECTION_TYPES:
                section = self._scope_query(AssurancePassportSection).filter_by(passport_id=passport_id, section_type=section_type).first()
                if section:
                    section.readiness_score = readiness_score
                    section.status = "needs_review" if scope_missing else "ready_for_review" if not [m for m in missing if m["section_type"] == section_type] else "missing_proof"
                    section.payload = payload
                    section.updated_at = datetime.utcnow()
            passport.status = payload["status"]
            passport.updated_at = datetime.utcnow()
            self._audit(
                passport_id,
                "readiness_evaluated",
                subject_type="passport",
                subject_id=passport_id,
                details={"score": readiness_score, "status": status_value, "blocking_issue_count": len(blocking_issues)},
            )
            self.db.commit()
        return payload

    def overview(self) -> dict[str, Any]:
        passports = self._scope_query(AssurancePassport).order_by(AssurancePassport.updated_at.desc()).all()
        summaries = [self.readiness(row.id, persist=False) for row in passports]
        total_requirements = sum(item["checklist_count"] for item in summaries)
        total_satisfied = sum(item["satisfied_count"] for item in summaries)
        readiness_score = round(total_satisfied / total_requirements * 100, 1) if total_requirements else 0.0
        open_actions: list[dict[str, Any]] = []
        for passport, summary in zip(passports, summaries):
            for issue in summary["blocking_issues"][:5]:
                open_actions.append({
                    "passport_id": passport.id,
                    "passport_name": passport.farm_name,
                    "requirement_key": issue["requirement_key"],
                    "status": issue["status"],
                    "explanation": issue["explanation"],
                })
        return {
            "workspace_id": self.workspace_id,
            "organization_id": self.organization_id,
            "readiness_score": readiness_score,
            "passport_count": len(passports),
            "requirement_count": total_requirements,
            "satisfied_count": total_satisfied,
            "missing_proof_count": sum(len(item["blocking_issues"]) for item in summaries),
            "pending_review_count": sum(item["pending_review_count"] for item in summaries),
            "open_actions": open_actions,
            "passport_summaries": [
                {
                    "passport_id": passport.id,
                    "farm_name": passport.farm_name,
                    "status": summary["status"],
                    "readiness_score": summary["readiness_score"],
                    "blocking_issue_count": len(summary["blocking_issues"]),
                    "pending_review_count": summary["pending_review_count"],
                }
                for passport, summary in zip(passports, summaries)
            ],
            "disclaimer": ASSURANCE_DISCLAIMER,
        }

    def review_queue(self, passport_id: str) -> list[dict[str, Any]]:
        self._passport(passport_id)
        rows = self._scope_query(AssuranceEvidenceArtifact).filter_by(passport_id=passport_id).order_by(
            AssuranceEvidenceArtifact.created_at.asc()
        ).all()
        queue: list[dict[str, Any]] = []
        for row in rows:
            is_stale = bool(row.stale_after and row.stale_after < datetime.utcnow())
            if row.mapping_status == "accepted" and not is_stale and not row.unresolved_issue:
                continue
            payload = self.evidence_payload(row)
            payload["queue_reason"] = (
                "stale" if is_stale else "conflicting" if row.unresolved_issue else row.mapping_status or row.review_status
            )
            queue.append(payload)
        return queue

    def review(self, passport_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._passport(passport_id)
        action = str(payload.get("action") or "")
        if action not in REVIEW_ACTIONS:
            raise ValueError(f"action must be one of {sorted(REVIEW_ACTIONS)}")
        reason = str(payload.get("reason") or "").strip() or None
        if action in {"reject_mapping", "request_additional_proof", "mark_not_applicable"} and not reason:
            raise ValueError(f"reason is required for {action}")
        mapping_id = payload.get("evidence_mapping_id")
        checklist_item_id = payload.get("checklist_item_id")
        mapping = None
        item = None
        if mapping_id:
            mapping = self._scope_query(AssuranceEvidenceArtifact).filter_by(
                id=str(mapping_id), passport_id=passport_id
            ).first()
            if not mapping:
                raise KeyError("Evidence mapping not found")
        if checklist_item_id:
            item = self._scope_query(AssuranceChecklistItem).filter_by(
                id=str(checklist_item_id), passport_id=passport_id
            ).first()
            if not item:
                raise KeyError("Checklist item not found")
        if not mapping and not item:
            raise ValueError("evidence_mapping_id or checklist_item_id is required")

        previous_state = {
            "mapping_status": mapping.mapping_status if mapping else None,
            "review_status": mapping.review_status if mapping else None,
            "checklist_status": item.status if item else None,
        }
        next_status = REVIEW_ACTIONS[action]
        if mapping:
            if action == "correct_metadata":
                corrections = payload.get("corrections") or {}
                allowed = {
                    "evidence_type", "proof_domain", "truth_label", "reporting_period",
                    "confidence", "data_quality", "stale_after", "unresolved_issue",
                }
                unknown = set(corrections) - allowed
                if unknown:
                    raise ValueError(f"Unsupported correction fields: {', '.join(sorted(unknown))}")
                if "truth_label" in corrections and corrections["truth_label"] not in TRUTH_LABELS:
                    raise ValueError(f"truth_label must be one of {sorted(TRUTH_LABELS)}")
                for key, value in corrections.items():
                    setattr(mapping, key, _dt(value) if key == "stale_after" else value)
                mapping.mapping_status = "reviewer_required"
                mapping.review_status = "pending_review"
            else:
                mapping.mapping_status = next_status
                mapping.review_status = "accepted" if action == "accept_mapping" else "rejected" if action == "reject_mapping" else "pending_review"
                if action == "reopen":
                    mapping.unresolved_issue = None
                elif action == "request_additional_proof":
                    mapping.unresolved_issue = reason
        if item:
            item.status = next_status
            item.notes = reason or f"Reviewer action: {action}."
            item.updated_at = datetime.utcnow()
        event = AssuranceReviewEvent(
            id=f"are-{uuid.uuid4().hex[:16]}",
            **self._scope_values(),
            passport_id=passport_id,
            evidence_artifact_id=mapping.id if mapping else None,
            checklist_item_id=item.id if item else None,
            action=action,
            actor_user_id=self.actor_user_id,
            actor_label=payload.get("actor_label"),
            reason=reason,
            previous_state=previous_state,
            next_state={
                "mapping_status": mapping.mapping_status if mapping else None,
                "review_status": mapping.review_status if mapping else None,
                "checklist_status": item.status if item else None,
            },
            metadata_json=payload.get("metadata") or {},
        )
        self.db.add(event)
        self.db.flush()
        self._audit(
            passport_id,
            "review_decision_recorded",
            subject_type="review_event",
            subject_id=event.id,
            details={"action": action, "mapping_id": mapping.id if mapping else None, "checklist_item_id": item.id if item else None},
        )
        self.db.commit()
        return {
            "review_event": _as_dict(event),
            "evidence_mapping": self.evidence_payload(mapping) if mapping else None,
            "checklist_item": _as_dict(item) if item else None,
        }

    def list_review_events(self, passport_id: str) -> list[dict[str, Any]]:
        self._passport(passport_id)
        return [
            _as_dict(row)
            for row in self._scope_query(AssuranceReviewEvent).filter_by(passport_id=passport_id).order_by(
                AssuranceReviewEvent.created_at.asc()
            ).all()
        ]

    def create_field_task(self, passport_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        passport = self._passport(passport_id)
        if not self.organization_id or not self.workspace_id:
            raise ValueError("field task creation requires Portal workspace scope")
        requirement_key = str(payload.get("requirement_key") or "")
        item = self._scope_query(AssuranceChecklistItem).filter_by(
            passport_id=passport_id,
            requirement_key=requirement_key,
        ).first()
        if not item:
            raise KeyError("Checklist item not found")
        idempotency_key = str(payload.get("idempotency_key") or _checksum({
            "passport_id": passport_id,
            "requirement_key": requirement_key,
            "title": payload.get("title"),
        }))[:64]
        existing = self.db.query(IngestionJob).filter_by(
            tenant_id=self.organization_id,
            workspace_id=self.workspace_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            return _as_dict(existing)
        job = IngestionJob(
            id=f"assurance-task-{uuid.uuid4().hex[:12]}",
            tenant_id=self.organization_id,
            workspace_id=self.workspace_id,
            job_type="field_ops_task",
            status="queued",
            input_json={
                "title": payload.get("title") or f"Collect proof: {requirement_key.replace('_', ' ')}",
                "description": payload.get("description") or item.explanation,
                "assignee": payload.get("assignee"),
                "due_at": payload.get("due_at"),
                "provenance": {
                    "source": "assurance",
                    "passport_id": passport.id,
                    "passport_name": passport.farm_name,
                    "checklist_item_id": item.id,
                    "requirement_key": requirement_key,
                    "rule_pack_id": item.rule_pack_id,
                    "workspace_id": self.workspace_id,
                },
            },
            output_json={},
            idempotency_key=idempotency_key,
        )
        self.db.add(job)
        self.db.flush()
        self._audit(
            passport_id,
            "field_task_created",
            subject_type="ingestion_job",
            subject_id=job.id,
            details={"requirement_key": requirement_key, "idempotency_key": idempotency_key},
        )
        self.db.commit()
        return _as_dict(job)

    def export_pdf(self, passport_id: str) -> dict[str, Any]:
        return self.create_package(
            passport_id,
            {"package_type": "assurance_passport", "export_type": "pdf"},
            legacy_inline=True,
        )

    def list_exports(self, passport_id: str) -> list[dict[str, Any]]:
        self._passport(passport_id)
        rows = self._scope_query(AssuranceExport).filter_by(passport_id=passport_id).order_by(
            AssuranceExport.created_at.desc()
        ).all()
        return [self._export_response(row, include_content=False) for row in rows]

    def _export_response(self, row: AssuranceExport, *, include_content: bool) -> dict[str, Any]:
        result = {
            "id": row.id,
            "passport_id": row.passport_id,
            "export_type": row.export_type,
            "package_type": row.package_type,
            "package_version": row.package_version,
            "package_status": row.package_status,
            "content_type": "application/pdf",
            "checksum": row.checksum,
            "storage_backend": row.storage_backend,
            "storage_ref": row.storage_ref,
            "generated_artifact_id": row.generated_artifact_id,
            "download_url": (
                f"/v1/workspaces/{self.workspace_id}/assurance/passports/{row.passport_id}/packages/{row.id}/download"
                if self.organization_id and row.generated_artifact_id
                else None
            ),
            "rule_pack_versions": row.rule_pack_versions or {},
            "evidence_references": row.evidence_references or [],
            "created_at": row.created_at.isoformat(),
            "disclaimer": ASSURANCE_DISCLAIMER,
        }
        if include_content:
            result["content_base64"] = (row.payload or {}).get("content_base64")
        return result

    def create_package(
        self,
        passport_id: str,
        payload: dict[str, Any],
        *,
        legacy_inline: bool = False,
    ) -> dict[str, Any]:
        passport = self._passport(passport_id)
        package_type = str(payload.get("package_type") or "assurance_passport")
        if package_type not in PACKAGE_TYPES:
            raise ValueError(f"package_type must be one of {sorted(PACKAGE_TYPES)}")
        idempotency_key = payload.get("idempotency_key")
        if idempotency_key:
            existing = self._scope_query(AssuranceExport).filter_by(
                passport_id=passport_id,
                package_type=package_type,
                idempotency_key=str(idempotency_key),
            ).first()
            if existing:
                return self._export_response(existing, include_content=legacy_inline)

        snapshot = self._export_payload(passport_id)
        readiness = snapshot["readiness"]
        if readiness["blocking_issues"]:
            package_status = "blocked"
        elif readiness["pending_review_count"]:
            package_status = "reviewer_evaluation_required"
        else:
            package_status = "ready_for_reviewer_evaluation"
        previous = self._scope_query(AssuranceExport).filter_by(
            passport_id=passport_id,
            package_type=package_type,
        ).order_by(AssuranceExport.package_version.desc()).first()
        package_version = (previous.package_version if previous else 0) + 1
        evidence_references = [
            {
                "mapping_id": item["id"],
                "source_kind": item["source_kind"],
                "source_id": item["source_id"],
                "checksum": item.get("checksum"),
            }
            for item in snapshot["evidence"]
        ]
        report_title = package_type.replace("_", " ").title()
        answer = (
            f"Status: {package_status}. Readiness: {readiness['readiness_score']}%. "
            f"Satisfied requirements: {readiness['satisfied_count']} of {readiness['checklist_count']}. "
            f"Blocking issues: {len(readiness['blocking_issues'])}. Pending human reviews: {readiness['pending_review_count']}.\n\n"
            f"{ASSURANCE_DISCLAIMER}"
        )
        try:
            from app.api.v1.chat_artifacts import ReportPdfRequest, build_report_pdf_bytes

            pdf_bytes = build_report_pdf_bytes(
                ReportPdfRequest(
                    title=report_title,
                    question=f"Immutable Assurance package snapshot for {passport.farm_name}",
                    answer=answer,
                    uploaded_evidence=[
                        {
                            "filename": item.get("filename") or item.get("source_id"),
                            "source_type": item.get("source_kind"),
                            "warnings": [item["unresolved_issue"]] if item.get("unresolved_issue") else [],
                        }
                        for item in snapshot["evidence"]
                    ],
                ),
                self.owner_id,
            )
        except (ImportError, ModuleNotFoundError):
            pdf_bytes = render_passport_pdf(snapshot)
        checksum = hashlib.sha256(pdf_bytes).hexdigest()
        export_id = f"aex-{uuid.uuid4().hex[:12]}"
        staged_artifact = None
        generated_artifact_id = None
        storage_backend = "inline_base64"
        storage_ref = None
        package_payload = {
            **snapshot,
            "package_type": package_type,
            "package_version": package_version,
            "package_status": package_status,
            "content_type": "application/pdf",
        }
        if legacy_inline:
            package_payload["content_base64"] = base64.b64encode(pdf_bytes).decode("ascii")
        else:
            if not self.organization_id or not self.workspace_id:
                raise ValueError("modern package delivery requires Portal workspace scope")
            generated_artifact_id = f"artifact-{uuid.uuid4().hex[:16]}"
            filename = f"{package_type}-v{package_version}.pdf"
            staged_artifact = stage_assurance_artifact(
                artifact_id=generated_artifact_id,
                organization_id=self.organization_id,
                workspace_id=self.workspace_id,
                title=report_title,
                filename=filename,
                pdf_bytes=pdf_bytes,
                metadata={
                    "assurance_export_id": export_id,
                    "passport_id": passport_id,
                    "package_type": package_type,
                    "package_version": package_version,
                    "package_status": package_status,
                    "immutable": True,
                },
            )
            self.db.add(staged_artifact.artifact)
            storage_backend = "generated_artifact"
            storage_ref = f"generated_artifact://{generated_artifact_id}"
        export = AssuranceExport(
            id=export_id,
            **self._scope_values(),
            passport_id=passport_id,
            export_type="pdf",
            package_type=package_type,
            package_version=package_version,
            package_status=package_status,
            generated_by_user_id=self.actor_user_id,
            idempotency_key=str(idempotency_key) if idempotency_key else None,
            rule_pack_versions=rule_pack_versions(passport.rule_pack_ids),
            evidence_references=evidence_references,
            generated_artifact_id=generated_artifact_id,
            storage_backend=storage_backend,
            storage_ref=storage_ref,
            checksum=checksum,
            payload=package_payload,
        )
        self.db.add(export)
        self.db.flush()
        self._audit(
            passport_id,
            "proof_package_generated",
            subject_type="assurance_export",
            subject_id=export.id,
            details={"package_type": package_type, "package_version": package_version, "package_status": package_status},
        )
        self.db.commit()
        if staged_artifact is not None:
            staged_artifact.promote()
        return self._export_response(export, include_content=legacy_inline)

    def package_artifact(self, passport_id: str, package_id: str) -> tuple[AssuranceExport, GeneratedArtifact]:
        """Resolve a package and catalog artifact strictly inside Portal scope."""

        self._passport(passport_id)
        row = self._scope_query(AssuranceExport).filter_by(id=package_id, passport_id=passport_id).first()
        if not row or not row.generated_artifact_id:
            raise KeyError("Proof package not found")
        artifact = self.db.query(GeneratedArtifact).filter(
            GeneratedArtifact.id == row.generated_artifact_id,
            GeneratedArtifact.tenant_id == self.organization_id,
            GeneratedArtifact.workspace_id == self.workspace_id,
            GeneratedArtifact.artifact_type == "assurance_proof_package",
        ).first()
        if not artifact or str((artifact.metadata_json or {}).get("assurance_export_id")) != row.id:
            raise KeyError("Proof package not found")
        return row, artifact

    def run_agent(self, passport_id: str) -> dict[str, Any]:
        """Run deterministic, workspace-scoped Assurance triage.

        Evidence text is never interpreted as instruction. The run consumes
        only server-owned mappings, statuses, provenance identifiers, and the
        deterministic readiness result. It proposes next actions but cannot
        accept evidence, complete review, certify, or generate/send a package.
        """

        if not self.organization_id or not self.workspace_id or not self.actor_user_id:
            raise ValueError("Assurance Agent requires Portal workspace scope")
        passport = self._passport(passport_id)
        readiness = self.readiness(passport_id)
        mappings = self._scope_query(AssuranceEvidenceArtifact).filter_by(passport_id=passport_id).all()
        classifications = [
            {
                "mapping_id": row.id,
                "source_kind": row.source_kind,
                "source_id": row.source_id,
                "evidence_type": row.evidence_type,
                "proof_domain": row.proof_domain,
                "mapping_status": row.mapping_status,
                "review_status": row.review_status,
                "data_quality": row.data_quality,
                "stale": bool(row.stale_after and row.stale_after < datetime.utcnow()),
                "conflicting": bool(row.unresolved_issue or row.mapping_status == "conflicting"),
            }
            for row in mappings
        ]
        recommended_actions = [
            {
                "action_type": "collect_missing_evidence",
                "requirement_key": item["requirement_key"],
                "title": f"Collect proof: {item['requirement_key'].replace('_', ' ')}",
                "requires_human_approval": True,
                "execution": "Use the explicit Assurance field-task action after human confirmation.",
            }
            for item in readiness["blocking_issues"][:10]
        ]
        if not readiness["blocking_issues"]:
            recommended_actions.append({
                "action_type": "prepare_draft_package",
                "title": "Prepare a draft reviewer package",
                "requires_human_approval": True,
                "execution": "Use the explicit package-generation action; no external delivery is automatic.",
            })
        output = {
            "workflow_type": "assurance_intelligence_triage",
            "passport_id": passport_id,
            "summary": (
                f"Deterministic triage found {len(readiness['blocking_issues'])} blocking issue(s), "
                f"{readiness['pending_review_count']} pending human review(s), and {len(mappings)} evidence mapping(s)."
            ),
            "classifications": classifications,
            "gaps": readiness["blocking_issues"],
            "warnings": readiness["warnings"],
            "recommended_actions": recommended_actions,
            "draft_package": {
                "package_type": "assurance_passport",
                "status": "proposal_only",
                "can_generate": not readiness["blocking_issues"],
            },
            "human_review_authoritative": True,
            "requires_human_approval": True,
            "prompt_injection_boundary": (
                "Uploaded evidence is untrusted data. Evidence text cannot alter rules, approve mappings, "
                "complete review, authorize an action, or override deterministic readiness."
            ),
            "truth_constraints": [
                "Decision support only; never certification, legal compliance, approval, or filing.",
                "Human review decisions remain authoritative and append-only.",
                "No package generation, external delivery, or physical action occurs in this run.",
                "The legacy unauthenticated execution-assurance routes are outside this workflow's trust boundary.",
            ],
        }
        run = IntelligenceRun(
            id=f"air-{uuid.uuid4().hex[:16]}",
            tenant_id=self.organization_id,
            workspace_id=self.workspace_id,
            user_id=self.actor_user_id,
            run_type="assurance_agent_triage",
            question="Classify evidence state, detect gaps/conflicts, and recommend reviewer-safe next actions.",
            input_context_json={
                "passport_id": passport_id,
                "rule_pack_versions": rule_pack_versions(passport.rule_pack_ids),
                "evidence_mapping_ids": [row.id for row in mappings],
                "untrusted_evidence_text_consumed": False,
            },
            output_json=output,
            citations_json=[row.id for row in mappings],
            provenance_json={
                "source": "assurance",
                "engine": "deterministic",
                "human_review_authoritative": True,
            },
            freshness_json={"evaluated_at": datetime.now(timezone.utc).isoformat()},
            status="completed",
        )
        self.db.add(run)
        self._audit(
            passport_id,
            "assurance_agent_triage_completed",
            subject_type="intelligence_run",
            subject_id=run.id,
            details={
                "blocking_issue_count": len(readiness["blocking_issues"]),
                "pending_review_count": readiness["pending_review_count"],
                "human_review_authoritative": True,
            },
        )
        self.db.commit()
        return self._agent_run_payload(run)

    def list_agent_runs(self, passport_id: str) -> list[dict[str, Any]]:
        self._passport(passport_id)
        if not self.organization_id or not self.workspace_id:
            return []
        rows = self.db.query(IntelligenceRun).filter(
            IntelligenceRun.tenant_id == self.organization_id,
            IntelligenceRun.workspace_id == self.workspace_id,
            IntelligenceRun.run_type == "assurance_agent_triage",
        ).order_by(IntelligenceRun.created_at.desc()).limit(100).all()
        return [
            self._agent_run_payload(row)
            for row in rows
            if str((row.input_context_json or {}).get("passport_id")) == passport_id
        ][:25]

    def _agent_run_payload(self, row: IntelligenceRun) -> dict[str, Any]:
        return {
            "id": row.id,
            "workspace_id": row.workspace_id,
            "run_type": row.run_type,
            "status": row.status,
            "created_at": row.created_at.isoformat(),
            "output": row.output_json or {},
            "citations": row.citations_json or [],
            "provenance": row.provenance_json or {},
            "freshness": row.freshness_json or {},
        }

    def _export_payload(self, passport_id: str) -> dict[str, Any]:
        passport = self._passport(passport_id)
        scoped_assets = self._scoped_compliance_assets(passport)
        readiness = self.readiness(passport_id, persist=True)
        return {
            "passport": _as_dict(passport),
            "farm_summary": {
                "farm_name": passport.farm_name,
                "farm_location": passport.farm_location,
                "crop": passport.crop,
                "season": passport.season,
                "reporting_period": passport.reporting_period,
                "parcels": [self._parcel_payload(row) for row in scoped_assets["parcels"]],
                "jurisdictions": [self._jurisdiction_payload(row) for row in scoped_assets["jurisdictions"]],
            },
            "water_proof": {
                "wells": [self._well_payload(row) for row in scoped_assets["wells"]],
                "meters": [self._meter_payload(row) for row in scoped_assets["meters"]],
                "measurements": [self._measurement_payload(row) for row in scoped_assets["measurements"]],
                "water_budgets": [self._water_budget_payload(row) for row in scoped_assets["water_budgets"]],
            },
            "input_proof": [_as_dict(row) for row in self._scope_query(InputApplication).filter_by(passport_id=passport_id).all()],
            "traceability_proof": {
                "harvest_lots": [_as_dict(row) for row in self._scope_query(HarvestLot).filter_by(passport_id=passport_id).all()],
                "events": [_as_dict(row) for row in self._scope_query(TraceabilityEvent).filter_by(passport_id=passport_id).all()],
            },
            "evidence": [self.evidence_payload(row) for row in self._scope_query(AssuranceEvidenceArtifact).filter_by(passport_id=passport_id).all()],
            "readiness": readiness,
            "audit_trail": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": "AGRO-AI Assurance OS",
                "scope": readiness["scope"],
            },
            "disclaimer": ASSURANCE_DISCLAIMER,
        }


def render_passport_pdf(package: dict[str, Any]) -> bytes:
    from io import BytesIO

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ModuleNotFoundError:
        return _minimal_passport_pdf(package)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title="Assurance Passport Audit Readiness")
    styles = getSampleStyleSheet()
    story = []

    def add_heading(text: str) -> None:
        story.append(Paragraph(text, styles["Heading2"]))

    def add_body(text: str) -> None:
        story.append(Paragraph(text.replace("&", "&amp;"), styles["BodyText"]))
        story.append(Spacer(1, 8))

    passport = package["passport"]
    readiness = package["readiness"]
    story.append(Paragraph("Assurance Passport - Audit Readiness", styles["Title"]))
    add_body(package["disclaimer"])
    add_heading("Farm Summary")
    add_body(f"Farm: {passport.get('farm_name')} | Crop: {passport.get('crop') or 'not provided'} | Period: {passport.get('reporting_period')}")
    add_heading("Water Proof")
    water = package["water_proof"]
    add_body(f"Wells: {len(water['wells'])}; meters: {len(water['meters'])}; measurements: {len(water['measurements'])}; water budgets: {len(water['water_budgets'])}.")
    add_heading("Input Proof")
    add_body(f"Input application records: {len(package['input_proof'])}.")
    add_heading("Traceability Proof")
    trace = package["traceability_proof"]
    add_body(f"Harvest lots: {len(trace['harvest_lots'])}; traceability events: {len(trace['events'])}.")
    add_heading("Missing Evidence")
    if readiness["missing_evidence"]:
        add_body("; ".join(item["requirement_key"] for item in readiness["missing_evidence"]))
    else:
        add_body("No missing checklist evidence detected for the selected rule packs.")
    add_heading("Readiness Score")
    add_body(f"{readiness['readiness_score']}% - {readiness['status']}.")
    add_heading("Risk Score")
    add_body(f"{readiness['risk_score']} ({readiness['risk_level']}).")
    add_heading("Audit Trail")
    add_body(f"Generated at {package['audit_trail']['generated_at']}. Scope: audit readiness evidence package for reviewer evaluation.")
    doc.build(story)
    return buf.getvalue()


def _minimal_passport_pdf(package: dict[str, Any]) -> bytes:
    passport = package["passport"]
    readiness = package["readiness"]
    lines = [
        "Assurance Passport - Audit Readiness",
        package["disclaimer"],
        f"Farm: {passport.get('farm_name')} | Crop: {passport.get('crop') or 'not provided'} | Period: {passport.get('reporting_period')}",
        f"Readiness Score: {readiness['readiness_score']}% - {readiness['status']}.",
        f"Risk Score: {readiness['risk_score']} ({readiness['risk_level']}).",
        "Audit readiness evidence package for reviewer evaluation.",
    ]
    text = "\\n".join(line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines)
    stream = f"BT /F1 10 Tf 72 740 Td ({text}) Tj ET".encode("latin-1", errors="replace")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"5 0 obj << /Length " + str(len(stream)).encode() + b" >> stream\n" + stream + b"\nendstream endobj\n",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(pdf)
