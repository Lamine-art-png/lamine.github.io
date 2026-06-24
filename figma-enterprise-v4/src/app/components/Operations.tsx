import { MoreHorizontal, User } from "lucide-react";

export function Operations() {
  return (
    <div className="min-h-screen">
      {/* Top Bar */}
      <header className="bg-[#FFFEFA] border-b border-[rgba(16,35,27,0.12)] px-8 py-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div>
              <div className="flex items-center gap-3 mb-1">
                <h1 className="text-2xl font-bold text-[#10231B]">Operations</h1>
                <span className="px-2.5 py-1 bg-[#F6F4EE] border border-[rgba(16,35,27,0.12)] rounded text-xs font-medium text-[#68776F]">
                  Evaluation workspace
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2 pl-6 border-l border-[rgba(16,35,27,0.12)]">
              <div>
                <div className="text-sm font-medium text-[#10231B]">Alpha Vineyard</div>
                <div className="text-xs text-[#68776F]">Wine grapes · Coastal production block</div>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="px-2.5 py-1 bg-[#F6F4EE] border border-[rgba(16,35,27,0.12)] rounded text-xs font-medium text-[#68776F]">
              Evaluation · not live · not certified
            </span>
            <button className="px-4 py-2 bg-[#16533C] hover:bg-[#1F7350] text-white text-sm font-medium rounded-lg transition-colors">
              Run Agent
            </button>
            <button className="w-9 h-9 flex items-center justify-center hover:bg-[#F6F4EE] rounded-lg transition-colors">
              <MoreHorizontal className="w-5 h-5 text-[#68776F]" />
            </button>
            <button className="w-9 h-9 flex items-center justify-center bg-[#10231B] hover:bg-[#16533C] text-white rounded-lg transition-colors">
              <User className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="p-8 space-y-6">
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-[#FFFEFA] border border-[rgba(16,35,27,0.12)] rounded-xl p-6">
            <div className="text-xs text-[#68776F] uppercase tracking-wider mb-2">Current decision</div>
            <div className="text-2xl font-bold text-[#10231B] mb-1">Irrigate 42 min tonight</div>
            <div className="text-sm text-[#68776F]">Decision ready</div>
          </div>
          <div className="bg-[#FFFEFA] border border-[rgba(16,35,27,0.12)] rounded-xl p-6">
            <div className="text-xs text-[#68776F] uppercase tracking-wider mb-2">Confidence</div>
            <div className="text-2xl font-bold text-[#10231B] mb-1">86%</div>
            <div className="text-sm text-[#68776F]">Decision confidence score</div>
          </div>
          <div className="bg-[#FFFEFA] border border-[rgba(16,35,27,0.12)] rounded-xl p-6">
            <div className="text-xs text-[#68776F] uppercase tracking-wider mb-2">Evidence completeness</div>
            <div className="text-2xl font-bold text-[#10231B] mb-1">92%</div>
            <div className="text-sm text-[#68776F]">Cross-source reconciliation coverage</div>
          </div>
          <div className="bg-[#FFFEFA] border border-[rgba(16,35,27,0.12)] rounded-xl p-6">
            <div className="text-xs text-[#68776F] uppercase tracking-wider mb-2">Estimated water savings</div>
            <div className="text-2xl font-bold text-[#10231B] mb-1">27%</div>
            <div className="text-sm text-[#68776F]">Assumption vs historical baseline</div>
          </div>
        </div>

        <div className="bg-[#FFFEFA] border border-[rgba(16,35,27,0.12)] rounded-xl p-8">
          <h2 className="text-lg font-bold text-[#10231B] mb-4">Decision Pipeline</h2>
          <p className="text-[#68776F] mb-6">
            Source normalization, reconciliation, confidence scoring, and verification preparation.
          </p>
          <div className="flex items-center gap-4">
            {["Sources", "Normalize", "Reconcile", "Decide"].map((step, i) => (
              <div key={step} className="flex-1">
                <div className="bg-[#16533C] text-white px-4 py-3 rounded-lg text-center">
                  <div className="text-xs font-medium">{step}</div>
                  <div className="text-[10px] text-white/70 mt-1">Complete</div>
                </div>
              </div>
            ))}
            {["Verify"].map((step) => (
              <div key={step} className="flex-1">
                <div className="bg-[#F6F4EE] border border-[rgba(16,35,27,0.12)] text-[#68776F] px-4 py-3 rounded-lg text-center">
                  <div className="text-xs font-medium">{step}</div>
                  <div className="text-[10px] mt-1">Complete</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
