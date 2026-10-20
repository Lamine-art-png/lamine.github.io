// TrueType/OpenType font reader for certificate PDFs: tables, cmap, metrics,
// glyph outlines, OpenType layout tables (GDEF/GSUB/GPOS), and a glyph
// subsetter that produces a compact TrueType font for embedding.
// Reads lazily from the original bytes; nothing is copied until subsetting.

const tagAt = (v, o) => String.fromCharCode(v.getUint8(o), v.getUint8(o + 1), v.getUint8(o + 2), v.getUint8(o + 3));

export class Font {
  /** @param {Uint8Array|ArrayBuffer} data  @param {{index?: number}} opts face index for .ttc collections */
  constructor(data, { index = 0 } = {}) {
    this.bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
    this.view = new DataView(this.bytes.buffer, this.bytes.byteOffset, this.bytes.byteLength);
    let dir = 0;
    if (tagAt(this.view, 0) === "ttcf") {
      const count = this.view.getUint32(8);
      if (index >= count) throw new Error("font index out of range");
      dir = this.view.getUint32(12 + index * 4);
    }
    const flavor = this.view.getUint32(dir);
    if (flavor !== 0x00010000 && tagAt(this.view, dir) !== "true") throw new Error("only TrueType-outline fonts are supported");
    const numTables = this.view.getUint16(dir + 4);
    this.tables = {};
    for (let i = 0; i < numTables; i++) {
      const r = dir + 12 + i * 16;
      this.tables[tagAt(this.view, r)] = { offset: this.view.getUint32(r + 8), length: this.view.getUint32(r + 12) };
    }
    // cmap is optional: PDF-embedded subsets address glyphs by id.
    for (const t of ["head", "hhea", "maxp", "hmtx", "loca", "glyf"]) if (!this.tables[t]) throw new Error(`font is missing the ${t} table`);
    const head = this.tables.head.offset;
    this.unitsPerEm = this.view.getUint16(head + 18);
    this.bbox = [0, 2, 4, 6].map((d) => this.view.getInt16(head + 36 + d));
    this.indexToLocFormat = this.view.getInt16(head + 50);
    const hhea = this.tables.hhea.offset;
    this.ascender = this.view.getInt16(hhea + 4);
    this.descender = this.view.getInt16(hhea + 6);
    this.numberOfHMetrics = this.view.getUint16(hhea + 34);
    this.numGlyphs = this.view.getUint16(this.tables.maxp.offset + 4);
    const os2 = this.tables["OS/2"];
    this.fsType = os2 ? this.view.getUint16(os2.offset + 8) : 0;
    this.capHeight = os2 && this.view.getUint16(os2.offset) >= 2 ? this.view.getInt16(os2.offset + 88) : Math.round(this.ascender * 0.7);
    this.name = this.postscriptName();
    this._cmap = null;
    this._layout = {};
  }

  u8(o) {
    return this.view.getUint8(o);
  }
  u16(o) {
    return this.view.getUint16(o);
  }
  i16(o) {
    return this.view.getInt16(o);
  }
  u32(o) {
    return this.view.getUint32(o);
  }

  /** Whether the font's license permits embedding (OS/2 fsType). */
  get embeddable() {
    return (this.fsType & 0x000f) !== 0x0002;
  }

  postscriptName() {
    const t = this.tables.name;
    if (!t) return "Embedded";
    const count = this.u16(t.offset + 2);
    const strings = t.offset + this.u16(t.offset + 4);
    for (let i = 0; i < count; i++) {
      const r = t.offset + 6 + i * 12;
      if (this.u16(r + 6) !== 6) continue;
      const platform = this.u16(r);
      const len = this.u16(r + 8);
      const off = strings + this.u16(r + 10);
      let s = "";
      if (platform === 3 || platform === 0) for (let j = 0; j < len; j += 2) s += String.fromCharCode(this.u16(off + j));
      else for (let j = 0; j < len; j++) s += String.fromCharCode(this.u8(off + j));
      s = s.replace(/[^A-Za-z0-9-]/g, "");
      if (s) return s;
    }
    return "Embedded";
  }

  /** Unicode code point → glyph id (0 when missing). */
  glyphForCodePoint(cp) {
    if (!this._cmap) this._cmap = this.readCmap();
    return this._cmap(cp);
  }

  readCmap() {
    if (!this.tables.cmap) return () => 0;
    const base = this.tables.cmap.offset;
    const n = this.u16(base + 2);
    const subs = [];
    for (let i = 0; i < n; i++) {
      const r = base + 4 + i * 8;
      subs.push({ platform: this.u16(r), encoding: this.u16(r + 2), offset: base + this.u32(r + 4) });
    }
    const pick = (p, e) => subs.find((s) => s.platform === p && s.encoding === e && [4, 12].includes(this.u16(s.offset)));
    const sub = pick(3, 10) || pick(0, 4) || pick(3, 1) || pick(0, 3) || subs.find((s) => [4, 12].includes(this.u16(s.offset)));
    if (!sub) return () => 0;
    const o = sub.offset;
    if (this.u16(o) === 12) {
      const groups = this.u32(o + 12);
      return (cp) => {
        let lo = 0;
        let hi = groups - 1;
        while (lo <= hi) {
          const mid = (lo + hi) >> 1;
          const g = o + 16 + mid * 12;
          const start = this.u32(g);
          const end = this.u32(g + 4);
          if (cp < start) hi = mid - 1;
          else if (cp > end) lo = mid + 1;
          else return this.u32(g + 8) + (cp - start);
        }
        return 0;
      };
    }
    const segX2 = this.u16(o + 6);
    const ends = o + 14;
    const starts = ends + segX2 + 2;
    const deltas = starts + segX2;
    const ranges = deltas + segX2;
    return (cp) => {
      if (cp > 0xffff) return 0;
      let lo = 0;
      let hi = segX2 / 2 - 1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        const end = this.u16(ends + mid * 2);
        const start = this.u16(starts + mid * 2);
        if (cp > end) lo = mid + 1;
        else if (cp < start) hi = mid - 1;
        else {
          const delta = this.i16(deltas + mid * 2);
          const ro = this.u16(ranges + mid * 2);
          if (ro === 0) return (cp + delta) & 0xffff;
          const gi = this.u16(ranges + mid * 2 + ro + (cp - start) * 2);
          return gi === 0 ? 0 : (gi + delta) & 0xffff;
        }
      }
      return 0;
    };
  }

  advance(gid) {
    const h = this.tables.hmtx.offset;
    const i = Math.min(gid, this.numberOfHMetrics - 1);
    return this.u16(h + i * 4);
  }

  leftSideBearing(gid) {
    const h = this.tables.hmtx.offset;
    if (gid < this.numberOfHMetrics) return this.i16(h + gid * 4 + 2);
    return this.i16(h + this.numberOfHMetrics * 4 + (gid - this.numberOfHMetrics) * 2);
  }

  glyphRange(gid) {
    const l = this.tables.loca.offset;
    let a;
    let b;
    if (this.indexToLocFormat === 0) {
      a = this.u16(l + gid * 2) * 2;
      b = this.u16(l + gid * 2 + 2) * 2;
    } else {
      a = this.u32(l + gid * 4);
      b = this.u32(l + gid * 4 + 4);
    }
    return [this.tables.glyf.offset + a, b - a];
  }

  /** Component glyph ids of a composite glyph (empty for simple glyphs). */
  components(gid) {
    const [o, len] = this.glyphRange(gid);
    if (!len || this.i16(o) >= 0) return [];
    const out = [];
    let p = o + 10;
    for (;;) {
      const flags = this.u16(p);
      out.push({ gid: this.u16(p + 2), at: p + 2 - o });
      p += 4 + (flags & 1 ? 4 : 2);
      if (flags & 8) p += 2;
      else if (flags & 0x40) p += 4;
      else if (flags & 0x80) p += 8;
      if (!(flags & 0x20)) break;
    }
    return out;
  }

  /**
   * Glyph outline as contours of points {x, y, on}, with composites resolved.
   * Used to draw glyphs in tests; PDFs embed the font itself.
   */
  contours(gid, depth = 0) {
    const [o, len] = this.glyphRange(gid);
    if (!len || depth > 8) return [];
    const nc = this.i16(o);
    if (nc < 0) {
      const out = [];
      let p = o + 10;
      for (;;) {
        const flags = this.u16(p);
        const child = this.u16(p + 2);
        p += 4;
        let dx = 0;
        let dy = 0;
        if (flags & 1) {
          dx = flags & 2 ? this.i16(p) : 0;
          dy = flags & 2 ? this.i16(p + 2) : 0;
          p += 4;
        } else {
          dx = flags & 2 ? (this.view.getInt8(p)) : 0;
          dy = flags & 2 ? (this.view.getInt8(p + 1)) : 0;
          p += 2;
        }
        let [a, b, c, d] = [1, 0, 0, 1];
        const f2 = (q) => this.i16(q) / 16384;
        if (flags & 8) {
          a = d = f2(p);
          p += 2;
        } else if (flags & 0x40) {
          a = f2(p);
          d = f2(p + 2);
          p += 4;
        } else if (flags & 0x80) {
          a = f2(p);
          b = f2(p + 2);
          c = f2(p + 4);
          d = f2(p + 6);
          p += 8;
        }
        for (const contour of this.contours(child, depth + 1)) out.push(contour.map((pt) => ({ x: a * pt.x + c * pt.y + dx, y: b * pt.x + d * pt.y + dy, on: pt.on })));
        if (!(flags & 0x20)) break;
      }
      return out;
    }
    const endPts = [];
    for (let i = 0; i < nc; i++) endPts.push(this.u16(o + 10 + i * 2));
    const nPts = nc ? endPts[nc - 1] + 1 : 0;
    let p = o + 10 + nc * 2;
    p += 2 + this.u16(p);
    const flags = [];
    while (flags.length < nPts) {
      const f = this.u8(p++);
      flags.push(f);
      if (f & 8) {
        const r = this.u8(p++);
        for (let k = 0; k < r; k++) flags.push(f);
      }
    }
    const coords = (short, same) => {
      const out = [];
      let v = 0;
      for (const f of flags) {
        if (f & short) {
          const d = this.u8(p++);
          v += f & same ? d : -d;
        } else if (!(f & same)) {
          v += this.i16(p);
          p += 2;
        }
        out.push(v);
      }
      return out;
    };
    const xs = coords(2, 16);
    const ys = coords(4, 32);
    const out = [];
    let start = 0;
    for (const end of endPts) {
      const c = [];
      for (let i = start; i <= end; i++) c.push({ x: xs[i], y: ys[i], on: Boolean(flags[i] & 1) });
      out.push(c);
      start = end + 1;
    }
    return out;
  }

  /** SVG path data for a glyph in font units, y up (flip when drawing). */
  svgPath(gid, ox = 0, oy = 0, scale = 1) {
    const T = (pt) => `${((ox + pt.x) * scale).toFixed(2)} ${(-(oy + pt.y) * scale).toFixed(2)}`;
    let d = "";
    for (const c of this.contours(gid)) {
      if (!c.length) continue;
      const pts = c.slice();
      let startIdx = pts.findIndex((q) => q.on);
      let first;
      if (startIdx < 0) {
        first = { x: (pts[0].x + pts[1 % pts.length].x) / 2, y: (pts[0].y + pts[1 % pts.length].y) / 2, on: true };
        startIdx = 0;
      } else first = pts[startIdx];
      d += `M${T(first)}`;
      const n = pts.length;
      let prevOff = null;
      for (let k = 1; k <= n; k++) {
        const pt = k === n && startIdx >= 0 && pts[startIdx] === first ? first : pts[(startIdx + k) % n];
        if (pt.on) {
          d += prevOff ? `Q${T(prevOff)} ${T(pt)}` : `L${T(pt)}`;
          prevOff = null;
        } else {
          if (prevOff) {
            const mid = { x: (prevOff.x + pt.x) / 2, y: (prevOff.y + pt.y) / 2 };
            d += `Q${T(prevOff)} ${T(mid)}`;
          }
          prevOff = pt;
        }
      }
      if (prevOff) d += `Q${T(prevOff)} ${T(first)}`;
      d += "Z";
    }
    return d;
  }

  // ───────────── OpenType layout ─────────────

  coverage(o) {
    this._cov ??= new Map();
    let cached = this._cov.get(o);
    if (!cached) this._cov.set(o, (cached = this.readCoverage(o)));
    return cached;
  }

  readCoverage(o) {
    const fmt = this.u16(o);
    const map = new Map();
    if (fmt === 1) {
      const n = this.u16(o + 2);
      for (let i = 0; i < n; i++) map.set(this.u16(o + 4 + i * 2), i);
    } else if (fmt === 2) {
      const n = this.u16(o + 2);
      for (let i = 0; i < n; i++) {
        const r = o + 4 + i * 6;
        const start = this.u16(r);
        const end = this.u16(r + 2);
        const idx = this.u16(r + 4);
        for (let g = start; g <= end; g++) map.set(g, idx + g - start);
      }
    }
    return map;
  }

  classDef(o) {
    this._cls ??= new Map();
    let cached = this._cls.get(o);
    if (!cached) this._cls.set(o, (cached = this.readClassDef(o)));
    return cached;
  }

  readClassDef(o) {
    const fmt = this.u16(o);
    const map = new Map();
    if (fmt === 1) {
      const start = this.u16(o + 2);
      const n = this.u16(o + 4);
      for (let i = 0; i < n; i++) map.set(start + i, this.u16(o + 6 + i * 2));
    } else if (fmt === 2) {
      const n = this.u16(o + 2);
      for (let i = 0; i < n; i++) {
        const r = o + 4 + i * 6;
        const c = this.u16(r + 4);
        for (let g = this.u16(r); g <= this.u16(r + 2); g++) map.set(g, c);
      }
    }
    return (g) => map.get(g) || 0;
  }

  /** GDEF: glyph classes (1 base, 2 ligature, 3 mark, 4 component), mark attachment classes, mark sets. */
  get gdef() {
    if (this._layout.gdef !== undefined) return this._layout.gdef;
    const t = this.tables.GDEF;
    if (!t) return (this._layout.gdef = null);
    const o = t.offset;
    const off = (p) => this.u16(o + p);
    const gdef = {
      glyphClass: off(4) ? this.classDef(o + off(4)) : () => 0,
      markAttachClass: off(10) ? this.classDef(o + off(10)) : () => 0,
      markSets: [],
    };
    if (this.u32(o) >= 0x00010002 && off(12)) {
      const ms = o + off(12);
      const n = this.u16(ms + 2);
      for (let i = 0; i < n; i++) gdef.markSets.push(this.coverage(ms + this.u32(ms + 4 + i * 4)));
    }
    return (this._layout.gdef = gdef);
  }

  /** Parsed GSUB/GPOS header: script → langsys features, features, lookups (lazy). */
  layout(tag) {
    if (this._layout[tag] !== undefined) return this._layout[tag];
    const t = this.tables[tag];
    if (!t) return (this._layout[tag] = null);
    const o = t.offset;
    const scriptList = o + this.u16(o + 4);
    const featureList = o + this.u16(o + 6);
    const lookupList = o + this.u16(o + 8);
    const scripts = {};
    for (let i = 0, n = this.u16(scriptList); i < n; i++) {
      const r = scriptList + 2 + i * 6;
      const s = scriptList + this.u16(r + 4);
      const langSys = (p) => {
        const req = this.u16(p + 2);
        const cnt = this.u16(p + 4);
        const idx = [];
        for (let k = 0; k < cnt; k++) idx.push(this.u16(p + 6 + k * 2));
        if (req !== 0xffff) idx.unshift(req);
        return idx;
      };
      const def = this.u16(s) ? langSys(s + this.u16(s)) : null;
      const langs = {};
      for (let k = 0, m = this.u16(s + 2); k < m; k++) langs[tagAt(this.view, s + 4 + k * 6)] = langSys(s + this.u16(s + 8 + k * 6));
      scripts[tagAt(this.view, r)] = { default: def, langs };
    }
    const features = [];
    for (let i = 0, n = this.u16(featureList); i < n; i++) {
      const r = featureList + 2 + i * 6;
      const f = featureList + this.u16(r + 4);
      const lookups = [];
      for (let k = 0, m = this.u16(f + 2); k < m; k++) lookups.push(this.u16(f + 4 + k * 2));
      features.push({ tag: tagAt(this.view, r), lookups });
    }
    const lookups = [];
    for (let i = 0, n = this.u16(lookupList); i < n; i++) {
      const l = lookupList + this.u16(lookupList + 2 + i * 2);
      const type = this.u16(l);
      const flag = this.u16(l + 2);
      const subs = [];
      const cnt = this.u16(l + 4);
      for (let k = 0; k < cnt; k++) subs.push(l + this.u16(l + 6 + k * 2));
      const markSet = flag & 0x10 ? this.u16(l + 6 + cnt * 2) : null;
      lookups.push({ type, flag, subs, markSet });
    }
    return (this._layout[tag] = { scripts, features, lookups });
  }

  /** Lookup indices for the given feature tags under a script (first match in scriptTags). */
  lookupsFor(tag, scriptTags, featureTags) {
    const lay = this.layout(tag);
    if (!lay) return [];
    const script = scriptTags.map((s) => lay.scripts[s]).find(Boolean) || lay.scripts.DFLT || lay.scripts.latn;
    if (!script?.default) return [];
    const wanted = new Set(featureTags);
    const out = [];
    for (const fi of script.default) {
      const f = lay.features[fi];
      if (f && wanted.has(f.tag)) for (const li of f.lookups) out.push({ index: li, feature: f.tag });
    }
    return out.sort((a, b) => a.index - b.index);
  }

  /** Script tags available in GSUB. */
  scriptTags(tag = "GSUB") {
    return Object.keys(this.layout(tag)?.scripts || {});
  }
}

/**
 * Build a compact TrueType font containing only `glyphIds` (glyph 0 is always
 * kept). Returns { bytes, newId: Map(oldGid → newGid) }. Composite glyphs keep
 * their components. Hinting programs are kept; layout tables are dropped.
 */
export function subsetFont(font, glyphIds, { codePoints = null } = {}) {
  const keep = new Set([0, ...glyphIds]);
  const cmapEntries = [];
  if (codePoints) {
    for (const cp of codePoints) {
      const g = font.glyphForCodePoint(cp);
      if (g) {
        keep.add(g);
        cmapEntries.push([cp, g]);
      }
    }
  }
  const queue = [...keep];
  while (queue.length) {
    for (const c of font.components(queue.pop())) {
      if (!keep.has(c.gid)) {
        keep.add(c.gid);
        queue.push(c.gid);
      }
    }
  }
  const order = [...keep].sort((a, b) => a - b);
  const newId = new Map(order.map((g, i) => [g, i]));
  const glyfParts = [];
  const loca = [0];
  let glyfLen = 0;
  for (const g of order) {
    const [o, len] = font.glyphRange(g);
    const copy = new Uint8Array(font.bytes.subarray(o, o + len));
    if (len && font.i16(o) < 0) {
      const dv = new DataView(copy.buffer);
      for (const c of font.components(g)) dv.setUint16(c.at, newId.get(c.gid));
    }
    glyfParts.push(copy);
    glyfLen += len;
    const pad = (4 - (glyfLen % 4)) % 4;
    if (pad) {
      glyfParts.push(new Uint8Array(pad));
      glyfLen += pad;
    }
    loca.push(glyfLen);
  }
  const glyf = concat(glyfParts);
  const locaBytes = new Uint8Array(loca.length * 4);
  const lv = new DataView(locaBytes.buffer);
  loca.forEach((v, i) => lv.setUint32(i * 4, v));
  const hmtx = new Uint8Array(order.length * 4);
  const hv = new DataView(hmtx.buffer);
  order.forEach((g, i) => {
    hv.setUint16(i * 4, font.advance(g));
    hv.setInt16(i * 4 + 2, font.leftSideBearing(g));
  });
  const copyTable = (tag) => (font.tables[tag] ? new Uint8Array(font.bytes.subarray(font.tables[tag].offset, font.tables[tag].offset + font.tables[tag].length)) : null);
  const head = copyTable("head");
  const hd = new DataView(head.buffer);
  hd.setUint32(8, 0); // checkSumAdjustment, recomputed below
  hd.setInt16(50, 1); // long loca offsets
  const hhea = copyTable("hhea");
  new DataView(hhea.buffer).setUint16(34, order.length);
  const maxp = copyTable("maxp");
  new DataView(maxp.buffer).setUint16(4, order.length);
  // Minimal post table (format 3: no glyph names).
  const postSrc = copyTable("post");
  const post = new Uint8Array(32);
  if (postSrc) post.set(postSrc.subarray(0, 32));
  new DataView(post.buffer).setUint32(0, 0x00030000);
  const tables = { head, hhea, maxp, hmtx, loca: locaBytes, glyf, post };
  for (const t of ["cvt ", "fpgm", "prep", "OS/2", "name"]) {
    const b = copyTable(t);
    if (b) tables[t] = b;
  }
  if (codePoints) tables.cmap = cmapFormat12(cmapEntries.map(([cp, g]) => [cp, newId.get(g)]));
  const bytes = writeFont(tables);
  return { bytes, newId };
}

/** A cmap table with a single (3,10) format-12 subtable. */
function cmapFormat12(entries) {
  entries.sort((a, b) => a[0] - b[0]);
  const groups = [];
  for (const [cp, g] of entries) {
    const last = groups[groups.length - 1];
    if (last && cp === last[1] + 1 && g === last[2] + (cp - last[0])) last[1] = cp;
    else groups.push([cp, cp, g]);
  }
  const out = new Uint8Array(12 + 16 + groups.length * 12);
  const v = new DataView(out.buffer);
  v.setUint16(2, 1);
  v.setUint16(4, 3);
  v.setUint16(6, 10);
  v.setUint32(8, 12);
  v.setUint16(12, 12);
  v.setUint32(16, 16 + groups.length * 12);
  v.setUint32(24, groups.length);
  groups.forEach(([a, b, g], i) => {
    v.setUint32(28 + i * 12, a);
    v.setUint32(32 + i * 12, b);
    v.setUint32(36 + i * 12, g);
  });
  return out;
}

function concat(parts) {
  const len = parts.reduce((s, p) => s + p.length, 0);
  const out = new Uint8Array(len);
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

function checksum(bytes) {
  const padded = bytes.length % 4 ? concat([bytes, new Uint8Array(4 - (bytes.length % 4))]) : bytes;
  const v = new DataView(padded.buffer, padded.byteOffset, padded.byteLength);
  let sum = 0;
  for (let i = 0; i < padded.length; i += 4) sum = (sum + v.getUint32(i)) >>> 0;
  return sum;
}

function writeFont(tables) {
  const tags = Object.keys(tables).sort();
  const n = tags.length;
  let es = 0;
  while (1 << (es + 1) <= n) es++;
  const header = new Uint8Array(12 + n * 16);
  const hv = new DataView(header.buffer);
  hv.setUint32(0, 0x00010000);
  hv.setUint16(4, n);
  hv.setUint16(6, (1 << es) * 16);
  hv.setUint16(8, es);
  hv.setUint16(10, n * 16 - (1 << es) * 16);
  const parts = [header];
  let offset = header.length;
  tags.forEach((tag, i) => {
    const data = tables[tag];
    const r = 12 + i * 16;
    for (let k = 0; k < 4; k++) hv.setUint8(r + k, tag.charCodeAt(k));
    hv.setUint32(r + 4, checksum(data));
    hv.setUint32(r + 8, offset);
    hv.setUint32(r + 12, data.length);
    parts.push(data);
    const pad = (4 - (data.length % 4)) % 4;
    if (pad) parts.push(new Uint8Array(pad));
    offset += data.length + pad;
  });
  const out = concat(parts);
  const headIdx = tags.indexOf("head");
  const headOff = hv.getUint32(12 + headIdx * 16 + 8);
  new DataView(out.buffer).setUint32(headOff + 8, (0xb1b0afba - checksum(out)) >>> 0);
  return out;
}
