const LEGACY_DYNAMIC_CATALOG_PREFIX = "agroai_ui_catalog_v4:";

export const FULL_UI_TRANSLATION_DIAGNOSTIC = "Full UI translation unavailable";

export function purgeLegacyDynamicCatalogCache(locale: string) {
  try {
    const prefix = `${LEGACY_DYNAMIC_CATALOG_PREFIX}${locale}:`;
    for (let index = localStorage.length - 1; index >= 0; index -= 1) {
      const key = localStorage.key(index);
      if (key?.startsWith(prefix)) localStorage.removeItem(key);
    }
  } catch {
    // Browser cache cleanup is a best-effort migration only.
  }
}
