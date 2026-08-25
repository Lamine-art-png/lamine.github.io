import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalCopy } from "../hooks/usePortalCopy";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type Readiness = {
  readiness_score: number;
  status: string;
  review_status: string;
  checklist_count: number;
  satisfied_count: number;
  pending_review_count: number;
  blocking_issues: Requirement[];
  requirements: Requirement[];
  score_explanation?: { numerator?: number; denominator?: number; formula?: string; does_not_mean?: string };
  disclaimer?: string;
};

type Requirement = {
  id?: string;
  requirement_key: string;
  title?: string;
  domain?: string;
  section_type?: string;
  status: string;
  explanation?: string;
  blocking?: boolean;
  needed_evidence_types?: string[];
  evidence_mapping_ids?: string[];
};

type PassportSummary = {
  id: string;
  farm_name: string;
  crop?: string;
  reporting_period?: string;
  status: string;
  readiness?: Readiness;
};

type PassportDetail = {
  passport: PassportSummary;
  evidence: EvidenceMapping[];
  latest_readiness: Readiness;
  review_queue?: EvidenceMapping[];
  packages?: ProofPackage[];
  disclaimer: string;
};

type EvidenceMapping = {
  id: string;
  source_kind: string;
  source_id?: string;
  evidence_type: string;
  proof_domain: string;
  mapping_status: string;
  review_status: string;
  truth_label: string;
  reporting_period?: string;
  confidence?: number;
  data_quality?: string;
  unresolved_issue?: string;
  stale_after?: string;
  source?: { title?: string; summary?: string; occurred_at?: string; assets?: Array<{ id: string; kind: string; filename?: string }> };
  queue_reason?: string;
};

type EvidenceCandidate = {
  source_kind: "canonical_evidence" | "field_observation";
  source_id: string;
  evidence_type: string;
  title?: string;
  summary?: string;
  occurred_at?: string;
  quality_status?: string;
  assets?: Array<{ id: string }>;
};

type ProofPackage = {
  id: string;
  package_type: string;
  package_version: number;
  package_status: string;
  created_at: string;
  checksum?: string;
  download_url?: string;
};

type AgentRun = {
  id: string;
  status: string;
  created_at: string;
  output: {
    summary?: string;
    gaps?: Requirement[];
    warnings?: Requirement[];
    recommended_actions?: Array<{ action_type: string; title: string; requires_human_approval?: boolean }>;
    human_review_authoritative?: boolean;
    prompt_injection_boundary?: string;
    truth_constraints?: string[];
  };
};

type RulePackOption = {
  id: string;
  title: string;
  version: string;
  customer_description?: string;
};

type ReviewAction = "accept_mapping" | "reject_mapping" | "correct_metadata" | "request_additional_proof" | "mark_not_applicable" | "reopen";
type MetadataCorrections = Partial<Record<"evidence_type" | "proof_domain" | "truth_label" | "reporting_period" | "confidence" | "data_quality" | "stale_after" | "unresolved_issue", string | number | null>>;

type Tab = "readiness" | "requirements" | "evidence" | "review" | "agent" | "packages";

function entitlementEnabled(entitlements: Record<string, unknown>, key: string, fallback = false) {
  if (entitlements.internal_testing === true || entitlements.all_features === true) return true;
  const capabilities = entitlements.capabilities;
  const value = capabilities && typeof capabilities === "object" && !Array.isArray(capabilities)
    ? (capabilities as Record<string, unknown>)[key]
    : entitlements[key];
  return value === true || value === "enabled" || value === "preview" || fallback;
}

function toneForStatus(status: string): "neutral" | "good" | "warn" | "locked" {
  if (["accepted", "ready_for_review", "ready_for_reviewer_evaluation", "mapped", "present", "not_applicable"].includes(status)) return "good";
  if (["missing", "rejected", "stale", "conflicting", "blocked", "missing_proof"].includes(status)) return "warn";
  if (["locked", "unavailable"].includes(status)) return "locked";
  return "neutral";
}

function readable(value: string) {
  return value.replaceAll("_", " ");
}

function newOperationKey(prefix: string) {
  const random = globalThis.crypto && "randomUUID" in globalThis.crypto
    ? globalThis.crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}:${random}`;
}

export function Assurance() {
  const { currentWorkspace, entitlements } = useAuth();
  const { tx } = usePortalCopy(["assurance", "shared"]);
  const workspaceId = currentWorkspace?.id || "";
  const [selectedPassportId, setSelectedPassportId] = useState("");
  const [activeTab, setActiveTab] = useState<Tab>("readiness");
  const [showCreate, setShowCreate] = useState(false);
  const [farmName, setFarmName] = useState("");
  const [crop, setCrop] = useState("");
  const [reportingPeriod, setReportingPeriod] = useState(String(new Date().getFullYear()));
  const [selectedRulePackIds, setSelectedRulePackIds] = useState<string[]>([]);
  const [candidateId, setCandidateId] = useState("");
  const [requirementKey, setRequirementKey] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [packageType, setPackageType] = useState("assurance_passport");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const packageRequest = useRef<{ scope: string; key: string } | null>(null);
  const agentRequest = useRef<{ scope: string; key: string } | null>(null);
  const canMap = entitlementEnabled(entitlements, "assurance.evidence_mapping");
  const canReview = entitlementEnabled(entitlements, "assurance.review");
  const canExport = entitlementEnabled(entitlements, "assurance.exports");
  const canCreateTask = entitlementEnabled(entitlements, "assurance.agent");
  const canRunAgent = entitlementEnabled(entitlements, "assurance.agent");

  const passports = usePortalResource<{ passports: PassportSummary[] }>(
    useCallback(async () => (await apiClient.assurance.passports(workspaceId)) as { passports: PassportSummary[] }, [workspaceId]),
    { enabled: Boolean(workspaceId) },
  );
  const rulePacks = usePortalResource<{ rule_packs: Record<string, RulePackOption> }>(
    useCallback(async () => (await apiClient.assurance.rulePacks(workspaceId)) as { rule_packs: Record<string, RulePackOption> }, [workspaceId]),
    { enabled: Boolean(workspaceId) },
  );
  const detail = usePortalResource<PassportDetail>(
    useCallback(
      async () => (await apiClient.assurance.passport(workspaceId, selectedPassportId)) as PassportDetail,
      [workspaceId, selectedPassportId],
    ),
    { enabled: Boolean(workspaceId && selectedPassportId) },
  );
  const candidates = usePortalResource<{ canonical_evidence: EvidenceCandidate[]; field_observations: EvidenceCandidate[] }>(
    useCallback(async () => (await apiClient.assurance.evidenceCandidates(workspaceId)) as { canonical_evidence: EvidenceCandidate[]; field_observations: EvidenceCandidate[] }, [workspaceId]),
    { enabled: Boolean(workspaceId && selectedPassportId && canMap) },
  );
  const proofPackages = usePortalResource<{ packages: ProofPackage[] }>(
    useCallback(async () => (await apiClient.assurance.packages(workspaceId, selectedPassportId)) as { packages: ProofPackage[] }, [workspaceId, selectedPassportId]),
    { enabled: Boolean(workspaceId && selectedPassportId && canExport) },
  );
  const reviewQueue = usePortalResource<{ review_queue: EvidenceMapping[]; events: unknown[] }>(
    useCallback(async () => (await apiClient.assurance.reviewQueue(workspaceId, selectedPassportId)) as { review_queue: EvidenceMapping[]; events: unknown[] }, [workspaceId, selectedPassportId]),
    { enabled: Boolean(workspaceId && selectedPassportId && canReview) },
  );
  const agentRuns = usePortalResource<{ runs: AgentRun[] }>(
    useCallback(async () => (await apiClient.assurance.agentRuns(workspaceId, selectedPassportId)) as { runs: AgentRun[] }, [workspaceId, selectedPassportId]),
    { enabled: Boolean(workspaceId && selectedPassportId && canRunAgent) },
  );

  const passportRows = passports.data?.passports || [];
  const readiness = detail.data?.latest_readiness || passportRows.find((row) => row.id === selectedPassportId)?.readiness;
  const allCandidates = useMemo(
    () => [...(candidates.data?.canonical_evidence || []), ...(candidates.data?.field_observations || [])],
    [candidates.data],
  );
  const selectedCandidate = allCandidates.find((item) => `${item.source_kind}:${item.source_id}` === candidateId);

  useEffect(() => {
    if (!passportRows.length) {
      setSelectedPassportId("");
      return;
    }
    if (!passportRows.some((row) => row.id === selectedPassportId)) setSelectedPassportId(passportRows[0].id);
  }, [passportRows, selectedPassportId]);

  async function refreshAll() {
    await Promise.all([
      passports.refresh({ silent: true }),
      selectedPassportId ? detail.refresh({ silent: true }) : Promise.resolve(),
      selectedPassportId ? reviewQueue.refresh({ silent: true }) : Promise.resolve(),
      selectedPassportId ? proofPackages.refresh({ silent: true }) : Promise.resolve(),
      selectedPassportId && canRunAgent ? agentRuns.refresh({ silent: true }) : Promise.resolve(),
      selectedPassportId && canMap ? candidates.refresh({ silent: true }) : Promise.resolve(),
    ]);
  }

  async function createPassport() {
    if (!farmName.trim() || !workspaceId || !selectedRulePackIds.length) return;
    setBusy("create");
    setMessage("");
    try {
      const created = await apiClient.assurance.createPassport(workspaceId, {
        farm_name: farmName.trim(), crop: crop.trim() || null, reporting_period: reportingPeriod,
        rule_pack_ids: selectedRulePackIds,
      }) as PassportDetail;
      setSelectedPassportId(created.passport.id);
      setShowCreate(false);
      setFarmName("");
      setSelectedRulePackIds([]);
      setMessage(tx("Assurance Passport created."));
      await passports.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : tx("Passport could not be created."));
    } finally {
      setBusy("");
    }
  }

  async function mapEvidence() {
    if (!selectedCandidate || !selectedPassportId) return;
    setBusy("mapping");
    setMessage("");
    try {
      await apiClient.assurance.mapEvidence(workspaceId, selectedPassportId, {
        source_kind: selectedCandidate.source_kind,
        source_id: selectedCandidate.source_id,
        evidence_type: selectedCandidate.evidence_type,
        requirement_keys: requirementKey ? [requirementKey] : [],
      });
      setCandidateId("");
      setRequirementKey("");
      setMessage(tx("Evidence mapped for human review."));
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : tx("Evidence could not be mapped."));
    } finally {
      setBusy("");
    }
  }

  async function submitReview(mappingId: string, action: ReviewAction, corrections?: MetadataCorrections) {
    if (["reject_mapping", "request_additional_proof", "mark_not_applicable"].includes(action) && !reviewNote.trim()) {
      setMessage(tx("Add a reviewer note before rejecting, requesting proof, or marking not applicable."));
      return;
    }
    setBusy(`review:${mappingId}`);
    setMessage("");
    try {
      await apiClient.assurance.review(workspaceId, selectedPassportId, {
        action, evidence_mapping_id: mappingId, reason: reviewNote.trim() || null,
        corrections: corrections || {},
      });
      setReviewNote("");
      setMessage(tx("Review decision recorded in the append-only history."));
      await refreshAll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : tx("Review decision could not be recorded."));
    } finally {
      setBusy("");
    }
  }

  async function createPackage() {
    if (!selectedPassportId) return;
    const requestScope = `${workspaceId}:${selectedPassportId}:${packageType}`;
    if (!packageRequest.current || packageRequest.current.scope !== requestScope) {
      packageRequest.current = {
        scope: requestScope,
        key: newOperationKey(`assurance-package:${selectedPassportId}:${packageType}`),
      };
    }
    setBusy("package");
    setMessage("");
    try {
      const result = await apiClient.assurance.createPackage(workspaceId, selectedPassportId, {
        package_type: packageType,
        idempotency_key: packageRequest.current.key,
      }) as ProofPackage;
      await savePackageBlob(result);
      setMessage(tx("Immutable proof package generated."));
      await proofPackages.refresh({ silent: true });
      packageRequest.current = null;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : tx("Proof package could not be generated."));
    } finally {
      setBusy("");
    }
  }

  async function savePackageBlob(item: ProofPackage) {
    const blob = await apiClient.assurance.downloadPackage(workspaceId, selectedPassportId, item.id);
    const href = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = href;
    link.download = `${item.package_type}-v${item.package_version}.pdf`;
    link.click();
    URL.revokeObjectURL(href);
  }

  async function downloadPackage(item: ProofPackage) {
    setBusy(`download:${item.id}`);
    setMessage("");
    try {
      await savePackageBlob(item);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : tx("Proof package could not be downloaded."));
    } finally {
      setBusy("");
    }
  }

  async function runAgent() {
    if (!selectedPassportId) return;
    const requestScope = `${workspaceId}:${selectedPassportId}`;
    if (!agentRequest.current || agentRequest.current.scope !== requestScope) {
      agentRequest.current = {
        scope: requestScope,
        key: newOperationKey(`assurance-agent:${selectedPassportId}`),
      };
    }
    setBusy("agent");
    setMessage("");
    try {
      await apiClient.assurance.runAgent(workspaceId, selectedPassportId, agentRequest.current.key);
      setMessage(tx("Assurance Agent triage prepared for human review."));
      await agentRuns.refresh({ silent: true });
      agentRequest.current = null;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : tx("Assurance Agent triage could not be prepared."));
    } finally {
      setBusy("");
    }
  }

  async function createTask(requirement: Requirement) {
    setBusy(`task:${requirement.requirement_key}`);
    setMessage("");
    try {
      await apiClient.assurance.createFieldTask(workspaceId, selectedPassportId, {
        requirement_key: requirement.requirement_key,
        title: `${tx("Collect proof")}: ${requirement.title || readable(requirement.requirement_key)}`,
      });
      setMessage(tx("Field task created with Assurance provenance."));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : tx("Field task could not be created."));
    } finally {
      setBusy("");
    }
  }

  if (!workspaceId) return <div className="p-6"><InlineState title={tx("Select a workspace to open Assurance.")} /></div>;

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: "readiness", label: tx("Readiness") },
    { id: "requirements", label: tx("Requirements") },
    { id: "evidence", label: tx("Evidence") },
    { id: "review", label: tx("Review") },
    { id: "agent", label: tx("Assurance Agent") },
    { id: "packages", label: tx("Proof packages") },
  ];
  const rulePackOptions = Object.values(rulePacks.data?.rule_packs || {});

  function toggleRulePack(packId: string) {
    setSelectedRulePackIds((current) => current.includes(packId)
      ? current.filter((value) => value !== packId)
      : [...current, packId]);
  }

  return (
    <div className="min-h-full" style={{ background: BG }} data-assurance-v2>
      <header className="flex flex-col gap-4 border-b px-4 py-5 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8" style={{ background: SURFACE, borderColor: BORDER }}>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ color: MUTED }}>{tx("AEP Assurance Intelligence")}</div>
          <h1 className="mt-1 text-[26px] font-semibold" style={{ color: TEXT }}>{tx("Assurance")}</h1>
          <p className="mt-1 max-w-3xl text-[13px] leading-6" style={{ color: MUTED }}>{tx("Evidence readiness decision support for human reviewer evaluation. Not certification or regulatory approval.")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label={tx("Selected Assurance Passport")}
            value={selectedPassportId}
            onChange={(event) => setSelectedPassportId(event.target.value)}
            className="min-w-[220px] rounded-lg px-3 py-2 text-[12px]"
            style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}
          >
            <option value="">{tx("Select a passport")}</option>
            {passportRows.map((passport) => <option key={passport.id} value={passport.id}>{passport.farm_name} · {passport.reporting_period || tx("No period")}</option>)}
          </select>
          <PortalButton onClick={() => setShowCreate((value) => !value)}>{tx("New passport")}</PortalButton>
        </div>
      </header>

      <div className="mx-auto w-full max-w-[1320px] space-y-5 px-4 py-5 sm:px-6 lg:px-8">
        {showCreate ? (
          <section className="rounded-xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }} aria-label={tx("Create Assurance Passport")}>
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="text-[12px] font-medium" style={{ color: TEXT }}>{tx("Farm or operation name")}<input value={farmName} onChange={(event) => setFarmName(event.target.value)} className="mt-1.5 w-full rounded-lg px-3 py-2 font-normal" style={{ border: `1px solid ${BORDER}`, background: BG }} /></label>
              <label className="text-[12px] font-medium" style={{ color: TEXT }}>{tx("Crop")}<input value={crop} onChange={(event) => setCrop(event.target.value)} className="mt-1.5 w-full rounded-lg px-3 py-2 font-normal" style={{ border: `1px solid ${BORDER}`, background: BG }} /></label>
              <label className="text-[12px] font-medium" style={{ color: TEXT }}>{tx("Reporting period")}<input value={reportingPeriod} onChange={(event) => setReportingPeriod(event.target.value)} className="mt-1.5 w-full rounded-lg px-3 py-2 font-normal" style={{ border: `1px solid ${BORDER}`, background: BG }} /></label>
            </div>
            <fieldset className="mt-4">
              <legend className="text-[12px] font-semibold" style={{ color: TEXT }}>{tx("Choose the evidence programs this passport should evaluate")}</legend>
              <p className="mt-1 text-[11px] leading-5" style={{ color: MUTED }}>{tx("Select one or more. Only the requirements from your choices will affect readiness.")}</p>
              <div className="mt-3 grid gap-3 lg:grid-cols-3">
                {rulePackOptions.map((pack) => <label key={pack.id} className="flex cursor-pointer gap-3 rounded-lg p-3" style={{ background: BG, border: `1px solid ${selectedRulePackIds.includes(pack.id) ? "#2D6A4F" : BORDER}` }}><input type="checkbox" checked={selectedRulePackIds.includes(pack.id)} onChange={() => toggleRulePack(pack.id)} /><span><span className="block text-[12px] font-semibold" style={{ color: TEXT }}>{tx(pack.title)}</span><span className="mt-1 block text-[11px] leading-5" style={{ color: MUTED }}>{tx(pack.customer_description || "Organize evidence for reviewer evaluation.")}</span></span></label>)}
              </div>
              {!rulePackOptions.length ? <div className="mt-3"><InlineState title={rulePacks.isLoading ? tx("Loading evidence programs…") : (rulePacks.error || tx("Evidence programs are unavailable."))} /></div> : null}
            </fieldset>
            <div className="mt-4 flex gap-2"><PortalButton disabled={!farmName.trim() || !selectedRulePackIds.length || busy === "create"} onClick={createPassport}>{busy === "create" ? tx("Creating…") : tx("Create passport")}</PortalButton><PortalButton variant="secondary" onClick={() => setShowCreate(false)}>{tx("Cancel")}</PortalButton></div>
          </section>
        ) : null}

        {message ? <InlineState title={message} /> : null}
        {passports.isLoading || (selectedPassportId && detail.isLoading) ? <InlineState title={tx("Loading Assurance workspace…")} /> : null}
        {passports.error ? <InlineState title={passports.error} detail={tx("The Assurance route is protected by release and commercial controls.")} /> : null}

        {!passportRows.length && !passports.isLoading && !passports.error ? (
          <InlineState title={tx("No Assurance Passports yet.")} detail={tx("Create a passport to select rule packs, map canonical evidence, and prepare reviewer-safe proof packages.")} />
        ) : null}

        {selectedPassportId && readiness ? (
          <>
            <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label={tx("Assurance metrics")}>
              <Metric label={tx("Readiness score")} value={`${readiness.readiness_score || 0}%`} detail={`${readiness.satisfied_count || 0}/${readiness.checklist_count || 0} ${tx("requirements covered")}`} />
              <Metric label={tx("Blocking issues")} value={String(readiness.blocking_issues?.length || 0)} detail={tx("Must be resolved or explicitly reviewed")} />
              <Metric label={tx("Pending review")} value={String(readiness.pending_review_count || 0)} detail={tx("Human decisions still required")} />
              <Metric label={tx("Package posture")} value={readiness.blocking_issues?.length ? tx("Draft only") : tx("Reviewer-ready")} detail={tx("Never a certification claim")} />
            </section>

            <nav className="flex gap-1 overflow-x-auto rounded-xl p-1" style={{ background: "#EAE8E0" }} aria-label={tx("Assurance sections")}>
              {tabs.map((tab) => (
                <button key={tab.id} type="button" onClick={() => setActiveTab(tab.id)} aria-current={activeTab === tab.id ? "page" : undefined} className="whitespace-nowrap rounded-lg px-4 py-2 text-[12px] font-semibold" style={{ background: activeTab === tab.id ? SURFACE : "transparent", color: activeTab === tab.id ? TEXT : MUTED }}>{tab.label}</button>
              ))}
            </nav>

            {activeTab === "readiness" ? <ReadinessPanel readiness={readiness} tx={tx} onCreateTask={createTask} canCreateTask={canCreateTask} busy={busy} /> : null}
            {activeTab === "requirements" ? <RequirementsPanel requirements={readiness.requirements || []} tx={tx} /> : null}
            {activeTab === "evidence" ? (
              <EvidencePanel
                mappings={detail.data?.evidence || []}
                candidates={allCandidates}
                requirements={readiness.requirements || []}
                candidateId={candidateId}
                requirementKey={requirementKey}
                canMap={canMap}
                busy={busy}
                tx={tx}
                onCandidate={setCandidateId}
                onRequirement={setRequirementKey}
                onMap={mapEvidence}
              />
            ) : null}
            {activeTab === "review" ? (
              <ReviewPanel
                queue={reviewQueue.data?.review_queue || detail.data?.review_queue || []}
                mappings={detail.data?.evidence || []}
                canReview={canReview}
                reviewNote={reviewNote}
                busy={busy}
                tx={tx}
                onNote={setReviewNote}
                onReview={submitReview}
              />
            ) : null}
            {activeTab === "agent" ? (
              <AgentPanel
                runs={agentRuns.data?.runs || []}
                canRun={canRunAgent}
                busy={busy}
                tx={tx}
                onRun={runAgent}
              />
            ) : null}
            {activeTab === "packages" ? (
              <PackagesPanel
                packages={proofPackages.data?.packages || []}
                packageType={packageType}
                canExport={canExport}
                busy={busy}
                tx={tx}
                onPackageType={setPackageType}
                onCreate={createPackage}
                onDownload={downloadPackage}
              />
            ) : null}
          </>
        ) : null}

        <p className="pb-4 text-[11px] leading-5" style={{ color: MUTED }}>{detail.data?.disclaimer || tx("AGRO-AI organizes supporting records for reviewer evaluation. It does not certify, approve, file, or determine legal compliance.")}</p>
      </div>
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="rounded-xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="text-[11px] font-medium" style={{ color: MUTED }}>{label}</div><div className="mt-2 text-[25px] font-semibold" style={{ color: TEXT }}>{value}</div><div className="mt-2 text-[11px] leading-5" style={{ color: MUTED }}>{detail}</div></div>;
}

function Panel({ title, eyebrow, children }: { title: string; eyebrow: string; children: ReactNode }) {
  return <section className="overflow-hidden rounded-xl" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="border-b px-5 py-4 sm:px-6" style={{ borderColor: BORDER }}><div className="text-[10px] font-semibold uppercase tracking-[0.16em]" style={{ color: MUTED }}>{eyebrow}</div><h2 className="mt-1 text-[16px] font-semibold" style={{ color: TEXT }}>{title}</h2></div><div className="p-5 sm:p-6">{children}</div></section>;
}

function ReadinessPanel({ readiness, tx, onCreateTask, canCreateTask, busy }: { readiness: Readiness; tx: (value: string) => string; onCreateTask: (item: Requirement) => void; canCreateTask: boolean; busy: string }) {
  return <Panel eyebrow={tx("Deterministic readiness")} title={tx("Why this score exists")}><div className="grid gap-5 lg:grid-cols-[1fr_1.4fr]"><div><div className="rounded-lg p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="flex items-center justify-between gap-3"><span className="text-[13px] font-semibold" style={{ color: TEXT }}>{tx("Score formula")}</span><StatusBadge label={readable(readiness.status)} tone={toneForStatus(readiness.status)} /></div><p className="mt-3 text-[12px] leading-6" style={{ color: MUTED }}>{readiness.score_explanation?.formula || tx("Covered selected requirements divided by all selected requirements.")}</p><p className="mt-2 text-[11px] leading-5" style={{ color: MUTED }}>{readiness.score_explanation?.does_not_mean || tx("This score does not mean certification or regulatory approval.")}</p></div></div><div className="space-y-3"><h3 className="text-[13px] font-semibold" style={{ color: TEXT }}>{tx("Blocking evidence gaps")}</h3>{readiness.blocking_issues?.length ? readiness.blocking_issues.map((item) => <div key={`${item.requirement_key}:${item.status}`} className="flex flex-col gap-3 rounded-lg p-4 sm:flex-row sm:items-center sm:justify-between" style={{ background: BG, border: `1px solid ${BORDER}` }}><div><div className="text-[12px] font-semibold" style={{ color: TEXT }}>{item.title || readable(item.requirement_key)}</div><div className="mt-1 text-[11px] leading-5" style={{ color: MUTED }}>{item.explanation}</div></div><div className="flex items-center gap-2"><StatusBadge label={readable(item.status)} tone="warn" /><PortalButton variant="secondary" disabled={!canCreateTask || busy === `task:${item.requirement_key}`} onClick={() => onCreateTask(item)}>{canCreateTask ? tx("Create field task") : tx("Team plan required")}</PortalButton></div></div>) : <InlineState title={tx("No blocking evidence gaps detected.")} detail={tx("Human review may still be required before external reliance.")} />}</div></div></Panel>;
}

function RequirementsPanel({ requirements, tx }: { requirements: Requirement[]; tx: (value: string) => string }) {
  return <Panel eyebrow={tx("Selected rule packs")} title={tx("Requirement matrix")}><div className="space-y-3">{requirements.map((item) => <div key={`${item.id}:${item.requirement_key}`} className="grid gap-3 rounded-lg p-4 sm:grid-cols-[1.4fr_0.7fr_auto] sm:items-center" style={{ background: BG, border: `1px solid ${BORDER}` }}><div><div className="text-[12px] font-semibold" style={{ color: TEXT }}>{item.title || readable(item.requirement_key)}</div><div className="mt-1 text-[11px] leading-5" style={{ color: MUTED }}>{item.explanation}</div></div><div className="text-[11px]" style={{ color: MUTED }}>{readable(item.domain || item.section_type || tx("Assurance"))}</div><StatusBadge label={readable(item.status)} tone={toneForStatus(item.status)} /></div>)}</div></Panel>;
}

function EvidencePanel({ mappings, candidates, requirements, candidateId, requirementKey, canMap, busy, tx, onCandidate, onRequirement, onMap }: { mappings: EvidenceMapping[]; candidates: EvidenceCandidate[]; requirements: Requirement[]; candidateId: string; requirementKey: string; canMap: boolean; busy: string; tx: (value: string) => string; onCandidate: (value: string) => void; onRequirement: (value: string) => void; onMap: () => void }) {
  return <Panel eyebrow={tx("Canonical evidence graph")} title={tx("Map evidence without duplicating source records")}><div className="rounded-lg p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="grid gap-3 lg:grid-cols-[1.4fr_1fr_auto] lg:items-end"><label className="text-[11px] font-semibold" style={{ color: TEXT }}>{tx("Evidence source")}<select value={candidateId} onChange={(event) => onCandidate(event.target.value)} disabled={!canMap} className="mt-1.5 w-full rounded-lg px-3 py-2 font-normal" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><option value="">{tx("Select canonical evidence")}</option>{candidates.map((item) => <option key={`${item.source_kind}:${item.source_id}`} value={`${item.source_kind}:${item.source_id}`}>{item.title || item.source_id} · {readable(item.source_kind)}</option>)}</select></label><label className="text-[11px] font-semibold" style={{ color: TEXT }}>{tx("Requirement")}<select value={requirementKey} onChange={(event) => onRequirement(event.target.value)} disabled={!canMap} className="mt-1.5 w-full rounded-lg px-3 py-2 font-normal" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><option value="">{tx("Match by evidence type")}</option>{requirements.map((item) => <option key={item.requirement_key} value={item.requirement_key}>{item.title || readable(item.requirement_key)}</option>)}</select></label><PortalButton disabled={!canMap || !candidateId || busy === "mapping"} onClick={onMap}>{canMap ? (busy === "mapping" ? tx("Mapping…") : tx("Map evidence")) : tx("Professional plan required")}</PortalButton></div></div><div className="mt-5 space-y-3">{mappings.length ? mappings.map((item) => <div key={item.id} className="grid gap-3 rounded-lg p-4 sm:grid-cols-[1.4fr_0.8fr_auto] sm:items-center" style={{ border: `1px solid ${BORDER}` }}><div><div className="text-[12px] font-semibold" style={{ color: TEXT }}>{item.source?.title || readable(item.evidence_type)}</div><div className="mt-1 text-[11px]" style={{ color: MUTED }}>{readable(item.source_kind)} · {item.truth_label} · {item.source?.assets?.length || 0} {tx("media references")}</div></div><div className="text-[11px]" style={{ color: MUTED }}>{item.source?.occurred_at || tx("No event timestamp")}</div><StatusBadge label={readable(item.mapping_status)} tone={toneForStatus(item.mapping_status)} /></div>) : <InlineState title={tx("No evidence mappings yet.")} detail={tx("Select a canonical Evidence Record or Field Intelligence observation above.")} />}</div></Panel>;
}

function ReviewPanel({ queue, mappings, canReview, reviewNote, busy, tx, onNote, onReview }: { queue: EvidenceMapping[]; mappings: EvidenceMapping[]; canReview: boolean; reviewNote: string; busy: string; tx: (value: string) => string; onNote: (value: string) => void; onReview: (id: string, action: ReviewAction, corrections?: MetadataCorrections) => Promise<void> }) {
  const [editingId, setEditingId] = useState("");
  const [corrections, setCorrections] = useState<MetadataCorrections>({});
  const queueIds = new Set(queue.map((item) => item.id));
  const reviewed = mappings.filter((item) => !queueIds.has(item.id) && ["accepted", "rejected", "not_applicable"].includes(item.mapping_status));

  function editField(field: keyof MetadataCorrections, value: string) {
    setCorrections((current) => ({ ...current, [field]: field === "confidence" && value !== "" ? Number(value) : value }));
  }

  async function submitCorrection(mappingId: string) {
    await onReview(mappingId, "correct_metadata", corrections);
    setEditingId("");
    setCorrections({});
  }

  function mappingCard(item: EvidenceMapping, reopenedOnly = false) {
    const isBusy = busy === `review:${item.id}`;
    return <article key={item.id} className="rounded-lg p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div><div className="text-[12px] font-semibold" style={{ color: TEXT }}>{item.source?.title || readable(item.evidence_type)}</div><div className="mt-1 text-[11px] leading-5" style={{ color: MUTED }}>{item.source?.summary || item.unresolved_issue || tx("Review the mapping, provenance, timing, and data quality.")}</div></div><StatusBadge label={readable(item.queue_reason || item.mapping_status)} tone={toneForStatus(item.queue_reason || item.mapping_status)} /></div>{reopenedOnly ? <div className="mt-4"><PortalButton variant="secondary" disabled={!canReview || isBusy} onClick={() => onReview(item.id, "reopen")}>{tx("Reopen")}</PortalButton></div> : <><div className="mt-4 flex flex-wrap gap-2"><PortalButton disabled={!canReview || isBusy} onClick={() => onReview(item.id, "accept_mapping")}>{tx("Accept mapping")}</PortalButton><PortalButton variant="secondary" disabled={!canReview || isBusy} onClick={() => onReview(item.id, "reject_mapping")}>{tx("Reject")}</PortalButton><PortalButton variant="secondary" disabled={!canReview || isBusy} onClick={() => onReview(item.id, "request_additional_proof")}>{tx("Request proof")}</PortalButton><PortalButton variant="secondary" disabled={!canReview || isBusy} onClick={() => onReview(item.id, "mark_not_applicable")}>{tx("Mark not applicable")}</PortalButton><PortalButton variant="secondary" disabled={!canReview || isBusy} onClick={() => { setEditingId(editingId === item.id ? "" : item.id); setCorrections({}); }}>{tx("Correct metadata")}</PortalButton>{["rejected", "not_applicable"].includes(item.mapping_status) ? <PortalButton variant="secondary" disabled={!canReview || isBusy} onClick={() => onReview(item.id, "reopen")}>{tx("Reopen")}</PortalButton> : null}</div>{editingId === item.id ? <div className="mt-4 rounded-lg p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="text-[11px] font-semibold" style={{ color: TEXT }}>{tx("Change only fields that need correction")}</div><div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><CorrectionInput label={tx("Evidence type")} placeholder={item.evidence_type} value={corrections.evidence_type} onChange={(value) => editField("evidence_type", value)} /><CorrectionInput label={tx("Proof domain")} placeholder={item.proof_domain} value={corrections.proof_domain} onChange={(value) => editField("proof_domain", value)} /><label className="text-[11px] font-semibold" style={{ color: TEXT }}>{tx("Truth label")}<select value={String(corrections.truth_label ?? "")} onChange={(event) => editField("truth_label", event.target.value)} className="mt-1.5 w-full rounded-lg px-3 py-2 font-normal" style={{ background: BG, border: `1px solid ${BORDER}` }}><option value="">{tx("Keep current")}</option><option value="measured">{tx("Measured")}</option><option value="reported">{tx("Reported")}</option><option value="estimated">{tx("Estimated")}</option><option value="calculated">{tx("Calculated")}</option><option value="AI-inferred">{tx("AI-inferred")}</option></select></label><CorrectionInput label={tx("Reporting period")} placeholder={item.reporting_period || tx("Not set")} value={corrections.reporting_period} onChange={(value) => editField("reporting_period", value)} /><CorrectionInput label={tx("Confidence (0 to 1)")} type="number" placeholder="0.00" value={corrections.confidence} onChange={(value) => editField("confidence", value)} /><CorrectionInput label={tx("Data quality")} placeholder={item.data_quality || tx("Unknown")} value={corrections.data_quality} onChange={(value) => editField("data_quality", value)} /><CorrectionInput label={tx("Stale after")} type="datetime-local" placeholder={item.stale_after || ""} value={corrections.stale_after} onChange={(value) => editField("stale_after", value)} /><CorrectionInput label={tx("Unresolved issue")} placeholder={item.unresolved_issue || tx("None")} value={corrections.unresolved_issue} onChange={(value) => editField("unresolved_issue", value)} /></div><div className="mt-3 flex gap-2"><PortalButton disabled={!Object.keys(corrections).length || isBusy} onClick={() => submitCorrection(item.id)}>{tx("Record correction")}</PortalButton><PortalButton variant="secondary" onClick={() => { setEditingId(""); setCorrections({}); }}>{tx("Cancel")}</PortalButton></div></div> : null}</>}</article>;
  }

  const queuedCards = queue.map((item) => mappingCard(item));
  const reviewedCards = reviewed.map((item) => mappingCard(item, true));
  return <Panel eyebrow={tx("Human review workflow")} title={tx("Evidence mapping review queue")}><label className="block text-[11px] font-semibold" style={{ color: TEXT }}>{tx("Reviewer note")}<textarea value={reviewNote} onChange={(event) => onNote(event.target.value)} rows={3} className="mt-1.5 w-full rounded-lg px-3 py-2 font-normal" style={{ background: BG, border: `1px solid ${BORDER}` }} placeholder={tx("Explain a rejection, request for proof, or not-applicable decision.")} /></label><div className="mt-5 space-y-3">{queue.length ? queuedCards : <InlineState title={tx("Review queue is clear.")} detail={tx("Accepted decisions remain in append-only review history.")} />}</div>{reviewed.length ? <div className="mt-6"><h3 className="text-[12px] font-semibold" style={{ color: TEXT }}>{tx("Completed decisions")}</h3><p className="mt-1 text-[11px]" style={{ color: MUTED }}>{tx("Reopen a completed mapping when new information requires another review.")}</p><div className="mt-3 space-y-3">{reviewedCards}</div></div> : null}{!canReview ? <div className="mt-4"><InlineState title={tx("Team plan required for reviewer decisions.")} detail={tx("Readiness remains visible, but review mutations are enforced by the backend entitlement gate.")} /></div> : null}</Panel>;
}

function CorrectionInput({ label, value, placeholder, type = "text", onChange }: { label: string; value: string | number | null | undefined; placeholder: string; type?: string; onChange: (value: string) => void }) {
  return <label className="text-[11px] font-semibold" style={{ color: TEXT }}>{label}<input type={type} min={type === "number" ? 0 : undefined} max={type === "number" ? 1 : undefined} step={type === "number" ? 0.01 : undefined} value={value ?? ""} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} className="mt-1.5 w-full rounded-lg px-3 py-2 font-normal" style={{ background: BG, border: `1px solid ${BORDER}` }} /></label>;
}

function AgentPanel({ runs, canRun, busy, tx, onRun }: { runs: AgentRun[]; canRun: boolean; busy: string; tx: (value: string) => string; onRun: () => void }) {
  const latest = runs[0];
  return <Panel eyebrow={tx("Controlled intelligence workflow")} title={tx("Assurance Agent triage")}><div className="flex flex-col gap-3 rounded-lg p-4 sm:flex-row sm:items-center sm:justify-between" style={{ background: BG, border: `1px solid ${BORDER}` }}><div><p className="text-[12px] font-semibold" style={{ color: TEXT }}>{tx("Classify mappings, detect gaps and conflicts, and propose reviewer-safe next actions.")}</p><p className="mt-1 text-[11px] leading-5" style={{ color: MUTED }}>{tx("Uploaded evidence is untrusted data. Human review remains authoritative; the Agent cannot certify, approve, send, or execute physical work.")}</p></div><PortalButton disabled={!canRun || busy === "agent"} onClick={onRun}>{canRun ? (busy === "agent" ? tx("Preparing triage…") : tx("Run deterministic triage")) : tx("Team plan required")}</PortalButton></div>{latest ? <div className="mt-5 space-y-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><div className="text-[12px] font-semibold" style={{ color: TEXT }}>{latest.output.summary}</div><div className="mt-1 text-[11px]" style={{ color: MUTED }}>{new Date(latest.created_at).toLocaleString()}</div></div><StatusBadge label={latest.output.human_review_authoritative ? tx("Human review authoritative") : readable(latest.status)} tone="neutral" /></div><div className="grid gap-3 lg:grid-cols-2"><div className="rounded-lg p-4" style={{ border: `1px solid ${BORDER}` }}><div className="text-[11px] font-semibold" style={{ color: TEXT }}>{tx("Detected gaps and conflicts")}</div><div className="mt-3 space-y-2">{latest.output.gaps?.length ? latest.output.gaps.map((item) => <div key={`${item.requirement_key}:${item.status}`} className="flex items-center justify-between gap-2 text-[11px]" style={{ color: MUTED }}><span>{item.title || readable(item.requirement_key)}</span><StatusBadge label={readable(item.status)} tone="warn" /></div>) : <span className="text-[11px]" style={{ color: MUTED }}>{tx("No blocking gaps detected in this run.")}</span>}</div></div><div className="rounded-lg p-4" style={{ border: `1px solid ${BORDER}` }}><div className="text-[11px] font-semibold" style={{ color: TEXT }}>{tx("Proposed next actions")}</div><div className="mt-3 space-y-2">{latest.output.recommended_actions?.map((item) => <div key={`${item.action_type}:${item.title}`} className="text-[11px] leading-5" style={{ color: MUTED }}>{item.title} · {tx("requires human confirmation")}</div>)}</div></div></div></div> : <div className="mt-5"><InlineState title={tx("No Assurance Agent runs yet.")} detail={tx("A run reads only server-owned mappings and deterministic readiness state; evidence text cannot change its rules.")} /></div>}</Panel>;
}

function PackagesPanel({ packages, packageType, canExport, busy, tx, onPackageType, onCreate, onDownload }: { packages: ProofPackage[]; packageType: string; canExport: boolean; busy: string; tx: (value: string) => string; onPackageType: (value: string) => void; onCreate: () => void; onDownload: (item: ProofPackage) => void }) {
  return <Panel eyebrow={tx("Immutable outputs")} title={tx("Reviewer-safe proof packages")}><div className="flex flex-col gap-3 rounded-lg p-4 sm:flex-row sm:items-end" style={{ background: BG, border: `1px solid ${BORDER}` }}><label className="flex-1 text-[11px] font-semibold" style={{ color: TEXT }}>{tx("Package type")}<select value={packageType} onChange={(event) => onPackageType(event.target.value)} disabled={!canExport} className="mt-1.5 w-full rounded-lg px-3 py-2 font-normal" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><option value="assurance_passport">{tx("Assurance Passport")}</option><option value="water_evidence_pack">{tx("Water evidence pack")}</option><option value="buyer_proof_pack">{tx("Buyer proof pack")}</option><option value="input_application_record_pack">{tx("Input application record pack")}</option><option value="operational_execution_pack">{tx("Operational execution pack")}</option></select></label><PortalButton disabled={!canExport || busy === "package"} onClick={onCreate}>{canExport ? (busy === "package" ? tx("Generating…") : tx("Generate PDF snapshot")) : tx("Professional plan required")}</PortalButton></div><div className="mt-5 space-y-3">{packages.length ? packages.map((item) => <div key={item.id} className="grid gap-3 rounded-lg p-4 sm:grid-cols-[1.2fr_0.5fr_0.8fr_auto_auto] sm:items-center" style={{ border: `1px solid ${BORDER}` }}><div className="text-[12px] font-semibold" style={{ color: TEXT }}>{readable(item.package_type)}</div><div className="text-[11px]" style={{ color: MUTED }}>{tx("Version")} {item.package_version}</div><div className="text-[11px]" style={{ color: MUTED }}>{new Date(item.created_at).toLocaleString()}</div><StatusBadge label={readable(item.package_status)} tone={toneForStatus(item.package_status)} /><PortalButton variant="secondary" disabled={busy === `download:${item.id}`} onClick={() => onDownload(item)}>{busy === `download:${item.id}` ? tx("Downloading…") : tx("Download")}</PortalButton></div>) : <InlineState title={tx("No proof packages generated yet.")} detail={tx("Each generated package preserves rule-pack versions, evidence references, checksum, and review posture.")} />}</div></Panel>;
}
