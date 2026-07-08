import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, LoaderCircle, ShieldCheck, X } from "lucide-react";

type UploadState = {
  phase: "uploading" | "stored" | "complete" | "failed";
  filename?: string;
  message?: string;
  job_id?: string;
};

const EVENT = "agroai:upload-state";
const COPY = {
  failed: { label: "Upload failed" },
  complete: { label: "File ready" },
  stored: { label: "Securely stored" },
  uploading: { label: "Uploading file" },
  working: { label: "Working..." },
};

export function UploadStatusToast() {
  const [state, setState] = useState<UploadState | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    const onState = (event: Event) => {
      const detail = (event as CustomEvent<UploadState>).detail;
      if (!detail?.phase) return;
      setState(detail);
      if (timer.current) window.clearTimeout(timer.current);
      if (detail.phase === "complete" || detail.phase === "failed") {
        timer.current = window.setTimeout(() => setState(null), detail.phase === "failed" ? 10_000 : 6_000);
      }
    };
    window.addEventListener(EVENT, onState);
    return () => {
      window.removeEventListener(EVENT, onState);
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, []);

  if (!state) return null;

  const failed = state.phase === "failed";
  const complete = state.phase === "complete";
  const stored = state.phase === "stored";
  const Icon = failed ? AlertCircle : complete ? CheckCircle2 : stored ? ShieldCheck : LoaderCircle;
  const title = failed ? COPY.failed.label : complete ? COPY.complete.label : stored ? COPY.stored.label : COPY.uploading.label;

  return (
    <div className="fixed right-6 top-6 z-[150] w-[390px] max-w-[calc(100vw-32px)] rounded-2xl p-4 shadow-2xl" style={{ background: "#FFFEFA", border: `1px solid ${failed ? "rgba(153,27,27,0.28)" : "rgba(16,35,27,0.18)"}` }} role="status" aria-live="polite">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl" style={{ background: failed ? "#FEF2F2" : complete ? "#ECFDF3" : "#EEF8E8", color: failed ? "#991B1B" : "#0D5B3D" }}>
          <Icon size={18} className={state.phase === "uploading" ? "animate-spin" : ""} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold" style={{ color: "#10231B" }}>{title}</div>
          <div className="mt-1 text-[12px] leading-5" style={{ color: failed ? "#991B1B" : "#607168" }}>{state.message || state.filename || COPY.working.label}</div>
          {state.job_id && !failed ? <div className="mt-2 text-[10px] font-medium uppercase tracking-wider" style={{ color: "#839087" }}>Processing receipt active</div> : null}
        </div>
        <button type="button" onClick={() => setState(null)} className="rounded-lg p-1" style={{ color: "#718078" }} aria-label="Dismiss upload status"><X size={15} /></button>
      </div>
    </div>
  );
}
