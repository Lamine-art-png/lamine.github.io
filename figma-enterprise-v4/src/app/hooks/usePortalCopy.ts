import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import {
  ensureLocaleSourceCatalog,
  hasLocaleSourceCatalog,
  primeLocaleSourceCatalogFromCache,
} from "../dynamicLocaleCatalog";
import { formatTranslation, getStoredLocale, normalizeLocale } from "../i18n";
import { getLocaleRuntimeSnapshot, subscribeLocaleRuntime } from "../localeRuntimeStore";
import { dynamicCopySourceForNamespaces, translatePortalLiteral } from "../portalLiteralCatalog";

export type PortalCopyValues = Record<string, string | number | undefined>;

export function usePortalCopy(namespaces: readonly string[]) {
  const namespaceKey = namespaces.join("|");
  const [locale, setLocale] = useState(getStoredLocale());
  const runtimeRevision = useSyncExternalStore(
    subscribeLocaleRuntime,
    getLocaleRuntimeSnapshot,
    getLocaleRuntimeSnapshot,
  );
  const source = useMemo(
    () => dynamicCopySourceForNamespaces(namespaceKey.split("|").filter(Boolean)),
    [namespaceKey],
  );

  useEffect(() => {
    const listener = ((event: CustomEvent) => {
      setLocale(event.detail?.selectedLocale || event.detail?.locale || getStoredLocale());
    }) as EventListener;
    window.addEventListener("agroai:locale-change", listener);
    return () => window.removeEventListener("agroai:locale-change", listener);
  }, []);

  useEffect(() => {
    if (normalizeLocale(locale) === "en" || !Object.keys(source).length) return;
    primeLocaleSourceCatalogFromCache(locale, source);
    if (hasLocaleSourceCatalog(locale, source)) return;
    void ensureLocaleSourceCatalog(locale, source).catch((error) => {
      console.warn("route_copy_translation_deferred", {
        locale,
        namespaces: namespaceKey,
        error: error instanceof Error ? error.message : String(error),
      });
    });
  }, [locale, namespaceKey, source]);

  const tx = (value: string): string => {
    void runtimeRevision;
    return translatePortalLiteral(value, locale);
  };

  const tf = (template: string, values: PortalCopyValues): string => formatTranslation(tx(template), values);

  return { locale, tx, tf };
}
