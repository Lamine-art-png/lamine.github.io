import { FormEvent, ReactNode, useEffect, useState } from "react";
import { CheckCircle2, Loader2, ShieldCheck } from "lucide-react";
import { apiClient } from "../api/client";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

const PAGE_TITLE = "Request restoration of access";
const PAGE_INTRO = "AGRO-AI restricts accounts when organization or operational-use evidence cannot be sufficiently verified. Submit an appeal only for a legitimate agricultural organization, professional role, or operational use case.";
const EMAIL_LABEL = "AGRO-AI account email";
const EMAIL_BUTTON = "Send secure appeal link";
const SECURE_NOTE = "For privacy, the response is the same whether or not an account exists. Eligible accounts receive a time-limited link by email.";
const SUBMIT_BUTTON = "Submit appeal";
const RETURN_LABEL = "Return to sign in";

const emptyForm = {
  full_name: "",
  professional_role: "",
  organization_name: "",
  website_url: "",
  professional_profile_url: "",
  agricultural_use_case: "",
  acres_or_sites: "",
  planned_data_sources: "",
  explanation: "",
  supporting_evidence_url: "",
};

export function AccessAppealPage() {
  const token = new URLSearchParams(window.location.search).get("token") || "";
  const [email, setEmail] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [maskedEmail, setMaskedEmail] = useState("");
  const [loading, setLoading] = useState(Boolean(token));
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (!token) return;
    apiClient.accessAppeals.form(token)
      .then((data: any) => {
        setMaskedEmail(String(data.masked_email || ""));
        setForm({ ...emptyForm, ...(data.form || {}) });
      })
      .catch((cause: Error) => setError(cause.message || "The secure appeal link is invalid or expired."))
      .finally(() => setLoading(false));
  }, [token]);

  async function requestLink(event: FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError("");
    setMessage("");
    try {
      const result: any = await apiClient.accessAppeals.request({ email });
      setMessage(String(result.message || "A secure link will be sent if the account is eligible."));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The appeal request could not be completed.");
    } finally {
      setWorking(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError("");
    try {
      const result: any = await apiClient.accessAppeals.submit(token, form);
      setMessage(String(result.message || "Your appeal was submitted."));
      setSubmitted(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The appeal could not be submitted.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#F1ECDD] px-5 py-10 text-[#10231B]">
      <div className="mx-auto max-w-[760px] overflow-hidden rounded-[22px] border border-[#D8D7CC] bg-[#FFFDF8] shadow-[0_24px_80px_rgba(16,35,27,0.13)]">
        <header className="bg-[#09271D] px-7 py-7 text-white md:px-10">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-[#DDF39B]"><ShieldCheck className="h-4 w-4" /> AGRO-AI SECURITY</div>
          <h1 className="mt-4 text-[30px] font-semibold tracking-tight">{PAGE_TITLE}</h1>
          <p className="mt-3 max-w-2xl text-[14px] leading-7 text-white/72">{PAGE_INTRO}</p>
        </header>
        <main className="p-7 md:p-10">
          {error ? <div className="mb-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-800">{error}</div> : null}
          {message ? <div className="mb-5 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-[13px] text-emerald-900">{message}</div> : null}
          {loading ? <div className="flex items-center gap-2 py-10 text-[14px] text-[#68776E]"><Loader2 className="h-4 w-4 animate-spin" /> Loading secure appeal...</div> : null}

          {!token && !loading ? (
            <form onSubmit={requestLink} className="space-y-5">
              <Field caption={EMAIL_LABEL}><Input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required autoComplete="email" /></Field>
              <p className="text-[12px] leading-6 text-[#6E7A73]">{SECURE_NOTE}</p>
              <Button type="submit" disabled={working} className="w-full bg-[#10231B] text-white hover:bg-[#183528]">{working ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{EMAIL_BUTTON}</Button>
            </form>
          ) : null}

          {token && !loading && !submitted && !error ? (
            <form onSubmit={submit} className="space-y-5">
              <div className="rounded-xl border border-[#D8E4D5] bg-[#F5FAF3] px-4 py-3 text-[13px]">Secure appeal for <strong>{maskedEmail}</strong>. The account remains restricted during review.</div>
              <div className="grid gap-4 md:grid-cols-2">
                <Field caption="Full legal name"><Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required /></Field>
                <Field caption="Professional role"><Input value={form.professional_role} onChange={(e) => setForm({ ...form, professional_role: e.target.value })} required /></Field>
                <Field caption="Legal organization name"><Input value={form.organization_name} onChange={(e) => setForm({ ...form, organization_name: e.target.value })} required /></Field>
                <Field caption="Acres, sites, or customers served"><Input value={form.acres_or_sites} onChange={(e) => setForm({ ...form, acres_or_sites: e.target.value })} required /></Field>
                <Field caption="Organization website"><Input type="url" value={form.website_url} onChange={(e) => setForm({ ...form, website_url: e.target.value })} /></Field>
                <Field caption="Professional or company profile"><Input type="url" value={form.professional_profile_url} onChange={(e) => setForm({ ...form, professional_profile_url: e.target.value })} /></Field>
              </div>
              <TextField caption="Genuine agricultural use case" value={form.agricultural_use_case} onChange={(value) => setForm({ ...form, agricultural_use_case: value })} minLength={40} />
              <TextField caption="Systems or data sources you intend to connect" value={form.planned_data_sources} onChange={(value) => setForm({ ...form, planned_data_sources: value })} minLength={10} />
              <TextField caption="Why the original account information was incomplete or should be reconsidered" value={form.explanation} onChange={(value) => setForm({ ...form, explanation: value })} minLength={20} />
              <Field caption="Optional supporting-evidence URL"><Input type="url" value={form.supporting_evidence_url} onChange={(e) => setForm({ ...form, supporting_evidence_url: e.target.value })} /></Field>
              <Button type="submit" disabled={working} className="w-full bg-[#10231B] text-white hover:bg-[#183528]">{working ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{SUBMIT_BUTTON}</Button>
            </form>
          ) : null}

          {submitted ? <div className="py-8 text-center"><CheckCircle2 className="mx-auto h-10 w-10 text-[#2D6A4F]" /><p className="mt-4 text-[15px] leading-7">Your appeal is in the AGRO-AI security review queue. Access remains restricted until a decision is issued.</p></div> : null}
          <div className="mt-7 border-t border-[#E4E1D8] pt-5 text-center"><a href="/" className="text-[13px] font-semibold text-[#2D6A4F] hover:underline">{RETURN_LABEL}</a></div>
        </main>
      </div>
    </div>
  );
}

function Field({ caption, children }: { caption: string; children: ReactNode }) {
  return <label className="block"><span className="mb-2 block text-[13px] font-semibold">{caption}</span>{children}</label>;
}

function TextField({ caption, value, onChange, minLength }: { caption: string; value: string; onChange: (value: string) => void; minLength: number }) {
  return <label className="block"><span className="mb-2 block text-[13px] font-semibold">{caption}</span><textarea value={value} onChange={(e) => onChange(e.target.value)} minLength={minLength} required rows={5} className="w-full rounded-lg border border-[#D6DDD0] bg-white px-3 py-2 text-[14px] outline-none focus:border-[#2D6A4F]" /></label>;
}
