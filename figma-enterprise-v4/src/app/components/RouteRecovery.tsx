import { Link } from "react-router";
import { BG, BORDER, MUTED, SURFACE, TEXT } from "./portalUi";

export function RouteRecovery() {
  return (
    <div className="min-h-screen flex items-center justify-center px-6" style={{ background: BG }}>
      <section className="w-full max-w-[520px] rounded-xl p-6" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
        <div className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>AGRO-AI Portal</div>
        <h1 className="mt-4 text-[26px] font-semibold" style={{ color: TEXT }}>Page not available</h1>
        <p className="mt-3 text-[14px] leading-relaxed" style={{ color: MUTED }}>
          The portal could not find that workspace page. Return to the operating dashboard or pricing.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link className="rounded-lg px-4 py-2 text-[12px] font-medium text-white" style={{ background: "#16533C" }} to="/">
            Open portal
          </Link>
          <Link className="rounded-lg px-4 py-2 text-[12px] font-medium" style={{ border: `1px solid ${BORDER}`, color: TEXT }} to="/pricing">
            View pricing
          </Link>
        </div>
      </section>
    </div>
  );
}
