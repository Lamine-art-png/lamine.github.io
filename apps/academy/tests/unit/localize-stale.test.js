// A translation is used only while its source is unchanged: an edited source
// (or translated JSON whose ids no longer match) falls back to the source.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv } from "../helpers.js";
import { localize } from "../../src/services/content.js";
import { sha256Hex } from "../../src/lib/util.js";

test("stale translations and mismatched JSON ids are not overlaid", async () => {
  const env = makeEnv();
  const src = { id: "q_x", prompt: "Which crop?", data_json: JSON.stringify({ options: [{ id: "o1", text: "Maize" }, { id: "o2", text: "Rice" }] }) };
  const put = async (field, value, sourceValue) =>
    env.DB.prepare("INSERT OR REPLACE INTO content_translations (entity_type, entity_id, field, locale, value, status, source_hash, updated_at) VALUES ('question', 'q_x', ?, 'fr-FR', ?, 'reviewed', ?, '2026-01-01')")
      .bind(field, value, await sha256Hex(sourceValue))
      .run();
  await put("prompt", "Quelle culture ?", src.prompt);
  await put("data_json", JSON.stringify({ options: [{ id: "o1", text: "Maïs" }, { id: "o2", text: "Riz" }] }), src.data_json);
  let row = { ...src };
  await localize(env, "question", row, ["prompt", "data_json"], "fr-FR", { requireReviewed: true });
  assert.equal(row.prompt, "Quelle culture ?");
  assert.match(row.data_json, /Maïs/);

  // The source question is edited: new prompt, an option replaced.
  const edited = { id: "q_x", prompt: "Which cereal?", data_json: JSON.stringify({ options: [{ id: "o1", text: "Maize" }, { id: "o3", text: "Wheat" }] }) };
  row = { ...edited };
  await localize(env, "question", row, ["prompt", "data_json"], "fr-FR", { requireReviewed: true });
  assert.equal(row.prompt, "Which cereal?", "stale prompt falls back to the source");
  assert.equal(row.data_json, edited.data_json, "stale options fall back to the source");
  assert.equal(row._tr.status, "missing");

  // Even with a matching hash, translated JSON must keep the source's ids.
  await put("data_json", JSON.stringify({ options: [{ id: "o1", text: "Maïs" }, { id: "o2", text: "Riz" }] }), edited.data_json);
  row = { ...edited };
  await localize(env, "question", row, ["data_json"], "fr-FR", { requireReviewed: true });
  assert.equal(row.data_json, edited.data_json, "ids differ from the source: not used");
});
