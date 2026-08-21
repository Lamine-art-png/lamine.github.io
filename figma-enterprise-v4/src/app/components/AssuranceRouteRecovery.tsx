import { useRouteError } from "react-router";
import { usePortalCopy } from "../hooks/usePortalCopy";

export function AssuranceRouteRecovery() {
  const error = useRouteError();
  const { tx } = usePortalCopy(["assurance", "shared"]);
  const detail = error instanceof Error ? error.message : tx("The Assurance workspace could not be loaded.");
  return (
    <div className="min-h-full bg-[#F6F4EE] px-4 py-10 sm:px-8" data-assurance-route-recovery>
      <section className="mx-auto max-w-[760px] rounded-2xl border border-[#D6DDD0] bg-[#FFFDF8] p-7 shadow-[0_18px_60px_rgba(16,35,27,0.08)]">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#2D6A4F]">{tx("Assurance route recovery")}</div>
        <h1 className="mt-3 text-[26px] font-semibold text-[#10231B]">{tx("Assurance is temporarily unavailable")}</h1>
        <p className="mt-3 text-[13px] leading-6 text-[#65736A]">{detail}</p>
        <p className="mt-2 text-[12px] leading-6 text-[#65736A]">{tx("The portal shell and every other operating route remain available.")}</p>
        <div className="mt-6 flex flex-wrap gap-3">
          <a href="/" className="rounded-lg bg-[#10231B] px-4 py-2 text-[12px] font-semibold text-white">{tx("Open command center")}</a>
          <a href="/evidence" className="rounded-lg border border-[#D6DDD0] px-4 py-2 text-[12px] font-semibold text-[#10231B]">{tx("Open evidence")}</a>
          <button type="button" onClick={() => window.location.reload()} className="rounded-lg border border-[#D6DDD0] px-4 py-2 text-[12px] font-semibold text-[#10231B]">{tx("Retry Assurance")}</button>
        </div>
      </section>
    </div>
  );
}
