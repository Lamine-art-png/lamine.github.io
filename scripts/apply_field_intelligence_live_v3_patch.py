from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


EDGE = "cloudflare/edge-gateway/src/edge-main-v3.ts"
replace_once(
    EDGE,
    '''  const image = Array.from(decodeBase64(payload.image));
  const candidates = model === FIELD_VISION_PRIMARY_MODEL
    ? [FIELD_VISION_PRIMARY_MODEL, FIELD_VISION_FALLBACK_MODEL]
    : [model];
  for (const candidate of candidates) {
    try {
      const result = await env.AI.run(candidate, { image, prompt, max_tokens: 1400 });
      return json({
''',
    '''  const imageBytes = Array.from(decodeBase64(payload.image));
  const imageDataUri = `data:${contentType};base64,${payload.image}`;
  const candidates = model === FIELD_VISION_PRIMARY_MODEL
    ? [FIELD_VISION_PRIMARY_MODEL, FIELD_VISION_FALLBACK_MODEL]
    : [model];
  for (const candidate of candidates) {
    try {
      const result = candidate === FIELD_VISION_PRIMARY_MODEL
        ? await env.AI.run(FIELD_VISION_PRIMARY_MODEL, { image: imageDataUri, prompt, max_tokens: 1400, temperature: 0.1 })
        : await env.AI.run(FIELD_VISION_FALLBACK_MODEL, { image: imageBytes, prompt, max_tokens: 1400 });
      return json({
''',
)

ROUTES = "agroai_api/app/api/v1/field_intelligence.py"
replace_once(
    ROUTES,
    'frame_timestamp_seconds: float | None = Form(default=None, ge=0, le=MAX_RECORDING_SECONDS if "MAX_RECORDING_SECONDS" in globals() else 900),\n',
    'frame_timestamp_seconds: float | None = Form(default=None, ge=0, le=900),\n',
)

COMPONENT = "figma-enterprise-v4/src/app/components/FieldIntelligenceV2.tsx"
replace_once(
    COMPONENT,
    '''          {Array.isArray(vision.observations) && <ul className="mt-2 space-y-1 text-[12px] text-[#3B4A41]">
            {vision.observations.map((item: string, index: number) => <li key={index}>• {item}</li>)}
          </ul>}
          {Array.isArray(vision.uncertainties) && vision.uncertainties.length > 0 && <p className="mt-2 flex gap-1 text-[11px] text-[#B26B00]"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />{vision.uncertainties.join(", ")}</p>}
''',
    '''          <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
            {vision.crop_condition && vision.crop_condition !== "unknown" && <span className="rounded-full bg-white px-2 py-1">{t("fieldIntel.cropCondition")}: {String(vision.crop_condition).replaceAll("_", " ")}</span>}
            {vision.coverage_assessment && vision.coverage_assessment !== "unknown" && <span className="rounded-full bg-white px-2 py-1">{t("fieldIntel.coverageAssessment")}: {String(vision.coverage_assessment).replaceAll("_", " ")}</span>}
            {vision.equipment_condition && !["unknown", "not_visible"].includes(vision.equipment_condition) && <span className="rounded-full bg-white px-2 py-1">{t("fieldIntel.equipmentCondition")}: {String(vision.equipment_condition).replaceAll("_", " ")}</span>}
          </div>
          {Array.isArray(vision.visible_facts) && vision.visible_facts.length > 0 && <div className="mt-3">
            <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[#2D6A4F]">{t("fieldIntel.visibleFacts")}</div>
            <ul className="mt-1 space-y-2 text-[12px] text-[#3B4A41]">
              {vision.visible_facts.map((item: any, index: number) => <li key={index} className="rounded-lg bg-white/80 p-2"><span className="font-semibold">{item?.label || "—"}</span>{item?.evidence && <span> · {item.evidence}</span>}{Number.isFinite(Number(item?.confidence)) && <span className="ml-1 text-[#65736A]">({Math.round(Number(item.confidence) * 100)}%)</span>}</li>)}
            </ul>
          </div>}
          {Array.isArray(vision.hypotheses) && vision.hypotheses.length > 0 && <div className="mt-3">
            <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[#B26B00]">{t("fieldIntel.hypotheses")}</div>
            <ul className="mt-1 space-y-2 text-[12px] text-[#3B4A41]">
              {vision.hypotheses.map((item: any, index: number) => <li key={index} className="rounded-lg border border-[#EAD8AF] bg-[#FFF9EA] p-2"><span className="font-semibold">{item?.label || "—"}</span>{item?.evidence && <span> · {item.evidence}</span>}{item?.verification && <div className="mt-1 text-[11px] text-[#65736A]">{t("fieldIntel.verifyBy")}: {item.verification}</div>}</li>)}
            </ul>
          </div>}
          {Array.isArray(vision.observations) && vision.observations.length > 0 && <ul className="mt-2 space-y-1 text-[12px] text-[#3B4A41]">
            {vision.observations.map((item: string, index: number) => <li key={index}>• {item}</li>)}
          </ul>}
          {Array.isArray(vision.media_moments) && vision.media_moments.length > 0 && <div className="mt-3">
            <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[#2D6A4F]">{t("fieldIntel.videoMoments")}</div>
            <ul className="mt-1 space-y-1 text-[12px] text-[#3B4A41]">{vision.media_moments.map((item: any, index: number) => <li key={index}>• {Number.isFinite(Number(item?.frame_timestamp_seconds)) ? `${Math.floor(Number(item.frame_timestamp_seconds) / 60)}:${String(Math.round(Number(item.frame_timestamp_seconds)) % 60).padStart(2, "0")} · ` : ""}{item?.summary || (item?.possible_issues || []).join(", ") || "—"}</li>)}</ul>
          </div>}
          {Array.isArray(vision.uncertainties) && vision.uncertainties.length > 0 && <p className="mt-2 flex gap-1 text-[11px] text-[#B26B00]"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />{vision.uncertainties.join(", ")}</p>}
          {vision.human_review_required && <p className="mt-2 text-[11px] font-medium text-[#B26B00]">{t("fieldIntel.humanReviewRequired")}</p>}
''',
)

I18N = "figma-enterprise-v4/src/app/i18n.ts"
replace_once(
    I18N,
    '  "fieldIntel.hypotheses": "Possible conditions",\n',
    '  "fieldIntel.hypotheses": "Possible conditions",\n  "fieldIntel.cropCondition": "Crop condition",\n  "fieldIntel.coverageAssessment": "Coverage",\n  "fieldIntel.equipmentCondition": "Equipment",\n  "fieldIntel.verifyBy": "Verify by",\n  "fieldIntel.videoMoments": "Video moments",\n  "fieldIntel.humanReviewRequired": "Human confirmation is required before acting on this analysis.",\n',
)
replace_once(
    I18N,
    '  "fieldIntel.hypotheses": "Conditions possibles",\n',
    '  "fieldIntel.hypotheses": "Conditions possibles",\n  "fieldIntel.cropCondition": "État de la culture",\n  "fieldIntel.coverageAssessment": "Couverture",\n  "fieldIntel.equipmentCondition": "Équipement",\n  "fieldIntel.verifyBy": "À vérifier par",\n  "fieldIntel.videoMoments": "Moments de la vidéo",\n  "fieldIntel.humanReviewRequired": "Une confirmation humaine est requise avant d’agir sur cette analyse.",\n',
)

BACKEND_TEST = "agroai_api/tests/test_field_intelligence_multimodal_v3.py"
replace_once(
    BACKEND_TEST,
    '    assert "degraded" in edge\n',
    '    assert "degraded" in edge\n    assert "imageDataUri" in edge\n    assert "temperature: 0.1" in edge\n',
)

FRONTEND_TEST = "figma-enterprise-v4/tests/field-intelligence-multimodal-contract.mjs"
replace_once(
    FRONTEND_TEST,
    'assert.match(component, /liveVision\\.visible_facts/);\n',
    'assert.match(component, /liveVision\\.visible_facts/);\nassert.match(component, /vision\\.visible_facts/);\nassert.match(component, /vision\\.hypotheses/);\nassert.match(component, /vision\\.media_moments/);\n',
)

print("Field Intelligence final vision and evidence UI patch applied")
