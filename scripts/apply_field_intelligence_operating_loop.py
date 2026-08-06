from __future__ import annotations

from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    Path(path).write_text(content, encoding="utf-8")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return source.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Durable task provenance and idempotency
# ---------------------------------------------------------------------------
path = "agroai_api/app/services/field_operating_loop.py"
source = read(path)
source = replace_once(
    source,
    '''    source_exception_id: str | None = None,
    source_decision_id: str | None = None,
) -> dict[str, Any]:''',
    '''    source_exception_id: str | None = None,
    source_decision_id: str | None = None,
    source_observation_id: str | None = None,
    source_evidence_ids: list[str] | None = None,
    source_asset_ids: list[str] | None = None,
) -> dict[str, Any]:''',
    "field task signature",
)
source = replace_once(
    source,
    '''            "source_exception_id": source_exception_id,
            "source_decision_id": source_decision_id,
            "created_from": created_from,''',
    '''            "source_exception_id": source_exception_id,
            "source_decision_id": source_decision_id,
            "source_observation_id": source_observation_id,
            "source_evidence_ids": list(source_evidence_ids or []),
            "source_asset_ids": list(source_asset_ids or []),
            "created_from": created_from,''',
    "task provenance payload",
)
source = replace_once(
    source,
    '''        "source_exception_id": payload.get("source_exception_id"),
        "source_decision_id": payload.get("source_decision_id"),
        "created_from": payload.get("created_from", "manual"),''',
    '''        "source_exception_id": payload.get("source_exception_id"),
        "source_decision_id": payload.get("source_decision_id"),
        "source_observation_id": payload.get("source_observation_id"),
        "source_evidence_ids": payload.get("source_evidence_ids", []),
        "source_asset_ids": payload.get("source_asset_ids", []),
        "created_from": payload.get("created_from", "manual"),''',
    "task provenance serialization",
)
write(path, source)

path = "agroai_api/app/services/field_intelligence.py"
source = read(path)
start = source.index("def create_task_from_observation(")
end = source.index("\n\ndef map_observations", start)
replacement = '''def create_task_from_observation(db: Session, ctx: AuthContext, observation_id: str, payload: dict) -> dict:
    from app.services.field_intelligence_metrics import tasks_created
    from app.services.field_operating_loop import (
        build_field_ops_context,
        create_task,
        list_tasks,
    )

    observation = get_observation(db, ctx, observation_id)
    authorize_workspace_action(db, ctx, observation.workspace_id, write=True)
    organization_id = require_org(ctx)
    workspace = resolve_workspace(db, organization_id, observation.workspace_id)
    fops = build_field_ops_context(db, organization_id, workspace)

    # One observation owns one primary operator task. Repeated taps, retries, or
    # slow mobile responses return the existing durable task instead of creating
    # duplicates that fragment the operating queue.
    linked_ids = [str(value) for value in (observation.task_ids_json or []) if value]
    if linked_ids:
        tasks_by_id = {str(task.get("id")): task for task in list_tasks(fops)}
        for task_id in linked_ids:
            existing = tasks_by_id.get(task_id)
            if existing:
                return {"task": existing, "created": False}

    structured = dict(observation.structured_json or {})
    vision = dict(structured.get("vision") or {})
    correlation = dict(observation.correlation_json or {})
    recommendation = str(
        observation.recommended_action
        or vision.get("recommended_follow_up")
        or correlation.get("recommended_next_action")
        or ""
    ).strip()

    def unique_text(values: list[object], *, limit: int = 12) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for value in values:
            text_value = str(value or "").strip()
            key = text_value.casefold()
            if text_value and key not in seen:
                seen.add(key)
                output.append(text_value[:500])
            if len(output) >= limit:
                break
        return output

    instructions = unique_text(list(payload.get("instructions") or []))
    if not instructions:
        candidates: list[object] = [recommendation]
        for hypothesis in vision.get("hypotheses") or []:
            if isinstance(hypothesis, dict):
                candidates.append(hypothesis.get("verification"))
        instructions = unique_text(candidates)
    if not instructions:
        instructions = ["Review the linked field observation and confirm the next action."]

    evidence_required = unique_text(list(payload.get("evidence_required") or []))
    if not evidence_required:
        candidates = list(structured.get("evidence_requirements") or [])
        candidates.extend(observation.uncertain_fields_json or [])
        candidates.extend(vision.get("uncertainties") or [])
        for hypothesis in vision.get("hypotheses") or []:
            if isinstance(hypothesis, dict):
                candidates.append(hypothesis.get("verification"))
        evidence_required = unique_text(candidates)

    asset_ids = [
        row.id
        for row in (
            db.query(FieldObservationAsset)
            .filter(FieldObservationAsset.tenant_id == observation.tenant_id)
            .filter(FieldObservationAsset.observation_id == observation.id)
            .filter(FieldObservationAsset.status == "stored")
            .all()
        )
    ]
    summary = str(observation.summary or observation.corrected_transcript or observation.transcript or "Field observation").strip()
    title = str(payload.get("title") or recommendation or summary or "Field observation follow-up")[:120]
    why = str(
        payload.get("why")
        or f"Field Intelligence observation {observation.id[:8]} requires follow-through: {summary}"
    )[:8000]

    task = create_task(
        fops,
        title=title,
        field=observation.field_name,
        block=observation.block_name,
        assigned_to=payload.get("assigned_to"),
        priority=payload.get("priority") or _priority_from_severity(observation.severity),
        why=why,
        instructions=instructions,
        evidence_required=evidence_required,
        created_from="field_intelligence",
        source_observation_id=observation.id,
        source_evidence_ids=[str(value) for value in (observation.evidence_ids_json or []) if value],
        source_asset_ids=asset_ids,
    )
    task_ids = [str(value) for value in (observation.task_ids_json or []) if value]
    if task.get("id") and str(task["id"]) not in task_ids:
        task_ids.append(str(task["id"]))
    observation.task_ids_json = task_ids
    _audit(
        observation,
        "task_created",
        actor=ctx.user.id,
        details={"task_id": task.get("id"), "source": "field_intelligence"},
    )
    db.commit()
    tasks_created.inc()
    return {"task": task, "created": True}
'''
source = source[:start] + replacement + source[end:]
write(path, source)

path = "agroai_api/app/api/v1/field_intelligence.py"
source = read(path)
source = replace_once(
    source,
    '''    task = svc.create_task_from_observation(db, ctx, observation_id, payload.model_dump())
    return {"status": "created", "task": task}''',
    '''    result = svc.create_task_from_observation(db, ctx, observation_id, payload.model_dump())
    return {
        "status": "created" if result.get("created") else "existing",
        "created": bool(result.get("created")),
        "task": result.get("task"),
    }''',
    "field task response",
)
write(path, source)

# ---------------------------------------------------------------------------
# Frontend API types
# ---------------------------------------------------------------------------
path = "figma-enterprise-v4/src/app/api/client.ts"
source = read(path)
source = replace_once(
    source,
    '''export type IntelligenceRunPayload = { task: "chat" | "field_diagnosis" | "exception_triage" | "decision_workbench" | "report_factory" | "connector_diagnosis" | "readiness_analysis"; question: string; workspace_id?: string; field_id?: string; audience?: string; history?: { role: string; content: string }[]; uploaded_evidence?: Record<string, unknown>[]; preferred_language?: string };''',
    '''export type IntelligenceRunPayload = { task: "chat" | "field_diagnosis" | "exception_triage" | "decision_workbench" | "report_factory" | "connector_diagnosis" | "readiness_analysis"; question: string; workspace_id?: string; field_id?: string; field_observation_id?: string; audience?: string; history?: { role: string; content: string }[]; uploaded_evidence?: Record<string, unknown>[]; preferred_language?: string };''',
    "intelligence observation type",
)
source = replace_once(
    source,
    '''export type FieldOpsTaskPayload = { title: string; field?: string; block?: string; assigned_to?: string; priority?: "high" | "medium" | "low"; why: string; instructions?: string[]; evidence_required?: string[]; source_exception_id?: string; source_decision_id?: string; created_from?: "exception" | "decision" | "missing_evidence" | "manual" | "field_update"; workspace_id?: string };''',
    '''export type FieldOpsTaskPayload = { title: string; field?: string; block?: string; assigned_to?: string; priority?: "high" | "medium" | "low"; why: string; instructions?: string[]; evidence_required?: string[]; source_exception_id?: string; source_decision_id?: string; source_observation_id?: string; source_evidence_ids?: string[]; source_asset_ids?: string[]; created_from?: "exception" | "decision" | "missing_evidence" | "manual" | "field_update" | "field_intelligence"; workspace_id?: string };''',
    "field task provenance type",
)
write(path, source)

# ---------------------------------------------------------------------------
# Field Intelligence: selected deep links, action feedback, and coherent loop
# ---------------------------------------------------------------------------
path = "figma-enterprise-v4/src/app/components/FieldIntelligenceV2.tsx"
source = read(path)
anchor = '''  useEffect(() => {
    if (!online) return;
    const interval = window.setInterval(() => {
      if (processingActive) {
        void doFlush();
      } else {
        void loadObservations();
      }
    }, processingActive ? 2200 : 12000);
    return () => window.clearInterval(interval);
  }, [online, processingActive, doFlush, loadObservations]);
'''
addition = anchor + '''
  useEffect(() => {
    const observationId = new URLSearchParams(window.location.search).get("observation_id");
    if (!observationId || selected?.id === observationId) return;
    const match = observations.find((observation) => String(observation.id) === observationId);
    if (match) setSelected(match);
  }, [observations, selected?.id]);
'''
source = replace_once(source, anchor, addition, "observation deep link")
source = replace_once(
    source,
    '''function ObservationDrawer({ t, observation, onClose, onReload }: any) {
  const [busy, setBusy] = useState(false);
  const [corrected, setCorrected] = useState(observation.corrected_transcript || observation.transcript || "");
  const [editing, setEditing] = useState(false);''',
    '''function ObservationDrawer({ t, observation, onClose, onReload }: any) {
  const [busy, setBusy] = useState(false);
  const [corrected, setCorrected] = useState(observation.corrected_transcript || observation.transcript || "");
  const [editing, setEditing] = useState(false);
  const [taskResult, setTaskResult] = useState<Record<string, any> | null>(null);
  const [actionError, setActionError] = useState("");''',
    "drawer action state",
)
source = replace_once(
    source,
    '''  const createTask = async () => {
    setBusy(true);
    try { await apiClient.fieldIntelligence.createTask(observation.id, {}); await onReload(); }
    finally { setBusy(false); }
  };
''',
    '''  const createTask = async () => {
    setBusy(true);
    setActionError("");
    try {
      const response: any = await apiClient.fieldIntelligence.createTask(observation.id, {});
      const task = response?.task || null;
      if (!task?.id) throw new Error(t("fieldIntel.taskFailed"));
      setTaskResult({ ...task, alreadyExisted: response?.status === "existing" || response?.created === false });
      await onReload();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : t("fieldIntel.taskFailed"));
    } finally {
      setBusy(false);
    }
  };

  const linkedTaskId = String(taskResult?.id || observation.task_ids?.[0] || "");
  const askHref = `/intelligence?field_observation_id=${encodeURIComponent(String(observation.id))}&source=field-intelligence`;
''',
    "drawer task action",
)
recommended_old = '''      <DrawerSection title={t("fieldIntel.recommended")}>
        <p className="text-[13px] leading-6 text-[#3B4A41]">{observation.recommended_action || vision.recommended_follow_up || "—"}</p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <button type="button" disabled={busy} onClick={() => void createTask()} className="inline-flex min-h-[42px] items-center justify-center gap-2 rounded-lg bg-[#0D2B1E] px-3 text-[12px] font-semibold text-white">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}{t("fieldIntel.createTask")}
          </button>
          <a href="/intelligence" className="inline-flex min-h-[42px] items-center justify-center gap-2 rounded-lg border border-[#D6DDD0] px-3 text-[12px] font-semibold text-[#10231B]">
            <Sparkles className="h-4 w-4" />{t("askAgroAi")}
          </a>
        </div>
      </DrawerSection>'''
recommended_new = '''      <DrawerSection title={t("fieldIntel.workflowTitle")}>
        <div className="grid grid-cols-4 gap-1.5">
          {[
            [t("fieldIntel.workflowCapture"), true],
            [t("fieldIntel.workflowUnderstand"), Boolean(observation.summary || observation.transcript)],
            [t("fieldIntel.workflowDecide"), Boolean(observation.recommended_action || vision.recommended_follow_up)],
            [t("fieldIntel.workflowAct"), Boolean(linkedTaskId)],
          ].map(([label, complete], index) => (
            <div key={String(label)} className="rounded-lg border px-2 py-2 text-center text-[10px] font-semibold" style={{ borderColor: complete ? "#8FC3A6" : "#D6DDD0", background: complete ? "#EDF7F1" : "#FBFAF6", color: complete ? "#1B5E3F" : "#65736A" }}>
              <div>{index + 1}</div><div className="mt-1 leading-4">{String(label)}</div>
            </div>
          ))}
        </div>
      </DrawerSection>

      <DrawerSection title={t("fieldIntel.recommended")}>
        <p className="text-[13px] leading-6 text-[#3B4A41]">{observation.recommended_action || vision.recommended_follow_up || "—"}</p>
        {actionError && <div role="alert" className="mt-3 rounded-lg border border-[#F0C8C1] bg-[#FFF4F1] px-3 py-2 text-[12px] text-[#9F2D20]">{actionError}</div>}
        {linkedTaskId && <div className="mt-3 rounded-xl border border-[#BFD8C9] bg-[#EDF7F1] p-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-[#1B5E3F]"><CheckCircle2 className="h-4 w-4" />{taskResult?.alreadyExisted ? t("fieldIntel.taskAlreadyCreated") : t("fieldIntel.taskCreated")}</div>
          <div className="mt-1 text-[12px] leading-5 text-[#3B4A41]">{taskResult?.title || observation.recommended_action || observation.summary}</div>
        </div>}
        <div className="mt-3 grid grid-cols-2 gap-2">
          {linkedTaskId ? (
            <a href={`/tasks?task_id=${encodeURIComponent(linkedTaskId)}&observation_id=${encodeURIComponent(String(observation.id))}`} className="inline-flex min-h-[42px] items-center justify-center gap-2 rounded-lg bg-[#0D2B1E] px-3 text-[12px] font-semibold text-white">
              <CheckCircle2 className="h-4 w-4" />{t("fieldIntel.openTask")}
            </a>
          ) : (
            <button type="button" disabled={busy} onClick={() => void createTask()} className="inline-flex min-h-[42px] items-center justify-center gap-2 rounded-lg bg-[#0D2B1E] px-3 text-[12px] font-semibold text-white disabled:opacity-60">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}{t("fieldIntel.createTask")}
            </button>
          )}
          <a href={askHref} className="inline-flex min-h-[42px] items-center justify-center gap-2 rounded-lg border border-[#D6DDD0] px-3 text-[12px] font-semibold text-[#10231B]">
            <Sparkles className="h-4 w-4" />{t("askAgroAi")}
          </a>
        </div>
        <p className="mt-2 text-[11px] leading-5 text-[#65736A]">{t("fieldIntel.actionContextHint")}</p>
      </DrawerSection>'''
source = replace_once(source, recommended_old, recommended_new, "drawer operating loop")
write(path, source)

# ---------------------------------------------------------------------------
# Ask AGRO-AI: carry and visibly pin the exact observation
# ---------------------------------------------------------------------------
path = "figma-enterprise-v4/src/app/components/Intelligence.tsx"
source = read(path)
source = replace_once(
    source,
    '''  async uploadEvidence(file: File, workspaceId?: string) {
    return apiClient.evidence.upload(file, undefined, workspaceId) as Promise<AnyRecord>;
  },''',
    '''  async uploadEvidence(file: File, workspaceId?: string) {
    return apiClient.evidence.upload(file, undefined, workspaceId) as Promise<AnyRecord>;
  },
  async getFieldObservation(observationId: string) {
    return apiClient.fieldIntelligence.observation(observationId) as Promise<AnyRecord>;
  },''',
    "intelligence observation dependency",
)
write(path, source)

path = "figma-enterprise-v4/src/app/components/intelligence/useIntelligenceController.ts"
source = read(path)
source = replace_once(
    source,
    '''  uploadEvidence: (file: File, workspaceId?: string) => Promise<AnyRecord>;
  planActions: (payload: AnyRecord) => Promise<AnyRecord[]>;''',
    '''  uploadEvidence: (file: File, workspaceId?: string) => Promise<AnyRecord>;
  getFieldObservation: (observationId: string) => Promise<AnyRecord>;
  planActions: (payload: AnyRecord) => Promise<AnyRecord[]>;''',
    "controller observation dependency type",
)
insert_after = '''export type IntelligenceDependencies = {
'''
# Add a bounded server-fetched observation snapshot as linked evidence. It is
# compact enough for every model route and preserves the exact observation ID.
helper_marker = '''};

export function useIntelligenceController'''
helper = '''};

function linkedObservationEvidence(observation: AnyRecord | null): AnyRecord[] {
  if (!observation?.id) return [];
  const vision = observation.structured?.vision || {};
  const payload = {
    observation_id: observation.id,
    field_name: observation.field_name,
    block_name: observation.block_name,
    crop: observation.crop,
    event_type: observation.event_type,
    severity: observation.severity,
    occurred_at: observation.occurred_at,
    summary: observation.summary,
    transcript: observation.corrected_transcript || observation.transcript,
    recommended_action: observation.recommended_action || vision.recommended_follow_up,
    visible_facts: Array.isArray(vision.visible_facts) ? vision.visible_facts.slice(0, 8) : [],
    hypotheses: Array.isArray(vision.hypotheses) ? vision.hypotheses.slice(0, 8) : [],
    uncertainties: Array.isArray(vision.uncertainties) ? vision.uncertainties.slice(0, 8) : [],
    correlation: observation.correlation,
    confidence: observation.confidence,
    asset_count: Array.isArray(observation.assets) ? observation.assets.length : 0,
  };
  return [{
    filename: `Field observation ${String(observation.id).slice(0, 8)}`,
    source_type: "field_observation",
    import_status: "linked",
    parsed_preview: JSON.stringify(payload).slice(0, 10000),
    observation_id: observation.id,
  }];
}

export function useIntelligenceController'''
source = replace_once(source, helper_marker, helper, "controller linked evidence helper")
source = replace_once(
    source,
    '''  const [fileImports, setFileImports] = useState<ChatFileImport[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const fileInputRef = useRef<HTMLInputElement | null>(null);''',
    '''  const [fileImports, setFileImports] = useState<ChatFileImport[]>([]);
  const [linkedObservation, setLinkedObservation] = useState<AnyRecord | null>(null);
  const [linkedObservationLoading, setLinkedObservationLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const contextualLaunchRef = useRef("");''',
    "controller linked observation state",
)
workspace_effect = '''  useEffect(() => {
    setMessages([]);
    setActiveConversationId("");
    setFileImports([]);
    setFailedPrompt("");
    refreshConversations().catch(() => null);
  }, [currentWorkspace?.id]);
'''
context_effect = workspace_effect + '''
  useEffect(() => {
    if (historyStatus === "loading") return;
    const observationId = new URLSearchParams(window.location.search).get("field_observation_id") || "";
    if (!observationId) {
      setLinkedObservation(null);
      return;
    }
    const launchKey = `${currentWorkspace?.id || "workspace"}:${observationId}`;
    if (contextualLaunchRef.current === launchKey) return;
    contextualLaunchRef.current = launchKey;
    setLinkedObservationLoading(true);
    deps.getFieldObservation(observationId).then((response) => {
      const observation = response.observation || response;
      setLinkedObservation(observation);
      const prompt = [
        t("intelligence.fieldObservationPrompt"),
        safeText(observation.summary || observation.corrected_transcript || observation.transcript),
      ].filter(Boolean).join("\n\n");
      return send(prompt, { fieldObservation: observation });
    }).catch((err) => {
      setError(err instanceof Error ? err.message : t("intelligence.fieldObservationUnavailable"));
    }).finally(() => setLinkedObservationLoading(false));
  }, [currentWorkspace?.id, historyStatus]);
'''
source = replace_once(source, workspace_effect, context_effect, "contextual observation launch")
source = replace_once(
    source,
    '''  function newChat() {
    setActiveConversationId(""); setMessages([]); setQuestion(""); setFileImports([]); setError(""); setNotice(""); setFailedPrompt("");
  }''',
    '''  function newChat() {
    setActiveConversationId(""); setMessages([]); setQuestion(""); setFileImports([]); setError(""); setNotice(""); setFailedPrompt("");
    setLinkedObservation(null);
    contextualLaunchRef.current = "";
    if (window.location.search) window.history.replaceState({}, "", "/intelligence");
  }''',
    "new chat context reset",
)
source = replace_once(
    source,
    '''  async function send(prompt = question, options: { retry?: boolean } = {}) {''',
    '''  async function send(prompt = question, options: { retry?: boolean; fieldObservation?: AnyRecord } = {}) {''',
    "contextual send options",
)
source = replace_once(
    source,
    '''      const evidence = [...importedBeforeSend, ...newlyImported].map(uploadMetadata);
      const history = priorRows.filter((row) => row.role === "user" || row.role === "assistant").slice(-12).map((row) => ({ role: row.role, content: safeText(row.content).slice(0, 2200) }));
      const request = { task: isReportIntent(clean) ? "report_factory" as const : "chat" as const, question: clean, workspace_id: currentWorkspace?.id, audience: "operator", history, uploaded_evidence: evidence, preferred_language: normalizedLocale } as AnyRecord;''',
    '''      const activeObservation = options.fieldObservation || linkedObservation;
      const evidence = [
        ...linkedObservationEvidence(activeObservation),
        ...[...importedBeforeSend, ...newlyImported].map(uploadMetadata),
      ];
      const history = priorRows.filter((row) => row.role === "user" || row.role === "assistant").slice(-12).map((row) => ({ role: row.role, content: safeText(row.content).slice(0, 2200) }));
      const request = {
        task: isReportIntent(clean) ? "report_factory" as const : "chat" as const,
        question: clean,
        workspace_id: currentWorkspace?.id,
        field_id: activeObservation?.field_id,
        field_observation_id: activeObservation?.id,
        audience: "operator",
        history,
        uploaded_evidence: evidence,
        preferred_language: normalizedLocale,
      } as AnyRecord;''',
    "linked evidence request",
)
source = replace_once(
    source,
    '''    fileImports,
    setFileImports,
    sidebarOpen,''',
    '''    fileImports,
    setFileImports,
    linkedObservation,
    linkedObservationLoading,
    sidebarOpen,''',
    "controller return linked observation",
)
write(path, source)

path = "figma-enterprise-v4/src/app/components/intelligence/IntelligenceView.tsx"
source = read(path)
source = replace_once(
    source,
    '''    fileImports,
    setFileImports,
    sidebarOpen,''',
    '''    fileImports,
    setFileImports,
    linkedObservation,
    linkedObservationLoading,
    sidebarOpen,''',
    "view linked state destructure",
)
card_anchor = '''              {error ? (
'''
card = '''              {(linkedObservation || linkedObservationLoading) ? (
                <section className="rounded-xl p-4 sm:p-5" style={{ background: "#EDF7F1", border: "1px solid #BFD8C9" }}>
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.12em]" style={{ color: "#2D6A4F" }}>{t("intelligence.fieldObservationContext")}</div>
                      <div className="mt-2 break-words text-[15px] font-semibold" style={{ color: TEXT }}>{safeText(linkedObservation?.field_name || linkedObservation?.block_name || t("fieldIntel.unassignedField"))}</div>
                      <p className="mt-1 break-words text-[13px] leading-6" style={{ color: MUTED }}>{linkedObservationLoading ? t("intelligence.fieldObservationLoading") : safeText(linkedObservation?.summary || linkedObservation?.corrected_transcript || linkedObservation?.transcript)}</p>
                      {!linkedObservationLoading && <div className="mt-2 flex flex-wrap gap-2 text-[11px]" style={{ color: MUTED }}><span>{safeText(linkedObservation?.event_type)}</span><span>·</span><span>{Array.isArray(linkedObservation?.assets) ? linkedObservation.assets.length : 0} {t("fieldIntel.attachments")}</span></div>}
                    </div>
                    {linkedObservation?.id ? <div className="flex flex-shrink-0 flex-wrap gap-2">
                      <a href={`/field-intelligence?observation_id=${encodeURIComponent(String(linkedObservation.id))}`} className="rounded-lg px-3 py-2 text-[12px] font-semibold" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: TEXT }}>{t("intelligence.openObservation")}</a>
                      <a href="/tasks" className="rounded-lg px-3 py-2 text-[12px] font-semibold" style={{ background: "#0D2B1E", color: "white" }}>{t("tasks")}</a>
                    </div> : null}
                  </div>
                </section>
              ) : null}

              {error ? (
'''
source = replace_once(source, card_anchor, card, "linked context card")
write(path, source)

# ---------------------------------------------------------------------------
# Command Center / Field Queue / Tasks: one navigable operating loop
# ---------------------------------------------------------------------------
path = "figma-enterprise-v4/src/app/components/Overview.tsx"
source = read(path)
source = replace_once(
    source,
    '''  const tasks = arr<Row>(tasksState.data?.tasks || center.operator_tasks);
  const missing = arr<Row>(center.missing_evidence);''',
    '''  const tasks = arr<Row>(tasksState.data?.tasks || center.operator_tasks);
  const routeMode = window.location.pathname.startsWith("/tasks") ? "tasks" : window.location.pathname.startsWith("/field-queue") ? "queue" : "command";
  const focusedTaskId = new URLSearchParams(window.location.search).get("task_id") || "";
  const displayTasks = useMemo(() => focusedTaskId ? [...tasks].sort((a, b) => String(a.id) === focusedTaskId ? -1 : String(b.id) === focusedTaskId ? 1 : 0) : tasks, [focusedTaskId, tasks]);
  const missing = arr<Row>(center.missing_evidence);''',
    "overview route context",
)
source = replace_once(
    source,
    '''            <h1 className="text-[26px] font-semibold tracking-tight sm:text-[30px]" style={{ color: TEXT }}>Command Center</h1>
            <p className="mt-2 max-w-3xl text-[13px] leading-relaxed sm:text-[14px]" style={{ color: MUTED }}>Field queue, tasks, evidence gaps, reports, and audit follow-through in one operating room.</p>''',
    '''            <h1 className="text-[26px] font-semibold tracking-tight sm:text-[30px]" style={{ color: TEXT }}>{routeMode === "tasks" ? "Tasks" : routeMode === "queue" ? "Field Queue" : "Command Center"}</h1>
            <p className="mt-2 max-w-3xl text-[13px] leading-relaxed sm:text-[14px]" style={{ color: MUTED }}>{routeMode === "tasks" ? "Execute and close the work created from field observations, decisions, and evidence gaps." : routeMode === "queue" ? "Review what needs attention, understand why, and turn the right item into accountable work." : "Capture, understand, decide, assign, and verify field work in one operating loop."}</p>''',
    "overview route header",
)
main_anchor = '''        {message ? <InlineState title={message} /> : null}

        <section className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 xl:grid-cols-5 xl:gap-4">'''
main_replacement = '''        {message ? <InlineState title={message} /> : null}

        <section className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            ["1", "Capture", "/field-intelligence", "Voice, photo, video"],
            ["2", "Understand", "/field-queue", "Review evidence and analysis"],
            ["3", "Decide", "/intelligence", "Ask AGRO-AI in context"],
            ["4", "Act", "/tasks", "Assign, complete, verify"],
          ].map(([step, label, href, detail]) => <a key={href} href={href} className="rounded-xl p-3 transition hover:-translate-y-0.5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="text-[10px] font-semibold uppercase tracking-[0.12em]" style={{ color: MUTED }}>{step}</div><div className="mt-1 text-[13px] font-semibold" style={{ color: TEXT }}>{label}</div><div className="mt-1 text-[11px] leading-4" style={{ color: MUTED }}>{detail}</div></a>)}
        </section>

        <section className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 xl:grid-cols-5 xl:gap-4">'''
source = replace_once(source, main_anchor, main_replacement, "overview operating loop nav")
source = replace_once(
    source,
    '''{tasks.length ? tasks.map((task, index) => <TaskCard key={task.id || index} task={task} busy={busy} onStatus={setTaskStatus} />) :''',
    '''{displayTasks.length ? displayTasks.map((task, index) => <TaskCard key={task.id || index} task={task} busy={busy} onStatus={setTaskStatus} focused={String(task.id) === focusedTaskId} />) :''',
    "task focus list",
)
source = replace_once(
    source,
    '''function TaskCard({ task, busy, onStatus }: { task: Row; busy: string; onStatus: (id: string, status: string) => void }) {
  return (
    <article className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>''',
    '''function TaskCard({ task, busy, onStatus, focused }: { task: Row; busy: string; onStatus: (id: string, status: string) => void; focused?: boolean }) {
  return (
    <article className="rounded-xl p-4" style={{ background: focused ? "#EDF7F1" : BG, border: `1px solid ${focused ? "#72A98B" : BORDER}`, boxShadow: focused ? "0 0 0 3px rgba(45,106,79,0.08)" : undefined }}>''',
    "task focused card",
)
source = replace_once(
    source,
    '''      <Chips items={lines(task.evidence_required || task.missing_evidence)} empty="No required evidence listed." />
      <div className="mt-3 flex flex-wrap gap-2">{[["open", "Reopen"], ["in_progress", "Start"], ["done", "Done"]].map(([status, label]) => <PortalButton key={status} variant="secondary" onClick={() => onStatus(String(task.id), status)} disabled={busy === task.id}>{label}</PortalButton>)}</div>''',
    '''      <Chips items={lines(task.evidence_required || task.missing_evidence)} empty="No required evidence listed." />
      {task.source_observation_id ? <div className="mt-3 rounded-lg p-3" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="text-[11px] font-semibold uppercase tracking-[0.1em]" style={{ color: MUTED }}>Source · Field Intelligence</div><div className="mt-2 flex flex-wrap gap-2"><a href={`/field-intelligence?observation_id=${encodeURIComponent(String(task.source_observation_id))}`} className="rounded-lg px-3 py-2 text-[12px] font-semibold" style={{ border: `1px solid ${BORDER}`, color: TEXT }}>Review observation</a><a href={`/intelligence?field_observation_id=${encodeURIComponent(String(task.source_observation_id))}&source=task`} className="rounded-lg px-3 py-2 text-[12px] font-semibold" style={{ background: "#0D2B1E", color: "white" }}>Ask AGRO-AI</a></div></div> : null}
      <div className="mt-3 flex flex-wrap gap-2">{[["open", "Reopen"], ["in_progress", "Start"], ["done", "Done"]].map(([status, label]) => <PortalButton key={status} variant="secondary" onClick={() => onStatus(String(task.id), status)} disabled={busy === task.id}>{label}</PortalButton>)}</div>''',
    "task source actions",
)
write(path, source)

# ---------------------------------------------------------------------------
# English source catalog. Runtime locale translation covers all enabled locales.
# ---------------------------------------------------------------------------
path = "figma-enterprise-v4/src/app/i18n.ts"
source = read(path)
source = replace_once(
    source,
    '''  "fieldIntel.createTask": "Create task", "fieldIntel.correlation": "AGRO-AI correlation",''',
    '''  "fieldIntel.createTask": "Create task", "fieldIntel.openTask": "Open task", "fieldIntel.taskCreated": "Task created and linked", "fieldIntel.taskAlreadyCreated": "Linked task already exists", "fieldIntel.taskFailed": "The task could not be created.",
  "fieldIntel.workflowTitle": "Observation to action", "fieldIntel.workflowCapture": "Capture", "fieldIntel.workflowUnderstand": "Understand", "fieldIntel.workflowDecide": "Decide", "fieldIntel.workflowAct": "Act", "fieldIntel.actionContextHint": "The task and Ask AGRO-AI keep this observation, transcript, media analysis, evidence, and uncertainty attached.",
  "fieldIntel.correlation": "AGRO-AI correlation",''',
    "field workflow translations",
)
source = replace_once(
    source,
    '''  "intelligence.createApproval": "Create approval", "intelligence.doIt": "Do it",
  fieldIntelligence: "Field Intelligence",''',
    '''  "intelligence.createApproval": "Create approval", "intelligence.doIt": "Do it",
  "intelligence.fieldObservationContext": "Linked Field Intelligence observation", "intelligence.fieldObservationLoading": "Loading the exact observation, transcript, media analysis, and evidence...", "intelligence.fieldObservationPrompt": "Analyze this linked field observation. Separate confirmed facts from uncertainty, explain what it means, identify what must be verified, and recommend the best next action.", "intelligence.fieldObservationUnavailable": "The linked field observation could not be loaded.", "intelligence.openObservation": "Open observation",
  fieldIntelligence: "Field Intelligence",''',
    "intelligence context translations",
)
write(path, source)

# ---------------------------------------------------------------------------
# Regression contracts
# ---------------------------------------------------------------------------
path = "figma-enterprise-v4/tests/field-intelligence-multimodal-contract.mjs"
source = read(path)
source = replace_once(
    source,
    '''const client = fs.readFileSync(path.join(root, "src/app/api/client.ts"), "utf8");
const locales = JSON.parse''',
    '''const client = fs.readFileSync(path.join(root, "src/app/api/client.ts"), "utf8");
const intelligenceController = fs.readFileSync(path.join(root, "src/app/components/intelligence/useIntelligenceController.ts"), "utf8");
const intelligenceView = fs.readFileSync(path.join(root, "src/app/components/intelligence/IntelligenceView.tsx"), "utf8");
const overview = fs.readFileSync(path.join(root, "src/app/components/Overview.tsx"), "utf8");
const locales = JSON.parse''',
    "workflow test source files",
)
source = replace_once(
    source,
    '''assert.match(component, /createTask/);
assert.match(component, /href="\\/intelligence"/);''',
    '''assert.match(component, /createTask/);
assert.match(component, /taskResult/);
assert.match(component, /field_observation_id=/);
assert.match(component, /task_id=/);
assert.match(intelligenceController, /linkedObservationEvidence/);
assert.match(intelligenceController, /getFieldObservation/);
assert.match(intelligenceController, /field_observation_id/);
assert.match(intelligenceView, /fieldObservationContext/);
assert.match(overview, /source_observation_id/);
assert.match(overview, /Observation to action|Capture/);''',
    "workflow frontend assertions",
)
write(path, source)

path = "agroai_api/tests/unit/test_field_intelligence.py"
source = read(path)
source = replace_once(
    source,
    '''from app.models.operational_records import EvidenceRecord''',
    '''from app.models.operational_records import EvidenceRecord, IngestionJob''',
    "task test import",
)
test_anchor = '''def test_idempotency_conflict_returns_409(client, db):
'''
new_test = '''def test_observation_task_is_idempotent_and_source_linked(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(
        client,
        headers,
        client_capture_id="cap-task-loop",
        idempotency_key="idem-task-loop",
        note_text="Inspect the north row for visible stress and verify with a follow-up photo.",
    ).json()["capture"]
    observation = _complete(client, headers, cap["id"]).json()["observation"]
    _process(db)

    first = client.post(
        f"/v1/field-intelligence/observations/{observation['id']}/tasks",
        json={},
        headers=headers,
    )
    second = client.post(
        f"/v1/field-intelligence/observations/{observation['id']}/tasks",
        json={},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["status"] == "created"
    assert second.json()["status"] == "existing"
    task = first.json()["task"]
    assert second.json()["task"]["id"] == task["id"]
    assert task["source_observation_id"] == observation["id"]
    assert task["created_from"] == "field_intelligence"
    job = db.get(IngestionJob, task["id"])
    assert job is not None
    assert (job.input_json or {}).get("source_observation_id") == observation["id"]
    refreshed = _fetch(client, headers, observation["id"])
    assert refreshed["task_ids"] == [task["id"]]


'''+test_anchor
source = replace_once(source, test_anchor, new_test, "idempotent task test")
write(path, source)

print("Field Intelligence operating-loop patch applied")
