export const BG = "#F6F4EE";
export const SURFACE = "#FFFEFA";
export const BORDER = "rgba(16,35,27,0.12)";
export const TEXT = "#10231B";
export const MUTED = "#68776F";
export const GREEN = "#16533C";
export const GREEN_HOVER = "#1F7350";

export function InlineState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="rounded-lg px-4 py-3 text-[13px]" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="font-semibold" style={{ color: TEXT }}>{title}</div>
      {detail ? <div className="mt-1 leading-relaxed" style={{ color: MUTED }}>{detail}</div> : null}
    </div>
  );
}
export function StatusBadge({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "good" | "warn" | "locked" }) {
  const styles = {
    neutral: { background: BG, color: MUTED, border: `1px solid ${BORDER}` },
    good: { background: "#F0FDF4", color: "#15803D", border: "1px solid #BBF7D0" },
    warn: { background: "#FFFBEB", color: "#92400E", border: "1px solid #FCD34D" },
    locked: { background: "#F0F7EE", color: "#1F5A43", border: "1px solid #CFE1CB" },
  };
  return (
    <span className="inline-flex items-center px-2.5 py-1 rounded text-[11px] font-medium" style={styles[tone]}>
      {label}
    </span>
  );
}

export function PortalButton({
  children,
  disabled,
  onClick,
  variant = "primary",
}: {
  children: ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  variant?: "primary" | "secondary";
}) {
  const isPrimary = variant === "primary";
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="px-4 py-2 text-[12px] font-medium rounded-lg transition-colors disabled:cursor-not-allowed disabled:opacity-60"
      style={
        disabled
          ? { background: "#E7E2D7", color: MUTED }
          : isPrimary
            ? { background: GREEN, color: "white" }
            : { border: `1px solid ${BORDER}`, color: TEXT, background: "transparent" }
      }
      onMouseEnter={(event) => {
        if (disabled) return;
        event.currentTarget.style.background = isPrimary ? GREEN_HOVER : BG;
      }}
      onMouseLeave={(event) => {
        if (disabled) return;
        event.currentTarget.style.background = isPrimary ? GREEN : "transparent";
      }}
    >
      {children}
    </button>
  );
}
import { ReactNode } from "react";
