# TPMS — AppScript → ERP (MongoDB) Migration Analysis

Reverse-engineered from the 5 AppScript projects and `Copy of Calender_with_dashboard (1).xlsx`
(48 tabs, spreadsheet ID `1HiRCcWd8vLLMAb8cJ1pQ3WKbXR-TUNsuxfIt3h6fXrg`).

---

## 1. What TPMS actually is

**Team Productivity Monitoring System** — Sparsh's consulting-delivery tracker. Sparsh
assigns an **OM/SMOps** owner to each client company. Every month that client must complete a
fixed catalogue of **14 activities** (WRM, MMR, ORM, DRM & KPI, Culture Rating …). TPMS
schedules those activities on a calendar, chases them with email/WhatsApp reminders,
escalates when they slip, collects proof-of-work uploads, runs the rating forms, and rolls
everything up into 5 dashboards.

It is **one system split across 5 separate AppScript deployments** that all read/write the
**same spreadsheet**:

| Project | Role | `code.js` |
|---|---|---|
| `copy_of calender/` | Main SPA — login, calendar, all dashboards | **4,207 lines** ✅ |
| `HOD_Accountability/` | Standalone rating form (deep-linked) | 545 lines |
| `HOD_Owernership/` | Same, different constants | 546 lines (identical logic) |
| `HOD_Culture/` | Same again | 546 lines ✅ |
| `Implementation_Update_Feedback/` | Yes/No checklist for the MD | 387 lines |

**All five projects are now supplied.** `HOD_Culture/code.js` is byte-identical to
`HOD_Accountability/code.js` apart from 4 constants (sheet names, `FORM_TYPE`, 2 template
columns) and the page `<h1>`. The three rating forms are one codebase cloned three times —
in the ERP they are a single parameterised implementation, which is already how
`app/routes/forms.py` models them.

---

## 0. ⚠ Do this before anything else

**A live WhatsApp Cloud API access token is hardcoded at `copy_of calender/code.js:77`**, along
with the phone-number ID and business-account ID. This file is sitting in a working directory
and will land in git the moment the folder is added. **Rotate the token in Meta Business
Manager now**, and never port it into the ERP as a literal — it belongs in the environment
alongside the other secrets in `app/config/settings.py`.

Two other credential issues carry over from the sheet:
- Passwords are compared in plaintext (`code.js:115`, `:135`) against `Staff_Password` /
  `Employee_Password` columns. All are `a1234`. Must be hashed on migration.
- Sessions are a UUID in `CacheService` with a 6-hour TTL (`CFG.SESSION_TTL`). Apps Script
  cache is **evictable**, so users get logged out unpredictably. Use real JWTs in the ERP.

---

## 2. Roles & identity

Two separate people-tables, two login populations:

| Sheet | Who | Role field | Values |
|---|---|---|---|
| `Staff` (10 rows) | Sparsh internal | `Staff_Role` | `Admin`, `SMOps` |
| `Company_Employees` (17 rows) | Client-side | `Role` / `Designation` | `MD`, `HOD`, `IMPLEMENTOR`, `HR` |

The SPA collapses these into **3 UI roles** (`index.html` `data-roles`):

- **Admin** — sees everything: 7 dashboards + calendar + HOD view + employee tasks + reviews
- **Staff** (SMOps) — own clients only; approves reschedules, confirms completions
- **Learner** (client-side employee) — own company only; marks tasks done, requests reschedules

Org graph lives in `Company_Employees`: `HOD_IDs` (comma-separated — an employee can report
to several HODs), `MD_ID`, `HR_IDs`. This is what drives "who is on my team" in the rating
forms and "who do I escalate to".

**Passwords are plaintext (`a1234`) in the sheet.** Must become hashed on migration.

---

## 3. The activity catalogue — the spine of the system

`Activity` sheet, 14 rows. Three columns drive all behaviour:

| Column | Effect |
|---|---|
| `Responsive` = `Company vise` \| `HOD wise` | **Scope.** Decides the once-per-month duplicate check and whether uploads/scores are per-company or per-HOD |
| `Upload Required` = `Yes` | Renders the file-upload block on the calendar event; feeds `Task_Uploads` |
| `Frequency` | `once in a month`, `3-4 in month`, `multiple times` — governs the conflict warning |
| `Success_Measure_actual%` = `Manual` | Score is typed in by staff, not computed. 10 of 14 are Manual |

Three activities are **auto-scored from TPMS forms** (already encoded in `app/models/forms.py:148`):

```
Accountability & Ownership Rating → accountability + ownership forms
Culture Rating                    → culture form
Implementation Update Feedback    → implementation_feedback form
```

---

## 4. Main calendar app — reconstructed API surface

30 `google.script.run` calls across the 12 HTML pages:

**Auth/shell** — `authenticateUser(user,pass)` → `{success, token, userData:{role,username,email,companyId}}` ·
`validateSession(token)` · `invalidateSession(token)` · `getPageContent(page)` (server-side
HTML include — **drops entirely** in React) · `getProfile` · `changePassword`

**Calendar** — `getInitialData(token)` → `{activities[], companies[{id,name,smName}], departments[], staff[]}` ·
`getEvents(token, year, month)` · `getDoers(token, companyId, depts[])` ·
`checkScheduleConflict(token, payload)` · `saveSchedule` · `updateSchedule` · `deleteSchedule`

**Lifecycle** — `markLearnerDone` · `confirmCompletion` · `requestReschedule(token,id,newDate,newTime,reason)` ·
`getRescheduleRequests(token,'Pending')` · `decideRescheduleRequest(token,id,approve,note)`

**Uploads** — `uploadTaskFile(token, scheduleId, {name,mimeType,data:base64})` · `getTaskUploads(token, scheduleId)`

**Dashboards** — `getAnalytics` · `getStaffDashboard` · `getLearnerDashboard` · `getClientCalendarData` ·
`getHodDashboard` · `getEmployeeActivityDashboard(token,scope)` · `getSuccessDashboard(token,scope)` ·
`getManualScores(token,cid,month)` · `saveManualScore(token,payload)` · `getEscalationDashboard` ·
`getLogsReport` · `getReviewReports`

### Page → server-function map (8 dashboards, 12 HTML files)

| Page | Calls | Returns (from render code) |
|---|---|---|
| `AdminDashboard` (435 L, **2 tabs**) | `getAnalytics(token,{month,smopsId,companyId})` | `{selectedMonth, filters:{months,smops,companies}, cards{14 KPIs}, clients[], oms[], topDelayed[]}` |
| ” tab 2 — client-wise calendar | `getClientCalendarData(token,{month,companyId,hodId,smopsId,side})` | `{filters, isAdmin, planned, completed, pending, delayed, lapsed, events[]}` |
| ” OM activity grid | `getStaffDashboard(token,{…,side,actionSide})` | `{cards, activities[{short,full}], clientsGrid[{company,cells{},done,pct}], openActions[]}` |
| `StaffDashboard` (189 L) | `getStaffDashboard(token,{month,smopsId})` | `+ {smopsName, isAdmin, smopsOptions[], monthOptions[], alerts[]}` |
| `LearnerDashboard` (202 L) | `getLearnerDashboard(token,{companyId,month})` | `{company, om, completion, status, opCards, cards{met,partial,notMet,avgScore,target}, rows[], pendingActions[], activities[], clientsGrid[]}` |
| `HodView` (218 L) | `getHodDashboard(token,{from,to,employeeId})` | `{hod{}, canPick, hodOptions[], cards, scoreRows[], tracker[], alerts[], openActions[]}` |
| `EmployeeActivity` (159 L) | `getEmployeeActivityDashboard(token,{companyId,month,employeeId,designation,side})` | `{cards, rows[{name,designation,department,total,completed,missed,pending,score,activities[]}], *Options[]}` |
| `SucessDashboard` (287 L) | `getSuccessDashboard` · `getManualScores` · `saveManualScore` | `{cards, scorecard, uploads[], matrixActivities[], clients[]}` |
| `EscalationDashboard` (145 L) | `getEscalationDashboard(token,{smopsId,companyId})` | `{filters, cards{activeCount,avgOverdue,resolvedMonth,avgResolution,l1,l2,l3}, active[], resolved[]}` |
| `ReportDashboard` (252 L) | `getLogsReport(token, 'email'\|'whatsapp', {status,side,from,to})` | `{type, columns[], rows[][], counts{total,sent,failed,skipped}, spark[], truncated}` — **client-side CSV export, capped at latest 3000** |
| `ReviewReport` (382 L) | `getReviewReports(token, sourceId, {month,companyId,hodId})` | `{sources[], source{id,label,status{high,mid,low}}, isYesNo, totals, hods[], trend{months[],employees[]}, monthOptions[], hodOptions[], canPickHod}` |
| `Profile` (85 L) | `getProfile(token)` → `{fields:[[label,value]]}` · `changePassword(token,old,new)` | min 6 chars, client-validated only |

`Calender.html` (853 L) is by far the largest and holds 16 of the 30 calls.
`stylesheet.html` (187 L) is pure CSS — the design tokens the whole SPA shares.

### Scoring formula (recovered from `ReviewReport.html:198-220`)

The rating→percentage conversion the dashboards use, **not** documented anywhere else:

```
row  Score% = Σ(ratings) ÷ (answered_criteria × 5) × 100     // unanswered cells excluded
grand Score% = Σ(all ratings) ÷ Σ(all answered × 5) × 100
yes/no Score% = yes_count ÷ total_answered × 100
```

Status bands (`rrStatus`, per-form labels come from the backend `source.status`):
**≥85 Strong · 70–84 Moderate · <70 Needs Focus.**
Cell tint bands differ from status bands: ≥80 green / ≥50 amber / <50 red.

Elsewhere the KPI targets are **90% completion** and **95% action closure**
(`AdminDashboard.html:192-194`), and client health badges are `STRONG / GOOD / WATCH / AT-RISK`
with tint thresholds ≥90 / ≥80 / below.

### Schedule payload (`Calender.html:649`)

```js
{ title, eventTime, activity, companyId, companyName,
  planStart, planEnd,                    // planEnd only for recurring
  departments: [],                       // HOD | MD | HR | IMPLEMENTOR
  companyAssigners: [],                  // "doers" — client-side names
  staffAssigners: [],                    // SMOps owners
  recurrence: 'One-time'|'Daily'|'Weekly'|'Monthly'|'Periodically',
  weekdays: [0..6],                      // Periodically only
  status, comment,
  reminders: [ {channel:'Email'|'WhatsApp'|'Both', type:'offset', dir:'before'|'after',
                value:N, unit:'MINS'|'HRS'|'DAYS'}
             | {channel, type:'exact', date, time} ] }
```

Recurring saves **expand server-side into N rows** sharing one `Batch_ID`
(response is `{count, reminders, scheduleMails}`), each with its own `Schedule_ID`
(`SCH-<epoch>-<n>`).

---

## 5. End-to-end lifecycle

```
 SCHEDULE          Staff/Admin/Learner opens Schedule modal
                   → checkScheduleConflict: if activity is "once in a month" and this
                     company (Company vise) or this doer (HOD wise) already has it
                     this month → warn, allow "Schedule Anyway" override
                   → saveSchedule: expand recurrence → N Calendar_Schedule rows
                   → materialise Reminders rows (defaults from Activity_Reminder_Rules
                     + per-schedule custom ones)
                   → send "scheduled" mail to Staff side + Company side
                     (Templates sheet, per-activity, per-side)
                   → WhatsApp via Meta Cloud API (Whatsapp_templates + WhatsappVariables)

 REMIND            Time-driven trigger scans Reminders where Remind_At <= now
                   and Status = Pending → send → Status = Sent, stamp Sent_At
                   Defaults (Activity_Reminder_Rules): Day-2 Email, Day-1 Email,
                   2h-before Both

 RESCHEDULE        Learner: requestReschedule (must be ≥12h before event)
                     → Reschedule_Requests row, Status = Pending
                   Staff: decideRescheduleRequest
                     → approve: move Event_Date/Time, Status = Rescheduled,
                       Reschedule_Count++, regenerate reminders, notify both sides
                     → reject: Status = Rejected + note
                   Staff editing date/time directly also auto-flips → Rescheduled

 DO               If Upload Required → uploadTaskFile → Drive → Task_Uploads row
                   Learner: markLearnerDone → Learner_Done = Yes (+By/+At)
                   Staff:   confirmCompletion → Status = Completed, Completed_At/by
                   ⇒ two-step completion. Doer claims, staff verifies.
                   Also writes Activity_Tracker (per employee × month × activity)

 ESCALATE          Overdue sweep → Escalations row, 7-stage ladder (§5.1)
                   Status Active → Resolved; also creates Action_Items
                   (Follow up: <Activity>, Owner, Target_Date, Delay_Days)
                   Past-due & never done ⇒ Status = Lapsed

 SCORE             Success_Measures row per (Company, Activity, Month):
                     Activity_Implementation_Target_% / Actual_Implementation_%
                     Activity_Score_Target_%         / Actual_Activity_Score_%
                     Achievement_%
                   Implementation % = completed ÷ scheduled (auto)
                   Score % = Manual for 10 activities (saveManualScore, → Success_Manual,
                             company-scope or per-HOD scope)
                           = derived from form submissions for the other 3
```

---

### 5.1 Escalation — ⚠ THREE conflicting ladders, two of them live

This is the single most important finding in the codebase. **Two independent escalation
engines run on separate daily triggers, on completely different timelines, and a third
timeline is shown to users in the UI.** All three disagree.

**Engine A — `runEscalationLadder()` (`code.js:3755`, daily 07:00)** — the one that actually
emails people. Calendar days, weekends counted. Tracks progress in the `Esc_Stage` column:

| Δ | Stage | Recipients | Effect |
|---|---|---|---|
| D+1 | `[Pending Action]` mail | owners + HODs + HRs, cc SMOps | `Esc_Stage = 1`, WhatsApp to doers |
| D+2 | `[CRITICAL]` mail | MDs (fallback HOD+HR), cc SMOps + owners | `Esc_Stage = 2` |
| D+3 | `[LAPSED]` mail | owners + HODs + HRs + MDs, cc SMOps | **`Status = Lapsed`**, tracker updated |

Skips rows where `Learner_Done = Yes` (waiting on staff ≠ overdue), and `markLearnerDone`
resets `Esc_Stage` to 0.

**Engine B — `syncAutoFeed()` (`code.js:2714`, daily 06:00, *also* called inline by
`getAnalytics`)** — writes rows but **sends no email at all**:

- overdue ≥ **1 day** → open `Action_Items` row (`Follow up: <Activity>`)
- overdue ≥ **5 days** → `Escalations` row, level via `escLevel_()`: **≥5 HOD · ≥7 HR · ≥10 MD**
- activity Completed/Cancelled → auto-close the action + resolve the escalation

Idempotent, keyed by `Schedule_ID`; only touches rows carrying one, so manual rows are safe.
On close it computes the delay split: `Learner_Delay_Days` (target → learner-done) and
`Staff_Delay_Days` (learner-done → staff-confirm).

**Engine C — `ES_TIMELINE` (`EscalationDashboard.html:52`)** — a hardcoded display constant
under the heading "ESCALATION REMINDER TIMELINE (SYSTEM LOGIC)", showing a 7-stage
T−2 / T / T+2 / T+4 / T+5 / T+7 / T+10 ladder with subject-line formats. **Nothing implements
it.** The subject formats it advertises don't match the ones Engine A actually sends.

**The consequence:** an activity is force-marked `Lapsed` on **day 3** by Engine A, but the
`Escalations` table Engine B feeds doesn't open a row until **day 5** — and its level labels
(HOD/HR/MD at 5/7/10) describe a progression that never fires as mail. So the Escalation
Dashboard shows one story, users receive a different one, and the documented spec is a third.

**This must be resolved with the client before porting.** Do not port all three. My reading is
that Engine A is the working implementation (it sends mail, sets Lapsed, is referenced by the
lifecycle module header comment `D+1 → D+2 → D+3 Lapsed`) and Engines B/C are an older or
aspirational design that was never retired. Confirm which cadence the business actually wants —
a 3-day auto-lapse is aggressive and may be an accident.

Separately, `Activity_Reminder_Rules` (Day−2 Email, Day−1 Email, 2h-before Both) supplies
*pre-event* reminders via `autoRemindersFromRules_()` and is applied to every schedule on
save. That part is coherent and does not conflict.

---

### 5.2 Success-Measure engine (`code.js:2054`)

Two functions, and the split matters: **`seedSuccessMeasures()` creates rows;
`syncSuccessMeasures()` only ever updates them.** Sync explicitly skips any aggregate with no
pre-seeded row (`code.js:2154`) — so if the seed hasn't run for a month, that month silently
scores nothing. Reproduce this as an upsert in Mongo and the whole class of bug disappears.

Per `(company × activity × month)`:

```
Actual_Implementation_%  = completed > 0 ? 100 : 0      // BINARY, not a ratio
autoScore                = completed ÷ total × 100
Achievement_%            = Actual_Score ÷ Score_Target × 100   (targets default to 100%)
```

`Actual_Score_%` resolves by activity class, in priority order:
1. **Review-backed** (`REVIEW_SCORE_ACTIVITIES`, `code.js:2004`) → from the form response
   sheets. Ratings: `Σratings ÷ (count × 5) × 100`, **averaged company-wide, not per employee**.
   Yes/No: `yes ÷ total × 100`. Accountability & Ownership are averaged *together* into one
   activity score.
2. **Manual** (`Success_Measure_actual% = "Manual"`, 10 of 14 activities) → typed into
   `Success_Manual`. Company-scope reads one row; HOD-scope **averages across all HODs** who
   have a value.
3. Otherwise → `autoScore`.

**`Calendar Discipline` is a pseudo-activity** (`code.js:2093`): it has no schedules of its
own. Its score is the completion rate across *all other* activities that month, excluding
itself and `Action Closure Review`. Worth calling out — it looks like a normal catalogue row
but is entirely derived.

Month keys are normalised by `succMonthNorm_()`, which absorbs `Date`, `jul26`, `July26`, and
`2026-07-14` into a canonical `jul26`, with `succMonthDisplay_()` rendering `July26`. That
explains the format drift noted in §9.2 — it's papered over by a normaliser rather than fixed.

### 5.3 Other mechanics worth porting deliberately

- **Recurrence** (`buildOccurrences_`, `code.js:1304`) — `One-time`, `Monthly` (day-of-month
  clamped to short months), `Weekly` (+7d), `Periodically` (weekday mask). The UI filter offers
  a `Daily` option that the generator does not implement.
- **Reminder cron** — `runReminders()` every **5 minutes**; offsets computed from `eventTime`
  or `CFG.DEFAULT_REMIND_TIME = '09:00'`. Note: **`exact`-type reminders attach only to the
  first occurrence** of a recurring batch (`code.js:1210`), while offset reminders attach to
  every one. Almost certainly unintended.
- **WhatsApp ignores the Channel setting** — `sendReminderForRow_` fires `waNotify_()` before
  checking `doEmail` (`code.js:1268`, comment: *"WhatsApp auto-fires regardless"*). Choosing
  "Email" still attempts WhatsApp; it's suppressed only by a missing template.
- **Form deep links** (`HOD_FORMS`, `code.js:60`) — all four URLs point at `/dev` deployments,
  not `/exec`. Dev URLs require the caller to have edit access to the script, so **these links
  are broken for real client recipients**. `MID` is derived from the event date via
  `midFromDate_()`.
- **Role scoping on write** — Staff may only schedule for companies where they are the
  `Staff_ID(SMOps)`; Learners only for their own `companyId` (`code.js:809-818`).

---

## 6. The rating/checklist forms (separate deployments)

These are **not** inside the SPA. They are standalone web apps opened by deep link:

```
?CID=PTOP001&EID=EMP_223&MID=jul26
   ^company     ^HOD/MD      ^month token
```

No login — **the URL is the credential.** The link is emailed/WhatsApped from the calendar
when the "Accountability & Ownership Rating" / "Culture Rating" / "Implementation Update
Feedback" activity fires.

### Rating matrix (Accountability / Ownership / Culture)

- `getFormData(cid,eid,mid)` → HOD + their team (everyone whose `HOD_IDs` contains `eid`) + questions
- Renders a grid: **rows = team members, columns = 0–5 radio buttons, one table per criterion**
- **Cell-level partial submission** — the distinctive behaviour. Every already-saved
  (question × employee) cell renders `checked` + `disabled`; you can come back and fill
  only the blanks. `submitResponses` re-reads existing rows and appends *only* new cells
  (`code.js:236`). Re-submitting the same cell is rejected, not overwritten.
- One sheet row per rating: `Timestamp, Month, Company_ID, HOD_ID, HOD_Name, Question_ID,
  Question, Employee_ID, Employee_Name, Rating`
- On submit → 2 mail streams: **HOD summary** to Admin + the company's SMOps (grouped by
  question), and a **per-employee scorecard** with their own average

### Yes/No checklist (Implementation Update Feedback)

Same skeleton, respondent is the **MD** not an HOD, no team dimension. Per-question
`Answer` (Yes/No) + `Remark`. Same partial-submission rule, keyed by question only.
Single mail stream (Admin + SMOps).

### Matching by ID *and* by text

Both forms key existing answers by `Question_ID` **and** by question text
(`ratingsByText` / `answersByText`). This is a defence against the questions sheet being
re-ordered — the `Question_ID` is derived from the `SR` column, which shifts. **In Mongo,
use a stable `criterion_code` (`A1`,`O2`,`C3`) and drop the text fallback.**

---

## 7. Sheets → MongoDB collections

| Sheet | Rows | → Collection | Notes |
|---|---|---|---|
| `Companies` | 1 | `companies` | **exists** |
| `Staff` | 10 | `users` (staff) | role Admin/SMOps |
| `Company_Employees` | 17 | `users` (client) | `hod_ids[]`, `md_id`, `hr_ids[]` |
| `Department` | 4 | enum / `departments` | HOD, MD, HR, IMPLEMENTOR |
| `Activity` | 14 | `tpms_activities` | scope, upload_required, frequency, scoring mode |
| `Calendar_Schedule` | 512 | `tpms_schedules` | ⚠ merge decision — see §9 |
| `Reminders` | 294 | `tpms_reminders` | index `{status, remind_at}` for the cron |
| `Activity_Reminder_Rules` | 3 | `tpms_reminder_rules` | defaults applied at schedule time |
| `Reschedule_Requests` | 0 | `tpms_reschedule_requests` | |
| `Task_Uploads` | 0 | `tpms_task_uploads` | Drive → **S3** (`app/services/s3_service.py` exists) |
| `Activity_Tracker` | 422 | `tpms_activity_tracker` | per employee × month × activity — could be a view |
| `Escalations` | 82 | `tpms_escalations` | |
| `Action_Items` | 127 | `tpms_action_items` | |
| `Success_Measures` | 942 | `tpms_success_measures` | one per company×activity×month |
| `Success_Manual` | 0 | fold into `tpms_success_measures` | scope: company \| hod |
| `HOD_*_Question`, `Implementation_update_feedback_` | 3–15 | **`FORM_DEFINITIONS`** | already in code, not DB |
| `HOD_*_Responses` (3) | 150–260 | `tpms_accountability` / `_ownership` / `_culture` | **exist** |
| `Sheet36` | 0 | `tpms_implementation_feedback` | **exists** (feedback responses) |
| `Templates` (11 cols × activity) | 14 | `tpms_mail_templates` | activity × side × event |
| `HOD_Form_mail_templates` (6 cols) | 1 | `tpms_mail_templates` | form × side |
| `Whatsapp_templates` + `WhatsappVariables` | 1 / 140 | `tpms_wa_templates` | Meta template + positional var map |
| `Scheduled_logs`, `Whatsapp_logs`, `HOD_Form_mail_logs` | 763/195/0 | `tpms_notification_logs` | one collection + `channel` field |
| `Pivot Table 1`, `*_master` (12), `Founder/OM/Client/… Dashboard`, `Mail Reminder` | — | **skip** | empty stubs, spec mock-ups, or Excel pivots |

---

## 8. What already exists in the ERP

**Do not rebuild these.**

| Piece | Location | State |
|---|---|---|
| Form definitions + registry | `backend/app/models/forms.py` | ⚠ Accountability + Ownership live; Culture & Implementation Feedback empty **and Culture's `audience`/`self_rating` are factually wrong — see §9.5** |
| Form submission API | `backend/app/routes/forms.py` (720 L) | ✅ ratings, feedback, submissions, members, client dashboard |
| Per-form collections + indexes | `backend/app/db/mongodb.py:_ensure_form_collections` | ✅ auto-provisioned on startup |
| Activity catalogue + form→activity map | `app/models/forms.py:129` | ✅ all 14 |
| Calendar events + conflict validation | `backend/app/routes/calendar_events.py` (1442 L) | ✅ but generic LMS-flavoured |
| Schedule Activity modal | `frontend/src/components/calendar/ScheduleCalendarModal.jsx` | ✅ |
| Reminder scheduler | `backend/app/services/reminder_scheduler.py` | ✅ generic |
| S3 uploads | `backend/app/services/s3_service.py` | ✅ |
| TPMS shell + routing + role gate | `frontend/src/features/tpms/` (33 files, 4.8k L) | ✅ layouts for Admin / SMOps / Client |
| Rating & checklist forms (React) | `.../admin/pages/forms/`, `.../client/` | ✅ wired to `/api/forms/*` |

**Mock-only UI shells — every one says "All data is placeholder mock":**
`AdminView`, `ClientView`, `HodView`, `EmployeeTasks`, `Escalations`, `ImplementationTracker`,
`LogsReport`, `ReviewReport`, `OmSmopsView`, `SmopsDashboard`, `HodActivity`, `SmopsEmployeeTask`.

**Missing on the backend entirely:** escalation engine, reschedule-request workflow,
two-step (learner-done → staff-confirm) completion, `Activity_Tracker` rollup,
Success-Measure computation + manual score entry, task uploads tied to a schedule,
WhatsApp send path, per-activity mail templates, and every `/api/tpms/*` dashboard endpoint.

---

## 9. Decisions needed before coding

1. **Merge or fork the calendar.** `Calendar_Schedule` (activity/company/doers/SMOps/
   escalation-stage) vs the ERP's `calendar_events` (batch/quarter/session/assessment).
   `calendar_event.py` already carries `activity`, `activity_meta`, `company_id` — suggesting
   the intent was to merge. Recommend **extending `calendar_events` with a
   `kind: "tpms_activity"` discriminator** rather than a parallel collection, so one calendar
   UI serves both. Confirm.
2. **Month token.** Forms use `jul26`; `Success_Measures` uses `July26`; `Calendar_Schedule`
   uses real dates. Standardise on **`YYYY-MM`** stored, formatted at the edge.
3. **Form access.** AppScript used unauthenticated deep links (`?CID&EID&MID`). The ERP has
   real auth. Keep the emailed deep link but require login, or issue signed single-use tokens?
   This changes the notification payload.
4. **Cell-locking semantics.** Sheet version made saved cells permanently immutable. Keep, or
   allow edit-until-period-close? (Recommend a `locked_at` on the period.)
5. ~~**Culture form.**~~ **RESOLVED — and the ERP model is wrong.** `HOD_Culture/code.js`
   confirms Culture is **HOD-rates-team**, identical to Accountability and Ownership: it builds
   the team from `HOD_IDs`, returns `hod:{id,name}` + `team[]`, and writes one row per
   (question × employee) to `HOD_Culture_Responses` (261 rows of live data agree).
   `app/models/forms.py:80` currently declares `audience:"all", self_rating:True` — **that is
   incorrect and must be changed** before the form is enabled, or 261 historical rows won't
   migrate into a shape the reader understands. Corrected definition (criteria verbatim from
   `HOD_Culture_Question`):

   ```python
   "culture": {
       "form_type": "culture", "kind": KIND_RATING_MATRIX,
       "title": "Culture Rating",
       "description": "Monthly HOD culture rating for each team member.",
       "available": True,
       "audience": "hod",                      # was "all"
       # self_rating: True  ← DELETE this key
       "scale": {"min": SCALE_MIN, "max": SCALE_MAX},
       "criteria": [
           {"code": "C1", "title": "Works in the Team",
            "prompt": "Supportive and works as a team"},
           {"code": "C2", "title": "Problem Solving Approach",
            "prompt": "Acts as a problem solver in day-to-day work situations and approches with multiple solutions."},
           {"code": "C3", "title": "Carrying Pocket Diary",
            "prompt": "Carries the Pocket Diary at all times as required"},
           {"code": "C4", "title": "Understanding the Core Ideology",
            "prompt": "Is aware of company core values and actively practices them"},
           {"code": "C5", "title": "Customer First Attitude",
            "prompt": "Exhibits a customer-first attitude for internal and external customers"},
       ],
   }
   ```

   Note the `Activity` sheet marks *Culture Rating* as `Company vise` while *Accountability &
   Ownership Rating* is `HOD wise`. That column governs **scheduling and upload scope only** —
   it does not describe who fills the form. All three rating forms are filled by HODs.

6. **Implementation Feedback respondent.** AppScript = **MD only** (`getFormData` looks the
   respondent up by `Employee_ID` and labels it `md`, writing `MD_ID`/`MD_Name`). ERP model =
   `audience:"all", respondent:"user"`. Same class of contradiction as #5 — verify with the
   client whether it stays MD-only. The 15 questions are confirmed and ready to paste; they
   have no descriptions, so `desc` is `""` for all of them:

   > ORM score received · process audit scores per dept · CSI reviewed · TEI actions taken ·
   > OHL pyramid progress · DRM depts (free text) · IRM RRO schedules · WRM happening ·
   > MMR conducted · A&O ratings · culture ratings · leadership scoring · leader calendars ·
   > implementation speed · leadership support & decision speed

   ⚠ Q6 ("Please mention for which departments you are receiving DRM scores?") is a
   **free-text question living in a Yes/No form**. It currently gets answered Yes/No with the
   real answer in `Remark`. Consider a `question_type` field on the checklist model.
7. **WhatsApp.** All 195 `Whatsapp_logs` rows are `Failed — HTTP 400 (#132000)` (Meta template
   parameter-count mismatch). The integration never worked. Scope in or out?
8. **Escalation — which of the three ladders is real?** (§5.1) The highest-priority question
   in this migration. Engine A auto-lapses at **D+3**; Engine B reports levels at **T+5/7/10**;
   the UI documents a **7-stage** ladder nobody implements. Recommend: keep Engine A's mail
   cadence, drop Engine C, and rebuild Engine B's `Escalations`/`Action_Items` rows as a
   *projection* of Engine A's stages so the dashboard and the inbox finally agree. Needs a
   business decision on whether 3 days to auto-lapse is intended.
9. **Log volume.** `getLogsReport` truncates to the latest 3000 rows and exports CSV
   client-side. With Mongo, paginate server-side and stream the export instead.
10. **Broken form links.** `HOD_FORMS` points at `/dev` deployment URLs, which only work for
    users with script edit access — so the emailed form buttons are dead for actual clients.
    In the ERP these become in-app authenticated routes, but confirm whether anyone has been
    successfully filling these forms via email, because the data suggests not.
11. **Binary implementation %.** `Actual_Implementation_%` is `100` or `0`, never a ratio
    (§5.2). For "WRM, 3-4 in month" this means 1 of 4 completed still reports 100%. Intended,
    or should it become `completed ÷ total`?

---

## 10. Suggested build order

0. **Rotate the leaked WhatsApp token** (§0)
1. Master data: activities, departments, reminder rules, mail templates → seed from xlsx
2. Schedules: create/update/delete + recurrence expansion + once-a-month conflict check
3. Lifecycle: learner-done → staff-confirm; reschedule request/approve
4. Notifications: template resolution + email send + logs (WhatsApp behind a flag)
5. Reminder cron over `tpms_reminders`
6. Uploads → S3, tied to schedule + activity scope
7. Escalation + action-item sweep (daily job)
8. Success Measures: auto implementation %, manual score entry, form-derived scores
9. Replace the 12 mock dashboards with real endpoints
10. Fix Culture in `FORM_DEFINITIONS` (§9.5 — ready to paste, no blockers) and add the
    Implementation Feedback questions once §9.6 is confirmed
11. Migration script: xlsx → Mongo (≈3.5k rows of live history)
