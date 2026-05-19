import { MockTranslationProvider } from "../providers/mockProviders.js";

const provider = new MockTranslationProvider();

export const translationAgent = {
  async translate(text, language = "en") {
    return provider.translate(text, language);
  },
};
