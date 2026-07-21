import { useEffect } from "react";
import { useLocale } from "../hooks/useLocale";

/**
 * Staging environment indicator.
 *
 * Rendered only when the build explicitly declares
 * VITE_DEPLOYMENT_ENVIRONMENT=staging — production builds declare
 * "production" and never show it. Shows the exact short build SHA for
 * release-alignment review and injects a robots noindex meta so staging
 * pages stay out of search indexes. No secrets, no upstream origins.
 */
const DEPLOYMENT_ENVIRONMENT = String(import.meta.env.VITE_DEPLOYMENT_ENVIRONMENT || "").trim();
const BUILD_SHA = String(import.meta.env.VITE_BUILD_SHA || "").trim();

export function isStagingBuild(): boolean {
  return DEPLOYMENT_ENVIRONMENT === "staging";
}

export function StagingBanner() {
  const { t } = useLocale();

  useEffect(() => {
    if (!isStagingBuild()) return undefined;
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex, nofollow";
    document.head.appendChild(meta);
    return () => { document.head.removeChild(meta); };
  }, []);

  if (!isStagingBuild()) return null;
  return (
    <div
      role="status"
      data-staging-banner
      className="flex items-center justify-center gap-2 px-3 py-1 text-[11px] font-semibold"
      style={{ background: "#B7950B", color: "#241B02" }}
    >
      <span className="uppercase tracking-[0.16em]">{t("staging.banner")}</span>
      {BUILD_SHA ? (
        <span className="rounded bg-[#241B02]/10 px-1.5 font-mono" title={t("staging.buildSha")}>
          {BUILD_SHA.slice(0, 10)}
        </span>
      ) : null}
    </div>
  );
}
