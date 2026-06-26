import { useCallback, useState } from "react";
import { apiClient } from "../api/client";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;

const SUGGESTIONS = [
  "What should I do today?",
  "What evidence is missing before I can trust this recommendation?",
  "Draft a water operations report from the current field context.",
  "Which connectors should I set up first?",
  "Explain the irrigation decision in plain English.",
];

function asArray(value: unknown): AnyRecord[] {
  return Array.isArray(value) ? (value as AnyRecord[]) : [];
}

function safeText(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return fallback;
  }
}

function resultAnswer(result: AnyRecord | null) {
  if (!result) return "";
  return (
    result.answer ||
    result.response ||
    result.summary ||
    result.message ||
    result.output ||
    "AGRO-AI completed the request."
  );
}

export function Intelligence() {
  const briefState = usePortalResource<AnyRecord>(useCallback(() => apiClient.intelligence.brief(), []));
  const [question, setQuestion] = useState("What should I do today?");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnyRecord | null>(null);

  const brief = briefState.data || {};
  const workspace = (brief.workspace || {}) as AnyRecord;
  const field = (brief.field_state || {}) as AnyRecord;
  const integrations = asArray(brief.integration_status);

  async function ask(prompt = question) {
    const q = prompt.trim();
    if (!q) return;

    setQuestion(q);
    setLoading(true);
    setResult(null);

    try {
      const intelligenceApi = apiClient.intelligence as any;

      const response = intelligenceApi.ask
        ? await intelligenceApi.ask({ question: q, workspace_id: workspace.id, block_id: field.block_id })
        : await apiClient.intelligence.action({
            action: "ask",
            payload: {
              question: q,
              workspace_id: workspace.id,
              block_id: field.block_id,
              surface: "ask_agro_ai",
            },
          });

      setResult(response as AnyRecord);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-8" style={{ background: "#0D2B1E", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
        <div className="max-w-5xl">
          <div className="flex items-center gap-2 mb-4">
            <StatusBadge label={brief.mode === "live" ? "Live brain" : "Demo brain"} tone={brief.mode === "live" ? "good" : "warn"} />
            <StatusBadge label="Evidence-grounded" tone="good" />
          </div>

          <h1 className="text-[34px] font-semibold tracking-tight" style={{ color: "white" }}>
            Ask AGRO-AI
          </h1>

          <p className="mt-3 max-w-3xl text-[14px] leading-relaxed" style={{ color: "rgba(255,255,255,0.68)" }}>
            Ask questions across field evidence, water status, telemetry, connectors, missing data, reports, and decisions. The answer should tell you what it knows, what it does not know, and what to do next.
          </p>
        </div>
      </header>

      <main className="px-8 py-7" style={{ maxWidth: 1180 }}>
        <section className="grid gap-5" style={{ gridTemplateColumns: "1.4fr 0.6fr" }}>
          <div className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>
              Ask the operating system
            </div>

            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={5}
              className="w-full resize-none rounded-xl px-4 py-4 text-[14px] outline-none"
              style={{
                background: BG,
                border: `1px solid ${BORDER}`,
                color: TEXT,
              }}
              placeholder="Ask AGRO-AI what to do, what is missing, what changed, or what to report."
            />

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <PortalButton onClick={() => ask()} disabled={loading}>
                {loading ? "Thinking…" : "Ask AGRO-AI"}
              </PortalButton>
              <PortalButton variant="secondary" onClick={() => setQuestion("")}>
                Clear
              </PortalButton>
            </div>

            <div className="mt-5 flex flex-wrap gap-2">
              {SUGGESTIONS.map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => ask(item)}
                  className="rounded-full px-3 py-2 text-[12px]"
                  style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>
              Current context
            </div>

            <Info label="Workspace" value={safeText(workspace.name, "Demo workspace")} />
            <Info label="Field" value={safeText(field.name || field.crop_type, "Evaluation field")} />
            <Info label="Mode" value={brief.mode === "live" ? "Live operations" : "Demo / evaluation"} />
            <Info label="Connectors" value={`${integrations.length || 0} configured or available`} />

            <div className="mt-4 rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
              <div className="text-[12px] leading-relaxed" style={{ color: MUTED }}>
                Live WiseConn/Talgil sync requires credentials. Until then, AGRO-AI should label answers as demo or sample-context based.
              </div>
            </div>
          </div>
        </section>

        {briefState.error ? (
          <div className="mt-5">
            <InlineState title="Brain context unavailable" detail={briefState.error} />
          </div>
        ) : null}

        <section className="mt-6 rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="flex items-center justify-between gap-4 mb-4">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>
                Response
              </div>
              <h2 className="text-[20px] font-semibold" style={{ color: TEXT }}>
                AGRO-AI answer
              </h2>
            </div>
            {result ? <StatusBadge label="Generated" tone="good" /> : <StatusBadge label={loading ? "Thinking" : "Ready"} />}
          </div>

          {!result && !loading ? (
            <div className="rounded-xl p-5 text-[13px] leading-relaxed" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>
              Ask a question above. The response will appear here with a clear answer, missing evidence, and next action.
            </div>
          ) : null}

          {loading ? (
            <div className="rounded-xl p-5 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>
              AGRO-AI is reading the current field context…
            </div>
          ) : null}

          {result ? (
            <div className="space-y-4">
              <div className="rounded-xl p-5" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                <div className="text-[14px] leading-relaxed whitespace-pre-wrap" style={{ color: TEXT }}>
                  {safeText(resultAnswer(result))}
                </div>
              </div>

              {Array.isArray(result.missing_data) && result.missing_data.length ? (
                <ResultList title="Missing evidence" items={result.missing_data} />
              ) : null}

              {Array.isArray(result.next_actions) && result.next_actions.length ? (
                <ResultList title="Next actions" items={result.next_actions} />
              ) : null}

              {Array.isArray(result.citations) && result.citations.length ? (
                <ResultList title="Citations" items={result.citations} />
              ) : null}
            </div>
          ) : null}
        </section>
      </main>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b py-3 last:border-b-0" style={{ borderColor: BORDER }}>
      <span className="text-[12px]" style={{ color: MUTED }}>{label}</span>
      <span className="text-[12px] font-semibold text-right" style={{ color: TEXT }}>{value}</span>
    </div>
  );
}

function ResultList({ title, items }: { title: string; items: unknown[] }) {
  return (
    <div className="rounded-xl p-4" style={{ background: "#F6F4EE", border: `1px solid ${BORDER}` }}>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>{title}</div>
      <div className="space-y-2">
        {items.map((item, index) => (
          <div key={index} className="text-[13px] leading-relaxed" style={{ color: TEXT }}>
            • {safeText(item)}
          </div>
        ))}
      </div>
    </div>
  );
}
