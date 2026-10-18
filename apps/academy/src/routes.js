// Route table. `auth` requires a signed-in learner; `perm` requires an admin
// permission (see ROLE_PERMISSIONS). All POST routes are CSRF-checked.
import * as pub from "./pages/public.js";
import * as auth from "./pages/auth.js";
import * as catalog from "./pages/catalog.js";
import * as learn from "./pages/learn.js";
import * as assess from "./pages/assess.js";
import * as certs from "./pages/certs.js";
import * as dash from "./pages/dashboard.js";
import * as account from "./pages/account.js";
import * as ops from "./pages/admin/ops.js";
import * as cur from "./pages/admin/curriculum.js";
import * as asm from "./pages/admin/assessments.js";
import * as people from "./pages/admin/people.js";
import * as tr from "./pages/admin/translations.js";

const AUTH = { auth: true };
const p = (perm) => ({ perm });

export function registerRoutes(r) {
  // Public site
  r.get("/", pub.home);
  r.get("/programs", pub.programs);
  r.get("/paths", pub.paths);
  r.get("/instructors", pub.instructorsPage);
  r.get("/about", pub.about);
  r.get("/faq", pub.faq);
  r.get("/help", pub.help);
  r.get("/contact", (c) => pub.contact(c, { sent: c.url.searchParams.get("sent") === "1" }));
  r.post("/contact", pub.contactSubmit);
  for (const doc of ["terms", "privacy", "accessibility"]) r.get(`/${doc}`, (c) => ((c.params.doc = doc), pub.legal(c)));
  r.post("/preferences/theme", pub.setTheme);
  r.get("/art/:motif/:palette/:file", pub.art);
  r.get("/sitemap.xml", pub.sitemap);
  r.get("/robots.txt", pub.robots);
  r.get("/healthz", pub.health);
  r.get("/languages", pub.languages);
  r.get("/__staging/inbox", pub.stagingInbox);

  // Authentication
  r.get("/register", (c) => auth.registerPage(c));
  r.post("/register", auth.register);
  r.get("/login", (c) => auth.loginPage(c));
  r.post("/login", auth.login);
  r.post("/logout", auth.logout, AUTH);
  r.get("/verify-email", auth.verifyEmail);
  r.post("/verify-email/resend", auth.resendVerification, AUTH);
  r.get("/forgot-password", (c) => auth.forgotPage(c));
  r.post("/forgot-password", auth.forgot);
  r.get("/reset-password", (c) => auth.resetPage(c));
  r.post("/reset-password", auth.reset);
  r.get("/auth/google", auth.googleStart);
  r.get("/auth/google/callback", auth.googleCallback);

  // Catalog and enrollment
  r.get("/courses", catalog.catalog);
  r.get("/courses/:slug", catalog.courseLanding);
  r.post("/courses/:slug/enroll", catalog.enrollAction, AUTH);
  r.post("/courses/:slug/withdraw", catalog.withdrawAction, AUTH);
  r.post("/courses/:slug/feedback", learn.courseFeedback, AUTH);

  // Classroom
  r.get("/learn/:course", learn.resume, AUTH);
  r.get("/learn/:course/:lesson", learn.lessonPage);
  r.post("/learn/:course/:lesson/complete", learn.completeLesson, AUTH);
  r.post("/learn/:course/:lesson/notes", learn.addNote, AUTH);
  r.post("/learn/:course/:lesson/notes/:note/delete", learn.deleteNote, AUTH);
  r.post("/learn/:course/:lesson/bookmarks", learn.addBookmark, AUTH);
  r.post("/learn/:course/:lesson/feedback", learn.lessonFeedback, AUTH);
  r.post("/api/progress", learn.progressApi, AUTH);
  r.get("/captions/:file", learn.captions);
  r.get("/resources/:id", learn.resourceDownload, AUTH);

  // Assessments
  r.get("/assessments/:id", assess.intro, AUTH);
  r.post("/assessments/:id/start", assess.start, AUTH);
  r.get("/attempts/:id", assess.attemptPage, AUTH);
  r.post("/api/attempts/:id/save", assess.saveApi, AUTH);
  r.post("/attempts/:id/submit", assess.submit, AUTH);

  // Credentials
  r.get("/certificates/:cred", certs.certificatePage, AUTH);
  r.get("/certificates/:cred/pdf", certs.certificatePdfRoute, AUTH);
  r.post("/certificates/claim/:slug", certs.claim, AUTH);
  r.get("/verify", certs.verifyForm);
  r.get("/verify/:cred", certs.verifyPage);

  // Learner workspace
  r.get("/dashboard", dash.overview, AUTH);
  r.get("/dashboard/courses", dash.coursesTab, AUTH);
  r.get("/dashboard/results", dash.resultsTab, AUTH);
  r.get("/dashboard/history", dash.historyTab, AUTH);
  r.get("/dashboard/certificates", dash.certificatesTab, AUTH);
  r.post("/dashboard/goals", dash.addGoal, AUTH);
  r.post("/dashboard/goals/:id", dash.updateGoal, AUTH);
  r.post("/dashboard/notifications/read", dash.markNotificationsRead, AUTH);
  r.get("/account", (c) => account.accountPage(c), AUTH);
  r.post("/account/profile", account.saveProfile, AUTH);
  r.post("/account/preferences", account.savePreferences, AUTH);
  r.post("/account/password", account.changePassword, AUTH);
  r.post("/account/sessions/revoke", account.revokeOtherSessions, AUTH);
  r.get("/account/export", account.exportData, AUTH);
  r.post("/account/delete", account.deleteAccountAction, AUTH);

  // Administration
  r.get("/admin", ops.overview, p("analytics.view"));
  r.get("/admin/analytics/course/:id", ops.courseEngagement, p("analytics.view"));
  r.get("/admin/feedback", ops.feedback, p("feedback.view"));
  r.post("/admin/feedback/:id", ops.feedbackUpdate, p("feedback.view"));
  r.get("/admin/support", ops.support, p("support.manage"));
  r.post("/admin/support/:id", ops.supportUpdate, p("support.manage"));
  r.get("/admin/email", ops.emailOutbox, p("support.manage"));
  r.post("/admin/email/flush", ops.emailFlush, p("support.manage"));
  r.get("/admin/audit", ops.auditLog, p("audit.view"));

  r.get("/admin/courses", cur.courses, p("courses.edit"));
  r.get("/admin/courses/new", cur.newCourse, p("courses.edit"));
  r.post("/admin/courses", cur.createCourse, p("courses.edit"));
  r.get("/admin/courses/:id", cur.editCourse, p("courses.edit"));
  r.post("/admin/courses/:id", cur.saveCourse, p("courses.edit"));
  r.post("/admin/courses/:id/status", cur.setCourseStatus, p("courses.edit"));
  r.post("/admin/courses/:id/discard", cur.discardDraft, p("courses.edit"));
  r.post("/admin/courses/:id/reviews", cur.saveReview, p("courses.review"));
  r.post("/admin/courses/:id/modules", cur.addModule, p("courses.edit"));
  r.post("/admin/courses/:id/assessments", asm.createAssessment, p("assessments.edit"));
  r.post("/admin/modules/:id", cur.saveModule, p("courses.edit"));
  r.post("/admin/modules/:id/delete", cur.deleteModule, p("courses.edit"));
  r.post("/admin/modules/:id/lessons", cur.addLesson, p("courses.edit"));
  r.get("/admin/lessons/:id", cur.editLesson, p("courses.edit"));
  r.post("/admin/lessons/:id", cur.saveLesson, p("courses.edit"));
  r.post("/admin/lessons/:id/delete", cur.deleteLesson, p("courses.edit"));
  r.post("/admin/lessons/:id/resources", cur.addResource, p("courses.edit"));
  r.post("/admin/lessons/:id/upload", cur.uploadResource, p("courses.edit"));
  r.post("/admin/resources/:id/delete", cur.deleteResource, p("courses.edit"));
  r.get("/admin/videos", cur.videos, p("courses.edit"));
  r.post("/admin/videos", cur.createVideo, p("courses.edit"));
  r.get("/admin/videos/:id", cur.editVideo, p("courses.edit"));
  r.post("/admin/videos/:id", cur.saveVideo, p("courses.publish"));
  r.post("/admin/videos/:id/captions", cur.addCaptions, p("courses.edit"));
  r.post("/admin/captions/:id/delete", cur.deleteCaptions, p("courses.edit"));
  r.get("/admin/instructors", cur.instructors, p("instructors.edit"));
  r.post("/admin/instructors", cur.saveInstructor, p("instructors.edit"));
  r.get("/admin/programs", cur.programsAdmin, p("courses.edit"));
  r.post("/admin/programs/:id", cur.saveProgram, p("courses.publish"));
  r.post("/admin/paths/:id", cur.savePath, p("courses.publish"));

  r.get("/admin/assessments/:id", asm.editAssessment, p("assessments.edit"));
  r.post("/admin/assessments/:id", asm.saveAssessment, p("assessments.edit"));
  r.post("/admin/assessments/:id/rules", asm.addRule, p("assessments.edit"));
  r.post("/admin/rules/:id/delete", asm.deleteRule, p("assessments.edit"));
  r.get("/admin/banks", asm.banks, p("assessments.edit"));
  r.post("/admin/banks", asm.createBank, p("assessments.edit"));
  r.get("/admin/banks/:id", asm.bankDetail, p("assessments.edit"));
  r.post("/admin/banks/:id/cases", asm.addCase, p("assessments.edit"));
  r.get("/admin/banks/:id/questions/new", asm.questionForm, p("assessments.edit"));
  r.post("/admin/banks/:id/questions", asm.saveQuestion, p("assessments.edit"));
  r.get("/admin/questions/:qid", asm.questionForm, p("assessments.edit"));
  r.post("/admin/questions/:qid", asm.saveQuestion, p("assessments.edit"));
  r.get("/admin/grading", asm.gradingQueue, p("grading"));
  r.get("/admin/grading/:id", asm.gradeAttemptPage, p("grading"));
  r.post("/admin/grading/:id/:qid", asm.gradeItem, p("grading"));

  r.get("/admin/learners", people.learners, p("learners.view"));
  r.get("/admin/learners/:id", people.learnerDetail, p("learners.view"));
  r.post("/admin/learners/:id/resend", people.resendVerification, p("learners.manage"));
  r.post("/admin/learners/:id/status", people.setStatus, p("learners.manage"));
  r.post("/admin/learners/:id/roles", people.setRoles, p("learners.manage"));
  r.post("/admin/learners/:id/enroll", people.enrollLearner, p("learners.manage"));
  r.get("/admin/certificates", people.certificates, p("certificates.manage"));
  r.post("/admin/certificates/issue", people.issue, p("certificates.manage"));
  r.post("/admin/certificates/:id/revoke", people.revoke, p("certificates.manage"));
  r.post("/admin/certificates/:id/reinstate", people.reinstate, p("certificates.manage"));

  r.get("/admin/translations", tr.overview, p("translations.edit"));
  r.get("/admin/translations/ui", tr.uiEditor, p("translations.edit"));
  r.post("/admin/translations/ui", tr.uiSave, p("translations.edit"));
  r.get("/admin/translations/content", tr.contentEditor, p("translations.edit"));
  r.post("/admin/translations/content", tr.contentSave, p("translations.edit"));
  r.get("/admin/translations/export", tr.exportContent, p("translations.edit"));
  r.post("/admin/translations/import", tr.importContent, p("translations.edit"));
}
