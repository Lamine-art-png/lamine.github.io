const PREFIX = "velia:";

export const storageService = {
  set(key, value) {
    localStorage.setItem(`${PREFIX}${key}`, JSON.stringify(value));
  },
  get(key, fallback) {
    const raw = localStorage.getItem(`${PREFIX}${key}`);
    if (!raw) return fallback;
    try { return JSON.parse(raw); } catch { return fallback; }
  },
  remove(key) {
    localStorage.removeItem(`${PREFIX}${key}`);
  },
};
