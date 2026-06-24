const BG = "#F6F4EE";
const SURFACE = "#FFFEFA";
const BORDER = "rgba(16,35,27,0.12)";
const TEXT = "#10231B";
const MUTED = "#68776F";
const GREEN = "#16533C";
const GREEN_HOVER = "#1F7350";

type ConfidenceLevel = "high" | "medium" | "none";
type EvidenceStatus = "mapped" | "missing";

function ConfidenceBadge({ level }: { level: ConfidenceLevel }) {
  if (level === "none") return <span className="text-[11px]" style={{ color: MUTED }}>—</span>;
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium"
      style={
        level === "high"
          ? { background: "#F0FDF4", color: "#15803D", border: "1px solid #BBF7D0" }
          : { background: "#FFFBEB", color: "#92400E", border: "1px solid #FCD34D" }
      }
    >
      {level === "high" ? "High" : "Medium"}
    </span>
  );
}

function StatusDot({ status }: { status: EvidenceStatus }) {
  return (
    <div className="flex items-center gap-1.5">
      <div
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: status === "mapped" ? GREEN : "#B42318" }}
      />
      <span className="text-[12px]" style={{ color: status === "mapped" ? TEXT : "#B42318" }}>
        {status === "mapped" ? "Mapped" : "Missing"}
      </span>
    </div>
  );
}

const evidenceRows = [
  {
    name: "Controller events",
    file: "controller_events.csv",
    domain: "Water proof",
    status: "mapped" as EvidenceStatus,
    confidence: "high" as ConfidenceLevel,
    issue: "None",
    action: "Open",
  },
  {
    name: "Weather context",
    file: "weather_window.csv",
    domain: "Water proof",
    status: "mapped" as EvidenceStatus,
    confidence: "medium" as ConfidenceLevel,
    issue: "Reviewer check",
    action: "Open",
  },
  {
    name: "Crop profile",
    file: "crop_profile.pdf",
    domain: "Farm summary",
    status: "mapped" as EvidenceStatus,
    confidence: "high" as ConfidenceLevel,
    issue: "None",
    action: "Open",
  },
  {
    name: "Input application",
    file: "Missing record",
    domain: "Input proof",
    status: "missing" as EvidenceStatus,
    confidence: "none" as ConfidenceLevel,
    issue: "Required record missing",
    action: "Request",
  },
  {
    name: "Traceability events",
    file: "Missing record",
    domain: "Traceability",
    status: "missing" as EvidenceStatus,
    confidence: "none" as ConfidenceLevel,
    issue: "Required for lot chain",
    action: "Request",
  },
];

const evidenceActions = [
  "Upload source file",
  "Connect controller",
  "Classify records",
  "Resolve missing proof",
  "Prepare export",
];

export function Evidence() {
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
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-[28px] font-semibold mb-1" style={{ color: TEXT }}>Evidence</h1>
            <p className="text-[13px]" style={{ color: MUTED }}>
              Classify field records, controller data, and uploaded files into proof domains.
            </p>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <button
              className="px-4 py-2 text-[12px] font-medium text-white rounded-lg transition-colors"
              style={{ background: GREEN }}
              onMouseEnter={(e) => (e.currentTarget.style.background = GREEN_HOVER)}
              onMouseLeave={(e) => (e.currentTarget.style.background = GREEN)}
            >
              Upload Evidence
            </button>
            <button
              className="px-4 py-2 text-[12px] font-medium rounded-lg transition-colors"
              style={{ border: `1px solid ${BORDER}`, color: TEXT, background: "transparent" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = BG)}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              Classify with Agent
            </button>
            <button
              className="px-4 py-2 text-[12px] font-medium rounded-lg transition-colors"
              style={{ border: `1px solid ${BORDER}`, color: TEXT, background: "transparent" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = BG)}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              Map to Proof Domain
            </button>
          </div>
        </div>

        {/* Main grid — table + actions */}
        <div className="grid gap-5" style={{ gridTemplateColumns: "3fr 1fr" }}>
          {/* Evidence table */}
          <div
            className="rounded-xl overflow-hidden"
            style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
          >
            <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}>
              <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>
                Evidence vault
              </div>
              <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>
                Field records and source files
              </h3>
            </div>
            {/* Table header */}
            <div
              className="grid px-6 py-2.5 gap-4"
              style={{
                gridTemplateColumns: "1.2fr 1.2fr 0.9fr auto auto 1fr auto",
                borderBottom: `1px solid ${BORDER}`,
                background: BG,
              }}
            >
              {["Evidence", "File / Source", "Proof domain", "Status", "Confidence", "Issue", "Action"].map((h) => (
                <span key={h} className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>
                  {h}
                </span>
              ))}
            </div>
            <div>
              {evidenceRows.map((row, i) => (
                <div
                  key={i}
                  className="grid px-6 py-4 gap-4 items-center"
                  style={{
                    gridTemplateColumns: "1.2fr 1.2fr 0.9fr auto auto 1fr auto",
                    borderTop: i > 0 ? `1px solid ${BORDER}` : "none",
                  }}
                >
                  <span className="text-[13px] font-medium" style={{ color: TEXT }}>{row.name}</span>
                  <span
                    className="text-[12px]"
                    style={{
                      color: row.file === "Missing record" ? "#B42318" : MUTED,
                      fontFamily: row.file !== "Missing record" ? "monospace" : "inherit",
                    }}
                  >
                    {row.file}
                  </span>
                  <span className="text-[12px]" style={{ color: MUTED }}>{row.domain}</span>
                  <StatusDot status={row.status} />
                  <ConfidenceBadge level={row.confidence} />
                  <span
                    className="text-[12px]"
                    style={{ color: row.issue === "None" ? MUTED : "#B7791F" }}
                  >
                    {row.issue}
                  </span>
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

          {/* Evidence actions */}
          <div
            className="rounded-xl overflow-hidden"
            style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
          >
            <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}>
              <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>
                Quick actions
              </div>
              <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>Evidence actions</h3>
            </div>
            <div className="px-4 py-4 space-y-2">
              {evidenceActions.map((action, i) => (
                <button
                  key={i}
                  className="w-full text-left px-4 py-3 rounded-lg text-[13px] font-medium transition-colors"
                  style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}
                  onMouseEnter={(e) => (e.currentTarget.style.borderColor = "rgba(16,35,27,0.25)")}
                  onMouseLeave={(e) => (e.currentTarget.style.borderColor = BORDER)}
                >
                  {action}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
