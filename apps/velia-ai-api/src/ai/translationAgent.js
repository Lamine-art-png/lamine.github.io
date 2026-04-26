import { MockTranslationProvider } from "../providers/mockProviders.js";
import { modelRouter } from "./modelRouter.js";

const provider = new MockTranslationProvider();

export const translationAgent = {
  async translate(text, language = "en") {
    if (language === "en") return text;

    const llm = modelRouter.llmProvider();
    const model = modelRouter.modelFor("translate");
    const prompt = `Translate the following text to ${language}. Return only the translated text.\n\nText: ${text}`;

    try {
      const result = await llm.generate(prompt, { task: "translation", model, temperature: 0 });
      if (result?.text) return result.text.trim();
    } catch {
      // fallback handled below
    }

    return provider.translate(text, language);
  },
};
