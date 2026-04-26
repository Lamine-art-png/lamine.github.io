import { embeddingService } from "./embeddingService.js";
import { createVectorStore } from "./vectorStore.js";
import { seedKnowledgeDocuments } from "./knowledgeBase.js";

const store = createVectorStore();

function chunkDocument(doc) {
  return doc.text
    .split(/\.\s+/)
    .map((sentence, idx) => ({
      id: `${doc.id}::${idx}`,
      text: sentence.trim(),
      metadata: { docId: doc.id, title: doc.title, topic: doc.topic },
    }))
    .filter((chunk) => chunk.text.length > 10);
}

let bootstrapped = false;

function bootstrap() {
  if (bootstrapped) return;
  seedKnowledgeDocuments.forEach((doc) => {
    chunkDocument(doc).forEach((chunk) => {
      const emb = embeddingService.embedText(chunk.text);
      store.upsert({ ...chunk, vector: emb.vector });
    });
  });
  bootstrapped = true;
}

export const ragEngine = {
  retrieve(query, topK = 4) {
    bootstrap();
    const q = embeddingService.embedText(query || "irrigation");
    const ranked = store.search(q.vector, topK);
    return ranked.map((item) => ({
      chunkId: item.id,
      text: item.text,
      score: item.score,
      source: item.metadata,
      citation: `${item.metadata.docId}#${item.chunkId || item.id}`,
    }));
  },
};
