// Admin: early-access registrants (super administrators only). Import shows a
// preview first; invitations go in explicit, confirmed batches.
import { html } from "../../lib/html.js";
import { redirect, HttpError } from "../../lib/http.js";
import { adminPage, table, hidden, textarea, input, str } from "./shell.js";
import { parseRegistrants, previewImport, importRegistrants, summary, sendInvitations, INVITE_BATCH } from "../../services/earlyAccess.js";

function requireSuper(c) {
  if (!c.roles.includes("super_admin")) throw new HttpError(403, "forbidden");
}

const HELP = html`<p class="small">Export the registrations from the Platform API (<code>saas_requests</code> where <code>source_page = 'academy/early-access'</code>) as CSV with the columns
  <code>source_id, email, name, language, role, email_opt_in, registered_at</code>. Importing creates no accounts and sends no email. Internal test submissions are skipped.</p>`;

export async function page(c, { preview = null, data = "" } = {}) {
  requireSuper(c);
  const s = await summary(c.env, c.cfg);
  const confirmPhrase = `send ${s.invitable > INVITE_BATCH ? INVITE_BATCH : s.invitable} invitations`;
  const body = html`
  <section class="grid-3 mb-3">
    <div class="card"><p class="small muted">Registrants</p><p class="display-sm">${s.total}</p></div>
    <div class="card"><p class="small muted">Activated (verified account)</p><p class="display-sm">${s.activated}</p></div>
    <div class="card"><p class="small muted">Invited, not yet activated</p><p class="display-sm">${s.invited}</p></div>
  </section>
  <p class="small">Pending: ${s.pending} (of which ${s.noConsent} without consent to be contacted). Languages: ${s.locales.map((l) => `${l.locale} ${l.n}`).join(", ") || "—"}.</p>

  <form class="form-card mt-3" method="post" action="/admin/early-access/import">${hidden(c)}
    <h2 class="h2">Import registrations</h2>${HELP}
    ${textarea("data", "CSV or JSON export", data, { rows: 8, required: true })}
    <input type="hidden" name="mode" value="${preview ? "import" : "preview"}">
    ${preview
      ? html`<div class="panel small mb-2"><strong>Preview:</strong> ${preview.records} valid row(s): ${preview.fresh} new, ${preview.known} already imported, ${preview.accounts} already have a verified account (they will be linked),
          ${preview.optedIn} consented to be contacted. ${preview.internal} internal test row(s) skipped. ${preview.rejected.length} rejected${preview.rejected.length ? `: ${preview.rejected.slice(0, 10).map((r) => `line ${r.line} (${r.reason})`).join("; ")}` : ""}.</div>
          <button class="btn btn-primary">Import ${preview.records} registrant(s)</button>`
      : html`<button class="btn btn-secondary">Preview import</button>`}
  </form>

  <form class="form-card mt-3" method="post" action="/admin/early-access/invite" data-confirm="Send these invitations now?">${hidden(c)}
    <h2 class="h2">Invitations</h2>
    <p class="small">${s.invitable} registrant(s) consented, have no Academy account and have not been invited. Each person is invited at most once, in their registration language, with a link to create their own account. Batches of up to ${INVITE_BATCH}.
      ${c.cfg.environment === "production" ? "" : html`<strong>Outside production only synthetic staging test addresses are ever invited.</strong>`}</p>
    ${s.invitable
      ? html`<input type="hidden" name="expected" value="${Math.min(s.invitable, INVITE_BATCH)}">
          ${input("confirm", `Type “${confirmPhrase}” to confirm`, "", { required: true })}
          <button class="btn btn-danger">Send invitations</button>`
      : html`<p class="small muted">Nobody to invite.</p>`}
  </form>`;
  return adminPage(c, { title: "Early-access registrants", active: "/admin/early-access", body });
}

export async function importAction(c) {
  requireSuper(c);
  const b = await c.readBody();
  const data = String(b.data || "");
  let parsed;
  try {
    parsed = parseRegistrants(data);
  } catch (e) {
    return redirect(`/admin/early-access?err=${encodeURIComponent(`Could not read the export: ${e.message}`)}`);
  }
  if (b.mode !== "import") {
    const p = await previewImport(c.env, parsed.records);
    return page(c, { preview: { ...p, records: parsed.records.length, rejected: parsed.rejected, internal: parsed.internal }, data });
  }
  const r = await importRegistrants(c.env, parsed.records, c.user.id);
  return redirect(`/admin/early-access?ok=${encodeURIComponent(`imported:${r.rows}:${r.linked}`)}`);
}

export async function inviteAction(c) {
  requireSuper(c);
  const b = await c.readBody();
  const expected = Number(b.expected);
  if (str(b.confirm, 60).toLowerCase() !== `send ${expected} invitations`) return redirect(`/admin/early-access?err=${encodeURIComponent("Type the confirmation phrase exactly to send invitations.")}`);
  const r = await sendInvitations(c.env, c.cfg, { actorId: c.user.id, expected, defer: c.defer });
  if (r.mismatch) return redirect(`/admin/early-access?err=${encodeURIComponent(`The number of people to invite changed (now ${r.available}). Review and confirm again.`)}`);
  return redirect(`/admin/early-access?ok=${encodeURIComponent(`invited:${r.sent}`)}`);
}
