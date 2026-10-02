# Leadership Score → TPMS: Implementation Plan

Companion to [TPMS_MODULE_ANALYSIS.md](TPMS_MODULE_ANALYSIS.md) and
[TPMS_ERP_IMPLEMENTATION_PLAN.md](TPMS_ERP_IMPLEMENTATION_PLAN.md).

Source: *Key insights of Leadership Score* (8 pp.). Scope: L4 (Asst. Manager) and above.
Cycle: every 2 months. Feedback: 180° or 360°, completely anonymous.

Goal: build Leadership Score as a **form-based feature inside TPMS**, following the existing
forms workflow — Form → Assign Feedback Givers → Email Form Link → Submit Response →
Store Responses → Calculate Score → Result/Report. Not a separate form system, and not
dependent on Culture Rating.

---

## 0. Verdict

Roughly **60% of this already exists**. The TPMS forms sub-module implements the exact
pipeline the document describes: a form-scored activity is scheduled on the calendar,
`tpms_form_link_service` mints one unguessable token per respondent, `tpms_notify_service`
injects that link into the schedule mail, the recipient opens `/f/<token>`, fills the form,
and the response lands in a per-form collection — with delivery and completion auditable in
TPMS ▸ Form Mail Logs.

That spine carries Leadership Score unchanged. What does **not** carry is the shape of the
data on top of it. Every existing TPMS rating form is *one HOD rating many team members*.
Leadership Score is *many anonymous givers rating one leader*, with level-specific questions,
option-based scores, per-parameter weightages and a two-month cycle. Six structural
mismatches follow in §2 — none fatal, none cosmetic.

Target pipeline:

```
1 Cycle opens    HR creates the 2-month cycle for a company
2 Subjects       Leaders L4+ enrolled, each with a level
3 Givers         HR picks 8 per subject, by relation
4 Links mailed   One token per (subject x giver)
5 Responses      Anonymous, one submission each
6 Score          Weighted, threshold-gated
7 RRO            Reporting manager discusses with the leader
```

---

## 1. Reuse inventory

`REUSE` = untouched · `EXTEND` = additive, must not alter current behaviour · `NEW` = net-new.

| Component | File | Verdict | What changes |
|---|---|---|---|
| Form registry | `app/models/forms.py` | EXTEND | Add `leadership` to `FORM_DEFINITIONS` with a third kind `KIND_LEADERSHIP_FEEDBACK`. Add to `FORM_COLLECTIONS` and `ACTIVITY_FORM_MAP`. |
| Link / token service | `services/tpms_form_link_service.py` | EXTEND | Add `subject_id` + `relation` to the assignment key and document. `eligible_respondents()` gains a leadership branch reading the HR-chosen giver list. |
| Assignment collection | `tpms_form_assignments` | REUSE | No migration — it carries **no unique index**, so widening the lookup key is code-only. Existing rows keep `subject_id: ""`. |
| Mail dispatch | `services/tpms_notify_service.py` | REUSE | Nothing. `_recipient_form_links()` and `_ensure_links_delivered()` are already form-agnostic and handle **multiple links per recipient** — exactly the case where one person rates several leaders. |
| Token gate | `routes/forms.py` · `_assignment_for()` | REUSE | Nothing. The two-check rule (live token + signed-in user *is* the respondent) is right for confidential feedback. |
| Assigned-form endpoint | `GET /api/forms/assigned/{token}` | EXTEND | Leadership branch returning the subject (name/designation only) and the question set for that subject's **level**, instead of the company roster. |
| Assigned-form router | `features/tpms/forms/AssignedFormPage.jsx` | EXTEND | One more branch on `definition.kind`. No other change. |
| Rating UI | `features/tpms/client/ClientRatingForm.jsx` | NEW sibling | Not adaptable — its axis is members × criteria with 0–5 radios. Leadership needs one subject × questions with four labelled options. |
| Question master | `tpms_form_questions` | EXTEND | Add `level`, `options[]`, `weightage`. Existing rows unaffected (`level: null`). Keeps one admin screen for all form text. |
| Question admin UI | `admin/pages/FormQuestionAdmin.jsx` | EXTEND | Level filter, option editor, weightage column with a total-must-be-100 guard. |
| Activity catalogue | `tpms_activities` · `ACTIVITY_SEED` | EXTEND | Seed a `Leadership Score` activity, `score_mode: "form"`, `scope: "company"`, `frequency: "once in 2 months"`. |
| Scheduling | calendar events · `kind: tpms_activity` | REUSE | Nothing in phase 1 — HR schedules six occurrences a year. See **M6**. |
| Form Mail Logs | `GET /api/forms/assignments` · `FormLinks.jsx` | EXTEND | Add a *Subject* column and a cycle filter. Giver name is already there — this screen is HR/admin-only, which is where the confidentiality boundary sits. |
| Score engine | `services/tpms_score_service.py` | EXTEND | `activity_score_pct()` pools Σrating ÷ (n × 5) — an unweighted mean over a `ratings.{code}.{member}` path leadership responses don't have. Add a leadership branch so the Success-Measure rollup still gets one number. |
| Success measures | `tpms_success_measures` | REUSE | Nothing, once the branch above exists. |
| Review Report | `features/tpms/common/ReviewReport.jsx` | NEW | Cannot be reused: it renders per-respondent submission cards, which here would expose exactly what must stay anonymous. |
| Company gate | `utils/tpms_access.py` | REUSE | Nothing. The router-wide `_tpms_company_gate` dependency already covers every new `/forms` route. |
| Submission notifier | `notify_form_submission()` | **MUST NOT REUSE** | It mails a per-employee scorecard naming their ratings. Firing it for a leadership response would breach anonymity. |

---

## 2. The six structural mismatches

### M1 — The matrix axis flips

Every existing rating form stores one document per `(company, period, hod_id)` with a
`ratings.{criterion}.{member_id}` map — one rater, many subjects. Leadership Score is the
transpose: many raters, one subject. The same giver may hold several assignments in one
cycle; the same subject collects up to eight documents.

**Resolution.** New collection `tpms_leadership_responses`, one document per
`(company, cycle, subject_id, giver_id)`. Do not bend the existing collection shape — the
unique index `uniq_company_period_respondent` would reject the second giver for a subject.

### M2 — Anonymity is a hard requirement, and the current code is built the other way

The document is explicit: feedback is *completely* confidential, the giver list is known only
to HR, and the action point tells leaders not to speculate about who said what. Existing
submissions store `rated_by`, `rated_by_name` and `hod_name` on every cell and mail a
scorecard to the rated person. A leader with eight responses and a small team can
de-anonymise a relation group of one.

**Resolution.** Store `giver_id` for audit and duplicate-prevention, but never return it from
any endpoint a subject or their manager can reach — enforce that in the serializer, not the
UI. Gate every score behind a **minimum-response threshold** (recommend 3) and suppress any
relation-group breakdown with fewer than 2 responses. Never call `notify_form_submission()`
on this path.

### M3 — Four level-specific question sets

The question master is keyed `(form_type, item_id)` — one set per form. Leadership needs four:
L4 and L5 have 5 questions each, L6 and L7+ have 6. The set is chosen by the **subject's**
level, not the giver's. Compounding this, **no level field exists on users** — `designation`
is free text and `department` holds a governance role (HOD/MD/HR/Implementor), not a grade.

**Resolution.** Add `level` to the question master, making the key `(form_type, level,
item_id)`. For the user side, add an explicit `leadership_level` set per subject when HR
enrols them into a cycle, snapshotted onto the subject row so a later promotion doesn't
retro-change a closed cycle. A designation→level mapping table is the wrong first move —
designations are inconsistent across the 22 client companies.

### M4 — Option-based scoring, not a 0–5 scale

Each question offers four labelled options scoring **1 / 2 / 4 / 5**. A score of 3 is never
awarded — the rubric deliberately splits "struggling" from "solid" with a gap. The existing
`RatingCell.rating` validator accepts any integer 0–5, which would let a client post a 3 that
no option can produce.

**Resolution.** Store the chosen `option_id` *and* its `score`, and validate server-side that
the option belongs to that question. Keep `SCALE_MAX = 5` as the denominator so percentages
stay comparable with the other TPMS forms.

### M5 — Per-parameter weightages, which no TPMS form has

Implementation step 4 of the document: *"All parameters should have weightages to create
scoring — HR and MD."* No existing form carries a weightage, and `activity_score_pct()`
computes a flat pooled mean.

**Resolution.** A `weightage` per `(level, question)` on the question master, validated to
total exactly 100 within each level before saving — reject the save rather than silently
normalising, so a half-configured level can never produce a plausible-looking wrong score.
Seed every level equal-weighted (20% × 5, or 16.67% × 6) so the module is usable before HR
and the MD sit down.

### M6 — A 2-month cycle against a codebase where "period" means one month

The most invasive mismatch. `period = "YYYY-MM"` is assumed by `period_tokens()`,
`period_parts()`, `period_end_utc()` (which sets link expiry to month-end), the submission
unique indexes, `/forms/my-forms`, the Review Report filters and `tpms_success_measures`.
Separately, `RECURRENCE_PERIODICALLY` is **weekday**-based, not every-N-months — the
recurrence engine cannot express "every 2 months" at all.

**Resolution.** Store **both**. `cycle` is the real key (e.g. `"2026-C3"` for May–Jun);
`period` carries the cycle's *closing* month so every period-keyed mechanism above keeps
working untouched — and link expiry then lands on the end of the closing month, which is the
correct business behaviour anyway. For scheduling, HR creates six occurrences a year manually
in phase 1; adding a `RECURRENCE_EVERY_N_MONTHS` mode is a clean phase-6 follow-up, not a
blocker.

---

## 3. The source rubric's internal inconsistencies — seeded as printed

**Decided: the document is the single source of truth and is used exactly as it stands.**
The items below are recorded so nobody re-discovers them and assumes a bug. None of them is
corrected, flagged on screen, or held back for confirmation — there is no review register and
no sign-off gate, and no approval from HR, the MD or anyone else is required before a level is
scored. Whatever the document prints is what leaders are scored on.

1. **L5 Q3 and Q4 are swapped.** Q3 asks about communication skill but its options describe
   priority-setting ("Everything feels urgent", "Clear priorities aligned to goals"). Q4 asks
   about making the team accountable but its options describe communication ("Causes confusion
   or mixed messages"). Q5 then asks about priorities again with accountability options.
2. **L7+ Q6 scores are inverted.** "Goals are aligned and largely executed" scores **1** while
   "Goals are unclear and execution is inconsistent" scores **4**, so the worst answer earns the
   second-highest score and an L7 leader loses roughly a sixth of their weightage for doing the
   right thing. Invisible in the result — it simply reads as a low score. Seeded and scored
   exactly as printed. If this is ever to change it is an ordinary edit through the admin
   screen, not a code change.
3. **L7+ Q1 and Q2 prompts don't match their options.** Q1 asks about measuring progress and
   counselling but the options describe team structure; Q2 asks about building a strong team
   but the options describe business impact — which is what Q3 then asks.
4. **L4 Q5 option A is truncated** — "Loses accountability under scale" appears cut off, and
   echoes L7+ Q4 option A ("Loses control under scale"). "Under scale" is not a condition an
   Asst. Manager operates in, so L4's worst-case option describes something that cannot happen.
5. **L6 Q5 and Q6 overlap.** Q5 asks how the leader inspires the team but its options describe
   process and job redesign, which is what Q6 explicitly covers.

All of it is seeded verbatim. Question text, option wording, option scores and weightages stay
editable through the existing admin screen, so anything the business later wants changed is a
runtime edit — but nothing waits on that, and no cycle is held up by it.

---

## 4. Database / models / collections

| Collection | Grain | Key fields | Index |
|---|---|---|---|
| `tpms_leadership_cycles` **NEW** | one per (company, cycle) | `company_id`, `cycle`, `label`, `period` (closing month), `starts_on`, `ends_on`, `degree` (180｜360), `min_responses`, `status` (draft｜open｜closed), `created_by` | unique `(company_id, cycle)` |
| `tpms_leadership_subjects` **NEW** | one per (cycle, leader) | `company_id`, `cycle`, `subject_id`, `level` (L4｜L5｜L6｜L7), snapshot `name` / `designation` / `department`, `enrolled_by` | unique `(company_id, cycle, subject_id)` |
| `tpms_leadership_responses` **NEW** | one per (cycle, subject, giver) | `company_id`, `cycle`, `period`, `subject_id`, `subject_level`, `giver_id` *(HR/audit only)*, `relation`, `answers` = {question_id → {option_id, score}}, `submitted_at` | unique `(company_id, cycle, subject_id, giver_id)` |
| `tpms_leadership_scores` **NEW** | one per (cycle, subject) | per-question mean + weighted contribution, `final_score`, `response_count`, `by_relation`, `weightages` snapshot, `computed_at` | unique `(company_id, cycle, subject_id)` |
| `tpms_form_questions` **EXTEND** | one per (form, level, item) | + `level`, + `options[]` = {option_id, label, score}, + `weightage` | existing, plus `(form_type, level, order)` |
| `tpms_form_assignments` **EXTEND** | one per mailed link | + `subject_id`, + `subject_name`, + `relation`, + `cycle` | none today — widening the key needs no migration |

**Decision — no separate "givers" collection.** An assignment row already *is* a giver: it
names the respondent, carries their token, and tracks sent / opened / submitted. Adding
`subject_id` and `relation` to it makes a `tpms_leadership_givers` table redundant, keeps one
audit trail instead of two that can disagree, and means Form Mail Logs works for this module
the day it ships.

Provision the four new collections through the existing startup-hook pattern in
`app/db/mongodb.py` — a `_ensure_leadership_collections()` alongside
`_ensure_tpms_collections()`, driven by an index spec list in the model file. Failures there
must stay non-fatal, exactly as the two existing provisioners do.

---

## 5. Form and question structure

```python
# app/models/forms.py — the third kind
KIND_LEADERSHIP_FEEDBACK = "leadership_feedback"

FORM_DEFINITIONS["leadership"] = {
    "form_type": "leadership",
    "kind": KIND_LEADERSHIP_FEEDBACK,
    "title": "Leadership Score",
    "description": "Confidential leadership feedback. Applicable from L4 and above.",
    "available": True,
    "audience": "assigned",     # NEW: neither 'hod' nor 'md' — HR names the givers
    "scale": {"min": 1, "max": 5},
    "levels": ["L4", "L5", "L6", "L7"],
    "anonymous": True,          # read by the serializer, not just documentation
}

FORM_COLLECTIONS["leadership"] = "tpms_leadership_responses"
ACTIVITY_FORM_MAP["Leadership Score"] = ["leadership"]
```

One question in the master:

```json
{
  "form_type": "leadership", "level": "L4", "item_id": "L4Q1",
  "title": "Self-management",
  "prompt": "How does he/she manage himself?",
  "weightage": 20.0,
  "options": [
    {"option_id": "A", "label": "Needs frequent reminders; priorities change daily.",    "score": 1},
    {"option_id": "B", "label": "Manages own work but struggles under pressure.",        "score": 2},
    {"option_id": "C", "label": "Plans work, meets commitments, handles pressure well.", "score": 4},
    {"option_id": "D", "label": "Fully self-driven; anticipates issues before they arise.", "score": 5}
  ],
  "order": 0, "active": true
}
```

### Leadership levels

| Level | Who | Questions | Theme |
|---|---|---|---|
| L4 | Asst. Manager | 5 | Self-management + managing others |
| L5 | Manager | 5 | Managing managers, delegation, priorities |
| L6 | Senior Manager | 6 | Managers' productivity, measurement, innovation |
| L7+ | — | 6 | Strategy, business acumen, alignment |

### Relations (the 8 givers)

2 superiors · 2 peers (same dept) · 2 peers (other dept) · 2 direct reports.

- **360°** uses all four relations.
- **180°** uses superiors and peers only.

Stored per cycle so a company can start at 180° and move to 360°.

---

## 6. Score calculation

```
For subject S in cycle C, with R responses (R >= min_responses, else "Awaiting responses"):

  question mean      avg(q)  = mean over responses of answers[q].score      -> 1..5
  achievement        ach(q)  = avg(q) / 5 * 100                             -> 0..100
  weighted score     w(q)    = ach(q) * weightage(q) / 100
  Leadership Score           = sum over q of w(q)                           -> 0..100

Relation breakdown: the same maths restricted to one relation group,
reported only when that group has >= 2 responses.

A question no giver answered is excluded from the total and its weightage is
reported as unearned, rather than counted as zero.
```

**Decision — unanswered questions dilute rather than fail.** Treating a missing question as 0
would punish a leader for a giver's omission. Excluding it and reporting the *applicable
weightage* alongside the score keeps a partially-answered cycle honest and readable — the same
discipline the score engine already applies when it returns `None` for "no data" instead of 0.

Compute live on read so a weightage change takes effect immediately, and snapshot into
`tpms_leadership_scores` when a cycle closes so a historical score can never silently move.
`tpms_score_service.activity_score_pct()` gains a leadership branch returning the company-level
mean of subject scores, so the Success-Measure rollup and client scorecard keep working with no
changes of their own.

---

## 7. API surface

New endpoints on a dedicated `/api/leadership` router; the two token endpoints stay on
`/api/forms` so there remains exactly one assigned-form path.

| Method & path | Who | Purpose |
|---|---|---|
| `GET /leadership/cycles` | HR · staff | Cycles for a company, newest first. |
| `POST /leadership/cycles` | HR · staff | Open a cycle — window, degree, minimum responses. |
| `PATCH /leadership/cycles/{id}` | HR · staff | Edit while draft; close when the window ends (snapshots scores). |
| `GET /leadership/subjects` | HR · staff | Enrolled leaders for a cycle, with response counts. |
| `POST /leadership/subjects` | HR · staff | Enrol a leader at a level. Rejects a level the master has no questions for. |
| `GET /leadership/subjects/{id}/givers` | HR only | The giver list. Most confidentiality-sensitive endpoint in the module. |
| `PUT /leadership/subjects/{id}/givers` | HR only | Set the 8 givers with relations; mints assignments and mails links. |
| `POST /leadership/cycles/{id}/dispatch` | HR · staff | Send or re-send every pending link for the cycle. |
| `GET /forms/assigned/{token}` | the giver | **EXTEND** Returns the subject and their level's questions. |
| `POST /forms/leadership/response` | the giver | Submit one response. Token-scoped, single-shot, no `notify_form_submission`. |
| `GET /leadership/scores` | HR · staff · manager | Subject scores for a cycle. Threshold-gated; never carries giver identity. |
| `GET /leadership/scores/{subject_id}` | + the subject | One leader's full breakdown for the RRO conversation. |
| `GET /leadership/questions` | staff | Master by level, with options and weightages. |
| `PUT /leadership/questions/weightages` | Super Admin · Admin | Set weightages for a level. Rejects any total ≠ 100. |

---

## 8. Access control and confidentiality

| Capability | Super Admin · Admin | HR (client) | Reporting manager | The leader | Giver |
|---|---|---|---|---|---|
| Open / close a cycle | ✓ | ✓ | — | — | — |
| Enrol subjects | ✓ | ✓ | — | — | — |
| See the giver list | ✓ | ✓ | — | — | — |
| Edit questions / options | ✓ | — | — | — | — |
| Edit weightages | ✓ | — | — | — | — |
| Submit feedback | — | — | — | — | ✓ own token |
| See a subject's score | ✓ | ✓ | ✓ own reports | ✓ own | — |
| **See who gave what** | **Nobody.** The response→giver mapping exists only for duplicate prevention and audit, and is never serialized to any client. ||||

Three enforcement rules:

1. **Threshold.** No score is shown until `min_responses` (default 3) have arrived. Below that
   the API returns a state, not a number.
2. **Group suppression.** A relation group with one response is folded into the total and not
   shown separately — otherwise "direct reports: 2.0" names one person.
3. **Enforce in the serializer.** Strip `giver_id` and `relation` in one response-builder every
   score endpoint calls, so a future endpoint cannot leak by omission.

Two roles the document assumes do not exist cleanly in the ERP today:

- **HR** is a value in `TPMS_DEPARTMENTS` (`["HOD","MD","HR","IMPLEMENTOR"]`) resolved through
  `governance_role`. Grant HR capability on that basis, mirroring `_is_hod()` — not by
  inventing a new ERP role.
- **Reporting manager** already exists as `reporting_manager` on the user, which is what the
  RRO view can key on.

---

## 9. Files to create and modify

### Create — backend
- `app/models/leadership.py` — levels, relations, cycle helpers, Pydantic payloads, index spec, question seed for L4–L7
- `app/services/leadership_service.py` — cycles, subjects, givers, scoring
- `app/services/leadership_link_service.py` — thin wrapper minting per-(subject × giver) assignments via the existing link service
- `app/routes/leadership.py` — the `/api/leadership` router

### Create — frontend
- `services/leadershipApi.js`
- `features/tpms/leadership/LeadershipFeedbackForm.jsx` — the giver's form
- `features/tpms/admin/pages/LeadershipCycles.jsx` — cycle list and creation
- `features/tpms/admin/pages/LeadershipSubjects.jsx` — enrol leaders, assign givers, dispatch
- `features/tpms/common/LeadershipReport.jsx` — subject scorecard for HR, manager and leader
- `features/tpms/admin/pages/LeadershipWeightages.jsx` — per-level weightage editor

### Modify — backend
- `app/models/forms.py` — third kind, definition, collection, activity map
- `app/models/tpms.py` — seed the `Leadership Score` activity
- `app/routes/forms.py` — leadership branch in `assigned_form()`; new response endpoint; question master gains level/options/weightage
- `app/services/tpms_form_link_service.py` — `subject_id` in the key; leadership branch in `eligible_respondents()` and `assignments_for_event()`
- `app/services/tpms_score_service.py` — leadership branch in `activity_score_pct()`
- `app/db/mongodb.py` — `_ensure_leadership_collections()`
- `main.py` — register the router

### Modify — frontend
- `App.jsx` — four routes under `/tpms/admin` and `/tpms/smops`
- `components/layout/Sidebar.jsx` — TPMS submodule entries
- `features/tpms/forms/AssignedFormPage.jsx` — route the new kind
- `features/tpms/admin/pages/FormQuestionAdmin.jsx` — level filter, option editor, weightage column
- `features/tpms/admin/pages/FormLinks.jsx` — Subject column, cycle filter
- `services/tpmsFormsApi.js` — leadership response call

---

## 10. Delivery phases

Ordered because each phase depends on the one before it — questions must exist before a form
can render, and responses must exist before a score means anything.

1. **Foundations** — model file, index provisioning, the third form kind, and the L4–L7
   question master seeded with options and equal weightages. Not gated on anything: the
   document is seeded as printed (§3). Nothing user-visible yet.
2. **Cycles and subjects** — cycle CRUD, subject enrolment with levels, and the two admin
   screens. HR can set up a cycle end-to-end without anything being mailed.
3. **Givers, links and the form** — giver assignment, the widened assignment key, dispatch, the
   `/f/<token>` leadership branch and the giver's form. First phase that touches shared code —
   regression-test the other four forms here.
4. **Scoring and reports** — the scorer, threshold and suppression rules, the subject scorecard,
   and the Success-Measure branch so Leadership Score joins the client dashboard.
5. **Weightage administration and RRO view** — per-level weightage editor with the 100% guard,
   and the manager-facing view used during RRO.
6. **Follow-ups** — `RECURRENCE_EVERY_N_MONTHS` so the 2-month cycle schedules itself;
   cycle-over-cycle trend on the scorecard; reminder rules for unsubmitted links.

---

## 11. Testing requirements

### Confidentiality — the tests that matter most
- No score endpoint returns `giver_id`, per-response `relation`, or any giver name — assert on
  the serialized payload, for every role.
- A subject requesting their own score with 2 responses and `min_responses: 3` gets a state,
  not a number.
- A relation group with 1 response is absent from the breakdown but present in the total.
- Submitting a leadership response sends no scorecard mail.
- A manager cannot read a score for someone who does not report to them.

### Scoring
- Known fixture: 8 responses, hand-computed weighted total, to 2 dp.
- Weightages summing to 99.99 or 100.01 are rejected; exactly 100 is accepted.
- Zero responses divides by nothing and returns no-data, never a crash or a 0.
- An unanswered question is excluded and reported as unearned weightage.
- Changing a weightage changes the next read with no recompute step.
- Only option scores 1, 2, 4, 5 are accepted; a posted 3 is rejected.

### Links and tokens
- One giver rating three leaders receives three distinct tokens, and each opens only its own
  subject.
- A forwarded token opens nothing for a different signed-in user (403).
- Re-dispatching a cycle does not mint second links for people who already hold one.
- A submitted token is terminal (409); a token past the closing month is expired (410).

### Regression — shared code
- Accountability, Ownership, Culture and Implementation Feedback all still mint links, mail,
  render and submit unchanged after the assignment key widens.
- Existing question-master rows with no `level` still load in the admin screen and still
  validate submissions.
- `activity_score_pct()` returns identical values for the four existing activities.
- A company with TPMS disabled gets 403 on every new endpoint.

---

## 12. Decisions needed before build starts

1. ~~**The rubric defects (§3).**~~ **Settled — nothing to decide.** The document is the single
   source of truth and its questions and options are used exactly as printed. No confirmation
   is sought or required from HR, the MD or anyone else.
2. **Minimum responses.** Recommend 3 of 8 before a score is visible. Lower means faster
   results and weaker anonymity.
3. **Does the leader see their own score in-app?** The document says everyone gets their
   scores, but discussion happens at RRO. Recommend the manager sees it first and the leader's
   view unlocks when the cycle closes.
4. **Who is HR here?** Confirm HR capability should key on `governance_role == "hr"` rather
   than a new ERP role — and whether Sparsh staff should also hold it.
5. **Cycle calendar.** Do all companies run the same six windows a year (Jan–Feb, Mar–Apr, …),
   or does each company set its own?
6. **Relation weighting.** This plan assumes all eight responses count equally. If a superior's
   feedback should weigh more than a peer's, say so now — it changes the scorer, not just a
   config value.

---

*Analysis based on the `IRM_17AUG` branch: `app/models/forms.py`, `app/routes/forms.py`,
`app/services/tpms_form_link_service.py`, `app/services/tpms_notify_service.py`,
`app/services/tpms_score_service.py`, `app/models/tpms.py` and the TPMS frontend feature tree.*
