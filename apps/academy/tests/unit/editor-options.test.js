// Editing a question never gives two options the same id.
import { test } from "node:test";
import assert from "node:assert/strict";
import { fromEditorLines } from "../../src/pages/admin/assessments.js";

test("duplicate option labels are refused and reused ids stay distinct", () => {
  const previous = { data_json: JSON.stringify({ options: [{ id: "o1", text: "Maize" }, { id: "o2", text: "Rice" }] }) };
  assert.throws(() => fromEditorLines("single", "* Maize\nmaize\nRice", previous), /Each option must be different/);
  assert.throws(() => fromEditorLines("ordering", "Plant\nWater\nPlant", null), /Each item must be different/);
  const built = fromEditorLines("multiple", "* Maize\n* Rice\nWheat", previous);
  const ids = built.data.options.map((o) => o.id);
  assert.deepEqual(ids.slice(0, 2), ["o1", "o2"], "unchanged options keep their ids");
  assert.equal(new Set(ids).size, ids.length, "all ids distinct");
});
