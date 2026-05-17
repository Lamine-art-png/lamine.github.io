const supported = ["en", "fr", "es", "pt", "ar", "wo", "hi"];

export const translationAgent = {
  supportedLanguages: supported,
  translate(text, language = "en") {
    if (!supported.includes(language) || language === "en") return text;
    return `[${language}] ${text}`;
  },
};
