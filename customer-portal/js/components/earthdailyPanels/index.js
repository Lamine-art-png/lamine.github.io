import { escapeHtml } from "../dom.js";

export function badge(label, tone = "neutral") {
  return `<span class="badge ${tone}">${escapeHtml(label)}</span>`;
}

export function panel(number, title, body, extraClass = "") {
  return `<section class="panel-card command-section earthdaily-panel ${extraClass}">
    <div class="section-heading numbered-heading"><span>${String(number).padStart(2, "0")}</span><div><h3>${escapeHtml(title)}</h3></div></div>
    ${body}
  </section>`;
}

export function skeletonRows(count = 4) {
  return `<div class="earthdaily-skeleton">${Array.from({ length: count }, () => "<span></span>").join("")}</div>`;
}

export function bar(label, value) {
  const pct = Math.round(Math.max(0, Math.min(1, Number(value) || 0)) * 100);
  return `<div class="earthdaily-bar"><div><span>${escapeHtml(label)}</span><strong>${pct}%</strong></div><i style="width:${pct}%"></i></div>`;
}

export function jsonDetails(title, payload) {
  return `<details class="technical-trace earthdaily-json"><summary>${escapeHtml(title)}</summary><pre>${escapeHtml(JSON.stringify(payload ?? {}, null, 2))}</pre></details>`;
}

export function list(items) {
  return `<ul>${(items || []).map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>`;
}

