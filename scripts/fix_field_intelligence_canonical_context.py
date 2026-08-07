from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELD = ROOT / "figma-enterprise-v4/src/app/components/FieldIntelligenceV2.tsx"
INTEL = ROOT / "figma-enterprise-v4/src/app/components/Intelligence.tsx"
TEST = ROOT / "figma-enterprise-v4/tests/field-intelligence-canonical-context-contract.mjs"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


field = FIELD.read_text(encoding="utf-8")

field = replace_once(
    field,
    '  const [busy, setBusy] = useState(false);\n  const [corrected, setCorrected] = useState(observation.corrected_transcript || observation.transcript || "");',
    '  const [busy, setBusy] = useState(false);\n  const [createdTask, setCreatedTask] = useState<any>(null);\n  const [taskError, setTaskError] = useState("");\n  const [corrected, setCorrected] = useState(observation.corrected_transcript || observation.transcript || "");',
    "drawer task state",
)

field = replace_once(
    field,
    '  const createTask = async () => {\n    setBusy(true);\n    try { await apiClient.fieldIntelligence.createTask(observation.id, {}); await onReload(); }\n    finally { setBusy(false); }\n  };',
    '''  const createTask = async () => {\n    setBusy(true);\n    setTaskError("");\n    try {\n      const response: any = await apiClient.fieldIntelligence.createTask(observation.id, {});\n      const task = response?.task || response;\n      if (!task?.id) throw new Error("The server did not return the created task.");\n      setCreatedTask(task);\n      await onReload();\n    } catch (error) {\n      setTaskError(error instanceof Error ? error.message : "Task creation failed. Retry from this observation.");\n    } finally {\n      setBusy(false);\n    }\n  };''',
    "canonical task creation",
)

field = replace_once(
    field,
    '<a href="/intelligence" className="inline-flex min-h-[42px] items-center justify-center gap-2 rounded-lg border border-[#D6DDD0] px-3 text-[12px] font-semibold text-[#10231B]">\n            <Sparkles className="h-4 w-4" />{t("askAgroAi")}\n          </a>',
    '<a href={`/intelligence?field_observation_id=${encodeURIComponent(String(observation.id))}&source=field-intelligence`} className="inline-flex min-h-[42px] items-center justify-center gap-2 rounded-lg border border-[#D6DDD0] px-3 text-[12px] font-semibold text-[#10231B]">\n            <Sparkles className="h-4 w-4" />{t("askAgroAi")}\n          </a>',
    "contextual Ask link",
)

field = replace_once(
    field,
    '''        </div>\n      </DrawerSection>\n\n      <DrawerSection title={t("fieldIntel.correlation")}>''',
    '''        </div>\n        {createdTask?.id && <div role="status" className="mt-3 rounded-xl border border-[#BFD8C9] bg-[#EDF7F1] p-3 text-[12px] text-[#1B5E3F]">\n          <div className="font-semibold">Task created and linked</div>\n          <div className="mt-1 text-[#536158]">{createdTask.title || "The observation is now accountable work in Tasks."}</div>\n          <a href={`/tasks?task_id=${encodeURIComponent(String(createdTask.id))}&observation_id=${encodeURIComponent(String(observation.id))}`} className="mt-2 inline-flex rounded-lg bg-[#0D2B1E] px-3 py-2 font-semibold text-white">Open task</a>\n        </div>}\n        {taskError && <div role="alert" className="mt-3 rounded-xl border border-[#E6B7AD] bg-[#FFF4F1] p-3 text-[12px] text-[#9F2D20]">{taskError}</div>}\n      </DrawerSection>\n\n      <DrawerSection title={t("fieldIntel.correlation")}>''',
    "task result UI",
)

FIELD.write_text(field, encoding="utf-8")

intel = INTEL.read_text(encoding="utf-8")
intel = replace_once(
    intel,
    'import { API_BASE_URL, apiClient } from "../api/client";',
    'import { useEffect, useRef, useState } from "react";\nimport { API_BASE_URL, apiClient } from "../api/client";',
    "react hooks import",
)

intel = replace_once(
    intel,
    'type AnyRecord = Record<string, any>;\n\nconst RESPONSE_LANGUAGE_STORAGE_KEY',
    '''type AnyRecord = Record<string, any>;\n\nfunction contextualFieldObservationId(): string {\n  if (typeof window === "undefined" || window.location.pathname !== "/intelligence") return "";\n  return new URLSearchParams(window.location.search || "").get("field_observation_id") || "";\n}\n\nfunction linkedFieldObservationEvidence(observation: AnyRecord): AnyRecord {\n  const vision = observation?.structured?.vision || observation?.structured_json?.vision || {};\n  return {\n    filename: `Field Intelligence observation ${String(observation.id || "").slice(0, 8)}`,\n    source_type: "field_observation",\n    import_status: "linked",\n    observation_id: observation.id,\n    parsed_preview: JSON.stringify({\n      observation_id: observation.id,\n      field_name: observation.field_name,\n      block_name: observation.block_name,\n      crop: observation.crop,\n      event_type: observation.event_type,\n      severity: observation.severity,\n      occurred_at: observation.occurred_at,\n      summary: observation.summary,\n      transcript: observation.corrected_transcript || observation.transcript,\n      recommended_action: observation.recommended_action || vision.recommended_follow_up,\n      visible_facts: Array.isArray(vision.visible_facts) ? vision.visible_facts.slice(0, 10) : [],\n      hypotheses: Array.isArray(vision.hypotheses) ? vision.hypotheses.slice(0, 10) : [],\n      uncertainties: Array.isArray(vision.uncertainties) ? vision.uncertainties.slice(0, 10) : [],\n      media_moments: Array.isArray(vision.media_moments) ? vision.media_moments.slice(0, 10) : [],\n      correlation: observation.correlation || observation.correlation_json,\n      confidence: observation.confidence,\n      evidence_ids: observation.evidence_ids || observation.evidence_ids_json || [],\n      asset_count: Array.isArray(observation.assets) ? observation.assets.length : 0,\n    }).slice(0, 12000),\n  };\n}\n\nasync function withFieldObservationContext(request: AnyRecord): Promise<AnyRecord> {\n  const observationId = contextualFieldObservationId();\n  if (!observationId) return request;\n  const response: AnyRecord = await apiClient.fieldIntelligence.observation(observationId) as AnyRecord;\n  const observation = response?.observation || response;\n  if (!observation?.id) return request;\n  const existing = Array.isArray(request?.uploaded_evidence) ? request.uploaded_evidence : [];\n  return {\n    ...(request || {}),\n    field_id: request?.field_id || observation.field_id,\n    field_observation_id: observationId,\n    uploaded_evidence: [\n      linkedFieldObservationEvidence(observation),\n      ...existing.filter((item: AnyRecord) => String(item?.observation_id || "") !== observationId),\n    ],\n  };\n}\n\nconst RESPONSE_LANGUAGE_STORAGE_KEY''',
    "context helpers",
)

intel = replace_once(
    intel,
    '  async runIntelligence(request: AnyRecord) {\n    const languageAwareRequest = withIndependentResponseLanguage(request);',
    '  async runIntelligence(request: AnyRecord) {\n    const contextualRequest = await withFieldObservationContext(request);\n    const languageAwareRequest = withIndependentResponseLanguage(contextualRequest);',
    "contextual request enrichment",
)

intel = replace_once(
    intel,
    '''export function Intelligence() {\n  const controller = useIntelligenceController(intelligenceDependencies);\n  return <>\n    <IntelligencePlanControls />\n    <IntelligenceView controller={controller} />\n  </>;\n}''',
    '''type IntelligenceController = ReturnType<typeof useIntelligenceController>;\n\nfunction contextualPrompt(observation: AnyRecord): string {\n  const summary = String(observation.summary || observation.corrected_transcript || observation.transcript || "Review the linked field observation.").trim();\n  return [\n    "Analyze this linked Field Intelligence observation as one operational case.",\n    "Use its transcript, media analysis, visible facts, hypotheses, evidence, and uncertainty. Separate confirmed facts from hypotheses, explain what matters, state what must be verified, and recommend the best next accountable action. Do not invent measurements or diagnoses.",\n    summary,\n  ].join("\\n\\n");\n}\n\nfunction FieldObservationContext({ controller }: { controller: IntelligenceController }) {\n  const observationId = contextualFieldObservationId();\n  const [observation, setObservation] = useState<AnyRecord | null>(null);\n  const [loadError, setLoadError] = useState("");\n  const sentObservationRef = useRef("");\n\n  useEffect(() => {\n    let cancelled = false;\n    setObservation(null);\n    setLoadError("");\n    if (!observationId) return () => { cancelled = true; };\n    void apiClient.fieldIntelligence.observation(observationId)\n      .then((response: any) => {\n        if (cancelled) return;\n        const row = response?.observation || response;\n        if (!row?.id) throw new Error("The linked field observation could not be loaded.");\n        setObservation(row);\n      })\n      .catch((error: unknown) => {\n        if (!cancelled) setLoadError(error instanceof Error ? error.message : "The linked field observation could not be loaded.");\n      });\n    return () => { cancelled = true; };\n  }, [observationId]);\n\n  useEffect(() => {\n    if (!observation?.id || sentObservationRef.current === String(observation.id)) return;\n    sentObservationRef.current = String(observation.id);\n    void controller.send(contextualPrompt(observation));\n  }, [controller.send, observation]);\n\n  if (!observationId) return null;\n  return <section className="border-b border-[#BFD8C9] bg-[#EDF7F1] px-4 py-3 sm:px-8">\n    <div className="mx-auto flex max-w-[1100px] flex-wrap items-start justify-between gap-3">\n      <div className="min-w-0 flex-1">\n        <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#2D6A4F]">Field Intelligence · linked observation</div>\n        <div className="mt-1 text-[14px] font-semibold text-[#10231B]">{observation?.field_name || observation?.block_name || "Field observation"}</div>\n        <div className="mt-1 line-clamp-2 text-[12px] leading-5 text-[#536158]">{loadError || observation?.summary || observation?.corrected_transcript || observation?.transcript || "Loading the exact field observation…"}</div>\n      </div>\n      <a href={`/field-intelligence?observation_id=${encodeURIComponent(observationId)}`} className="inline-flex min-h-[38px] items-center rounded-lg border border-[#8FC3A6] bg-white px-3 text-[12px] font-semibold text-[#1B5E3F]">Open observation</a>\n    </div>\n  </section>;\n}\n\nexport function Intelligence() {\n  const controller = useIntelligenceController(intelligenceDependencies);\n  return <>\n    <IntelligencePlanControls />\n    <FieldObservationContext controller={controller} />\n    <IntelligenceView controller={controller} />\n  </>;\n}''',
    "canonical contextual bootstrap",
)

INTEL.write_text(intel, encoding="utf-8")

TEST.write_text(r'''import fs from "node:fs";\nimport assert from "node:assert/strict";\n\nconst field = fs.readFileSync(new URL("../src/app/components/FieldIntelligenceV2.tsx", import.meta.url), "utf8");\nconst intelligence = fs.readFileSync(new URL("../src/app/components/Intelligence.tsx", import.meta.url), "utf8");\n\nassert.match(field, /field_observation_id=\$\{encodeURIComponent\(String\(observation\.id\)\)\}/);\nassert.match(field, /Task created and linked/);\nassert.match(field, /\/tasks\?task_id=\$\{encodeURIComponent\(String\(createdTask\.id\)\)\}&observation_id=/);\nassert.doesNotMatch(field, /<a href="\/intelligence"[^>]*>\s*<Sparkles/);\n\nassert.match(intelligence, /function contextualFieldObservationId\(\)/);\nassert.match(intelligence, /field_observation_id: observationId/);\nassert.match(intelligence, /linkedFieldObservationEvidence/);\nassert.match(intelligence, /Field Intelligence · linked observation/);\nassert.match(intelligence, /void controller\.send\(contextualPrompt\(observation\)\)/);\nassert.match(intelligence, /const contextualRequest = await withFieldObservationContext\(request\)/);\n\nconsole.log("field_intelligence_canonical_context_contract=ok");\n'''.replace('\\n', '\n'), encoding="utf-8")

print("patched Field Intelligence canonical context and task workflow")
