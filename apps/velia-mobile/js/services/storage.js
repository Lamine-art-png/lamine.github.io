const PREFIX = "terris-mobile:";
const LEGACY_PREFIX = "velia-mobile:";

export const storage = {
  get(key, fallback) {
    try {
      const raw = localStorage.getItem(PREFIX + key);
      if (raw) return JSON.parse(raw);
      const legacyRaw = localStorage.getItem(LEGACY_PREFIX + key);
      if (!legacyRaw) return fallback;
      const parsed = JSON.parse(legacyRaw);
      localStorage.setItem(PREFIX + key, JSON.stringify(parsed));
      return parsed;
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
  },
  keys: { currentPrefix: PREFIX, legacyPrefix: LEGACY_PREFIX },
};
