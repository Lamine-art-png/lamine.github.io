import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import {
  ensureLocaleCatalog,
  hasCompleteLocaleCatalog,
  hasCoreLocaleCatalog,
  hasCriticalLocaleCatalog,
  primeLocaleCatalogFromCache,
} from "../dynamicLocaleCatalog";
import {
  applyLocale,
  canonicalizeSelectedLocale,
  getStoredLocale,
  normalizeLocale,
  resolveLocaleDetailed,
  setStoredLocale,
  t,
} from "../i18n";
import { FULL_UI_TRANSLATION_DIAGNOSTIC, purgeLegacyDynamicCatalogCache } from "../i18nReleaseCompatibility";
import { getLocaleRuntimeSnapshot, notifyLocaleRuntime, subscribeLocaleRuntime } from "../localeRuntimeStore";

let explicitLocaleActivated = false;
let stableLocale = normalizeLocale(getStoredLocale()) === "en" ? getStoredLocale() : "en";
let rollbackInProgress = false;

function primeCriticalLocale(locale: string) {
  primeLocaleCatalogFromCache(locale, "critical");
}

function primeKnownLocale(locale: string) {
  primeCriticalLocale(locale);
  primeLocaleCatalogFromCache(locale, "core");
  primeLocaleCatalogFromCache(locale, "full");
}

function markStable(locale: string) {
  stableLocale = canonicalizeSelectedLocale(locale);
  rollbackInProgress = false;
}

export function useLocale() {
  const [selectedLocale, setSelectedLocaleState] = useState(getStoredLocale());
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const runtimeRevision = useSyncExternalStore(
    subscribeLocaleRuntime,
    getLocaleRuntimeSnapshot,
    getLocaleRuntimeSnapshot,
  );
  const effectiveLocale = useMemo(() => normalizeLocale(selectedLocale), [selectedLocale]);
  const resolution = useMemo(() => resolveLocaleDetailed(selectedLocale), [selectedLocale]);

  useEffect(() => {
    const listener = ((event: CustomEvent) => {
      const nextLocale = event.detail?.selectedLocale || event.detail?.locale || getStoredLocale();
      setSelectedLocaleState(nextLocale);
    }) as EventListener;
    window.addEventListener("agroai:locale-change", listener);
    return () => window.removeEventListener("agroai:locale-change", listener);
  }, []);

  useEffect(() => {
    applyLocale(selectedLocale);
  }, [selectedLocale]);

  useEffect(() => {
    let cancelled = false;

    async function hydrateSelectedLocale() {
      setCatalogError(null);
      if (effectiveLocale === "en") {
        markStable(selectedLocale);
        setCatalogLoading(false);
        return;
      }

      purgeLegacyDynamicCatalogCache(effectiveLocale);
      primeKnownLocale(selectedLocale);
      if (hasCompleteLocaleCatalog(selectedLocale)) {
        markStable(selectedLocale);
        setCatalogLoading(false);
        notifyLocaleRuntime();
        return;
      }

      setCatalogLoading(true);
      try {
        if (!hasCriticalLocaleCatalog(selectedLocale)) {
          await ensureLocaleCatalog(selectedLocale, "critical");
        }
        if (cancelled) return;
        notifyLocaleRuntime();

        if (!hasCoreLocaleCatalog(selectedLocale)) {
          await ensureLocaleCatalog(selectedLocale, "core");
        }
        if (cancelled) return;
        notifyLocaleRuntime();

        // Critical/core localization is enough to make the portal interactive.
        // Full literal convergence continues without holding the product behind
        // a global startup cover; failure still rolls back to the last stable locale.
        setCatalogLoading(false);

        if (!hasCompleteLocaleCatalog(selectedLocale)) {
          await ensureLocaleCatalog(selectedLocale, "full");
        }
        if (cancelled) return;
        if (!hasCompleteLocaleCatalog(selectedLocale)) {
          throw new Error(`Full UI translation incomplete for ${selectedLocale}`);
        }

        markStable(selectedLocale);
        notifyLocaleRuntime();
      } catch (cause) {
        if (cancelled) return;
        const message = cause instanceof Error ? cause.message : "UI translation unavailable";
        console.warn(FULL_UI_TRANSLATION_DIAGNOSTIC, { locale: selectedLocale, error: message });
        setCatalogError(message);
        setCatalogLoading(false);

        const current = getStoredLocale();
        if (!rollbackInProgress && current === selectedLocale && stableLocale !== selectedLocale) {
          rollbackInProgress = true;
          const restored = setStoredLocale(stableLocale);
          primeKnownLocale(restored);
          setSelectedLocaleState(restored);
          notifyLocaleRuntime();
        }
      }
    }

    void hydrateSelectedLocale();
    return () => {
      cancelled = true;
    };
  }, [selectedLocale, effectiveLocale]);

  const setLocale = (nextLocale: string) => {
    const canonical = canonicalizeSelectedLocale(nextLocale);
    const current = getStoredLocale();
    const localChoiceIsExplicit = current !== "auto";
    if ((explicitLocaleActivated || localChoiceIsExplicit) && canonical !== current) {
      primeCriticalLocale(current);
      setSelectedLocaleState(current);
      notifyLocaleRuntime();
      return current;
    }
    primeKnownLocale(canonical);
    const activated = setStoredLocale(canonical);
    if (normalizeLocale(activated) === "en" || hasCompleteLocaleCatalog(activated)) markStable(activated);
    setSelectedLocaleState(activated);
    notifyLocaleRuntime();
    return activated;
  };

  const activateLocale = (nextLocale: string) => {
    explicitLocaleActivated = true;
    const canonical = canonicalizeSelectedLocale(nextLocale);
    const current = getStoredLocale();
    primeKnownLocale(current);
    if (normalizeLocale(current) === "en" || hasCompleteLocaleCatalog(current)) markStable(current);

    primeKnownLocale(canonical);
    const activated = setStoredLocale(canonical);
    if (normalizeLocale(activated) === "en" || hasCompleteLocaleCatalog(activated)) markStable(activated);
    setSelectedLocaleState(activated);
    setCatalogError(null);
    notifyLocaleRuntime();
    return activated;
  };

  return {
    selectedLocale,
    effectiveLocale,
    locale: selectedLocale,
    normalizedLocale: effectiveLocale,
    resolution,
    setLocale,
    activateLocale,
    catalogLoading,
    catalogError,
    t: (key: string) => {
      void runtimeRevision;
      return t(key, selectedLocale);
    },
  };
}
