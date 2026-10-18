// Credential issuance, eligibility, verification and revocation.
// Eligibility is always evaluated on the server from persisted records.
import { credentialId, hmacHex, newId, nowIso, safeEqual } from "../lib/util.js";
import { HttpError } from "../lib/http.js";
import { auditStmt } from "../lib/security.js";
import { notifyStmt, grantAchievement, eventStmt } from "./activity.js";
import { queueEmail, deliverById } from "./email.js";

export async function certificationExam(env, courseId) {
  return env.DB.prepare("SELECT * FROM assessments WHERE course_id = ? AND kind = 'exam' AND is_certification = 1 AND status = 'active' ORDER BY created_at LIMIT 1")
    .bind(courseId)
    .first();
}

export async function lessonCompletion(env, userId, courseId) {
  const row = await env.DB.prepare(
    `SELECT COUNT(*) AS required,
            SUM(CASE WHEN lp.status = 'completed' THEN 1 ELSE 0 END) AS done
       FROM lessons l LEFT JOIN lesson_progress lp ON lp.lesson_id = l.id AND lp.user_id = ?
      WHERE l.course_id = ? AND l.status = 'ready' AND l.is_required = 1
        AND (l.assessment_id IS NULL OR l.assessment_id NOT IN (SELECT id FROM assessments WHERE kind = 'exam'))`,
  )
    .bind(userId, courseId)
    .first();
  return { required: row?.required || 0, done: row?.done || 0 };
}

export async function bestPassedAttempt(env, userId, assessmentId) {
  return env.DB.prepare(
    "SELECT * FROM attempts WHERE user_id = ? AND assessment_id = ? AND status = 'graded' AND passed = 1 ORDER BY score_pct DESC, graded_at ASC LIMIT 1",
  )
    .bind(userId, assessmentId)
    .first();
}

/** Returns { eligible, reasons: string[], attempt, exam } */
export async function checkEligibility(env, user, course) {
  const reasons = [];
  if (!course.certificate_enabled) reasons.push("cert.reason.disabled");
  if (!user.email_verified_at) reasons.push("cert.reason.verify_email");
  const lessons = await lessonCompletion(env, user.id, course.id);
  if (course.require_all_lessons && lessons.done < lessons.required) reasons.push("cert.reason.lessons");
  if (course.require_quizzes_pass) {
    const missing = await env.DB.prepare(
      `SELECT COUNT(*) AS n FROM assessments a WHERE a.course_id = ? AND a.kind = 'quiz' AND a.is_required = 1 AND a.status = 'active'
         AND NOT EXISTS (SELECT 1 FROM attempts t WHERE t.assessment_id = a.id AND t.user_id = ? AND t.status = 'graded' AND t.passed = 1)`,
    )
      .bind(course.id, user.id)
      .first();
    if (missing.n > 0) reasons.push("cert.reason.quizzes");
  }
  const exam = await certificationExam(env, course.id);
  let attempt = null;
  if (!exam) reasons.push("cert.reason.no_exam");
  else {
    attempt = await bestPassedAttempt(env, user.id, exam.id);
    if (!attempt) reasons.push("cert.reason.exam");
  }
  return { eligible: reasons.length === 0, reasons, attempt, exam, lessons };
}

function signaturePayload(cert) {
  return [cert.credential_id, cert.user_id || "", cert.course_id, cert.credential_name, cert.course_title, cert.issued_at].join("|");
}

export async function signCertificate(cfg, cert) {
  if (!cfg.certSecret) throw new HttpError(503, "certificate_signing_unconfigured");
  return hmacHex(cfg.certSecret, signaturePayload(cert));
}

/**
 * Cryptographic integrity of a stored credential. Returns exactly one of
 *   "valid"       — the HMAC was recomputed and matches the stored signature
 *   "invalid"     — the record or its signature was altered (or is missing)
 *   "unavailable" — signing is not configured or verification errored
 * Callers must treat anything other than "valid" as not verified (fail closed).
 */
export async function signatureStatus(cfg, cert) {
  if (!cfg.certSecret) return "unavailable";
  if (typeof cert?.signature !== "string" || !/^[0-9a-f]{64}$/.test(cert.signature)) return "invalid";
  try {
    return safeEqual(await hmacHex(cfg.certSecret, signaturePayload(cert)), cert.signature) ? "valid" : "invalid";
  } catch (e) {
    console.error("certificate signature check failed", e?.message);
    return "unavailable";
  }
}

export async function activeCertificate(env, userId, courseId) {
  return env.DB.prepare("SELECT * FROM certificates WHERE user_id = ? AND course_id = ? AND status = 'active'").bind(userId, courseId).first();
}

/**
 * Issue a credential if (and only if) the learner is eligible. Idempotent:
 * an existing active credential is returned instead of creating a duplicate,
 * and a unique index guards against concurrent issuance.
 */
export async function issueIfEligible(env, cfg, user, course, { actorId = null, defer = null } = {}) {
  const existing = await activeCertificate(env, user.id, course.id);
  if (existing) return { certificate: existing, created: false };
  const elig = await checkEligibility(env, user, course);
  if (!elig.eligible) return { certificate: null, created: false, reasons: elig.reasons };
  // Never issue an unsigned credential. The learner's progress is kept and the
  // certificate can be claimed once signing is configured again.
  if (!cfg.certSecret) {
    console.error("certificate issuance skipped: signing is not configured");
    return { certificate: null, created: false, reasons: ["cert.reason.signing_unavailable"] };
  }

  const program = course.program_id ? await env.DB.prepare("SELECT title FROM programs WHERE id = ?").bind(course.program_id).first() : null;
  const base = await env.DB.prepare("SELECT title FROM courses WHERE id = ?").bind(course.id).first();
  const cert = {
    id: newId("crt_"),
    credential_id: credentialId(),
    user_id: user.id,
    course_id: course.id,
    attempt_id: elig.attempt?.id ?? null,
    credential_name: (user.credential_name || user.display_name).trim(),
    // Certificates record the course's canonical (source-language) title.
    course_title: base.title,
    program_title: program?.title ?? null,
    score_pct: elig.attempt?.score_pct ?? null,
    issued_at: nowIso(),
  };
  cert.signature = await signCertificate(cfg, cert);
  try {
    await env.DB.batch([
      env.DB.prepare(
        `INSERT INTO certificates (id, credential_id, user_id, course_id, attempt_id, credential_name, course_title, program_title, score_pct, issued_at, status, signature, created_at)
         VALUES (?,?,?,?,?,?,?,?,?,?, 'active', ?, ?)`,
      ).bind(cert.id, cert.credential_id, cert.user_id, cert.course_id, cert.attempt_id, cert.credential_name, cert.course_title, cert.program_title, cert.score_pct, cert.issued_at, cert.signature, cert.issued_at),
      env.DB.prepare("INSERT INTO certificate_events (id, certificate_id, event, actor_id, detail, created_at) VALUES (?,?,?,?,?,?)").bind(
        newId("ce_"),
        cert.id,
        "issued",
        actorId,
        JSON.stringify({ attempt_id: cert.attempt_id, score_pct: cert.score_pct }),
        cert.issued_at,
      ),
      auditStmt(env, actorId, "certificate.issue", "certificate", cert.id, { credential_id: cert.credential_id, course_id: course.id, user_id: user.id }),
      notifyStmt(env, user.id, { kind: "certificate", title: course.title, body: cert.credential_id, url: `/certificates/${cert.credential_id}` }),
      eventStmt(env, { userId: user.id, event: "certificate_issued", courseId: course.id }),
    ]);
  } catch (e) {
    if (/UNIQUE/i.test(String(e?.message))) {
      const again = await activeCertificate(env, user.id, course.id);
      if (again) return { certificate: again, created: false };
    }
    throw e;
  }
  await grantAchievement(env, user.id, "first_certificate", cert.credential_id);
  const count = await env.DB.prepare("SELECT COUNT(*) AS n FROM certificates WHERE user_id = ? AND status = 'active'").bind(user.id).first();
  if (count.n >= 3) await grantAchievement(env, user.id, "three_certificates");
  const mailId = await queueEmail(env, cfg, {
    user,
    template: "certificate_issued",
    vars: { course: course.title, credential: cert.credential_id, url: `${cfg.origin}/certificates/${cert.credential_id}` },
  });
  if (defer) defer(deliverById(env, cfg, mailId));
  return { certificate: { ...cert, status: "active" }, created: true };
}

export async function getByCredential(env, credential) {
  const id = String(credential || "").trim().toUpperCase();
  if (!/^AGA-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}$/.test(id)) return null;
  return env.DB.prepare(
    `SELECT ce.*, c.slug AS course_slug, c.level AS course_level, c.duration_minutes
       FROM certificates ce JOIN courses c ON c.id = ce.course_id WHERE ce.credential_id = ?`,
  )
    .bind(id)
    .first();
}

export async function revokeCertificate(env, certId, actorId, reason) {
  const cert = await env.DB.prepare("SELECT * FROM certificates WHERE id = ?").bind(certId).first();
  if (!cert) throw new HttpError(404, "not_found");
  if (cert.status === "revoked") return cert;
  const now = nowIso();
  await env.DB.batch([
    env.DB.prepare("UPDATE certificates SET status='revoked', revoked_at=?, revoked_reason=?, revoked_by=? WHERE id=?").bind(now, reason, actorId, certId),
    env.DB.prepare("INSERT INTO certificate_events (id, certificate_id, event, actor_id, detail, created_at) VALUES (?,?,?,?,?,?)").bind(newId("ce_"), certId, "revoked", actorId, reason, now),
    auditStmt(env, actorId, "certificate.revoke", "certificate", certId, { credential_id: cert.credential_id, reason }),
  ]);
  return { ...cert, status: "revoked", revoked_at: now, revoked_reason: reason };
}

export async function reinstateCertificate(env, certId, actorId) {
  const cert = await env.DB.prepare("SELECT * FROM certificates WHERE id = ?").bind(certId).first();
  if (!cert) throw new HttpError(404, "not_found");
  if (cert.status === "active") return cert;
  if (cert.user_id && (await activeCertificate(env, cert.user_id, cert.course_id))) throw new HttpError(409, "active_certificate_exists");
  const now = nowIso();
  await env.DB.batch([
    env.DB.prepare("UPDATE certificates SET status='active', revoked_at=NULL, revoked_reason=NULL, revoked_by=NULL WHERE id=?").bind(certId),
    env.DB.prepare("INSERT INTO certificate_events (id, certificate_id, event, actor_id, detail, created_at) VALUES (?,?,?,?,?,?)").bind(newId("ce_"), certId, "reinstated", actorId, null, now),
    auditStmt(env, actorId, "certificate.reinstate", "certificate", certId, { credential_id: cert.credential_id }),
  ]);
  return { ...cert, status: "active" };
}

/** LinkedIn's supported "Add license or certification" profile flow. */
export function linkedinAddUrl(cfg, cert) {
  const d = new Date(cert.issued_at);
  const p = new URLSearchParams({
    startTask: "CERTIFICATION_NAME",
    name: cert.course_title,
    issueYear: String(d.getUTCFullYear()),
    issueMonth: String(d.getUTCMonth() + 1),
    certUrl: `${cfg.origin}/verify/${cert.credential_id}`,
    certId: cert.credential_id,
  });
  if (cfg.linkedinOrgId) p.set("organizationId", cfg.linkedinOrgId);
  else p.set("organizationName", "AGRO-AI Academy");
  return `https://www.linkedin.com/profile/add?${p.toString()}`;
}

export function shareUrls(cfg, cert) {
  const verifyUrl = `${cfg.origin}/verify/${cert.credential_id}`;
  return {
    verifyUrl,
    linkedinAdd: linkedinAddUrl(cfg, cert),
    linkedinShare: `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(verifyUrl)}`,
    facebook: `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(verifyUrl)}`,
    pdf: `/certificates/${cert.credential_id}/pdf`,
  };
}
