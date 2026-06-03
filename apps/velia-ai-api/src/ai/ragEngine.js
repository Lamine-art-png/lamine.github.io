import { chunkKnowledgeDocument, loadKnowledgeDocuments } from "./knowledgeBase.js";
import { embeddingService } from "./embeddingService.js";
import { vectorStore } from "./vectorStore.js";

let initialized = false;
let indexedChunkCount = 0;
let lastIngestError = null;

function tokenize(text) {
  return new Set(String(text || "").toLowerCase().split(/\W+/).filter((token) => token.length > 2));
}

function lexicalOverlap(query, text) {
  const q = tokenize(query);
  if (!q.size) return 0;
  const t = tokenize(text);
  let hits = 0;
  for (const token of q) if (t.has(token)) hits += 1;
  return hits / q.size;
}

function rerank(query, hits, topK) {
  return hits
    .map((hit) => ({
      ...hit,
      relevanceScore: Number(((hit.score || 0) * 0.75 + lexicalOverlap(query, hit.text) * 0.25).toFixed(4)),
    }))
    .sort((a, b) => b.relevanceScore - a.relevanceScore)
    .slice(0, topK);
}

export async function ingestKnowledge(options = {}) {
  const docs = loadKnowledgeDocuments(options.dir);
  const chunks = docs.flatMap((doc) => chunkKnowledgeDocument(doc, options.chunkOptions));
  const rows = [];
  for (const chunk of chunks) {
    const embedding = await embeddingService.embed(`${chunk.source.title}\n${chunk.text}`, { taskType: "RETRIEVAL_DOCUMENT" });
    rows.push({
      id: chunk.id,
      text: chunk.text,
      vector: embedding.vector,
      source: chunk.source,
      metadata: {
        ...chunk.metadata,
        embeddingProvider: embedding.provider,
        embeddingModel: embedding.model,
        embeddingFallbackUsed: embedding.fallbackUsed,
      },
    });
  }
  await vectorStore.upsertMany(rows);
  indexedChunkCount = rows.length;
  initialized = true;
  lastIngestError = null;
  return { documentCount: docs.length, chunkCount: rows.length };
}

async function ensureInitialized() {
  if (initialized) return;
  try {
    await ingestKnowledge();
  } catch (error) {
    lastIngestError = error.message;
    initialized = true;
  }
}

export const ragEngine = {
  async ingest(options) {
    initialized = false;
    return ingestKnowledge(options);
  },

  async retrieve(query, options = {}) {
    await ensureInitialized();
    if (lastIngestError) {
      return { chunks: [], fallbackUsed: true, fallbackReason: lastIngestError, sources: [] };
    }

    try {
      const topK = options.topK || 4;
      const embedding = await embeddingService.embed(query || "irrigation decision", { taskType: "RETRIEVAL_QUERY" });
      const initial = await vectorStore.search(embedding.vector, Math.max(topK * 3, topK), { minScore: options.minScore ?? -1 });
      const ranked = rerank(query, initial, topK);
      const chunks = ranked.map((hit) => ({
        chunkId: hit.id,
        text: hit.text,
        score: hit.score,
        relevanceScore: hit.relevanceScore,
        source: hit.source,
        metadata: hit.metadata,
      }));
      return {
        chunks,
        sources: chunks.map((chunk) => ({ ...chunk.source, score: chunk.relevanceScore })),
        indexedChunkCount,
        embeddingProvider: embedding.provider,
        fallbackUsed: false,
      };
    } catch (error) {
      return { chunks: [], fallbackUsed: true, fallbackReason: error.message, sources: [] };
    }
  },

  async resetForTests() {
    initialized = false;
    indexedChunkCount = 0;
    lastIngestError = null;
    if (typeof vectorStore.clear === "function") await vectorStore.clear();
  },
};
