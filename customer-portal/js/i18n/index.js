import { translations } from "./translations.js";

let currentLanguage = "en";

export function setLanguage(language) {
  currentLanguage = translations[language] ? language : "en";
}

export function t(path, fallback = "") {
  const parts = path.split(".");
  let cursor = translations[currentLanguage] || translations.en;
  for (const part of parts) {
    cursor = cursor?.[part];
  }
  return cursor ?? fallback ?? path;
}

export function language() {
  return currentLanguage;
}
