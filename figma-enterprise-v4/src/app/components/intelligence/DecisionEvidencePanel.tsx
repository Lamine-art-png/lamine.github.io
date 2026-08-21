import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, CircleHelp, FlaskConical, ShieldCheck } from "lucide-react";
import { BG, BORDER, MUTED, TEXT } from "../portalUi";
import { asArray, AnyRecord, safeText } from "./intelligenceSupport";

export function DecisionEvidencePanel({ details, t }: { details: AnyRecord; t: (key: string) => string }) {
  if (!details || typeof details !== "object") return null;

  const graph = details.intelligence_graph && typeof details.intelligence_graph === "object" ? details.intelligence_graph : {};
  const facts = asArray(details.evidence_used) as AnyRecord[];
  const derived = asArray(details.derived_findings) as AnyRecord[];
  const hypotheses = asArray(details.hypotheses) as AnyRecord[];
  const missing = asArray(details.missing_evidence) as AnyRecord[];
  const conflicts = asArray(details.conflicts) as AnyRecord[];
  const verification = asArray(details.verification_plan) as AnyRecord[];
  const scienceChecks = asArray(graph.science_checks) as AnyRecord[];
  const sourceHealth = graph.source_health && typeof graph.source_health === "object" ? graph.source_health as AnyRecord : {};
  const confidenceScore = typeof details.confidence_score === "number"
    ? details.confidence_score
    : typeof graph.grounding_confidence === "number"
      ? graph.grounding_confidence
      : undefined;
  const confidenceLabel = safeText(details.confidence, "low");
  const evidenceCount = Number(sourceHealth.direct_or_source_count || facts.length || 0);
  const conflictCount = Number(sourceHealth.conflict_count || conflicts.length || 0);

  const hasDetail = Boolean(facts.length || derived.length || hypotheses.length || missing.length || conflicts.length || verification.length || scienceChecks.length);
  if (!hasDetail) return null;

  return (
    <details className="mt-4 whitespace-normal rounded-xl" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-3 sm:px-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[12px] font-semibold" style={{ color: TEXT }}>
            <ShieldCheck size={15} /> {t("intelligence.reasoning.title")}
          </div>
          <div className="mt-1 text-[11px] leading-relaxed" style={{ color: MUTED }}>{t("intelligence.reasoning.subtitle")}</div>
        </div>
        <ChevronDown size={16} className="flex-shrink-0" style={{ color: MUTED }} />
      </summary>

      <div className="border-t px-3 pb-4 pt-3 sm:px-4" style={{ borderColor: BORDER }}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric label={t("intelligence.reasoning.confidence")} value={confidenceScore === undefined ? confidenceLabel : `${Math.round(confidenceScore * 100)}%`} />
          <Metric label={t("intelligence.reasoning.evidence")} value={String(evidenceCount)} />
          <Metric label={t("intelligence.reasoning.conflicts")} value={String(conflictCount)} warning={conflictCount > 0} />
          <Metric label={t("intelligence.reasoning.science")} value={String(scienceChecks.length)} />
        </div>

        {facts.length ? <ReasoningSection icon={<ShieldCheck size={14} />} title={t("intelligence.reasoning.facts")} rows={facts.map((row) => safeText(row.claim || row.statement))} /> : null}
        {derived.length || scienceChecks.length ? (
          <ReasoningSection
            icon={<FlaskConical size={14} />}
            title={t("intelligence.reasoning.derived")}
            rows={[
              ...derived.map((row) => safeText(row.claim)),
              ...scienceChecks.map((row) => formatScienceCheck(row)),
            ].filter(Boolean)}
          />
        ) : null}
        {conflicts.length ? <ReasoningSection icon={<AlertTriangle size={14} />} title={t("intelligence.reasoning.conflicts")} rows={conflicts.map((row) => safeText(row.summary || row.reason))} warning /> : null}
        {hypotheses.length || missing.length ? (
          <ReasoningSection
            icon={<CircleHelp size={14} />}
            title={t("intelligence.reasoning.uncertainty")}
            rows={[
              ...hypotheses.map((row) => safeText(row.claim)),
              ...missing.map((row) => safeText(row.item || row.why_it_matters || row)),
            ].filter(Boolean)}
          />
        ) : null}
        {verification.length ? (
          <ReasoningSection
            icon={<CheckCircle2 size={14} />}
            title={t("intelligence.reasoning.verify")}
            rows={verification.map((row) => {
              const action = safeText(row.action);
              const check = safeText(row.verification);
              return action && check ? `${action}: ${check}` : check || action;
            }).filter(Boolean)}
          />
        ) : null}
      </div>
    </details>
  );
}

function Metric({ label, value, warning = false }: { label: string; value: string; warning?: boolean }) {
  return (
    <div className="rounded-lg px-3 py-2" style={{ background: "rgba(255,255,255,0.78)", border: `1px solid ${BORDER}` }}>
      <div className="text-[10px] font-medium" style={{ color: MUTED }}>{label}</div>
      <div className="mt-1 text-[14px] font-semibold" style={{ color: warning ? "#92400E" : TEXT }}>{value}</div>
    </div>
  );
}

function ReasoningSection({ icon, title, rows, warning = false }: { icon: ReactNode; title: string; rows: string[]; warning?: boolean }) {
  const visible = rows.filter(Boolean).slice(0, 8);
  if (!visible.length) return null;
  return (
    <section className="mt-4">
      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.06em]" style={{ color: warning ? "#92400E" : MUTED }}>
        {icon} {title}
      </div>
      <div className="mt-2 space-y-1.5">
        {visible.map((row, index) => (
          <div key={`${title}-${index}`} className="text-[12px] leading-relaxed" style={{ color: TEXT }}>• {row}</div>
        ))}
      </div>
    </section>
  );
}

function formatScienceCheck(row: AnyRecord): string {
  const name = safeText(row.name || row.rule_id);
  const value = row.value;
  const unit = safeText(row.unit);
  if (value === null || value === undefined || value === "") return name;
  return `${name}: ${value}${unit ? ` ${unit}` : ""}`;
}
