import { ImageWithFallback } from "./figma/ImageWithFallback";
import wiseconnLogo from "../../imports/wiseconn-logo-1.png";
import talgilLogo from "../../imports/talgil-logo-1.png";

const BG = "#F6F4EE";
const SURFACE = "#FFFEFA";
const BORDER = "rgba(16,35,27,0.12)";
const TEXT = "#10231B";
const MUTED = "#68776F";
const GREEN = "#16533C";
const GREEN_HOVER = "#1F7350";

type PillVariant = "warning" | "blocked" | "pending" | "review";

function StatusPill({ label, variant }: { label: string; variant: PillVariant }) {
  const styles: Record<PillVariant, React.CSSProperties> = {
    warning: { background: "#FFFBEB", color: "#92400E", border: "1px solid #FCD34D" },
    blocked: { background: "#FEF2F2", color: "#991B1B", border: "1px solid #FECACA" },
    pending: { background: BG, color: MUTED, border: `1px solid ${BORDER}` },
    review: { background: "#EFF6FF", color: "#1D4ED8", border: "1px solid #BFDBFE" },
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

const workQueue = [
  {
    title: "Attach water measurement proof",
    reason: "Required for assurance export",
    status: "Approval required",
    statusVariant: "warning" as PillVariant,
    action: "Review",
  },
  {
    title: "Request input application records",
    reason: "Missing supporting document set",
    status: "Pending document",
    statusVariant: "pending" as PillVariant,
    action: "Follow up",
  },
  {
    title: "Prepare proof package draft",
    reason: "Draft export ready after missing proof is resolved",
    status: "Blocked",
    statusVariant: "blocked" as PillVariant,
    action: "Open",
  },
  {
    title: "Review traceability mapping",
    reason: "Evidence linked but not reviewer-checked",
    status: "Needs review",
    statusVariant: "review" as PillVariant,
    action: "Review",
  },
];

const pipelineSteps = [
  { label: "Ingest", done: true },
  { label: "Normalize", done: true },
  { label: "Classify", done: true },
  { label: "Detect gaps", done: true },
  { label: "Propose actions", done: false, badge: "Pending" },
  { label: "Human review", done: false, badge: "Review" },
];

export function Overview() {
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
          <span className="text-[11px]" style={{ color: MUTED }}>
            Updated a few minutes ago
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

      {/* Page content */}
      <div className="px-8 py-6 space-y-5" style={{ maxWidth: 1220 }}>

        {/* Summary card + AI panel */}
        <div className="grid gap-5" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <div
            className="rounded-xl p-7"
            style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
          >
            <div
              className="text-[10px] font-semibold uppercase tracking-widest mb-3"
              style={{ color: MUTED }}
            >
              AGRO-AI Enterprise Portal
            </div>
            <h2
              className="text-[22px] font-semibold leading-snug mb-2"
              style={{ color: TEXT }}
            >
              Operational overview
            </h2>
            <p className="text-[13px] leading-relaxed mb-6" style={{ color: MUTED }}>
              Monitor proof coverage, water decisions, assurance readiness, and
              agent-assisted work in one workspace.
            </p>
            <div className="flex items-center gap-2">
              <button
                className="px-4 py-2 text-[12px] font-medium text-white rounded-lg transition-colors"
                style={{ background: GREEN }}
                onMouseEnter={(e) => (e.currentTarget.style.background = GREEN_HOVER)}
                onMouseLeave={(e) => (e.currentTarget.style.background = GREEN)}
              >
                Run Agent
              </button>
              <button
                className="px-4 py-2 text-[12px] font-medium rounded-lg transition-colors"
                style={{ border: `1px solid ${BORDER}`, color: TEXT, background: "transparent" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = BG)}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                Attach Evidence
              </button>
              <button
                className="px-4 py-2 text-[12px] font-medium rounded-lg transition-colors"
                style={{ border: `1px solid ${BORDER}`, color: TEXT, background: "transparent" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = BG)}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                Prepare Export
              </button>
            </div>
          </div>

          {/* AI state panel — dark */}
          <div
            className="rounded-xl p-7"
            style={{ background: "#0D2B1E", border: "1px solid rgba(255,255,255,0.06)" }}
          >
            <div
              className="text-[10px] font-semibold uppercase tracking-widest mb-3"
              style={{ color: "rgba(155,216,75,0.65)" }}
            >
              What AGRO-AI sees
            </div>
            <h3
              className="text-[16px] font-semibold leading-snug mb-2"
              style={{ color: "white" }}
            >
              Readiness is blocked by missing proof.
            </h3>
            <p
              className="text-[12px] leading-relaxed mb-5"
              style={{ color: "rgba(255,255,255,0.42)" }}
            >
              The package can be prepared, but external use remains blocked until
              required records are attached and reviewed.
            </p>
            <div className="space-y-3">
              {[
                { label: "Proof present", value: "Controller events, weather context, crop profile" },
                { label: "Proof missing", value: "Water proof, input applications, traceability" },
                { label: "Next action", value: "Attach scoped water measurement proof" },
                { label: "Human gate", value: "Required before external use" },
              ].map(({ label, value }) => (
                <div key={label} className="flex gap-4 items-start">
                  <span
                    className="text-[11px] font-medium flex-shrink-0 pt-px"
                    style={{ color: "rgba(255,255,255,0.35)", width: 108 }}
                  >
                    {label}
                  </span>
                  <span className="text-[12px]" style={{ color: "rgba(255,255,255,0.7)" }}>
                    {value}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Metrics */}
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: "Assurance readiness", value: "72%", sub: "Package completeness toward reviewer handoff" },
            { label: "Open actions", value: "7", sub: "Open tasks across evidence and assurance" },
            { label: "Missing proof", value: "4", sub: "Required items not attached or verified" },
            { label: "Agent runs", value: "3", sub: "Recent automated runs in this workspace" },
          ].map(({ label, value, sub }) => (
            <div
              key={label}
              className="rounded-xl p-5"
              style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
            >
              <div className="text-[11px] font-medium mb-2.5" style={{ color: MUTED }}>
                {label}
              </div>
              <div className="text-[30px] font-semibold leading-none mb-2" style={{ color: TEXT }}>
                {value}
              </div>
              <div className="text-[11px]" style={{ color: MUTED }}>{sub}</div>
            </div>
          ))}
        </div>

        {/* Work queue + Agent workflow — 60/40 split */}
        <div className="grid gap-5" style={{ gridTemplateColumns: "3fr 2fr" }}>
          {/* Priority work queue */}
          <div
            className="rounded-xl overflow-hidden"
            style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
          >
            <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}>
              <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>
                Action queue
              </div>
              <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>
                Highest-priority work
              </h3>
            </div>
            {/* Table header */}
            <div
              className="grid px-6 py-2.5"
              style={{
                gridTemplateColumns: "1fr auto auto",
                borderBottom: `1px solid ${BORDER}`,
                background: BG,
              }}
            >
              <span className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>Task</span>
              <span className="text-[10px] font-semibold uppercase tracking-widest w-[120px]" style={{ color: MUTED }}>Status</span>
              <span className="text-[10px] font-semibold uppercase tracking-widest w-[72px] text-right" style={{ color: MUTED }}>Action</span>
            </div>
            <div>
              {workQueue.map((item, i) => (
                <div
                  key={i}
                  className="grid px-6 py-4 items-center gap-4"
                  style={{
                    gridTemplateColumns: "1fr auto auto",
                    borderTop: i > 0 ? `1px solid ${BORDER}` : "none",
                  }}
                >
                  <div>
                    <div className="text-[13px] font-medium mb-0.5" style={{ color: TEXT }}>
                      {item.title}
                    </div>
                    <div className="text-[11px]" style={{ color: MUTED }}>{item.reason}</div>
                  </div>
                  <div className="w-[120px]">
                    <StatusPill label={item.status} variant={item.statusVariant} />
                  </div>
                  <div className="w-[72px] flex justify-end">
                    <button
                      className="px-3 py-1.5 text-[11px] font-medium rounded transition-colors"
                      style={{ border: `1px solid ${BORDER}`, color: TEXT, background: "transparent" }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = BG)}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                    >
                      {item.action}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Evidence-backed automation */}
          <div
            className="rounded-xl overflow-hidden"
            style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
          >
            <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}>
              <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>
                Agent workflow
              </div>
              <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>
                Evidence-backed automation
              </h3>
            </div>
            <div className="px-6 py-5">
              <div className="space-y-3 mb-5">
                {pipelineSteps.map((step, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <div
                      className="w-5 h-5 rounded-full flex-shrink-0 flex items-center justify-center"
                      style={{
                        background: step.done ? GREEN : BG,
                        border: step.done ? "none" : `1px solid ${BORDER}`,
                      }}
                    >
                      {step.done && (
                        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                          <path d="M2 5.5l2 2 4-4" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                    </div>
                    <span
                      className="text-[13px] flex-1"
                      style={{ color: step.done ? TEXT : MUTED, fontWeight: step.done ? 500 : 400 }}
                    >
                      {step.label}
                    </span>
                    {step.badge && (
                      <span
                        className="text-[10px] font-medium px-1.5 py-0.5 rounded"
                        style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}
                      >
                        {step.badge}
                      </span>
                    )}
                  </div>
                ))}
              </div>
              <p
                className="text-[11px] leading-relaxed pt-4"
                style={{ color: MUTED, borderTop: `1px solid ${BORDER}` }}
              >
                Automation accelerates preparation. Human review governs external use.
              </p>
            </div>
          </div>
        </div>

        {/* Integration strip */}
        <div
          className="rounded-xl px-6 py-5"
          style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
        >
          <div
            className="text-[10px] font-semibold uppercase tracking-widest mb-4"
            style={{ color: MUTED }}
          >
            Connected systems
          </div>
          <div className="flex items-center gap-3 mb-4 flex-wrap">
            <div
              className="flex items-center gap-2.5 px-3.5 py-2 rounded-lg"
              style={{ background: BG, border: `1px solid ${BORDER}` }}
            >
              <div className="w-6 h-6 rounded overflow-hidden bg-white flex items-center justify-center flex-shrink-0">
                <ImageWithFallback src={wiseconnLogo} alt="WiseConn" className="w-full h-full object-contain" />
              </div>
              <div>
                <div className="text-[12px] font-medium" style={{ color: TEXT }}>WiseConn</div>
                <div className="text-[10px]" style={{ color: MUTED }}>integrated</div>
              </div>
            </div>
            <div
              className="flex items-center gap-2.5 px-3.5 py-2 rounded-lg"
              style={{ background: BG, border: `1px solid ${BORDER}` }}
            >
              <div className="w-6 h-6 rounded overflow-hidden bg-white flex items-center justify-center flex-shrink-0">
                <ImageWithFallback src={talgilLogo} alt="Talgil" className="w-full h-full object-contain" />
              </div>
              <div>
                <div className="text-[12px] font-medium" style={{ color: TEXT }}>Talgil</div>
                <div className="text-[10px]" style={{ color: MUTED }}>integrated</div>
              </div>
            </div>
            <div
              className="flex items-center gap-2 px-3.5 py-2 rounded-lg"
              style={{ background: BG, border: `1px solid ${BORDER}` }}
            >
              <div className="text-[12px] font-medium" style={{ color: TEXT }}>CropX</div>
              <div className="text-[10px]" style={{ color: MUTED }}>compatible</div>
            </div>
            <div
              className="flex items-center gap-2 px-3.5 py-2 rounded-lg"
              style={{ background: BG, border: `1px solid ${BORDER}` }}
            >
              <div className="text-[12px] font-medium" style={{ color: TEXT }}>Telemetry APIs</div>
              <div className="text-[10px]" style={{ color: MUTED }}>compatible</div>
            </div>
          </div>
          <p className="text-[10px] leading-relaxed" style={{ color: MUTED }}>
            Compatibility indicates technical integration capability. It does not imply endorsement, certification, or formal partnership unless explicitly stated.
          </p>
        </div>
      </div>
    </div>
  );
}
