// Map the backend's security-audit reason codes to an existing, translated
// customer-facing instruction. Never expose internal scores or weaken gating.
// All displayed messages below already exist in the production locale source.
export type RegistrationStep = 1 | 2 | 3;
export type RegistrationGuidance = { step: RegistrationStep; message: string };
const BY_REASON: Record<string, RegistrationGuidance> = {
  disposable_email_domain: { step: 1, message: "Please provide stronger organization or operational evidence." },
  invalid_name: { step: 1, message: "Complete your account and organization details to continue." },
  unverifiable_organization_name: { step: 1, message: "Complete your account and organization details to continue." },
  unsupported_organization_type: { step: 1, message: "Select organization type" },
  organization_evidence_required: { step: 1, message: "At least one verifiable website or professional profile is required." },
  consumer_email_requires_public_profile: { step: 1, message: "At least one verifiable website or professional profile is required." },
  email_website_domain_mismatch: { step: 1, message: "Please provide stronger organization or operational evidence." },
  professional_role_required: { step: 2, message: "Complete the operating details to continue." },
  valid_phone_required: { step: 2, message: "Complete the operating details to continue." },
  consumer_email_requires_phone: { step: 2, message: "Complete the operating details to continue." },
  country_required: { step: 2, message: "Complete the operating details to continue." },
  operating_region_required: { step: 2, message: "Complete the operating details to continue." },
  operational_scale_required: { step: 2, message: "Complete the operating details to continue." },
  consumer_email_requires_operational_scale: { step: 2, message: "Complete the operating details to continue." },
  agricultural_segment_required: { step: 2, message: "Complete the operating details to continue." },
  detailed_use_case_required: { step: 3, message: "Use at least 12 characters." },
  agricultural_use_case_not_detected: { step: 3, message: "Genuine agricultural use case" },
  data_sources_required: { step: 3, message: "Planned data sources" },
  complete_organization_verification_required: { step: 1, message: "Complete your account and organization details to continue." },
};
const FIELD_STEP: Record<string, RegistrationStep> = {
  name: 1, email: 1, password: 1, organization_name: 1,
  organization_type: 1, website_url: 1, professional_profile_url: 1,
  terms_accepted: 1, authority_confirmed: 1, terms_version: 1,
  privacy_version: 1, professional_role: 2, phone_number: 2,
  country: 2, operating_region: 2, acres_or_sites: 2, primary_crops: 2,
  intended_use: 3, planned_data_sources: 3, workspace_name: 3,
};
function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}
export function explainRegistrationError(error: unknown): RegistrationGuidance | null {
  const raw = asObject(error);
  const response = asObject(raw?.details);
  if (!response) return null;
  const detail = response.detail;
  if (Array.isArray(detail)) {
    // Pydantic 422 responses list paths such as ["body", "phone_number"].
    for (const issue of detail) {
      const location = asObject(issue)?.loc;
      if (!Array.isArray(location)) continue;
      for (const field of location) {
        if (typeof field === "string" && field in FIELD_STEP) {
          const step = FIELD_STEP[field];
          return { step, message: step === 1
            ? "Complete your account and organization details to continue."
            : step === 2 ? "Complete the operating details to continue." : "Genuine agricultural use case" };
        }
      }
    }
    return { step: 1, message: "Complete your account and organization details to continue." };
  }
  const info = asObject(detail);
  if (!info) return null;
  if (info.code === "password_policy_failed" || info.code === "legal_acceptance_required") {
    return { step: 1, message: typeof info.message === "string" ? info.message : "Complete your account and organization details to continue." };
  }
  if (info.code !== "organization_verification_rejected") return null;
  const reasons = Array.isArray(info.reason_codes) ? info.reason_codes : [];
  for (const reason of reasons) {
    if (typeof reason === "string" && reason in BY_REASON) return BY_REASON[reason];
  }
  return { step: 2, message: "Please provide stronger organization or operational evidence." };
}
