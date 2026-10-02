# Admin Reports Module — Analysis & Implementation Plan

**Project:** Sparsh 2.0 — Business Coaching ERP
**Prepared:** 2026-07-01
**Status:** **Analysis & design only — no code written, no existing files modified.**
**Objective:** Add an **Admin-only "Reports"** module to the Sidebar delivering company + employee ("Doer") task-performance reporting, reusing the existing design system, APIs, charts, and components.

> This is a pre-implementation blueprint. Every claim is grounded in the current codebase with `file:line` references. **Implementation should begin only after you approve this plan and resolve the "Decisions Needed" in §5.**

---

## 0. Decisions — RESOLVED (2026-07-01)

| # | Decision | Chosen | Impact |
|---|---|---|---|
| Score formula | undefined → define | **Default accepted** (`0.6·completion_rate + 0.4·on_time_rate`; bands Excellent ≥85 / Good 70–84 / Average 50–69 / Needs Attention <50) | Computed; no new data |
| Checklist | A/B/C | **B — map to session-template `tasks[]` + `company_session_progress`** | Adds a "Checklist (session tasks)" report view; reuses `company.py:495-579` completion data |
| Approved/Rejected | A/B | **A — report-only** (`verification` shown as "Awaiting Approval"; no Approved/Rejected counts) | No workflow change |
| Timeline | A/B | **A — reconstruct from existing** (`created_at`→`completed_at` + best-effort `activity_logs` events) | Read-only; no new capture |
| Admin roles | which roles | **`superadmin` ONLY** | Sidebar link + all `/api/reports/*` + page guard gated to `superadmin` alone (not `admin`) |

> Consequence of "superadmin only": the `admin` role will **not** see or access Reports. This matches the existing pattern where the Sidebar Settings link is superadmin-only (`Navbar.jsx`), and superadmin already bypasses permission checks (`auth_controller.py:73-96`). Sidebar `roles: ['superadmin']`; API gate `check_role(["superadmin"])`; add a page-level guard redirecting non-superadmins.

---

## 1. Executive Summary & Terminology Mapping

The codebase **already tracks the raw task data** needed for most of the requested reports (dates, statuses, assignee/creator, priority, category, department-on-user, activity logs) and **already has reusable report UI** (`TaskDashboard.jsx`, `StackedReportPanel.jsx`, `StatusSummaryCards.jsx`, `DateRangeFilter.jsx`, recharts patterns, `exportTasksToCsv`). Export infra (`openpyxl`, `reportlab`) exists server-side.

However, your spec uses vocabulary that must be mapped to what actually exists — and three concepts **do not exist** and must be defined or built:

| Spec term | Reality in codebase | Where |
|---|---|---|
| **Doer** (employee doing the task) | `target_staff_id` (task assignee list) | `calendar_event.py:50-51`, `tasks.py:51,216` |
| **Delegator** (who assigned) | `user_id` (creator) with `assigned_to="other"` | `calendar_event.py:50`, `tasks.py:150-152` |
| **Assigned date** | `start` (ISO) + `created_at` (UTC) | `calendar_event.py`, `calendar_events.py:226` |
| **Due date** | `end` (falls back to `start`) | `tasks.py:96` |
| **Completed date** | `completed_at` — **set only when `workflow_status→"completed"`** | `tasks.py:343` |
| **Status** | `workflow_status` (7 values) + legacy `status` | `tasks.py:19-22` |
| **Priority** | `priority` (default "Normal") | `calendar_event.py:23` |
| **Department** | On the **user** doc, not the task | `user.py`, join via `target_staff_id` |
| **Score / Performance Rating** | ❌ **Does not exist for tasks** — must be COMPUTED | see §5.1 |
| **Checklist** | ❌ **No checklist entity** — closest is session-template `tasks[]` | see §5.2 |
| **Approved / Rejected** states | ❌ **Not in workflow** (`verification` ≈ pending-approval) | see §5.3 |
| **Timeline (started/approved)** | ⚠️ Partial — no `started_at`; status changes in `activity_logs` as free text | see §5.4 |

**Bottom line:** ~70% of the module can be built by **reusing/aggregating existing data**; ~30% needs small, **non-breaking additive** work (a computed score definition, an optional structured status-history capture, and UI). No existing API, model, workflow, auth, or UI needs to change.

---

## 2. Data Availability Matrix (the core of this analysis)

Legend: ✅ Exists · 🟨 Computed from existing data · 🟥 Needs new data capture

| Requested report field / metric | Status | Source / how |
|---|---|---|
| Total Employees | ✅ | count `staff`+`learners` (`user.py:30-31`) |
| Total Assigned Tasks | ✅ | count tasks (`type="task"`) across `TASK_COLLECTIONS` (`tasks.py:14`) |
| Completed / Pending / Overdue Tasks | ✅ / 🟨 | `workflow_status`; overdue = `_is_overdue()` (`tasks.py`) |
| Average Completion Rate | 🟨 | completed ÷ assigned |
| Average Performance Score | 🟥→🟨 | **must define** (recommend on-time rate; see §5.1) |
| Company: Total/Completed/Pending/Completion% | ✅ / 🟨 | task counts by status |
| Productivity Score | 🟥→🟨 | derived formula (§5.1) |
| Doer: Assigned/Completed/Pending/Overdue | ✅ / 🟨 | group tasks by `target_staff_id` |
| Doer: Completion % | 🟨 | completed ÷ assigned per doer |
| Doer: Average Score | 🟥→🟨 | computed (§5.1) |
| Doer: Average Completion Time | 🟨 | `completed_at − start` (only for completed tasks) |
| Doer: Performance Rating / Ranking | 🟨 | rank by chosen score |
| Name / Role / Department | ✅ | user doc (`department` default "Other") |
| Task Summary (assigned/completed/pending/overdue) | ✅ / 🟨 | per-doer grouping |
| **Rejected / Approved Tasks** | 🟥 | **no such status** — see §5.3 |
| Assignment History table (task, module, assigner, dates, status, priority, score) | ✅ / 🟨 | task docs + join users; "module"=collection/`category`; "score" computed |
| **Timeline (assigned→started→in-progress→completed→approved)** | ⚠️ 🟥 | partial — no `started_at`/`approved`; see §5.4 |
| Monthly / weekly completion, status distribution, productivity trend, score trend, completion-time trend | 🟨 | aggregate task docs by period (pattern already in `tasks.py:/tasks/dashboard` monthly buckets) |
| Department Comparison | 🟨 | group by user `department` (pattern in `company.py:635-640`) |
| Filters: date/month/quarter/year/department/doer/delegator/status/priority | ✅ / 🟨 | period logic exists (`tasks.py` `_period_to_range`); others via query params |
| Export PDF / Excel / CSV | ✅ | `reportlab` + `openpyxl` server-side; CSV via `exportTasksToCsv` client-side |
| Search (employee/task/department) | ✅ | reuse `TaskListView` search pattern |
| Sorting | ✅ | reuse `TaskListView` sort pattern |

---

## 3. Existing API Analysis (reuse first)

Existing analytics endpoints (all **role/company-scoped**, all currently **Python-loop aggregation, not Mongo pipelines**):

| Endpoint | Returns | Reuse for Reports? |
|---|---|---|
| `GET /api/tasks/dashboard` (`tasks.py:224-301`) | `summary` (status counts, overdue, in_time/delayed) + `monthly[]` buckets (`total, score(in-time), overdue, pending, inProgress, inTime, delayed`) | **Primary reuse** — closest analog; extend with per-doer grouping |
| `GET /api/tasks?scope=&type=&status=&sort=&skip=&limit=` (`tasks.py`) | scoped task list (creator/assignee/watcher visibility) | Reuse for assignment-history + drill-down |
| `GET /api/dashboard/stats` (`dashboard.py:11-127`) | org KPIs, 14-day pulse, session mix | Reuse KPI/pulse pattern |
| `GET /api/users/{id}/analytics` (`user.py:334-434`) | weekly scores, attendance, learning progress (**assessment-based, `task_stats` is stubbed**) | Reference only (learning, not task perf) |
| `GET /api/companies/{id}/analytics` (`company.py:581-761`) | monthly trend, dept distribution, session split, top performers (**uses `$group`+`$lookup`**), performance_data | Reuse dept-distribution + aggregation pattern |
| `GET /api/quarters/{id}/analytics` (`quarter.py:39-90`) | sessions, attendance, tasks_done% | Reference |
| `GET /api/companies/{id}/users/template` (`company.py:287-336`) | **openpyxl Excel** streaming download | **Reuse as the Excel-export template** |

**Conclusion:** The `/tasks/dashboard` monthly-bucket aggregation is the right foundation. For the *Doer performance* and *individual Doer* reports, we need **new aggregation grouped by `target_staff_id`** — not currently provided. Recommend **new endpoints under `/api/reports/*`** (additive, non-breaking) rather than overloading task routes.

---

## 4. Existing Database Analysis

**Task documents** (`calendar_event.py`, `type="task"`, stored across `STAFF_CALENDER`/`LEARNER_CALENDER`/`calendar_events`):
`title, type, start, end, created_at, updated_at, completed_at?, status(legacy), workflow_status(pending|accepted|in_progress|dependent_on_others|blocked|verification|completed), priority, category, description, tags[], user_id(creator/delegator), target_staff_id[](doers), assigned_to(myself|other), watchers[], batch_id?, quarter_id?, company_id?, deleted_at?`.

**User/employee documents** (`user.py`, split `staff` vs `learners`, discriminated by `tag`):
`email, first_name, last_name, full_name, mobile, role, company_id, is_active, tag(staff|learner), department(default "Other"), designation?, session_type?, permissions{}, created_at`.

**Audit** (`activity_logs` via `activity_log_service.py:6-21`): `user_id, user_name, user_email, action, module, details(free text), metadata{}, timestamp`. Task actions logged: `"Create Event", "Update Event", "Update Task Status", "Soft Delete Task", "Restore Task"`.

**Key data facts for reporting:**
- ✅ Completion timestamp exists (`completed_at`) — enables completion-time and on-time metrics.
- ✅ Overdue computable (`end` vs now).
- 🟥 **No `started_at`** — "started" milestone not directly available.
- 🟥 **Status-change history is unstructured** — stored as free-text in `activity_logs.details` (e.g., `"Task <id> -> in_progress"`), not queryable structured metadata. Timeline reconstruction is possible but fragile.
- 🟥 **No task-level score field.**

---

## 5. Gaps & Decisions Needed (must resolve before build)

### 5.1 "Score" / "Performance Rating" is undefined — **define it**
No task score exists. **Recommended definition** (computable from existing fields, no new capture):

```
on_time_rate   = on_time_completed / total_completed          # completed_at <= end
completion_rate= completed / assigned
productivity   = 0.6*completion_rate + 0.4*on_time_rate        # 0..1 → ×100
performance_rating = Excellent ≥85 | Good 70–84 | Average 50–69 | Needs Attention <50
avg_completion_time = mean(completed_at − start) over completed tasks
```
> Decision: accept this formula, or provide your own weighting / rating bands.

### 5.2 "Checklist" does not exist — **choose scope**
No checklist entity. Options:
- **(A) Drop "checklist"** from v1 (treat tasks as the unit) — *recommended, lowest risk*.
- **(B) Map to session-template `tasks[]`** + `company_session_progress.done_indices` (`company.py:495-579`) — reporting on session task completion.
- **(C) Build a real checklist/subtask feature** — larger scope, changes task model.
> Decision: A, B, or C?

### 5.3 "Approved / Rejected" task states do not exist — **choose mapping**
Workflow has no approve/reject. `verification` is the closest ("awaiting approval"). Options:
- **(A)** Report `verification` as "Awaiting Approval"; omit "Approved/Rejected" counts — *recommended for v1*.
- **(B)** Extend `workflow_status` enum with `approved`/`rejected` — a workflow change (touches task status logic + Task UI); **out of "do not change existing workflow" guardrail** unless you approve it.
> Decision: A (report-only mapping) or B (workflow change)?

### 5.4 Timeline fidelity — **choose level**
- **(A) Reconstruct from what exists:** creation (`created_at`) → completion (`completed_at`), plus best-effort status events parsed from `activity_logs`. No "started"/"approved". Read-only, zero new capture. *Recommended for v1.*
- **(B) Add a structured `task_status_history` collection** (additive, non-breaking): each status change writes `{task_id, from, to, changed_by, at}`. Enables an accurate full timeline going forward (not retroactive). Small change to the status-update handler (additive log write only — no behavior change).
> Decision: A now, B as a fast-follow? (Recommended.)

### 5.5 "Admin only" — **confirm which role(s)**
Roles: `superadmin, admin, coach, staff, clientadmin, clientuser`. "Admin" most likely means `admin` — but `superadmin` outranks admin and should presumably also see it.
> Decision: gate to `['superadmin','admin']` (recommended), or `admin` only, or include `coach`?

---

## 6. Report Architecture

**Non-breaking, additive, namespaced** (mirrors existing conventions):

```
Backend  (new, additive)
  app/routes/reports.py          # new router → registered in main.py alongside others
  app/services/report_service.py # aggregation helpers (Mongo pipelines, role-scoped)
  (optional) app/models/reports.py            # response DTOs
  (optional, §5.4B) task_status_history collection + 1 additive log write

Frontend (new, additive)
  src/pages/ReportsDashboard.jsx      # /admin/reports  (KPIs + company charts + doer table)
  src/pages/DoerReportDetails.jsx     # /admin/reports/:doerId (individual report)
  src/services/reportApi.js           # axios calls (reuse shared instance)
  (reuse) StatusSummaryCards, DateRangeFilter, StackedReportPanel, recharts patterns,
          TaskListView filter/sort/search, exportTasksToCsv
  Sidebar link (admin-only) + 2 lazy routes in App.jsx
```

**Guardrails honored:** no change to existing endpoints, task workflow, auth, or UI components; Reports consumes them. New APIs are read-only aggregations. Reuses the exact design tokens/components so it looks native.

---

## 7. Report Flow Diagram

```
Admin clicks Sidebar ▸ Reports  (visible only to superadmin)
        │
        ▼
/admin/reports  ── ReportsDashboard.jsx
   ├─ GET /api/reports/overview?period=&department=      → KPI cards (StatusSummaryCards)
   ├─ GET /api/reports/company?period=                   → Bar/Pie/Line/Area (recharts)
   └─ GET /api/reports/doers?period=&dept=&sort=&search= → ranked Doer table (TaskListView pattern)
        │  (click a Doer row)
        ▼
/admin/reports/:doerId  ── DoerReportDetails.jsx
   ├─ GET /api/reports/doers/{id}?period=       → basic info + task summary + metric cards
   ├─ GET /api/reports/doers/{id}/history?...    → assignment-history table (paginated)
   ├─ GET /api/reports/doers/{id}/timeline?...   → per-task timeline (created→completed [+status events])
   └─ GET /api/reports/doers/{id}/trends?...     → line/bar/pie/area trend charts
        │
        ▼
Export ▸  GET /api/reports/export?scope=&format=csv|xlsx|pdf   (openpyxl / reportlab)
```

Every list endpoint returns `{ items, total, skip, limit }`; every endpoint is **role-scoped** (admins → org-wide; scoping mirrors existing analytics).

---

## 8. Required APIs (new — `/api/reports/*`, read-only, additive)

All: `Depends(get_current_user)` + **`check_role(["superadmin"])`** (superadmin-only), Pydantic responses, skip/limit pagination, Mongo aggregation pipelines (grouped by `target_staff_id` / `department` / month).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/reports/overview?period&department` | KPI cards: employees, assigned, completed, pending, overdue, avg completion %, avg score |
| GET | `/api/reports/company?period&department` | Company totals + series for Bar/Pie/Line/Area (status distribution, monthly completion, productivity trend) |
| GET | `/api/reports/doers?period&department&status&priority&search&sort&skip&limit` | Ranked Doer performance rows (assigned/completed/pending/overdue/completion%/avg score/avg time/rating) |
| GET | `/api/reports/doers/{doer_id}?period` | Individual: basic info + task summary + metrics |
| GET | `/api/reports/doers/{doer_id}/history?period&status&priority&skip&limit` | Assignment history (task, module, assigner, dates, status, priority, score) |
| GET | `/api/reports/doers/{doer_id}/timeline?task_id?` | Timeline events (per §5.4 choice) |
| GET | `/api/reports/doers/{doer_id}/trends?period&granularity` | Monthly/weekly series for the 7 charts |
| GET | `/api/reports/departments?period` | Department comparison series |
| GET | `/api/reports/export?scope&doer_id?&period&format=csv\|xlsx\|pdf` | File download (reportlab/openpyxl) |

> Reuse note: internal aggregation can share helpers with `tasks.py`'s `_resolve_workflow_status`, `_is_overdue`, `_completion_timing`, `_period_to_range` (refactor into `report_service`/shared util without changing task routes' behavior).

## 9. Required Database Changes

- **None required** for v1 option-A path (all reads over existing task/user/activity collections).
- **Recommended additive index** (safe): compound index to speed report grouping, e.g. on task collections `{type:1, "target_staff_id":1, workflow_status:1, start:1}` and on `staff`/`learners` `{department:1, is_active:1}`. Additive only.
- **Optional (§5.4B):** new `task_status_history` collection + **one additive write** in the existing status-update handler (no change to response or existing behavior). Enables accurate forward-looking timelines.
- **Optional (scale):** migrate the reused Python-loop aggregations to Mongo `$group`/`$facet` pipelines in `report_service` (the module ships with pipelines from day 1; existing endpoints untouched).

## 10. Required UI Components & Charts (reuse map)

**Reuse as-is / by pattern:**
- KPI cards → `StatusSummaryCards.jsx` (`cardOrder`, `summary`, `onSelect`) + Dashboard tile pattern (`Dashboard.jsx:98-119`).
- Charts → recharts patterns from `Dashboard.jsx:135-175` (Area w/ gradient, Pie w/ Legend) and `StackedReportPanel.jsx:40-50` (stacked Bar). All use `var(--accent-*)` tokens, `ResponsiveContainer`, themed tooltips, `animationDuration`. Dark mode automatic.
- Filters/sort/search/view-toggle → `TaskListView.jsx:216-312` toolbar + `DateRangeFilter.jsx` (period presets + custom range).
- Tables → inline `<table>` pattern (`TaskListView.jsx:335-383`).
- Master→detail → `UserManagement→UserDetails` routing + `useParams` fetch pattern; tabs via button-toggle (`TaskDashboard.jsx:325-334`).
- CSV export → `exportTasksToCsv` (`taskDisplayUtils.js:30-52`); PDF/Excel via new backend endpoint.
- Nav → `Sidebar.jsx links[]` config; icons from `lucide-react` (`BarChart3, TrendingUp, Award, Users, FileText`).

**Charts required (all recharts, interactive tooltips/legends/animation):**
Monthly Task Completion (Line) · Weekly Performance (Bar) · Task Status Distribution (Pie) · Productivity Trend (Area) · Score Trend (Line) · Completion-Time Trend (Bar) · Department Comparison (Bar).

## 11. Filters · Export · Search · Sort (mapping)

- **Filters:** Date range/month/quarter/year (reuse `DateRangeFilter` + `_period_to_range`), Department, Doer, Delegator, Status, Priority (query params → aggregation `$match`). Reports update dynamically (client refetch on change — TaskDashboard pattern).
- **Export:** CSV (client blob, existing), Excel (`openpyxl`, reuse `company.py:287-336` streaming pattern), PDF (`reportlab`, reuse `assistant/export/pdf_generator.py` approach).
- **Search:** employee/task/department — client filter for loaded rows + server `search` param for large sets.
- **Sort:** name/assigned/completed/score/performance/completion-time — server `sort` param.

## 12. Performance Plan

- **Frontend:** `React.lazy` the two Reports pages (currently no code-splitting anywhere — this also prevents bundle growth); lazy-mount charts; paginate the Doer + history tables; debounce search; memoize chart data.
- **Backend:** use **Mongo aggregation pipelines** (not Python loops) for all report grouping; cap result sets with skip/limit + `total`; add the compound indexes in §9; consider caching hot report responses via the existing `TTLCache` pattern (`assistant/caching/cache.py`).

## 13. Permissions (Admin-only)

- **Sidebar:** add link with `roles: ['superadmin']` (superadmin-only). Existing filter logic (`Sidebar.jsx:64-76`) auto-hides it from every other role, exactly like the current superadmin-only Settings link.
- **Routes:** wrap in `PrivateRoute`; **add a page-level role guard** (redirect non-superadmins) so the URL can't be hit directly — small addition, since existing `PrivateRoute` only checks auth, not role.
- **API:** every `/api/reports/*` endpoint gated by `check_role(["superadmin"])`.

## 14. Implementation Plan (phased, after approval)

| Phase | Scope | Est. |
|---|---|---|
| **0. Decisions** | Resolve §5 (score formula, checklist scope, approve/reject, timeline level, admin roles) | — |
| **1. Backend aggregation** | `report_service` pipelines + `/api/reports/overview,company,doers,departments` (read-only, admin-gated); indexes | 3–4 d |
| **2. Reports Dashboard UI** | `/admin/reports` page: KPI cards + company charts + ranked Doer table (reuse components); Sidebar link + lazy route + role guard | 3–4 d |
| **3. Individual Doer report** | `/admin/reports/:doerId`: summary + history table + trend charts + timeline (per §5.4) | 3–4 d |
| **4. Filters/search/sort/export** | wire filters; CSV (reuse) + Excel/PDF endpoints | 2–3 d |
| **5. (Optional) status history** | `task_status_history` + additive log write for accurate timelines | 1 d |
| **6. Perf & polish** | pagination, caching, dark-mode check, responsive QA | 1–2 d |
| **7. Test & review** | role-gating tests, aggregation correctness, no-regression check | 1–2 d |

**Total ≈ 2.5–3.5 weeks** for a single full-stack dev (v1, option-A choices).

## 15. Deliverables Checklist (as requested)

1. ✅ Complete Project Analysis — §1–§4 (+ companion `LMS_ANALYSIS_AND_IMPLEMENTATION_REPORT.md` for full architecture)
2. ✅ Existing API Analysis — §3
3. ✅ Existing Database Analysis — §4
4. ✅ Report Architecture — §6
5. ✅ Report Flow Diagram — §7
6. ✅ Required APIs — §8
7. ✅ Required Database Changes — §9 (none required for v1; optional additive items)
8. ✅ Required UI Components — §10
9. ✅ Required Charts — §10
10. ✅ Implementation Plan — §14

**Guardrails confirmed:** no existing API, business logic, workflow, UI language, or auth is changed; the module is additive and namespaced; it reuses existing components, charts, tables, cards, typography, colors, spacing, and layouts to feel native.

---

## Decisions — RESOLVED (see §0)

1. **Score formula** — ✅ default accepted (`0.6·completion + 0.4·on-time`; Excellent/Good/Average/Needs-Attention bands).
2. **Checklist** — ✅ **B: map to session-template `tasks[]`** (+ `company_session_progress`). Adds a checklist/session-tasks report view.
3. **Approved/Rejected** — ✅ **A: report-only** (`verification` = "Awaiting Approval").
4. **Timeline** — ✅ **A: reconstruct from existing** (`created_at`→`completed_at` + `activity_logs`).
5. **Access** — ✅ **`superadmin` only** (not `admin`).

**Ready for implementation approval.** On your go-ahead I'll start Phase 1 (backend aggregation endpoints, superadmin-gated) followed by the UI phases in §14.

---

## Addendum B — "FocusPrint ERP" spec reconciliation (2026-07-01)

A second, fuller spec ("FocusPrint ERP – Admin Reports & Analytics Module") was provided. It is the **same module** as this blueprint (the app is Sparsh 2.0; "FocusPrint" is treated as a label for this repo). All 12 requested deliverables are already covered above; this addendum records only the **delta** — the extra cards, charts, and KPIs it adds, and how each maps to real data.

### B.1 Deliverables map (FocusPrint → this document)

| # | FocusPrint deliverable | Covered in |
|---|---|---|
| 1 | Complete Project Analysis | §1–§4 (+ `LMS_ANALYSIS_AND_IMPLEMENTATION_REPORT.md`) |
| 2 | Existing API Analysis | §3 |
| 3 | Existing Database Analysis | §4 |
| 4 | Report Module Architecture | §6 |
| 5 | Required APIs | §8 (+ B.3 additions) |
| 6 | Required Database Changes | §9 (none required for v1) |
| 7 | Required UI Components | §10 |
| 8 | Report Screen Flow | §7 |
| 9 | Graph Strategy | §10 + B.2 |
| 10 | Performance Strategy | §12 |
| 11 | Security Considerations | §13 (superadmin-only) |
| 12 | Implementation Roadmap | §14 |

### B.2 New summary cards, charts & KPIs (delta)

**Extra summary cards** (added to §1 Dashboard cards):
| Card | Status | Source |
|---|---|---|
| Total Delegators | 🟨 | distinct task `user_id` where `assigned_to="other"` |
| Total Doers | 🟨 | distinct ids across `target_staff_id` |

**Extra charts** (added to §10's 7 charts → 10 total; all recharts):
| Chart | Type | Status | Source |
|---|---|---|---|
| Daily Performance | Line | 🟨 | tasks grouped by day (reuse `dashboard.py` 14-day pulse pattern) |
| Priority Distribution | Pie | ✅ | group by `priority` |
| Company Growth Trend | Line | 🟨 | **define** — recommend cumulative tasks (or active users) per month |
| Top Performers | Horizontal Bar | 🟨 | rank doers by score; recharts `layout="vertical"` |

**Extra KPIs** (added to §5.1 score set — all computed, no new data):
```
success_rate         = approved_or_completed / total_completed     # (approved N/A → uses completed)
delay_rate           = delayed_completed / total_completed
efficiency           = on_time_completed / assigned
workload_distribution= per-doer assigned counts (Gini/spread across team) → bar/heat
```

### B.3 ⚠️ Task-History columns that have NO backing data

The FocusPrint "Task History" asks for **Started Date** and **Approved Date** columns, and "Rejected/Approved Tasks" counts. Per the resolved decisions (§0): timeline = *reconstruct from existing* and approve/reject = *report-only*. Therefore:

| Column / metric | Reality | v1 behavior |
|---|---|---|
| Assigned Date | ✅ `start`/`created_at` | shown |
| Due Date | ✅ `end` | shown |
| **Started Date** | 🟥 no `started_at` field | shown as **"—"** (or first `in_progress` event *if* status-history option §5.4B is later adopted) |
| Completed Date | ✅ `completed_at` | shown |
| **Approved Date** | 🟥 no approval workflow | shown as **"—"** / column hidden |
| Score | 🟨 computed (§5.1) | shown |
| **Rejected / Approved counts** | 🟥 no such states | omitted; `verification` shown as "Awaiting Approval" |

> To make Started/Approved dates real, adopt **§5.4 option B** (`task_status_history` + additive log write) and, for approvals, **§5.3 option B** (workflow enum change). Both were previously declined for v1. Flag if you now want them.

### B.4 FocusPrint decisions — RESOLVED (2026-07-01)

| Decision | Chosen | Effect |
|---|---|---|
| Started/Approved dates | **Keep v1 — show "—"** | No workflow/data-capture change; columns render "—". Real dates only if status-history is enabled later. |
| Access | **`superadmin` only** (confirmed) | `admin` role does **not** see Reports. |
| Company Growth Trend | **Cumulative tasks/month** | Line chart = running total of tasks created over time. |

**Net effect on build:** unchanged from §14 — still fully additive, superadmin-gated, no workflow change. The 3 extra charts (Daily, Priority, Growth, Top Performers) and 2 extra cards (Delegators, Doers) fold into Phases 1–3. Started/Approved columns ship as "—". Ready for implementation on approval.

*End of analysis. No code was written and no existing project files were modified.*
