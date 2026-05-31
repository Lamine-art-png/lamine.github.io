"""Shared constants for the compliance kernel."""

FEATURE_FLAG = "CALIFORNIA_COMPLIANCE_PACK_ENABLED"
TRUTH_LABELS = {"measured", "reported", "estimated", "calculated", "AI-inferred"}
WORKFLOWS = {"sgma_gsa_annual_report_readiness", "gears_groundwater_extractor_readiness"}
DISCLAIMER = (
    "AGRO-AI California Compliance Pack prepares operational evidence packages only. "
    "It does not provide legal advice, certify measurement methods, guarantee compliance, "
    "file reports with regulators, or imply regulator endorsement."
)
