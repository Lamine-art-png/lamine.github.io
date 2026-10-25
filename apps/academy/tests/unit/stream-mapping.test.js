// Mapping Stream uploads to Course A1's fourteen lesson videos (scripts/stream.mjs).
import { test } from "node:test";
import assert from "node:assert/strict";
import { mapUploads, a1Videos, numberIn } from "../../scripts/stream.mjs";

const uid = (i) => i.toString(16).padStart(32, "0");

test("A1 has fourteen lesson videos in syllabus order, quizzes excluded", () => {
  const v = a1Videos();
  assert.equal(v.length, 14);
  assert.deepEqual([v[0].id, v[7].id, v[13].id], ["vid_a1_welcome", "vid_a1_irrigation", "vid_a1_summary"]);
  assert.equal(v[7].title, "Case study: irrigation and water management");
});

test("uploads map by title; numbers break ties; unrelated or ambiguous uploads stay unmapped", () => {
  const titles = [
    "Welcome to the course", "From rules to learning: what AI is and isn't", "Why agriculture is turning to AI now",
    "Data: the raw material of agricultural AI", "Models, training and predictions", "From prediction to recommendation",
    "Planning and planting", "Irrigation and water management", "Crop health monitoring from above and up close",
    "Harvest, markets and the supply chain", "Limits, errors and when to challenge a recommendation",
    "Data ownership, privacy and trust", "Practical exercise: evaluate an AI recommendation", "Course summary and next steps",
  ];
  // Shuffled, with file extensions and the founder's numbering.
  const uploads = titles.map((t, i) => ({ uid: uid(i), name: `${String(i + 1).padStart(2, "0")} - ${t}.mp4` })).reverse();
  uploads.push({ uid: uid(99), name: "AGRO-AI brand film 2026.mp4" });
  const map = mapUploads(uploads);
  assert.equal(map.length, 14);
  for (const m of map) assert.equal(m.upload.uid, uid(m.video.n - 1), `video ${m.video.n}`);
  assert.ok(!map.some((m) => m.upload.uid === uid(99)));
  // Two copies of the same lesson: neither is chosen over the other.
  const dup = mapUploads([{ uid: uid(1), name: "Planning and planting" }, { uid: uid(2), name: "Planning and planting" }]);
  assert.equal(dup.length, 0);
  // Titles alone (no numbers) still map.
  assert.equal(mapUploads(titles.map((t, i) => ({ uid: uid(i), name: t }))).length, 14);
});

test("video numbers are read from common naming schemes, not from years", () => {
  assert.equal(numberIn("A1-07 Planning.mp4"), 7);
  assert.equal(numberIn("Lesson 12 – Data ownership"), 12);
  assert.equal(numberIn("video_3_final.mov"), 3);
  assert.equal(numberIn("Brand film 2026.mp4"), null);
  assert.equal(numberIn("Welcome"), null);
});
