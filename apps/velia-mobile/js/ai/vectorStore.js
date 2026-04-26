export function createVectorStore() {
  const rows = [];

  function cosineLike(a, b) {
    const size = Math.min(a.length, b.length);
    if (!size) return 0;
    let dot = 0;
    for (let i = 0; i < size; i += 1) dot += a[i] * b[i];
    return dot / size;
  }

  return {
    upsert(entry) {
      rows.push(entry);
    },
    search(queryVector, topK = 5) {
      return rows
        .map((row) => ({ ...row, score: cosineLike(queryVector, row.vector) }))
        .sort((a, b) => b.score - a.score)
        .slice(0, topK);
    },
    list() {
      return rows;
    },
  };
}
