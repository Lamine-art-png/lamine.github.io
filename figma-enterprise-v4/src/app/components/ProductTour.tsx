import { useCallback, useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import { useLocation, useNavigate } from "react-router";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalCopy } from "../hooks/usePortalCopy";

const TOUR_VERSION = "product_tour_v2";
const TOUR_EVENT = "agroai:replay-product-tour";

type AnyRecord = Record<string, any>;
type TourStep = {
  eyebrow: string;
  title: string;
  description: string;
  route?: string;
  selector?: string;
  targetText?: string;
  closest?: string;
};

type Rect = { top: number; left: number; width: number; height: number };

type Placement = { top: string; left: string; transform?: string };

const TOUR_ACTIONS = {
  skip: "Skip tour",
  back: "Back",
  next: "Next",
  saving: "Saving...",
  start: "Start operating",
};

const STEPS: TourStep[] = [
  {
    eyebrow: "Welcome to AGRO-AI",
    title: "A quick tour of your operating workspace",
    description: "This tour opens the real sections of the portal and explains what each one is for. It stays high level so you can start working quickly.",
  },
  {
    eyebrow: "Operate",
    title: "Command Center",
    description: "Start here for the workspace priority, operating status, fields needing attention, open tasks, evidence gaps, reports, and follow-through.",
    route: "/",
    selector: "h1",
  },
  {
    eyebrow: "Operate",
    title: "Field Queue",
    description: "Review fields that need attention, why they were flagged, the latest signal, missing evidence, and the recommended next operator action.",
    route: "/field-queue",
    targetText: "Field Queue",
    closest: "section",
  },
  {
    eyebrow: "Operate",
    title: "Tasks",
    description: "Track operator work from open to in progress to done. Tasks keep recommendations and evidence gaps from disappearing after review.",
    route: "/tasks",
    targetText: "Operator Tasks",
    closest: "section",
  },
  {
    eyebrow: "Decide",
    title: "Decisions",
    description: "Turn available workspace evidence into operator-ready priorities, water-risk review, compliance preparation, and manager briefs before action is taken.",
    route: "/operations",
    selector: "h1",
  },
  {
    eyebrow: "Trust the answer",
    title: "Evidence and uploaded files",
    description: "See the original source files you uploaded and the evidence records derived from them. File status and provenance stay visible instead of becoming a black box.",
    route: "/evidence",
    selector: "[data-tour='evidence-source-library']",
  },
  {
    eyebrow: "Connect your systems",
    title: "Connectors",
    description: "Bring in approved controllers, files, accounts, cloud drives, data providers, and enterprise systems. Availability depends on the connector and your plan.",
    route: "/integrations",
    selector: "h1",
  },
  {
    eyebrow: "Intelligence",
    title: "Ask AGRO-AI",
    description: "Ask questions, investigate risk, work through imported files and workspace evidence, prepare reports, and turn findings into the next operating step.",
    route: "/intelligence",
    selector: "h1",
  },
  {
    eyebrow: "Know what is missing",
    title: "Readiness",
    description: "See which source types are present, which are missing, and what gaps limit stronger decisions, reporting, or operational confidence.",
    route: "/readiness",
    selector: "h1",
  },
  {
    eyebrow: "Prioritize risk",
    title: "Exceptions",
    description: "Review the issues, missing evidence, stale sources, and other conditions that need attention instead of scanning every record manually.",
    route: "/exceptions",
    selector: "h1",
  },
  {
    eyebrow: "Workspace data",
    title: "Sources",
    description: "This is your organized source library. See filenames, providers, processing state, linked evidence, and whether a source is ready for AGRO-AI intelligence.",
    route: "/sources",
    selector: "[data-tour='source-library-table']",
  },
  {
    eyebrow: "You are ready",
    title: "Start operating",
    description: "Use Command Center for daily operations, Connectors and Sources for data, Evidence for provenance, and Ask AGRO-AI when you need investigation or synthesis.",
  },
];

const TOUR_COPY_VALUES = Array.from(new Set([
  ...Object.values(TOUR_ACTIONS),
  ...STEPS.flatMap((step) => [step.eyebrow, step.title, step.description]),
]));

function localKey(userId?: string) {
  return `agroai_product_tour_${TOUR_VERSION}_${userId || "user"}`;
}

function completedStepsFrom(response: unknown): string[] {
  const payload = response && typeof response === "object" ? response as AnyRecord : {};
  const onboarding = payload.onboarding && typeof payload.onboarding === "object" ? payload.onboarding as AnyRecord : {};
  return Array.isArray(onboarding.completed_steps) ? onboarding.completed_steps.map(String) : [];
}

function visible(element: Element): element is HTMLElement {
  if (!(element instanceof HTMLElement)) return false;
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function byText(text: string, closest?: string): HTMLElement | null {
  const normalized = text.trim().toLowerCase();
  const candidates = Array.from(document.querySelectorAll("h1,h2,h3,h4,[role='heading']"));
  const heading = candidates.find((element) => visible(element) && (element.textContent || "").trim().toLowerCase() === normalized)
    || candidates.find((element) => visible(element) && (element.textContent || "").trim().toLowerCase().includes(normalized));
  if (!(heading instanceof HTMLElement)) return null;
  if (!closest) return heading;
  const container = heading.closest(closest);
  return container instanceof HTMLElement && visible(container) ? container : heading;
}

function resolveTarget(step: TourStep): HTMLElement | null {
  if (step.selector) {
    const element = document.querySelector(step.selector);
    if (visible(element as Element)) return element as HTMLElement;
  }
  if (step.targetText) return byText(step.targetText, step.closest);
  return null;
}

function rectFor(element: HTMLElement | null): Rect | null {
  if (!element) return null;
  const rect = element.getBoundingClientRect();
  return {
    top: Math.max(8, rect.top - 6),
    left: Math.max(8, rect.left - 6),
    width: Math.min(window.innerWidth - 16, rect.width + 12),
    height: Math.min(window.innerHeight - 16, rect.height + 12),
  };
}

function cardPlacement(rect: Rect | null): Placement {
  if (!rect) return { top: "50%", left: "50%", transform: "translate(-50%, -50%)" };
  const cardWidth = Math.min(400, window.innerWidth - 32);
  const cardHeight = 330;
  const gap = 18;
  const rightSpace = window.innerWidth - (rect.left + rect.width);
  const leftSpace = rect.left;
  if (rightSpace >= cardWidth + gap) {
    return { top: `${Math.min(window.innerHeight - cardHeight - 16, Math.max(16, rect.top))}px`, left: `${rect.left + rect.width + gap}px` };
  }
  if (leftSpace >= cardWidth + gap) {
    return { top: `${Math.min(window.innerHeight - cardHeight - 16, Math.max(16, rect.top))}px`, left: `${Math.max(16, rect.left - cardWidth - gap)}px` };
  }
  const below = rect.top + rect.height + gap;
  if (window.innerHeight - below >= cardHeight) return { top: `${below}px`, left: `${Math.max(16, Math.min(window.innerWidth - cardWidth - 16, rect.left))}px` };
  return { top: `${Math.max(16, rect.top - cardHeight - gap)}px`, left: `${Math.max(16, Math.min(window.innerWidth - cardWidth - 16, rect.left))}px` };
}

export function ProductTour() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { tx } = usePortalCopy(["tour", "shared"], TOUR_COPY_VALUES);
  const [open, setOpen] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const [serverSteps, setServerSteps] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const step = STEPS[stepIndex];
  const storageKey = useMemo(() => localKey(user?.id), [user?.id]);

  const measure = useCallback(() => {
    setRect(rectFor(resolveTarget(STEPS[stepIndex])));
  }, [stepIndex]);

  const openTour = useCallback(() => {
    setRect(null);
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
          setRect(null);
          setStepIndex(0);
          setOpen(true);
        }
      })
      .catch(() => {
        if (!active) return;
        if (window.localStorage.getItem(storageKey) !== "done") {
          setRect(null);
          setStepIndex(0);
          setOpen(true);
        }
      });
    return () => { active = false; };
  }, [storageKey, user?.id]);

  useEffect(() => {
    if (!open) return;
    if (step.route && location.pathname !== step.route) {
      setRect(null);
      navigate(step.route);
      return;
    }

    let cancelled = false;
    let attempt = 0;
    const locate = () => {
      if (cancelled) return;
      const target = resolveTarget(step);
      if (target) {
        target.scrollIntoView({ block: "center", behavior: "instant" as ScrollBehavior });
        window.requestAnimationFrame(() => { if (!cancelled) setRect(rectFor(target)); });
        return;
      }
      attempt += 1;
      if (attempt < 24) window.setTimeout(locate, 125);
      else setRect(null);
    };
    const timer = window.setTimeout(locate, 80);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [location.pathname, navigate, open, step]);

  useEffect(() => {
    if (!open) return;
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
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
    setRect(null);
    setStepIndex((value) => value + 1);
  }

  function back() {
    setRect(null);
    setStepIndex((value) => Math.max(0, value - 1));
  }

  if (!open) return null;

  const placement = cardPlacement(rect);
  return (
    <div className="fixed inset-0 z-[120]" role="dialog" aria-modal="true" aria-label={tx("AGRO-AI product tour")}>
      {!rect ? <div className="absolute inset-0 bg-black/55" /> : (
        <div
          className="absolute rounded-xl border-2 border-white/90 pointer-events-none"
          style={{
            top: rect.top,
            left: rect.left,
            width: rect.width,
            height: rect.height,
            boxShadow: "0 0 0 9999px rgba(0,0,0,0.58), 0 0 0 5px rgba(221,235,143,0.26)",
          }}
        />
      )}

      <section
        className="absolute w-[400px] max-w-[calc(100vw-32px)] rounded-2xl p-6 shadow-2xl"
        style={{ ...placement, background: "#FFFEFA", border: "1px solid rgba(16,35,27,0.14)", color: "#10231B" }}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.16em]" style={{ color: "#567064" }}>{tx(step.eyebrow)}</div>
            <div className="mt-2 text-[12px] font-medium" style={{ color: "#6B7F75" }}>{stepIndex + 1} / {STEPS.length}</div>
          </div>
          <button type="button" onClick={() => void finish()} className="rounded-lg p-1.5 hover:bg-black/5" aria-label={tx("Skip product tour")}><X size={17} /></button>
        </div>

        <h2 className="mt-5 text-[23px] font-semibold tracking-tight">{tx(step.title)}</h2>
        <p className="mt-3 text-[14px] leading-6" style={{ color: "#5D7067" }}>{tx(step.description)}</p>

        <div className="mt-6 flex gap-1.5" aria-hidden="true">
          {STEPS.map((_, index) => <span key={index} className="h-1.5 flex-1 rounded-full" style={{ background: index <= stepIndex ? "#1F7350" : "#E4E8E2" }} />)}
        </div>

        <div className="mt-6 flex items-center justify-between gap-3">
          <button type="button" onClick={() => void finish()} className="text-[12px] font-medium" style={{ color: "#687B71" }}>{tx(TOUR_ACTIONS.skip)}</button>
          <div className="flex gap-2">
            {stepIndex > 0 ? <button type="button" onClick={back} className="h-10 rounded-lg px-4 text-[12px] font-semibold" style={{ border: "1px solid #D9DED8", color: "#31483D" }}>{tx(TOUR_ACTIONS.back)}</button> : null}
            <button type="button" onClick={next} disabled={saving} className="h-10 rounded-lg px-5 text-[12px] font-semibold disabled:opacity-60" style={{ background: "#0D2B1E", color: "white" }}>{stepIndex === STEPS.length - 1 ? (saving ? tx(TOUR_ACTIONS.saving) : tx(TOUR_ACTIONS.start)) : tx(TOUR_ACTIONS.next)}</button>
          </div>
        </div>
      </section>
    </div>
  );
}

export function replayProductTour() {
  window.dispatchEvent(new Event(TOUR_EVENT));
}
