import { CheckCircle2, Code2, ExternalLink, FileCheck2, Loader2, LockKeyhole, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiClient, type ApiError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { PlatformApplicationGate } from "./PlatformApplicationGate";

type TermsDocument = {
  document_type: string;
  version: string;
  content_digest: string;
  effective_at?: string | null;
  legal_review_status?: string;
  reacceptance_required?: boolean;
};

type GateState = "loading" | "self_service" | "legacy" | "blocked";

const LEGAL_BASE = "https://agroai-pilot.com/platform-api/assets/legal";

const legalNames: Record<string, string> = {
  api_terms: "Platform API Terms",
  acceptable_use: "Acceptable Use Policy",
  privacy: "Platform API Privacy Notice",
  data_processing_addendum: "Data Processing Addendum",
};

function legalName(type: string) {
  return legalNames[type] || type.replaceAll("_", " ");
}

function legalUrl(document: TermsDocument) {
  return `${LEGAL_BASE}/${encodeURIComponent(document.document_type)}-${encodeURIComponent(document.version)}.html`;
}

function digestPreview(value: string) {
  if (!value) return "";
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}

export function PlatformSelfServiceGate() {
  const { currentOrganization, refreshMe } = useAuth();
  const [state, setState] = useState<GateState>("loading");
  const [documents, setDocuments] = useState<TermsDocument[]>([]);
  const [agreed, setAgreed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const organizationRole = String(currentOrganization?.role || "").trim().toLowerCase();
  const canManagePlatform = ["owner", "admin"].includes(organizationRole);

  const sortedDocuments = useMemo(
    () => [...documents].sort((a, b) => a.document_type.localeCompare(b.document_type)),
    [documents],
  );

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!canManagePlatform) {
        setState("legacy");
        return;
      }
      setError("");
      try {
        // A self-service launch exposes the effective legal catalog. If this
        // endpoint is still closed, preserve the existing reviewed private-beta
        // path instead of pretending public enrollment is active.
        const result = await apiClient.get("/v1/platform/terms") as { documents?: TermsDocument[] };
        if (cancelled) return;
        const required = Array.isArray(result?.documents) ? result.documents : [];
        if (!required.length) {
          setError("TEST self-service is not available because the Platform legal catalog is not ready.");
          setState("blocked");
          return;
        }
        if (required.some((item) => item.legal_review_status !== "approved_effective" || !item.version || !item.content_digest)) {
          setError("TEST self-service is not available because the effective Platform legal catalog is incomplete.");
          setState("blocked");
          return;
        }
        setDocuments(required);
        setState("self_service");
      } catch (cause) {
        if (cancelled) return;
        const apiError = cause as ApiError;
        if (apiError?.status === 404) {
          setState("legacy");
          return;
        }
        setError(apiError?.message || "TEST self-service readiness could not be verified.");
        setState("blocked");
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [canManagePlatform]);

  const acceptAndContinue = async () => {
    if (!agreed || submitting || !sortedDocuments.length) return;
    setSubmitting(true);
    setError("");
    try {
      // Acceptance is intentionally idempotent server-side. Submitting every
      // currently effective document also handles users returning after a
      // partially completed acceptance flow.
      for (const document of sortedDocuments) {
        await apiClient.post("/v1/platform/terms/accept", {
          document_type: document.document_type,
          document_version: document.version,
        });
      }
      // refreshMe invokes the developer overview. In a public TEST launch the
      // backend auto-enrolls the eligible owner/admin here and the parent route
      // immediately switches into the developer console.
      await refreshMe();
    } catch (cause) {
      const apiError = cause as ApiError;
      setError(apiError?.message || "The Platform agreements could not be accepted.");
    } finally {
      setSubmitting(false);
    }
  };

  if (state === "legacy") return <PlatformApplicationGate />;

  if (state === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F3F1E9] text-[#10231B]">
        <Loader2 className="h-5 w-5 animate-spin text-[#315D46]" />
        <span className="ml-3 text-[12px] font-semibold">Preparing your TEST developer workspace…</span>
      </div>
    );
  }

  if (state === "blocked") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#EEEADF] px-4 py-10 text-[#10231B]">
        <div className="w-full max-w-[640px] rounded-[28px] border border-[#D4DCCF] bg-[#FFFDF8] p-8 shadow-[0_30px_100px_rgba(16,35,27,.12)]">
          <div className="inline-flex items-center gap-2 rounded-full border border-[#E3D5A8] bg-[#FFF9E8] px-3 py-1.5 text-[10px] font-bold uppercase tracking-[.16em] text-[#705518]">
            <LockKeyhole className="h-3.5 w-3.5" /> Fail-closed launch gate
          </div>
          <h1 className="mt-5 text-[30px] font-semibold tracking-[-.035em]">TEST self-service is temporarily unavailable.</h1>
          <p className="mt-4 text-[12px] leading-6 text-[#65736A]">{error}</p>
          <p className="mt-4 text-[11px] leading-6 text-[#718078]">
            No project, API key, live access, provider connection, or physical action was created.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#EEEADF] text-[#10231B]">
      <div className="grid min-h-screen xl:grid-cols-[.82fr_1.18fr]">
        <section className="relative overflow-hidden bg-[#071F16] px-7 py-9 text-white md:px-11">
          <div
            className="absolute inset-0 opacity-35"
            style={{
              backgroundImage:
                "radial-gradient(circle at 16% 12%,rgba(205,239,139,.32),transparent 29%),linear-gradient(rgba(255,255,255,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.05) 1px,transparent 1px)",
              backgroundSize: "auto,36px 36px,36px 36px",
            }}
          />
          <div className="relative flex h-full min-h-[520px] flex-col justify-between">
            <a href="https://agroai-pilot.com/platform-api" className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#173B2B] text-[#DCEF8B]">
                <Code2 className="h-5 w-5" />
              </div>
              <div>
                <div className="text-[15px] font-semibold">AGRO-AI</div>
                <div className="text-[11px] text-white/45">Platform API</div>
              </div>
            </a>
            <div className="max-w-xl py-14">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[10px] font-bold uppercase tracking-[.17em] text-[#DCEF8B]">
                <ShieldCheck className="h-3.5 w-3.5" /> Self-service TEST access
              </div>
              <h1 className="mt-6 text-[44px] font-semibold leading-[1.02] tracking-[-.045em] md:text-[54px]">
                Start building without waiting for us.
              </h1>
              <p className="mt-6 text-[14px] leading-7 text-white/65">
                Accept the current developer agreements and AGRO-AI will create a bounded TEST entitlement for your verified organization. No sales call or manual API-access review is required.
              </p>
              <div className="mt-8 grid gap-3 sm:grid-cols-2">
                {[
                  "Deterministic agricultural test data",
                  "Scoped agro_test_ credentials",
                  "Projects, jobs, usage, and logs",
                  "CLI, Python, TypeScript, and HTTP",
                ].map((label) => (
                  <div key={label} className="rounded-2xl border border-white/10 bg-white/5 p-4 text-[11px] font-semibold">
                    <CheckCircle2 className="mb-3 h-4 w-4 text-[#DCEF8B]" /> {label}
                  </div>
                ))}
              </div>
            </div>
            <div className="text-[10px] leading-5 text-white/35">
              TEST access never grants live provider credentials, production customer data, or physical execution.
            </div>
          </div>
        </section>

        <main className="flex items-center px-4 py-8 md:px-8 xl:px-11">
          <div className="mx-auto w-full max-w-[820px] rounded-[28px] border border-black/10 bg-[#FFFDF8] p-6 shadow-[0_28px_90px_rgba(16,35,27,.11)] md:p-8">
            <div className="border-b border-[#E0E5DC] pb-6">
              <div className="text-[10px] font-bold uppercase tracking-[.18em] text-[#4D745C]">Developer agreements</div>
              <h2 className="mt-2 text-[29px] font-semibold tracking-[-.035em]">Activate TEST access.</h2>
              <p className="mt-2 text-[12px] leading-6 text-[#65736A]">
                Organization: <strong className="text-[#244735]">{currentOrganization?.name || "Verified AGRO-AI organization"}</strong>
              </p>
            </div>

            <div className="mt-6 space-y-3">
              {sortedDocuments.map((document) => (
                <a
                  key={`${document.document_type}:${document.version}`}
                  href={legalUrl(document)}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center justify-between gap-4 rounded-2xl border border-[#D8E0D4] bg-white p-4 transition hover:border-[#9DB29E]"
                >
                  <span className="min-w-0">
                    <span className="flex items-center gap-2 text-[12px] font-semibold text-[#244735]">
                      <FileCheck2 className="h-4 w-4 text-[#4D745C]" /> {legalName(document.document_type)}
                    </span>
                    <span className="mt-1 block text-[10px] text-[#718078]">
                      Version {document.version} · digest {digestPreview(document.content_digest)}
                    </span>
                  </span>
                  <ExternalLink className="h-4 w-4 shrink-0 text-[#718078]" />
                </a>
              ))}
            </div>

            <label className="mt-6 flex cursor-pointer items-start gap-3 rounded-2xl border border-[#D5DFD1] bg-[#F6F9F3] p-4">
              <input
                type="checkbox"
                checked={agreed}
                onChange={(event) => setAgreed(event.target.checked)}
                className="mt-0.5 h-4 w-4"
              />
              <span className="text-[11px] leading-6 text-[#53665A]">
                I have read and agree to the current documents above on behalf of this organization, and I confirm I have authority to accept them.
              </span>
            </label>

            {error ? (
              <div role="alert" className="mt-4 rounded-xl border border-[#E4B9AE] bg-[#FFF2EE] p-3 text-[11px] text-[#823628]">
                {error}
              </div>
            ) : null}

            <button
              type="button"
              disabled={!agreed || submitting}
              onClick={() => void acceptAndContinue()}
              className="mt-6 inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#102F22] px-5 text-[12px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-45"
            >
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
              {submitting ? "Activating TEST access…" : "Accept and activate TEST access"}
            </button>

            <p className="mt-4 text-center text-[10px] leading-5 text-[#7A867E]">
              LIVE projects remain a separate reviewed process. This action cannot enable billing, live providers, production webhooks, or physical agricultural commands.
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
