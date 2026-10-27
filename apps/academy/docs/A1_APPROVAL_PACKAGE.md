# Course A1: release approval package

**Course:** Introduction to Artificial Intelligence in Agriculture (`crs_a1`)
**Prepared:** 2026-10-27, by engineering (with automated checks). This document
records what has been verified automatically and what a named person must still
review. **Nothing here is an approval.** Each approval is recorded by the
reviewer in production (Admin), against the exact content fingerprint; editing
the course afterwards voids it.

Where approvals happen: `https://academy.agroai-pilot.com/admin` (production).
Approvals recorded in staging do not carry over.

## 1. Release gates

| Gate | Who | Status | Where it is recorded |
|---|---|---|---|
| Production deployed, A1 unpublished | Engineering | See the deploy run in the release report | GitHub Actions *Academy Deploy* |
| 14 videos protected, mapped, playable for enrolled learners only | Engineering (automated, every deploy) | Verified on every staging deploy; production verified at deploy | Job summary of each deploy; `stream_protection` table |
| 14 English captions reviewed against the audio | Caption reviewer | **Open** | Admin → Videos → each video → Captions (status *reviewed*) |
| 14 videos watched in full and approved | Founder or delegated content owner | **Open** | Admin → Videos (status *approved*) |
| Academic review | Named subject-matter reviewer (not the lesson author) | **Open** | Admin → Courses → A1 → Reviews (*academic*) |
| Assessment review | Named assessment reviewer | **Open** | Admin → Courses → A1 → Reviews (*assessment*) |
| Accessibility review | Named accessibility tester (screen reader + keyboard) | **Open** | Admin → Courses → A1 → Reviews (*accessibility*) |
| Legal sign-off of `/terms`, `/privacy`, `/accessibility` | Counsel or founder | **Open** | Signed, dated note in company records (LAUNCH.md §7) |
| Publication | Founder | Blocked until all of the above | Admin → Courses → A1 → Publish (readiness panel all green) |

Order: captions and video approvals **before** the three reviews (a caption or
video change voids a review). Detailed reviewer instructions: `docs/REVIEWS.md`.

## 2. The fourteen videos

All 14 uploads are in Cloudflare Stream, mapped to their lessons by video
number, and protected on every deploy: signed URLs required, playback only on
the two Academy hosts, no downloads. The deploy also proves from outside that a
bare video id (stream, MP4, thumbnail) and an expired token are refused and a
fresh signed token plays, and fails if any of this is not true. Videos are
presented by **Joshua, an AI-generated presenter (Synthesia)**; every lesson
page states this under the player.

| # | Lesson | Video record |
|---|---|---|
| 1 | Welcome to the course | `vid_a1_welcome` |
| 2 | From rules to learning: what AI is (and isn't) | `vid_a1_what_is_ai` |
| 3 | Why agriculture is turning to AI now | `vid_a1_why_now` |
| 4 | Data: the raw material of agricultural AI | `vid_a1_data` |
| 5 | Models, training and predictions | `vid_a1_models` |
| 6 | From prediction to recommendation | `vid_a1_recommendations` |
| 7 | Planning and planting | `vid_a1_planning` |
| 8 | Case study: irrigation and water management | `vid_a1_irrigation` |
| 9 | Crop health monitoring from above and up close | `vid_a1_crop_health` |
| 10 | Harvest, markets and the supply chain | `vid_a1_harvest` |
| 11 | Limits, errors and when to challenge a recommendation | `vid_a1_limits` |
| 12 | Data ownership, privacy and trust | `vid_a1_data_rights` |
| 13 | Practical exercise: evaluate an AI recommendation | `vid_a1_exercise` |
| 14 | Course summary and next steps | `vid_a1_summary` |

**Video approver checks, per video:** plays to the end; matches its lesson;
official AGRO-AI logo correct; no factual error in narration; nothing that
contradicts the lesson text; audio clear. Then set the video to *approved*.

## 3. Captions and transcripts

The production deploy asks Stream for an English machine draft of each video
and imports it as a **draft** (status `machine`): learners never see it, and it
is removed from Stream's player. The *Academy Preflight* production job prints
a mechanical check of every draft and reviewed caption
(`scripts/caption-qa.mjs`): lines over 42 characters, more than two lines per
cue, reading speed over 20 characters per second, cues under 1 s or over 7 s,
overlaps, whether the captions cover the whole video, and likely
misrecognitions of course terms (AGRO-AI, NDVI, evapotranspiration, ET₀/ETc,
Kc). It reports counts and cue numbers only.

**Caption reviewer, per video:** open the draft in Admin → Videos → Captions,
correct it against the audio (at least 99% word accuracy; course terms spelled
as in the lesson text; numbers and units exact; the checker's flagged cues
fixed), save as *reviewed*. The next production deploy publishes exactly the
reviewed captions to Stream's player and removes every other track; the
lesson's transcript tab is built from the reviewed caption.

## 4. Academic content: automated and AI pre-review

#### Automated content and assessment checks (all passed)

- Lessons with text: 14; questions: 48 (27 single-answer).
- Question types: single 26, true_false 6, ordering 2, multiple 6, matching 3, short_answer 2, case 3.
- Checked for every question: answer key well formed for its type (exactly one correct option for single-answer, at least one but not all for multiple-answer, boolean for true/false, unique steps and pairs for ordering and matching, accepted answers for short answer), a teaching explanation, a valid difficulty and lesson link, no duplicate prompt.
- Exam bank covers 11 of 14 lessons. Lessons tested by no question: Welcome to the course; Practical exercise: evaluate an AI recommendation; Course summary and next steps.
- Correct-answer position (single-answer): A=26, B=1 (options are shuffled for learners, so position bias does not reach them).
- Correct answer is the uniquely longest option in 13 of 27 questions (48%). Above ~40% is a known cue for test-wise learners: reviewer to judge.

| Assessment | Bank | Difficulty | Draw | Pool |
|---|---|---|---|---|
| asm_a1_q1 | bnk_a1_m1 | any | 5 | 6 |
| asm_a1_q2 | bnk_a1_m2 | any | 5 | 6 |
| asm_a1_q3 | bnk_a1_m3 | any | 5 | 6 |
| asm_a1_exam | bnk_a1_exam | easy | 6 | 9 |
| asm_a1_exam | bnk_a1_exam | medium | 10 | 14 |
| asm_a1_exam | bnk_a1_exam | hard | 4 | 7 |

| Lesson | Est. min | Words | Reading min (200 wpm) | Narrated |
|---|---|---|---|---|
| Welcome to the course | 5 | 322 | 2 | yes |
| From rules to learning: what AI is (and isn't) | 12 | 539 | 3 | yes |
| Why agriculture is turning to AI now | 10 | 420 | 2 | yes |
| Data: the raw material of agricultural AI | 14 | 427 | 2 | yes |
| Models, training and predictions | 14 | 436 | 2 | yes |
| From prediction to recommendation | 12 | 360 | 2 | yes |
| Planning and planting | 10 | 272 | 1 | yes |
| Case study: irrigation and water management | 15 | 409 | 2 | yes |
| Crop health monitoring from above and up close | 12 | 335 | 2 | yes |
| Harvest, markets and the supply chain | 10 | 252 | 1 | yes |
| Limits, errors and when to challenge a recommendation | 12 | 328 | 2 | yes |
| Data ownership, privacy and trust | 10 | 313 | 2 | yes |
| Practical exercise: evaluate an AI recommendation | 15 | 334 | 2 | yes |
| Course summary and next steps | 6 | 267 | 1 | yes |

Notes for reviewers:
- q_a1m3_2: short answer accepts only "NDVI"; reviewer to check reasonable variants
- q_a1x_e9: short answer accepts only "transpiration", "evapotranspiration"; reviewer to check reasonable variants


### AI pre-review of the lesson text (not an approval)

All 14 lessons were read in full. The content is accurate, appropriately
scoped for a non-technical audience, and consistently careful about AI's
limits (calibrated trust, human accountability, verification). Formulas and
figures checked: ETc = ET₀ × Kc; NDVI = (NIR − Red) ÷ (NIR + Red) with the
stated typical ranges; the irrigation scenario arithmetic (18 mm ÷ 5 mm/day ≈
3.6 days); exam rules (20 questions, 30 minutes, 80%, one-hour retry) match the
configured assessment. Two items for the academic reviewer to decide:

1. **Course structure statement.** *Welcome to the course* says "Each module
   contains short lessons and ends with a quiz", but Module 4 (*Using AI
   responsibly*) has no quiz; it ends with the summary and the final exam.
   Suggested wording: "Modules 1–3 each end with a practice quiz; Module 4
   leads to the final exam." Check whether video 1 narrates the same sentence.
2. **Water statistic attribution.** *Why agriculture is turning to AI now*
   attributes "roughly 70% of global freshwater withdrawals" to *irrigated*
   agriculture. FAO (AQUASTAT) attributes about 70% to agriculture as a whole,
   most of it irrigation. Suggested wording: "agriculture accounts for roughly
   70% of global freshwater withdrawals, most of it for irrigation."

### Corrections already made by engineering (2026-10-27)

The automated check found four question defects, now corrected in the course
source and, for existing databases, by migration `0010_a1_question_fixes.sql`
(applies only while A1 is unpublished):

- `q_a1x_e8` (exam, multiple answer) marked **all four** options correct, so
  ticking every box always scored. A plausible distractor was added ("A
  vendor's claim about how accurate its model is") and the explanation now
  teaches why it is not farm data.
- `q_a1m3_3`, `q_a1m3_5`, `q_a1x_e6`: explanations were one-liners; each now
  teaches the concept from its lesson.

The assessment reviewer should still judge item quality, the 80% standard, and
the two short-answer keys (NDVI; transpiration/evapotranspiration).

## 5. Accessibility

Automated: the CI scan (axe-core, WCAG 2.2 AA) covers public, learner and
admin pages with no serious or critical violations, and the browser journey
checks keyboard use, mobile layout, dark theme and right-to-left. The
accessibility reviewer must test with a screen reader and keyboard only:
player controls and captions in Stream's player, lesson text, the transcript
tab, every question type (including ordering and matching), the exam timer,
and the certificate PDF and verification page. Captions must be reviewed first.

## 6. Legal documents (for counsel)

Engineering corrected statements in `src/content/legal.js` that were out of
date (updated 2026-10-27); counsel should review the documents as they now
stand:

- **Terms:** learners may not copy, record, download or redistribute course
  material; pages and the player display the learner's name and a short
  account reference so copies can be traced.
- **Privacy:** adds the security record (sign-in events, refused or unusually
  frequent video-playback requests); lists Cloudflare file storage and video
  streaming among the providers.
- **Accessibility statement:** videos now exist (the previous text said they
  were in production); English captions are published only after human
  review; the PDF certificate embeds fonts for many scripts.

Checklist for counsel: `docs/LAUNCH.md` §7. Also confirm: the AI-presenter
disclosure wording; the certificate's stated status ("not an academic degree,
government qualification or accredited professional license"); minimum age 16.

## 7. Content protection (what is and is not possible)

- Videos: signed, expiring, non-downloadable tokens issued only to enrolled
  learners and staff; renewal is rate limited and refusals are logged; requests
  beyond the limit are recorded in the audit log for staff review.
- Course pages and the player show the learner's name and account reference
  (a visible licence mark), so a recording or copy is attributable.
- Pages are private, not cached and not indexed.
- **Screenshots and screen recording cannot be prevented by any web
  application**; the licence mark makes them traceable, and the Terms prohibit
  them. Stream's own full-screen button shows the video without the page's
  licence mark; the Academy's full-screen button keeps it.
