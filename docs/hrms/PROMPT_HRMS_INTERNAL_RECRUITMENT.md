# Implementation Prompt — HRMS Phase: Internal (In-House) Recruitment Track

Paste this whole file as the task prompt. Attach `HRMS_MODULE_OVERVIEW.md` and
`Sparsh_Magic_Internal_Recruitment_Policy_SOP.docx` alongside it.

---

## 0. Context

You are extending the existing **HRMS module** of the Sparsh ERP (FastAPI + MongoDB backend,
React + Tailwind + shadcn/ui frontend). The module is already built and running — see the
attached `HRMS_MODULE_OVERVIEW.md`, which is authoritative for current behaviour, file layout,
invariants and traps. **Read it before writing code.**

Today the module implements only the **recruitment-agency model**: the tenant recruits *on
behalf of* client companies, and a CV is shared with the client for a verdict before
interviews.

We are adding a **second, parallel track**: **Sparsh Magic's own internal hiring**, governed by
the attached SOP (Part B — Internal Recruitment Policy & SOP). The defining difference: **there
is no client.** Headcount, salary band and budget are owned and approved internally by
Management/Finance, and the offer is issued directly by Sparsh Magic HR.

This is **role-based new functionality**, not a rewrite. The client track must continue to work
byte-for-byte as it does today.

---

## 1. Non-negotiable constraints

Violating any of these is a failed implementation.

1. **Do not break the client track.** Every existing endpoint, status, transition and analytics
   figure keeps its current behaviour when the track is `client`. New fields are optional and
   default to today's semantics.
2. **Honour every invariant in §4 of the overview** — `company_id` is the only tenant boundary;
   scoping filters fail closed (`$in: []`, never an absent filter); every candidate stage move
   goes through `FORWARD_TRANSITIONS` / `can_transition()`; business ids come from
   `hrms_id_service.next_business_id`; analytics never writes; nothing is computed in the
   browser.
3. **Capability parity.** Any new `Cap` must be added to **both** `backend/app/models/hrms.py`
   and `frontend/src/features/hrms/access.js`, or `test_capability_parity.py` fails.
4. **Any new `AppStatus` needs a `STAGE_RANK` entry**, or it ranks 0 and is credited to no
   funnel stage.
5. **Every new collection carries `request_no`**, and candidate-linked ones also carry `uk`, so
   one scope filter still works uniformly across analytics.
6. **Do not write the literal tokens `insert_`, `update_`, `delete_`** anywhere in
   `hrms_analytics_service.py`, including comments — the read-only test greps source text.
7. **The sidebar list and the workspace tab strip stay disjoint** (`HRMS_WORKSPACE` in
   `Sidebar.jsx` vs `hrmsSubmodules`).
8. **`client_id` is never a security check.** An internal requisition simply has no client.
9. Tests follow the house convention: no pytest, no live DB, `FakeCollection`, ASCII output,
   exit 1 on failure.
10. Frontend is mobile-first and responsive, Tailwind + shadcn/ui, reusing the existing
    `common/` components (`HrmsPageHeader`, `HrmsScopeBar`, `HrmsStates`) — no new design
    language, no custom CSS where a utility exists.

---

## 2. What to build

### 2.1 Track discriminator

Add `requisition_track: "client" | "internal"` to `hrms_requisitions`, defaulting to `"client"`
so existing rows are unchanged.

- `internal` ⇒ `client_id` **must be null**; reject with 422 if supplied.
- `client` ⇒ current behaviour verbatim.
- The track is **immutable after creation** — changing it mid-flight would invalidate an
  approval already granted under different rules.
- Analytics keeps its existing "In-house / no client" bucket, but internal-track requisitions
  are additionally filterable via `?track=internal` on every list, report and analytics
  endpoint.

### 2.2 New roles

Add **`FINANCE`** as a seventh HRMS role, resolved from `governance_role: FINANCE` on a
client-side user. It is the budget approver for the internal track. `MD` retains everything it
has today plus every new internal capability (it is the top of the ladder).

Map the SOP's actors onto existing roles: **HOD → `MANAGER`**, **HR team → `HR`**,
**Management → `MD`**, **Finance → `FINANCE`**.

### 2.3 New capabilities

Add to the `Cap` enum and the frontend `CAP` map, granted per the RACI matrix in Annexure B of
the SOP:

```
requisition.approve_budget      MD, FINANCE                 (A — mandatory gate)
scorecard.read                  MD, HR, MANAGER, FINANCE
scorecard.write                 HR
scorecard.approve               MANAGER (HOD), MD (managerial+ roles)
reference.read                  MD, HR, MANAGER
reference.write                 HR
probation.read                  MD, HR, MANAGER
probation.review                MANAGER                     (A/R per RACI)
probation.confirm               HR (recommend), MD (managerial+ confirm)
induction.read                  MD, HR, MANAGER
induction.write                 HR
exception.read                  MD, HR, MANAGER, FINANCE
exception.write                 HR, MANAGER
exception.approve               MD, FINANCE
personnel_file.close            HR
```

`INTERNAL` (Sparsh support staff) gets the `*.read` capabilities only — approvals, budget and
confirmations are the client's own governance acts, consistent with the existing withholdings
in §3.3 of the overview.

### 2.4 Internal approval chain

The client track's chain is `Pending HR Review → [sanction check] → Pending MD Approval →
Approved`. The internal track inserts a **mandatory budget gate** and mirrors §3 + §4 of the
SOP:

```
Pending HR Verification
   └─ hr-verify (Cap: requisition.review_hr)
Pending Budget Approval          ← MANDATORY, no bypass, no sourcing before this
   └─ budget-approve (Cap: requisition.approve_budget)  [+ approved_salary_band, approved_headcount]
   └─ over sanctioned strength? → Pending Escalation (existing ladder, MAX_ESCALATION_LEVELS = 5)
Pending Scorecard Approval
   └─ scorecard-approve (Cap: scorecard.approve; MD approval additionally required for managerial+)
Approved   → the JD/posting becomes publishable
```

Reuse the existing `POST /requisitions/{no}/approve` endpoint with new `action` values
(`hr-verify`, `budget-approve`, `scorecard-approve`) rather than adding parallel endpoints.
Any rung may still `reject`.

**Hard block:** a posting may not be published, and no candidate may be created against, an
internal requisition that has not cleared `budget-approve`. Enforce server-side in the posting
and candidate services, not merely in the UI. Store `budget_approved_by`, `budget_approved_at`,
`approved_salary_band_min/max`, `approved_headcount`.

### 2.5 Position Scorecard (new entity)

New collection `hrms_position_scorecards`, business id `SCR-YYYY-NNN` (year-scoped, per-company
counter, minted atomically).

- One scorecard per requisition, drafted by HR, approved by the HOD (and by MD for managerial+).
- Holds weighted criteria: `{ label, category (skill|experience|culture_fit), weight, max_score }`.
- Candidate evaluation against it produces a weighted 1–5 score.
- **Scoring guide from the SOP:** `>= 4.0` strong, `< 3.0` auto-reject recommendation. Surface
  the band; do not auto-transition the candidate — HR still decides.
- Interview scorecards on the internal track are scored against this scorecard's criteria
  instead of the fixed client-track fields.

### 2.6 Reference check (new entity, gates the offer)

New collection `hrms_reference_checks`, id `REF-YYYY-NNN`, carrying `request_no` + `uk`.

- Fields: referee name, designation, organisation, relationship, contact, mode, date,
  responses, outcome (`Positive` / `Negative` / `Unable to Verify`), conducted_by, remarks.
- **On the internal track, reference check is mandatory before an offer is created** — Sparsh
  Magic bears the direct employment risk. `POST /offers` returns 409 if no completed reference
  check exists for the candidate, unless a logged Exception (§2.9) overrides it.
- On the client track it stays optional and unenforced.

### 2.7 Salary within approved budget

`POST /offers` on an internal-track requisition validates the offered CTC against
`approved_salary_band_min/max`. Outside the band ⇒ 409 with a machine-readable reason, cleared
only by a fresh `budget-approve` at the new figure or a logged Exception.

### 2.8 Induction, probation, personnel file closure

Extend `hrms_onboarding` — do **not** create a parallel onboarding flow.

- **Induction:** a Day-1 checklist (policies, systems/access, introductions) reusing the
  existing 12-key checklist mechanism with internal-track-specific keys.
- **Probation:** new collection `hrms_probation_reviews`, id `PRB-YYYY-NNN`, linked by
  `request_no` + employee code. Fields: probation start/end (default 3–6 months, configurable
  per employment terms), reviewer, rating against the position scorecard, outcome
  (`Confirmed` / `Extended` / `Terminated`), extension end date, remarks, confirmed_by,
  confirmed_at.
- **New terminal candidate status `Probation Confirmed`**, reachable only from
  `Employee Created` on the internal track. Add it to `AppStatus`, `FORWARD_TRANSITIONS` and
  `STAGE_RANK` at **rank 8** alongside `Employee Created` (it is a post-hire governance event,
  not a further funnel stage — do not add a rank 9, or the client-track funnel gains an empty
  tail).
- **Personnel file closure:** on probation confirmation, HR records a closure note; the internal
  requisition closes with closing status `Hired`. There is no client handover in this track.

### 2.9 Exception log

New collection `hrms_exceptions`, id `EXC-YYYY-NNN`, carrying `request_no` (and `uk` where
candidate-specific).

- Types: `Extended TAT`, `Relaxed Scorecard`, `Offer Outside Budget`, `Reference Check Waived`,
  `Other`.
- Fields: reason, raised_by, approver, approved_at, status (`Pending` / `Approved` / `Rejected`),
  linked entity.
- An **approved** exception is the only thing that unblocks the 409s in §2.6 and §2.7 — the
  code must check for one rather than offering a boolean override flag on the request body.
- Exceptions beyond HR/HOD authority require `exception.approve` (MD or FINANCE).

### 2.10 SLA / TAT tracking

Per §8 of the SOP, stamp and compute against these targets on the internal track:

| Milestone | Target |
|---|---|
| Budget/headcount approval | 3 working days from requisition |
| Position scorecard approved | 2 working days from budget approval |
| Shortlist ready for HOD review | 15 working days |
| Offer released after final selection | 3 working days |
| Induction completed | Day 1 of joining |
| Probation review completed | Before probation end |

- Store target and actual timestamps per milestone on the requisition; compute breach
  server-side (**working days**, not calendar days — exclude weekends; holidays out of scope
  for this phase, note it in the module doc).
- On breach, fire an in-app + email escalation via the existing `hrms_notify_service`
  (`notify_hrms_role`). Seed scripts must keep patching notifications out.

### 2.11 KPI dashboard (§10 of the SOP)

Extend `hrms_analytics_service` (read-only) with an internal-track KPI block, returned by
`GET /analytics/dashboard?track=internal`:

- % requisitions with approved budget before sourcing (target 100%)
- % shortlists ready within TAT Day 15 (target 95%+)
- offer-to-joining conversion rate
- % reference checks completed before offer (target 100%)
- % offer letters issued before joining date (target 100%)
- % probation confirmations completed on time (target 95%+)
- 90-day retention of new joinees
- new-hire induction feedback score

Respect the existing guards: `SCAN_CAP = 20000`, `MAX_RANGE_DAYS = 1100`,
`MAX_EXPORT_ROWS = 5000`. Add `probation` and `exceptions` as report entities under
`GET /reports/{entity}` with the same CSV/XLSX server-side export.

### 2.12 Record retention (§13 of the SOP)

Store a `retention_until` on the relevant records per the SOP table (requisition & budget
approval 3 years from closure; unselected candidates 1 year; offer, reference and probation
records employment + 3 years). **This phase computes and stores the date and exposes it on
reports — it does not purge.** Do not build a deletion job; say so explicitly in the docs.

---

## 3. New / changed API surface

Extend, don't fork. All under `/api/hrms`, all accepting the existing `company_id` (ignored for
client-side callers) plus the new `track` filter.

```
POST   /requisitions                        + requisition_track, budget fields
POST   /requisitions/{no}/approve           + actions: hr-verify | budget-approve | scorecard-approve
GET    /requisitions?track=internal

GET    /scorecards                          POST /scorecards
GET/PATCH /scorecards/{scr_no}              POST /scorecards/{scr_no}/approve
POST   /candidates/{uk}/scorecard-evaluate

GET    /reference-checks                    POST /reference-checks
GET/PATCH /reference-checks/{ref_no}

GET    /probation                           GET /probation/due
POST   /probation                           GET/PATCH /probation/{prb_no}
POST   /probation/{prb_no}/confirm

GET    /exceptions                          POST /exceptions
POST   /exceptions/{exc_no}/approve

GET    /analytics/dashboard?track=internal  GET /reports/probation  GET /reports/exceptions
GET    /requisitions/{no}/sla               milestone targets vs actuals
```

Every route starts with `_require(current_user, Cap.X)` — no exceptions.

---

## 4. Frontend

New routes inside the existing `HrmsWorkspace` shell, gated on `can(cap)` from `HrmsContext`
(which fails closed while loading and on error):

```
/hrms/internal-requisitions     internal-track requisition list + budget approval dialog
/hrms/scorecards                ScorecardLibrary + ScorecardBuilder
/hrms/reference-checks          ReferenceCheckBoard
/hrms/probation                 ProbationBoard (due / overdue / confirmed)
/hrms/exceptions                ExceptionLog
```

- Place the pipeline-stage screens in the **workspace tab strip**; place governance screens
  (Exceptions, Probation) in the **sidebar**. Keep the two lists disjoint.
- Reuse `RequisitionFormModal` with a track toggle rather than cloning it. Reuse
  `ApprovalDialog` for the new actions.
- The internal track's UI must never render a client selector; the client track's UI must be
  visually unchanged.
- Tables, modals and the scorecard builder must be usable at 375px width — cards on mobile,
  table on `md:` and up. Semantic HTML, keyboard navigable, ARIA on the approval dialogs.

---

## 5. Tests

Add to `backend/app/services/hrms/tests/`, house convention (no pytest, no live DB,
`FakeCollection`, exit 1 on failure). At minimum:

- `test_internal_requisition_chain.py` — the full ladder, including the escalation path when a
  position has no sanctioned figure (which counts as over-sanction, fail-closed).
- `test_internal_budget_gate.py` — posting and candidate creation are blocked before
  `budget-approve`; the client track is unaffected.
- `test_scorecard.py` — weighting, 4.0/3.0 bands, approval routing for managerial+.
- `test_reference_gate.py` — offer 409 without a reference check; unblocked by an approved
  exception only.
- `test_probation.py` — `Employee Created → Probation Confirmed` legality; illegal moves 409.
- `test_exceptions.py` — approval authority per role.
- `test_sla.py` — working-day arithmetic across a weekend.
- Extend `test_capability_parity.py` coverage implicitly by adding the caps to both files.
- Extend `test_phase10_analytics.py` expectations for the new KPI block, without introducing
  forbidden tokens into the analytics source.

Also extend `scripts/seed_hrms_realistic_ops.py` with internal-track requisitions under its own
existing `realistic-ops` marker — **do not widen the `--undo` filter**, and keep invented data
only (`example.com` emails, `+91 00000 xxxxx` phones).

---

## 6. Deliverables and output format

1. **Plan first.** Before any code, output a short gap analysis: what already exists that can be
   reused, what is genuinely new, and every file you intend to touch. Flag anything in the SOP
   that conflicts with a current invariant, and propose the resolution — do not silently pick
   one.
2. **Then implement, phase by phase**, in this order: models/caps → requisition chain → scorecard
   → reference check → offer gate → probation/induction → exceptions → SLA → analytics →
   frontend → tests. Stop after each phase for review.
3. **Return only changed code**, in this format:

```
File:
Reason:
Find:
Replace With:
Notes:
```

   No placeholders, no `...existing code...`, no regenerated unchanged files. Imports only if
   they changed. Name every dependency the change affects.
4. **Update `HRMS_MODULE_OVERVIEW.md`** in the same style as the original: add the internal
   track to §6, the new statuses to §7, the new collections to §5, the new caps to §3.3, the new
   endpoints to §14, and add every new gotcha to §17. Remove anything from §16 that this phase
   builds.

---

## 7. Ask before assuming

Ask only if genuinely blocking; otherwise state your assumption inline and continue.

Known open questions worth confirming up front:

- Is `FINANCE` a distinct `governance_role` in the ERP today, or must MD approve budget until
  it exists?
- Default probation duration — 3 or 6 months — and is it per-designation or per-offer?
- Should an internal requisition be publishable to the same public `/apply/{code}` surface, or
  is internal hiring sourced only through HR-entered CVs and referrals?
