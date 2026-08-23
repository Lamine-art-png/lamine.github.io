import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, History, RefreshCw, ShieldCheck } from "lucide-react";
import { API_BASE_URL, apiClient } from "../../api/client";
import { useAuth } from "../../auth/AuthProvider";
import { useLocale } from "../../hooks/useLocale";
import { BG, BORDER, MUTED, SURFACE, TEXT } from "../portalUi";
import { AnyRecord, asArray, safeText } from "./intelligenceSupport";

function query(workspaceId?: string) {
  return workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
}

function stateLabel(value: unknown) {
  return safeText(value).replaceAll("_", " ");
}

function shortDate(value: unknown) {
  const text = safeText(value);
  if (!text) return "";
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

async function lifecycleMutation(lifecycleId: string, action: string, payload?: AnyRecord) {
  const token = window.localStorage.getItem("agroai_access_token");
  const headers = new Headers({ "Content-Type": "application/json", "Idempotency-Key": `${action}-${lifecycleId}-${Date.now()}` });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}/v1/intelligence/memory/lifecycles/${encodeURIComponent(lifecycleId)}/${action}`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data && typeof data === "object" ? (data.detail || data.message) : null;
    const message = detail && typeof detail === "object" ? detail.message : detail;
    throw new Error(String(message || response.status));
  }
  return data as AnyRecord;
}

export function DecisionMemoryWorkspace() {
  const { currentWorkspace } = useAuth();
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [decisions, setDecisions] = useState<AnyRecord[]>([]);
  const [fieldStates, setFieldStates] = useState<AnyRecord[]>([]);
  const [learning, setLearning] = useState<AnyRecord>({});
  const [specialists, setSpecialists] = useState<AnyRecord[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [lifecycle, setLifecycle] = useState<AnyRecord>({});
  const [changes, setChanges] = useState<AnyRecord>({});

  const selected = useMemo(() => decisions.find((row) => String(row.id) === selectedId) || decisions[0] || {}, [decisions, selectedId]);
  const currentFieldState = fieldStates[0] || {};

  async function loadCore() {
    setLoading(true);
    setError("");
    try {
      const workspaceId = currentWorkspace?.id;
      const [decisionResponse, fieldResponse, learningResponse, specialistResponse] = await Promise.all([
        apiClient.get(`/v1/intelligence/memory/decisions${query(workspaceId)}`) as Promise<AnyRecord>,
        apiClient.get(`/v1/intelligence/memory/field-state${query(workspaceId)}`) as Promise<AnyRecord>,
        apiClient.get(`/v1/intelligence/memory/learning/summary${query(workspaceId)}`) as Promise<AnyRecord>,
        apiClient.post("/v1/intelligence/analysis/specialists", { workspace_id: workspaceId }) as Promise<AnyRecord>,
      ]);
      const decisionRows = asArray(decisionResponse.items) as AnyRecord[];
      setDecisions(decisionRows);
      setFieldStates(asArray(fieldResponse.items) as AnyRecord[]);
      setLearning(learningResponse || {});
      setSpecialists(asArray(specialistResponse.specialists) as AnyRecord[]);
      if (!selectedId && decisionRows[0]?.id) setSelectedId(String(decisionRows[0].id));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("intelligence.retryState"));
    } finally {
      setLoading(false);
    }
  }

  async function loadSelected(decision: AnyRecord) {
    const snapshotId = safeText(decision.id);
    const lifecycleId = safeText(decision.lifecycle?.id);
    if (!snapshotId) {
      setChanges({});
      setLifecycle({});
      return;
    }
    try {
      const requests: Promise<AnyRecord>[] = [
        apiClient.get(`/v1/intelligence/memory/decisions/${encodeURIComponent(snapshotId)}/changes`) as Promise<AnyRecord>,
      ];
      if (lifecycleId) requests.push(apiClient.get(`/v1/intelligence/memory/lifecycles/${encodeURIComponent(lifecycleId)}`) as Promise<AnyRecord>);
      const [changeResponse, lifecycleResponse] = await Promise.all(requests);
      setChanges(changeResponse || {});
      setLifecycle(lifecycleResponse || decision.lifecycle || {});
    } catch {
      setChanges({});
      setLifecycle(decision.lifecycle || {});
    }
  }

  useEffect(() => {
    setDecisions([]);
    setFieldStates([]);
    setLearning({});
    setSpecialists([]);
    setSelectedId("");
    setLifecycle({});
    setChanges({});
    if (open) loadCore().catch(() => null);
  }, [currentWorkspace?.id]);

  useEffect(() => {
    if (open && !decisions.length && !loading) loadCore().catch(() => null);
  }, [open]);

  useEffect(() => {
    if (open && selected?.id) loadSelected(selected).catch(() => null);
  }, [open, selected?.id, selected?.lifecycle?.id]);

  async function mutate(action: string, payload?: AnyRecord) {
    const lifecycleId = safeText(lifecycle.id || selected.lifecycle?.id);
    if (!lifecycleId) return;
    setBusy(action);
    setError("");
    try {
      await lifecycleMutation(lifecycleId, action, payload);
      await loadCore();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("intelligence.actionExecuteFailed"));
    } finally {
      setBusy("");
    }
  }

  async function reject() {
    const reason = window.prompt(t("message"));
    if (!reason?.trim()) return;
    await mutate("reject", { reason: reason.trim() });
  }

  async function syncLearning() {
    setBusy("learning");
    setError("");
    try {
      const token = window.localStorage.getItem("agroai_access_token");
      const headers = new Headers({ "Content-Type": "application/json", "Idempotency-Key": `learning-${Date.now()}` });
      if (token) headers.set("Authorization", `Bearer ${token}`);
      const response = await fetch(`${API_BASE_URL}/v1/intelligence/memory/learning/materialize`, { method: "POST", headers, body: "{}" });
      if (!response.ok) throw new Error(String(response.status));
      await loadCore();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("intelligence.retryState"));
    } finally {
      setBusy("");
    }
  }

  const state = safeText(lifecycle.state || selected.lifecycle?.state);
  const verifiedCount = Number(learning.verified_count || 0);
  const decisionCount = Number(learning.decision_count || 0);
  const conflictCount = asArray(currentFieldState.conflicts).length;
  const unknownCount = asArray(currentFieldState.unknowns).length;
  const drivers = asArray(changes.change_drivers).map((row) => safeText(row)).filter(Boolean);
  const events = asArray(lifecycle.events) as AnyRecord[];

  return (
    <section className="border-b" style={{ background: SURFACE, borderColor: BORDER }}>
      <div className="mx-auto max-w-[1200px] px-4 py-3 sm:px-6">
        <button type="button" onClick={() => setOpen((value) => !value)} className="flex w-full items-center justify-between gap-3 text-left">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg" style={{ background: BG, color: "#0D2B1E" }}><ShieldCheck size={17} /></div>
            <div className="min-w-0">
              <div className="text-[12px] font-semibold" style={{ color: TEXT }}>{t("decisions")} · {t("evidence")}</div>
              <div className="mt-0.5 truncate text-[11px]" style={{ color: MUTED }}>{t("fieldOperatingRoom")} · {t("intelligence.history")}</div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden text-[11px] sm:block" style={{ color: MUTED }}>{decisions.length} · {verifiedCount}</div>
            {open ? <ChevronUp size={16} style={{ color: MUTED }} /> : <ChevronDown size={16} style={{ color: MUTED }} />}
          </div>
        </button>

        {open ? (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap gap-2">
                <Stat label={t("decisions")} value={String(decisions.length)} />
                <Stat label={t("fieldIntel.confidence")} value={currentFieldState.state?.grounding_confidence === undefined ? "—" : `${Math.round(Number(currentFieldState.state.grounding_confidence) * 100)}%`} />
                <Stat label={t("fieldIntel.state.conflict")} value={String(conflictCount)} warning={conflictCount > 0} />
                <Stat label={t("fieldIntel.uncertain")} value={String(unknownCount)} warning={unknownCount > 0} />
                <Stat label={t("fieldIntel.verifyBy")} value={`${verifiedCount}/${decisionCount}`} />
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={() => syncLearning()} disabled={Boolean(busy)} className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-[11px] font-semibold disabled:opacity-50" style={{ border: `1px solid ${BORDER}`, color: TEXT }}><History size={14} /> {t("fieldIntel.syncNow")}</button>
                <button type="button" onClick={() => loadCore()} disabled={loading} className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-[11px] font-semibold disabled:opacity-50" style={{ border: `1px solid ${BORDER}`, color: TEXT }}><RefreshCw size={14} /> {t("retry")}</button>
              </div>
            </div>

            {error ? <div className="rounded-lg px-3 py-2 text-[12px]" style={{ background: "#FEF2F2", color: "#991B1B", border: "1px solid #FECACA" }}>{error}</div> : null}
            {loading ? <div className="rounded-lg px-3 py-3 text-[12px]" style={{ background: BG, color: MUTED }}>{t("intelligence.preparingAnswer")}</div> : null}

            {!loading ? (
              <div className="grid gap-3 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.4fr)]">
                <div className="space-y-2">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.06em]" style={{ color: MUTED }}>{t("intelligence.history")}</div>
                  {decisions.slice(0, 10).map((row) => {
                    const active = String(row.id) === String(selected.id);
                    return (
                      <button key={String(row.id)} type="button" onClick={() => setSelectedId(String(row.id))} className="w-full rounded-xl p-3 text-left" style={{ background: active ? "#F0F5F1" : BG, border: `1px solid ${active ? "#A9B9AD" : BORDER}` }}>
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-[12px] font-semibold" style={{ color: TEXT }}>{stateLabel(row.domain || row.task)}</span>
                          <span className="flex-shrink-0 text-[10px]" style={{ color: MUTED }}>{shortDate(row.created_at)}</span>
                        </div>
                        <div className="mt-1 truncate text-[11px]" style={{ color: MUTED }}>{stateLabel(row.lifecycle?.state)}</div>
                      </button>
                    );
                  })}
                  {!decisions.length ? <div className="rounded-xl p-3 text-[12px]" style={{ background: BG, color: MUTED, border: `1px solid ${BORDER}` }}>{t("intelligence.noChats")}</div> : null}
                </div>

                <div className="space-y-3">
                  {selected?.id ? (
                    <div className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <div className="text-[10px] font-semibold uppercase tracking-[0.06em]" style={{ color: MUTED }}>{stateLabel(selected.domain)}</div>
                          <div className="mt-1 break-words text-[13px] font-semibold" style={{ color: TEXT }}>{safeText(selected.question || selected.task)}</div>
                          <div className="mt-2 flex flex-wrap gap-2 text-[10px]" style={{ color: MUTED }}>
                            <span>{stateLabel(state)}</span>
                            <span>·</span>
                            <span>{Math.round(Number(selected.grounding_confidence || 0) * 100)}%</span>
                            <span>·</span>
                            <span>{shortDate(selected.created_at)}</span>
                          </div>
                        </div>
                        {state === "awaiting_approval" ? (
                          <div className="flex flex-shrink-0 gap-2">
                            <button type="button" onClick={() => mutate("approve")} disabled={Boolean(busy)} className="rounded-lg px-3 py-2 text-[11px] font-semibold disabled:opacity-50" style={{ background: "#0D2B1E", color: "white" }}>{t("intelligence.createApproval")}</button>
                            <button type="button" onClick={() => reject()} disabled={Boolean(busy)} className="rounded-lg px-3 py-2 text-[11px] font-semibold disabled:opacity-50" style={{ background: SURFACE, color: "#991B1B", border: `1px solid ${BORDER}` }}>{t("fieldIntel.cancel")}</button>
                          </div>
                        ) : null}
                      </div>

                      {drivers.length ? (
                        <div className="mt-4 border-t pt-3" style={{ borderColor: BORDER }}>
                          <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.06em]" style={{ color: MUTED }}><History size={13} /> {t("intelligence.history")}</div>
                          <div className="mt-2 space-y-1.5">{drivers.slice(0, 6).map((driver, index) => <div key={`${driver}-${index}`} className="text-[11px] leading-relaxed" style={{ color: TEXT }}>• {driver}</div>)}</div>
                        </div>
                      ) : null}

                      {events.length ? (
                        <div className="mt-4 border-t pt-3" style={{ borderColor: BORDER }}>
                          <div className="text-[10px] font-semibold uppercase tracking-[0.06em]" style={{ color: MUTED }}>{t("fieldIntel.audit")}</div>
                          <div className="mt-2 grid gap-2 sm:grid-cols-2">
                            {events.slice(-8).map((event) => (
                              <div key={String(event.id || event.sequence)} className="rounded-lg px-3 py-2" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
                                <div className="flex items-center gap-2 text-[11px] font-semibold" style={{ color: TEXT }}>
                                  {event.to_state === "verified" ? <CheckCircle2 size={13} /> : event.to_state === "rejected" || event.to_state === "failed" ? <AlertTriangle size={13} /> : <ShieldCheck size={13} />}
                                  {stateLabel(event.to_state)}
                                </div>
                                <div className="mt-1 text-[10px]" style={{ color: MUTED }}>{shortDate(event.created_at)}</div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  {specialists.length ? (
                    <div className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                      <div className="text-[10px] font-semibold uppercase tracking-[0.06em]" style={{ color: MUTED }}>{t("intelligence")} · {t("fieldIntel.correlation")}</div>
                      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                        {specialists.map((row) => (
                          <div key={safeText(row.domain)} className="rounded-lg px-3 py-2" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
                            <div className="text-[11px] font-semibold" style={{ color: TEXT }}>{stateLabel(row.domain)}</div>
                            <div className="mt-1 text-[10px]" style={{ color: MUTED }}>{stateLabel(row.status)} · {Math.round(Number(row.confidence_cap || 0) * 100)}%</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function Stat({ label, value, warning = false }: { label: string; value: string; warning?: boolean }) {
  return (
    <div className="rounded-lg px-3 py-2" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="text-[9px] font-medium" style={{ color: MUTED }}>{label}</div>
      <div className="mt-0.5 text-[12px] font-semibold" style={{ color: warning ? "#92400E" : TEXT }}>{value}</div>
    </div>
  );
}
