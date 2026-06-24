const BG = "#F6F4EE";
const SURFACE = "#FFFEFA";
const BORDER = "rgba(16,35,27,0.12)";
const TEXT = "#10231B";
const MUTED = "#68776F";
const GREEN = "#16533C";
const GREEN_HOVER = "#1F7350";

type ReportStatus = "blocked" | "draftable" | "ready";

interface ReportCard {
  title: string;
  description: string;
  status: ReportStatus;
  statusLabel: string;
  action: string;
}

const reports: ReportCard[] = [
  {
    title: "Assurance Passport PDF",
    description: "Full proof package with evidence chain, water records, and assurance summary.",
    status: "blocked",
    statusLabel: "Blocked by missing proof",
    action: "Resolve blockers",
  },
  {
    title: "Buyer Proof Pack",
    description: "Evidence-backed summary prepared for buyer or counterparty review.",
    status: "draftable",
    statusLabel: "Draftable",
    action: "Prepare draft",
  },
  {
    title: "WaterOps Evidence Pack",
    description: "Controller events, weather context, and irrigation records compiled for review.",
    status: "ready",
    statusLabel: "Ready for reviewer evaluation",
    action: "Generate",
  },
  {
    title: "Lender / Landowner Risk Summary",
    description: "Operational and assurance readiness overview for lender or landowner briefing.",
    status: "draftable",
    statusLabel: "Draftable",
    action: "Prepare summary",
  },
];

function StatusIndicator({ status, label }: { status: ReportStatus; label: string }) {
  const config: Record<ReportStatus, { dot: string; text: string }> = {
    blocked: { dot: "#B42318", text: "#B42318" },
    draftable: { dot: "#B7791F", text: "#B7791F" },
    ready: { dot: GREEN, text: GREEN },
  };
  return (
    <div className="flex items-center gap-1.5">
      <div
        className="w-1.5 h-1.5 rounded-full flex-shrink-0"
        style={{ background: config[status].dot }}
      />
      <span className="text-[12px] font-medium" style={{ color: config[status].text }}>
        {label}
      </span>
    </div>
  );
}

export function Reports() {
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
          <h1 className="text-[28px] font-semibold mb-1" style={{ color: TEXT }}>Reports</h1>
          <p className="text-[13px]" style={{ color: MUTED }}>
            Prepare draft proof packages and operational reports with reviewer gates.
          </p>
        </div>

        {/* Report cards */}
        <div className="grid grid-cols-2 gap-4">
          {reports.map((report, i) => (
            <div
              key={i}
              className="rounded-xl p-6"
              style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
            >
              <div className="flex items-start justify-between gap-4 mb-3">
                <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>
                  {report.title}
                </h3>
                <StatusIndicator status={report.status} label={report.statusLabel} />
              </div>
              <p className="text-[13px] leading-relaxed mb-4" style={{ color: MUTED }}>
                {report.description}
              </p>
              <button
                className="px-4 py-2 text-[12px] font-medium rounded-lg transition-colors"
                style={
                  report.status === "ready"
                    ? { background: GREEN, color: "white" }
                    : { border: `1px solid ${BORDER}`, color: TEXT, background: "transparent" }
                }
                onMouseEnter={(e) => {
                  if (report.status === "ready") {
                    e.currentTarget.style.background = GREEN_HOVER;
                  } else {
                    e.currentTarget.style.background = BG;
                  }
                }}
                onMouseLeave={(e) => {
                  if (report.status === "ready") {
                    e.currentTarget.style.background = GREEN;
                  } else {
                    e.currentTarget.style.background = "transparent";
                  }
                }}
              >
                {report.action}
              </button>
            </div>
          ))}
        </div>

        {/* Reviewer warning */}
        <div
          className="rounded-xl px-6 py-4 flex items-start gap-3"
          style={{ background: "#FFFBEB", border: "1px solid #FCD34D" }}
        >
          <div
            className="w-4 h-4 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
            style={{ background: "#B7791F" }}
          >
            <span className="text-white text-[9px] font-bold leading-none">!</span>
          </div>
          <p className="text-[12px] leading-relaxed" style={{ color: "#92400E" }}>
            External use requires reviewer approval. AGRO-AI does not claim certification or regulatory approval. All outputs are draft-only until a human reviewer completes evaluation.
          </p>
        </div>
      </div>
    </div>
  );
}
