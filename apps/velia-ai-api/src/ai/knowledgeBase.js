import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const knowledgeDir = path.resolve(__dirname, "../../knowledge");

export const graphSchema = {
  entities: ["crop", "soil_type", "irrigation_method", "weather_risk", "field_observation", "recommendation", "confidence_factor", "verification_outcome"],
  relationships: [
    { from: "weather_risk", to: "recommendation", type: "changes_urgency" },
    { from: "soil_type", to: "confidence_factor", type: "changes_confidence" },
    { from: "field_observation", to: "recommendation", type: "provides_ground_truth_signal" },
    { from: "crop", to: "recommendation", type: "affects_water_demand" },
    { from: "verification_outcome", to: "confidence_factor", type: "updates_future_confidence" },
  ],
};

export function traverseGraph(entity) {
  return graphSchema.relationships.filter((edge) => edge.from === entity || edge.to === entity);
}

export function validateKnowledgeDocument(doc) {
  const required = ["id", "title", "topic", "sourceType", "content", "version", "lastUpdated", "citation"];
  const missing = required.filter((key) => !(key in (doc || {})));
  if (missing.length) throw new Error(`Knowledge document missing ${missing.join(", ")}`);
  if (typeof doc.content !== "string" || !doc.content.trim()) throw new Error(`Knowledge document ${doc.id} has empty content`);
  return doc;
}

export function loadKnowledgeDocuments(dir = knowledgeDir) {
  const files = fs.readdirSync(dir).filter((file) => file.endsWith(".json")).sort();
  return files.map((file) => {
    const doc = JSON.parse(fs.readFileSync(path.join(dir, file), "utf8"));
    return validateKnowledgeDocument({ ...doc, file });
  });
}

export function chunkKnowledgeDocument(doc, options = {}) {
  const maxChars = options.maxChars || 420;
  const sentences = doc.content.split(/(?<=[.!?])\s+/).map((s) => s.trim()).filter(Boolean);
  const chunks = [];
  let buffer = "";
  for (const sentence of sentences) {
    if (buffer && `${buffer} ${sentence}`.length > maxChars) {
      chunks.push(buffer);
      buffer = sentence;
    } else {
      buffer = buffer ? `${buffer} ${sentence}` : sentence;
    }
  }
  if (buffer) chunks.push(buffer);
  return chunks.map((text, index) => ({
    id: `${doc.id}:${index}`,
    text,
    source: {
      id: doc.id,
      title: doc.title,
      topic: doc.topic,
      sourceType: doc.sourceType,
      version: doc.version,
      lastUpdated: doc.lastUpdated,
      citation: doc.citation,
    },
    metadata: { chunkIndex: index, file: doc.file },
  }));
}

export const seedDocs = loadKnowledgeDocuments().map((doc) => ({
  id: doc.id,
  text: doc.content,
  topic: doc.topic,
  title: doc.title,
  citation: doc.citation,
}));
