# Sparsh Magic ERP — Enterprise Reports & Analytics — Analysis & Plan

**Prepared:** 2026-07-01
**Status:** **Analysis & design only — awaiting approval before building the expansion.**
**Context:** This is the **enterprise superset** of the Admin Reports module already delivered this session (see [ADMIN_REPORTS_MODULE_ANALYSIS.md](ADMIN_REPORTS_MODULE_ANALYSIS.md) and the shipped code: `backend/app/routes/reports.py`, `backend/app/services/report_service.py`, `frontend/src/pages/ReportsDashboard.jsx`, `frontend/src/pages/DoerReportDetails.jsx`). It keeps everything already built (task performance) and adds new data domains: **company, learner, session, batch, department, assessment, and attendance analytics**, ~17 charts, drill-down, and broader (Admin) access.

> The full architecture/UI/DB/security analysis was completed earlier this session and lives in [ADMIN_REPORTS_MODULE_ANALYSIS.md](ADMIN_REPORTS_MODULE_ANALYSIS.md) and [LMS_ANALYSIS_AND_IMPLEMENTATION_REPORT.md](LMS_ANALYSIS_AND_IMPLEMENTATION_REPORT.md). This document is the **enterprise delta**: what already exists to reuse, what must be computed, what is genuinely missing, and the roadmap.

---

## 0. Already built vs. requested (start here)

| Requested area | Status |
|---|---|
| Sidebar "Reports" (admin-gated), lazy routes, page guard | ✅ Built (superadmin) — needs access widened to Admin (see §13) |
| Task KPI cards, employee (Doer) performance table + ranking | ✅ Built |
| Individual employee report + task history + per-task timeline | ✅ Built |
| Task charts (completion, status, priority, growth, top performers, dept) | ✅ Built |
| CSV / Excel / PDF export | ✅ Built |
| **Company / learner / session / batch / department analytics** | 🟨 New — data exists, needs new endpoints + UI |
| **Assessment score & attendance analytics** | 🟨 New — data exists (`LearnerAssessments`, `attendance`) |
| **Global filters (company/batch/quarter/coach/learner)** | 🟨 New — extend current period/department filters |
| **Drill-down (Company→Dept→Batch→Employee→Assignment→Timeline)** | 🟨 New — layered endpoints + UI |
| **Employee ID, Reporting Manager, Active Courses, Started/Approved/Reviewed** | 🟥 Do not exist — see §Gaps |

---

## Deliverable 1 — Complete Project Analysis
Full analysis in [ADMIN_REPORTS_MODULE_ANALYSIS.md](ADMIN_REPORTS_MODULE_ANALYSIS.md) §1–§4 and [LMS_ANALYSIS_AND_IMPLEMENTATION_REPORT.md](LMS_ANALYSIS_AND_IMPLEMENTATION_REPORT.md). Summary: FastAPI + MongoDB (Motor, async) backend, 17 routers under `/api`; React 19 + Vite + Tailwind v4 frontend, Context state, recharts, config-driven role-filtered Sidebar. JWT (HS256) + dual RBAC. Deployed via Docker Compose to EC2.

## Deliverable 2 — Existing API Analysis (reuse first)
| Endpoint | Provides | Reuse for |
|---|---|---|
| `GET /api/reports/*` (**new, built**) | task overview/company/doers/detail/history/timeline/export | Task analytics base |
| `GET /api/dashboard/stats` | companies, batches, learners, session velocity, 14-day pulse, session mix | Top KPIs, session charts |
| `GET /api/companies/{id}/analytics` | monthly_trend, dept_distribution, session_type_split, **top_performers ($group+$lookup on LearnerAssessments)**, performance_data | Company/dept/assessment analytics |
| `GET /api/users/{id}/analytics` | weekly assessment scores, monthly attendance, learning progress | Individual learner report |
| `GET /api/quarters/{id}/analytics` | sessions, avg attendance, active companies, task completion % | Batch/quarter analytics |
| `GET /api/users`, `/companies`, `/batches`, `/quarters` | entity lists + counts | KPI counts, filters |
| `GET /api/companies/{id}/users/template` | openpyxl Excel streaming | Excel export pattern (already reused) |

**Conclusion:** company/learner/session analytics data already exists and is partly aggregated. New `/api/reports/*` enterprise endpoints should **wrap and unify** these (org-wide, superadmin/admin-scoped) rather than duplicate them.

## Deliverable 3 — Existing Database Analysis (data availability)
Collections available: `staff`, `learners`, `companies`, `batches`, `quarters`, `STAFF_CALENDER`/`LEARNER_CALENDER`/`calendar_events` (events + tasks), `session_templates` (with assessments), `attendance`, `LearnerAssessments` (scores/percentage), `activity_logs`, `media_library`, `roles`, `notifications`.

**Data-availability matrix (enterprise requirements):**

| Requirement | Status | Source |
|---|---|---|
| Total Companies / Users / Coaches / Learners | ✅ | counts of `companies`, `staff`+`learners`, staff role=coach, `learners` |
| Total Sessions / Active Batches | ✅ | events (`type=event`), `batches` status=active |
| Total / Completed / Pending Tasks | ✅ | already built |
| **Active Courses** | 🟥 | **no Courses entity** — LMS was a proposal, not built. Options in §Decisions |
| Average Performance Score / Completion Rate | 🟨 | computed (built for tasks) |
| **Average Assessment Score** | ✅ | `LearnerAssessments.percentage` (aggregate) |
| **Attendance %** | ✅ | `attendance` collection (present/total) |
| Company Growth / Active Members / Sessions | 🟨 | `companies`, events, `company analytics` |
| Engagement % / Productivity | 🟨 | computed from tasks + attendance + assessments |
| Employee: assigned/completed/pending/overdue/completion% | ✅ | already built |
| Employee: **Attendance % / Assessment Score** | 🟨 | join `attendance` + `LearnerAssessments` by user |
| Top / Lowest Performers | 🟨 | rank doers (built) — add "lowest" (reverse) |
| Individual: Name/Dept/Company/Designation | ✅ | user doc |
| Individual: **Employee ID / Reporting Manager** | 🟥 | **fields do not exist** on user model |
| Individual: Batch / Quarter | 🟨 | via company→batch→quarter membership (indirect) |
| Assignment history: task/assigned-by/dates/status/priority/score | ✅ | already built |
| Assignment history: **Started / Approved dates** | 🟥 | not tracked (v1 decision — shown "—") |
| Assignment history: **Session Name / Assignment Name / Assessment Marks** | 🟨/🟥 | session assessments live in `LearnerAssessments` (per session/quiz), **not per task** — needs a separate "assessment history" view, cannot be a task-row column |
| Timeline: Created→Assigned→Accepted→Started→In Progress→Completed→**Reviewed→Approved** | 🟨/🟥 | reconstructable up to Completed from `activity_logs`; **Started/Reviewed/Approved not captured** |
| Department / Session / Batch analytics | 🟨 | `attendance`, events, `batches`, `LearnerAssessments` |
| Drill-down Company→Dept→Batch→Employee→Assignment | 🟨 | layered aggregation endpoints |
| Export PDF/Excel/CSV | ✅ | built |

## Deliverable 4 — Existing Dashboard Analysis
`Dashboard.jsx`: KPI tiles (role-gated), recharts Area/Pie, operational timeline. Patterns already reused in the built `ReportsDashboard.jsx`.

## Deliverable 5 — Existing Chart Analysis
recharts (Area/Bar/Pie/Line, `ResponsiveContainer`, themed tooltips, gradients, `var(--accent-*)`), plus `StackedReportPanel.jsx`. Donut = Pie with `innerRadius`. Horizontal bar = `layout="vertical"`. All 17 requested chart types are supported by the existing library — **no new chart dependency needed**.

## Deliverable 6 — Reusable Components List
Sidebar (config-driven), PrivateRoute, Navbar, `StatusSummaryCards`, `DateRangeFilter`, `StackedReportPanel`, `Button`, `Modal`, `NotificationModal`, recharts patterns, `exportTasksToCsv`, design tokens (`src/index.css`), lucide icons, framer-motion. Plus the **already-built** `ReportsDashboard`, `DoerReportDetails`, `reportApi.js`, `report_service.py` to extend.

## Deliverable 7 — Required APIs (new, additive, `/api/reports/*`)
Extend the existing reports router (all superadmin/admin-gated):
- `GET /reports/enterprise-overview` — org KPIs (companies, users, coaches, learners, sessions, batches, tasks, avg assessment, attendance, completion).
- `GET /reports/companies` — per-company analytics (growth, members, sessions, avg score, attendance, productivity).
- `GET /reports/companies/{id}` — single company drill-down.
- `GET /reports/learners` and `/reports/learners/{id}` — learner performance (assessment score, attendance, progress) + individual report.
- `GET /reports/departments` — already built (extend with attendance/assessment).
- `GET /reports/sessions` — session analytics (total/active/completed, attendance %, ratings).
- `GET /reports/batches` and `/reports/batches/{id}` — batch analytics.
- `GET /reports/assessments/trends` — assessment score trends.
- `GET /reports/attendance/trends` — attendance trends.
- `GET /reports/performers?order=top|bottom&limit=10` — best/lowest performers.
- Extend `/reports/export` with report-type param.
- Extend all with global filters: `company_id, batch_id, quarter_id, coach_id, department, period, status, priority`.

## Deliverable 8 — Required Database Changes
- **None mandatory** for v1 of the expansion (all reads over existing collections).
- **Recommended additive indexes:** `attendance.user_id`, `LearnerAssessments.user_id`/`company_id`, task-collection compound (already recommended), `staff.email`/`learners.email` unique.
- **Optional (only if you want those fields):** add `employee_id` and `reporting_manager_id` to the user model + a backfill migration (additive). Required to satisfy "Employee ID" and "Reporting Manager".
- **Optional (accurate timelines/approvals):** `task_status_history` collection + workflow `approved/rejected` states — previously declined for v1.

## Deliverable 9 — UI Flow
```
Sidebar ▸ Reports (superadmin + admin)
 └─ /admin/reports  (Executive Dashboard: global filters → KPI cards → tabbed analytics)
      ├─ Tabs: Overview | Companies | Employees | Learners | Departments | Sessions | Batches
      ├─ each tab: chart grid + ranked table (reuse patterns)
      ├─ click Company → /admin/reports/company/:id  (drill-down)
      ├─ click Employee/Learner → /admin/reports/:userId (individual — extends built page)
      └─ click Assignment row → Timeline drawer (built)
```

## Deliverable 10 — Data Flow Diagram
```
Filters (company/batch/quarter/dept/coach/date) ─► reportApi ─► /api/reports/* (gated)
     ► report_service: load users + fetch tasks/attendance/assessments/sessions
     ► in-memory aggregation (reuse task helpers) ► JSON (chart-ready) ► recharts/tables
Export ► /reports/export?type=&format= ► openpyxl/reportlab ► blob download
```

## Deliverable 11 — Report Architecture
Additive & namespaced (extends existing): new service modules `report_service_company.py` / `_learner.py` (or extend `report_service.py`), new endpoints on the existing `reports` router, new frontend tab components under `features/reports/` reusing built pages. No existing endpoint, workflow, auth, or UI component changes.

## Deliverable 12 — Performance Strategy
- Lazy-load each analytics tab (React.lazy) — module already lazy-loaded.
- Server: prefer Mongo aggregation pipelines for company/assessment/attendance rollups (large collections); cap with skip/limit + `total`; add the indexes in §8; cache hot org-wide responses via existing `TTLCache`.
- Frontend: debounce filters, memoize chart data, paginate/virtualize large tables, single fetch-orchestrator per tab to avoid re-render storms.

## Deliverable 13 — Security Strategy
- **Access: Super Admin + Admin** (this spec) — widen the built gate from `["superadmin"]` to `["superadmin","admin"]` on the Sidebar link, page guards, and every `/api/reports/*` endpoint. ⚠️ This changes the earlier "superadmin only" decision — confirm in §Decisions.
- Company-scoping: superadmin = all; admin = coaching-wide (org) per existing scope model. No PII beyond what admins already see. Read-only endpoints; no mutations.

## Deliverable 14 — Development Roadmap (builds on shipped module)
| Phase | Scope | Est. |
|---|---|---|
| **E0. Access + filters** | widen gate to admin; add global filter bar (company/batch/quarter/coach/dept) | 1–2 d |
| **E1. Enterprise overview** | org KPI endpoint + cards (companies/users/coaches/learners/sessions/batches/assessment/attendance) | 2 d |
| **E2. Company analytics** | per-company endpoints + tab + drill-down page (reuse company analytics) | 2–3 d |
| **E3. Learner analytics** | assessment + attendance per learner; individual learner report | 2–3 d |
| **E4. Department / Session / Batch** | analytics endpoints + tabs + charts | 3 d |
| **E5. Charts & performers** | remaining chart types, top/lowest performers, donut/area/stacked | 2–3 d |
| **E6. Drill-down + export** | layered drill-down wiring; export per report type | 2 d |
| **E7. Perf + hardening** | pipelines, indexes, caching, responsive/dark-mode QA, no-regression | 2 d |
| **(Optional) E8** | add Employee ID / Reporting Manager fields + backfill; status-history for Started/Approved | 2–3 d |

**Total ≈ 3–4 weeks** for the full enterprise expansion (on top of the ~built base).

## Deliverable 15 — Final Requirements & Decisions Needed
**Guardrails:** reuse existing APIs/components; new APIs only where data isn't already served; no change to existing business logic or UI language; additive & namespaced.

**Decisions that gate the build:**
1. **Access** — spec says Super Admin **+** Admin; earlier you chose superadmin-only. Confirm widening to `['superadmin','admin']`?
2. **Employee ID & Reporting Manager** — fields don't exist. (A) omit for v1 / (B) add fields + backfill migration?
3. **"Active Courses"** — no Courses entity. (A) omit / (B) map to active session templates or batches / (C) build the LMS first?
4. **Started / Reviewed / Approved dates & states** — not captured. (A) keep showing "—" (v1) / (B) add status-history + approval workflow (larger)?
5. **Assessment Marks in assignment history** — assessments are per session/quiz (`LearnerAssessments`), not per task. Show them in a separate **Assessment History** section rather than as task-row columns — confirm?
6. **Scope/pacing** — build the full enterprise module now (3–4 wk), or incrementally (approve phase-by-phase)?

---

## Decisions — RESOLVED (2026-07-01)

| # | Decision | Chosen |
|---|---|---|
| Access | superadmin+admin vs superadmin | **Super Admin + Admin** — gate widened to `['superadmin','admin']` everywhere |
| Employee ID / Reporting Manager | add vs omit | **Omit for v1** (no user-model change) |
| Active Courses | map/omit/build | **Map to active Session Templates** (labeled "Courses") |
| Started/Approved dates | keep/build | **Keep "—"** (v1) |
| Assessment Marks | column vs section | **Separate Assessment-History section** (not task columns) |
| Pacing | full vs incremental | **Incremental, phase-by-phase** (review between phases) |

**Build order:** E0 (access + filters) → E1 (enterprise overview) → E2 (company) → E3 (learner) → E4 (dept/session/batch) → E5 (charts/performers) → E6 (drill-down/export) → E7 (perf). Each phase delivered for review before the next.

*The previously-built base Reports module is unchanged except for the access-gate widening in E0.*

---

## Addendum D — "LMS-wise" reporting (analysis + critical finding)

A spec requests a third report level — **LMS-wise reporting** — with an LMS filter (Company → LMS → Department), an LMS dashboard (users/courses/completion/certificates/learning-hours), LMS charts, and an LMS performance table.

### D.1 🚨 Critical finding: there is no "LMS" entity in this system
Verified by code search: `lms` appears only as a **permission-module label** in `models/rbac.py` and inside GPT/assistant prompt text — **not** as a collection, model, or per-company platform. There is also **no `course`, `certificate`, or `learning_hours`** field anywhere. The `group` module added recently is **task groups** (member sets for task coordination), not learning.

Therefore, as literally specified, an "LMS filter listing LMS platforms associated with a company" and cards like **Total Courses / Assigned Courses / Completed Courses / Certificates Earned / Total Learning Hours** have **no data source**. Building them as-is would show fabricated or empty values.

### D.2 What the "learning" domain actually is here
The training/learning structure that DOES exist and is company-associated:
```
Company ─< Batch (training program/cohort) ─< Quarter ─< Session (calendar event, type=event, session_template)
                                                             ├─ attendance (present/absent)
                                                             └─ LearnerAssessments (percentage, passed)
```
The closest real analogue to "an LMS instance a company is enrolled in" is a **Batch** (a training program). A company can belong to multiple batches (`batches.companies[]`).

### D.3 Recommended mapping: **LMS = Batch (training program)**
Interpret "LMS-wise" as **Batch-wise** reporting. This reuses existing batch/session/assessment/attendance data, needs no new data model, and is fully backward-compatible.

**Filter hierarchy:** Company → **LMS (Batch)** → Department. When no company is selected the LMS dropdown lists all batches; when a company is selected it lists only that company's batches (`batches.companies[] contains company_id`) — exactly the requested cascading behavior.

### D.4 Data-availability under the Batch mapping
| Requested LMS metric | Status | Source |
|---|---|---|
| Total / Active / Inactive Users | 🟨 | batch companies' learners (`is_active`) |
| Total "Courses" | 🟨 | sessions (or session templates) in the batch |
| Assigned / Completed / In-Progress "Courses" | 🟨 | session completion via `company_session_progress` / event `status` |
| Completion Rate, Avg Score | 🟨/✅ | computed / `LearnerAssessments.percentage` |
| **Certificates Earned** | 🟥 | no certificate entity → omit or 0 |
| **Total Learning Hours** | 🟥 | not tracked → omit or "—" |
| Performance Index | 🟨 | computed (existing productivity formula) |
| Charts (completion/activity/enrollment/score dist./top users/depts/courses…) | 🟨 | sessions + assessments + attendance scoped to the batch |
| LMS table (name, company, users, completion %, avg score, last activity, status) | 🟨 | batch + scoped rollups (Learning Hours/Certificates columns omitted) |

### D.5 Reuse & new APIs (additive, `/api/reports/*`)
- Reuse: existing batch analytics (`/quarters/{id}/analytics`, company dashboard), `compute_*` helpers, `LearnerAssessments`, `attendance`.
- New: `GET /reports/lms` (list batches as "LMS" rows, optional `company_id` scope), `GET /reports/lms/{batch_id}` (LMS dashboard), `GET /reports/lms/{batch_id}/employees`. Extend `/reports/export` + filters with `batch_id` (LMS).

### D.6 UI plan (reuse existing)
- Add an **LMS dropdown** (reuse `FilterDropdown`) between Company and Department; cascades off the selected company; searchable.
- Selecting an LMS renders an **LMS panel** (reuse the `CompanyPanel` structure: KPI cards + charts + performance table) scoped to the batch.
- Drill-down: Overall → Company → LMS(Batch) → Department → Employee, inheriting filters via URL params. Export respects Company + LMS + Department + Date. Loading skeletons + empty state ("No LMS data").

### D.7 Decisions needed before building
1. **Mapping:** Adopt **LMS = Batch** (recommended, reuses data) — or define LMS as another entity (e.g., GPT project), or build a brand-new LMS/course module first (large)?
2. **Certificates & Learning Hours:** Omit for v1 (recommended) — or add new data capture (certificate issuance + time tracking; sizable backend work)?
3. **"Courses":** map to **sessions** (per-batch scheduled sessions) or **session templates**? (recommended: sessions.)

*No code written for LMS reporting yet — pending the mapping decision, since the literal "LMS" entity does not exist in the current data model.*

---

## Addendum C — Company → Employee BI drill-down (E2 + E3 detailed design)

A fourth spec ("Sparsh Magic LMS Enterprise Reports — Company → Employee → Complete Analytics") requests the **drill-down BI experience**: Reports → All Companies → Select Company → Company Dashboard → Select Employee → Complete Employee Report → Assignment/Assessment/Attendance/Timeline. This is exactly roadmap phases **E2 (Company)** and **E3 (Employee)**. This addendum is the pre-code design for those two phases.

### C.1 Requested deliverables → where covered
Project/API/DB analysis → §1–§4 + [ADMIN_REPORTS_MODULE_ANALYSIS.md](ADMIN_REPORTS_MODULE_ANALYSIS.md) + [LMS_ANALYSIS_AND_IMPLEMENTATION_REPORT.md](LMS_ANALYSIS_AND_IMPLEMENTATION_REPORT.md). Report architecture/UI-flow/data-flow/perf/security → §9–§13. Required APIs/DB → C.4/C.5. Phase plan → E2/E3 in §14.

### C.2 Existing data flows (grounded)
- **Company:** `companies` ← `batches.companies[]` ← sessions (`type=event`, `batch_id`) ← `attendance`(session) / `LearnerAssessments`(company_id) / `company_session_progress`(done_indices). Learners: `learners.company_id`.
- **Employee:** `staff`/`learners` doc → tasks where doer (`target_staff_id`) → `attendance`(user_id) → `LearnerAssessments`(user_id) → `activity_logs`(user).
- **Assignment (task):** `type=task` docs; assigned_by=`user_id`, doer=`target_staff_id`, `start/end/completed_at`, `workflow_status`, `priority`.
- **Assessment:** `LearnerAssessments{ user_id, company_id, percentage, passed, session ref }` (per-session quiz).
- **Attendance:** `attendance{ user_id, session_id, session_name, date, status(present/absent), type }`.

### C.3 Employee-report field availability (v1 = show "—" for missing)
| Field | Status | Source |
|---|---|---|
| Name, Company, Department, Status | ✅ | user doc |
| **Employee ID, Profile Photo** | 🟥 | not stored → initials avatar; ID omitted (decision) |
| Joining Date | 🟨 | `created_at` (proxy) |
| Batch / Quarter / Coach | 🟨 | indirect (company→batch→quarter; coach via session `coach_ids`) |
| Sessions total/completed, Attendance % | ✅ | `attendance` |
| Assignments assigned/completed/pending/overdue | ✅ | tasks (built) |
| Avg Assessment Score, Pass/Fail | ✅ | `LearnerAssessments.percentage` / `passed` |
| Productivity / Completion % | 🟨 | computed (built) |
| Assignment history: name/assigned-by/assigned/due/completed/priority/status/score | ✅ | tasks (built) |
| **Started / Submitted / Reviewed / Approved dates, Remarks** | 🟥 | not tracked → "—" |
| Assessment history: name/session/date/score/%/pass-fail | ✅ | `LearnerAssessments` |
| **Assessment Time Taken** | 🟥 | not stored → "—" |
| Attendance history: session/date/status | ✅ | `attendance` |
| **Check-In / Check-Out / Duration, Learning Hours** | 🟥 | not stored → "—" |
| Timeline (created→assigned→completed) | 🟨 | `activity_logs` + `created_at`/`completed_at` (no started/submitted/reviewed/approved) |

### C.4 Required APIs (additive, `/api/reports/*`, admin-gated)
- `GET /reports/companies?period&search&sort&skip&limit` → per-company rows (employees, sessions, assignments, attendance %, avg score, completion %, productivity).
- `GET /reports/companies/{id}` → company dashboard payload (KPIs + chart series: monthly progress, attendance, assignment completion, assessment trend, employee/department distribution, top/lowest performers, batch performance).
- `GET /reports/companies/{id}/employees?search&sort&skip&limit` → **employees of that company only** (lazy — not loaded until a company is selected, per the perf rule).
- `GET /reports/employees/{userId}` → employee info + learning summary + performance series.
- `GET /reports/employees/{userId}/assignments` → assignment history (built as doer history; reuse).
- `GET /reports/employees/{userId}/assessments` → assessment history (`LearnerAssessments`).
- `GET /reports/employees/{userId}/attendance` → attendance history.
- `GET /reports/employees/{userId}/timeline?task_id` → built.
- Export: extend `/reports/export?type=company|employee&id=&format=`.

### C.5 Required DB changes
None mandatory. Recommended additive indexes: `attendance.user_id`+`session_id`, `LearnerAssessments.user_id`+`company_id`, `learners.company_id`. (Employee ID / check-in-out / submitted-reviewed-approved would need new capture — deferred per v1 decisions.)

### C.6 Drill-down architecture & UI flow
```
/admin/reports  (Executive Overview — built)
  Global filter bar: Company ▾ → (on select) Employee ▾ + date/batch/quarter/dept/coach
  ├─ No company → org-wide overview (built)
  ├─ Company selected → Company Dashboard (KPIs + 10 charts + employee table)  [E2]
  │     click employee row ▼
  └─ /admin/reports/employee/:userId → Complete Employee Report               [E3]
        info + learning summary + assignment/assessment/attendance tabs + timeline + graphs
```
Context preserved via URL params (`?company=&employee=`) so drill-down never loses state. **Lazy:** employees/assessments/attendance fetched only on selection.

### C.7 Performance & security
Lazy per-selection loading (no bulk employee load); skip/limit + `total` on every list; Mongo aggregation for company/assessment/attendance rollups; memoized chart data; admin-gated (`superadmin`+`admin`), company-scoped. All read-only, additive.

**Status:** E2/E3 designed and ready. Build proceeds on approval, phase by phase (E2 first).
