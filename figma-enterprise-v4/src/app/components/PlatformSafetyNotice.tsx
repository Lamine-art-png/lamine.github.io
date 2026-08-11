import { LockKeyhole, ShieldCheck } from "lucide-react";

export function PlatformSafetyNotice() {
  return (
    <aside
      className="pointer-events-none fixed bottom-4 right-4 z-[90] hidden max-w-[390px] rounded-2xl border border-[#BFD0B9]/80 bg-[#F9FCF6]/95 p-3 shadow-[0_18px_55px_rgba(7,31,22,0.18)] backdrop-blur-xl xl:block"
      aria-label="Platform API private beta safety state"
    >
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#123326] text-[#DCEF8B]">
          <ShieldCheck className="h-4 w-4" />
        </div>
        <div>
          <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.16em] text-[#315D46]">
            <LockKeyhole className="h-3 w-3" /> Controlled private beta
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[10px] leading-5 text-[#5E7065]">
            <span>Automatic live approval disabled</span>
            <span>Physical execution disabled</span>
            <span>Test data isolated</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
