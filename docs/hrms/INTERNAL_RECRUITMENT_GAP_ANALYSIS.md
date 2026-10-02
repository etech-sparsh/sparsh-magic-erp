# Sparsh Magic Internal Recruitment — Analysis & Gap Report

> **Analysis only. No code was modified to produce this.**
> Verified against the working tree on 2026-08-14 by reading source and running the full
> HRMS test suite (**53/53 files pass**).

---

## Headline

**The Sparsh Magic internal recruitment workflow is already built.** It shipped as the
`internal` requisition track plus **Phase INT-2**, and it is live in the working tree:
34 backend services, 173 authenticated endpoints, 33 collections, 84 capabilities, 30
frontend screens, 53 green test files.

The specification I was given describes, in ~90% of its sections, functionality that exists
today. Implementing it as a new module would duplicate roughly 25,000 lines of working,
tested code and break the client track.

**The correct action is not to build the workflow. It is to close a short, specific list of
gaps** — set out in §B below. The largest by far is that **no scheduler drives any of it**:
the SLA sweep, probation reminders, pre-boarding reminders, policy review reminders and the
retention purge are all written and tested, and nothing calls them.

---

## A. Existing HRMS analysis

### A.1 Architecture

| Layer | Where | Notes |
|---|---|---|
| Backend | FastAPI + MongoDB (Motor), `backend/app/` | routes → services → collections; no ORM |
| Models | `models/hrms.py` (4,518 lines) | **single source of truth**: enums, both state graphs, capability enum, role tables, collection names, id formats, SLA + retention tables, Pydantic models |
| Routes | `routes/hrms.py` (2,930 lines, 173 endpoints) | every handler opens with `_require(user, Cap.X)` |
| Public | `routes/hrms_public.py` + `utils/hrms_public_guard.py` | 6 unauthenticated surfaces, DB-backed rate limits |
| Access | `utils/hrms_access.py` (328 lines) | identity → role → capability → company scope → client scope |
| Frontend | React + Tailwind, `frontend/src/features/hrms/` | `HrmsContext` fetches `/hrms/health`, gates on server-reported capabilities, **fails closed** |
| Scheduler | `services/reminder_scheduler.py`, started from `main.py` lifespan | 60-second asyncio loop, hour-gated daily jobs (the TPMS pattern) |
| Notifications | `hrms_notify_service.py` | `notify_user` / `notify_users` / `notify_hrms_role` → in-app rows + email |
| Audit | `hrms_audit_service.py` → `hrms_audit_log` | append-only; every service writes through it |
| Documents | `hrms_document_service.py` + S3 | typed, versioned, owner-linked, separate `document.verify` capability |

### A.2 The two tracks

Everything runs on one of two **requisition tracks**, fixed at creation and immutable after:

- **`client`** — the original agency model (recruit *for* a client company). Default; a
  requisition with no `requisition_track` field reads as `client`, which is the backward
  compatibility guarantee.
- **`internal`** — Sparsh Magic hiring for itself. This is the workflow the specification
  describes.

`TRACK_TRANSITIONS` selects the state table by track, so no handler branches on track.

### A.3 What the internal track already enforces

Each of these is server-side, table-driven, and covered by tests:

| Spec section | Built as | Evidence |
|---|---|---|
| §5 Requisition | `INTERNAL_REQ_TRANSITIONS`, `hrms_requisition_service` | `test_internal_requisition_chain.py` |
| §6 Mandatory budget gate | `assert_sourcing_allowed()`, called by **both** posting and candidate creation; `budget_approval_is_mandatory()` proves `APPROVED` is unreachable without `PENDING_BUDGET` | `test_internal_budget_gate.py` |
| §7 Position scorecard | `hrms_position_scorecards`, dual approval — `required_approvals(managerial)` returns `[MANAGER, MD]` for managerial+, and refuses two signatures from one user | `test_scorecard.py` |
| §8–9 Sourcing & CV screening | postings, public apply, bulk screen (max 200, partial success) | `test_phase4/5` |
| §11 Assessment | `hrms_assessment_service`, dual review, optional per posting | `test_phase6` |
| §12 Panel interview | `hrms_interview_service` + panel composition rules; mandatory Management final round for managerial+ | `test_int2_panel_composition.py`, `test_int2_final_round_gate.py` |
| §13 Shortlisting committee | `hrms_shortlist_service`, `hrms_shortlist_reviews` | `test_int2_shortlist_committee.py` |
| §15 Reference check | `assert_reference_cleared()` runs **before any write** on offer creation; only `Positive` clears | `test_reference_gate.py` |
| §16 Salary within band | `assert_within_band()` reads the band **stamped on the requisition at its budget gate**, never the band master | `test_internal_offer_gates.py` |
| §17 Offer approval | `POST /offers/{no}/approve` (`offer.approve`); create-and-send in one call is **409 on internal**; editing CTC withdraws approval | `test_internal_offer_gates.py` |
| §18 Offer release | issued by HR directly — no client handover exists on this track | — |
| §19 Pre-boarding | `hrms_preboarding_service`, touchpoints + due list + At Risk flag | `test_int2_preboarding.py` |
| §20 Joining & induction | 5 extra induction checklist keys appended **on internal track only** | `test_phase9` |
| §21 Probation | `hrms_probation_reviews`, 1–12 months (default 6), confirm requires typed signature, confirmation closes the requisition | `test_probation.py` |
| §22 Personnel file closure | `POST /personnel-file/close` — 409 unless probation `Confirmed`, 422 on empty note | `test_probation.py` |
| §23 RACI | `ROLE_CAPABILITIES` + `required_approvals()` + panel composition tables | `test_capability_parity.py` |
| §24 Permissions | 84 capabilities, 8 roles, enforced at every route | `test_capability_parity.py` |
| §25 Multi-company | `company_id` is the **only** tenant boundary; per-company departments, salary bands, comm templates, id counters | `test_client_scope.py` |
| §26 SLA targets | `SLA_MILESTONES` — 3 / 2 / 15 / 3 working days + 2 date-anchored. **Matches the spec exactly.** | `test_sla.py`, `test_int2_sla_date_anchored.py` |
| §28 Documentation | `hrms_record_document_service` — 5 printable SOP forms as PDFs | — |
| §29 KPIs | `internal_kpis()` — all 8, with honest denominators | `test_int2_internal_kpis.py` |
| §30 Exceptions | `hrms_exceptions` + `EXCEPTION_UNBLOCKS`. **The only way to bypass a gate** — there is no override flag anywhere in the module | `test_exceptions.py` |
| §31 Compliance | PII behind capabilities; statutory pre-employment gate on confirmation; EEO + data-use acknowledgements | `test_int2_statutory_gate.py` |
| §32 Retention | `RETENTION_YEARS` stamps `retention_until`; purge **proposes → MD approves → redacts** (never hard-deletes) | `test_int2_retention_purge.py` |
| §33 Policy review | `hrms_policies` + `hrms_policy_revisions` (Modification History) | `test_int2_policy_register.py` |
| §37 Audit trail | append-only `hrms_audit_log`, every service writes through it | — |
| §41 Entities | 15 of the ~21 conceptual entities exist, under these names | — |

### A.4 Reusable infrastructure (do not rebuild)

- **Scheduler**: `start_reminder_scheduler()` — an asyncio task on a 60s tick with hour-gated
  daily jobs and per-job last-run memory. Extend this; do not add a second runner.
- **Notifications**: `hrms_notify_service` fan-out by user or by governance role.
- **Documents**: typed, versioned, S3-backed, owner-linked.
- **Audit**: one `audit()` call site pattern across all 34 services.
- **Working-day maths**: `working_days_between()` / `add_working_days()` in `hrms_sla_service`.
- **Holiday master**: the ERP has a `holidays` collection and module — **HRMS does not use it yet.**

---

## B. Gap analysis — specification vs. built code

Ten items. Everything else in the specification is already built.

| # | Gap | Spec § | Severity | Classification |
|---|---|---|---|---|
| 1 | ~~**No scheduler wiring.**~~ **CLOSED — Phase INT-3, 2026-08-14.** `hrms_scheduler_service` now drives all five sweeps from the ERP's existing reminder loop. See [§Gap 1 — closed](#gap-1--closed-phase-int-3) below. | §27 | ~~Critical~~ | Done |
| 2 | ~~**No telephonic screening stage.**~~ **CLOSED — Phase INT-4, 2026-08-15.** The record, the two statuses, the work queue and a gate on interview scheduling. See [§Gap 2 — closed](#gap-2--closed-phase-int-4). | §10, §36 | ~~High~~ | Done |
| 3 | ~~**Working days ignore public holidays.**~~ **CLOSED — Phase INT-6, 2026-08-15.** Per-company working calendar, opted into per company, off by default. See [§Gap 3 — closed](#gap-3--closed-phase-int-6). | §26, §42 | ~~High~~ | Done |
| 4 | ~~**No per-company configuration.**~~ **CLOSED — Phase INT-5, 2026-08-15.** `hrms_settings` is read at last: five numeric policy tables as a per-company overlay. See [§Gap 4 — closed](#gap-4--closed-phase-int-5). | §42, §25 | ~~High~~ | Done |
| 5 | ~~**Salary negotiation is a gate, not a record.**~~ **CLOSED — Phase INT-10, 2026-08-21.** One row per round with the band stamped as it stood, plus the §16 comparison surface. The gate did not move. See [§Gaps 5, 9, 10 — closed](#gaps-5-9-10--closed-phase-int-10). | §16 | ~~Medium~~ | Done |
| 6 | ~~**KPI dashboard filters are date-range only.**~~ **CLOSED — Phase INT-8, 2026-08-21.** All six filters on the API; four as dashboard dropdowns. See [§Gap 6 — closed](#gap-6--closed-phase-int-8). | §29 | ~~Medium~~ | Done |
| 7 | ~~**Internal requisition tracker is thin.**~~ **CLOSED — Phase INT-7, 2026-08-21.** One server-computed row per requisition with every stage rolled up; a Tracker view beside the existing action queue. See [§Gap 7 — closed](#gap-7--closed-phase-int-7). | §35 | ~~Medium~~ | Done |
| 8 | ~~**Record-level notifications missing.**~~ **CLOSED — Phase INT-9, 2026-08-21.** Eleven events across the four silent services, recipients per Annexure B. See [§Gap 8 — closed](#gap-8--closed-phase-int-9). | §38 | ~~Medium~~ | Done |
| 9 | ~~**Candidate communication is _partly_ automated.**~~ **CLOSED — Phase INT-10, 2026-08-21.** `interview_scheduled` is now automatic on schedule and reschedule; short notice is recorded and warned about (never blocked). `offer_summary`, `stage_update` and `preboarding_checkin` stay manual **by documented design** — writing to a candidate about money is a decision, not a side effect. | §34 | ~~Low~~ | Done |
| 10 | ~~**Score bands: spec says three, code has four.**~~ **RESOLVED — Phase INT-10, 2026-08-21.** Both readings are real, so it is a per-company choice: `Hold` is now an optional band in `score_bands` (set to null → Strong / Consider / Reject). The default stays the signed SOP's four. See [§Gaps 5, 9, 10 — closed](#gaps-5-9-10--closed-phase-int-10). | §13 | ~~Decision~~ | Done |

### Gap 1 — closed (Phase INT-3)

Implemented 2026-08-14. **54/54 test files pass**, including 78 new checks.

| Change | File |
|---|---|
| The driver — five jobs, the run ledger, the per-record guards | `services/hrms_scheduler_service.py` (new, 412 lines) |
| Wired into the ERP's existing 60-second loop | `services/reminder_scheduler.py` |
| `SCHEDULED_JOBS` table, `COLL_JOB_RUNS`, `PROBATION_REMINDER_DAYS`, the unique index | `models/hrms.py` |
| Tests | `services/hrms/tests/test_int3_scheduler.py` (new, 78 checks) |
| Docstrings that claimed nothing drove them | `hrms_sla_service`, `hrms_policy_service`, `scripts/hrms_retention_purge.py` |

**No second scheduler was introduced** and **no governance logic moved** — each job calls the
service that already owns the decision, so the rules stay in one place.

Three decisions worth recording, because a rewrite would lose them:

1. **The run ledger is a collection, not a dict.** The TPMS jobs beside it remember their
   last run in process memory, which is correct for them — they are idempotent syncs.
   Re-running a *reminder* job sends the reminder again, and memory resets on every deploy.
2. **Two independent guarantees.** The ledger stops a job running twice in a period; the
   per-record guards (`sla_escalated`, `reminders_sent`, an existing `Proposed` batch) stop a
   record being notified twice even if it does. The second is what makes the house
   convention — stamp on success, retry on failure — safe for something that sends email.
3. **The retention job proposes and never executes.** It refuses to write an empty batch and
   refuses to stack a second proposal while one awaits a decision. A test greps the module to
   prove it cannot call approve or execute at all.

Not included, deliberately: **the SLA targets these jobs measure against are still the
module constants.** Making them per-company is Gap 4, and doing it here would have meant
shipping a configuration service inside a wiring change.

### Gap 2 — closed (Phase INT-4)

Implemented 2026-08-15. **55/55 test files pass**, including 77 new checks. Frontend builds
clean.

| Change | File |
|---|---|
| The record, the scoring, the status moves, the gate, the work queue | `services/hrms_telephonic_service.py` (new, 489 lines) |
| 2 statuses + `STAGE_RANK` + `PIPELINE_COLUMNS` + `FORWARD_TRANSITIONS` edges, 2 capabilities, `TELEPHONIC_CRITERIA`, a new exception type + gate, retention, purge target, 4 indexes, 2 Pydantic models | `models/hrms.py` |
| The gate call, inside the internal-track branch | `services/hrms_interview_service.py` |
| 5 endpoints | `routes/hrms.py` (173 → 178) |
| `TelephonicBoard` + route + tab strip + `CAP` map + API client | `frontend/src/…` |
| Tests | `test_int4_telephonic.py` (new, 77 checks) |

**Where the gate sits: interview scheduling, not the record.** The SOP puts the call before
*the panel*, so `assert_telephonic_cleared` guards entry into interviewing — asked first,
because being told to make a ten-minute call is a cheaper refusal than being told the panel is
wrong after assembling one.

Four decisions worth recording:

1. **It is a gate, not a warning.** Annexure C chose "warn, never block" for interview
   *windows* — a scheduling convenience, where a hard refusal pushes an urgent booking
   off-system. A skipped screening *stage* is a deviation from the documented process, and the
   SOP already names the mechanism for those: a new `Telephonic Screening Waived` exception
   type, added the same way INT-2 added the statutory one. There is no override flag.
2. **`No Answer` is a third outcome that moves nobody.** Without it, an unreachable candidate
   forces HR to choose between recording a rejection they did not decide and recording
   nothing — and "nothing" is what makes a pipeline look stalled for no visible reason.
3. **Both statuses rank 2, with `Shortlisted`.** A phone screen is a decision *about* a
   shortlisted candidate, the same reasoning the client-share band already follows. Ranking it
   3 would have pushed assessment and interview up and renumbered every Phase 10 figure.
4. **An in-flight candidate is not gated retroactively.** The gate is silent once any interview
   record exists, so shipping this could not strand anybody already mid-pipeline behind a call
   nobody can go back and make.

**Two things the new test caught in code I had just written**, recorded because both are the
kind of bug that passes review: `update_screening` read `current` *after* writing to it (works
against real Mongo, silently does nothing against a fake — now captured before the write), and
`test_int2_panel_composition` began failing because its internal candidates had no phone screen
(its fixtures now carry one, so a failure there still names the right control).

### Gap 4 — closed (Phase INT-5)

Implemented 2026-08-15. **56/56 test files pass**, including 94 new checks. Frontend builds
clean.

| Change | File |
|---|---|
| The overlay, the validators, the readers, reset | `services/hrms_config_service.py` (new, 357 lines) |
| `CONFIG_SPEC` (the table *is* the specification), 2 capabilities, 2 Pydantic models, a unique index, `score_band(value, bands)` | `models/hrms.py` |
| 3 endpoints — `GET`/`PATCH /settings`, `POST /settings/reset` | `routes/hrms.py` (178 → 181) |
| Wired to read config | `sla`, `probation`, `scheduler`, `scorecard`, `shortlist`, `telephonic`, `candidate`, `comm`, `preboarding`, `reference`, `survey` |
| `HrmsSettings` screen + sidebar entry + `CAP` map + API client | `frontend/src/…` |
| Tests | `test_int5_config.py` (new, 94 checks) |

**What became configurable:** SLA target days, retention years, probation duration
(default/min/max), probation reminder tiers, score band floors. Five numeric policy tables,
each actually read by the code that used to hard-code it.

Five decisions worth recording:

1. **An overlay, not a replacement.** Every default is read from the constant that already
   shipped, so a company with no settings row reproduces pre-INT-5 behaviour key for key —
   no migration, nothing to backfill. A test asserts the defaults equal `SLA_MILESTONES` and
   `RETENTION_YEARS` themselves rather than a re-typed copy.
2. **Maps merge per name; lists replace whole.** Overriding one SLA target keeps the other
   three. A reminder-tier list *is* the setting, so merging it would make removing a tier
   impossible.
3. **A value equal to the default is still stored.** Pruning would be tidier and wrong: a
   deliberately-chosen compliance number would drift if the module default ever moved.
   `reset` is the explicit way back to *following* the default.
4. **No caching.** Callers inside loops take an optional pre-resolved `config` instead, so
   one sweep reads the settings row once and judges every requisition against the same
   targets even if somebody edits them mid-run.
5. **`settings.write` is Management's and Finance's, not HR's.** Annexure B makes
   Management/Finance accountable for policy review, and these numbers are that policy as
   data. HR reads them — a target you cannot see is one you cannot plan against.

**Three keys were considered and deliberately left out**, each recorded in the code rather
than left to be inferred:

- **The managerial threshold** — moving it requires `REQUIRED_PANEL_ROLES` to move with it,
  or a company that made `mid` managerial gets a mandatory Management final round while the
  panel table still says a mid role needs only HR and the HOD. Two tables that must agree;
  making one per-company is a design change, not a config key.
- **Whether an assessment is required** — already per posting, which is finer-grained.
- **The holiday calendar** — that is Gap 3, and declaring a flag nothing reads is exactly
  the mistake this phase existed to correct.

**No gate is configurable, and a test enforces it.** The budget gate, reference check,
scorecard approval and telephonic screen stay non-negotiable; deviations go through the
exception log, where they are attributable.

**One thing the new test caught in existing code:** `test_int3_scheduler`'s stub for
`sweep_open_breaches` no longer matched the real signature. Fixed, and the test now also
asserts the SLA job resolves the rule set *once* and hands it down rather than letting the
sweep read it per requisition.

### Gap 3 — closed (Phase INT-6)

Implemented 2026-08-15. **57/57 test files pass**, including 66 new checks. Frontend builds
clean.

| Change | File |
|---|---|
| The calendar, the import, `holiday_set()` | `services/hrms_holiday_service.py` (new, 210 lines) |
| Holiday-aware `working_days_between` / `add_working_days`, calendar threaded through `sla_for` / the sweep / `escalate_if_breached`, truthful `counts_holidays` + `basis` | `services/hrms_sla_service.py` |
| The shortlist KPI now reads the configured target **and** the calendar | `services/hrms_analytics_service.py` |
| `honour_holidays` flag (a new `flag` config kind), `COLL_HOLIDAYS` relocated and documented, `MAX_HOLIDAYS`, audit constants, unique index, 2 Pydantic models | `models/hrms.py` |
| 4 endpoints | `routes/hrms.py` (181 → 185) |
| Working-calendar editor on the settings screen + API client | `frontend/src/…` |
| Tests | `test_int6_holidays.py` (new, 66 checks) |

**The finding that shaped the design: the ERP's `holidays` collection has no `company_id`** —
not on read, not on write, not even in its duplicate check. Reading it directly was the
obvious implementation and would have been wrong: one admin adding a regional festival for
one entity would silently have moved every other entity's SLA due dates. So HRMS keeps its
own calendar (`hrms_holidays`, another collection declared since Phase 1 and read by
nothing), and the ERP master is an **import** — a copy a company adopts, with an audit row —
rather than a live dependency.

Four other decisions worth recording:

1. **Off by default, per company.** Turning it on changes whether *existing* requisitions
   read as breached. That is a decision with a date, not something that arrives with a deploy.
2. **`None` and `set()` are different answers.** None = does not honour a calendar; empty set
   = honours one with no dates. Collapsing them makes "no holidays this quarter"
   indistinguishable from "nobody set this up" — the same three-way rule `scope_client_ids`
   follows.
3. **The basis is reported, never assumed.** The SLA response carries `counts_holidays`,
   `holidays_in_calendar` (null when not honouring) and a plain-English `basis`.
4. **The maths stays pure.** The calendar is an argument, so the tests walk the functions
   directly; loops resolve it once and pass it down.

**One inconsistency fixed on the way past:** `internal_kpis` measured "shortlist within Day
15" against a hard-coded 15 while the SLA screen measured against the configured target — two
answers to one question since INT-5. It now reads both the company's target and its calendar.

### Gap 7 — closed (Phase INT-7)

Implemented 2026-08-21. **58/58 test files pass**, including 46 new checks. Frontend builds
clean.

| Change | File |
|---|---|
| The tracker service — one row, every stage, batched | `services/hrms_tracker_service.py` (new, 337 lines) |
| `GET /internal-requisitions/tracker` | `routes/hrms.py` (185 → 186) |
| `InternalTracker` view + a Queue/Tracker toggle on the existing screen | `frontend/src/…` |
| Tests | `test_int7_tracker.py` (new, 46 checks) |

The row carries everything spec §35 lists: requisition/company/department/position, HOD and
HR owner, vacancy count, budget status **with the approval date Annexure C names**, scorecard
status, sourcing status, candidate counts (total → shortlisted → interviewed → selected →
joined, by `STAGE_RANK`), shortlist status, offer status, joining date, probation end date,
current status, SLA status + due date + days elapsed/over, and exception status (open vs
approved).

Four decisions worth recording:

1. **Read-only, structurally.** The test greps the module source for the three write
   prefixes, the same guarantee the analytics service carries. (The first draft failed its
   own grep by *naming* the tokens in the docstring — the check is on text, not behaviour.)
2. **Batched: eight reads per page, whatever N is.** The test counts `find()` calls and
   proves the number does not grow when the requisition count quadruples. An empty page
   short-circuits rather than issuing `$in: []` reads.
3. **Scoped exactly as the requisition list** — same `_visibility_filter`, so a plain
   EMPLOYEE sees only what they raised and nobody sees a tracker row they could not open.
4. **The SLA cell declares its basis.** Milestone rows only (the two date-anchored
   milestones are per-joiner and cannot honestly collapse into one cell), measured against
   the company's INT-5 targets and INT-6 calendar. `sla_basis` says so in the payload.

**No new capability and no new route in either navigation list**: the tracker is gated on
`requisition.read` and lives as a view toggle on the existing internal-requisitions screen,
so the sidebar/tab-strip disjointness rule is untouched.

**Two things the new test surfaced:** `FakeCursor.sort()` is a no-op in the shared harness
(ordering assertions through it prove nothing — the test pins the sort the service *asks*
for instead), and fake users need `_source_collection`/`role` stamps or `hrms_role` resolves
them to None and scoping tests pass for the wrong reason. Both recorded as traps 51–52.

### Gap 6 — closed (Phase INT-8)

Implemented 2026-08-21. **59/59 test files pass**, including 23 new checks. Frontend builds
clean. The two guard tests that own this service — the read-only source grep and the
existing KPI suite — stayed green throughout.

| Change | File |
|---|---|
| Six filters on `internal_kpis`, one narrowing point, echoed `filters` | `services/hrms_analytics_service.py` |
| Six Query params on `GET /analytics/internal-kpis` | `routes/hrms.py` |
| Filter bar on the SOP KPI block (department / position / level / status) | `frontend … RecruitmentDashboard.jsx` |
| Tracker `designation_level` defect fix (see below) | `services/hrms_tracker_service.py` |
| Tests | `test_int8_kpi_filters.py` (new, 23 checks) |

Decisions worth recording:

1. **One narrowing point.** Filters narrow the requisition query; everything downstream
   already flows from `request_nos`, so a filtered numerator can never meet an unfiltered
   denominator. The test pins the budget KPI's denominator moving with the department filter.
2. **The level filter reads the master with the model's own reading** — unbanded counts as
   `mid`, matching the panel rules. Fails closed on a level with no designations; a
   designation outside the requested level returns the empty set as the honest answer to a
   contradiction.
3. **Garbage statuses and levels are 422**, never matched-against-nothing — an all-zero
   dashboard from a typo reads as "hiring stopped".
4. **HR/HOD filters are API-only in the UI** for now: no light "users by governance role"
   listing exists to feed a dropdown, and a free-text id field is a worse UI than none.
   Recorded here rather than silently omitted.

**Defect found and fixed on the way past:** the INT-7 tracker's `designation_level` cell
read `req["designation_level"]` — a field requisitions never carry (the band lives on the
designation master). Always null on real documents; the test fixtures had set the field
directly and hidden it. Now resolved through the master as a ninth batched read, and the
fixture seeds the master instead. Recorded as trap 56.

### Gap 8 — closed (Phase INT-9)

Implemented 2026-08-21. **60/60 test files pass**, including 45 new checks, and the diff was
run through a four-lens adversarial verification workflow (RACI correctness, duplicate/
re-fire analysis, contract/ordering safety, test soundness) before being called done.

| Change | File |
|---|---|
| Scorecard: drafted / sent back / partial / fully approved | `services/hrms_scorecard_service.py` |
| Reference: non-clearing outcome warns HR (once) | `services/hrms_reference_service.py` |
| Probation: opened / confirmed / extended / terminated, `_is_managerial` | `services/hrms_probation_service.py` |
| Exceptions: raised → MD+FINANCE; decided → the raiser | `services/hrms_exception_service.py` |
| Tests | `test_int9_notifications.py` (new, 26 checks) |

Decisions worth recording:

1. **Recipients follow Annexure B, and channel follows the RACI letter.** "I" (informed) is
   in-app; a decision somebody is waiting on is email. The HOD is addressed as the
   requisition's raiser (a person); Management, Finance and HR as governance roles.
2. **One event, one notification.** Fired only on the state-changing edit: remarks on an
   already-negative reference, or a re-signature, say nothing again. The reference update
   path captures `previous_outcome` before the write (trap 36's lesson applied).
3. **Late imports of the notify facade** (the SLA service's pattern), so seed scripts and
   tests that patch `hrms_notify_service` attributes silence all of it. A structural check
   in the test asserts no service imports the facade at module top.
4. **Notify calls come after the business write**, so a notification can never describe a
   write that then failed. The facade's own contract (never raises) covers the reverse.

**A latent INT-3 bug found and fixed:** a probation extension returns the review to Pending
with a later `ends_on` — but the scheduler's reminder tiers were recorded as fired on the
record, so the extended period would never have been reminded about. The extension path now
resets `reminders_sent`, pinned by a test. Recorded as trap 58.

**What the adversarial verification found (30 agents, 4 lenses, 22 confirmed findings →
12 distinct defects, all fixed the same day):**

| # | Defect | Fix |
|---|---|---|
| 1 | Re-signing a partial scorecard re-fired the chase; a second Fail re-fired the sent-back mails | chase fires only when `outstanding_roles` changed; second Fail is 409 |
| 2 | The reference warning fired on CLIENT-track candidates, recommending a waiver `raise_exception` would refuse | `_notify_if_not_cleared` resolves the track and stays silent off the internal one |
| 3 | A managerial TERMINATION never informed Management, though a confirmation did | TERMINATED branch mirrors CONFIRMED: MD informed, in-app |
| 4 | The confirmed mail said "the requisition is closed" even when the closer had silently declined | the closer returns whether it closed; the sentence is conditional |
| 5 | The drafter was told twice about a rejection — by name AND by the HR fan-out | `notify_hrms_role` grew `exclude_user_ids` |
| 6 | The "needs approval" mail assumed the raiser can approve — any employee may raise | raiser's role is resolved; HOD role broadcast when they cannot |
| 7 | Re-queueing a scorecard (edit after rejection / signature-voiding change) notified nobody | `update_scorecard` re-asks the approver on re-queue |
| 8 | Moving `ends_on` through PATCH left the burned reminder tiers in place — the extension bug's sibling path | tiers reset on any real `ends_on` change |
| 9 | Two concurrent probation decisions could both land (read-then-write guard) | decision write is a CAS on the Pending state |
| 10 | Two concurrent scorecard signatures could silently drop one (snapshot-rebuild-overwrite) | signature write is a CAS on the approvals array it merged from |
| 11 | A reassigned probation review never told the new reviewer | handover notification on reviewer change |
| 12 | The scheduler's tier burn could overwrite a concurrent extension's re-arm | burn conditioned on `(ends_on, Pending)` as computed |

Two harness fixes fell out: `FakeCollection._matches` gained Mongo's array-equality arm
(without it every list-field CAS read as a phantom conflict), and the reviewer-handover
comparison had to be captured before the write — trap 36's live-reference lesson, hit again
in the phase that documented it. Four claims were **rejected** by the verifiers (governance-
role case sensitivity, a probation track guard that lives correctly upstream, and two
test-strengthening suggestions misfiled as defects).

### Gaps 5, 9, 10 — closed (Phase INT-10)

Implemented 2026-08-21. **61/61 test files pass**, including 86 checks in the new file and a
new section in the config test. The diff was run through a four-lens adversarial
verification (gate invariant, contract/scoping, RACI/frontend, test soundness) — **29 agents,
22 confirmed findings → 16 distinct defects, all fixed the same day**; three claims were
rejected as non-defects.

| Change | File |
|---|---|
| The negotiation record, the §16 comparison surface, row scoping | `services/hrms_negotiation_service.py` (new) |
| `negotiation_verdict`, `NegotiationRoundIn`, caps + grants, composite + per-round unique indexes, purge target, retention, `INTERVIEW_NOTICE_HOURS`, `interview_scheduled` → automatic, optional `Hold` band | `models/hrms.py` |
| 4 endpoints | `routes/hrms.py` (186 → 190) |
| Internal-only notice stamps, honest time label, naive/aware-safe reschedule compare, warning worded by the send's actual status | `services/hrms_interview_service.py` |
| `fire_event` returns what happened; templates classified server-side | `services/hrms_comm_service.py` |
| `describe()` exposes `optional_names`; null allowed for optional names only | `services/hrms_config_service.py` |
| `NegotiationBoard`, an Off control on the settings screen, server-driven template chips, the scheduler shows the warning | `frontend/src/…` |
| Tests | `test_int10_negotiation.py` (new, 86 checks); `test_int5_config.py` §11 |

**What the verification found and what changed:**

| # | Defect | Fix |
|---|---|---|
| 1 | `NaN` passed every comparison, recorded as *within*, skipped the Management notice, and left an unserialisable row that 500'd every read of the board | refused at the service (`isfinite`, plausibility cap) **and** the boundary (`allow_inf_nan=False`); the verdict returns `None` for non-finite |
| 2 | On an unbanded internal requisition the surface said NO while the offer gate fails open (pre-band-gate rows) — the one divergence the surface exists to prevent | the surface mirrors the gate and names the gap |
| 3 | Round numbering was read-then-insert with no uniqueness — two simultaneous round-3s | unique `(company, uk, round)` index; `DuplicateKeyError` → renumber once, then 409 |
| 4 | `uniq_neg_no` was bare, but ids are minted per company — tenant two's first round would collide | composite `(company_id, neg_no)` |
| 5 | Retention clamped every day > 28, not just 29 February | the siblings' 29-Feb-only rule |
| 6 | `candidate_name` was redacted on negotiation rows but survived in five sibling collections | added to every candidate-linked purge target |
| 7 | No row scoping: a HOD saw every candidate's pay across the company; `actor` was unused | the candidate pipeline's own `_scope_filter` / `_require_visible` (404, fail-closed) |
| 8 | INTERNAL (support staff) could read per-candidate pay, against the role's own stated rule | `NEGOTIATION_READ` withdrawn |
| 9 | "Latest round" depended on cursor order | sorted in Python as well as at the DB |
| 10 | Gap 9 ran on the **client track** — stamps, a Sparsh-originated email, a new warning | everything keyed on `_is_internal(req)`, at booking and on reschedule |
| 11 | The candidate's time was labelled "UTC" but carried the IST input's offset | normalised, formatted and labelled IST |
| 12 | A PATCH echoing the unchanged time read as a reschedule (aware vs naive compare) — ICS bump, re-notify, re-email | compared as UTC to the millisecond |
| 13 | The warning said "the candidate has been told" regardless of whether the send happened | `fire_event` returns the log status; wording follows it; `candidate_notified` stamped |
| 14 | The scheduling UI discarded the warning — "warn, never block" reached nobody | shown |
| 15 | `CommTemplates` still called `interview_scheduled` manual, from a hard-coded map | server stamps `automatic` / `manual` / `consent` |
| 16 | The three-band reading could not be switched on from the settings screen, and a null rendered as the word "null" | `optional_names` exposed; an explicit Off control; `save()` sends null for optional names |

The three rejected claims: emailing Management/Finance on an out-of-band round (they are **A**
on that row, not I — email is right); the board's row hint "needs fresh approval" (a fixed
string keyed off the server's verdict, not a browser judgement); and Pydantic coercing
`true` → `1.0` (the service-level bool guard still holds for direct callers, and `gt=0`
now bounds the boundary).

**Two harness lessons, again:** the shared `FakeCursor.sort` is a no-op, so order-dependent
logic must be asserted by reversing the stored order (trap 51); and the behavioural
interview test had to patch `hrms_comm_service.fire_event` — not the interview module —
because `_tell_candidate` imports it late (trap 59). Both were already written down; both
still had to be applied.

### Not a gap, but worth knowing

- **Client-scope narrowing is a shipped primitive that is not wired to pipeline surfaces**
  (`assert_client_allowed`, `require_engagement`). This affects the **client** track only —
  it is not a blocker for Sparsh Magic internal hiring. Do not provision a real client user
  until it is wired.
- **Leave, attendance and payroll are not built** and are out of this scope.
- **The spec's §36 flat status lifecycle does not match the implementation, by design.** The
  module separates *requisition approval status* from *candidate status* — one requisition
  carries many candidates at different stages, so a single flat lifecycle cannot represent
  the real state. This is a better model and should not be "corrected".

---

## C. Proposed architecture for the remaining work

Minimum change, maximum reuse. No new module, no new scheduler, no new design language.

### C.1 Scheduler (gap 1) — the priority

Extend `services/reminder_scheduler.py` following the **existing TPMS pattern**: an hour
constant, a gate on `hour >= N`, and a separate last-run memory per job so one failure never
consumes another's slot.

```
HRMS_SLA_SWEEP_HOUR      = 7   daily  -> sweep_open_breaches()   per hrms-enabled company
HRMS_PROBATION_HOUR      = 7   daily  -> tiered reminders at 30 / 15 / 7 / 1 days
HRMS_PREBOARDING_HOUR    = 8   daily  -> due_touchpoints() + joining-date reminders
HRMS_POLICY_REVIEW_HOUR  = 8   weekly -> notify_due_reviews()
HRMS_RETENTION_HOUR      = 3   weekly -> purge_service.propose() ONLY (never approve)
```

Two rules this must honour:

1. **The purge job proposes; it never executes.** Execution stays behind
   `POST /purge-batches/{batch_no}/approve`, the MD's capability and a typed signature.
   Invariant 15 ("the purge redacts, never hard-deletes, and never runs without an approval")
   is not negotiable.
2. **Reminders need sent-state**, or a 60s loop re-notifies all day. Follow
   `reminder_scheduler`'s own `REMINDER_MAX_AGE_HOURS` / `sent` flag convention rather than
   inventing a second one.

Companies to iterate: those with `companies.hrms_enabled` true.

### C.2 Configuration service (gap 4)

Implement the already-declared `hrms_settings` collection as a **per-company overlay over the
existing constants** — not a replacement for them.

```python
async def hrms_config(company_id: str) -> dict:
    """Module defaults, overlaid with this company's overrides. Defaults are the constants
    that ship today, so a company with no settings row behaves exactly as it does now."""
```

Overridable: SLA target days per milestone, retention years per record type, probation
default duration, managerial threshold (`MANAGERIAL_LEVELS`), reminder intervals, score-band
floors, assessment-required default, holiday-calendar opt-in.

**This is what makes §25 multi-company real.** Today a second Sparsh group entity would share
one hard-coded rule set. Data is already per-company; rules are not.

### C.3 Holiday-aware working days (gap 3)

Add an optional holiday set to `working_days_between()` / `add_working_days()`, loaded per
company from the ERP `holidays` collection and **gated on the config flag from C.2**.

The existing deferral note is right that honouring holidays *silently* would make two
companies disagree about whether the same requisition breached. Making it an explicit,
per-company setting resolves that objection without losing the capability.

### C.4 Telephonic screening (gap 2)

New collection `hrms_telephonic_screenings`, carrying `request_no` and `uk` (invariant 12).
Two new `AppStatus` values plus their `STAGE_RANK` entries and `FORWARD_TRANSITIONS` edges —
**rank 2, alongside `Shortlisted`**, because a phone screen is a decision *about* a
shortlisted candidate, exactly as the client-share band is.

> Adding a status without its `STAGE_RANK` entry silently ranks it 0 — counted in totals,
> credited to no funnel stage. This is trap #9 in the overview.

Capture per the spec: communication, notice period, salary expectation, location,
availability, motivation, role understanding, suitability, comments, score.

### C.5 Salary negotiation record (gap 5)

New collection `hrms_salary_negotiations` (`request_no` + `uk`), one row per round: candidate
expectation, proposed CTC, the approved band as it stood, the computed verdict
(`within` / `above` / `below`), who proposed, when, and the linked exception if above.

**The gate does not move.** `assert_within_band()` stays the enforcement point; the
negotiation record is the history and the comparison surface the spec asks to *display*.

### C.6 Everything else

- Gap 6 — add filter parameters to `internal_kpis()`, reusing the existing `_scope()` and
  `SCAN_CAP` guards. **Analytics still never writes** (invariant 8; the test greps source
  text for `insert_` / `update_` / `delete_`, comments included).
- Gap 7 — extend `InternalRequisitionList` columns from data the API already returns plus one
  aggregate endpoint. Nothing computed in the browser (invariant 9).
- Gap 8 — add `notify_hrms_role` / `notify_user` calls at the four silent services.
- Gap 9 — drive template sends from the C.1 jobs; measure interview notice in the SLA table.

### C.7 What must not change

| Invariant | Why it matters here |
|---|---|
| `company_id` is the only tenant boundary | multi-company (§25) rests entirely on it |
| Filters fail closed (`$in: []`, never absent) | a widening filter is a data leak |
| Every stage move through `FORWARD_TRANSITIONS` | new telephonic statuses must use the graph |
| Every approval through `TRACK_TRANSITIONS` | no branching on track inside handlers |
| A gate is bypassed only by an approved exception | no override flags, ever |
| Analytics never writes | enforced by a source-text grep test |
| Frontend `CAP` map == backend `Cap` enum | else controls silently vanish |
| Client track behaviour is byte-for-byte preserved | every new control keys on `track == internal` and returns early |

---

## D. Database changes

### New collections (4)

| Collection | Purpose | Carries |
|---|---|---|
| `hrms_settings` | per-company rule overrides (declared today, unused) | `company_id` — config, so no `request_no`, same reason `hrms_document_types` has none |
| `hrms_telephonic_screenings` | gap 2 | `company_id`, `request_no`, `uk` |
| `hrms_salary_negotiations` | gap 5 | `company_id`, `request_no`, `uk` |
| `hrms_job_runs` | scheduler last-run + sent-state ledger | `company_id`, `job_key`, `last_run_at` |

### Modified models — `models/hrms.py` only

- `AppStatus`: `TELEPHONIC_PASSED`, `TELEPHONIC_REJECTED`
- `STAGE_RANK`: both at rank 2
- `FORWARD_TRANSITIONS`: edges in from `Shortlisted`, out to assessment/interview
- `ID_FORMATS`: `TEL-`, `NEG-`
- `Cap`: `telephonic.read/write`, `negotiation.read/write`, `settings.read/write`
  — **and the identical additions to `frontend/src/features/hrms/access.js`**
- `ROLE_CAPABILITIES`: HR gets telephonic + negotiation write; MD/FINANCE get settings write
- `SLA_MILESTONES` / `RETENTION_YEARS`: unchanged as **defaults**, read through the config
  overlay rather than directly

### Indexes

```
hrms_telephonic_screenings   (company_id, request_no)   (company_id, uk)
hrms_salary_negotiations     (company_id, request_no)   (company_id, uk)
hrms_settings                (company_id) unique
hrms_job_runs                (company_id, job_key) unique
```

### No migration is required

Every change is additive. Existing requisitions have no `requisition_track` field and
`track_of()` already reads that absence as `client`. Existing companies have no `hrms_settings`
row and the overlay falls through to today's constants. **No existing document is rewritten.**

---

## E. API changes

### New endpoints

```
GET    /hrms/settings                          settings.read     per-company config + defaults
PATCH  /hrms/settings                          settings.write    override; validated per key

GET    /hrms/telephonic-screenings             telephonic.read
POST   /hrms/telephonic-screenings             telephonic.write  201
GET    /hrms/telephonic-screenings/{tel_no}    telephonic.read
PATCH  /hrms/telephonic-screenings/{tel_no}    telephonic.write  records outcome + score

GET    /hrms/negotiations                      negotiation.read  ?uk= filter
POST   /hrms/negotiations                      negotiation.write 201; computes the verdict
GET    /hrms/candidates/{uk}/negotiation       negotiation.read  comparison surface
```

### Modified endpoints

| Endpoint | Change | Compatibility |
|---|---|---|
| `GET /hrms/analytics/internal-kpis` | + `department_id`, `designation_id`, `designation_level`, `hr_user_id`, `hod_user_id`, `status` | all optional; omitting all reproduces today's response exactly |
| `GET /hrms/requisitions` (internal track) | + tracker aggregate fields | additive keys only |
| `GET /hrms/requisitions/{no}/sla` | reads targets through the config overlay | identical output with no settings row |
| `POST /hrms/candidates/screen` | `telephonic` action added to `ScreenAction` | existing actions unchanged |

**No endpoint is removed, renamed or given a required parameter it did not have.**

---

## F. UI changes

### New screens (3)

| Route | Component | Placement |
|---|---|---|
| `/hrms/telephonic-screening` | `TelephonicBoard` | workspace tab strip (a hiring stage) |
| `/hrms/negotiations` | `NegotiationBoard` | workspace tab strip |
| `/hrms/settings` | `HrmsSettings` | sidebar, admin-only (governance) |

> The sidebar list and the workspace tab strip **must stay disjoint** — a route in
> `HRMS_WORKSPACE` must not also appear in `hrmsSubmodules`.

### Modified screens (3)

- `InternalRequisitionList` — the full tracker column set, with status badges reusing the
  existing `statusConfig` vocabulary and an SLA health indicator.
- `RecruitmentDashboard` — filter bar on the `internal_kpis` block (it already renders
  `data.internal_kpis` via `KpiGrid`).
- `CandidateJourney` — telephonic and negotiation events on the existing timeline.

All of it reuses `HrmsPageHeader`, `HrmsScopeBar`, `HrmsStates`, the existing table/card
responsive pattern and Tailwind utilities. **No new design language, no custom CSS.**

---

## G. Scheduler jobs

| Job | Frequency | Condition | Action | Notification |
|---|---|---|---|---|
| `hrms_sla_sweep` | daily 07:00 | internal requisitions with open milestones | `sweep_open_breaches()` | approaching → owner; breached → owner + Management |
| `hrms_probation_reminders` | daily 07:00 | probation `Pending`, `ends_on` in 30/15/7/1 days | tiered reminder, one per tier per record | HOD + HR; Management for managerial+ |
| `hrms_preboarding_reminders` | daily 08:00 | accepted offers with a future joining date | `due_touchpoints()` + At Risk flag | HR owner |
| `hrms_policy_review` | weekly Mon 08:00 | policy review date due | `notify_due_reviews()` | HR + Management |
| `hrms_retention_propose` | weekly Sun 03:00 | records past `retention_until` | `purge_service.propose()` — **proposal only** | MD: batch awaiting approval |

Each iterates companies with `hrms_enabled`, records its run in `hrms_job_runs`, and is
remembered independently so one failure never consumes another's slot.

**Nothing on this list deletes anything.** The retention job creates a proposal; only an MD
with `retention.purge` and a typed signature causes redaction.

---

## H. Migration strategy

There is nothing to migrate. Stated explicitly because the specification asks:

1. **No schema is rewritten.** All four new collections are new; all model changes are new
   enum members and new optional fields.
2. **Existing recruitment data is untouched.** Client-track requisitions carry no
   `requisition_track` field; `track_of()` reads absence as `client`. That default is the
   compatibility guarantee and it is already in place.
3. **Existing internal-track records keep working.** The config overlay returns today's
   constants when no settings row exists.
4. **Rollback** is removing the new routes and the scheduler constants. No data written by
   the new code is read by the old code.
5. **The one behaviour change to stage deliberately** is holiday-aware SLA maths: it alters
   whether a requisition is reported as breached. It ships **off**, per company, behind the
   config flag — turning it on is a business decision with a visible date.

---

## I. Testing plan

House convention throughout: **no pytest, no live DB, `FakeCollection`, ASCII output, exit 1
on failure**, one self-contained file per area.

### Regression first (before any change)

```bash
cd backend
for f in app/services/hrms/tests/test_*.py; do
  .venv/Scripts/python.exe -m "app.services.hrms.tests.$(basename $f .py)"
done
```

Current baseline: **53/53 pass.** This must still read 53/53 after every gap is closed, plus
the new files below.

### New test files

| File | Asserts |
|---|---|
| `test_int3_scheduler.py` | each job selects the right records; is idempotent across two ticks in one day; a failure in one job does not consume another's slot; **the retention job proposes and never executes** |
| `test_int3_config.py` | absent settings row reproduces the constants exactly; an override changes the SLA due date; an invalid key is refused; one company's override does not reach another |
| `test_int3_telephonic.py` | new statuses have `STAGE_RANK` entries; illegal transitions 409; the funnel stays monotonic; capability enforced |
| `test_int3_negotiation.py` | verdict is correct within/above/below; above-band still requires an exception; **`assert_within_band` remains the enforcement point** |
| `test_int3_holidays.py` | flag off → weekends only (today's answer, unchanged); flag on → a company holiday extends the due date; two companies with different calendars get different answers |
| `test_int3_notifications.py` | probation-due reaches the HOD; exception-pending reaches Management; no notification fires twice for one event |

### Existing tests that must be extended, not replaced

- `test_capability_parity.py` — the six new capabilities in **both** files.
- `test_e2e_recruitment_journey.py` §13 — the structural assertion that every internal control
  keys on `track == internal`. Extend it to cover telephonic and negotiation.
- `test_phase10_analytics.py` — the read-only grep. **Do not write the literal tokens
  `insert_`, `update_` or `delete_` in `hrms_analytics_service.py`, comments included.**

### Manual end-to-end, per role

Run one internal requisition through HR → HOD → Management/Finance, asserting at each gate
that the role *without* the capability is refused **by the API**, not merely by a hidden
button. Then repeat for a managerial+ role and confirm the Management stages engage, and for
a non-managerial role and confirm they do not.

---

## Recommended sequence

| | Work | Why this order |
|---|---|---|
| ~~1~~ | ~~**Scheduler wiring** (gap 1)~~ — **done 2026-08-14** | Every SOP reminder and escalation was dead. Highest value, lowest risk — the functions existed and were tested. |
| ~~2~~ | ~~**Config service + holiday calendar**~~ (gaps 4, 3) — **both done 2026-08-15** | Unblocked genuine multi-company. Everything after it reads config rather than constants. |
| ~~3~~ | ~~**Telephonic screening** (gap 2)~~ — **done 2026-08-15** | The one real pipeline stage that was missing. Shipped ahead of gaps 3/4 because it was the only hard ✗ in the SOP's process flow. |
| 4 | **Tracker + KPI filters + notifications** ~~(gaps 7, 6, 8)~~ — **all done 2026-08-21** | Visibility work, no new gates. |
| ~~5~~ | ~~**Negotiation record** (gap 5)~~ — **done 2026-08-21** | The rule was already enforced; this added the history. |
| ~~6~~ | ~~**Automated candidate comms** (gap 9)~~ — **done 2026-08-21** | Interview confirmation automated; the money-related templates stay manual by design. |

**Open question before step 1:** gap 10 — three score bands (this specification) or four (the
signed SOP, and what the code does)? Recommendation: **keep the four**. The SOP is the signed
policy, spec §13 itself says to reuse existing scoring logic, and once the config service in
step 2 lands the floors become a per-company setting rather than a code decision.
