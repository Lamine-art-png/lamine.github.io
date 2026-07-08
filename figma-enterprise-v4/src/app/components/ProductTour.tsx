import { useCallback, useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";

const TOUR_VERSION = "product_tour_v1";
const TOUR_EVENT = "agroai:replay-product-tour";

type AnyRecord = Record<string, any>;
type TourStep = {
  eyebrow: string;
  title: string;
  description: string;
  target?: string;
};

type Rect = { top: number; left: number; width: number; height: number };

const STEPS: TourStep[] = [
  {
    eyebrow: "Welcome to AGRO-AI",
    title: "Your agricultural operating system",
    description: "AGRO-AI brings operations, field evidence, connected systems, decisions, reports, and intelligence into one workspace. Here is the 60-second tour.",
  },
  {
    eyebrow: "Operate",
    title: "Start with Command Center",
    description: "See what needs attention, move from signal to action, and keep the team focused on the highest-priority work.",
    target: "command-center",
  },
  {
    eyebrow: "Connect your reality",
    title: "Bring your systems and files in",
    description: "Connect controllers, email, cloud drives, weather, ET data, enterprise systems, or upload source files. AGRO-AI turns approved inputs into operational context.",
    target: "connectors",
  },
  {
    eyebrow: "Trust the answer",
    title: "Evidence keeps work traceable",
    description: "Use Evidence to see the records behind decisions and reports. Sources, timestamps, provenance, and gaps stay visible instead of disappearing inside a black box.",
    target: "evidence",
  },
  {
    eyebrow: "Intelligence",
    title: "Ask AGRO-AI to investigate and act",
    description: "Ask questions, import files, diagnose risk, review missing evidence, prepare reports, and turn findings into the next operating action.",
    target: "ask-agro-ai",
  },
];

function localKey(userId?: string) {
  return `agroai_product_tour_${TOUR_VERSION}_${userId || "user"}`;
}

function completedStepsFrom(response: unknown): string[] {
  const payload = response && typeof response === "object" ? response as AnyRecord : {};
  const onboarding = payload.onboarding && typeof payload.onboarding === "object" ? payload.onboarding as AnyRecord : {};
  return Array.isArray(onboarding.completed_steps) ? onboarding.completed_steps.map(String) : [];
}

function targetRect(target?: string): Rect | null {
  if (!target) return null;
  const element = document.querySelector(`[data-tour="${target}"]`);
  if (!(element instanceof HTMLElement)) return null;
  const rect = element.getBoundingClientRect();
  return {
    top: Math.max(8, rect.top - 6),
    left: Math.max(8, rect.left - 6),
    width: rect.width + 12,
    height: rect.height + 12,
  };
}

export function ProductTour() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const [serverSteps, setServerSteps] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const step = STEPS[stepIndex];
  const storageKey = useMemo(() => localKey(user?.id), [user?.id]);

  const measure = useCallback(() => {
    setRect(targetRect(STEPS[stepIndex]?.target));
  }, [stepIndex]);

  const openTour = useCallback(() => {
    setStepIndex(0);
    setOpen(true);
  }, []);

  useEffect(() => {
    const replay = () => openTour();
    window.addEventListener(TOUR_EVENT, replay);
    return () => window.removeEventListener(TOUR_EVENT, replay);
  }, [openTour]);

  useEffect(() => {
    if (!user?.id) return;
    let active = true;
    apiClient.onboarding.state()
      .then((response) => {
        if (!active) return;
        const completed = completedStepsFrom(response);
        setServerSteps(completed);
        const locallyCompleted = window.localStorage.getItem(storageKey) === "done";
        if (!completed.includes(TOUR_VERSION) && !locallyCompleted) {
          setStepIndex(0);
          setOpen(true);
        }
      })
      .catch(() => {
        if (!active) return;
        if (window.localStorage.getItem(storageKey) !== "done") {
          setStepIndex(0);
          setOpen(true);
        }
      });
    return () => { active = false; };
  }, [storageKey, user?.id]);

  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(measure);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [measure, open]);

  async function finish() {
    if (saving) return;
    setSaving(true);
    const completed = Array.from(new Set([...serverSteps, TOUR_VERSION]));
    window.localStorage.setItem(storageKey, "done");
    setOpen(false);
    try {
      const response = await apiClient.onboarding.update({
        current_step: "product_tour_complete",
        completed_steps: completed,
      }) as AnyRecord;
      setServerSteps(completedStepsFrom(response));
    } catch {
      // Local suppression prevents a broken onboarding endpoint from trapping the
      // customer in a repeated tour on this device.
    } finally {
      setSaving(false);
    }
  }

  function next() {
    if (stepIndex >= STEPS.length - 1) {
      void finish();
      return;
    }
    setStepIndex((value) => value + 1);
  }

  function back() {
    setStepIndex((value) => Math.max(0, value - 1));
  }

  if (!open) return null;

  const intro = !step.target || !rect;
  const cardTop = intro ? "50%" : `${Math.min(window.innerHeight - 310, Math.max(24, rect!.top - 8))}px`;
  const cardLeft = intro ? "50%" : `${Math.min(window.innerWidth - 420, Math.max(304, rect!.left + rect!.width + 24))}px`;

  return (
    <div className="fixed inset-0 z-[120]" role="dialog" aria-modal="true" aria-label="AGRO-AI product tour">
      {intro ? <div className="absolute inset-0 bg-black/55" /> : (
        <div
          className="absolute rounded-xl border-2 border-white/90 pointer-events-none"
          style={{
            top: rect!.top,
            left: rect!.left,
            width: rect!.width,
            height: rect!.height,
            boxShadow: "0 0 0 9999px rgba(0,0,0,0.58), 0 0 0 5px rgba(221,235,143,0.26)",
          }}
        />
      )}

      <section
        className="absolute w-[390px] max-w-[calc(100vw-32px)] rounded-2xl p-6 shadow-2xl"
        style={{
          top: cardTop,
          left: cardLeft,
          transform: intro ? "translate(-50%, -50%)" : undefined,
          background: "#FFFEFA",
          border: "1px solid rgba(16,35,27,0.14)",
          color: "#10231B",
        }}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.16em]" style={{ color: "#567064" }}>{step.eyebrow}</div>
            <div className="mt-2 text-[12px] font-medium" style={{ color: "#6B7F75" }}>{stepIndex + 1} / {STEPS.length}</div>
          </div>
          <button type="button" onClick={() => void finish()} className="rounded-lg p-1.5 hover:bg-black/5" aria-label="Skip product tour"><X size={17} /></button>
        </div>

        <h2 className="mt-5 text-[23px] font-semibold tracking-tight">{step.title}</h2>
        <p className="mt-3 text-[14px] leading-6" style={{ color: "#5D7067" }}>{step.description}</p>

        <div className="mt-6 flex gap-1.5" aria-hidden="true">
          {STEPS.map((_, index) => <span key={index} className="h-1.5 flex-1 rounded-full" style={{ background: index <= stepIndex ? "#1F7350" : "#E4E8E2" }} />)}
        </div>

        <div className="mt-6 flex items-center justify-between gap-3">
          <button type="button" onClick={() => void finish()} className="text-[12px] font-medium" style={{ color: "#687B71" }}>Skip tour</button>
          <div className="flex gap-2">
            {stepIndex > 0 ? <button type="button" onClick={back} className="h-10 rounded-lg px-4 text-[12px] font-semibold" style={{ border: "1px solid #D9DED8", color: "#31483D" }}>Back</button> : null}
            <button type="button" onClick={next} disabled={saving} className="h-10 rounded-lg px-5 text-[12px] font-semibold disabled:opacity-60" style={{ background: "#0D2B1E", color: "white" }}>{stepIndex === STEPS.length - 1 ? (saving ? "Saving..." : "Start operating") : "Next"}</button>
          </div>
        </div>
      </section>
    </div>
  );
}

export function replayProductTour() {
  window.dispatchEvent(new Event(TOUR_EVENT));
}
