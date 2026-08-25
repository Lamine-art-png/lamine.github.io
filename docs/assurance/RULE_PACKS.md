# Assurance rule packs

Rule packs are deterministic, versioned requirement catalogs. They organize reviewer evidence; they do not encode a legal opinion or claim that a customer satisfies a statute, standard, buyer program, or certification scheme.

## Customer-visible V1 packs

### `water_assurance_generic_v1` — version 1.0.0

Requires water-source/field scope, applied-water measurement, an irrigation execution record, and activity verification. Optional evidence includes wells, meters, runtime, flow, recommendations, approvals, tasks, photos, and variance records.

### `buyer_input_records_v1` — version 1.0.0

Requires an input application record plus supporting input documentation. Customer-specific buyer meaning must be selected and reviewed by the customer; AGRO-AI does not claim buyer acceptance.

### `operational_execution_proof_v1` — version 1.0.0

Models the provenance chain `recommendation -> human approval -> task/work order -> field execution -> verification`. Every stage remains separately reviewable.

## Compatibility packs

The historical `waterops_generic_v0_1`, `eudr_supplier_readiness_v0_1`, `buyer_input_records_v0_1`, and `farm_finance_risk_pack_v0_1` definitions remain available so existing API-key Passports and tests retain their behavior. New portal Passports default only to the customer-visible V1 packs.

## Version behavior

Each Passport stores selected pack IDs. Checklist rows preserve the rule-pack identity, and audit/export snapshots store the resolved version map. A newly generated package never mutates an older snapshot. Future rule changes require a new pack version and an explicit migration or customer selection; in-place historical reinterpretation is not allowed.
