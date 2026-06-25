import { useState } from "react";
import { Brain, Send } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type AiResponse = {
  status?: string;
  output?: string | Record<string, unknown>;
  provider?: string;
  model?: string;
  demo_fallback?: boolean;
  evidence_context?: {
    missing_data?: string[];
    citations?: Array<{ title?: string; source_type?: string; source_id?: string }>;
  };
  citations?: Array<{ title?: string; source_type?: string; source_id?: string }>;
  verification?: { status?: string; missing_data?: string[]; risk_flags?: string[] };
};

function formatOutput(value: unknown) {
  if (!value) return "No live AI output returned.";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

export function Intelligence() {
  const { currentOrganization, currentWorkspace } = useAuth();
  const [message, setMessage] = useState("");
  const [response, setResponse] = useState<AiResponse | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  async function askAgroAi() {
    const cleanMessage = message.trim();
    if (!cleanMessage) return;
    setIsLoading(true);
    setError("");
    setResponse(null);
    try {
      const result = await apiClient.ai.chat({
        message: cleanMessage,
        workspace_id: currentWorkspace?.id,
      });
      setResponse(result as AiResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI endpoint unavailable.");
    } finally {
      setIsLoading(false);
    }
  }

  const missing = response?.verification?.missing_data || response?.evidence_context?.missing_data || [];
  const citations = response?.citations || response?.evidence_context?.citations || [];
  const unavailable = response?.status === "unavailable" || response?.demo_fallback;

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="h-[72px] px-8 flex items-center justify-between" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div>
          <div className="text-[13px] font-semibold" style={{ color: TEXT }}>{currentWorkspace?.name || "Workspace"}</div>
          <div className="text-[11px]" style={{ color: MUTED }}>{currentOrganization?.name || "Organization"}</div>
        </div>
        <StatusBadge label={unavailable ? "AI unavailable" : response ? "Verified output" : "Awaiting request"} tone={unavailable ? "warn" : response ? "good" : "neutral"} />
      </header>

      <div className="px-8 py-6 space-y-5" style={{ maxWidth: 1220 }}>
        <div className="flex items-center gap-3">
          <Brain className="h-6 w-6" style={{ color: TEXT }} />
          <div>
            <h1 className="text-[28px] font-semibold mb-1" style={{ color: TEXT }}>Intelligence</h1>
            <p className="text-[13px]" style={{ color: MUTED }}>Ask AGRO-AI using only live workspace evidence.</p>
          </div>
        </div>

        <section className="rounded-xl overflow-hidden" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="px-6 py-4" style={{ borderBottom: `1px solid ${BORDER}` }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>Workspace assistant</div>
            <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>Ask AGRO-AI</h3>
          </div>
          <div className="p-6 space-y-4">
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              rows={5}
              className="w-full rounded-lg px-4 py-3 text-[13px] outline-none"
              style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}
              placeholder="Ask about irrigation, assurance readiness, evidence gaps, report drafting, or integration status."
            />
            <div className="flex items-center gap-3">
              <PortalButton disabled={isLoading || !message.trim()} onClick={askAgroAi}>
                <span className="inline-flex items-center gap-2"><Send className="h-3.5 w-3.5" />{isLoading ? "Asking" : "Ask"}</span>
              </PortalButton>
              <span className="text-[12px]" style={{ color: MUTED }}>{response?.provider ? `Provider: ${response.provider}${response.model ? ` / ${response.model}` : ""}` : "Provider status appears after response."}</span>
            </div>
          </div>
        </section>

        {isLoading ? <InlineState title="Loading intelligence response" /> : null}
        {error ? <InlineState title={error} /> : null}
        {unavailable ? <InlineState title="AI provider unavailable." detail="Configure hosted inference or local Ollama to enable live model output." /> : null}

        {response ? (
          <section className="rounded-xl overflow-hidden" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="px-6 py-4 flex items-center justify-between" style={{ borderBottom: `1px solid ${BORDER}` }}>
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>Response</div>
                <h3 className="text-[15px] font-semibold" style={{ color: TEXT }}>{response.verification?.status || response.status || "AI result"}</h3>
              </div>
              <StatusBadge label={response.demo_fallback ? "Unavailable" : "Verified"} tone={response.demo_fallback ? "warn" : "good"} />
            </div>
            <div className="p-6 space-y-4">
              <pre className="whitespace-pre-wrap text-[13px] leading-relaxed rounded-lg p-4" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>{formatOutput(response.output || response)}</pre>
              {missing.length ? <InlineState title="Missing data" detail={missing.join(", ")} /> : null}
              {citations.length ? (
                <div className="grid gap-2">
                  {citations.map((citation, index) => (
                    <div key={`${citation.source_id || index}`} className="rounded-lg px-4 py-3 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>
                      <span style={{ color: TEXT }}>{citation.title || citation.source_type || "Citation"}</span>
                      {citation.source_id ? ` / ${citation.source_id}` : ""}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </section>
        ) : null}
      </div>
    </div>
  );
}
