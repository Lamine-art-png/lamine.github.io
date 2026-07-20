import { useEffect, useState } from "react";
import { CheckCircle2, RefreshCw, ShieldAlert, XCircle } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalCopy } from "../hooks/usePortalCopy";

const COPY = [
  "Platform API access review", "Applications", "Support queue", "Abuse signals",
  "Billing operations", "Refresh", "Approve test access", "Request information", "Reject",
  "No records.", "Not found.", "All administrative decisions are audited.",
  "Meter export reconciliation", "Drain enabled meter outbox", "Loading…",
  "Program enrollments", "Live access reviews", "Strategic partner dossiers",
  "Approve live access", "Deny live access", "Suspend enrollment",
] as const;

function record(value: unknown): Record<string, any> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, any> : {};
}

function list(value: unknown, key: string): Record<string, any>[] {
  const rows = record(value)[key];
  return Array.isArray(rows) ? rows : [];
}

export function PlatformApiAdmin() {
  const { platformAdmin } = useAuth();
  const { tx } = usePortalCopy(["platform-api-admin"], COPY);
  const [applications, setApplications] = useState<Record<string, any>[]>([]);
  const [support, setSupport] = useState<Record<string, any>[]>([]);
  const [abuse, setAbuse] = useState<Record<string, any>[]>([]);
  const [enrollments, setEnrollments] = useState<Record<string, any>[]>([]);
  const [liveAccess, setLiveAccess] = useState<Record<string, any>[]>([]);
  const [dossiers, setDossiers] = useState<Record<string, any>[]>([]);
  const [reconciliation, setReconciliation] = useState<Record<string, any>>({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function refresh() {
    if (!platformAdmin) return;
    setLoading(true);
    setError("");
    const [applicationResult, supportResult, abuseResult, billingResult, enrollmentResult, liveResult, dossierResult] = await Promise.all([
      apiClient.platformProductAdmin.applications().catch(() => null),
      apiClient.platformProductAdmin.support().catch(() => null),
      apiClient.platformProductAdmin.abuse().catch(() => null),
      apiClient.platformProductAdmin.billingReconciliation().catch(() => null),
      apiClient.platformProductAdmin.enrollments().catch(() => null),
      apiClient.platformProductAdmin.liveAccess().catch(() => null),
      apiClient.platformProductAdmin.partnerDossiers().catch(() => null),
    ]);
    setApplications(list(applicationResult, "applications"));
    setSupport(list(supportResult, "support_requests"));
    setAbuse(list(abuseResult, "events"));
    setReconciliation(record(billingResult));
    setEnrollments(list(enrollmentResult, "enrollments"));
    setLiveAccess(list(liveResult, "requests"));
    setDossiers(list(dossierResult, "dossiers"));
    setLoading(false);
  }

  useEffect(() => { void refresh(); }, [platformAdmin]);

  async function review(applicationId: string, status: "approved" | "needs_information" | "rejected") {
    try {
      await apiClient.platformProductAdmin.reviewApplication(applicationId, {
        status,
        reason: status === "approved" ? "Approved after platform access review." : status === "rejected" ? "Not approved after platform access review." : "Additional technical and commercial information is required.",
        program: status === "approved" ? "developer_private_beta" : undefined,
        allowed_environments: status === "approved" ? ["test"] : [],
        maximum_projects: 1,
        maximum_live_projects: 0,
        maximum_service_accounts: 2,
        maximum_keys: 2,
        maximum_webhooks: 1,
        billing_mode: "none",
        plan_identifier: "sandbox",
        support_tier: "documentation",
        provider_restrictions: {},
        resource_restrictions: {},
        rate_limit_policy: {},
        quota_policy: {},
      });
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tx("Not found."));
    }
  }

  async function reviewLiveAccess(requestId: string, status: "approved" | "denied") {
    try {
      await apiClient.platformProductAdmin.reviewLiveAccess(requestId, {
        status,
        reason: status === "approved" ? "Approved after security, billing, and production readiness review." : "Denied after production access review.",
        conditions: status === "approved" ? ["No physical actions", "Provider access remains contract-gated"] : [],
      });
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tx("Not found."));
    }
  }

  async function suspendEnrollment(enrollmentId: string) {
    try {
      await apiClient.platformProductAdmin.suspendEnrollment(enrollmentId, "Suspended following platform access review.");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tx("Not found."));
    }
  }

  if (!platformAdmin) return <div className="min-h-full bg-[#F6F4EE] p-8">{tx("Not found.")}</div>;
  const empty = <div className="text-[13px] text-[#65736A]">{tx("No records.")}</div>;

  return (
    <div className="min-h-full bg-[#F6F4EE] px-4 py-6 text-[#10231B] md:px-7">
      <div className="mx-auto max-w-[1220px]">
        <header className="flex items-end justify-between gap-4">
          <div><div className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[#2D6A4F]">Platform administration</div><h1 className="mt-2 text-[30px] font-semibold">{tx("Platform API access review")}</h1><p className="mt-2 text-[13px] text-[#65736A]">{tx("All administrative decisions are audited.")}</p></div>
          <button type="button" onClick={() => void refresh()} className="inline-flex h-10 items-center gap-2 border border-[#D6DDD0] bg-white px-3 text-[12px] font-semibold"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> {loading ? tx("Loading…") : tx("Refresh")}</button>
        </header>
        {error ? <div role="alert" className="mt-4 border border-[#D9A88B] bg-[#FFF4ED] p-3 text-[13px] text-[#7A2E0E]">{error}</div> : null}
        <div className="mt-5 grid gap-4">
          <section className="border border-[#D6DDD0] bg-white p-4"><h2 className="font-semibold">{tx("Applications")}</h2><div className="mt-4 space-y-3">{applications.map((item) => <article key={String(item.id)} className="border border-[#E2D8C8] p-4"><div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between"><div><div className="font-semibold">{String(item.application_type)}</div><div className="mt-1 text-[12px] text-[#65736A]">{String(item.organization_id)} · {String(item.status)}</div><p className="mt-2 text-[13px]">{String(item.use_case || "")}</p></div>{["submitted", "under_review", "needs_information"].includes(String(item.status)) ? <div className="flex flex-wrap gap-2"><button type="button" onClick={() => void review(String(item.id), "approved")} className="inline-flex h-9 items-center gap-2 bg-[#2D6A4F] px-3 text-[11px] font-semibold text-white"><CheckCircle2 className="h-3.5 w-3.5" /> {tx("Approve test access")}</button><button type="button" onClick={() => void review(String(item.id), "needs_information")} className="h-9 border border-[#D6DDD0] px-3 text-[11px] font-semibold">{tx("Request information")}</button><button type="button" onClick={() => void review(String(item.id), "rejected")} className="inline-flex h-9 items-center gap-2 border border-[#D9A88B] px-3 text-[11px] font-semibold text-[#7A2E0E]"><XCircle className="h-3.5 w-3.5" /> {tx("Reject")}</button></div> : null}</div></article>)}</div>{!applications.length ? empty : null}</section>
          <div className="grid gap-4 lg:grid-cols-2">
            <section className="border border-[#D6DDD0] bg-white p-4"><h2 className="font-semibold">{tx("Program enrollments")}</h2><div className="mt-3 space-y-2">{enrollments.map((item) => <article key={String(item.id)} className="border border-[#E2D8C8] p-3 text-[13px]"><strong>{String(item.program)}</strong><div className="mt-1 text-[11px] text-[#65736A]">{String(item.organization_id)} · {String(item.status)} · {(Array.isArray(item.allowed_environments) ? item.allowed_environments : []).join(", ")}</div>{String(item.status) === "active" ? <button type="button" onClick={() => void suspendEnrollment(String(item.id))} className="mt-3 h-8 border border-[#D9A88B] px-3 text-[11px] font-semibold text-[#7A2E0E]">{tx("Suspend enrollment")}</button> : null}</article>)}</div>{!enrollments.length ? empty : null}</section>
            <section className="border border-[#D6DDD0] bg-white p-4"><h2 className="font-semibold">{tx("Live access reviews")}</h2><div className="mt-3 space-y-2">{liveAccess.map((item) => <article key={String(item.id)} className="border border-[#E2D8C8] p-3 text-[13px]"><strong>{String(item.organization_id)}</strong><div className="mt-1 text-[11px] text-[#65736A]">{String(item.status)} · {String(item.billing_plan || "—")}</div><p className="mt-2">{String(item.intended_production_use || "")}</p>{["submitted", "under_review", "needs_information"].includes(String(item.status)) ? <div className="mt-3 flex gap-2"><button type="button" onClick={() => void reviewLiveAccess(String(item.id), "approved")} className="h-8 bg-[#2D6A4F] px-3 text-[11px] font-semibold text-white">{tx("Approve live access")}</button><button type="button" onClick={() => void reviewLiveAccess(String(item.id), "denied")} className="h-8 border border-[#D9A88B] px-3 text-[11px] font-semibold text-[#7A2E0E]">{tx("Deny live access")}</button></div> : null}</article>)}</div>{!liveAccess.length ? empty : null}</section>
          </div>
          <section className="border border-[#D6DDD0] bg-white p-4"><h2 className="font-semibold">{tx("Strategic partner dossiers")}</h2><div className="mt-3 grid gap-2 md:grid-cols-2">{dossiers.map((item) => <article key={String(item.id)} className="border border-[#E2D8C8] p-3 text-[13px]"><strong>{String(item.partner_name)}</strong><div className="mt-1 text-[11px] text-[#65736A]">{String(item.provider_id)} · {String(item.contract_status)}</div><div className="mt-2 text-[11px]">Read: {String(item.read_readiness)} · Write: {String(item.write_readiness)} · Production: {String(item.production_readiness)}</div></article>)}</div>{!dossiers.length ? empty : null}</section>
          <div className="grid gap-4 lg:grid-cols-2">
            <section className="border border-[#D6DDD0] bg-white p-4"><h2 className="font-semibold">{tx("Support queue")}</h2><div className="mt-3 space-y-2">{support.map((item) => <div key={String(item.id)} className="border border-[#E2D8C8] p-3 text-[13px]"><strong>{String(item.subject)}</strong><div className="mt-1 text-[11px] text-[#65736A]">{String(item.severity)} · {String(item.status)} · {String(item.organization_id)}</div></div>)}</div>{!support.length ? empty : null}</section>
            <section className="border border-[#D6DDD0] bg-white p-4"><h2 className="flex items-center gap-2 font-semibold"><ShieldAlert className="h-4 w-4" /> {tx("Abuse signals")}</h2><div className="mt-3 space-y-2">{abuse.map((item) => <div key={String(item.id)} className="border border-[#E2D8C8] p-3 text-[13px]"><strong>{String(item.signal_type)}</strong><div className="mt-1 text-[11px] text-[#65736A]">{String(item.severity)} · {String(item.status)} · {String(item.organization_id)}</div></div>)}</div>{!abuse.length ? empty : null}</section>
          </div>
          <section className="border border-[#D6DDD0] bg-white p-4"><h2 className="font-semibold">{tx("Billing operations")}</h2><p className="mt-2 text-[13px] text-[#65736A]">{tx("Meter export reconciliation")}</p><pre className="mt-3 overflow-auto bg-[#F6F4EE] p-3 text-[11px]">{JSON.stringify(reconciliation, null, 2)}</pre><button type="button" onClick={() => apiClient.platformProductAdmin.drainMeterOutbox().then(refresh)} className="mt-3 h-9 border border-[#D6DDD0] px-3 text-[11px] font-semibold">{tx("Drain enabled meter outbox")}</button></section>
        </div>
      </div>
    </div>
  );
}
