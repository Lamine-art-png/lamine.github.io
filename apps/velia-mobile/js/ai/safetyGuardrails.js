export const safetyGuardrails = {
  apply(decision, context = {}) {
    const warnings = [];
    const patched = { ...decision };

    if ((decision.reasons || []).some((r) => /exact soil moisture/i.test(r))) {
      patched.reasons = decision.reasons.filter((r) => !/exact soil moisture/i.test(r));
      warnings.push("Removed unsupported exact moisture claim.");
    }

    if (context.weather?.stale) warnings.push("Weather data may be stale.");
    if ((decision.missingData || []).length > 0) warnings.push("Data is incomplete; recommendation confidence reduced.");
    if (decision.confidenceScore < 0.5 && !decision.fieldChecks.includes("Check field conditions before irrigating")) {
      patched.fieldChecks = [...decision.fieldChecks, "Check field conditions before irrigating"];
    }

    patched.guardrailWarnings = warnings;
    patched.disclaimer = "Recommendation support only. Always validate in-field conditions.";
    return patched;
  },
};
