// Interactive lesson blocks: the only shapes the lesson page renders. Editors
// are refused anything else at save time, and the page skips malformed data.
const textOk = (v) => typeof v === "string" && v.trim().length > 0 && v.length <= 2000;

export function validInteractive(d) {
  if (!d || typeof d !== "object" || (d.title != null && typeof d.title !== "string")) return false;
  if (d.kind === "reveal") return Array.isArray(d.cards) && d.cards.length > 0 && d.cards.length <= 50 && d.cards.every((x) => x && textOk(x.front) && textOk(x.back));
  if (d.kind === "checklist") return Array.isArray(d.items) && d.items.length > 0 && d.items.length <= 100 && d.items.every(textOk);
  return false;
}
