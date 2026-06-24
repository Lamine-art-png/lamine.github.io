const BG = "#F6F4EE";
const SURFACE = "#FFFEFA";
const BORDER = "rgba(16,35,27,0.12)";
const TEXT = "#10231B";
const MUTED = "#68776F";
const GREEN = "#16533C";
const GREEN_HOVER = "#1F7350";

type StepStatus = "complete" | "active" | "waiting";

interface WorkflowStep {
  label: string;
  status: StepStatus;
  detail: string;
}

const workflowSteps: WorkflowStep[] = [
  { label: "Ingest sources", status: "complete", detail: "5 sources ingested" },
  { label: "Normalize records", status: "complete", detail: "Records standardized" },
  { label: "Classify evidence", status: "complete", detail: "3 items mapped to domains" },
  { label: "Detect missing proof", status: "complete", detail: "4 gaps identified" },
  { label: "Generate recommendations", status: "active", detail: "In progress" },
  { label: "Wait for human approval", status: "waiting", detail: "Pending review" },
];

const findings = [
  "Readiness remains incomplete until water measurement proof is attached.",
  "Input application records are missing.",
  "Traceability mapping needs reviewer check.",
  "WaterOps evidence can be prepared as a draft.",
];

const agentActions = [
  { label: "Run gap analysis", description: "Detect missing proof across all domains" },
  { label: "Prepare proof draft", description: "Compile available evidence into a draft package" },
  { label: "Create follow-up tasks", description: "Generate action items from current findings" },
  { label: "Refresh readiness", description: "Re-evaluate assurance readiness score" },
];

function StepIcon({ status }: { status: StepStatus }) {
  if (status === "complete") {
    return (
      <div
        className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0"
        style={{ background: GREEN }}
      >
        <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
          <path d="M2 5.5l2.5 2.5 4.5-4.5" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
    );
  }
  if (status === "active") {
    return (
      <div
        className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0"
        style={{ background: BG, border: `2px solid ${GREEN}` }}
      >
        <div className="w-2 h-2 rounded-full" style={{ background: GREEN }} />
      </div>
    );
  }
  return (
    <div
      className="w-6 h-6 rounded-full flex-shrink-0"
      style={{ background: BG, border: `1px solid ${BORDER}` }}
    />
  );
}

export function Agents() {
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
          <h1 className="text-[28px] font-semibold mb-1" style={{ color: TEXT }}>Agents</h1>
          <p className="text-[13px]" style={{ color: MUTED }}>
            Analyze evidence, detect gaps, propose actions, and prepare review-ready work packages.
          </p>
        </div>

        {/* Main grid — workflow + findings */}
        <div className="grid gap-5" style={{ gridTemplateColumns: "3fr 2fr" }}>
          {/* Current run state */}
          <div
            className="rounded-xl overflow-hidden"
            style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
          >
            <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}>
              <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>
                AGRO-AI Agent
              </div>
              <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>Current run state</h3>
            </div>
            <div className="px-6 py-5 space-y-1">
              {workflowSteps.map((step, i) => (
                <div key={i}>
                  <div className="flex items-center gap-4 py-2">
                    <StepIcon status={step.status} />
                    <div className="flex-1 flex items-center justify-between gap-4">
                      <span
                        className="text-[13px]"
                        style={{
                          color: step.status === "waiting" ? MUTED : TEXT,
                          fontWeight: step.status === "complete" || step.status === "active" ? 500 : 400,
                        }}
                      >
                        {step.label}
                      </span>
                      <span
                        className="text-[11px] flex-shrink-0"
                        style={{
                          color:
                            step.status === "complete"
                              ? GREEN
                              : step.status === "active"
                              ? "#1D4ED8"
                              : MUTED,
                        }}
                      >
                        {step.detail}
                      </span>
                    </div>
                  </div>
                  {i < workflowSteps.length - 1 && (
                    <div
                      className="ml-3 w-px"
                      style={{
                        height: 8,
                        background: step.status === "complete" ? `${GREEN}50` : BORDER,
                      }}
                    />
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Latest findings */}
          <div
            className="rounded-xl overflow-hidden"
            style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
          >
            <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}>
              <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>
                AI Analysis
              </div>
              <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>Latest findings</h3>
            </div>
            <div className="px-6 py-5 space-y-4">
              {findings.map((finding, i) => (
                <div
                  key={i}
                  className="flex gap-3 items-start pb-4"
                  style={i < findings.length - 1 ? { borderBottom: `1px solid ${BORDER}` } : {}}
                >
                  <div
                    className="w-1.5 h-1.5 rounded-full flex-shrink-0 mt-2"
                    style={{ background: MUTED }}
                  />
                  <p className="text-[13px] leading-relaxed" style={{ color: TEXT }}>
                    {finding}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Agent actions */}
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
        >
          <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>
              Actions
            </div>
            <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>Agent actions</h3>
          </div>
          <div className="grid grid-cols-4 gap-4 p-5">
            {agentActions.map((action, i) => (
              <button
                key={i}
                className="text-left rounded-xl p-4 transition-colors"
                style={{ background: BG, border: `1px solid ${BORDER}` }}
                onMouseEnter={(e) => (e.currentTarget.style.borderColor = "rgba(16,35,27,0.25)")}
                onMouseLeave={(e) => (e.currentTarget.style.borderColor = BORDER)}
              >
                <div className="text-[13px] font-semibold mb-1" style={{ color: TEXT }}>
                  {action.label}
                </div>
                <div className="text-[11px] leading-relaxed" style={{ color: MUTED }}>
                  {action.description}
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
