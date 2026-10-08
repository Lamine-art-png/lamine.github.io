/** Friendly, step-specific guidance for server-side signup decisions.
 * Never display private scoring internals. Keep client and server in sync.
 */
export type SignupStep = 1 | 2 | 3;
type RegistrationIssue = { step: SignupStep; message: string };
const issues: Record<string, RegistrationIssue> = {
  disposable_email_domain: { step: 1, message: "Use a real email address. Personal Gmail and Outlook accounts are welcome, but temporary inboxes are not." },
  invalid_name: { step: 1, message: "Enter your real full name." },
  unverifiable_organization_name: { step: 1, message: "Enter your organization's real name." },
  unsupported_organization_type: { step: 1, message: "Choose the agricultural organization type that best describes you." },
  organization_evidence_required: { step: 1, message: "Add one public organization website or professional profile link (for example LinkedIn)." },
  consumer_email_requires_public_profile: { step: 1, message: "When using a personal email, add a verifiable organization website or professional profile." },
  email_website_domain_mismatch: { step: 1, message: "Check that your website belongs to your organization." },
  professional_role_required: { step: 2, message: "Enter your job or professional role (for example Farm Manager)." },
  valid_phone_required: { step: 2, message: "Enter a phone number with 8–15 digits, including your country code." },
  consumer_email_requires_phone: { step: 2, message: "A phone number is required when using a personal email." },
  country_required: { step: 2, message: "Enter your country." },
  operating_region_required: { step: 2, message: "Enter the region where you work." },
  operational_scale_required: { step: 2, message: "Enter an approximate operation size, such as 3 sites or 500 hectares." },
  consumer_email_requires_operational_scale: { step: 2, message: "Add an approximate number of acres, hectares, sites, or customers served." },
  agricultural_segment_required: { step: 2, message: "Name a crop or agricultural segment, such as Rice or Irrigation." },
  detailed_use_case_required: { step: 3, message: "Briefly describe a real goal in at least 12 characters. For example: Plan irrigation." },
  agricultural_use_case_not_detected: { step: 3, message: "Explain how you intend to use AGRO-AI for an agricultural task." },
  data_sources_required: { step: 3, message: "If you list data sources, name one (for example CSV or Excel), or leave this optional field empty." },
  complete_organization_verification_required: { step: 1, message: "Complete the required identity, operation, and use-case fields before submitting." },
};
const fieldNames: Record<string, RegistrationIssue> = {
  name: { step: 1, message: "Enter your full name." },
  email: { step: 1, message: "Enter a valid email address." },
  password: { step: 1, message: "Use a password with at least 12 characters and no email name." },
  organization_name: { step: 1, message: "Enter your organization name (at least 2 characters)." },
  workspace_name: { step: 3, message: "Enter a workspace name (at least 2 characters), or keep the default." },
  locale: { step: 1, message: "Select a supported language." },
};
export function explainRegistrationError(cause: unknown): RegistrationIssue | null {
  if (!cause || typeof cause !== "object") return null;
  const data = (cause as { details?: unknown }).details;
  if (!data || typeof data !== "object") return null;
  const detail = (data as { detail?: unknown }).detail;
  if (Array.isArray(detail)) {
    for (const item of detail) {
      if (!item || typeof item !== "object") continue;
      const loc = (item as { loc?: unknown }).loc;
      if (!Array.isArray(loc)) continue;
      for (const field of loc) {
        if (typeof field === "string" && field in fieldNames) return fieldNames[field];
      }
    }
    return { step: 1, message: "Check the information you entered and try again." };
  }
  if (!detail || typeof detail !== "object") return null;
  const object = detail as { code?: unknown; reason_codes?: unknown };
  if (object.code === "legal_acceptance_required") return {
    step: 1, message: "Accept the Terms of Service, acknowledge the Privacy Policy and confirm your authority to continue.",
  };
  if (object.code === "password_policy_failed") return fieldNames.password;
  if (object.code !== "organization_verification_rejected") return null;
  const reasons = Array.isArray(object.reason_codes) ? object.reason_codes : [];
  for (const reason of reasons) {
    if (typeof reason === "string" && reason in issues) return issues[reason];
  }
  return {
    step: 1,
    message: "We couldn't verify the details submitted. Review the fields or contact AGRO-AI support for an alternative verification method.",
  };
}
