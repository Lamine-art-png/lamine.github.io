import fs from "fs";
import path from "path";
import { VectorStoreProvider } from "./VectorStoreProvider.js";

export function cosineSimilarity(a = [], b = []) {
  const length = Math.max(a.length, b.length);
  if (!length) return 0;
  let dot = 0;
  let normA = 0;
  let normB = 0;
  for (let i = 0; i < length; i += 1) {
    const av = Number(a[i] || 0);
    const bv = Number(b[i] || 0);
    dot += av * bv;
    normA += av * av;
    normB += bv * bv;
  }
  if (!normA || !normB) return 0;
  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}

function readIndex(filePath) {
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
    return Array.isArray(parsed.rows) ? parsed.rows : [];
  } catch {
    return [];
  }
}

function writeIndex(filePath, rows) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify({ version: 1, updatedAt: new Date().toISOString(), rows }, null, 2));
}

export class LocalVectorStoreProvider extends VectorStoreProvider {
  constructor(options = {}) {
    super("local-json-vector");
    this.filePath = options.filePath;
    this.rows = options.rows || (this.filePath ? readIndex(this.filePath) : []);
  }

  persist() {
    if (this.filePath) writeIndex(this.filePath, this.rows);
  }

  async clear() {
    this.rows = [];
    this.persist();
  }

  async upsert(doc) {
    if (!doc?.id) throw new Error("Vector document requires id");
    if (!Array.isArray(doc.vector) || doc.vector.length === 0) throw new Error("Vector document requires vector");
    const row = {
      id: doc.id,
      vector: doc.vector,
      text: doc.text || "",
      source: doc.source || {},
      metadata: doc.metadata || {},
      updatedAt: new Date().toISOString(),
    };
    const existing = this.rows.findIndex((item) => item.id === row.id);
    if (existing >= 0) this.rows[existing] = row;
    else this.rows.push(row);
    this.persist();
    return row;
  }

  async search(vector, topK = 5, options = {}) {
    const minScore = options.minScore ?? -1;
    return this.rows
      .map((row) => ({ ...row, score: cosineSimilarity(row.vector, vector) }))
      .filter((row) => row.score >= minScore)
      .sort((a, b) => b.score - a.score)
      .slice(0, topK);
  }
}
