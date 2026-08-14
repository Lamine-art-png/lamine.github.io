import { CheckCircle2, Code2, ExternalLink, Loader2, ShieldCheck, TerminalSquare } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiClient, type ApiError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";

type TermsDocument = {
  document_type: string;
  version: string;
  content_digest: string;
  effective_at?: string | null;
  legal_review_status?: string;
};

const LEGAL_BASE = "https://agroai-pilot.com/platform-api/assets/legal";
const names: Record<string, string> = {
  api_terms: "Platform API Terms",
  acceptable_use: "Acceptable Use Policy",
  privacy: "Platform API Privacy Notice",
  data_processing_addendum: "Data Processing Addendum",
};

function codeFromLocation() {
  return new URLSearchParams(window.location.search).get("user_code")?.trim().toUpperCase() || "";
}

function legalUrl(document: TermsDocument) {
  return `${LEGAL_BASE}/${encodeURIComponent(document.document_type)}-${encodeURIComponent(document.version)}.html`;
}

export function PlatformCliDeviceApproval() {
  const { currentOrganization, refreshMe } = useAuth();
  const [userCode, setUserCode] = useState(codeFromLocation());
  const [documents, setDocuments] = useState<TermsDocument[]>([]);
  const [termsRequired, setTermsRequired] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [approved, setApproved] = useState(false);
  const [error, setError] = useState("");

  const sortedDocuments = useMemo(
    () => [...documents].sort((a, b) => a.document_type.localeCompare(b.document_type)),
    [documents],
  );

  useEffect(() => {
    let cancelled = false;
    async function loadTerms() {
      try {
        const result = await apiClient.get("/v1/platform/terms") as { documents?: TermsDocument[] };
        if (cancelled) return;
        const docs = Array.isArray(result?.documents) ? result.documents : [];
        if (!docs.length || docs.some((item) => item.legal_review_status !== "approved_effective")) {
          setError("CLI authorization is unavailable because the effective Platform legal catalog is not ready.");
        } else {
          setDocuments(docs);
          setTermsRequired(true);
        }
      } catch (cause) {
        if (cancelled) return;
        const apiError = cause as ApiError;
        // Before public self-service, the terms endpoint can be intentionally
        // closed. Existing approved private-beta developers may still use the
        // device flow if the server enables it for them.
        if (apiError?.status !== 404) setError(apiError?.message || "CLI authorization readiness could not be verified.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadTerms();
    return () => { cancelled = true; };
  }, []);

  const approve = async () => {
    if (!userCode || submitting || approved) return;
    if (termsRequired && !agreed) return;
    setSubmitting(true);
    setError("");
    try {
      if (termsRequired) {
        for (const document of sortedDocuments) {
          await apiClient.post("/v1/platform/terms/accept", {
            document_type: document.document_type,
            document_version: document.version,
          });
        }
        // This is the same self-service boundary used by the browser console.
        // It creates only the bounded TEST enrollment when the production
        // self-service launch flag is active.
        await apiClient.platformDeveloper.overview();
        await refreshMe();
      }
      await apiClient.post("/v1/platform/cli/device/approve", { user_code: userCode });
      setApproved(true);
    } catch (cause) {
      const apiError = cause as ApiError;
      setError(apiError?.message || "The CLI authorization request could not be approved.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#EEEADF] px-4 py-8 text-[#10231B] md:px-8">
      <div className="mx-auto grid min-h-[calc(100vh-4rem)] max-w-[1120px] overflow-hidden rounded-[30px] border border-black/10 bg-[#FFFDF8] shadow-[0_32px_100px_rgba(16,35,27,.13)] lg:grid-cols-[.85fr_1.15fr]">
        <section className="bg-[#082219] p-8 text-white md:p-10">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#173B2B] text-[#DCEF8B]"><Code2 className="h-5 w-5" /></div>
            <div><div className="text-[15px] font-semibold">AGRO-AI</div><div className="text-[11px] text-white/45">CLI authorization</div></div>
          </div>
          <div className="mt-20 max-w-md">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[10px] font-bold uppercase tracking-[.16em] text-[#DCEF8B]"><TerminalSquare className="h-3.5 w-3.5" /> First-party device flow</div>
            <h1 className="mt-6 text-[40px] font-semibold leading-[1.04] tracking-[-.045em]">Authorize your terminal without copying a browser session.</h1>
            <p className="mt-5 text-[13px] leading-7 text-white/60">The terminal receives a short-lived organization-bound human credential. Your password and permanent API keys never enter the CLI authorization exchange.</p>
          </div>
          <div className="mt-16 space-y-3 text-[11px] text-white/55">
            <div className="flex gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 text-[#DCEF8B]" /> Approval is tied to your authenticated organization.</div>
            <div className="flex gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 text-[#DCEF8B]" /> Device codes expire and can be exchanged only once.</div>
            <div className="flex gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 text-[#DCEF8B]" /> `agroai logout` revokes the server-side CLI session.</div>
          </div>
        </section>

        <main className="flex items-center p-6 md:p-10">
          <div className="w-full">
            {approved ? (
              <div className="rounded-[24px] border border-[#C9D9C3] bg-[#F4FAF1] p-7">
                <CheckCircle2 className="h-9 w-9 text-[#376D43]" />
                <h2 className="mt-4 text-[27px] font-semibold tracking-[-.035em]">Terminal authorized.</h2>
                <p className="mt-3 text-[12px] leading-6 text-[#5C7061]">Return to the terminal. The CLI will finish the one-time exchange automatically.</p>
                <p className="mt-4 text-[10px] text-[#78847A]">You can close this page.</p>
              </div>
            ) : (
              <>
                <div className="text-[10px] font-bold uppercase tracking-[.18em] text-[#4D745C]">Authorize AGRO-AI CLI</div>
                <h2 className="mt-2 text-[29px] font-semibold tracking-[-.035em]">Confirm this device code.</h2>
                <p className="mt-2 text-[12px] leading-6 text-[#65736A]">Organization: <strong className="text-[#244735]">{currentOrganization?.name || "Current organization"}</strong></p>

                <label className="mt-6 block text-[10px] font-bold uppercase tracking-[.14em] text-[#65736A]">Device code</label>
                <input
                  value={userCode}
                  onChange={(event) => setUserCode(event.target.value.toUpperCase().replace(/[^A-Z0-9-]/g, "").slice(0, 32))}
                  autoComplete="one-time-code"
                  spellCheck={false}
                  className="mt-2 h-12 w-full rounded-xl border border-[#CBD6C7] bg-white px-4 font-mono text-[18px] font-semibold tracking-[.16em] outline-none focus:border-[#6B8F70]"
                  placeholder="ABCD-EFGH"
                />

                {loading ? <div className="mt-5 flex items-center gap-2 text-[11px] text-[#65736A]"><Loader2 className="h-4 w-4 animate-spin" /> Checking developer agreements…</div> : null}

                {termsRequired && !loading ? (
                  <div className="mt-6 rounded-2xl border border-[#D8E0D4] bg-[#F8FAF5] p-4">
                    <div className="text-[11px] font-semibold text-[#244735]">Current developer agreements</div>
                    <div className="mt-3 space-y-2">
                      {sortedDocuments.map((document) => (
                        <a key={`${document.document_type}:${document.version}`} href={legalUrl(document)} target="_blank" rel="noreferrer" className="flex items-center justify-between rounded-xl bg-white px-3 py-2 text-[11px] text-[#365845]">
                          <span>{names[document.document_type] || document.document_type} · {document.version}</span><ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      ))}
                    </div>
                    <label className="mt-4 flex cursor-pointer items-start gap-3 text-[10px] leading-5 text-[#5C7061]">
                      <input type="checkbox" checked={agreed} onChange={(event) => setAgreed(event.target.checked)} className="mt-0.5 h-4 w-4" />
                      <span>I have read and agree to these documents on behalf of this organization and confirm I have authority to accept them.</span>
                    </label>
                  </div>
                ) : null}

                {error ? <div role="alert" className="mt-4 rounded-xl border border-[#E4B9AE] bg-[#FFF2EE] p-3 text-[11px] text-[#823628]">{error}</div> : null}

                <button
                  type="button"
                  disabled={!userCode || loading || submitting || (termsRequired && !agreed) || Boolean(error)}
                  onClick={() => void approve()}
                  className="mt-6 inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#102F22] px-5 text-[12px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-45"
                >
                  {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <TerminalSquare className="h-4 w-4" />}
                  {submitting ? "Authorizing…" : "Authorize terminal"}
                </button>
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
