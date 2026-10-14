import { useEffect, useState } from "react";
import { Loader2, Sprout, X } from "lucide-react";
import { apiClient, type ApiError } from "../api/client";
import { usePortalCopy } from "../hooks/usePortalCopy";
import { CROP_COPY_VALUES, CROP_INTELLIGENCE_COPY, type CropCopyKey } from "./cropIntelligenceCopy";
import { clearMarketHandoff, readMarketHandoff, type MarketYieldHandoff } from "./cropIntelligenceModel";

type Position = { position_id: string; name: string; commodity: string; season: string };
type YieldResponse = { applied_to_expected_production?: boolean; reason?: string | null };

/**
 * A Crop Intelligence production estimate arrives here only as a proposal. It is
 * recorded through the existing yield-estimate intake, never automatically, and
 * it changes a position's expected production only when a person with write
 * access explicitly asks for that; the replaced value is kept by the server.
 */
export function CropYieldProposalReview({ positions, canWrite, onRecorded }: {
  positions: Position[]; canWrite: boolean; onRecorded: (message: string) => void;
}) {
  const { tx, locale } = usePortalCopy([], CROP_COPY_VALUES);
  const c = (key: CropCopyKey) => tx(CROP_INTELLIGENCE_COPY[key]);
  const [proposal, setProposal] = useState<MarketYieldHandoff | null>(() => readMarketHandoff());
  const [positionId, setPositionId] = useState("");
  const [apply, setApply] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (!positionId && positions[0]) setPositionId(positions[0].position_id); }, [positions, positionId]);

  if (!proposal) return null;
  const format = new Intl.NumberFormat(locale && locale !== "auto" ? locale : undefined, { maximumFractionDigits: 2 });
  const discard = () => { clearMarketHandoff(); setProposal(null); };

  const record = async () => {
    if (!positionId || !canWrite) return;
    setBusy(true);
    setError("");
    try {
      const response = await apiClient.post<YieldResponse>(`/v1/market-intelligence/positions/${encodeURIComponent(positionId)}/yield-estimates`, {
        yield_per_area: proposal.yield_per_area,
        quantity_unit: proposal.quantity_unit,
        area_unit: proposal.area_unit === "acre" ? "acre" : "hectare",
        source: "crop_intelligence",
        note: proposal.note.slice(0, 1000) || null,
        apply_to_production: apply,
      });
      clearMarketHandoff();
      setProposal(null);
      onRecorded(response.applied_to_expected_production ? c("marketApplied") : apply && response.reason === "no_linked_area" ? c("marketNoArea") : c("marketRecorded"));
    } catch (cause) {
      setError((cause as ApiError)?.message || c("failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mt-4 rounded-2xl border border-[#C6DECC] bg-[#F7FBF8] p-5 shadow-[0_14px_40px_rgba(16,35,27,0.05)]" aria-labelledby="crop-yield-proposal-title" data-crop-yield-proposal>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="crop-yield-proposal-title" className="flex items-center gap-2 text-[16px] font-semibold text-[#10231B]"><Sprout className="h-4 w-4 text-[#2D6A4F]" />{c("marketTitle")}</h2>
          <p className="mt-1 text-[13px] leading-6 text-[#526057]">{c("marketBody")}</p>
        </div>
        <button type="button" onClick={discard} aria-label={c("marketDiscard")} className="inline-flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg text-[#526057]"><X className="h-4 w-4" /></button>
      </div>
      <dl className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl bg-white p-3"><dt className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[#65736A]">{c("marketYield")}</dt><dd className="mt-1 text-[20px] font-semibold text-[#10231B]">{format.format(Number(proposal.yield_per_area))} <span className="text-[13px] font-medium text-[#526057]">{proposal.quantity_unit}/{proposal.area_unit === "acre" ? "ac" : "ha"}</span></dd></div>
        <div className="rounded-xl bg-white p-3 text-[12px] text-[#526057]"><dt className="font-semibold text-[#10231B]">{proposal.basis === "marketable" ? c("marketBasisMarketable") : c("marketBasisTotal")}</dt>{proposal.interval ? <dd className="mt-1">{c("interval95")}: {format.format(proposal.interval[0])}–{format.format(proposal.interval[1])} {proposal.quantity_unit}</dd> : null}</div>
        <div className="rounded-xl bg-white p-3 text-[12px] text-[#526057]"><dt className="font-semibold text-[#10231B]">{c("marketSample")}</dt><dd className="mt-1">{proposal.object_label} · n = {proposal.sampled_units}</dd><dd className="mt-0.5">{c("inputsUnverified")}</dd></div>
      </dl>
      {!positions.length ? <p className="mt-4 text-[13px] text-[#65736A]">{c("marketNoPositions")}</p> : !canWrite ? <p className="mt-4 text-[13px] text-[#65736A]">{c("marketReadOnly")}</p> : (
        <div className="mt-4 space-y-3">
          <select aria-label={tx("Position")} value={positionId} onChange={(event) => setPositionId(event.target.value)} className="min-h-[44px] w-full rounded-xl border border-[#D6DDD0] bg-white px-3 text-[14px] sm:max-w-md">
            {positions.map((item) => <option key={item.position_id} value={item.position_id}>{item.name} · {item.commodity} · {item.season}</option>)}
          </select>
          <label className="flex items-start gap-3 text-[13px] text-[#10231B]">
            <input type="checkbox" className="mt-0.5 h-5 w-5" checked={apply} onChange={(event) => setApply(event.target.checked)} />
            <span><span className="font-semibold">{c("marketApply")}</span><span className="mt-0.5 block text-[12px] text-[#65736A]">{c("marketApplyHint")}</span></span>
          </label>
          {error ? <p role="alert" className="rounded-xl border border-[#F0C6B8] bg-[#FFF5F1] px-3 py-2 text-[13px] text-[#8B321B]">{error}</p> : null}
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy || !positionId} onClick={() => void record()} className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#234224] px-4 text-[13px] font-semibold text-white disabled:opacity-50">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{c("marketRecord")}</button>
            <button type="button" onClick={discard} className="inline-flex min-h-[44px] items-center rounded-xl border border-[#C7D2C9] bg-white px-4 text-[13px] font-semibold text-[#234224]">{c("marketDiscard")}</button>
          </div>
        </div>
      )}
    </section>
  );
}
