const PREFIX = "terris-mobile:";
const LEGACY_PREFIX = "velia-mobile:";

export const storage = {
  get(key, fallback) {
    const read = (prefix) => {
      const raw = localStorage.getItem(prefix + key);
      return raw ? JSON.parse(raw) : null;
    };
    try {
      const current = read(PREFIX);
      if (current) return current;
      const legacy = read(LEGACY_PREFIX);
      if (!legacy) return fallback;
      localStorage.setItem(PREFIX + key, JSON.stringify(legacy));
      return legacy;
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
  },
  legacyKey(key) {
    return LEGACY_PREFIX + key;
  },
  currentKey(key) {
    return PREFIX + key;
  },
};
