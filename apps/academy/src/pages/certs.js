// Credential pages: the learner's certificate with sharing tools, PDF
// download, public verification, and on-demand claiming.
import { html, raw } from "../lib/html.js";
import { redirect, HttpError } from "../lib/http.js";
import { newId, nowIso } from "../lib/util.js";
import { rateLimit } from "../lib/security.js";
import { qrSvg } from "../lib/qr.js";
import { unsupportedNameScripts } from "../lib/pdf.js";
import { renderCertificatePdf } from "../services/certificate-pdf.js";
import { formatDate } from "../lib/i18n.js";
import { icon } from "../views/icons.js";
import { alert, csrfField, emptyState, pageHead } from "../views/components.js";
import { getByCredential, shareUrls, signatureStatus, issueIfEligible } from "../services/certificates.js";
import { getCourseBySlug } from "../services/content.js";

export function certificateVisual(c, cert, verifyUrl) {
  const t = c.t;
  return html`<div class="certificate ${cert.status === "revoked" ? "revoked" : ""}" role="img" aria-label="${t("cert.visual_label", { name: cert.credential_name, course: cert.course_title })}">
    <div class="c-top"><div class="c-brand"><img src="/static/img/mark-64.png" alt=""><span>AGRO-AI <span>Academy</span></span></div><span class="c-id">${cert.credential_id}</span></div>
    <div class="c-center">
      <div class="c-label">${t("cert.title_label")}</div>
      <div class="c-name">${cert.credential_name}</div>
      <p class="c-text">${t("cert.completed_text")}</p>
      <div class="c-course" lang="en">${cert.course_title}</div>
    </div>
    <div class="c-foot">
      <div><span>${t("cert.issued")}</span><strong>${c.fmtDate(cert.issued_at)}</strong></div>
      <div><span>${t("cert.issuer")}</span><strong>AGRO-AI Academy</strong></div>
      <div class="c-qr">${raw(qrSvg(verifyUrl, { title: t("cert.qr_label") }))}</div>
    </div>
  </div>`;
}

export async function certificatePage(c) {
  const t = c.t;
  const cert = await getByCredential(c.env, c.params.cred);
  if (!cert) throw new HttpError(404, "not_found");
  if (cert.user_id !== c.user.id && !c.can("certificates.manage")) return redirect(`/verify/${cert.credential_id}`);
  const urls = shareUrls(c.cfg, cert);
  const integrity = await signatureStatus(c.cfg, cert);
  const verified = integrity === "valid";
  const fresh = c.url.searchParams.get("new") === "1" && verified;
  const pdfOk = unsupportedNameScripts(cert.credential_name).length === 0;
  const shareText = t("cert.share_text", { course: cert.course_title });
  const body = html`${pageHead({
    eyebrow: t("cert.eyebrow"),
    title: fresh ? t("cert.congrats_title") : cert.course_title,
    lead: fresh ? t("cert.congrats_lead", { course: cert.course_title }) : t("cert.owner_lead"),
    crumbs: [[t("nav.dashboard"), "/dashboard"], [t("nav.my_certificates"), "/dashboard/certificates"], [cert.credential_id]],
  })}
  <section class="section-tight"><div class="wrap cert-showcase">
    <div>${cert.status === "revoked" ? alert("error", t("cert.revoked_notice", { reason: cert.revoked_reason || "" })) : ""}
      ${!verified ? alert("error", integrity === "invalid" ? t("verify.integrity_body") : t("verify.unavailable_body")) : ""}
      ${certificateVisual(c, cert, urls.verifyUrl)}
      ${!pdfOk || c.url.searchParams.get("pdf") === "unsupported" ? alert("info", t("cert.pdf_script_note")) : ""}
    </div>
    <div>
      <h2 class="h2">${t("cert.share_title")}</h2>
      <p class="muted">${t("cert.share_lead")}</p>
      <div class="share-grid">
        <a class="btn btn-primary" href="${urls.linkedinAdd}" target="_blank" rel="noopener noreferrer">${icon("linkedin", { size: 18 })} ${t("cert.add_linkedin")}</a>
        <a class="btn btn-secondary" href="${urls.linkedinShare}" target="_blank" rel="noopener noreferrer">${icon("linkedin", { size: 18 })} ${t("cert.share_linkedin")}</a>
        <a class="btn btn-secondary" href="${urls.facebook}" target="_blank" rel="noopener noreferrer">${icon("facebook", { size: 18 })} ${t("cert.share_facebook")}</a>
        ${verified && pdfOk && cert.status === "active" ? html`<a class="btn btn-secondary" href="${urls.pdf}" download>${icon("download", { size: 18 })} ${t("cert.download_pdf")}</a>` : ""}
        <button class="btn btn-secondary" type="button" data-copy="${urls.verifyUrl}" data-copied="${t("cert.copied_link")}">${icon("link", { size: 18 })} ${t("cert.copy_link")}</button>
        <button class="btn btn-secondary" type="button" data-copy="${cert.credential_id}" data-copied="${t("cert.copied_id")}">${icon("copy", { size: 18 })} ${t("cert.copy_id")}</button>
        <button class="btn btn-secondary" type="button" data-share data-share-url="${urls.verifyUrl}" data-share-title="${cert.course_title}" data-share-text="${shareText}" hidden>${icon("share", { size: 18 })} ${t("cert.share_device")}</button>
        <button class="btn btn-quiet" type="button" data-print>${icon("file", { size: 18 })} ${t("cert.print")}</button>
      </div>
      <details class="panel mt-3"><summary><strong>${t("cert.linkedin_manual_title")}</strong></summary>
        <dl class="kv">
          <dt>${t("cert.field_name")}</dt><dd>${cert.course_title}</dd>
          <dt>${t("cert.field_org")}</dt><dd>AGRO-AI Academy</dd>
          <dt>${t("cert.field_issue")}</dt><dd>${c.fmtDate(cert.issued_at, { year: "numeric", month: "long" })}</dd>
          <dt>${t("cert.field_id")}</dt><dd><code>${cert.credential_id}</code></dd>
          <dt>${t("cert.field_url")}</dt><dd><a href="${urls.verifyUrl}">${urls.verifyUrl}</a></dd>
        </dl>
        <p class="tiny muted mt-2 mb-0">${t("cert.linkedin_note")}</p></details>
      <p class="small muted mt-3">${icon("shield", { size: 14 })} ${t("cert.public_note")} <a href="/verify/${cert.credential_id}">${t("cert.view_public")}</a></p>
      <p class="tiny muted">${t("cert.not_accredited")}</p>
    </div>
  </div></section>`;
  return c.page({ title: cert.course_title, body, noindex: true });
}

export async function certificatePdfRoute(c) {
  const cert = await getByCredential(c.env, c.params.cred);
  if (!cert) throw new HttpError(404, "not_found");
  if (cert.user_id !== c.user.id && !c.can("certificates.manage")) throw new HttpError(404, "not_found");
  if (cert.status !== "active") throw new HttpError(409, "certificate_revoked");
  // A PDF is only produced for a record whose signature verifies right now.
  const integrity = await signatureStatus(c.cfg, cert);
  if (integrity !== "valid") throw new HttpError(integrity === "invalid" ? 409 : 503, integrity === "invalid" ? "certificate_integrity_failed" : "certificate_verification_unavailable");
  await rateLimit(c, "cert-pdf", { limit: 60, windowSeconds: 3600, key: c.user.id });
  const verifyUrl = `${c.cfg.origin}/verify/${cert.credential_id}`;
  let pdf;
  try {
    pdf = await renderCertificatePdf(c.env, c.cfg.origin, cert, { verifyUrl, host: c.cfg.host, issuedDate: formatDate("en", cert.issued_at) });
  } catch (e) {
    if (e instanceof HttpError && e.code === "name_script_unsupported") return redirect(`/certificates/${cert.credential_id}?pdf=unsupported`);
    throw e;
  }
  c.defer(
    c.env.DB.prepare("INSERT INTO certificate_events (id, certificate_id, event, actor_id, created_at) VALUES (?,?,?,?,?)").bind(newId("ce_"), cert.id, "pdf_downloaded", c.user.id, nowIso()).run(),
  );
  return new Response(pdf, {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `attachment; filename="AGRO-AI-Academy-${cert.credential_id}.pdf"`,
      "Cache-Control": "private, no-store",
    },
  });
}

export async function verifyForm(c) {
  const t = c.t;
  const id = (c.url.searchParams.get("id") || "").trim();
  if (id) return redirect(`/verify/${encodeURIComponent(id.toUpperCase())}`);
  const body = html`${pageHead({ eyebrow: t("verify.eyebrow"), title: t("verify.title"), lead: t("verify.lead") })}
  <section class="section-tight"><div class="wrap narrow">
    <form class="form-card" method="get" action="/verify" role="search">
      <label for="cred">${t("verify.input_label")}</label>
      <div class="search-bar"><input id="cred" name="id" required placeholder="AGA-XXXX-XXXX-XXXX" autocomplete="off" spellcheck="false" autocapitalize="characters" maxlength="24">
        <button class="btn btn-primary" type="submit">${icon("shield", { size: 18 })} ${t("verify.button")}</button></div>
      <p class="small muted mb-0">${t("verify.hint")}</p>
    </form>
    <div class="panel mt-3"><h2 class="h2">${t("verify.what_title")}</h2><p class="mb-0">${t("verify.what_body")}</p></div>
  </div></section>`;
  return c.page({ title: t("verify.title"), description: t("verify.lead"), body, active: "verify" });
}

export async function verifyPage(c) {
  const t = c.t;
  await rateLimit(c, "verify", { limit: 120, windowSeconds: 600 });
  const cert = await getByCredential(c.env, c.params.cred);
  if (!cert) {
    const body = html`${pageHead({ eyebrow: t("verify.eyebrow"), title: t("verify.title") })}
      <section class="section-tight"><div class="wrap narrow"><div class="verify-result invalid">
        <p class="verify-status invalid">${icon("x", { size: 22 })} ${t("verify.not_found")}</p>
        <p>${t("verify.not_found_body", { id: c.params.cred.slice(0, 40) })}</p>
        <a class="btn btn-secondary" href="/verify">${t("verify.try_again")}</a></div></div></section>`;
    return c.page({ title: t("verify.not_found"), body, status: 404, noindex: true });
  }
  // Fail closed: a credential is shown as valid only when its signature was
  // recomputed and matched. Missing configuration or an error never passes.
  // Revocation is reported whatever the signature says: it can only make a
  // record less valid (deleted accounts are anonymized and revoked).
  const integrity = cert.status === "active" ? await signatureStatus(c.cfg, cert) : "not_checked";
  if (integrity === "unavailable") {
    const body = html`${pageHead({ eyebrow: t("verify.eyebrow"), title: t("verify.title") })}
      <section class="section-tight"><div class="wrap narrow"><div class="verify-result invalid" aria-live="polite">
        <p class="verify-status invalid">${icon("alert", { size: 22 })} ${t("verify.unavailable")}</p>
        <p>${t("verify.unavailable_body")}</p>
        <p class="small muted mb-0">${t("verify.credential_id")}: <code>${cert.credential_id}</code></p></div></div></section>`;
    const res = c.page({ title: t("verify.unavailable"), body, status: 503, noindex: true });
    res.headers.set("Retry-After", "300");
    return res;
  }
  const state = cert.status !== "active" ? "revoked" : integrity === "valid" ? "valid" : "integrity_failed";
  const valid = state === "valid";
  const verifyUrl = `${c.cfg.origin}/verify/${cert.credential_id}`;
  const body = html`${pageHead({ eyebrow: t("verify.eyebrow"), title: t("verify.result_title") })}
  <section class="section-tight"><div class="wrap cert-showcase">
    <div class="verify-result ${valid ? "valid" : "invalid"}" aria-live="polite" data-verify-state="${state}">
      <p class="verify-status ${valid ? "valid" : "invalid"}">${icon(valid ? "shield" : "alert", { size: 24 })} ${t(`verify.${state}`)}</p>
      <p class="muted">${t(state === "valid" ? "verify.valid_body" : state === "revoked" ? "verify.revoked_body" : "verify.integrity_body")}</p>
      <dl class="kv">
        <dt>${t("verify.holder")}</dt><dd>${cert.credential_name}</dd>
        <dt>${t("verify.credential")}</dt><dd lang="en">${cert.course_title}</dd>
        ${cert.program_title ? html`<dt>${t("verify.program")}</dt><dd lang="en">${cert.program_title}</dd>` : ""}
        <dt>${t("verify.issued")}</dt><dd>${c.fmtDate(cert.issued_at)}</dd>
        <dt>${t("verify.issuer")}</dt><dd>AGRO-AI Academy · AGRO-AI Inc.</dd>
        <dt>${t("verify.credential_id")}</dt><dd><code>${cert.credential_id}</code></dd>
        <dt>${t("verify.status")}</dt><dd>${cert.status === "active" ? html`<span class="badge badge-green">${t("verify.status_active")}</span>` : html`<span class="badge badge-danger">${t("verify.status_revoked")}</span> ${cert.revoked_at ? c.fmtDate(cert.revoked_at) : ""}`}</dd>
      </dl>
      <p class="tiny muted mt-3 mb-0">${t("verify.scope_note")}</p>
    </div>
    <div>${valid ? certificateVisual(c, cert, verifyUrl) : ""}
      <p class="small mt-2"><a href="/courses/${cert.course_slug}">${t("verify.about_course")}</a></p></div>
  </div></section>`;
  return c.page({
    title: t("verify.og_title", { name: cert.credential_name, course: cert.course_title }),
    description: t("verify.og_description", { course: cert.course_title, date: formatDate("en", cert.issued_at) }),
    body,
    noindex: true,
    canonical: `/verify/${cert.credential_id}`,
    jsonLd: valid
      ? {
          "@context": "https://schema.org",
          "@type": "EducationalOccupationalCredential",
          name: cert.course_title,
          credentialCategory: "certificate",
          identifier: cert.credential_id,
          dateCreated: cert.issued_at,
          url: verifyUrl,
          recognizedBy: { "@type": "Organization", name: "AGRO-AI Academy" },
        }
      : undefined,
  });
}

export async function claim(c) {
  const course = await getCourseBySlug(c.env, c.params.slug, c.locale, { userId: c.user?.id });
  await rateLimit(c, "cert-claim", { limit: 20, windowSeconds: 3600, key: c.user.id });
  const result = await issueIfEligible(c.env, c.cfg, c.user, course, { defer: c.defer });
  if (result.certificate) return redirect(`/certificates/${result.certificate.credential_id}${result.created ? "?new=1" : ""}`);
  return redirect(`/dashboard/certificates?missing=${encodeURIComponent(result.reasons?.[0] || "")}`);
}

export { emptyState, csrfField };
