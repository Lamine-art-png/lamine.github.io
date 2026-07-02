import { Link, useLocation } from "react-router";
import { CreditCard, Home, LifeBuoy, Settings } from "lucide-react";
import { BG, BORDER, MUTED, SURFACE, TEXT } from "./portalUi";

export function RouteRecovery() {
  const location = useLocation();
  const path = location.pathname;
  return (
    <div className="min-h-screen flex items-center justify-center px-6" style={{ background: BG }}>
      <section className="w-full max-w-[760px] rounded-2xl p-7" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
        <div className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>AGRO-AI portal</div>
        <h1 className="mt-4 text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>This workspace module is not available yet.</h1>
        <p className="mt-3 text-[14px] leading-7" style={{ color: MUTED }}>The portal is still usable. Continue to the operating room, pricing, settings, or support.</p>
        <div className="mt-5 rounded-xl p-4 text-[12px]" style={{ background: BG, border: `1px solid ${BORDER}`, color: MUTED }}><span className="font-semibold" style={{ color: TEXT }}>Requested path:</span> {path}</div>
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Link className="rounded-xl p-4 text-[13px] font-semibold" style={{ background: "#0D2B1E", color: "white" }} to="/"><Home className="mb-3 h-5 w-5" />Operating room</Link>
          <Link className="rounded-xl p-4 text-[13px] font-semibold" style={{ border: `1px solid ${BORDER}`, color: TEXT }} to="/pricing"><CreditCard className="mb-3 h-5 w-5" />Pricing</Link>
          <Link className="rounded-xl p-4 text-[13px] font-semibold" style={{ border: `1px solid ${BORDER}`, color: TEXT }} to="/settings"><Settings className="mb-3 h-5 w-5" />Settings</Link>
          <Link className="rounded-xl p-4 text-[13px] font-semibold" style={{ border: `1px solid ${BORDER}`, color: TEXT }} to="/support"><LifeBuoy className="mb-3 h-5 w-5" />Support</Link>
        </div>
      </section>
    </div>
  );
}
