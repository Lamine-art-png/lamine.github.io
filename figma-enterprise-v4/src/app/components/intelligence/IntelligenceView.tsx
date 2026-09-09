import { useState } from "react";
import { AudioLines, Download, Eye, FileText, Mail, MessageSquare, Plus, RefreshCw, Search, Send, Trash2, UploadCloud, X } from "lucide-react";
import { LanguageSelector } from "../LanguageSelector";
import { BG, BORDER, MUTED, SURFACE, TEXT } from "../portalUi";
import { safeText, AnyRecord } from "./intelligenceSupport";
import { DecisionEvidencePanel } from "./DecisionEvidencePanel";
import type { useIntelligenceController } from "./useIntelligenceController";
import { openAgroAiVoice, VoiceDictationButton } from "../voice/VoiceDictationButton";

type Controller = ReturnType<typeof useIntelligenceController>;

export function IntelligenceView({ controller }: { controller: Controller }) {
  const [artifactPreview, setArtifactPreview] = useState<AnyRecord | null>(null);
  const {
    t,
    messages,
    filteredConversations,
    activeConversationId,
    conversationSearch,
    setConversationSearch,
    historyStatus,
    question,
    setQuestion,
    loading,
    reportBusyId,
    reportEmailBusyId,
    actionBusyId,
    artifactBusyId,
    notice,
    error,
    failedPrompt,
    fileImports,
    setFileImports,
    sidebarOpen,
    setSidebarOpen,
    fileInputRef,
    hasFailed,
    prompts,
    riskLabel,
    loadConversation,
    deleteConversation,
    newChat,
    onFilesSelected,
    downloadReportFor,
    emailReportFor,
    runAction,
    downloadGeneratedArtifact,
    send,
    onKeyDown,
    sendDisabled,
  } = controller;

  const sidebarProps = {
    t,
    filteredConversations,
    activeConversationId,
    conversationSearch,
    setConversationSearch,
    historyStatus,
    loadConversation,
    deleteConversation,
    newChat,
    close: () => setSidebarOpen(false),
  };

  return (
    <div className="min-h-full" style={{ background: BG }}>
      <main className="relative flex min-h-full min-w-0">
        {sidebarOpen ? (
          <aside className="hidden w-[300px] flex-shrink-0 flex-col border-r p-4 lg:flex" style={{ background: SURFACE, borderColor: BORDER }}>
            <ConversationSidebar {...sidebarProps} />
          </aside>
        ) : null}

        {sidebarOpen ? (
          <div className="fixed inset-0 z-[80] lg:hidden">
            <button type="button" className="absolute inset-0 bg-black/45" onClick={() => setSidebarOpen(false)} aria-label={t("intelligence.closeSidebar")} />
            <aside
              className="absolute inset-y-0 left-0 flex w-[min(88vw,340px)] flex-col p-4 shadow-2xl"
              style={{ background: SURFACE, paddingTop: "max(1rem, env(safe-area-inset-top))", paddingBottom: "max(1rem, env(safe-area-inset-bottom))" }}
            >
              <ConversationSidebar {...sidebarProps} />
            </aside>
          </div>
        ) : null}

        <section className="flex min-w-0 flex-1 flex-col">
          <header className="px-4 py-5 sm:px-8 sm:py-6" style={{ background: "#0D2B1E", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
            <div className="flex items-start justify-between gap-3 sm:gap-4">
              <div className="min-w-0">
                <div className="inline-flex rounded-full px-3 py-1 text-[10px] font-semibold sm:text-[11px]" style={{ background: "rgba(255,255,255,0.12)", color: "white" }}>{t("intelligence.workspaceBadge")}</div>
                <h1 className="mt-3 text-[24px] font-semibold tracking-tight sm:text-[28px]" style={{ color: "white" }}>{t("intelligence.title")}</h1>
                <p className="mt-2 max-w-2xl text-[12px] leading-relaxed sm:text-[13px]" style={{ color: "rgba(255,255,255,0.68)" }}>{t("intelligence.subtitle")}</p>
              </div>
              {!sidebarOpen ? (
                <button type="button" onClick={() => setSidebarOpen(true)} className="flex-shrink-0 rounded-lg px-3 py-2 text-[12px] font-medium" style={{ background: "rgba(255,255,255,0.12)", color: "white" }}>
                  <span className="inline-flex items-center gap-2"><FileText size={15} /><span className="hidden min-[390px]:inline">{t("intelligence.history")}</span></span>
                </button>
              ) : null}
            </div>
          </header>

          <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6 sm:py-7">
            <div className="mx-auto max-w-[900px] space-y-4 sm:space-y-5">
              {error ? (
                <div className="flex flex-col gap-3 rounded-xl px-4 py-3 text-[13px] sm:flex-row sm:items-center sm:justify-between" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: "#991B1B" }}>
                  <span className="min-w-0 break-words">{error}</span>
                  {failedPrompt ? <button type="button" onClick={() => send(failedPrompt, { retry: true })} disabled={loading} className="inline-flex flex-shrink-0 items-center justify-center gap-2 rounded-lg px-3 py-2 text-[12px] font-semibold" style={{ background: "#0D2B1E", color: "white" }}><RefreshCw size={14} /> {t("retry")}</button> : null}
                </div>
              ) : null}
              {notice ? <div className="break-words rounded-xl px-4 py-3 text-[13px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: "#0D2B1E" }}>{notice}</div> : null}

              {!messages.length && !loading ? (
                <section className="rounded-xl p-4 sm:p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
                  <div className="text-[11px] font-semibold uppercase sm:text-[12px]" style={{ color: MUTED }}>{t("intelligence.startThread")}</div>
                  <h2 className="mt-3 text-[21px] font-semibold sm:text-[24px]" style={{ color: TEXT }}>{t("intelligence.askOrImport")}</h2>
                  <p className="mt-2 max-w-2xl text-[13px] leading-relaxed sm:text-[14px]" style={{ color: MUTED }}>{t("intelligence.liveEvidenceBody")}</p>
                  <div className="mt-5 flex flex-wrap gap-2">{prompts.map((prompt) => <button key={prompt} type="button" onClick={() => send(prompt)} className="max-w-full rounded-full px-3 py-2 text-left text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>{prompt}</button>)}</div>
                </section>
              ) : null}

              {messages.map((message, index) => {
                const actions = Array.isArray(message.agentic_actions) ? message.agentic_actions : [];
                return (
                  <div key={message.id || index} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                    <article className={message.role === "user" ? "max-w-[90%] sm:max-w-[72%]" : "w-full max-w-[820px]"}>
                      <div className="whitespace-pre-wrap rounded-2xl px-4 py-3 text-[14px] leading-6 sm:px-5 sm:py-4 sm:text-[15px] sm:leading-7" style={{ background: message.role === "user" ? "#0D2B1E" : SURFACE, color: message.role === "user" ? "white" : TEXT, border: `1px solid ${message.role === "user" ? "#0D2B1E" : BORDER}` }}>
                        {safeText(message.content)}
                        {message.role === "assistant" && message.decision_details ? <DecisionEvidencePanel details={message.decision_details} t={t} /> : null}
                        {message.role === "assistant" && message.artifact ? (
                          <div className="mt-4 flex flex-col gap-2 whitespace-normal min-[420px]:flex-row min-[420px]:flex-wrap">
                            <button type="button" onClick={() => downloadReportFor(message)} disabled={reportBusyId === String(message.id || index)} className="inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-[12px] font-semibold disabled:opacity-60" style={{ background: "#0D2B1E", color: "white" }}>{reportBusyId === String(message.id || index) ? <FileText size={15} /> : <Download size={15} />}{reportBusyId === String(message.id || index) ? t("intelligence.preparingPdf") : t("intelligence.downloadPdf")}</button>
                            <button type="button" onClick={() => emailReportFor(message)} disabled={reportEmailBusyId === String(message.id || index)} className="inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-[12px] font-semibold disabled:opacity-60" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}><Mail size={15} />{reportEmailBusyId === String(message.id || index) ? t("intelligence.emailing") : t("intelligence.emailToMe")}</button>
                          </div>
                        ) : null}
                        {message.role === "assistant" && actions.length ? (
                          <div className="mt-4 space-y-2 whitespace-normal">
                            {actions.map((action: AnyRecord) => {
                              const actionId = String(action.id || `${message.id}-${action.action_type}`);
                              const result = action.execution_result || {};
                              const resultStatus = String(result.status || action.status || "");
                              const executed = ["executed", "approval_recorded", "created"].includes(resultStatus);
                              const blocked = resultStatus === "blocked";
                              const generatedArtifact = result.artifact;
                              const draft = result.draft;
                              const sync = result.sync;
                              const changedWorkspace = result.created_workspace || result.updated_workspace;
                              const createdTask = result.created_task || result.created_approval_task || result.task;
                              return (
                                <div key={actionId} className="rounded-xl p-3" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                                    <div className="min-w-0"><div className="break-words text-[13px] font-semibold" style={{ color: TEXT }}>{safeText(action.title || action.action_type)}</div><div className="mt-1 break-words text-[12px] leading-relaxed" style={{ color: MUTED }}>{safeText(action.description)}</div><div className="mt-2 text-[11px] font-semibold" style={{ color: action.approval_required ? "#92400E" : "#0D2B1E" }}>{riskLabel(action)}</div></div>
                                    <button type="button" onClick={() => runAction(message, action)} disabled={executed || blocked || actionBusyId === actionId} className="flex-shrink-0 rounded-lg px-3 py-2 text-[12px] font-semibold disabled:opacity-50" style={{ background: action.approval_required ? "#92400E" : "#0D2B1E", color: "white" }}>{executed ? t("done") : actionBusyId === actionId ? t("working") : action.approval_required ? t("intelligence.createApproval") : t("intelligence.doIt")}</button>
                                  </div>
                                  {generatedArtifact?.preview ? (
                                    <ArtifactPreviewInline
                                      artifact={generatedArtifact}
                                      onOpen={() => setArtifactPreview(generatedArtifact)}
                                    />
                                  ) : null}
                                  {generatedArtifact?.download_url ? (
                                    <div className="mt-3 flex flex-wrap gap-2">
                                      {generatedArtifact?.preview ? (
                                        <button
                                          type="button"
                                          onClick={() => setArtifactPreview(generatedArtifact)}
                                          className="inline-flex max-w-full items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-semibold"
                                          style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: TEXT }}
                                        >
                                          <Eye size={14} />
                                          <span>{t("intelligence.previewArtifact")}</span>
                                        </button>
                                      ) : null}
                                      <button
                                        type="button"
                                        onClick={() => downloadGeneratedArtifact(action)}
                                        disabled={artifactBusyId === String(generatedArtifact.id || generatedArtifact.filename)}
                                        className="inline-flex max-w-full items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-semibold disabled:opacity-60"
                                        style={{ background: "#0D2B1E", color: "white" }}
                                        aria-label={safeText(generatedArtifact.filename)}
                                      >
                                        <Download size={14} />
                                        <span className="truncate">{safeText(generatedArtifact.filename)}</span>
                                      </button>
                                    </div>
                                  ) : null}
                                  {draft ? (
                                    <div className="mt-3 rounded-lg p-3" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
                                      {draft.to_email ? <div className="break-words text-[11px]" style={{ color: MUTED }}>{safeText(draft.to_email)}</div> : null}
                                      <div className="mt-1 break-words text-[12px] font-semibold" style={{ color: TEXT }}>{safeText(draft.subject)}</div>
                                      <div className="mt-2 whitespace-pre-wrap break-words text-[12px] leading-5" style={{ color: TEXT }}>{safeText(draft.body)}</div>
                                    </div>
                                  ) : null}
                                  {sync?.message ? <div className="mt-3 break-words text-[11px] leading-5" style={{ color: MUTED }}>{safeText(sync.message)}</div> : null}
                                  {changedWorkspace?.name ? <div className="mt-3 break-words text-[12px] font-semibold" style={{ color: "#0D2B1E" }}>{safeText(changedWorkspace.name)}</div> : null}
                                  {createdTask?.title ? <div className="mt-3 break-words text-[12px] font-semibold" style={{ color: "#0D2B1E" }}>{safeText(createdTask.title)}</div> : null}
                                  {action.execution_error ? <div className="mt-3 break-words text-[11px]" style={{ color: "#991B1B" }}>{safeText(action.execution_error)}</div> : null}
                                </div>
                              );
                            })}
                          </div>
                        ) : null}
                      </div>
                    </article>
                  </div>
                );
              })}

              {loading ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: MUTED }}>{t("intelligence.preparingAnswer")}</div> : null}
            </div>
          </div>

          <footer className="px-3 pb-3 sm:px-6 sm:pb-6" style={{ paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))" }}>
            <div className="mx-auto max-w-[900px] rounded-2xl p-3 shadow-[0_18px_60px_rgba(16,35,27,0.08)] sm:p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              {fileImports.length ? <div className="mb-3 flex flex-wrap gap-2">{fileImports.map((item) => <div key={item.id} className="flex max-w-full items-center gap-2 rounded-full px-3 py-2 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}><span className="max-w-[140px] truncate font-medium sm:max-w-[180px]">{item.filename}</span><span className="truncate" style={{ color: item.status === "failed" ? "#991B1B" : MUTED }}>{item.status === "queued" ? t("intelligence.fileQueued") : item.status === "uploading" ? t("intelligence.fileUploading") : item.status === "imported" ? t("intelligence.fileImported") : t("intelligence.fileFailed")}</span><button type="button" onClick={() => setFileImports((current) => current.filter((row) => row.id !== item.id))} title={t("remove")}><X size={13} /></button></div>)}</div> : null}
              {hasFailed ? <div className="mb-3 text-[12px]" style={{ color: "#991B1B" }}>{t("intelligence.fileFailedBeforeSend")}</div> : null}

              <div className="mb-2 flex sm:hidden">
                <button type="button" onClick={() => fileInputRef.current?.click()} className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-medium" style={{ border: `1px solid ${BORDER}`, color: TEXT }}><UploadCloud size={15} /> {t("intelligence.importFiles")}</button>
              </div>
              <div className="flex items-end gap-2 sm:gap-3">
                <button type="button" onClick={() => fileInputRef.current?.click()} className="hidden flex-shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-medium sm:inline-flex" style={{ border: `1px solid ${BORDER}`, color: TEXT }}><UploadCloud size={15} /> {t("intelligence.importFiles")}</button>
                <input ref={fileInputRef} type="file" multiple className="hidden" accept=".csv,.xlsx,.xls,.pdf,.txt,.md,.json,.geojson,.kml,.zip" onChange={(event) => onFilesSelected(event.target.files)} />
                <textarea value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={onKeyDown} rows={2} placeholder={t("intelligence.placeholder")} className="min-h-[48px] min-w-0 flex-1 resize-none rounded-lg px-3 py-3 text-[16px] outline-none sm:px-4 sm:text-[14px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
                <VoiceDictationButton
                  disabled={loading}
                  onTranscript={(transcript) => setQuestion((current: string) => [current.trim(), transcript.trim()].filter(Boolean).join(" "))}
                />
                <button
                  type="button"
                  onClick={() => openAgroAiVoice("ask")}
                  className="inline-flex h-[48px] flex-shrink-0 items-center justify-center gap-2 rounded-lg border px-3 text-[12px] font-semibold"
                  style={{ background: "#EEF8E8", borderColor: "#BFD8C9", color: "#16533C" }}
                  title="Start live voice conversation"
                  aria-label="Start live voice conversation"
                >
                  <AudioLines size={18} /><span className="hidden xl:inline">Live voice</span>
                </button>
                <button type="button" disabled={sendDisabled} onClick={() => send()} className="inline-flex h-[48px] w-[48px] flex-shrink-0 items-center justify-center rounded-lg disabled:opacity-50 sm:w-[52px]" style={{ background: "#0D2B1E", color: "white" }} title={t("send")}><Send size={18} /></button>
              </div>
              <div className="mt-3 hidden text-[11px] sm:block" style={{ color: MUTED }}>{t("intelligence.enterHint")}</div>
            </div>
          </footer>
        </section>
      </main>
      {artifactPreview ? (
        <ArtifactPreviewModal
          artifact={artifactPreview}
          closeLabel={t("close")}
          onClose={() => setArtifactPreview(null)}
        />
      ) : null}
    </div>
  );
}

function ArtifactPreviewInline({ artifact, onOpen }: { artifact: AnyRecord; onOpen: () => void }) {
  const preview = artifact?.preview || {};
  const format = String(preview.format || "");
  const slides = Array.isArray(preview.slides) ? preview.slides : [];
  const sections = Array.isArray(preview.sections) ? preview.sections : [];
  return (
    <button
      type="button"
      onClick={onOpen}
      className="mt-3 block w-full overflow-hidden rounded-xl text-left"
      style={{ background: SURFACE, border: `1px solid ${BORDER}` }}
    >
      <div className="flex items-center justify-between gap-3 px-3 py-2.5" style={{ borderBottom: `1px solid ${BORDER}` }}>
        <div className="min-w-0">
          <div className="truncate text-[12px] font-semibold" style={{ color: TEXT }}>{safeText(preview.title || artifact.title || artifact.filename)}</div>
          <div className="mt-0.5 text-[10px] uppercase tracking-[0.12em]" style={{ color: MUTED }}>{format === "pptx" ? `${slides.length} slides` : `${sections.length} sections`}</div>
        </div>
        <Eye size={15} style={{ color: "#0D2B1E" }} />
      </div>
      {format === "pptx" ? (
        <div className="flex gap-2 overflow-hidden p-3">
          {slides.slice(0, 3).map((slide: AnyRecord, index: number) => (
            <SlidePreview key={index} slide={slide} compact />
          ))}
        </div>
      ) : (
        <div className="p-3">
          <DocumentPreview preview={preview} compact />
        </div>
      )}
    </button>
  );
}

function ArtifactPreviewModal({ artifact, onClose, closeLabel }: { artifact: AnyRecord; onClose: () => void; closeLabel: string }) {
  const preview = artifact?.preview || {};
  const format = String(preview.format || "");
  const slides = Array.isArray(preview.slides) ? preview.slides : [];
  return (
    <div className="fixed inset-0 z-[140] bg-black/55 p-3 sm:p-6" role="dialog" aria-modal="true">
      <div className="mx-auto flex h-full max-w-[1180px] flex-col overflow-hidden rounded-2xl shadow-2xl" style={{ background: "#F5F5F0" }}>
        <div className="flex items-center justify-between gap-4 px-4 py-3 sm:px-5" style={{ background: "#0D2B1E" }}>
          <div className="min-w-0">
            <div className="truncate text-[13px] font-semibold text-white">{safeText(preview.title || artifact.title || artifact.filename)}</div>
            {preview.subtitle ? <div className="mt-1 truncate text-[11px] text-white/60">{safeText(preview.subtitle)}</div> : null}
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-white/80 hover:bg-white/10" aria-label={closeLabel}><X size={18} /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 sm:p-6">
          {format === "pptx" ? (
            <div className="mx-auto grid max-w-[1040px] gap-5">
              {slides.map((slide: AnyRecord, index: number) => (
                <div key={index}>
                  <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em]" style={{ color: MUTED }}>{String(index + 1).padStart(2, "0")}</div>
                  <SlidePreview slide={slide} />
                </div>
              ))}
            </div>
          ) : (
            <div className="mx-auto max-w-[820px]">
              <DocumentPreview preview={preview} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SlidePreview({ slide, compact = false }: { slide: AnyRecord; compact?: boolean }) {
  const layout = String(slide?.layout || "thesis");
  const dark = ["title", "actions", "closing"].includes(layout);
  const bullets = Array.isArray(slide?.bullets) ? slide.bullets : [];
  const left = Array.isArray(slide?.left_points) ? slide.left_points : [];
  const right = Array.isArray(slide?.right_points) ? slide.right_points : [];
  const metrics = Array.isArray(slide?.metrics) ? slide.metrics : [];
  return (
    <div
      className={compact ? "relative aspect-video w-[190px] flex-none overflow-hidden rounded-lg p-3" : "relative aspect-video w-full overflow-hidden rounded-xl p-6 sm:p-8"}
      style={{ background: dark ? "#0D2B1E" : "#F7F7F2", border: dark ? "1px solid #183C2C" : `1px solid ${BORDER}`, color: dark ? "white" : TEXT }}
    >
      <div className={compact ? "text-[5px] font-semibold uppercase tracking-[0.14em]" : "text-[9px] font-semibold uppercase tracking-[0.16em]"} style={{ color: dark ? "#C2E84F" : "#2F6A4B" }}>{safeText(slide?.eyebrow)}</div>
      <div className={compact ? "mt-1 line-clamp-2 text-[9px] font-semibold leading-[1.15]" : "mt-3 max-w-[92%] text-[24px] font-semibold leading-[1.08] sm:text-[30px]"}>{safeText(slide?.title)}</div>
      {slide?.headline ? <div className={compact ? "mt-1 line-clamp-2 text-[7px] font-semibold opacity-90" : "mt-5 max-w-[78%] text-[18px] font-semibold leading-tight sm:text-[24px]"}>{safeText(slide.headline)}</div> : null}
      {!compact && layout === "two_column" ? (
        <div className="mt-6 grid grid-cols-2 gap-4">
          <PreviewColumn title={slide?.left_title} points={left} dark={dark} />
          <PreviewColumn title={slide?.right_title} points={right} dark={dark} />
        </div>
      ) : null}
      {!compact && layout === "metrics" && metrics.length ? (
        <div className="mt-6 grid gap-3" style={{ gridTemplateColumns: `repeat(${Math.min(metrics.length, 4)}, minmax(0, 1fr))` }}>
          {metrics.slice(0, 4).map((metric: AnyRecord, index: number) => (
            <div key={index} className="rounded-xl p-4" style={{ background: "white", border: `1px solid ${BORDER}` }}>
              <div className="text-[24px] font-semibold" style={{ color: "#0D2B1E" }}>{safeText(metric.value)}</div>
              <div className="mt-2 text-[11px] font-semibold" style={{ color: TEXT }}>{safeText(metric.label)}</div>
              <div className="mt-2 text-[10px] leading-4" style={{ color: MUTED }}>{safeText(metric.context)}</div>
            </div>
          ))}
        </div>
      ) : null}
      {!compact && !["two_column", "metrics"].includes(layout) && bullets.length ? (
        <div className="mt-5 grid gap-2">
          {bullets.slice(0, 5).map((bullet: string, index: number) => (
            <div key={index} className="flex gap-3 text-[12px] leading-5 sm:text-[13px]">
              <span className="mt-2 h-1.5 w-1.5 flex-none rounded-full" style={{ background: "#C2E84F" }} />
              <span className="line-clamp-2">{safeText(bullet)}</span>
            </div>
          ))}
        </div>
      ) : null}
      {slide?.callout && !compact ? <div className="absolute bottom-6 right-7 max-w-[38%] text-right text-[11px] font-semibold" style={{ color: dark ? "#C2E84F" : "#2F6A4B" }}>{safeText(slide.callout)}</div> : null}
      <div className="absolute bottom-2 left-3 h-[2px] w-7 rounded-full" style={{ background: "#C2E84F" }} />
    </div>
  );
}

function PreviewColumn({ title, points, dark }: { title: unknown; points: unknown[]; dark: boolean }) {
  return (
    <div className="rounded-xl p-4" style={{ background: dark ? "rgba(255,255,255,0.08)" : "white", border: dark ? "1px solid rgba(255,255,255,0.12)" : `1px solid ${BORDER}` }}>
      <div className="text-[12px] font-semibold">{safeText(title)}</div>
      <div className="mt-3 space-y-2">
        {points.slice(0, 4).map((point, index) => <div key={index} className="text-[11px] leading-4 opacity-80">{safeText(point)}</div>)}
      </div>
    </div>
  );
}

function DocumentPreview({ preview, compact = false }: { preview: AnyRecord; compact?: boolean }) {
  const sections = Array.isArray(preview?.sections) ? preview.sections : [];
  return (
    <div className={compact ? "rounded-lg bg-white p-3" : "rounded-xl bg-white p-6 shadow-sm sm:p-10"} style={{ border: `1px solid ${BORDER}` }}>
      <div className={compact ? "text-[10px] font-semibold" : "text-[28px] font-semibold"} style={{ color: "#0D2B1E" }}>{safeText(preview?.title)}</div>
      {preview?.executive_summary ? <div className={compact ? "mt-2 line-clamp-3 text-[8px] leading-3" : "mt-5 text-[14px] font-medium leading-6"} style={{ color: compact ? MUTED : TEXT }}>{safeText(preview.executive_summary)}</div> : null}
      {!compact ? sections.map((section: AnyRecord, index: number) => (
        <section key={index} className="mt-8">
          <h3 className="text-[16px] font-semibold" style={{ color: "#0D2B1E" }}>{safeText(section.heading)}</h3>
          {section.summary ? <p className="mt-2 text-[13px] font-medium leading-6" style={{ color: TEXT }}>{safeText(section.summary)}</p> : null}
          {(section.paragraphs || []).slice(0, 5).map((paragraph: string, pIndex: number) => <p key={pIndex} className="mt-3 text-[12px] leading-6" style={{ color: MUTED }}>{safeText(paragraph)}</p>)}
          {(section.bullets || []).slice(0, 6).map((bullet: string, bIndex: number) => <div key={bIndex} className="mt-2 flex gap-2 text-[12px] leading-5" style={{ color: TEXT }}><span>•</span><span>{safeText(bullet)}</span></div>)}
        </section>
      )) : null}
    </div>
  );
}

function ConversationSidebar({
  t,
  filteredConversations,
  activeConversationId,
  conversationSearch,
  setConversationSearch,
  historyStatus,
  loadConversation,
  deleteConversation,
  newChat,
  close,
}: {
  t: (key: string) => string;
  filteredConversations: AnyRecord[];
  activeConversationId?: string;
  conversationSearch: string;
  setConversationSearch: (value: string) => void;
  historyStatus: string;
  loadConversation: (id: string) => void;
  deleteConversation: (id: string) => void;
  newChat: () => void;
  close: () => void;
}) {
  return (
    <>
      <div className="flex items-center justify-between gap-3">
        <div className="text-[12px] font-semibold" style={{ color: TEXT }}>{t("askAgroAi")}</div>
        <button type="button" onClick={close} className="rounded-lg p-2" style={{ border: `1px solid ${BORDER}`, color: MUTED }} title={t("intelligence.closeSidebar")}><X size={15} /></button>
      </div>
      <button type="button" onClick={newChat} className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-[12px] font-medium" style={{ background: "#0D2B1E", color: "white" }}><Plus size={14} /> {t("intelligence.newChat")}</button>
      <label className="mt-4 flex items-center gap-2 rounded-lg px-3 py-2.5" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>
        <Search size={14} />
        <input value={conversationSearch} onChange={(event) => setConversationSearch(event.target.value)} placeholder={t("intelligence.search")} className="w-full min-w-0 bg-transparent text-[16px] outline-none sm:text-[12px]" style={{ color: TEXT }} />
      </label>
      <div className="mt-5 text-[11px] font-semibold uppercase" style={{ color: MUTED }}>{t("intelligence.history")}</div>
      <div className="mt-3 flex-1 space-y-2 overflow-y-auto pr-1" style={{ WebkitOverflowScrolling: "touch" }}>
        {filteredConversations.map((row) => {
          const active = row.id === activeConversationId;
          return (
            <div key={row.id} className="group flex gap-2">
              <button type="button" onClick={() => loadConversation(row.id)} className="min-w-0 flex-1 rounded-xl px-3 py-3 text-left" style={{ background: active ? "#EEF8E8" : BG, border: `1px solid ${active ? "rgba(13,43,30,0.32)" : BORDER}` }}>
                <div className="flex items-center gap-2"><MessageSquare size={13} style={{ color: active ? "#0D2B1E" : MUTED }} /><div className="truncate text-[12px] font-semibold" style={{ color: TEXT }}>{row.title || t("intelligence.newChat")}</div></div>
                {row.preview ? <div className="mt-1 line-clamp-2 text-[11px] leading-4" style={{ color: MUTED }}>{row.preview}</div> : null}
              </button>
              <button type="button" onClick={() => deleteConversation(row.id)} className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg lg:hidden lg:group-hover:flex" style={{ border: `1px solid ${BORDER}`, color: MUTED }} title={t("intelligence.deleteChat")}><Trash2 size={14} /></button>
            </div>
          );
        })}
        {!filteredConversations.length ? <div className="rounded-lg p-3 text-[12px] leading-relaxed" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>{historyStatus === "loading" ? t("intelligence.loadingChats") : t("intelligence.noChats")}</div> : null}
      </div>
      <div className="mt-4"><LanguageSelector compact /></div>
    </>
  );
}
