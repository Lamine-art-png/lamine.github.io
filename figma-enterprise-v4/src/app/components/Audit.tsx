import { MoreHorizontal, User } from "lucide-react";

export function Audit() {
  return (
    <div className="min-h-screen">
      <header className="bg-[#FFFEFA] border-b border-[rgba(16,35,27,0.12)] px-8 py-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-6">
            <h1 className="text-2xl font-bold text-[#10231B]">Audit</h1>
            <span className="px-2.5 py-1 bg-[#F6F4EE] border border-[rgba(16,35,27,0.12)] rounded text-xs font-medium text-[#68776F]">
              Evaluation workspace
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button className="w-9 h-9 flex items-center justify-center hover:bg-[#F6F4EE] rounded-lg transition-colors">
              <MoreHorizontal className="w-5 h-5 text-[#68776F]" />
            </button>
            <button className="w-9 h-9 flex items-center justify-center bg-[#10231B] hover:bg-[#16533C] text-white rounded-lg transition-colors">
              <User className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>
      <div className="p-8">
        <div className="bg-[#FFFEFA] border border-[rgba(16,35,27,0.12)] rounded-xl p-8">
          <h2 className="text-lg font-bold text-[#10231B] mb-4">Audit Log</h2>
          <p className="text-[#68776F]">
            Track system activity and user actions for compliance and accountability.
          </p>
        </div>
      </div>
    </div>
  );
}
