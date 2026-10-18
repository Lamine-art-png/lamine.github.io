// OpenType text shaping for certificate names: script itemization, bidi
// reordering, and GSUB/GPOS application with Arabic joining and the Indic
// syllable model (following the OpenType script development specs and the
// behaviour of HarfBuzz). Produces positioned glyphs for the PDF writer.
import { scriptOf, bidiClass, isMark, mirrored, joiningType, RTL_SCRIPTS, INDIC_SCRIPTS, indicInfo, POS, SPLIT_MATRAS } from "./unicode-data.js";

// ───────────── Lookup engine ─────────────

const GLOBAL = 1;

class Shaper {
  constructor(font, buf, { script, manualJoiners = false, perSyllable = false } = {}) {
    this.font = font;
    this.buf = buf;
    this.script = script;
    this.scriptTags = scriptTagsFor(script, font);
    this.gdef = font.gdef;
    this.manualJoiners = manualJoiners;
    this.perSyllable = perSyllable;
  }

  glyphClass(g) {
    return this.gdef ? this.gdef.glyphClass(g.gid) : isMark(g.cp) ? 3 : 1;
  }

  /** Whether glyph g is skipped under a lookup's flags. */
  ignored(g, lookup, context = false) {
    // Positioning always looks through joiners; substitution only when not manual.
    if (this.table === "GPOS" && (g.cp === 0x200c || g.cp === 0x200d)) return true;
    if (!this.manualJoiners) {
      if (g.cp === 0x200d) return true;
      if (g.cp === 0x200c && context) return true;
    }
    const flag = lookup.flag;
    const cls = this.glyphClass(g);
    if (cls === 1 && flag & 2) return true;
    if (cls === 2 && flag & 4) return true;
    if (cls === 3) {
      if (flag & 8) return true;
      if (flag & 0x10 && lookup.markSet != null) return !this.gdef?.markSets[lookup.markSet]?.has(g.gid);
      if (flag & 0xff00 && this.gdef) return this.gdef.markAttachClass(g.gid) !== flag >> 8;
    }
    return false;
  }

  sameSyllable(a, b) {
    return !this.perSyllable || this.buf[a].syllable === this.buf[b].syllable;
  }

  next(i, lookup, context = false, limit = this.buf.length) {
    for (let j = i + 1; j < limit; j++) {
      if (!this.sameSyllable(i, j)) return -1;
      if (!this.ignored(this.buf[j], lookup, context)) return j;
    }
    return -1;
  }

  prev(i, lookup, context = false) {
    for (let j = i - 1; j >= 0; j--) {
      if (!this.sameSyllable(i, j)) return -1;
      if (!this.ignored(this.buf[j], lookup, context)) return j;
    }
    return -1;
  }

  /** Apply the given lookups (sorted by index) for one stage. table: "GSUB" | "GPOS". */
  applyStage(table, lookups) {
    const lay = this.font.layout(table);
    if (!lay) return;
    this.table = table;
    for (const { index, mask } of lookups) {
      const lookup = lay.lookups[index];
      if (!lookup) continue;
      if (table === "GSUB" && resolveType(this.font, lookup, "GSUB").type === 8) {
        for (let i = this.buf.length - 1; i >= 0; i--) if (this.buf[i].mask & mask && !this.ignored(this.buf[i], lookup)) this.applyAt(table, lookup, i);
        continue;
      }
      for (let i = 0; i < this.buf.length; ) {
        if (this.buf[i].mask & mask && !this.ignored(this.buf[i], lookup)) {
          const r = this.applyAt(table, lookup, i);
          i = r > i ? r : i + 1;
        } else i++;
      }
    }
  }

  /** Try each subtable at position i. Returns the next position, or -1 when nothing applied. */
  applyAt(table, lookup, i) {
    for (const sub of lookup.subs) {
      const { type, offset } = resolveSub(this.font, lookup.type, sub, table);
      const r = table === "GSUB" ? this.gsub(type, offset, lookup, i) : this.gpos(type, offset, lookup, i);
      if (r >= 0) return r;
    }
    return -1;
  }

  // ── GSUB ──
  gsub(type, o, lookup, i) {
    const f = this.font;
    const g = this.buf[i];
    switch (type) {
      case 1: {
        const fmt = f.u16(o);
        const idx = f.coverage(o + f.u16(o + 2)).get(g.gid);
        if (idx === undefined) return -1;
        g.gid = fmt === 1 ? (g.gid + f.i16(o + 4)) & 0xffff : f.u16(o + 6 + idx * 2);
        g.substituted = true;
        return i + 1;
      }
      case 2: {
        const idx = f.coverage(o + f.u16(o + 2)).get(g.gid);
        if (idx === undefined) return -1;
        const seq = o + f.u16(o + 6 + idx * 2);
        const n = f.u16(seq);
        const out = [];
        for (let k = 0; k < n; k++) out.push({ ...g, gid: f.u16(seq + 2 + k * 2), substituted: true, multiplied: n > 1, ligated: false, component: k });
        this.buf.splice(i, 1, ...out);
        return i + n;
      }
      case 3: {
        const idx = f.coverage(o + f.u16(o + 2)).get(g.gid);
        if (idx === undefined) return -1;
        const set = o + f.u16(o + 6 + idx * 2);
        if (f.u16(set) > 0) {
          g.gid = f.u16(set + 2);
          g.substituted = true;
        }
        return i + 1;
      }
      case 4: {
        const idx = f.coverage(o + f.u16(o + 2)).get(g.gid);
        if (idx === undefined) return -1;
        const set = o + f.u16(o + 6 + idx * 2);
        for (let k = 0, n = f.u16(set); k < n; k++) {
          const lig = set + f.u16(set + 2 + k * 2);
          const comps = f.u16(lig + 2);
          const positions = [i];
          let ok = true;
          for (let c = 1; c < comps; c++) {
            const j = this.next(positions[positions.length - 1], lookup);
            if (j < 0 || this.buf[j].gid !== f.u16(lig + 4 + (c - 1) * 2)) {
              ok = false;
              break;
            }
            positions.push(j);
          }
          if (!ok) continue;
          this.ligCounter = (this.ligCounter || 0) + 1;
          const ligId = this.ligCounter;
          g.gid = f.u16(lig);
          g.substituted = true;
          g.ligated = comps > 1;
          g.multiplied = false;
          g.ligId = ligId;
          g.text = positions.map((p) => this.buf[p].text).join("");
          g.cluster = Math.min(...positions.map((p) => this.buf[p].cluster));
          // Marks between components remember which component they belong to.
          for (let c = 0; c < positions.length - 1; c++)
            for (let m = positions[c] + 1; m < positions[c + 1]; m++) {
              this.buf[m].ligId = ligId;
              this.buf[m].ligComp = c + 1;
            }
          for (let c = positions.length - 1; c >= 1; c--) this.buf.splice(positions[c], 1);
          return i + 1;
        }
        return -1;
      }
      case 5:
      case 6:
        return this.contextual(type, o, lookup, i, "GSUB");
      case 8: {
        const cov = f.coverage(o + f.u16(o + 2));
        const idx = cov.get(g.gid);
        if (idx === undefined) return -1;
        let p = o + 4;
        const bt = f.u16(p);
        let pos = i;
        for (let k = 0; k < bt; k++) {
          pos = this.prev(pos, lookup, true);
          if (pos < 0 || !f.coverage(o + f.u16(p + 2 + k * 2)).has(this.buf[pos].gid)) return -1;
        }
        p += 2 + bt * 2;
        const la = f.u16(p);
        pos = i;
        for (let k = 0; k < la; k++) {
          pos = this.next(pos, lookup, true);
          if (pos < 0 || !f.coverage(o + f.u16(p + 2 + k * 2)).has(this.buf[pos].gid)) return -1;
        }
        p += 2 + la * 2;
        g.gid = f.u16(p + 2 + idx * 2);
        g.substituted = true;
        return i + 1;
      }
      default:
        return -1;
    }
  }

  /** Context (5/7) and chained context (6/8) lookups for GSUB and GPOS. */
  contextual(type, o, lookup, i, table) {
    const chained = (table === "GSUB" && type === 6) || (table === "GPOS" && type === 8);
    const ctx = parseContext(this.font, o, chained);
    const gid = this.buf[i].gid;
    if (ctx.fmt === 3) {
      if (!ctx.input[0].has(gid)) return -1;
      return this.tryRule(ctx.rule, lookup, i, table, (g, cov) => cov.has(g));
    }
    if (!ctx.coverage.has(gid)) return -1;
    const set = ctx.fmt === 1 ? ctx.sets[ctx.coverage.get(gid)] : ctx.sets[ctx.inputClass(gid)];
    if (!set) return -1;
    for (const rule of set) {
      const r = this.tryRule(rule, lookup, i, table, ctx.test);
      if (r >= 0) return r;
    }
    return -1;
  }

  /** Match one rule's input, backtrack and lookahead at i; apply its records. */
  tryRule(rule, lookup, i, table, test) {
    const pos = [i];
    let p = i;
    for (let k = rule.inputStart; k < rule.input.length; k++) {
      p = this.next(p, lookup, false);
      if (p < 0 || !test(this.buf[p].gid, rule.input[k], "input")) return -1;
      pos.push(p);
    }
    p = i;
    for (const it of rule.back) {
      p = this.prev(p, lookup, true);
      if (p < 0 || !test(this.buf[p].gid, it, "back")) return -1;
    }
    p = pos[pos.length - 1];
    for (const it of rule.ahead) {
      p = this.next(p, lookup, true);
      if (p < 0 || !test(this.buf[p].gid, it, "ahead")) return -1;
    }
    return this.applyRecords(rule.records, pos, table);
  }

  /** Apply nested lookups at matched positions, keeping later positions in step with buffer edits. */
  applyRecords(records, positions, table) {
    const lay = this.font.layout(table);
    const pos = positions.slice();
    let end = pos[pos.length - 1] + 1;
    for (const rec of records) {
      if (rec.seq >= pos.length) continue;
      const at = pos[rec.seq];
      const before = this.buf.length;
      const lookup = lay.lookups[rec.lookup];
      if (!lookup || at >= this.buf.length) continue;
      if (this.ignored(this.buf[at], lookup)) continue;
      this.applyAt(table, lookup, at);
      const delta = this.buf.length - before;
      if (delta) {
        end += delta;
        for (let k = rec.seq + 1; k < pos.length; k++) pos[k] += delta;
        if (delta < 0) {
          // A ligature consumed following input glyphs; drop their positions.
          const removed = -delta;
          pos.splice(rec.seq + 1, Math.min(removed, pos.length - rec.seq - 1));
          for (let k = rec.seq + 1; k < pos.length; k++) pos[k] = Math.max(pos[k], at + 1);
        } else {
          // A multiple substitution inserted glyphs after `at`.
          const extra = [];
          for (let k = 1; k <= delta; k++) extra.push(at + k);
          pos.splice(rec.seq + 1, 0, ...extra);
        }
      }
    }
    return Math.max(end, positions[0] + 1);
  }

  // ── GPOS ──
  valueRecord(p, fmt) {
    const f = this.font;
    const v = { xp: 0, yp: 0, xa: 0, ya: 0 };
    let q = p;
    if (fmt & 1) (v.xp = f.i16(q)), (q += 2);
    if (fmt & 2) (v.yp = f.i16(q)), (q += 2);
    if (fmt & 4) (v.xa = f.i16(q)), (q += 2);
    if (fmt & 8) (v.ya = f.i16(q)), (q += 2);
    for (const bit of [0x10, 0x20, 0x40, 0x80]) if (fmt & bit) q += 2;
    return { v, size: q - p };
  }

  applyValue(g, v) {
    g.xOff += v.xp;
    g.yOff += v.yp;
    g.xAdv += v.xa;
  }

  anchor(p) {
    return { x: this.font.i16(p + 2), y: this.font.i16(p + 4) };
  }

  gpos(type, o, lookup, i) {
    const f = this.font;
    const g = this.buf[i];
    switch (type) {
      case 1: {
        const fmt = f.u16(o);
        const idx = f.coverage(o + f.u16(o + 2)).get(g.gid);
        if (idx === undefined) return -1;
        const vf = f.u16(o + 4);
        const size = this.valueRecord(o + 6, vf).size;
        this.applyValue(g, this.valueRecord(fmt === 1 ? o + 6 : o + 8 + idx * size, vf).v);
        return i + 1;
      }
      case 2: {
        const fmt = f.u16(o);
        const idx = f.coverage(o + f.u16(o + 2)).get(g.gid);
        if (idx === undefined) return -1;
        const j = this.next(i, lookup);
        if (j < 0) return -1;
        const g2 = this.buf[j];
        const vf1 = f.u16(o + 4);
        const vf2 = f.u16(o + 6);
        const s1 = this.valueRecord(0, vf1).size;
        const s2 = this.valueRecord(0, vf2).size;
        if (fmt === 1) {
          const set = o + f.u16(o + 10 + idx * 2);
          for (let k = 0, n = f.u16(set); k < n; k++) {
            const r = set + 2 + k * (2 + s1 + s2);
            if (f.u16(r) === g2.gid) {
              this.applyValue(g, this.valueRecord(r + 2, vf1).v);
              this.applyValue(g2, this.valueRecord(r + 2 + s1, vf2).v);
              return vf2 ? j + 1 : j;
            }
          }
          return -1;
        }
        const c1 = f.classDef(o + f.u16(o + 8))(g.gid);
        const c2 = f.classDef(o + f.u16(o + 10))(g2.gid);
        const n1 = f.u16(o + 12);
        const n2 = f.u16(o + 14);
        if (c1 >= n1 || c2 >= n2) return -1;
        const r = o + 16 + (c1 * n2 + c2) * (s1 + s2);
        this.applyValue(g, this.valueRecord(r, vf1).v);
        this.applyValue(g2, this.valueRecord(r + s1, vf2).v);
        return vf2 ? j + 1 : j;
      }
      case 3: {
        // Cursive attachment: connect this glyph's exit to the next glyph's entry.
        const cov = f.coverage(o + f.u16(o + 2));
        const idx = cov.get(g.gid);
        if (idx === undefined) return -1;
        const exitOff = f.u16(o + 6 + idx * 4 + 2);
        if (!exitOff) return -1;
        const j = this.next(i, lookup);
        if (j < 0) return -1;
        const jdx = cov.get(this.buf[j].gid);
        if (jdx === undefined) return -1;
        const entryOff = f.u16(o + 6 + jdx * 4);
        if (!entryOff) return -1;
        const exit = this.anchor(o + exitOff);
        const entry = this.anchor(o + entryOff);
        this.buf[j].yOff += exit.y - entry.y + g.yOff;
        return i + 1;
      }
      case 4:
      case 5:
      case 6: {
        const markCov = f.coverage(o + f.u16(o + 2));
        const mIdx = markCov.get(g.gid);
        if (mIdx === undefined) return -1;
        const classCount = f.u16(o + 6);
        const markArray = o + f.u16(o + 8);
        const baseArray = o + f.u16(o + 10);
        const mr = markArray + 2 + mIdx * 4;
        const markClass = f.u16(mr);
        const markAnchor = this.anchor(markArray + f.u16(mr + 2));
        // Find the attachment target.
        let j = i - 1;
        if (type === 6) {
          while (j >= 0 && this.ignoredForMark(this.buf[j], lookup)) j--;
          if (j < 0 || this.glyphClass(this.buf[j]) !== 3) return -1;
          const same = (this.buf[j].ligId || 0) === (g.ligId || 0) && (this.buf[j].ligComp || 0) === (g.ligComp || 0);
          if (!same && this.buf[j].ligId !== g.ligId) return -1;
        } else {
          while (j >= 0 && this.glyphClass(this.buf[j]) === 3) j--;
          if (j < 0) return -1;
        }
        const target = this.buf[j];
        const baseIdx = f.coverage(o + f.u16(o + 4)).get(target.gid);
        if (baseIdx === undefined) return -1;
        let anchorOff;
        if (type === 5) {
          const lig = baseArray + f.u16(baseArray + 2 + baseIdx * 2);
          const comps = f.u16(lig);
          if (!comps) return -1;
          const comp = g.ligId && g.ligId === target.ligId && g.ligComp ? Math.min(g.ligComp, comps) - 1 : comps - 1;
          anchorOff = f.u16(lig + 2 + (comp * classCount + markClass) * 2);
          if (!anchorOff) return -1;
          anchorOff += lig;
        } else {
          const rec = baseArray + 2 + (baseIdx * classCount + markClass) * 2;
          anchorOff = f.u16(rec);
          if (!anchorOff) return -1;
          anchorOff += baseArray;
        }
        const a = this.anchor(anchorOff);
        g.attach = { to: j, dx: a.x - markAnchor.x, dy: a.y - markAnchor.y };
        return i + 1;
      }
      case 7:
      case 8:
        return this.contextual(type, o, lookup, i, "GPOS");
      default:
        return -1;
    }
  }

  ignoredForMark(g, lookup) {
    return this.ignored(g, { ...lookup, flag: lookup.flag & ~8 });
  }

  /** Whether `feature` has a lookup that would substitute exactly this glyph sequence. */
  wouldSubstitute(feature, gids) {
    const cache = (this.font._would ??= new Map());
    const key = `${this.scriptTags[0]}|${feature}|${gids.join(",")}`;
    if (!cache.has(key)) cache.set(key, this.computeWouldSubstitute(feature, gids));
    return cache.get(key);
  }

  computeWouldSubstitute(feature, gids) {
    const lay = this.font.layout("GSUB");
    if (!lay) return false;
    for (const { index } of this.font.lookupsFor("GSUB", this.scriptTags, [feature])) {
      const lookup = lay.lookups[index];
      for (const sub of lookup.subs) {
        const { type, offset: o } = resolveSub(this.font, lookup.type, sub, "GSUB");
        const f = this.font;
        if (type === 1 && gids.length === 1 && f.coverage(o + f.u16(o + 2)).has(gids[0])) return true;
        if (type === 4) {
          const idx = f.coverage(o + f.u16(o + 2)).get(gids[0]);
          if (idx === undefined) continue;
          const set = o + f.u16(o + 6 + idx * 2);
          for (let k = 0, n = f.u16(set); k < n; k++) {
            const lig = set + f.u16(set + 2 + k * 2);
            const comps = f.u16(lig + 2);
            if (comps !== gids.length) continue;
            let ok = true;
            for (let c = 1; c < comps; c++) if (f.u16(lig + 4 + (c - 1) * 2) !== gids[c]) ok = false;
            if (ok) return true;
          }
        }
        if (type === 5 || type === 6) {
          // Try the rule on a scratch buffer of exactly these glyphs.
          const scratch = gids.map((gid, k) => ({ gid, cp: 0, mask: GLOBAL, cluster: k, text: "", syllable: 0, xAdv: 0, xOff: 0, yOff: 0 }));
          const s = new Shaper(this.font, scratch, { script: this.script, manualJoiners: true });
          const before = scratch.map((x) => x.gid).join();
          s.applyAt("GSUB", lookup, 0);
          if (scratch.map((x) => x.gid).join() !== before) return true;
        }
      }
    }
    return false;
  }
}

/** Parse (once per font and offset) a context or chained-context subtable. */
function parseContext(f, o, chained) {
  f._ctx ??= new Map();
  const key = o * 2 + (chained ? 1 : 0);
  let ctx = f._ctx.get(key);
  if (ctx) return ctx;
  const fmt = f.u16(o);
  const list = (p) => {
    const n = f.u16(p);
    const a = [];
    for (let k = 0; k < n; k++) a.push(f.u16(p + 2 + k * 2));
    return a;
  };
  const records = (p, n) => {
    const r = [];
    for (let k = 0; k < n; k++) r.push({ seq: f.u16(p + k * 4), lookup: f.u16(p + k * 4 + 2) });
    return r;
  };
  if (fmt === 3) {
    const cov = (p) => f.coverage(o + f.u16(p));
    let rule;
    let input;
    if (chained) {
      let p = o + 2;
      const back = list(p).map((_, k) => cov(p + 2 + k * 2));
      p += 2 + back.length * 2;
      input = list(p).map((_, k) => cov(p + 2 + k * 2));
      p += 2 + input.length * 2;
      const ahead = list(p).map((_, k) => cov(p + 2 + k * 2));
      p += 2 + ahead.length * 2;
      rule = { back, input, ahead, inputStart: 1, records: records(p + 2, f.u16(p)) };
    } else {
      const ic = f.u16(o + 2);
      input = [];
      for (let k = 0; k < ic; k++) input.push(cov(o + 6 + k * 2));
      rule = { back: [], input, ahead: [], inputStart: 1, records: records(o + 6 + ic * 2, f.u16(o + 4)) };
    }
    ctx = { fmt, input, rule };
  } else {
    const coverage = f.coverage(o + f.u16(o + 2));
    const cls = (p) => (f.u16(p) ? f.classDef(o + f.u16(p)) : () => 0);
    let backCls;
    let inputClass;
    let aheadCls;
    let setsAt;
    if (fmt === 1) setsAt = o + 4;
    else if (chained) {
      backCls = cls(o + 4);
      inputClass = cls(o + 6);
      aheadCls = cls(o + 8);
      setsAt = o + 10;
    } else {
      inputClass = cls(o + 4);
      setsAt = o + 6;
    }
    const sets = list(setsAt).map((off) => {
      if (!off) return null;
      const set = o + off;
      return list(set).map((ro) => {
        const r = set + ro;
        if (chained) {
          const back = list(r);
          const ip = r + 2 + back.length * 2;
          const inCount = f.u16(ip);
          const input = [0];
          for (let q = 0; q < inCount - 1; q++) input.push(f.u16(ip + 2 + q * 2));
          const ap = ip + 2 + (inCount - 1) * 2;
          const ahead = list(ap);
          const rp = ap + 2 + ahead.length * 2;
          return { back, input, ahead, inputStart: 1, records: records(rp + 2, f.u16(rp)) };
        }
        const inCount = f.u16(r);
        const input = [0];
        for (let q = 0; q < inCount - 1; q++) input.push(f.u16(r + 4 + q * 2));
        return { back: [], input, ahead: [], inputStart: 1, records: records(r + 4 + (inCount - 1) * 2, f.u16(r + 2)) };
      });
    });
    const test =
      fmt === 1
        ? (gid, v) => gid === v
        : (gid, v, where) => (where === "back" ? backCls(gid) : where === "ahead" ? aheadCls(gid) : inputClass(gid)) === v;
    ctx = { fmt, coverage, inputClass, sets, test };
  }
  f._ctx.set(key, ctx);
  return ctx;
}

const extCache = new WeakMap();
function resolveSub(font, type, sub, table) {
  const extType = table === "GSUB" ? 7 : 9;
  if (type !== extType) return { type, offset: sub };
  return { type: font.u16(sub + 2), offset: sub + font.u32(sub + 4) };
}
function resolveType(font, lookup, table) {
  let c = extCache.get(lookup);
  if (!c) {
    c = lookup.subs.length ? resolveSub(font, lookup.type, lookup.subs[0], table) : { type: lookup.type };
    extCache.set(lookup, c);
  }
  return c;
}

const SCRIPT_TAGS = {
  deva: ["dev2", "deva"], beng: ["bng2", "beng"], guru: ["gur2", "guru"], gujr: ["gjr2", "gujr"], orya: ["ory2", "orya"], taml: ["tml2", "taml"],
  telu: ["tel2", "telu"], knda: ["knd2", "knda"], mlym: ["mlm2", "mlym"], hani: ["hani"], kana: ["kana", "hani"], hang: ["hang"], zyyy: ["DFLT"],
};
function scriptTagsFor(script, font) {
  const tags = SCRIPT_TAGS[script] || [script];
  return [...tags, "DFLT", "latn"].filter((t, i, a) => a.indexOf(t) === i && (font.layout("GSUB")?.scripts[t] || font.layout("GPOS")?.scripts[t] || t === "DFLT"));
}

/** Build stage lookups: features → [{index, mask}] sorted by lookup index. */
function stageLookups(font, table, tags, features) {
  const byIndex = new Map();
  for (const { tag, mask } of features) {
    for (const { index } of font.lookupsFor(table, tags, [tag])) byIndex.set(index, (byIndex.get(index) || 0) | mask);
  }
  return [...byIndex].sort((a, b) => a[0] - b[0]).map(([index, mask]) => ({ index, mask }));
}

// ───────────── Buffer setup ─────────────

function normalizeForFont(text, font, script) {
  const out = [];
  const chars = [...text.normalize("NFC")];
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    const cp = ch.codePointAt(0);
    // Bengali YYA is a composition exclusion that shapers recompose when the font has it.
    if (cp === 0x09af && chars[i + 1] === "\u09bc" && font.glyphForCodePoint(0x09df)) {
      out.push(0x09df);
      i++;
      continue;
    }
    // Thai/Lao SARA AM: decompose, and move NIKHAHIT before preceding above-base marks.
    if (cp === 0x0e33 || cp === 0x0eb3) {
      const nikhahit = cp - 0x0e33 + 0x0e4d;
      const aa = cp - 0x0e33 + 0x0e32;
      let k = out.length;
      const above = (c) => c === 0x0e31 || (c >= 0x0e34 && c <= 0x0e37) || (c >= 0x0e47 && c <= 0x0e4e) || c === 0x0eb1 || (c >= 0x0eb4 && c <= 0x0eb7) || (c >= 0x0ec8 && c <= 0x0ecd);
      while (k > 0 && above(out[k - 1])) k--;
      out.splice(k, 0, nikhahit);
      out.push(aa);
      continue;
    }
    if (SPLIT_MATRAS[cp]) {
      out.push(...SPLIT_MATRAS[cp]);
      continue;
    }
    if (!font.glyphForCodePoint(cp)) {
      const d = [...ch.normalize("NFD")].map((c) => c.codePointAt(0));
      if (d.length > 1 && d.every((c) => font.glyphForCodePoint(c))) {
        out.push(...d);
        continue;
      }
    }
    out.push(cp);
  }
  return out;
}

function makeBuffer(cps, font, rtl) {
  return cps.map((cp, k) => {
    const c = rtl ? mirrored(cp) : cp;
    return { gid: font.glyphForCodePoint(c), cp, cluster: k, text: String.fromCodePoint(cp), mask: GLOBAL, syllable: 0, xAdv: 0, xOff: 0, yOff: 0, attach: null };
  });
}

// ───────────── Script shapers ─────────────

const ARABIC_FORMS = ["isol", "fina", "fin2", "fin3", "medi", "med2", "init"];

function shapeArabic(font, buf) {
  const s = new Shaper(font, buf, { script: "arab" });
  const tags = s.scriptTags;
  const bits = {};
  ARABIC_FORMS.forEach((f, i) => (bits[f] = 2 << i));
  // Joining analysis (logical order); transparent marks are skipped.
  const types = buf.map((g) => joiningType(g.cp));
  const forms = new Array(buf.length).fill(null);
  let prev = -1;
  for (let i = 0; i < buf.length; i++) {
    const t = types[i];
    if (t === "T") continue;
    const joinsPrev = prev >= 0 && (types[prev] === "D" || types[prev] === "C") && (t === "D" || t === "R" || t === "C");
    if (t === "D" || t === "R") forms[i] = joinsPrev ? "fina" : "isol";
    if (joinsPrev && forms[prev]) forms[prev] = forms[prev] === "isol" ? "init" : forms[prev] === "fina" ? "medi" : forms[prev];
    prev = t === "U" ? -1 : i;
  }
  forms.forEach((form, i) => form && (buf[i].mask |= bits[form]));
  s.applyStage("GSUB", stageLookups(font, "GSUB", tags, [{ tag: "ccmp", mask: GLOBAL }, { tag: "locl", mask: GLOBAL }]));
  for (const f of ARABIC_FORMS) s.applyStage("GSUB", stageLookups(font, "GSUB", tags, [{ tag: f, mask: bits[f] }]));
  s.applyStage("GSUB", stageLookups(font, "GSUB", tags, [{ tag: "rlig", mask: GLOBAL }]));
  s.applyStage("GSUB", stageLookups(font, "GSUB", tags, [{ tag: "rclt", mask: GLOBAL }, { tag: "calt", mask: GLOBAL }]));
  s.applyStage("GSUB", stageLookups(font, "GSUB", tags, ["mset", "liga", "clig"].map((tag) => ({ tag, mask: GLOBAL }))));
  return s;
}

function shapeDefault(font, buf, script, rtl) {
  const s = new Shaper(font, buf, { script });
  const tags = s.scriptTags;
  const dir = rtl ? ["rtla", "rtlm"] : ["ltra", "ltrm"];
  s.applyStage("GSUB", stageLookups(font, "GSUB", tags, [{ tag: "rvrn", mask: GLOBAL }]));
  s.applyStage("GSUB", stageLookups(font, "GSUB", tags, [...dir, "ccmp", "locl", "rlig", "calt", "clig", "liga", "rclt"].map((tag) => ({ tag, mask: GLOBAL }))));
  return s;
}

/** Indic: syllables, initial reordering, basic features, final reordering, presentation features. */
function shapeIndic(font, buf, script) {
  const cfg = INDIC_SCRIPTS[script];
  const s = new Shaper(font, buf, { script, manualJoiners: true, perSyllable: true });
  const tags = s.scriptTags;
  const oldSpec = !/2$/.test(tags[0] || "");
  const F = { rphf: 2, pref: 4, blwf: 8, abvf: 16, half: 32, pstf: 64, init: 128 };
  const viramaGid = font.glyphForCodePoint(cfg.virama);
  for (const g of buf) Object.assign(g, indicInfo(script, g.cp));

  // Consonant positions from the font: below-base / post-base forms.
  const consonantPosition = (g) => {
    if (!viramaGid) return POS.BASE_C;
    const pairs = [[viramaGid, g.gid], [g.gid, viramaGid]];
    for (const p of pairs) if (s.wouldSubstitute("blwf", p)) return POS.BELOW_C;
    for (const p of pairs) if (s.wouldSubstitute("pstf", p)) return POS.POST_C;
    for (const p of pairs) if (s.wouldSubstitute("pref", p)) return POS.POST_C;
    return POS.BASE_C;
  };
  for (const g of buf) if (g.cat === "C" || g.cat === "Ra") g.pos = consonantPosition(g);

  // Syllables.
  const isCons = (g) => ["C", "Ra", "V", "PLACEHOLDER"].includes(g.cat);
  const syllables = [];
  for (let i = 0; i < buf.length; ) {
    const start = i;
    const g = buf[i];
    if (g.cat === "Repha") i++;
    if (i < buf.length && isCons(buf[i])) {
      i++;
      for (;;) {
        // (nukta) (joiner) halant (joiner) consonant …
        while (i < buf.length && buf[i].cat === "N") i++;
        let j = i;
        if (j < buf.length && (buf[j].cat === "ZWJ" || buf[j].cat === "ZWNJ") && buf[j + 1]?.cat === "H") j++;
        if (j < buf.length && buf[j].cat === "H") {
          let k = j + 1;
          if (k < buf.length && (buf[k].cat === "ZWJ" || buf[k].cat === "ZWNJ")) k++;
          if (k < buf.length && (buf[k].cat === "C" || buf[k].cat === "Ra") && buf[k - 1].cat !== "ZWNJ") {
            i = k + 1;
            continue;
          }
          i = k;
          break;
        }
        break;
      }
      // Matras, modifiers.
      for (;;) {
        if (i < buf.length && (buf[i].cat === "ZWJ" || buf[i].cat === "ZWNJ") && buf[i + 1]?.cat === "M") i++;
        if (i < buf.length && buf[i].cat === "M") {
          i++;
          while (i < buf.length && (buf[i].cat === "N" || buf[i].cat === "H")) i++;
          continue;
        }
        break;
      }
      while (i < buf.length && buf[i].cat === "SM") i++;
      syllables.push({ start, end: i, type: "consonant" });
    } else {
      i = Math.max(i, start + 1);
      syllables.push({ start, end: i, type: "other" });
    }
  }
  syllables.forEach((sy, k) => {
    for (let i = sy.start; i < sy.end; i++) buf[i].syllable = k + 1;
  });

  s.applyStage("GSUB", stageLookups(font, "GSUB", tags, [{ tag: "locl", mask: GLOBAL }, { tag: "ccmp", mask: GLOBAL }]));

  // Initial reordering, syllable by syllable (positions recomputed after ccmp).
  const bySyllable = () => {
    const out = [];
    for (let i = 0; i < buf.length; ) {
      let j = i;
      while (j < buf.length && buf[j].syllable === buf[i].syllable) j++;
      out.push([i, j]);
      i = j;
    }
    return out;
  };
  for (const [start, end] of bySyllable()) {
    if (!buf.slice(start, end).some(isCons)) continue;
    let hasReph = false;
    let limit = start;
    const isJoiner = (g) => g && (g.cat === "ZWJ" || g.cat === "ZWNJ");
    if (start + 3 <= end && buf[start].cat === "Ra" && buf[start + 1].cat === "H" && !isJoiner(buf[start + 2]) && s.wouldSubstitute("rphf", [buf[start].gid, buf[start + 1].gid])) {
      hasReph = true;
      limit = start + 2;
      while (limit < end && isJoiner(buf[limit])) limit++;
    } else if (buf[start].cat === "Repha") {
      hasReph = true;
      limit = start + 1;
      while (limit < end && isJoiner(buf[limit])) limit++;
    }
    let base = end;
    let seenBelow = false;
    for (let i = end; i > limit; ) {
      i--;
      const g = buf[i];
      if (isCons(g)) {
        if (g.pos !== POS.BELOW_C && (g.pos !== POS.POST_C || seenBelow)) {
          base = i;
          break;
        }
        if (g.pos === POS.BELOW_C) seenBelow = true;
        base = i;
      } else if (start < i && g.cat === "ZWJ" && buf[i - 1].cat === "H") break;
    }
    if (base === end && hasReph) base = start;
    if (hasReph && base === start && limit - base <= 2) hasReph = false;

    for (let i = start; i < base; i++) buf[i].pos = Math.min(POS.PRE_C, buf[i].pos);
    if (base < end) buf[base].pos = POS.BASE_C;
    if (hasReph) buf[start].pos = POS.RA_TO_BECOME_REPH;

    // Attach halants, nukta, joiners to the preceding character's position.
    let lastPos = POS.START;
    for (let i = start; i < end; i++) {
      const g = buf[i];
      if (["ZWJ", "ZWNJ", "N", "H"].includes(g.cat)) {
        g.pos = lastPos;
        if (g.cat === "H" && g.pos === POS.PRE_M) {
          for (let j = i; j > start; j--)
            if (buf[j - 1].pos !== POS.PRE_M) {
              g.pos = buf[j - 1].pos;
              break;
            }
        }
      } else if (g.pos !== POS.SMVD) lastPos = g.pos;
    }
    // Post-base consonants own everything before them since the last consonant or matra.
    let last = base;
    for (let i = base + 1; i < end; i++) {
      if (isCons(buf[i])) {
        for (let j = last + 1; j < i; j++) if (buf[j].pos < POS.SMVD) buf[j].pos = buf[i].pos;
        last = i;
      } else if (buf[i].cat === "M") last = i;
    }
    // Stable sort by position.
    const seg = buf.slice(start, end).map((g, k) => ({ g, k }));
    seg.sort((a, b) => a.g.pos - b.g.pos || a.k - b.k);
    seg.forEach((x, k) => (buf[start + k] = x.g));
    base = end;
    for (let i = start; i < end; i++)
      if (buf[i].pos === POS.BASE_C) {
        base = i;
        break;
      }
    // Masks.
    for (let i = start; i < end && buf[i].pos === POS.RA_TO_BECOME_REPH; i++) buf[i].mask |= F.rphf;
    const preMask = F.half | (!oldSpec && !cfg.blwfPostOnly ? F.blwf : 0);
    for (let i = start; i < base; i++) buf[i].mask |= preMask;
    for (let i = base + 1; i < end; i++) buf[i].mask |= F.blwf | F.abvf | F.pstf;
    if (base + 2 < end) {
      for (let i = base + 1; i + 1 < end; i++)
        if (s.wouldSubstitute("pref", [buf[i].gid, buf[i + 1].gid])) {
          buf[i].mask |= F.pref;
          buf[i + 1].mask |= F.pref;
          break;
        }
    }
    // ZWNJ disables half forms.
    for (let i = base + 1; i < end; i++)
      if (buf[i].cat === "ZWNJ") for (let j = i - 1; j >= start; j--) {
        buf[j].mask &= ~F.half;
        if (isCons(buf[j])) break;
      }
  }

  // Basic shaping features, each its own stage.
  for (const [tag, mask] of [["nukt", GLOBAL], ["akhn", GLOBAL], ["rphf", F.rphf], ["rkrf", GLOBAL], ["pref", F.pref], ["blwf", F.blwf], ["abvf", F.abvf], ["half", F.half], ["pstf", F.pstf], ["vatu", GLOBAL], ["cjct", GLOBAL]]) {
    s.applyStage("GSUB", stageLookups(font, "GSUB", tags, [{ tag, mask }]));
  }

  // Final reordering.
  const isHalant = (g) => g.cat === "H" || (g.gid === viramaGid && g.ligated && g.multiplied);
  for (const [start, end] of bySyllable()) {
    if (!buf.slice(start, end).some(isCons)) continue;
    let tryPref = buf.slice(start, end).some((g) => g.mask & F.pref);
    let base = start;
    for (; base < end; base++) {
      if (buf[base].pos >= POS.BASE_C) {
        if (tryPref && base + 1 < end) {
          for (let i = base + 1; i < end; i++)
            if (buf[i].mask & F.pref) {
              if (!(buf[i].substituted && buf[i].ligated && !buf[i].multiplied)) {
                base = i;
                while (base < end && isHalant(buf[base])) base++;
                if (base < end) buf[base].pos = POS.BASE_C;
                tryPref = false;
              }
              break;
            }
        }
        if (script === "mlym") {
          for (let i = base + 1; i < end; i++) {
            while (i < end && (buf[i].cat === "ZWJ" || buf[i].cat === "ZWNJ")) i++;
            if (i === end || !isHalant(buf[i])) break;
            i++;
            while (i < end && (buf[i].cat === "ZWJ" || buf[i].cat === "ZWNJ")) i++;
            if (i < end && isCons(buf[i]) && buf[i].pos === POS.BELOW_C) {
              base = i;
              buf[base].pos = POS.BASE_C;
            }
          }
        }
        if (start < base && buf[base].pos > POS.BASE_C) base--;
        break;
      }
    }
    if (base === end && start < base && buf[base - 1].cat === "ZWJ") base--;
    if (base < end) while (start < base && (buf[base].cat === "N" || buf[base].cat === "H")) base--;

    // Pre-base matras move closer to the base, after the last standalone halant.
    if (start + 1 < end && start < base) {
      let newPos = base === end ? base - 2 : base - 1;
      if (script !== "mlym" && script !== "taml") {
        for (;;) {
          while (newPos > start && !(buf[newPos].cat === "M" || isHalant(buf[newPos]))) newPos--;
          if (isHalant(buf[newPos]) && buf[newPos].pos !== POS.PRE_M) {
            if (newPos + 1 < end && buf[newPos + 1].cat === "ZWJ" && newPos > start) {
              newPos--;
              continue;
            }
          } else newPos = start;
          break;
        }
      }
      if (start < newPos && buf[newPos].pos !== POS.PRE_M) {
        for (let i = newPos; i > start; i--)
          if (buf[i - 1].pos === POS.PRE_M) {
            const old = i - 1;
            if (old < base && base <= newPos) base--;
            const [m] = buf.splice(old, 1);
            buf.splice(newPos, 0, m);
            newPos--;
          }
      }
    }

    // Reph moves according to the script's reph position.
    if (start + 1 < end && buf[start].pos === POS.RA_TO_BECOME_REPH && (buf[start].cat === "Repha") !== (buf[start].ligated && !buf[start].multiplied)) {
      const rephPos = POS[cfg.rephPos];
      let newReph = -1;
      const step2 = () => {
        let p = start + 1;
        while (p < base && !isHalant(buf[p])) p++;
        if (p < base && isHalant(buf[p])) {
          if (p + 1 < base && (buf[p + 1].cat === "ZWJ" || buf[p + 1].cat === "ZWNJ")) p++;
          return p;
        }
        return -1;
      };
      if (rephPos !== POS.AFTER_POST) newReph = step2();
      if (newReph < 0 && rephPos === POS.AFTER_MAIN) {
        let p = base;
        while (p + 1 < end && buf[p + 1].pos <= POS.AFTER_MAIN) p++;
        if (p < end) newReph = p;
      }
      if (newReph < 0 && rephPos === POS.AFTER_SUB) {
        let p = base;
        while (p + 1 < end && ![POS.POST_C, POS.AFTER_POST, POS.SMVD].includes(buf[p + 1].pos)) p++;
        if (p < end) newReph = p;
      }
      if (newReph < 0) newReph = step2();
      if (newReph < 0) {
        let p = end - 1;
        while (p > start && buf[p].pos === POS.SMVD) p--;
        if (isHalant(buf[p])) for (let i = base + 1; i < p; i++) if (buf[i].cat === "M") p--;
        newReph = p;
      }
      const [reph] = buf.splice(start, 1);
      buf.splice(newReph, 0, reph);
      if (start < base && base <= newReph) base--;
    }

    // Pre-base-reordering consonants.
    if (tryPref && base + 1 < end) {
      for (let i = base + 1; i < end; i++)
        if (buf[i].mask & F.pref) {
          if (buf[i].ligated && !buf[i].multiplied) {
            let newPos = base;
            if (script !== "mlym" && script !== "taml") while (newPos > start && !(buf[newPos - 1].cat === "M" || isHalant(buf[newPos - 1]))) newPos--;
            if (newPos > start && isHalant(buf[newPos - 1]) && newPos < end && (buf[newPos].cat === "ZWJ" || buf[newPos].cat === "ZWNJ")) newPos++;
            const [g] = buf.splice(i, 1);
            buf.splice(newPos, 0, g);
            if (newPos <= base && base < i) base++;
          }
          break;
        }
    }
    // 'init' applies to a left matra at the start of a word.
    if (buf[start].pos === POS.PRE_M && (start === 0 || !/[\p{L}\p{M}]/u.test(buf[start - 1].text))) buf[start].mask |= F.init;
  }

  s.applyStage("GSUB", stageLookups(font, "GSUB", tags, [{ tag: "init", mask: F.init }, ...["pres", "abvs", "blws", "psts", "haln", "calt", "clig", "liga", "rlig"].map((tag) => ({ tag, mask: GLOBAL }))]));
  return s;
}

// ───────────── Positioning ─────────────

function position(s, { zeroMarks }) {
  const { font, buf } = s;
  for (const g of buf) {
    g.xAdv = font.advance(g.gid);
    g.xOff = 0;
    g.yOff = 0;
    g.attach = null;
  }
  const tags = s.scriptTags;
  const feats = ["kern", "mark", "mkmk", "curs", "dist", "abvm", "blwm"].map((tag) => ({ tag, mask: GLOBAL }));
  s.perSyllable = false;
  s.applyStage("GPOS", stageLookups(font, "GPOS", tags, feats));
  if (zeroMarks) for (const g of buf) if (s.glyphClass(g) === 3) g.xAdv = 0;
  for (const g of buf) if (g.cp === 0x200c || g.cp === 0x200d) (g.xAdv = 0), (g.hidden = true);
}

// ───────────── Public API ─────────────

/** Split text into runs of one script (common and inherited characters join their neighbours). */
export function itemize(text) {
  const chars = [...text].map((ch) => ({ ch, cp: ch.codePointAt(0), script: scriptOf(ch.codePointAt(0)) }));
  let cur = null;
  for (const c of chars) {
    if (c.script === "zinh" || (c.script === "zyyy" && cur)) c.script = c.script === "zinh" ? cur || "zyyy" : cur;
    else if (c.script !== "zyyy") cur = c.script;
  }
  for (let i = chars.length - 1, next = null; i >= 0; i--) {
    if (chars[i].script === "zyyy" && next) chars[i].script = next;
    else if (chars[i].script !== "zyyy") next = chars[i].script;
  }
  return chars;
}

/** Bidi embedding levels for a single paragraph (implicit rules, no explicit embeddings). */
export function bidiLevels(cps) {
  const types = cps.map(bidiClass);
  const firstStrong = types.find((t) => t === "L" || t === "R" || t === "AL");
  const para = firstStrong === "R" || firstStrong === "AL" ? 1 : 0;
  // W1: NSM takes the previous type; W2/W3: EN after AL is AN, AL → R.
  let lastStrong = para ? "R" : "L";
  for (let i = 0; i < types.length; i++) {
    if (types[i] === "NSM") types[i] = i ? types[i - 1] : para ? "R" : "L";
    if (types[i] === "EN" && lastStrong === "AL") types[i] = "AN";
    if (["L", "R", "AL"].includes(types[i])) lastStrong = types[i];
  }
  for (let i = 0; i < types.length; i++) if (types[i] === "AL") types[i] = "R";
  // N1/N2: neutrals between same-direction strongs take that direction, else the paragraph's.
  const strongOf = (t) => (t === "L" ? "L" : t === "R" || t === "AN" || t === "EN" ? (t === "EN" && para === 0 ? "L" : "R") : null);
  for (let i = 0; i < types.length; i++) {
    if (types[i] !== "WS" && types[i] !== "ON") continue;
    let j = i;
    while (j < types.length && (types[j] === "WS" || types[j] === "ON")) j++;
    const before = i ? strongOf(types[i - 1]) : para ? "R" : "L";
    const after = j < types.length ? strongOf(types[j]) : para ? "R" : "L";
    const dir = before === after ? before : para ? "R" : "L";
    for (let k = i; k < j; k++) types[k] = dir;
    i = j - 1;
  }
  return types.map((t) => {
    if (para === 0) return t === "R" ? 1 : t === "AN" || t === "EN" ? (t === "AN" ? 2 : 0) : 0;
    return t === "L" || t === "EN" || t === "AN" ? 2 : 1;
  });
}

/** Visual order of indices for the given levels (rule L2). */
export function visualOrder(levels) {
  const order = levels.map((_, i) => i);
  const max = Math.max(0, ...levels);
  const minOdd = Math.min(...levels.filter((l) => l % 2), Infinity);
  for (let lvl = max; lvl >= (minOdd === Infinity ? max + 1 : minOdd); lvl--) {
    for (let i = 0; i < order.length; ) {
      if (levels[order[i]] >= lvl) {
        let j = i;
        while (j < order.length && levels[order[j]] >= lvl) j++;
        const seg = order.slice(i, j).reverse();
        order.splice(i, j - i, ...seg);
        i = j;
      } else i++;
    }
  }
  return order;
}

export const SUPPORTED_COMPLEX = new Set(["arab", "hebr", "deva", "beng", "guru", "gujr", "taml", "knda", "mlym", "thai"]);

/**
 * Shape a line of text. `chooseFonts(Map script → code points)` returns
 * Map(script → Font|null), so a line can share one font across scripts.
 * Returns { glyphs: [{font, gid, x, y, text}], width, unsupported } in font
 * units of each glyph's own font, scaled by `size`/unitsPerEm into points.
 */
export function shapeLine(text, chooseFonts, size) {
  const chars = itemize(text);
  const cps = chars.map((c) => c.cp);
  const levels = bidiLevels(cps);
  // Runs: same script and same level.
  // Like browsers, spaces are shaped on their own (word-by-word shaping), so
  // script-specific substitutions never apply to them.
  const runs = [];
  const isSpace = (k) => chars[k].cp === 0x20;
  for (let i = 0; i < chars.length; ) {
    let j = i + 1;
    while (j < chars.length && chars[j].script === chars[i].script && levels[j] === levels[i] && isSpace(j) === isSpace(i)) j++;
    runs.push({ start: i, end: j, script: chars[i].script, level: levels[i], space: isSpace(i) });
    i = j;
  }
  const unsupported = [];
  const shaped = [];
  // Fonts are chosen for the whole line, from all characters of each script.
  const scriptName = (r) => (r.script === "zyyy" ? "latn" : r.script);
  const byScript = new Map();
  for (const run of runs) {
    const sc = scriptName(run);
    byScript.set(sc, [...(byScript.get(sc) || []), ...cps.slice(run.start, run.end)]);
  }
  const fontFor = chooseFonts(byScript);
  for (const run of runs) {
    const runText = cps.slice(run.start, run.end).map((c) => String.fromCodePoint(c)).join("");
    const script = scriptName(run);
    const font = fontFor.get(script);
    if (!font) {
      unsupported.push(script);
      continue;
    }
    const rtl = run.level % 2 === 1;
    const norm = normalizeForFont(runText, font, script);
    const buf = makeBuffer(norm, font, rtl);
    if (buf.some((g) => !g.gid && g.cp !== 0x200c && g.cp !== 0x200d)) unsupported.push(script);
    let s;
    if (run.space) s = shapeDefault(font, buf, "zyyy", rtl);
    else if (script === "arab") s = shapeArabic(font, buf);
    else if (INDIC_SCRIPTS[script]) s = shapeIndic(font, buf, script);
    else s = shapeDefault(font, buf, script, rtl);
    position(s, { zeroMarks: !INDIC_SCRIPTS[script] });
    shaped.push({ run, font, buf: s.buf, rtl });
  }
  // Visual order of runs by level, then glyphs within RTL runs reversed.
  const runLevels = shaped.map((r) => r.run.level);
  const order = visualOrder(runLevels);
  const glyphs = [];
  let pen = 0;
  for (const idx of order) {
    const { font, buf, rtl } = shaped[idx];
    const scale = size / font.unitsPerEm;
    const visual = rtl ? buf.map((g, k) => ({ g, k })).reverse() : buf.map((g, k) => ({ g, k }));
    const absX = new Array(buf.length);
    const absY = new Array(buf.length);
    for (const { g, k } of visual) {
      absX[k] = pen + g.xOff * scale;
      absY[k] = g.yOff * scale;
      pen += g.xAdv * scale;
    }
    // Attachments: position marks from their (already placed) anchors, in logical order.
    for (let k = 0; k < buf.length; k++) {
      const a = buf[k].attach;
      if (!a) continue;
      absX[k] = absX[a.to] + a.dx * scale + buf[k].xOff * scale;
      absY[k] = absY[a.to] + a.dy * scale + buf[k].yOff * scale;
    }
    for (const { g, k } of visual) if (!g.hidden) glyphs.push({ font, gid: g.gid, x: absX[k], y: absY[k], text: g.text, cluster: g.cluster, logical: idx * 100000 + k, run: idx });
  }
  const runInfo = shaped.map((r) => ({ text: cps.slice(r.run.start, r.run.end).map((c) => String.fromCodePoint(c)).join(""), rtl: r.rtl }));
  return { glyphs, runs: runInfo, width: pen, unsupported: [...new Set(unsupported)] };
}
