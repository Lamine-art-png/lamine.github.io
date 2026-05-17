import { seedDocs } from "./knowledgeBase.js";
import { embeddingService } from "./embeddingService.js";
import { vectorStore } from "./vectorStore.js";

let initialized = false;

function chunkText(text) {
  return text.split(/\.\s+/).filter(Boolean);
}

async function initRag() {
  if (initialized) return;
  for (const doc of seedDocs) {
    const chunks = chunkText(doc.text);
    for (let i = 0; i < chunks.length; i += 1) {
      const emb = await embeddingService.embed(chunks[i]);
      await vectorStore.upsert({ id: `${doc.id}-${i}`, docId: doc.id, topic: doc.topic, text: chunks[i], vector: emb.vector });
    }
  }
  initialized = true;
}

export const ragEngine = {
  async retrieve(query) {
    await initRag();
    const emb = await embeddingService.embed(query || "irrigation");
    const hits = await vectorStore.search(emb.vector, 4);
    return hits.map((h) => ({ text: h.text, source: { docId: h.docId, topic: h.topic }, score: h.score }));
  },
};
