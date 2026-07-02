import { Link } from "react-router";
import { BG, BORDER, MUTED, SURFACE, TEXT } from "./portalUi";

export function RouteRecovery() {
  return (
    <div className="min-h-screen flex items-center justify-center px-6" style={{ background: BG }}>
      <section className="w-full max-w-[620px] rounded-xl p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
        <div className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>AGRO-AI Portal</div>
        <h1 className="mt-4 text-[26px] font-semibold" style={{ color: TEXT }}>Workspace module recovered safely</h1>
        <p className="mt-3 text-[14px] leading-relaxed" style={{ color: MUTED }}>
          This screen is a safe recovery boundary. It keeps the portal usable if a module is still loading, blocked by plan access, or temporarily unreachable.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link className="rounded-lg px-4 py-2 text-[12px] font-medium text-white" style={{ background: "#16533C" }} to="/">Open portal</Link>
          <Link className="rounded-lg px-4 py-2 text-[12px] font-medium" style={{ border: `1px solid ${BORDER}`, color: TEXT }} to="/intelligence">Ask AGRO-AI</Link>
          <Link className="rounded-lg px-4 py-2 text-[12px] font-medium" style={{ border: `1px solid ${BORDER}`, color: TEXT }} to="/settings">Settings</Link>
          <Link className="rounded-lg px-4 py-2 text-[12px] font-medium" style={{ border: `1px solid ${BORDER}`, color: TEXT }} to="/pricing">Pricing</Link>
        </div>
      </section>
    </div>
  );
}
