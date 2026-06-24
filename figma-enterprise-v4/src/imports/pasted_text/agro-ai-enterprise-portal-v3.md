Refine the current AGRO-AI Enterprise Portal design into Version 3.

Important: edit the existing generated design. Do not only summarize what you did. Do not create a marketing page. Do not leave placeholder pages empty. Build actual high-fidelity product screens on the canvas.

Use Figma-native structure:

* Create clean desktop frames at 1440 × 1024.
* Use Auto Layout for sidebar, topbar, cards, rows, tables, buttons, pills, and workflow steps.
* Use an 8px spacing system.
* Use consistent component styles for cards, metric cards, status pills, buttons, table rows, nav items, and integration chips.
* Use reusable components where possible.
* Keep layers clearly named.
* Align everything to a clean grid.
* Avoid overflow, overlaps, cropped text, or squeezed columns.
* Keep all text readable at desktop size.
* Do not leave giant empty white/beige areas.

Design target:
This should feel like a premium enterprise product workspace, not a landing page and not a generic dashboard template.

Reference quality:

* Claude / ChatGPT for calm AI workspace feel
* Linear for typography, spacing, density, and product cleanliness
* Stripe Dashboard for enterprise trust
* Ramp for finance-grade clarity
* Vercel for minimal premium software polish
* Palantir-style operational seriousness, but cleaner and less heavy

Product:
AGRO-AI is an AI-native operating system for farm operations, WaterOps, evidence workflows, assurance readiness, and agent-assisted work.

Primary design principle:
Function first. Design supports the work.
The user should immediately understand:

* what workspace they are in
* what is blocked
* what proof exists
* what proof is missing
* what the AI recommends
* what needs human review
* what can be exported
* what requires action now

Visual direction:

* More premium
* More minimalist
* More sleek
* More magical, but not sci-fi
* More corporate
* More product-first
* More operational
* More useful
* Less placeholder
* Less empty
* Less generic SaaS
* Less marketing
* Less “big hero”
* More real work surface

Colors:
Background: #F6F4EE
Surface: #FFFEFA
Sidebar: #061D15
Sidebar elevated item: #0B2A1F
Primary green: #16533C
Action green: #1F7350
Accent lime: #9BD84B, use sparingly
Text: #10231B
Muted text: #68776F
Border: rgba(16,35,27,0.12)
Warning: #B7791F
Danger: #B42318

Typography:
Use Inter or similar.
Tight hierarchy.
No huge marketing headline.
No tiny unreadable labels.
Use:

* Page title: 28–36px
* Card title: 18–22px
* Metric value: 30–38px
* Body: 14–16px
* Labels: 11–12px uppercase

Global layout:
Every screen should use the same application shell:

* Left sidebar: 280px wide
* Topbar: 72px high
* Main content max width: 1180–1220px
* Content padding: 32px
* No right rail
* No floating panels
* No overlap
* No giant empty sections

Sidebar:
Keep the sidebar, but refine it.
Top:
AGRO-AI logo
AGRO-AI
Enterprise Portal

Navigation:
Overview
WaterOps
Assurance
Evidence
Reports
Agents

Admin:
Integrations
Sources
Settings

Bottom workspace card:
Evaluation workspace
Reviewer evaluation required before external use.

Sidebar refinement:

* active nav should be elegant, not too bright
* nav item height 44–48px
* subtle border or inset accent
* keep it clean and serious

Topbar:
Left:
North Coast Vineyard
Wine grapes · Coastal production block

Right:
Evaluation workspace badge
Not live badge
Updated a few minutes ago
Run Agent button

Topbar should feel like a real app context bar.

Now rebuild these screens with real content:

SCREEN 1 — Overview

This must be the most polished screen.

Page title:
Overview

Top workspace summary card:
Eyebrow: AGRO-AI ENTERPRISE PORTAL
Title: Operational overview
Subtitle: Monitor proof coverage, water decisions, assurance readiness, and agent-assisted work in one workspace.
Actions:
Run Agent
Attach Evidence
Prepare Export

Make this summary card compact. Do not make it a giant marketing hero.

Next to it, or integrated as a strong secondary panel, create an AI state panel:
Title: What AGRO-AI sees
Main finding: Readiness is blocked by missing proof.
Text: The package can be prepared, but external use remains blocked until required records are attached and reviewed.

Rows:
Proof present — Controller events, weather context, crop profile
Proof missing — Water proof, input applications, traceability
Next action — Attach scoped water measurement proof
Human gate — Required before external use

This panel should feel like a premium AI reasoning/status panel, not a sales card.

Metrics row:
Four compact cards:
Assurance readiness — 72%
Open actions — 7
Missing proof — 4
Agent runs — 3

Each metric should have a one-line explanation:

* Package completeness toward reviewer handoff
* Open tasks across evidence and assurance
* Required items not attached or verified
* Recent automated runs in this workspace

Main grid:
Left 60% width:
Card: Highest-priority work
Use a real work queue table/list with 4 rows.

Rows:

1. Attach water measurement proof
   Reason: Required for assurance export
   Status: Approval required
   Action: Review

2. Request input application records
   Reason: Missing supporting document set
   Status: Pending document
   Action: Follow up

3. Prepare proof package draft
   Reason: Draft export ready after missing proof is resolved
   Status: Blocked
   Action: Open

4. Review traceability mapping
   Reason: Evidence linked but not reviewer-checked
   Status: Needs review
   Action: Review

Right 40% width:
Card: Evidence-backed automation
Show 6 compact workflow states:
Ingest
Normalize
Classify
Detect gaps
Propose actions
Human review

First four should look complete/active.
Last two should look pending/review.
Add note:
Automation accelerates preparation. Human review governs external use.

Bottom section:
Connected systems
Chips:
WiseConn integrated
Talgil integrated
CropX compatible
Telemetry APIs compatible

Use provided WiseConn and Talgil logos subtly.
Small note:
Compatibility indicates technical integration capability. It does not imply endorsement, certification, or formal partnership unless explicitly stated.

SCREEN 2 — Assurance

Do not leave this page almost empty. It must look like a real assurance workbench.

Page title:
Assurance

Top summary:
Assurance readiness: 62%
Subtitle:
Package completeness toward reviewer handoff. Missing proof items block external use.

Top metric row:
Readiness — 62%
Missing proof — 4
Proof domains complete — 3/7
Reviewer gates — 2 pending

Main layout:
Left/main card:
Missing proof queue

Create a table with columns:
Requirement
Domain
Why it matters
Status
Action

Rows:
Water measurement proof | WaterOps | Required for assurance export | Approval required | Review
Input application records | Input proof | Missing supporting document set | Pending document | Follow up
Traceability events | Traceability | Needed for lot-level proof chain | Needs review | Review
Boundary reference | Farm summary | Required for farm context | Missing | Attach

Right card:
Proof coverage

Sections:
Proof present:

* Controller events
* Weather context
* Crop profile

Proof missing:

* Water measurement
* Input applications
* Traceability events
* Boundary reference

Next best action:
Attach water measurement proof.

Human review:
Required before external use.

Bottom card:
Reviewer-safe language
Show:

* Draft package only
* Not certified
* Not regulator-approved
* Not legal determination
* Human reviewer required

This page should feel like an audit/proof preparation workbench.

SCREEN 3 — Evidence

Do not leave this page empty. It must feel like a real evidence vault.

Page title:
Evidence

Top summary:
Evidence Vault
Subtitle:
Classify field records, controller data, and uploaded files into proof domains.

Actions:
Upload evidence
Classify with Agent
Map to proof domain

Main table:
Columns:
Evidence
File / Source
Proof domain
Status
Confidence
Issue
Action

Rows:
Controller events | controller_events.csv | Water proof | Mapped | High | None | Open
Weather context | weather_window.csv | Water proof | Mapped | Medium | Reviewer check | Open
Crop profile | crop_profile.pdf | Farm summary | Mapped | High | None | Open
Input application | Missing record | Input proof | Missing | — | Required record missing | Request
Traceability events | Missing record | Traceability | Missing | — | Required for lot chain | Request

Right side or bottom card:
Evidence actions

* Upload source file
* Connect controller
* Classify records
* Resolve missing proof
* Prepare export

SCREEN 4 — Reports

Do not leave Reports as one empty card.
Make it useful.

Page title:
Reports

Top summary:
Reports & Exports
Subtitle:
Prepare draft proof packages and operational reports with reviewer gates.

Report cards:

1. Assurance Passport PDF
   Status: Blocked by missing proof
   Action: Resolve blockers

2. Buyer Proof Pack
   Status: Draftable
   Action: Prepare draft

3. WaterOps Evidence Pack
   Status: Ready for reviewer evaluation
   Action: Generate

4. Lender / Landowner Risk Summary
   Status: Draftable
   Action: Prepare summary

Add a warning note:
External use requires reviewer approval. AGRO-AI does not claim certification or regulatory approval.

SCREEN 5 — Agents

Make this feel like an AI-native workspace, not a blank page.

Page title:
Agents

Top summary:
AGRO-AI Agent
Subtitle:
Analyze evidence, detect gaps, propose actions, and prepare review-ready work packages.

Main panel:
Current run state

Show workflow:
Ingest sources
Normalize records
Classify evidence
Detect missing proof
Generate recommendations
Wait for human approval

Show statuses for each.

Right panel:
Latest findings

* Readiness remains incomplete until water measurement proof is attached.
* Input application records are missing.
* Traceability mapping needs reviewer check.
* WaterOps evidence can be prepared as a draft.

Bottom:
Agent actions

* Run gap analysis
* Prepare proof draft
* Create follow-up tasks
* Refresh readiness

Interaction style:
Do not overuse icons.
Use clean rows, tables, and subtle status pills.
Use precise product language.
Do not exaggerate with marketing claims.
Do not say “fully automated compliance”.
Do not say “certified”.

Important improvements over Version 2:

* Make every page feel complete enough to evaluate.
* Add real operational rows and tables.
* Reduce huge empty space.
* Make the design more premium through typography, spacing, and restraint.
* Use fewer oversized blocks.
* Make AI panels feel like system intelligence, not marketing.
* Make primary work queue the center of gravity.
* Keep all screens consistent.
* Keep everything editable in Figma.
* Ensure all content fits inside 1440 × 1024 without awkward scrolling in the frame.
* Avoid duplicated topbars or broken frames.

Final result:
Produce polished, high-fidelity, editable desktop frames for:

* Overview
* Assurance
* Evidence
* Reports
* Agents

The Overview screen should be the flagship screen. Assurance and Evidence should be nearly as polished because they are central to the product.

Quality bar:
This should look like a product a serious water district, farm enterprise team, farmland owner, lender, or corporate agriculture buyer would trust.
It should feel like a $50K–$250K/year enterprise software workspace.
