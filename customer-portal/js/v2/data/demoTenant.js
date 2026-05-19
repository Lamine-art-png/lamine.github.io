export function demoSeedData() {
  const organizations = [{ id: "org_demo", name: "Demo Organization" }];
  const farms = [
    { id: "farm_alpha", organizationId: "org_demo", name: "Alpha Vineyard", provider: "WiseConn", crop: "Grape", soil: "Loam", waterStatus: "Stable", sensorStatus: "Healthy" },
    { id: "farm_delta", organizationId: "org_demo", name: "Delta Almonds", provider: "Talgil", crop: "Almond", soil: "Clay loam", waterStatus: "Watch", sensorStatus: "Partial" },
    { id: "farm_west", organizationId: "org_demo", name: "West Citrus", provider: "WiseConn", crop: "Citrus", soil: "Sandy loam", waterStatus: "Stable", sensorStatus: "Healthy" },
  ];
  const fields = [
    { id: "field_a1", farmId: "farm_alpha", name: "North Block", crop: "Cabernet", soil: "Loam" },
    { id: "field_d1", farmId: "farm_delta", name: "East Pivot", crop: "Almond", soil: "Clay loam" },
    { id: "field_w1", farmId: "farm_west", name: "Citrus East", crop: "Citrus", soil: "Sandy loam" },
  ];
  const zones = [
    { id: "zone_162803", fieldId: "field_a1", farmId: "farm_alpha", name: "Zone 162803", provider: "WiseConn", sensorCount: 8, dataQuality: "Good", executionStatus: "scheduled", observedOutcome: "Pending" },
    { id: "zone_tg_993", fieldId: "field_d1", farmId: "farm_delta", name: "Target 993", provider: "Talgil", sensorCount: 5, dataQuality: "Moderate", executionStatus: "recommended", observedOutcome: "Pending" },
    { id: "zone_98123", fieldId: "field_w1", farmId: "farm_west", name: "Zone 98123", provider: "WiseConn", sensorCount: 7, dataQuality: "Good", executionStatus: "verified", observedOutcome: "Moisture recovered" },
  ];

  const recommendations = [
    { id: "rec_1", zoneId: "zone_162803", farmId: "farm_alpha", recommendation: "Irrigate at 05:30 for 34 min", priority: "high", confidence: 86, status: "scheduled", source: "WiseConn live", createdAt: "2026-04-27T04:30:00Z", keyDrivers: ["ET rise", "Soil moisture decline"], limitations: ["Wind model pending"], executionSteps: ["Queue irrigation", "Confirm valve pressure"], verificationPlan: "Observe canopy and sensor rebound after 2h." },
    { id: "rec_2", zoneId: "zone_tg_993", farmId: "farm_delta", recommendation: "Irrigate at 06:10 for 22 min", priority: "medium", confidence: 74, status: "recommended", source: "Talgil live", createdAt: "2026-04-27T03:50:00Z", keyDrivers: ["Temperature increase", "Controller telemetry"], limitations: ["One sensor intermittent"], executionSteps: ["Schedule run", "Verify flow"], verificationPlan: "Capture soil probe trend at +90 min." },
    { id: "rec_3", zoneId: "zone_98123", farmId: "farm_west", recommendation: "Maintain current schedule", priority: "low", confidence: 91, status: "verified", source: "WiseConn live", createdAt: "2026-04-26T20:10:00Z", keyDrivers: ["Stable ET", "Recent applied event"], limitations: [], executionSteps: ["No new run"], verificationPlan: "Continue daily checks." },
  ];

  const verificationLogs = [
    { id: "v1", recommendationId: "rec_1", zoneId: "zone_162803", stage: "scheduled", by: "Ravi Kumar", at: "2026-04-27T04:45:00Z", changed: "Morning run scheduled", outcome: "Pending", note: "Ops queue accepted." },
    { id: "v2", recommendationId: "rec_3", zoneId: "zone_98123", stage: "verified", by: "Elena Ruiz", at: "2026-04-26T23:00:00Z", changed: "Confirmed no extra run", outcome: "Moisture stable", note: "No stress signals." },
  ];

  const providerConnections = [
    { id: "p_wiseconn", provider: "WiseConn", state: "connected", health: "Healthy", lastSync: "2026-04-27T04:40:00Z", farmsSynced: 2, zonesDiscovered: 15, sensorCount: 46, status: "Connected source live" },
    { id: "p_talgil", provider: "Talgil", state: "syncing", health: "Degraded", lastSync: "2026-04-27T04:10:00Z", farmsSynced: 1, zonesDiscovered: 6, sensorCount: 19, status: "Syncing controller mapping" },
  ];

  const auditLogs = [
    { id: "a1", action: "login", actor: "Elena Ruiz", at: "2026-04-27T03:55:00Z", metadata: "owner session created" },
    { id: "a2", action: "provider_connection", actor: "Platform", at: "2026-04-27T04:12:00Z", metadata: "Talgil sync started" },
    { id: "a3", action: "recommendation_generation", actor: "Intelligence Engine", at: "2026-04-27T04:30:00Z", metadata: "rec_1 generated" },
    { id: "a4", action: "verification_submission", actor: "Ravi Kumar", at: "2026-04-27T04:45:00Z", metadata: "rec_1 moved to scheduled" },
  ];

  const memberships = [
    { id: "m1", organizationId: "org_demo", userId: "u1", role: "owner" },
    { id: "m2", organizationId: "org_demo", userId: "u2", role: "farm_manager" },
    { id: "m3", organizationId: "org_demo", userId: "u3", role: "operator" },
    { id: "m4", organizationId: "org_demo", userId: "u4", role: "viewer" },
  ];

  const reports = [
    { id: "r1", name: "Water efficiency report", cadence: "weekly", updatedAt: "2026-04-27T02:00:00Z" },
    { id: "r2", name: "Recommendation execution report", cadence: "monthly", updatedAt: "2026-04-26T21:30:00Z" },
    { id: "r3", name: "Verification compliance report", cadence: "quarterly", updatedAt: "2026-04-25T18:20:00Z" },
    { id: "r4", name: "Farm performance report", cadence: "weekly", updatedAt: "2026-04-27T01:00:00Z" },
    { id: "r5", name: "Decision confidence report", cadence: "monthly", updatedAt: "2026-04-26T22:10:00Z" },
  ];

  return { organizations, farms, fields, zones, recommendations, verificationLogs, providerConnections, auditLogs, memberships, reports };
}
