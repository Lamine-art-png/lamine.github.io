import { useCallback, useEffect, useRef, useState } from "react";
import { Download, FileText, Loader2, Play } from "lucide-react";
import { apiClient } from "../api/client";

/**
 * Authenticated media experience for observation assets.
 *
 * Bytes are fetched with the bearer token through the authorized range route
 * and surfaced as short-lived object URLs — no permanent public object URL
 * ever exists. Players handle loading, failure, deletion and permission
 * states; downloads reuse the same authorized fetch.
 */

type Asset = Record<string, any>;

type Props = { t: (key: string) => string; assets: Asset[]; transcript?: string | null };

function useAssetUrl(asset: Asset | null) {
  const [url, setUrl] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "failed" | "gone">("idle");
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!asset || asset.status !== "stored") {
      setState(asset ? "gone" : "idle");
      return () => undefined;
    }
    setState("loading");
    (async () => {
      try {
        const blob = await apiClient.fieldIntelligence.assetBlob(asset.id);
        if (cancelled) return;
        const objectUrl = URL.createObjectURL(blob);
        urlRef.current = objectUrl;
        setUrl(objectUrl);
        setState("ready");
      } catch (error: any) {
        if (cancelled) return;
        setState(error?.status === 404 || error?.status === 410 ? "gone" : "failed");
      }
    })();
    return () => {
      cancelled = true;
      if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = null; }
    };
  }, [asset?.id, asset?.status]);

  return { url, state };
}

function AssetTile({ t, asset }: { t: (key: string) => string; asset: Asset }) {
  const { url, state } = useAssetUrl(asset);
  const [downloadBusy, setDownloadBusy] = useState(false);

  const download = useCallback(async () => {
    setDownloadBusy(true);
    try {
      const blob = await apiClient.fieldIntelligence.assetBlob(asset.id);
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = asset.filename || `${asset.kind}-${asset.id}`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 5000);
    } catch {
      /* surfaced through tile state on next fetch */
    } finally {
      setDownloadBusy(false);
    }
  }, [asset.id, asset.filename, asset.kind]);

  const meta = (
    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-[#65736A]">
      <span>{t(`fieldIntel.kind.${asset.kind}`)}</span>
      {asset.size_bytes ? <span>{(asset.size_bytes / 1024 / 1024).toFixed(2)} MB</span> : null}
      {asset.duration_seconds ? <span>{Math.round(asset.duration_seconds)}s</span> : null}
      <button type="button" onClick={download} disabled={downloadBusy || asset.status !== "stored"}
        className="inline-flex items-center gap-1 rounded border border-[#D6DDD0] px-2 py-0.5 font-semibold text-[#10231B] disabled:opacity-40"
        aria-label={t("fieldIntel.download")}>
        {downloadBusy ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : <Download className="h-3 w-3" aria-hidden />}
        {t("fieldIntel.download")}
      </button>
    </div>
  );

  if (asset.status !== "stored") {
    return (
      <div className="rounded-lg border border-[#D6DDD0] bg-[#F7F8F5] p-3 text-[12px] text-[#65736A]">
        {t("fieldIntel.mediaDeleted")}
      </div>
    );
  }
  if (state === "loading" || state === "idle") {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-[#D6DDD0] p-3 text-[12px] text-[#65736A]">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {t("fieldIntel.mediaLoading")}
      </div>
    );
  }
  if (state === "failed" || state === "gone" || !url) {
    return (
      <div className="rounded-lg border border-[#E4C7C2] bg-[#FBF3F2] p-3 text-[12px] text-[#B23B2E]">
        {state === "gone" ? t("fieldIntel.mediaDeleted") : t("fieldIntel.mediaFailed")}
      </div>
    );
  }
  if (asset.kind === "audio") {
    return (
      <div className="rounded-lg border border-[#D6DDD0] p-3">
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <audio controls preload="metadata" src={url} className="w-full" aria-label={t("fieldIntel.audioPlayer")} />
        {meta}
      </div>
    );
  }
  if (asset.kind === "video") {
    return (
      <div className="rounded-lg border border-[#D6DDD0] p-3">
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video controls preload="metadata" src={url} className="max-h-[280px] w-full rounded" aria-label={t("fieldIntel.videoPlayer")} />
        {meta}
      </div>
    );
  }
  if (asset.kind === "photo") {
    return (
      <div className="rounded-lg border border-[#D6DDD0] p-3">
        <img src={url} alt={asset.filename || t("fieldIntel.photoEvidence")} className="max-h-[280px] w-full rounded object-contain" />
        {meta}
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-[#D6DDD0] p-3">
      <div className="flex items-center gap-2 text-[12px] text-[#3B4A41]">
        <FileText className="h-4 w-4" aria-hidden /> {asset.filename || t("fieldIntel.fileEvidence")}
      </div>
      {meta}
    </div>
  );
}

export function MediaViewer({ t, assets, transcript }: Props) {
  const media = (assets || []).filter((asset) => asset && asset.id);
  if (media.length === 0) return null;
  const audio = media.find((asset) => asset.kind === "audio" && asset.status === "stored");
  return (
    <div className="space-y-2">
      {media.map((asset) => <AssetTile key={asset.id} t={t} asset={asset} />)}
      {audio && transcript ? (
        <div className="rounded-lg border border-[#D6DDD0] bg-[#F7F8F5] p-3">
          <div className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-[#2D6A4F]">
            <Play className="h-3 w-3" aria-hidden /> {t("fieldIntel.transcriptWithAudio")}
          </div>
          <p className="mt-1 whitespace-pre-wrap text-[13px] text-[#10231B]">{transcript}</p>
        </div>
      ) : null}
    </div>
  );
}
