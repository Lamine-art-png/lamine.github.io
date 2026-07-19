import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, RefreshCw, ShieldAlert, XCircle } from "lucide-react";
import { apiClient } from "../api/client";
import { BG, BORDER, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

const HEADER = "Access appeals";
const SUBHEADER = "Review suspended accounts that submitted stronger organization and agricultural-use evidence.";
const EMPTY = "No appeals match this status.";

export function AccessAppealsAdminPage() {
  const [appealStatus, setAppealStatus] = useState("pending");
  const [appeals, setAppeals] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [working, setWorking] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data: any = await apiClient.platformAdmin.appeals(appealStatus);
      setAppeals(Array.isArray(data.appeals) ? data.appeals : []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Appeals could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [appealStatus]);

  useEffect(() => { void load(); }, [load]);

  async function decide(id: string, action: "approve" | "reject" | "request_information") {
    const defaultNote = action === "approve"
      ? "Organization and operational use verified through appeal."
      : action === "request_information"
        ? "Please provide stronger organization or operational evidence."
        : "The submitted evidence did not sufficiently verify a legitimate agricultural organization and use case.";
    const notes = window.prompt("Decision note sent to the applicant:", defaultNote);
    if (notes === null) return;
    setWorking(id + action);
    setError("");
    try {
      await apiClient.platformAdmin.decideAppeal(id, { action, notes });
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The appeal decision could not be saved.");
    } finally {
      setWorking("");
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-6 py-7 md:px-8" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-3 flex gap-2"><StatusBadge label="Platform security" tone="good" /><StatusBadge label="Manual appeal review" tone="neutral" /></div>
            <h1 className="text-[30px] font-semibold" style={{ color: TEXT }}>{HEADER}</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-7" style={{ color: MUTED }}>{SUBHEADER}</p>
          </div>
          <PortalButton variant="secondary" onClick={() => void load()}><RefreshCw className="h-4 w-4" /> Refresh</PortalButton>
        </div>
      </header>

      <main className="space-y-5 px-5 py-6 md:px-8" style={{ maxWidth: 1200 }}>
        {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-800">{error}</div> : null}
        <div className="flex flex-wrap gap-2">
          {[["pending", "Pending"], ["additional_information_required", "More information"], ["approved", "Approved"], ["rejected", "Rejected"], ["all", "All"]].map(([value, label]) => (
            <button key={value} onClick={() => setAppealStatus(value)} className="rounded-lg px-3 py-2 text-[12px] font-semibold" style={{ background: appealStatus === value ? "#10231B" : SURFACE, color: appealStatus === value ? "white" : TEXT, border: `1px solid ${BORDER}` }}>{label}</button>
          ))}
        </div>

        {loading ? <div className="rounded-2xl p-8 text-[14px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: MUTED }}>Loading access appeals...</div> : null}
        {!loading && !appeals.length ? <div className="rounded-2xl p-8 text-[14px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: MUTED }}>{EMPTY}</div> : null}

        {appeals.map((appeal) => (
          <article key={appeal.id} className="rounded-2xl p-5 md:p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-[18px] font-semibold" style={{ color: TEXT }}>{appeal.full_name || appeal.user?.name || "Unnamed applicant"}</h2>
                  <StatusBadge label={String(appeal.status || "pending").replaceAll("_", " ")} tone={appeal.status === "approved" ? "good" : appeal.status === "rejected" ? "warning" : "neutral"} />
                </div>
                <p className="mt-1 text-[13px]" style={{ color: MUTED }}>{appeal.user?.email} · {appeal.organization_name || appeal.organization?.name || "No organization"}</p>
              </div>
              <p className="text-[11px]" style={{ color: MUTED }}>{appeal.submitted_at ? new Date(appeal.submitted_at).toLocaleString() : "Link requested"}</p>
            </div>

            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <Info label="Professional role" value={appeal.professional_role} />
              <Info label="Scale" value={appeal.acres_or_sites} />
              <Info label="Website" value={appeal.website_url} link />
              <Info label="Professional profile" value={appeal.professional_profile_url} link />
            </div>
            <LongInfo label="Agricultural use case" value={appeal.agricultural_use_case} />
            <LongInfo label="Systems and data sources" value={appeal.planned_data_sources} />
            <LongInfo label="Explanation" value={appeal.explanation} />
            {appeal.supporting_evidence_url ? <Info label="Supporting evidence" value={appeal.supporting_evidence_url} link /> : null}
            {appeal.review_notes ? <LongInfo label="Review notes" value={appeal.review_notes} /> : null}

            {appeal.status === "pending" ? (
              <div className="mt-5 flex flex-wrap gap-2">
                <PortalButton onClick={() => void decide(appeal.id, "approve")} disabled={Boolean(working)}><CheckCircle2 className="h-4 w-4" /> Approve</PortalButton>
                <PortalButton variant="secondary" onClick={() => void decide(appeal.id, "request_information")} disabled={Boolean(working)}><ShieldAlert className="h-4 w-4" /> Request information</PortalButton>
                <PortalButton variant="secondary" onClick={() => void decide(appeal.id, "reject")} disabled={Boolean(working)}><XCircle className="h-4 w-4" /> Reject</PortalButton>
              </div>
            ) : null}
          </article>
        ))}
      </main>
    </div>
  );
}

function Info({ label, value, link = false }: { label: string; value?: string | null; link?: boolean }) {
  const shown = value || "—";
  return <div><div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: MUTED }}>{label}</div>{link && value ? <a href={value} target="_blank" rel="noreferrer" className="mt-1 block break-all text-[13px] font-semibold text-[#2D6A4F] hover:underline">{shown}</a> : <div className="mt-1 text-[13px] font-semibold" style={{ color: TEXT }}>{shown}</div>}</div>;
}

function LongInfo({ label, value }: { label: string; value?: string | null }) {
  return <div className="mt-4 rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: MUTED }}>{label}</div><p className="mt-2 whitespace-pre-wrap text-[13px] leading-6" style={{ color: TEXT }}>{value || "—"}</p></div>;
}
