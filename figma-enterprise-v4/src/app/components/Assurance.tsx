const BG = "#F6F4EE";
const SURFACE = "#FFFEFA";
const BORDER = "rgba(16,35,27,0.12)";
const TEXT = "#10231B";
const MUTED = "#68776F";
const GREEN = "#16533C";
const GREEN_HOVER = "#1F7350";

type PillVariant = "warning" | "blocked" | "pending" | "review" | "missing";

function StatusPill({ label, variant }: { label: string; variant: PillVariant }) {
  const styles: Record<PillVariant, React.CSSProperties> = {
    warning: { background: "#FFFBEB", color: "#92400E", border: "1px solid #FCD34D" },
    blocked: { background: "#FEF2F2", color: "#991B1B", border: "1px solid #FECACA" },
    pending: { background: BG, color: MUTED, border: `1px solid ${BORDER}` },
    review: { background: "#EFF6FF", color: "#1D4ED8", border: "1px solid #BFDBFE" },
    missing: { background: "#FEF2F2", color: "#B42318", border: "1px solid #FECACA" },
  };
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium"
      style={styles[variant]}
    >
      {label}
    </span>
  );
}

const missingProofRows = [
  {
    requirement: "Water measurement proof",
    domain: "WaterOps",
    why: "Required for assurance export",
    status: "Approval required",
    statusVariant: "warning" as PillVariant,
    action: "Review",
  },
  {
    requirement: "Input application records",
    domain: "Input proof",
    why: "Missing supporting document set",
    status: "Pending document",
    statusVariant: "pending" as PillVariant,
    action: "Follow up",
  },
  {
    requirement: "Traceability events",
    domain: "Traceability",
    why: "Needed for lot-level proof chain",
    status: "Needs review",
    statusVariant: "review" as PillVariant,
    action: "Review",
  },
  {
    requirement: "Boundary reference",
    domain: "Farm summary",
    why: "Required for farm context",
    status: "Missing",
    statusVariant: "missing" as PillVariant,
    action: "Attach",
  },
];

export function Assurance() {
  return (
    <div className="min-h-screen" style={{ background: BG }}>
      {/* Top Bar */}
      <header
        className="h-[72px] px-8 flex items-center justify-between"
        style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}
      >
        <div>
          <div className="text-[13px] font-semibold" style={{ color: TEXT }}>
            North Coast Vineyard
          </div>
          <div className="text-[11px]" style={{ color: MUTED }}>
            Wine grapes · Coastal production block
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span
            className="text-[11px] font-medium px-2.5 py-1 rounded"
            style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}
          >
            Evaluation workspace
          </span>
          <span
            className="text-[11px] font-medium px-2.5 py-1 rounded"
            style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}
          >
            Not live
          </span>
          <button
            className="px-4 py-2 text-[13px] font-medium text-white rounded-lg transition-colors"
            style={{ background: GREEN }}
            onMouseEnter={(e) => (e.currentTarget.style.background = GREEN_HOVER)}
            onMouseLeave={(e) => (e.currentTarget.style.background = GREEN)}
          >
            Run Agent
          </button>
        </div>
      </header>

      <div className="px-8 py-6 space-y-5" style={{ maxWidth: 1220 }}>
        {/* Page header */}
        <div>
          <h1 className="text-[28px] font-semibold mb-1" style={{ color: TEXT }}>Assurance</h1>
          <p className="text-[13px]" style={{ color: MUTED }}>
            Package completeness toward reviewer handoff. Missing proof items block external use.
          </p>
        </div>

        {/* Metric row */}
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: "Readiness", value: "62%", sub: "Toward reviewer handoff" },
            { label: "Missing proof", value: "4", sub: "Required items not attached" },
            { label: "Proof domains complete", value: "3/7", sub: "Across all required domains" },
            { label: "Reviewer gates", value: "2", sub: "Pending human review" },
          ].map(({ label, value, sub }) => (
            <div
              key={label}
              className="rounded-xl p-5"
              style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
            >
              <div className="text-[11px] font-medium mb-2.5" style={{ color: MUTED }}>{label}</div>
              <div className="text-[30px] font-semibold leading-none mb-2" style={{ color: TEXT }}>{value}</div>
              <div className="text-[11px]" style={{ color: MUTED }}>{sub}</div>
            </div>
          ))}
        </div>

        {/* Main grid — 60/40 */}
        <div className="grid gap-5" style={{ gridTemplateColumns: "3fr 2fr" }}>
          {/* Missing proof queue */}
          <div
            className="rounded-xl overflow-hidden"
            style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
          >
            <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}>
              <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>
                Gap analysis
              </div>
              <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>
                Missing proof queue
              </h3>
            </div>
            {/* Table header */}
            <div
              className="grid px-6 py-2.5 gap-4"
              style={{
                gridTemplateColumns: "2fr 1fr 2fr auto auto",
                borderBottom: `1px solid ${BORDER}`,
                background: BG,
              }}
            >
              {["Requirement", "Domain", "Why it matters", "Status", "Action"].map((h) => (
                <span key={h} className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>
                  {h}
                </span>
              ))}
            </div>
            <div>
              {missingProofRows.map((row, i) => (
                <div
                  key={i}
                  className="grid px-6 py-4 gap-4 items-center"
                  style={{
                    gridTemplateColumns: "2fr 1fr 2fr auto auto",
                    borderTop: i > 0 ? `1px solid ${BORDER}` : "none",
                  }}
                >
                  <span className="text-[13px] font-medium" style={{ color: TEXT }}>{row.requirement}</span>
                  <span className="text-[12px]" style={{ color: MUTED }}>{row.domain}</span>
                  <span className="text-[12px]" style={{ color: MUTED }}>{row.why}</span>
                  <StatusPill label={row.status} variant={row.statusVariant} />
                  <button
                    className="px-3 py-1.5 text-[11px] font-medium rounded transition-colors"
                    style={{ border: `1px solid ${BORDER}`, color: TEXT, background: "transparent" }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = BG)}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                  >
                    {row.action}
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Proof coverage */}
          <div
            className="rounded-xl overflow-hidden"
            style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
          >
            <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}>
              <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>
                Coverage
              </div>
              <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>Proof coverage</h3>
            </div>
            <div className="px-6 py-5 space-y-5">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>
                  Proof present
                </div>
                <div className="space-y-2">
                  {["Controller events", "Weather context", "Crop profile"].map((item) => (
                    <div key={item} className="flex items-center gap-2.5">
                      <div
                        className="w-4 h-4 rounded-full flex items-center justify-center flex-shrink-0"
                        style={{ background: GREEN }}
                      >
                        <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
                          <path d="M1.5 4.5l1.5 1.5 3.5-3.5" stroke="white" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </div>
                      <span className="text-[13px]" style={{ color: TEXT }}>{item}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ borderTop: `1px solid ${BORDER}`, paddingTop: 16 }}>
                <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>
                  Proof missing
                </div>
                <div className="space-y-2">
                  {["Water measurement", "Input applications", "Traceability events", "Boundary reference"].map((item) => (
                    <div key={item} className="flex items-center gap-2.5">
                      <div
                        className="w-4 h-4 rounded-full flex-shrink-0"
                        style={{ background: BG, border: "1px solid rgba(180,35,24,0.3)" }}
                      />
                      <span className="text-[13px]" style={{ color: MUTED }}>{item}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ borderTop: `1px solid ${BORDER}`, paddingTop: 16 }}>
                <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>
                  Next best action
                </div>
                <p className="text-[12px]" style={{ color: TEXT }}>Attach water measurement proof.</p>
              </div>

              <div style={{ borderTop: `1px solid ${BORDER}`, paddingTop: 12 }}>
                <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: MUTED }}>
                  Human review
                </div>
                <p className="text-[12px]" style={{ color: MUTED }}>Required before external use.</p>
              </div>
            </div>
          </div>
        </div>

        {/* Reviewer-safe language */}
        <div
          className="rounded-xl px-6 py-5"
          style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
        >
          <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>
            Reviewer-safe language
          </div>
          <div className="flex flex-wrap gap-x-8 gap-y-2">
            {[
              "Draft package only",
              "Not certified",
              "Not regulator-approved",
              "Not a legal determination",
              "Human reviewer required",
            ].map((item) => (
              <div key={item} className="flex items-center gap-2">
                <div className="w-1 h-1 rounded-full flex-shrink-0" style={{ background: MUTED }} />
                <span className="text-[12px]" style={{ color: MUTED }}>{item}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
