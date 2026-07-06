import { Download, FileText, Mail, MessageSquare, Plus, RefreshCw, Search, Send, Trash2, UploadCloud, X } from "lucide-react";
import { LanguageSelector } from "../LanguageSelector";
import { BG, BORDER, MUTED, SURFACE, TEXT } from "../portalUi";
import { safeText, AnyRecord } from "./intelligenceSupport";
import type { useIntelligenceController } from "./useIntelligenceController";

type Controller = ReturnType<typeof useIntelligenceController>;

export function IntelligenceView({ controller }: { controller: Controller }) {
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
    send,
    onKeyDown,
    sendDisabled,
  } = controller;

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <main className="grid min-h-screen" style={{ gridTemplateColumns: sidebarOpen ? "300px minmax(0, 1fr)" : "minmax(0, 1fr)" }}>
        {sidebarOpen ? (
          <aside className="flex min-h-screen flex-col border-r p-4" style={{ background: SURFACE, borderColor: BORDER }}>
            <div className="flex items-center justify-between gap-3">
              <div className="text-[12px] font-semibold" style={{ color: TEXT }}>{t("askAgroAi")}</div>
              <button type="button" onClick={() => setSidebarOpen(false)} className="rounded-lg p-2" style={{ border: `1px solid ${BORDER}`, color: MUTED }} title={t("intelligence.closeSidebar")}><X size={15} /></button>
            </div>
            <button type="button" onClick={newChat} className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-[12px] font-medium" style={{ background: "#0D2B1E", color: "white" }}><Plus size={14} /> {t("intelligence.newChat")}</button>
            <label className="mt-4 flex items-center gap-2 rounded-lg px-3 py-2" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>
              <Search size={14} />
              <input value={conversationSearch} onChange={(event) => setConversationSearch(event.target.value)} placeholder={t("intelligence.search")} className="w-full bg-transparent text-[12px] outline-none" style={{ color: TEXT }} />
            </label>
            <div className="mt-5 text-[11px] font-semibold uppercase" style={{ color: MUTED }}>{t("intelligence.history")}</div>
            <div className="mt-3 flex-1 space-y-2 overflow-y-auto pr-1">
              {filteredConversations.map((row) => {
                const active = row.id === activeConversationId;
                return <div key={row.id} className="group flex gap-2">
                  <button type="button" onClick={() => loadConversation(row.id)} className="min-w-0 flex-1 rounded-xl px-3 py-3 text-left" style={{ background: active ? "#EEF8E8" : BG, border: `1px solid ${active ? "rgba(13,43,30,0.32)" : BORDER}` }}>
                    <div className="flex items-center gap-2"><MessageSquare size={13} style={{ color: active ? "#0D2B1E" : MUTED }} /><div className="truncate text-[12px] font-semibold" style={{ color: TEXT }}>{row.title || t("intelligence.newChat")}</div></div>
                    {row.preview ? <div className="mt-1 line-clamp-2 text-[11px] leading-4" style={{ color: MUTED }}>{row.preview}</div> : null}
                  </button>
                  <button type="button" onClick={() => deleteConversation(row.id)} className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-lg group-hover:flex" style={{ border: `1px solid ${BORDER}`, color: MUTED }} title={t("intelligence.deleteChat")}><Trash2 size={14} /></button>
                </div>;
              })}
              {!filteredConversations.length ? <div className="rounded-lg p-3 text-[12px] leading-relaxed" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}>{historyStatus === "loading" ? t("intelligence.loadingChats") : t("intelligence.noChats")}</div> : null}
            </div>
            <div className="mt-4"><LanguageSelector compact /></div>
          </aside>
        ) : null}

        <section className="flex min-w-0 flex-col">
          <header className="px-8 py-6" style={{ background: "#0D2B1E", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="inline-flex rounded-full px-3 py-1 text-[11px] font-semibold" style={{ background: "rgba(255,255,255,0.12)", color: "white" }}>{t("intelligence.workspaceBadge")}</div>
                <h1 className="mt-3 text-[28px] font-semibold tracking-tight" style={{ color: "white" }}>{t("intelligence.title")}</h1>
                <p className="mt-2 max-w-2xl text-[13px] leading-relaxed" style={{ color: "rgba(255,255,255,0.68)" }}>{t("intelligence.subtitle")}</p>
              </div>
              {!sidebarOpen ? <button type="button" onClick={() => setSidebarOpen(true)} className="rounded-lg px-3 py-2 text-[12px] font-medium" style={{ background: "rgba(255,255,255,0.12)", color: "white" }}><span className="inline-flex items-center gap-2"><FileText size={15} /> {t("intelligence.history")}</span></button> : null}
            </div>
          </header>

          <div className="flex-1 overflow-y-auto px-6 py-7">
            <div className="mx-auto max-w-[900px] space-y-5">
              {error ? <div className="flex items-center justify-between gap-3 rounded-xl px-4 py-3 text-[13px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: "#991B1B" }}><span>{error}</span>{failedPrompt ? <button type="button" onClick={() => send(failedPrompt, { retry: true })} disabled={loading} className="inline-flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-semibold" style={{ background: "#0D2B1E", color: "white" }}><RefreshCw size={14} /> {t("retry")}</button> : null}</div> : null}
              {notice ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: "#0D2B1E" }}>{notice}</div> : null}

              {!messages.length && !loading ? <section className="rounded-xl p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
                <div className="text-[12px] font-semibold uppercase" style={{ color: MUTED }}>{t("intelligence.startThread")}</div>
                <h2 className="mt-3 text-[24px] font-semibold" style={{ color: TEXT }}>{t("intelligence.askOrImport")}</h2>
                <p className="mt-2 max-w-2xl text-[14px] leading-relaxed" style={{ color: MUTED }}>{t("intelligence.liveEvidenceBody")}</p>
                <div className="mt-5 flex flex-wrap gap-2">{prompts.map((prompt) => <button key={prompt} type="button" onClick={() => send(prompt)} className="rounded-full px-3 py-2 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>{prompt}</button>)}</div>
              </section> : null}

              {messages.map((message, index) => {
                const actions = Array.isArray(message.agentic_actions) ? message.agentic_actions : [];
                return <div key={message.id || index} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                  <article className={message.role === "user" ? "max-w-[72%]" : "w-full max-w-[820px]"}>
                    <div className="rounded-2xl px-5 py-4 text-[15px] leading-7 whitespace-pre-wrap" style={{ background: message.role === "user" ? "#0D2B1E" : SURFACE, color: message.role === "user" ? "white" : TEXT, border: `1px solid ${message.role === "user" ? "#0D2B1E" : BORDER}` }}>
                      {safeText(message.content)}
                      {message.role === "assistant" && message.artifact ? <div className="mt-4 flex flex-wrap gap-2 whitespace-normal">
                        <button type="button" onClick={() => downloadReportFor(message)} disabled={reportBusyId === String(message.id || index)} className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-semibold disabled:opacity-60" style={{ background: "#0D2B1E", color: "white" }}>{reportBusyId === String(message.id || index) ? <FileText size={15} /> : <Download size={15} />}{reportBusyId === String(message.id || index) ? t("intelligence.preparingPdf") : t("intelligence.downloadPdf")}</button>
                        <button type="button" onClick={() => emailReportFor(message)} disabled={reportEmailBusyId === String(message.id || index)} className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-semibold disabled:opacity-60" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}><Mail size={15} />{reportEmailBusyId === String(message.id || index) ? t("intelligence.emailing") : t("intelligence.emailToMe")}</button>
                      </div> : null}
                      {message.role === "assistant" && actions.length ? <div className="mt-4 space-y-2 whitespace-normal">{actions.map((action: AnyRecord) => {
                        const actionId = String(action.id || `${message.id}-${action.action_type}`);
                        const executed = action.execution_result || ["executed", "approval_recorded"].includes(String(action.status));
                        return <div key={actionId} className="rounded-xl p-3" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                          <div className="flex items-start justify-between gap-3">
                            <div><div className="text-[13px] font-semibold" style={{ color: TEXT }}>{safeText(action.title || action.action_type)}</div><div className="mt-1 text-[12px] leading-relaxed" style={{ color: MUTED }}>{safeText(action.description)}</div><div className="mt-2 text-[11px] font-semibold" style={{ color: action.approval_required ? "#92400E" : "#0D2B1E" }}>{riskLabel(action)}</div></div>
                            <button type="button" onClick={() => runAction(message, action)} disabled={executed || actionBusyId === actionId} className="shrink-0 rounded-lg px-3 py-2 text-[12px] font-semibold disabled:opacity-50" style={{ background: action.approval_required ? "#92400E" : "#0D2B1E", color: "white" }}>{executed ? t("done") : actionBusyId === actionId ? t("working") : action.approval_required ? t("intelligence.createApproval") : t("intelligence.doIt")}</button>
                          </div>
                        </div>;
                      })}</div> : null}
                    </div>
                  </article>
                </div>;
              })}

              {loading ? <div className="rounded-xl px-4 py-3 text-[13px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: MUTED }}>{t("intelligence.preparingAnswer")}</div> : null}
            </div>
          </div>

          <footer className="px-6 pb-6">
            <div className="mx-auto max-w-[900px] rounded-2xl p-4 shadow-[0_18px_60px_rgba(16,35,27,0.08)]" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
              {fileImports.length ? <div className="mb-3 flex flex-wrap gap-2">{fileImports.map((item) => <div key={item.id} className="flex items-center gap-2 rounded-full px-3 py-2 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}><span className="max-w-[180px] truncate font-medium">{item.filename}</span><span style={{ color: item.status === "failed" ? "#991B1B" : MUTED }}>{item.status === "queued" ? t("intelligence.fileQueued") : item.status === "uploading" ? t("intelligence.fileUploading") : item.status === "imported" ? t("intelligence.fileImported") : t("intelligence.fileFailed")}</span><button type="button" onClick={() => setFileImports((current) => current.filter((row) => row.id !== item.id))} title={t("remove")}><X size={13} /></button></div>)}</div> : null}
              {hasFailed ? <div className="mb-3 text-[12px]" style={{ color: "#991B1B" }}>{t("intelligence.fileFailedBeforeSend")}</div> : null}
              <div className="flex gap-3">
                <button type="button" onClick={() => fileInputRef.current?.click()} className="inline-flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-medium" style={{ border: `1px solid ${BORDER}`, color: TEXT }}><UploadCloud size={15} /> {t("intelligence.importFiles")}</button>
                <input ref={fileInputRef} type="file" multiple className="hidden" accept=".csv,.xlsx,.xls,.pdf,.txt,.md,.json,.geojson,.kml,.zip" onChange={(event) => onFilesSelected(event.target.files)} />
                <textarea value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={onKeyDown} rows={2} placeholder={t("intelligence.placeholder")} className="min-h-[48px] flex-1 resize-none rounded-lg px-4 py-3 text-[14px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />
                <button type="button" disabled={sendDisabled} onClick={() => send()} className="inline-flex h-[48px] w-[52px] shrink-0 items-center justify-center rounded-lg disabled:opacity-50" style={{ background: "#0D2B1E", color: "white" }} title={t("send")}><Send size={18} /></button>
              </div>
              <div className="mt-3 text-[11px]" style={{ color: MUTED }}>{t("intelligence.enterHint")}</div>
            </div>
          </footer>
        </section>
      </main>
    </div>
  );
}
