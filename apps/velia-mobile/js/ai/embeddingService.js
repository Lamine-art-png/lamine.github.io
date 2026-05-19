import { modelRouter } from "./modelRouter.js";

function hashToken(token) {
  return token.split("").reduce((acc, c) => acc + c.charCodeAt(0), 0) % 997;
}

export const embeddingService = {
  embedText(text) {
    const tokens = String(text || "").toLowerCase().split(/\W+/).filter(Boolean);
    const vector = tokens.slice(0, 24).map((t) => hashToken(t) / 997);
    return {
      vector,
      tokenCount: tokens.length,
      model: modelRouter.route("embed").id,
    };
  },
};
