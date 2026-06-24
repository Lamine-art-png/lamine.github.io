import { MoreHorizontal, User } from "lucide-react";
import { ImageWithFallback } from "./figma/ImageWithFallback";
import wiseconnLogo from "../../imports/wiseconn-logo-1.png";
import talgilLogo from "../../imports/talgil-logo-1.png";

export function Integrations() {
  return (
    <div className="min-h-screen">
      <header className="bg-[#FFFEFA] border-b border-[rgba(16,35,27,0.12)] px-8 py-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-6">
            <h1 className="text-2xl font-bold text-[#10231B]">Integrations</h1>
            <span className="px-2.5 py-1 bg-[#F6F4EE] border border-[rgba(16,35,27,0.12)] rounded text-xs font-medium text-[#68776F]">
              Evaluation workspace
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button className="px-4 py-2 bg-[#16533C] hover:bg-[#1F7350] text-white text-sm font-medium rounded-lg transition-colors">
              Add Integration
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
      <div className="p-8">
        <div className="bg-[#FFFEFA] border border-[rgba(16,35,27,0.12)] rounded-xl p-8">
          <h2 className="text-lg font-bold text-[#10231B] mb-4">Connected Systems</h2>
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div className="flex items-center gap-4 p-4 bg-[#F6F4EE] border border-[rgba(16,35,27,0.12)] rounded-lg">
              <div className="w-12 h-12 bg-white rounded flex items-center justify-center overflow-hidden">
                <ImageWithFallback 
                  src={wiseconnLogo} 
                  alt="WiseConn" 
                  className="w-full h-full object-contain p-1"
                />
              </div>
              <div className="flex-1">
                <div className="text-sm font-medium text-[#10231B]">WiseConn</div>
                <div className="text-xs text-[#68776F]">Integrated · Active</div>
              </div>
              <button className="px-3 py-1.5 text-xs text-[#68776F] hover:text-[#10231B]">Configure</button>
            </div>
            <div className="flex items-center gap-4 p-4 bg-[#F6F4EE] border border-[rgba(16,35,27,0.12)] rounded-lg">
              <div className="w-12 h-12 bg-white rounded flex items-center justify-center overflow-hidden">
                <ImageWithFallback 
                  src={talgilLogo} 
                  alt="Talgil" 
                  className="w-full h-full object-contain p-1"
                />
              </div>
              <div className="flex-1">
                <div className="text-sm font-medium text-[#10231B]">Talgil</div>
                <div className="text-xs text-[#68776F]">Integrated · Active</div>
              </div>
              <button className="px-3 py-1.5 text-xs text-[#68776F] hover:text-[#10231B]">Configure</button>
            </div>
          </div>
          <div className="text-xs text-[#68776F]">
            Compatibility indicates technical integration capability. It does not imply endorsement, certification, or formal partnership unless explicitly stated.
          </div>
        </div>
      </div>
    </div>
  );
}
