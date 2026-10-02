# TPMS — End-to-End Test Plan

How to exercise the TPMS module from a cold start through the full activity lifecycle.
Companion to [TPMS_MODULE_ANALYSIS.md](TPMS_MODULE_ANALYSIS.md) (what it does) and
[TPMS_ERP_IMPLEMENTATION_PLAN.md](TPMS_ERP_IMPLEMENTATION_PLAN.md) (how it was built).

Every step lists **what to do** and **what you should see**. Anything that doesn't match is a
defect — except the three items called out in §11 (Known, expected divergences), which are
ported behaviour and must not be filed as bugs.

Run the phases in order: later phases depend on data created by earlier ones.

---

## 0. Prerequisites

### 0.1 Bring the stack up

| Piece | Command | Expected |
|---|---|---|
| Backend | `cd backend && python main.py` | Uvicorn on `:8000`; `GET http://localhost:8000/` returns `{"status":"success"}` |
| Frontend | `cd frontend && npm run dev` | Vite dev server; API calls go to `/api` (override with `VITE_API_BASE_URL`) |
| Or both | `docker compose up --build` | Frontend on `:8082`, backend behind it |

Mongo and SMTP/S3 credentials come from `backend/.env`. Mail and upload steps (§5, §7) need
those to be real; everything else works without them.

### 0.2 Test accounts

You need **four** logins. The lifecycle cannot be tested with fewer — the two-step completion
requires a client user and an internal user acting on the same activity.

| # | Role | Purpose | Must have |
|---|---|---|---|
| A | `superadmin` or `admin` | Admin panel, delete, logs, score sync | — |
| B | internal staff (`staff` / `coach`) | SMOps: confirms completion, decides reschedules | owns the test company |
| C | `clientadmin` **or** `clientuser` | The doer: schedules, marks done, requests reschedule, uploads | `company_id` = test company, `department` ∈ HOD / MD / HR / IMPLEMENTOR |
| D | second client user, same company | Second doer, for the HOD-scope conflict test | same `company_id`, department HOD |

Note the test company's `_id` — several DB checks use it.

### 0.3 Confirm master data seeded itself

The TPMS collections and their indexes provision at startup (`app/db/mongodb.py`), and the
catalogue + default reminder rules are seeded insert-only.

```bash
curl -H "Authorization: Bearer <token-A>" http://localhost:8000/api/tpms/activities
curl -H "Authorization: Bearer <token-A>" http://localhost:8000/api/tpms/reminder-rules
curl -H "Authorization: Bearer <token-A>" http://localhost:8000/api/tpms/departments
```

**Expected:** 14 activities, 3 reminder rules, and departments `["HOD","MD","HR","IMPLEMENTOR"]`.
Spot-check three catalogue rows — the rest of the plan depends on their flags:

| Activity | frequency | scope | upload_required | score_mode |
|---|---|---|---|---|
| Monthly Management Review (MMR) | `once` | company | **yes** | manual |
| WRM | `3-4 in month` | hod | no | manual |
| Accountability & Ownership Rating | `once in a month` | hod | no | form |

**PASS:** 14/14 rows, no duplicates on a second backend restart (seeding is skipped once rows exist).

---

## 1. Access & routing

| # | Login | Go to | Expected |
|---|---|---|---|
| 1.1 | A (admin) | `/tpms` | Redirects to `/tpms/admin`; sidebar shows Admin View, Calendar, OM (SMOps) View, Client View, Implementation Tracker, Escalations, HOD View, Employee Tasks, Forms, Logs Report |
| 1.2 | B (internal staff) | `/tpms` | Redirects to `/tpms/smops`; **no** admin-only entries |
| 1.3 | B | `/tpms/admin` directly | Blocked by `RequireTpms admin` — not rendered |
| 1.4 | C (client) | `/tpms` | Redirects to `/tpms/smops`; sidebar shows Dashboard, Calendar, HOD Activity, Employee Task, Review Report, **Forms** |
| 1.5 | C | `/tpms/admin/logs` | Blocked |
| 1.6 | any | `/tpms/admin/calendar` (A) and `/tpms/smops/calendar` (B, C) | Same TPMS Calendar page renders for all three; the action buttons differ by role (§4) |

---

## 2. Schedule an activity (the entry point for everything else)

Do this as **C (client doer)** first, then repeat 2.6 as A.

| # | Step | Expected |
|---|---|---|
| 2.1 | Calendar → open the schedule modal | Modal opens in **TPMS mode**: Activity dropdown (14 items), Company, Departments, Company Assigners (doers), Staff Assigners, Plan start / Plan end, Recurrence, Reminders, Comment |
| 2.2 | Save with the Title empty | `400 Please fill: Title`. Repeat leaving Activity empty → `Please fill: Activity` |
| 2.3 | Save with no department | `Select at least one Department` |
| 2.4 | Save with no doer / no staff assigner | `Select at least one Company Assigner (doer)` / `Select at least one Staff Assigner` |
| 2.5 | Recurrence = *Periodically* with no weekday ticked | Rejected — Periodically requires ≥1 weekday |
| 2.6 | Fill everything: Activity **MMR**, one department, doer = C, staff assigner = B, one-time, today's date + a time, then Save | `200`; the event appears on the grid on that date with a **Scheduled** pill |

**Verify in the DB** (`calendar_events` or the company's calendar collection):

```js
db.calendar_events.findOne({ kind: "tpms_activity", activity: "Monthly Management Review (MMR)" })
// kind:"tpms_activity", tpms_status:"Scheduled", status:"schedule" (mirrored),
// company_id, assigned_departments[], assigned_member_ids[] (doers),
// coach_ids[] (staff assigners — kept separate on purpose), reminders[], activity_meta{}
db.tpms_activity_tracker.find({ event_id: "<id>" })   // one row per doer
```

**2.7 — Client scoping.** As C, try to schedule for a different company (edit the request body
directly if the UI hides it): the server forces `company_id` to C's own company. As B, schedule
for a company B does not own → `403 You can only schedule for your own companies.`

**2.8 — Recurrence expansion.** Schedule **WRM** with recurrence Monthly, plan start = the 31st
of a month, plan end = three months later.
**Expected:** one event per month sharing a `tpms_batch_id`, with the day clamped
(31 Jan → 28 Feb → **31 Mar**). Note: `Daily` intentionally yields nothing, and `plan_end < plan_start`
yields nothing — both are faithful ports, not bugs.

---

## 3. The once-per-month conflict rule

Advisory only: the modal warns, and **Schedule Anyway** always proceeds.

| # | Step | Expected |
|---|---|---|
| 3.1 | Schedule **MMR** (company scope, `once`) again for the same company, same month | Conflict warning naming the existing occurrence |
| 3.2 | Click **Schedule Anyway** | Saves; two occurrences now exist |
| 3.3 | Schedule **WRM** (`3-4 in month`) twice in one month | **No** warning — exempt frequency |
| 3.4 | Schedule **One pager Memo** (`multiple times`) twice | **No** warning — exempt |
| 3.5 | Schedule **Accountability & Ownership Rating** (HOD scope) for doer C, then again for doer **D** in the same month | Second one: **no** warning (different doer) |
| 3.6 | Repeat 3.5 but pick doer **C** again | Warning — HOD scope clashes only on the same doer |
| 3.7 | Cancel an occurrence, then re-schedule the same activity that month | No warning — cancelled occurrences never block |

---

## 4. Two-step completion — the core flow

This is the flow to demo. Statuses: **Scheduled → (learner_done) → Completed**.

| # | Who | Step | Expected |
|---|---|---|---|
| 4.1 | C | Calendar → click the day → open the drawer | Activity card with **✅ Mark Done** and **🔄 Request Reschedule** |
| 4.2 | B / A | Same activity in their drawer | **✔ Confirm Complete** instead; admin also sees delete |
| 4.3 | C | **Mark Done** | Toast "Marked done — staff will confirm". Status stays **Scheduled**; the card shows *"✅ Marked done by the doer — awaiting staff confirmation"* |
| 4.4 | — | DB | `learner_done:true`, `learner_done_by`, `learner_done_at`, `esc_stage:0` (ladder reset). `tpms_status` still `Scheduled` |
| 4.5 | B | Open the same activity → **Confirm Complete** | Status flips to **Completed** |
| 4.6 | — | DB | `tpms_status:"Completed"`, `status:"completed"`, `completed_at`, `completed_by`; `tpms_activity_tracker` rows → `Completed`; any open `tpms_action_items` → `Closed` with `delay_days` / `learner_delay_days` / `staff_delay_days` |
| 4.7 | C | Try **Mark Done** on the completed activity | `400 This activity is Completed.` — same for Cancelled and Lapsed |

**Negative checks (roles are enforced server-side, not just hidden in the UI):**

| # | Call | As | Expected |
|---|---|---|---|
| 4.8 | `POST /tpms/schedules/{id}/learner-done` | B or A (internal) | `403 Only the doer can mark an activity done.` |
| 4.9 | `POST /tpms/schedules/{id}/confirm` | C (client) | `403 Only internal staff can confirm completion.` |
| 4.10 | `POST /tpms/schedules/{id}/learner-done` | a client user of **another** company | `403 Not your company activity.` |

**4.11 — Delay split.** Schedule an activity dated 5 days ago (insert directly, or edit `start`
in Mongo), mark done as C, confirm as B **the next day**, then read the closed action item:
`learner_delay_days` = target → marked-done, `staff_delay_days` = marked-done → confirmed,
`delay_days` = the total. These three feed the dashboards' Learner Delay / Staff Delay columns.

---

## 5. Reschedule workflow

| # | Who | Step | Expected |
|---|---|---|---|
| 5.1 | C | On an activity starting **in under 12 hours** → Request Reschedule | `400 Reschedule requests must be raised at least 12 hours before the activity.` |
| 5.2 | C | On an activity 3+ days out → Request Reschedule, pick a new date + reason | `200`; row in `tpms_reschedule_requests` with `status:"Pending"` |
| 5.3 | C | Submit with no new date | `400 Choose a new date` |
| 5.4 | B | Calendar → requests panel | Pending badge with the count; the request lists old date, new date, reason, requester |
| 5.5 | C | Same panel | Sees only their own company's requests |
| 5.6 | B | **✔ Approve** | Event `start` moves to the new date/time; `tpms_status:"Rescheduled"`; `reschedule_count` +1; `esc_stage:0`; every entry in `reminders[]` back to `sent:false`; `tpms_activity_tracker.date` updated |
| 5.7 | B | Approve the **same** request again | `400 Request already Approved.` |
| 5.8 | C | Raise another request, B clicks **✕ Reject** with a note | Request → `Rejected` with `decided_by` + note; the **event does not move** |
| 5.9 | C | `POST /tpms/reschedule-requests/{id}/decide` | `403 Only internal staff can decide reschedule requests.` |
| 5.10 | A | Edit an activity's date via `PATCH /tpms/schedules/{id}` | Status auto-flips to **Rescheduled**, counter bumps, reminders re-arm — the same effect as an approval |

---

## 6. Proof-of-work uploads

Only activities the catalogue flags `upload_required` show the panel (MMR ✓, WRM ✗).

| # | Step | Expected |
|---|---|---|
| 6.1 | Open MMR in the drawer as C | Upload panel visible, listing existing files |
| 6.2 | Open WRM as C | **No** upload panel |
| 6.3 | Upload a small PDF | "Uploaded"; the file appears with uploader name + date |
| 6.4 | Reload the drawer | File still listed and downloadable — the S3 key is stored, a fresh signed URL is minted per read |
| 6.5 | Upload a file > 25 MB | Rejected (`UPLOAD_MAX_BYTES` = 25 MB) |
| 6.6 | `GET /tpms/uploads?company_id=<id>&period=YYYY-MM` | Returns the month's files — the Implementation Tracker's panel |

---

## 7. Reminders

TPMS writes reminders in the ERP's own `reminders[]` shape, so the **existing**
`reminder_scheduler` fires them — there is no second cron to watch.

| # | Step | Expected |
|---|---|---|
| 7.1 | Schedule an activity without touching Reminders | `reminders[]` pre-filled from `tpms_reminder_rules` (`activity:"*"` rules apply to all; a named rule to that one) |
| 7.2 | Add a custom reminder with offset `0` | Rejected — offset must be ≥1 |
| 7.3 | Set a reminder a few minutes out, wait for the 60s tick | Mail/WhatsApp sent; the entry flips to `sent:true`; a row lands in the notification log with `module:"tpms"` |
| 7.4 | Approve a reschedule for that activity (§5.6) | All entries back to `sent:false` — they fire again against the new date |

---

## 8. Daily sweeps: escalation ladder, auto-feed, scores

The three sweeps run **once per process-day** inside the reminder loop
(`reminder_scheduler.run_tpms_daily_jobs`). `last_recurring_day` starts as `None`, so
**restarting the backend re-runs all three immediately** — that is the practical way to test
them without waiting for midnight.

### 8.1 Escalation ladder (Engine A — the mails)

Simulate overdue by backdating an event that is **not** done:

```js
db.calendar_events.updateOne(
  { _id: ObjectId("<event id>") },
  { $set: { start: "<today minus N days>T09:00:00", esc_stage: 0,
            tpms_status: "Scheduled", status: "schedule", learner_done: false } }
)
```

Restart the backend after each change and check the log line `TPMS escalation ladder: …`.

| N days overdue | Expected |
|---|---|
| 1 | `[Pending Action]` mail to doers + HODs + HRs, cc SMOps; `esc_stage:1` |
| 2 | `[CRITICAL]` mail to MDs (falls back to HODs + HRs when no MD exists); `esc_stage:2` |
| 3 | `[LAPSED]` mail to everyone; `tpms_status:"Lapsed"`; `esc_stage:3` |

**8.1.1 — Idempotence.** Restart again without changing anything: **no** duplicate mails, stage
unchanged. The ladder is keyed by `esc_stage`.

**8.1.2 — Mark Done stops the ladder.** Backdate another event by 1 day, have C **Mark Done**,
then restart. `esc_stage` stays 0 and no escalation mail is sent — waiting on staff is not overdue.

### 8.2 Auto-feed (Engine B — the dashboard rows)

Same restart triggers `sync_auto_feed`. Expect rows in `tpms_action_items` and
`tpms_escalations` keyed by `event_id`, with levels **T+5 → HOD, T+7 → HR, T+10 → MD**.
Confirm re-running does not duplicate (`{event_id:1}` is unique on both collections).

### 8.3 Success measures

On-demand instead of waiting — admin only:

```bash
curl -X POST -H "Authorization: Bearer <token-A>" \
  "http://localhost:8000/api/tpms/success-measures/sync?period=YYYY-MM"
curl -H "Authorization: Bearer <token-A>" \
  "http://localhost:8000/api/tpms/success-measures?period=YYYY-MM&company_id=<id>"
```

| # | Check | Expected |
|---|---|---|
| 8.3.1 | Rows per activity | `impl_target`, `impl_actual`, `score_target`, `score_actual`, `achievement`, `scope` |
| 8.3.2 | Run the sync twice | Upserts — no duplicates (unique on company + activity + period + scope + hod_id) |
| 8.3.3 | `POST /tpms/manual-scores` as B | Saved; the next sync picks it up. HOD-scoped entries are averaged across HODs |
| 8.3.4 | Same call as C (client) | `403 Only internal staff can enter scores.` |
| 8.3.5 | Sync as C | `403 Admin only` |

---

## 9. Forms → score feed

| # | Who | Step | Expected |
|---|---|---|---|
| 9.1 | C | `/tpms/forms/accountability` — submit a rating matrix | Saved; re-opening shows the submitted cells **locked** |
| 9.2 | C | Re-submit a locked cell | Rejected — cell-level immutability |
| 9.3 | C | Enter a rating of 6 or −1 | Rejected — integers 0–5 only |
| 9.4 | C (HOD) | `/tpms/forms/culture` | Renders (HOD-rates-team, C1–C5) |
| 9.5 | MD-only user | `/tpms/forms/implementation-feedback` | Renders for MD; other client users are gated out |
| 9.6 | A | Re-run the score sync (§8.3), then read the measures | Form-scored activities (A&O Rating, Culture, Implementation Feedback) show a `score_actual` derived from the submissions, **pooled** sum ÷ count across all of an activity's forms — not an average of per-form percentages |
| 9.7 | A | `/tpms/admin/reviews` or `GET /tpms/reports/reviews?source=accountability&period=YYYY-MM` | The submissions appear per respondent, plus the monthly trend |

---

## 10. Dashboards, reports and scoping

Each page is a straight read of its endpoint. For every one: load as A, B and C and confirm the
**scope** narrows correctly — SMOps see only companies they own, clients only their own company.

| Page | Endpoint | Key check |
|---|---|---|
| Admin View | `/tpms/dashboards/analytics` | 14 KPI cards, client matrix, OM league table, top-delayed clients |
| OM (SMOps) View | `/tpms/dashboards/staff` | Only B's own clients |
| Client View / Client Dashboard | `/tpms/dashboards/client` | C sees only their company; the scorecard matches §8.3 |
| HOD View | `/tpms/dashboards/hod?member_id=` | One HOD's scorecard, tracker, alerts, follow-ups |
| Employee Tasks | `/tpms/dashboards/employee-activity` | Per-employee completion + per-activity breakdown |
| Implementation Tracker | `/tpms/dashboards/implementation` | Scorecard + proof uploads + client × activity matrix |
| Escalations | `/tpms/dashboards/escalations` | Active + resolved, with L1/L2/L3 counts from §8.2 |
| Logs Report | `/tpms/reports/logs?channel=email` | Server-side paging, KPI counts, sparkline; **`403 Admin only` for B and C** |

**KPI sanity check** — with the activities created above, the band should follow
≥95 STRONG / ≥85 GOOD / ≥70 WATCH / else AT-RISK; average delay is 1 dp and counts only
delays > 0; the trend compares against the previous **equal-length** window; and today's date
splits overdue from pending.

---

## 11. Known, expected divergences — do **not** file these

1. **Two escalation ladders disagree by design.** The mails you receive follow D+1 / D+2 / D+3
   (§8.1); the levels the Escalations dashboard shows follow T+5 / T+7 / T+10 (§8.2). Both are
   ported from the source, which runs both. Decision gate **D1** in the implementation plan.
2. **WhatsApp fires regardless of the rule's Channel setting** — a defect faithfully carried
   over from the Apps Script.
3. **`exact`-type reminders attach only to the first occurrence** of a recurrence — likewise.

A third ladder (T−2/T/T+2/T+4…) appears in the source UI as "system logic" but was never
implemented there, and is not implemented here.

---

## 12. Regression — the rest of the ERP must be untouched

TPMS shares `calendar_events`, the reminder loop and the schedule modal with existing modules.
After the above, confirm nothing bled across:

| # | Check | Expected |
|---|---|---|
| 12.1 | Main Calendar page (`/calendar`) | TPMS activities do **not** appear as sessions/tasks; stats unchanged |
| 12.2 | Create a normal session and a normal task from `/calendar` | The schedule modal in default `mode="erp"` still posts to `/calendar/events` |
| 12.3 | Task & Delegation module | Task list, recurrence and reminders unaffected |
| 12.4 | Personal Todo + its Frequency control | Saving a repeating todo generates its whole series at once, up to the (required) Repeat End Date — same dates a task would get, via `recurring_task_service.build_series_occurrences` |
| 12.5 | Backend log during all of the above | No `TPMS … failed` line ever stops the reminder loop; each sweep is individually try/except'd |
| 12.6 | LMS batches | `batch_id` on calendar events still means the LMS batch; TPMS uses `tpms_batch_id` |

---

## 13. Result sheet

| Phase | Scope | Result | Notes |
|---|---|---|---|
| 0 | Startup + seed (14 activities) | ☐ | |
| 1 | Access & routing per role | ☐ | |
| 2 | Schedule + validation + recurrence | ☐ | |
| 3 | Once-per-month conflict rule | ☐ | |
| 4 | Two-step completion + delay split | ☐ | |
| 5 | Reschedule request → decide | ☐ | |
| 6 | Uploads | ☐ | |
| 7 | Reminders | ☐ | |
| 8 | Daily sweeps (ladder / feed / scores) | ☐ | |
| 9 | Forms → score feed | ☐ | |
| 10 | Dashboards + reports + scoping | ☐ | |
| 12 | Regression on existing modules | ☐ | |

> ⚠ Per the implementation plan, the **escalation and scoring engines have not yet been
> exercised against a live database** — they are verified only by logic tests and import checks.
> Phases 8 and 9 are therefore the highest-risk part of this plan and should be run first on a
> dev database, before any UAT.
