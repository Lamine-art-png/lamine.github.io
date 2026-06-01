import type { BackendStatus } from "../api/contracts";

type Tone = "ok" | "warn" | "danger" | "neutral" | "gold";

export function StatusBadge({ label, tone = "neutral", title }: { label: string; tone?: Tone; title?: string }) {
  return (
    <span className={`status-badge tone-${tone}`} title={title}>
      <span className="status-dot" aria-hidden="true" />
      {label}
    </span>
  );
}

const BACKEND_TONE: Record<BackendStatus, Tone> = {
  available: "ok",
  limited: "warn",
  unavailable: "danger",
};

const BACKEND_LABEL: Record<BackendStatus, string> = {
  available: "Backend available",
  limited: "Backend limited",
  unavailable: "Backend unavailable",
};

export function BackendBadge({ status, detail }: { status: BackendStatus; detail: string }) {
  return <StatusBadge label={BACKEND_LABEL[status]} tone={BACKEND_TONE[status]} title={detail} />;
}
