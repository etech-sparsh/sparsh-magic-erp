# TPMS → ERP: Implementation Plan

Companion to [TPMS_MODULE_ANALYSIS.md](TPMS_MODULE_ANALYSIS.md) (what the system does).
This document is **how we build it**.

Goal: replicate the AppScript TPMS module into the ERP with **identical functionality,
workflows and UI**, changing only the colour scheme to the ERP theme — while reusing what the
ERP already has and never breaking existing modules.

---

## 0. Guiding principles

1. **Extend, don't fork.** Where the ERP already solves a problem (recurrence, reminders,
   email, uploads, auth), TPMS becomes a *caller* of that service, not a second copy. The one
   deliberate exception is scoring, which has no ERP equivalent.
2. **Additive schema only.** Every TPMS field added to an existing collection is optional with
   a default. No migration may rewrite a document another module owns.
3. **Discriminate, don't duplicate.** TPMS activities live in `calendar_events` behind a
   discriminator, so one calendar UI and one recurrence engine serve both modules.
4. **Sheet parity is verified, not assumed.** Every ported rule gets a test fed by the real
   xlsx rows (3.5k of them) so behaviour can be diffed against the sheet.
5. **Theme via tokens.** No hex codes in TPMS components. Map AppScript's palette onto the
   existing CSS variables once, centrally.
6. **Ship behind a flag.** TPMS routes already have `RequireTpms`. Keep new endpoints dark
   until their phase is verified.

---

## 1. Reuse inventory

The single most important input to this plan. **~45% of the module already exists.**

### 1.1 Reuse as-is (do not touch)

| Capability | Location | Notes |
|---|---|---|
| Auth, JWT, `get_current_user` | `app/controllers/auth_controller.py` | Replaces AppScript's UUID-in-cache session |
| Roles & permissions | `app/models/user.py`, `rbac.py` | `superadmin/admin/clientadmin/clientuser` + per-module CRUD flags |
| Companies | `app/routes/company.py`, `companies` | Direct substitute for the `Companies` sheet |
| Users | `staff` + `learners` collections | Substitute for `Staff` + `Company_Employees` |
| Email delivery | `app/services/notification_service.py` | SMTP + `{{var}}` template registry + `send_notification_from_template` |
| **WhatsApp delivery** | `notification_service.send_whatsapp_template` | Already implemented — TPMS's Meta integration is *not* new work |
| File storage | `app/services/s3_service.py` | Replaces Drive; signed URLs + multipart already there |
| Background job runner | `app/services/reminder_scheduler.py` | asyncio loop, 60s tick, started in `main.py` lifespan |
| Recurrence engine | `recurring_task_service.py` + `calendar_events` `repeat` | Covers Daily/Weekly/Monthly/Periodically |
| Form submission API | `app/routes/forms.py` (720 L) | Rating matrix + Yes/No, cell-level partial submit, all working |
| Form collections + indexes | `app/db/mongodb.py:_ensure_form_collections` | Auto-provisioned at startup |
| TPMS routing + role gate | `features/tpms/TpmsGate.jsx`, `access.js` | 3 panels (admin/smops/client) already wired in `App.jsx` |
| TPMS visual kit | `features/tpms/common/dashboardKit.jsx` | `KpiTile`, `Section`, `TableShell`, `StatusBadge`, `Progress`, `Fraction`, `Trend`, `DashboardHero` — already ERP-themed |
| Generic table | `features/tpms/common/DataTable.jsx` | search + sort + pagination |
| Theme tokens | `src/index.css` | CSS vars, light **and** dark mode |

### 1.2 Extend (existing thing, needs TPMS-specific additions)

| Thing | Extension needed |
|---|---|
| `calendar_events` | TPMS discriminator + lifecycle fields (§2.2) |
| `PATCH /calendar/events/{id}/complete` | Today: one-step, admin-only. TPMS needs **two-step** learner-done → staff-confirm |
| `POST /calendar/events/validate-conflict` | Add the TPMS *once-per-month per scope* rule alongside the existing time-overlap check |
| `ScheduleCalendarModal.jsx` | Activity list is hardcoded in the component — switch to the new catalogue API |
| `forms.py` `/dashboard` | Already computes a client scorecard; becomes one consumer of the real Success-Measure service |
| `reminder_scheduler` | Add 3 TPMS daily jobs to the existing loop |
| `FORM_DEFINITIONS` | Fix Culture (`audience`), add Implementation Feedback questions |

### 1.3 Build new (no ERP equivalent)

Activity catalogue · reminder rules · reschedule-request workflow · escalation engine ·
action items · activity tracker · **Success-Measure engine** · task uploads bound to a
schedule · TPMS mail-template resolution (per activity × side × event) · 8 dashboard
endpoints · the TPMS Calendar page · the xlsx→Mongo migration.

---

## 2. Phase 1 — Database

**Objective:** every collection, index and migration in place, with real data loaded, before a
line of business logic is written.

### 2.1 New collections

All prefixed `tpms_`, provisioned in `_ensure_form_collections` (rename to
`_ensure_tpms_collections`) so they self-create at startup like the form tables already do.

| Collection | Source sheet | Rows | Key fields | Indexes |
|---|---|---|---|---|
| `tpms_activities` | `Activity` | 14 | `name, short, frequency, scope(company\|hod), upload_required, score_mode(manual\|auto\|form), doc_link` | `{name:1}` unique |
| `tpms_reminder_rules` | `Activity_Reminder_Rules` | 3 | `activity('*'\|name), stage, offset_value, offset_unit, offset_dir, channel, active` | `{activity:1, active:1}` |
| `tpms_reschedule_requests` | `Reschedule_Requests` | 0 | `event_id, company_id, old_date, new_date, reason, requested_by, status, decided_by, note` | `{status:1, company_id:1}` |
| `tpms_task_uploads` | `Task_Uploads` | 0 | `event_id, company_id, activity, scope, period, member_id, s3_key, file_name, uploaded_by, uploaded_at` | `{event_id:1}`, `{company_id:1, period:1}` |
| `tpms_activity_tracker` | `Activity_Tracker` | 422 | `company_id, member_id, period, date, activity, status, event_id` | `{company_id:1, period:1, activity:1}`, `{event_id:1}` |
| `tpms_escalations` | `Escalations` | 82 | `event_id, company_id, om, activity, target_date, level, escalated_to, status, resolution_*` | `{event_id:1}` unique, `{status:1, company_id:1}` |
| `tpms_action_items` | `Action_Items` | 127 | `event_id, company_id, activity, action, owner_id, target_date, status, delay_days, learner_delay_days, staff_delay_days` | `{event_id:1}` unique, `{status:1}` |
| `tpms_success_measures` | `Success_Measures` + `Success_Manual` | 942 | `company_id, activity, period, impl_target, impl_actual, score_target, score_actual, achievement, scope, hod_id, updated_at` | `{company_id:1, activity:1, period:1}` **unique** |
| `tpms_mail_templates` | `Templates` (11 cols) + `HOD_Form_mail_templates` (6 cols) | 15 | `activity, side(staff\|company), event(schedule\|reminder\|reschedule\|cancel\|complete), subject, body_html` | `{activity:1, side:1, event:1}` unique |

**Decision — notification logs.** `Scheduled_logs` (763) + `Whatsapp_logs` (195) +
`HOD_Form_mail_logs` merge into the **existing** ERP notification-log collection with a
`module:"tpms"` tag, rather than a new `tpms_notification_logs`. Verify the existing
collection name in `notification_service.log_notification` before migrating.

**Skip entirely:** `Pivot Table 1`, the 12 empty `*_master` sheets, the 5 `* Dashboard` mock-up
tabs, `Mail Reminder`, `Sheet36` (duplicate of the feedback responses).

### 2.2 Extending `calendar_events`

A TPMS activity **is** a calendar event. Add a discriminator plus lifecycle fields — all
optional, all defaulted, so every existing event document stays valid.

```python
# app/models/calendar_event.py — additive
kind: Optional[str] = None          # "tpms_activity" | None (all existing events)
batch_id: Optional[str] = None      # groups a recurrence expansion
esc_stage: int = 0                  # 0..3, escalation ladder progress
reschedule_count: int = 0
learner_done: bool = False
learner_done_by: Optional[str] = None
learner_done_at: Optional[datetime] = None
completed_by: Optional[str] = None  # confirm `completed_at` isn't already present
```

Already present and reusable — **do not re-add**: `activity`, `activity_meta`, `company_id`,
`company_name`, `assigned_departments`, `assigned_member_ids`, `coach_ids`, `repeat`,
`repeat_end_date`, `repeat_data`, `reminders[]`, `status`, `status_history`, `attachments`.

⚠ **Verify first:** events are spread across several collections
(`CALENDAR_COLLECTIONS` + `calendar_events`, see `find_event_across_collections`). Every TPMS
aggregation must scan the same set — `forms.py` already does this via `_CAL_COLLECTIONS`.
Reuse that constant; do not hardcode one collection name.

New indexes on the calendar collections: `{kind:1, company_id:1, start:1}` and
`{kind:1, status:1, start:1}` (the escalation sweep's access path).

### 2.3 Canonical formats

| Concept | Standard | Rationale |
|---|---|---|
| Period | **`YYYY-MM`** stored | `forms.py:_month_parts` already converts to the legacy `jul26`/`July26` tokens for reads — that's the migration bridge, keep it |
| Dates | ISO `YYYY-MM-DD` | matches existing events |
| Identity | Mongo `_id` as string | never the sheet's `EMP_223` (keep as `employee_id` for traceability) |
| Percentages | `int` 0–100 | sheet stores `"100%"` strings — strip on migration |

### 2.4 Migration script — ❌ OUT OF SCOPE

**Decision (user): schema only, no data migration.** The historical sheet data (3.5k rows)
will not be loaded. The section below is retained only in case that changes.

The one exception is **master/reference data**, which the module cannot function without and
which is configuration rather than history: the 14-row activity catalogue and the 3 default
reminder rules are seeded at startup by `_ensure_tpms_collections`. Seeding is insert-only and
skipped entirely once the collection has rows, so it never overwrites operator edits.

<details><summary>Retained migration design (not being built)</summary>

`backend/scripts/migrate_tpms_from_xlsx.py` — idempotent, re-runnable, `--dry-run` first.

Order matters (referential integrity):
1. `tpms_activities`, `tpms_reminder_rules`, `tpms_mail_templates` — master data, no deps
2. Map `Company_ID` → ERP company `_id`; **fail loudly on any unmapped company**
3. Map `Employee_ID` / `Staff_ID` → `staff`/`learners` `_id`; build a lookup table and persist
   it (`tpms_migration_map`) so later steps and re-runs are stable
4. `Calendar_Schedule` (512) → calendar events with `kind:"tpms_activity"`
5. `Reminders` (294) → event `reminders[]`
6. Response sheets (593 rows) → the four existing `tpms_*` form collections
7. `Activity_Tracker`, `Action_Items`, `Escalations` — all keyed to step 4's event ids
8. `Success_Measures` + `Success_Manual` → merged `tpms_success_measures`
9. Logs → notification-log collection with `module:"tpms"`

</details>

**Exit criteria for Phase 1:** collections provision at startup; all indexes build; the seeded
catalogue matches the `Activity` sheet exactly. ✅ **Met** — see §7.

**Dependencies:** none.

---

## 3. Phase 2 — Backend

**Objective:** identical behaviour to the AppScript, exposed as REST, with the scheduled jobs
running.

### 3.1 New service layer

Put business logic in services, not routes — the routes stay thin, and the jobs and the API
then share one implementation.

| Service | Replaces | Responsibility |
|---|---|---|
| `tpms_schedule_service.py` | `saveSchedule`, `checkScheduleConflict`, `updateSchedule` | Once-per-month conflict rule (company vs HOD scope), delegates recurrence to the existing engine, writes tracker rows |
| `tpms_lifecycle_service.py` | `markLearnerDone`, `confirmCompletion`, reschedule fns | Two-step completion, reschedule request/decide, closes linked action items with the learner/staff delay split |
| `tpms_escalation_service.py` | `runEscalationLadder`, `syncAutoFeed` | The ladder + action-item/escalation feed — **see decision gate D1** |
| `tpms_score_service.py` | `syncSuccessMeasures`, `seedSuccessMeasures`, `reviewScoreMap_`, `manualScoresMap_` | The Success-Measure engine. **Highest-risk component** |
| `tpms_notify_service.py` | `sendScheduleEmails_`, `sendStatusEmails_`, `getTemplate_`, `waNotify_` | Resolves activity × side × event → template, then calls the **existing** notification service |
| `tpms_upload_service.py` | `uploadTaskFile`, `getTaskUploads` | Binds S3 uploads to an event + activity scope |

### 3.2 Endpoints

Mount under `/api/tpms`. Existing `/api/forms/*` stays exactly where it is.

**Schedules & lifecycle**
```
POST   /tpms/schedules                     create (recurrence, reminders, mails)
POST   /tpms/schedules/check-conflict      once-per-month pre-check
PATCH  /tpms/schedules/{id}                edit (auto-flags Rescheduled on date change)
DELETE /tpms/schedules/{id}
GET    /tpms/schedules?year&month&filters  calendar grid feed
POST   /tpms/schedules/{id}/learner-done
POST   /tpms/schedules/{id}/confirm
POST   /tpms/schedules/{id}/reschedule-request
GET    /tpms/reschedule-requests?status
POST   /tpms/reschedule-requests/{id}/decide
GET    /tpms/schedules/{id}/uploads
POST   /tpms/schedules/{id}/uploads
```

**Dashboards** — one per AppScript function; response shapes are already documented field-by-field in [TPMS_MODULE_ANALYSIS.md §4](TPMS_MODULE_ANALYSIS.md). Build the Pydantic response models straight from that table.
```
GET /tpms/dashboards/analytics            (Admin)
GET /tpms/dashboards/client-calendar      (Admin, tab 2)
GET /tpms/dashboards/staff                (OM/SMOps + admin grid)
GET /tpms/dashboards/learner              (Client)
GET /tpms/dashboards/hod
GET /tpms/dashboards/employee-activity
GET /tpms/dashboards/success             + GET/POST /tpms/manual-scores
GET /tpms/dashboards/escalations
GET /tpms/reports/logs?type=email|whatsapp   (server-side pagination + CSV stream)
GET /tpms/reports/reviews?source&month&company&hod
```

**Master data**
```
GET /tpms/activities        GET /tpms/departments        GET /tpms/reminder-rules
```

### 3.3 Background jobs

Add to the **existing** `reminder_scheduler` loop — do not introduce a second scheduler.

| Job | Cadence | Ports |
|---|---|---|
| `tpms_run_reminders` | every tick (60s) | `runReminders` (AppScript ran every 5 min) |
| `tpms_escalation_ladder` | daily ~07:00 | `runEscalationLadder` |
| `tpms_auto_feed` | daily ~06:00 | `syncAutoFeed` |
| `tpms_sync_success_measures` | daily + on-demand | `syncSuccessMeasures` — **make it an upsert**, removing the seed dependency (§9.x of the analysis) |

All must be **idempotent and keyed by event id**, exactly as the AppScript versions are, so a
re-run never double-writes. Guard each in try/except so a TPMS failure can't kill the loop
that existing modules depend on.

### 3.4 Permissions

Map AppScript roles onto ERP roles — no new role system:

| AppScript | ERP | TPMS rights |
|---|---|---|
| Admin | `superadmin`, `admin` | everything, all companies |
| Staff (SMOps) | internal non-admin | own companies only; approve reschedules, confirm completion |
| Learner | `clientadmin`, `clientuser` | own company only; schedule, mark done, request reschedule, fill forms |

Enforce server-side, mirroring `forms.py:_enforce_client_scope` (already written and correct):
- Staff may only write against companies they own (`Staff_ID(SMOps)` → company owner field)
- Client users are hard-scoped to `company_id` on **every** read and write
- Only staff/admin may `confirm`; only client users may `learner-done`

### 3.5 Validations to port exactly

Reschedule ≥12h before the event · reminder offset ≥1 · recurring requires `plan_end` ≥
`plan_start` · Periodically requires ≥1 weekday · ≥1 department, ≥1 doer, ≥1 staff assigner ·
rating 0–5 integer · upload ≤25 MB · cell-level immutability on form re-submit.

**Exit criteria:** every endpoint returns the shape in §4 of the analysis doc; a parity test
suite runs the ported scorer over migrated data and matches the sheet's computed columns.

**Dependencies:** Phase 1 complete. Escalation service blocked on **D1**.

---

## 4. Phase 3 — Frontend

**Objective:** every screen and interaction identical to TPMS; only the palette changes.

### 4.1 What already exists

The shell is **done**: routing, the three panels, the role gate, the sidebar entries, the
visual kit, the forms. The work is replacing mock data with real endpoints, plus building the
one genuinely missing screen (the Calendar).

| Screen | Current state | Work |
|---|---|---|
| Admin View | mock | wire `/dashboards/analytics` + add the **client-wise calendar tab** (2nd tab, currently absent) |
| OM/SMOps View, SmopsDashboard | mock | wire `/dashboards/staff` |
| Client View / ClientDashboard | partly real | wire `/dashboards/learner` |
| HodView, HodActivity | mock | wire `/dashboards/hod` |
| EmployeeTasks, SmopsEmployeeTask | mock | wire `/dashboards/employee-activity` |
| ImplementationTracker | mock | wire `/dashboards/success` + manual-score editing |
| Escalations | mock | wire `/dashboards/escalations` |
| LogsReport | mock | wire `/reports/logs` + server-side paging & CSV |
| ReviewReport | mock | wire `/reports/reviews` — cards + monthly-trend views |
| Rating forms (Acc/Own/Culture) | **working** | enable Culture once `FORM_DEFINITIONS` is fixed |
| Implementation Feedback | stub | enable once questions are added |
| **TPMS Calendar** | **missing** | **build** — month grid, filters, day drawer, schedule modal, lifecycle buttons, uploads, reschedule panel |

### 4.2 The Calendar page — the largest single item

Port of `Calender.html` (853 lines). Reuse `ScheduleCalendarModal`, `ActivityDetailView`,
`ReminderModal`. Build: month grid with status pills, the 6-tile stat band, 4 filters,
day-detail drawer, conflict-warning modal, reschedule-request modal, staff request-approval
panel with pending badge, per-event upload block, and the role-conditional lifecycle buttons.

### 4.3 Theming — the only intended change

One mapping table, applied centrally. AppScript purple → ERP indigo; status colours already
have ERP equivalents.

| TPMS | ERP token |
|---|---|
| `#7c3aed` / `#673ab7` (primary) | `--color-primary` `#6366f1` |
| `#15803d` / `#dcfce7` (completed) | `--accent-green` / `--accent-green-bg` |
| `#b45309` / `#fef3c7` (pending) | `--accent-orange` / `--accent-orange-bg` |
| `#b91c1c` / `#fee2e2` (overdue) | `--accent-red` / `--accent-red-bg` |
| `#1d4ed8` / `#dbeafe` (info) | `--accent-indigo` / `--accent-indigo-bg` |
| `#64748b` / `#f1f5f9` (lapsed) | existing muted tokens |

Rules: **no hex literals** in any TPMS component — tokens only, so dark mode works for free
(the AppScript UI was light-only; using tokens gets dark mode at no cost). Keep the existing
`HEADER_GRADIENT` in `dashboardKit.jsx`. All new tables go through `DataTable`; all KPI rows
through `KpiTile`; all panels through `Section`.

### 4.4 Frontend build order

1. `tpmsApi.js` — one client for all `/tpms/*` routes (mirrors `tpmsFormsApi.js` house style)
2. Calendar page (unblocks the whole lifecycle demo)
3. Dashboards in dependency order: Staff → Admin → Client → HOD → Employee
4. Implementation Tracker (needs the score engine live)
5. Escalations, Logs, Review Reports
6. Enable Culture + Implementation Feedback forms
7. Theme sweep + dark-mode pass + responsive check

**Exit criteria:** a side-by-side click-through of every AppScript screen vs the ERP screen
with a reviewer confirming behavioural parity.

**Dependencies:** each screen needs its Phase-2 endpoint. Calendar needs §3.2 schedules +
lifecycle.

---

## 5. Execution order

Phases overlap by design — the frontend for a feature starts as soon as its endpoint lands.

```
Week 1        Phase 1: schema + indexes + migration script (dry-run → verified load)
              ├─ parallel: fix FORM_DEFINITIONS (Culture) — zero-dependency quick win
              └─ parallel: rotate the leaked WhatsApp token
Week 2-3      Phase 2a: master data + schedule + lifecycle endpoints
              └─ Phase 3a starts: tpmsApi.js + Calendar page
Week 3-4      Phase 2b: Success-Measure engine + parity tests   ← highest risk
              └─ Phase 3b: Staff + Admin + Client dashboards
Week 4-5      Phase 2c: escalation + jobs (needs D1)  ·  Phase 3c: remaining dashboards
Week 5-6      Phase 3d: theme sweep, dark mode, parity walkthrough, UAT
```

**Critical path:** migration → schedule/lifecycle API → Calendar page → dashboards.
**Longest pole:** the Success-Measure engine — start its parity tests early.

---

## 6. Decision gates

These block specific steps. Everything else proceeds around them.

| # | Question | Blocks | Recommendation |
|---|---|---|---|
| **D1** | **Which escalation cadence is real?** Engine A auto-lapses at D+3; Engine B reports T+5/7/10; the UI documents a third | `tpms_escalation_service`, Escalations dashboard | Keep A's mail cadence; rebuild B's rows as a *projection* of A's stages so dashboard and inbox agree. Confirm D+3 auto-lapse is intended |
| **D2** | Implementation % stays **binary** (100/0) or becomes `completed ÷ total`? | score engine | Ask. Binary misreports "3-4 in month" activities |
| **D3** | Implementation Feedback: MD-only (AppScript) or all client users (ERP model)? | form definition | Ask — genuine business question |
| **D4** | Cell locks permanent, or editable until period close? | forms | Recommend a `locked_at` on the period |
| **D5** | Form deep links were `/dev` URLs — broken for clients. Confirm nobody depended on emailed links | notify service | In-app authenticated routes replace them |

---

## 7. Build log

### ✅ Phase 1 — Database (complete)

| Change | File |
|---|---|
| Culture fixed → HOD-rates-team, C1–C5, **live** | `app/models/forms.py` |
| Implementation Feedback → MD-only, 15 questions, **live** | `app/models/forms.py` |
| New `"md"` audience + generalised department gate | `app/models/forms.py`, `app/routes/forms.py` |
| TPMS domain layer: 10 collections, 9 models, tunables, 14-activity catalogue | `app/models/tpms.py` *(new)* |
| 9 TPMS lifecycle fields on calendar events | `app/models/calendar_event.py` |
| Startup provisioning: 15 indexes + master-data seed | `app/db/mongodb.py` |
| Duplicate period logic removed (single definition) | `app/routes/forms.py` |

**Verified against source, not assumed:** activity catalogue diffed against the `Activity`
sheet (14/14 rows, 0 mismatches) · `escLevel_` parity (5→HOD, 7→HR, 10→MD) · conflict-gate
parity (`once`→enforce, `3-4 in month`/`multiple times`→exempt) · every `app/` module imports.

⚠ **Name collision avoided:** `batch_id` was already the LMS Batch on calendar events. The
TPMS recurrence batch is `tpms_batch_id`; reusing the name would have corrupted LMS data.

### ✅ Phase 2 — Backend (complete)

| Change | File |
|---|---|
| Recurrence, conflict, create, tracker, write-scoping | `app/services/tpms_schedule_service.py` *(new)* |
| Two-step completion + reschedule workflow + delay split | `app/services/tpms_lifecycle_service.py` *(new)* |
| **Both** escalation engines (A: D+1/2/3 mails · B: T+5/7/10 rows) | `app/services/tpms_escalation_service.py` *(new)* |
| Success-Measure engine (seed + sync + manual + pooled form scores) | `app/services/tpms_score_service.py` *(new)* |
| Schedule update/delete with cascade + auto-Reschedule on date change | `app/services/tpms_schedule_service.py` |
| Task uploads → S3 (persistent key, signed URL per read) | `app/services/tpms_upload_service.py` *(new)* |
| All 9 dashboards + logs + review reports | `app/services/tpms_dashboard_service.py` *(new)* |
| Mail templates, placeholder fill, lifecycle notifications | `app/services/tpms_notify_service.py` *(new)* |
| **28 endpoints** | `app/routes/tpms.py` *(new)*, `main.py` |

**Endpoint map** — `/api/tpms/…`

```
activities · departments · reminder-rules                    master data
schedules (GET/POST) · check-conflict · {id} (PATCH/DELETE)  scheduling
{id}/learner-done · {id}/confirm                             two-step completion
{id}/reschedule-request · reschedule-requests · {id}/decide  reschedule workflow
{id}/uploads (GET/POST) · uploads                            proof of work → S3
success-measures · success-measures/sync · manual-scores     scoring
dashboards/analytics · staff · client · hod                  dashboards
dashboards/employee-activity · implementation · escalations
reports/logs · reports/reviews                               reports
```
| 3 daily sweeps added to the existing scheduler loop | `app/services/reminder_scheduler.py` |
| `tpms_status` field (TPMS's 5 statuses, mirrored into ERP `status`) | `app/models/calendar_event.py` |

**Reuse achieved:** TPMS reminders are written in the ERP's own `reminders[]` shape, so the
running `reminder_scheduler` fires them — **no second reminder cron**. The three daily sweeps
piggyback on that same loop, each individually try/except'd so a TPMS failure can never stop
the reminders that Tasks and the Calendar depend on.

**Bug found and fixed while porting.** `forms.py:_activity_score_pct` averaged each source
form's percentage separately; the Apps Script pools sum/count across all of an activity's
forms and divides once. On a realistic fixture (8 ratings at 5, 2 ratings at 1) that is
**84% vs 60% — a 24-point divergence**. `forms.py` now delegates to the pooled implementation,
so the module reports one number.

⚠ **Second name collision avoided:** the ERP calendar's `status` vocabulary is lowercase
(`schedule`/`completed`/`canceled`/`reschedule`) and has no "Lapsed". TPMS keeps its five
statuses in `tpms_status` and mirrors the closest value into `status`, so the existing
Calendar page and every other consumer keep working unchanged.

**Recurrence verified** against Apps Script semantics including the Monthly day-clamp
(31 Jan → 28 Feb → **31 Mar**), JS `getDay()` weekday indexing, and the quirks reproduced
verbatim (`Daily` yields nothing; `end < start` yields nothing).

Deliberate exception to the reuse principle: TPMS keeps its **own** recurrence generator.
`POST /calendar/events` uses different semantics (`repeat_interval`, no day-clamp) and its
route gate allows only admin/superadmin to create activity events, whereas TPMS permits Staff
and Learner. Storage, reminders and the calendar UI remain the shared ERP machinery.

**KPI parity verified** against code.js:1488-1492 — `statusBand` (≥95 STRONG / ≥85 GOOD /
≥70 WATCH / else AT-RISK), `pct`, `avgDelay` (1 dp, only delays > 0), `trend` vs the previous
**equal-length** window, and the overdue-vs-pending split on today's date.

### 🔄 Phase 3 — Frontend (in progress)

| Change | File |
|---|---|
| API client for all 28 TPMS routes | `src/services/tpmsApi.js` *(new)* |
| `HeaderSelect`/`FilterSelect` accept `{id,name}` as well as strings | `src/features/tpms/common/dashboardKit.jsx` |
| Escalations page → real API, server-side filtering | `src/features/tpms/admin/pages/Escalations.jsx` |
| Schedule modal gains a **TPMS mode** | `src/components/calendar/ScheduleCalendarModal.jsx` |
| **Calendar page** — month grid, day drawer, full lifecycle, uploads, requests | `src/features/tpms/calendar/TpmsCalendar.jsx` *(new)* |
| Calendar routed into all three panels + sidebar entries | `src/App.jsx`, `src/components/layout/Sidebar.jsx` |

**Theming turned out to be a non-issue.** The existing TPMS pages already style entirely
through CSS variables (`var(--accent-*)`, `var(--text-main)`, …) — there are no AppScript
purples to replace, and dark mode works for free. The colour-mapping table in §4.3 stands as
a reference for any new component, but no sweep is needed.

**Modal reuse instead of a second modal.** `ScheduleCalendarModal` had only `handleSave`
coupled to `/calendar/events`; the company/department/doer/staff pickers, reminder editor and
validation were all directly usable. It now takes `mode="tpms"`, which switches the save path
to `/tpms/schedules`, uses the TPMS recurrence set (adding Plan-end and a weekday picker for
*Periodically*), keeps doers and internal staff in **separate** fields — the ERP path merges
both into `assigned_member_ids`, but escalation must tell the doer from the SMOps owner — and
runs the once-per-month conflict check with a "Schedule Anyway" override. `mode` defaults to
`'erp'`, so existing behaviour is untouched. That reused ~460 lines rather than duplicating them.

**Verified:** production build passes; no new lint errors (the 3 reported across
`dashboardKit`, `ScheduleCalendarModal` are pre-existing — confirmed by linting the versions
in `git HEAD`).

**Calendar page** — the one screen with no ERP equivalent, and the module's core. Month grid
with status pills and a "+N more" overflow, a 6-tile stat band, activity/status filters, and a
day drawer carrying the whole lifecycle inline: doers get *Mark Done* and *Request Reschedule*,
staff get *Confirm Complete* and an approve/reject requests panel with a pending badge, admins
get delete. Upload-required activities render a proof panel that lists existing files and
accepts new ones. Reachable at `/tpms/admin/calendar` and `/tpms/smops/calendar` (the latter
serves internal SMOPS **and** client-side doers — the page gates each action by role).

**Next:** the remaining 11 dashboard pages — each is now a mechanical swap of mock arrays for
the matching `tpmsApi` call, following the Escalations pattern.

⚠ **Not yet exercised against a live database.** Everything is verified by logic tests and
import checks. The escalation and scoring engines need a smoke test on a dev database before
they are trusted — they write to `tpms_escalations`, `tpms_action_items` and
`tpms_success_measures` on a daily timer.

---

### On "exactly the same"

Replicating exactly also replicates three defects found in the source (analysis §5.1–5.3):
the contradictory escalation ladders, WhatsApp firing regardless of the Channel setting, and
`exact` reminders attaching only to the first occurrence of a recurrence. **My recommendation
is to fix all three and treat them as the only functional deviations**, listed here for
sign-off rather than silently carried forward. Everything else ports as-is.
