// Deterministic agricultural artwork for course covers and page visuals.
// Lightweight SVG (a few KB) keeps pages fast on rural connections; any course
// can replace it with licensed photography through the admin thumbnail field.

function rng(seedStr) {
  let h = 2166136261;
  for (const ch of String(seedStr)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return () => {
    h += 0x6d2b79f5;
    let t = h;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Every palette is a family of the AGRO-AI greens sampled from the official
// logo, so course art always reads as AGRO-AI. Keys are kept stable because
// cover URLs (/art/<motif>/<palette>/...) include them.
const PALETTES = {
  green: ["#082503", "#0c3e03", "#1c4c07", "#27570b", "#427b11", "#6fac1e", "#b1e646"],
  earth: ["#0f2410", "#1a3a12", "#2f5418", "#4f7a24", "#7fa63a", "#b9d36a", "#e4efb8"],
  water: ["#0b231a", "#123a2a", "#1d553b", "#2f7650", "#4f9a68", "#86c08f", "#c6e6c4"],
  dusk: ["#061a06", "#0c2a0c", "#163f12", "#245a18", "#3d7a1f", "#6fac1e", "#d6fc5b"],
  night: ["#051704", "#0a2808", "#123d0c", "#1c5410", "#2f7a16", "#6fac1e", "#b1e646"],
};

const f = (n) => Math.round(n * 10) / 10;

function pivots(r, p, w, h) {
  let s = `<rect width="${w}" height="${h}" fill="${p[1]}"/>`;
  // Section grid (roads) with center-pivot circles, as seen from orbit.
  const cell = Math.max(110, Math.round(w / 5.5));
  const ox = -Math.round(r() * cell * 0.5);
  const oy = -Math.round(r() * cell * 0.5);
  for (let y = oy; y < h + cell; y += cell) {
    for (let x = ox; x < w + cell; x += cell) {
      const cx = x + cell / 2;
      const cy = y + cell / 2;
      const rad = cell * 0.46;
      s += `<rect x="${x}" y="${y}" width="${cell}" height="${cell}" fill="${p[1 + Math.floor(r() * 2)]}" stroke="${p[0]}" stroke-width="2"/>`;
      if (r() < 0.82) {
        const tone = 2 + Math.floor(r() * 5);
        s += `<circle cx="${f(cx)}" cy="${f(cy)}" r="${f(rad)}" fill="${p[tone]}"/>`;
        // Wheel tracks of the pivot span.
        for (const k of [0.33, 0.62, 0.86]) s += `<circle cx="${f(cx)}" cy="${f(cy)}" r="${f(rad * k)}" fill="none" stroke="${p[0]}" stroke-opacity=".16" stroke-width="1.2"/>`;
        if (r() < 0.45) {
          // A recently irrigated or harvested sector.
          const a = r() * Math.PI * 2;
          const span = 0.8 + r() * 1.6;
          s += `<path d="M${f(cx)} ${f(cy)}L${f(cx + Math.cos(a) * rad)} ${f(cy + Math.sin(a) * rad)}A${f(rad)} ${f(rad)} 0 ${span > Math.PI ? 1 : 0} 1 ${f(cx + Math.cos(a + span) * rad)} ${f(cy + Math.sin(a + span) * rad)}Z" fill="${p[Math.max(2, tone - 2)]}" opacity=".55"/>`;
        }
        s += `<path d="M${f(cx)} ${f(cy)}l${f(rad * 0.98)} 0" stroke="${p[6]}" stroke-opacity=".55" stroke-width="1.4"/>`;
      }
    }
  }
  return s;
}

function rows(r, p, w, h) {
  const horizon = h * (0.34 + r() * 0.08);
  let s = `<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${p[0]}"/><stop offset="1" stop-color="${p[3]}"/></linearGradient>
  <linearGradient id="soil" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${p[2]}"/><stop offset="1" stop-color="${p[1]}"/></linearGradient></defs>
  <rect width="${w}" height="${h}" fill="url(#sky)"/>
  <circle cx="${f(w * (0.2 + r() * 0.6))}" cy="${f(horizon - 30)}" r="${f(36 + r() * 20)}" fill="${p[6]}" opacity=".9"/>
  <rect y="${f(horizon)}" width="${w}" height="${f(h - horizon)}" fill="url(#soil)"/>`;
  const vx = w * (0.35 + r() * 0.3);
  const n = 26;
  for (let i = -n; i <= n * 2; i++) {
    const x = (i / n) * w;
    s += `<path d="M${f(vx)} ${f(horizon)}L${f(x - 14)} ${h}L${f(x + 14)} ${h}Z" fill="${p[4 + (i & 1)]}" opacity="${0.55 + (i % 3) * 0.12}"/>`;
  }
  s += `<rect y="${f(horizon - 2)}" width="${w}" height="6" fill="${p[1]}" opacity=".6"/>`;
  return s;
}

function patchwork(r, p, w, h) {
  let s = `<rect width="${w}" height="${h}" fill="${p[1]}"/><g transform="rotate(${f(-12 + r() * 24)} ${w / 2} ${h / 2})">`;
  for (let y = -h * 0.3; y < h * 1.3; ) {
    const rh = 50 + r() * 90;
    for (let x = -w * 0.3; x < w * 1.3; ) {
      const rw = 70 + r() * 180;
      s += `<rect x="${f(x)}" y="${f(y)}" width="${f(rw - 4)}" height="${f(rh - 4)}" rx="2" fill="${p[1 + Math.floor(r() * 6)]}"/>`;
      if (r() < 0.35) {
        for (let k = 6; k < rw - 6; k += 9) s += `<path d="M${f(x + k)} ${f(y + 3)}v${f(rh - 10)}" stroke="${p[0]}" stroke-opacity=".18" stroke-width="2"/>`;
      }
      x += rw;
    }
    y += rh;
  }
  return s + "</g>";
}

function contours(r, p, w, h) {
  let s = `<rect width="${w}" height="${h}" fill="${p[0]}"/>`;
  const cx = w * (0.3 + r() * 0.4);
  const cy = h * (0.3 + r() * 0.4);
  for (let i = 18; i > 0; i--) {
    const rad = i * 34;
    let d = "";
    for (let a = 0; a <= 64; a++) {
      const t = (a / 64) * Math.PI * 2;
      const wob = 1 + 0.12 * Math.sin(t * 3 + i * 0.4) + 0.06 * Math.cos(t * 5 + i);
      d += `${a ? "L" : "M"}${f(cx + Math.cos(t) * rad * wob * 1.35)} ${f(cy + Math.sin(t) * rad * wob)}`;
    }
    s += `<path d="${d}Z" fill="${i % 4 === 0 ? p[2] : "none"}" fill-opacity=".25" stroke="${p[3 + (i % 4)]}" stroke-opacity="${0.35 + (i % 3) * 0.2}" stroke-width="${i % 4 === 0 ? 2.4 : 1.2}"/>`;
  }
  return s;
}

function orbit(r, p, w, h) {
  let s = `<rect width="${w}" height="${h}" fill="${p[0]}"/>`;
  for (let i = 0; i < 70; i++) s += `<circle cx="${f(r() * w)}" cy="${f(r() * h * 0.6)}" r="${f(r() * 1.4 + 0.3)}" fill="#fff" opacity="${f(0.2 + r() * 0.6)}"/>`;
  const R = w * 1.1;
  s += `<defs><radialGradient id="earth" cx=".5" cy=".2" r=".8"><stop offset="0" stop-color="${p[4]}"/><stop offset=".55" stop-color="${p[2]}"/><stop offset="1" stop-color="${p[1]}"/></radialGradient></defs>
  <circle cx="${w / 2}" cy="${f(h + R * 0.72)}" r="${f(R)}" fill="url(#earth)"/>
  <circle cx="${w / 2}" cy="${f(h + R * 0.72)}" r="${f(R + 6)}" fill="none" stroke="${p[6]}" stroke-opacity=".35" stroke-width="5"/>
  <ellipse cx="${w / 2}" cy="${f(h * 0.62)}" rx="${f(w * 0.52)}" ry="${f(h * 0.2)}" fill="none" stroke="${p[6]}" stroke-dasharray="4 8" stroke-opacity=".6"/>`;
  const sx = w * (0.25 + r() * 0.5);
  const sy = h * 0.43;
  s += `<g transform="translate(${f(sx)} ${f(sy)}) rotate(-20)"><rect x="-26" y="-6" width="18" height="12" fill="${p[5]}"/><rect x="8" y="-6" width="18" height="12" fill="${p[5]}"/><rect x="-7" y="-8" width="14" height="16" rx="2" fill="#e8efe5"/></g>
  <path d="M${f(sx)} ${f(sy + 10)}L${f(sx - 60)} ${f(h * 0.95)}L${f(sx + 60)} ${f(h * 0.95)}Z" fill="${p[6]}" opacity=".12"/>`;
  return s;
}

function network(r, p, w, h) {
  let s = `<rect width="${w}" height="${h}" fill="${p[0]}"/>` + patchwork(r, p, w, h).replace(/fill="#/g, 'fill-opacity=".25" fill="#');
  const nodes = [];
  const layers = 4;
  for (let l = 0; l < layers; l++) {
    const count = 3 + Math.floor(r() * 3);
    for (let i = 0; i < count; i++) nodes.push({ l, x: w * (0.14 + (l / (layers - 1)) * 0.72), y: h * ((i + 1) / (count + 1)) });
  }
  for (const a of nodes) for (const b of nodes) if (b.l === a.l + 1) s += `<path d="M${f(a.x)} ${f(a.y)}L${f(b.x)} ${f(b.y)}" stroke="${p[5]}" stroke-opacity="${f(0.15 + r() * 0.35)}" stroke-width="1.4"/>`;
  for (const n of nodes) s += `<circle cx="${f(n.x)}" cy="${f(n.y)}" r="9" fill="${p[1]}" stroke="${p[6]}" stroke-width="2.5"/>`;
  return s;
}

function code(r, p, w, h) {
  let s = `<rect width="${w}" height="${h}" fill="${p[0]}"/>`;
  let y = 40;
  while (y < h - 20) {
    let x = 40 + Math.floor(r() * 4) * 26;
    const tokens = 2 + Math.floor(r() * 5);
    for (let t = 0; t < tokens && x < w - 60; t++) {
      const tw = 20 + r() * 90;
      s += `<rect x="${f(x)}" y="${y}" width="${f(tw)}" height="10" rx="5" fill="${p[2 + Math.floor(r() * 5)]}" opacity=".85"/>`;
      x += tw + 12;
    }
    y += 26;
  }
  s += `<path d="M${w - 170} ${h / 2 - 60}l-50 60 50 60M${w - 90} ${h / 2 - 60}l50 60-50 60" stroke="${p[6]}" stroke-width="10" fill="none" stroke-linecap="round" stroke-linejoin="round" opacity=".9"/>`;
  return s;
}

const MOTIFS = { pivots, rows, patchwork, contours, orbit, network, code };

export function artSvg(motif, seed, palette = "green", w = 800, h = 450) {
  const r = rng(`${motif}:${seed}`);
  const p = PALETTES[palette] || PALETTES.green;
  const body = (MOTIFS[motif] || patchwork)(r, p, w, h);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid slice" role="img" aria-hidden="true">${body}<rect width="${w}" height="${h}" fill="url(#vg)"/><defs><linearGradient id="vg" x1="0" y1="0" x2="0" y2="1"><stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".28"/></linearGradient></defs></svg>`;
}

/** Choose a motif + palette for a course from its topics. */
export function courseArt(course) {
  const topics = (() => {
    try {
      return JSON.parse(course.topics_json || "[]");
    } catch {
      return [];
    }
  })().join(" ");
  const s = `${course.slug} ${topics}`.toLowerCase();
  if (/api|integration|developer|code/.test(s)) return { motif: "code", palette: "night" };
  if (/satellite|remote|sensing|orbit/.test(s)) return { motif: "orbit", palette: "night" };
  if (/irrigation|water/.test(s)) return { motif: "pivots", palette: "water" };
  if (/vision|robot|agent|machine|predict|neural/.test(s)) return { motif: "network", palette: "green" };
  if (/ethic|responsib|risk|yield|market/.test(s)) return { motif: "contours", palette: "earth" };
  if (/data|monitor|crop/.test(s)) return { motif: "patchwork", palette: "green" };
  if (/portal|enterprise|platform|report/.test(s)) return { motif: "pivots", palette: "green" };
  return { motif: "rows", palette: "dusk" };
}

export function courseThumb(course) {
  if (course.thumbnail_url) return course.thumbnail_url;
  const { motif, palette } = courseArt(course);
  return `/art/${motif}/${palette}/${encodeURIComponent(course.slug)}.svg`;
}
