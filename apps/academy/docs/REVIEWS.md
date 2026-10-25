# Course A1: approval workflow for human reviewers

A1 (*Introduction to Artificial Intelligence in Agriculture*) cannot be
published until named people have approved it. This document is the packet
for those people. The Academy records each approval against a fingerprint of
the exact course content: any later edit voids it. That covers lesson text,
quiz or exam questions, a video record and a caption. Nothing here is
approved by automation, and no review may be recorded on someone's behalf
without their actual review.

## Order of work (each step depends on the one before)

All approvals are stored per database. Video approvals, reviewed captions and
the three reviews count only where they are recorded, so they are done **in
production**. Staging is for rehearsal, and nothing recorded there carries
over. The 14 videos are shared, so production holds the one reviewed caption
set that Stream's player shows.

| # | Step | Who | Where |
|---|---|---|---|
| 1 | ~~Upload all 14 videos~~: done. 14/14 protected and verified (staging deploy run 40216697146) | Founder | — |
| 2 | Production credentials: the scoped Cloudflare token in `academy-production`, the signing key, backup passphrase, Resend key and admin address, plus required reviewers on the environment (LAUNCH.md §2) | Founder | GitHub → Settings → Environments |
| 3 | Merge PR #618, then authorize the production deploy: *Academy Deploy*, target production, confirmation `deploy academy production`. A1 stays unpublished. The deploy links the 14 videos, verifies their protection and imports 14 caption drafts | Founder | GitHub Actions |
| 4 | Sign in to production with the admin address and confirm Admin opens | Founder | `academy.agroai-pilot.com/admin` |
| 5 | For each of the 14 videos: correct the loaded draft against the audio and save it as *reviewed*. Then run the production deploy again, so the reviewed files reach the player | Caption reviewer | Admin → Videos → each video → Captions |
| 6 | For each of the 14 videos: watch it in full, check the official logo, and set it to *approved* | Founder or delegated content owner | Admin → Videos |
| 7 | Academic, assessment and accessibility reviews | Named reviewers | Admin → Courses → A1 → Reviews |
| 8 | Legal sign-off of `/privacy`, `/terms`, `/accessibility` | Counsel or founder | Outside the app (signed, dated note); see LAUNCH.md §7 |
| 9 | Publish A1. The readiness panel must be all green: 14 approved, playable and protected videos, reviewed captions, 3 reviews | Founder | Admin → Courses → A1 |

Steps 5 and 6 must be finished before step 7: changing a caption or a video
after a review voids that review.

## How a review is recorded

In Admin → Courses → A1 → *Reviews*:
1. Choose the review type and the decision (*approved* or *changes requested*).
2. Enter the reviewer's name and role, if they are not the signed-in account.
3. Add notes: what was checked, and any conditions.
4. Tick *I confirm this review covered the course content as it is now*.

The record keeps the decision, reviewer, notes, time and content fingerprint,
and is audited. *Changes requested* blocks publication until a later approval.

## 1. Academic review

**Reviewer:** someone with subject expertise in agronomy and applied machine
learning. It must not be the author of the lessons.

Check all 17 lessons, the 14 videos (watch them; they are 1–3 minutes each)
and the reviewed transcripts:
- Every factual claim is accurate and current, with no overstated AI capabilities.
- Agronomic examples (irrigation, crop health, planting, harvest, markets) are realistic.
- Lesson objectives match the content. Each video matches its lesson; note that the final video titles differ from the lesson titles.
- The level suits the stated audience: beginner, no technical background.
- Safety: lessons 11–13 say clearly when to challenge or reject a recommendation.
- The AI instructor (Joshua) is disclosed as an AI avatar wherever he appears.
- Time estimates are realistic. The videos run 1–3 minutes against lesson estimates of 5–15 minutes, which include reading. Confirm or ask for changes.

## 2. Assessment review

**Reviewer:** someone experienced in assessment design (an educator or
psychometrics background), ideally different from the academic reviewer.

Check in Admin → Assessments for A1:
- The 3 module quizzes each draw 5 of 6 questions; pass mark 60%.
- The certification exam draws 20 questions from a 30-question bank: 6 of 9 easy, 10 of 14 medium, 4 of 7 hard. Time limit 30 minutes, pass mark 80%, 60-minute cooldown, unlimited attempts.
- Every question has one defensible correct answer, and an explanation that teaches.
- Questions test the lesson objectives, not trivia, and the distractors are plausible.
- Any random draw is of comparable difficulty (rules are per difficulty band).
- The 80% standard is appropriate for a certificate that carries the AGRO-AI name.
- A certificate requires all lessons, narrated ones included (completed by server-measured watching), plus a passed exam. Registering, opening a video or editing progress never earns one.

## 3. Accessibility review

**Reviewer:** someone experienced in WCAG 2.2 AA testing, with a screen reader
(VoiceOver or NVDA) and keyboard-only use.

- **Captions:** all 14 English captions have been human-corrected (step 2): terminology, numbers, speaker text and timing. The transcript tab matches.
- **Player:** keyboard operable (play/pause, seek, speed, captions, fullscreen); controls labelled; visible focus. Check on desktop Chrome and Safari, and on iOS and Android.
- **Lesson text:** headings in order, link text meaningful, contrast in light and dark themes, readable at 200% zoom and at 320 px width.
- **Exams:** timer announced, autosave, questions readable by screen reader, nothing that relies on color alone.
- **Certificate:** the PDF has a text layer, and the verification page is readable.
- The automated axe-core scan (CI, 38 pages, 0 serious or critical) is a starting point, not a substitute for this review.

## Caption review (step 2)

**Reviewer:** a careful English editor. Ideally the accessibility reviewer
checks a sample afterwards.

The drafts come from Stream's speech recognition and are marked `machine`.
Learners never see them. For each video:
1. Open the draft.
2. Correct it against the audio, at least 99% word accuracy: agricultural terms, product names, numbers and units, and line breaks of no more than 2 lines and 42 characters.
3. Save it with status *reviewed*.

The next deploy publishes the reviewed file into Stream's player.

## 4. Legal sign-off (outside the app)

Use the checklist in LAUNCH.md §7. Record the sign-off as a dated note from
counsel or the founder in the company's records. The app has no record type
for it, so it does not gate publication automatically. Do not publish A1
until it exists.

## Evidence available to reviewers

- **Staging, as a staff account:** `https://academy-staging.agroai-pilot.com/admin`. The administrator bootstrap must be fixed first; see LAUNCH.md §2.
- **Stream protection report:** the latest *Academy Deploy* run, job summary.
- **Automated test results:** the latest CI run on PR #618 covers unit and integration tests, the browser journey and the accessibility scan.
