# HRMS Module — Implementation Roadmap

> **Status:** AWAITING APPROVAL — no code will be written until this roadmap is signed off.
> **Target:** `sparsh2.0` ERP (FastAPI + MongoDB backend, React 19 + Vite frontend)
> **Sources of truth:** `HRMS_BACKEND_ANALYSIS.md`, `HRMS_FRONTEND_ANALYSIS.md` (provided)
> **Baseline:** current `HRMS_NEW` branch @ `458c929`. The previous HRMS implementation is fully deleted and will **not** be recovered or referenced.
> **Author's note:** everything below is grounded in a read of the actual `sparsh2.0` tree, not in the source app's stack. See §0 for why that matters a great deal.

---

## Table of Contents

- [§0 Pre-Roadmap Findings — read before approving](#0-pre-roadmap-findings--read-before-approving)
  - [0.1 The source app and this ERP share almost no infrastructure](#01-the-source-app-and-this-erp-share-almost-no-infrastructure)
  - [0.2 Role-model translation (highest design risk)](#02-role-model-translation-highest-design-risk)
  - [0.3 Decisions that need your approval](#03-decisions-that-need-your-approval)
  - [0.4 Documented gaps in the analysis docs themselves](#04-documented-gaps-in-the-analysis-docs-themselves)
  - [0.5 Housekeeping found in the baseline](#05-housekeeping-found-in-the-baseline)
- [§1 Architecture & Conventions the HRMS Will Follow](#1-architecture--conventions-the-hrms-will-follow)
- [§2 Standard Suites (defined once, run every phase)](#2-standard-suites-defined-once-run-every-phase)
- [§3 Phase Index](#3-phase-index)
- [Phases 1–15](#phase-1--foundation-module-scaffold-access-control--registry)
- [§4 Traceability Matrix](#4-traceability-matrix--analysis-doc--phase)
- [§5 Final Production-Readiness Gate](#5-final-production-readiness-gate)

---

## §0 Pre-Roadmap Findings — read before approving

### 0.1 The source app and this ERP share almost no infrastructure

Both analysis documents describe **FocusPrint ERP**: Next.js 14 App Router, Neon Postgres, raw SQL, HMAC cookie sessions, TanStack Query, SweetAlert2. `sparsh2.0` is none of those things. This is a **re-implementation against a specification**, not a port. Every "copy this verbatim" instruction in the analysis docs has to be re-read as "re-implement this behaviour".

| Concern | Source app (per analysis docs) | `sparsh2.0` (verified in tree) | Consequence |
|---|---|---|---|
| Backend runtime | Next.js route handlers `src/app/api/**/route.ts` | FastAPI `APIRouter` in `backend/app/routes/*.py`, mounted `/api` in `main.py` | All ~60 endpoints re-authored as FastAPI routes |
| Database | Neon Postgres, raw parameterised SQL, `scripts/schema.sql` | MongoDB via `motor`; collections + indexes provisioned idempotently at startup in `db/mongodb.py` (`_ensure_tpms_collections` pattern) | No SQL, no `schema.sql`. Documents, not rows. Index spec lives in the model file |
| Auth | HMAC-signed `fp_session` cookie, **plaintext passwords** | JWT Bearer (`python-jose`), **bcrypt** hashes, token in `localStorage`, `get_current_user` dependency | Source's #1 risk does not exist here and must not be reintroduced |
| Identity | one `users` table, join by `users.name` | two collections — `staff` (internal) and `learners` (client-side) — joined by `ObjectId` | **We key HRMS on `user_id` ObjectId, never on name.** This eliminates the source's documented "renaming a user orphans their leave history" bug by construction |
| Tenancy | none | `company_id` on every client-side user + per-company module toggles | HRMS must be company-scoped end to end |
| Server state | TanStack Query (`hrms-queries.ts`) | **No react-query anywhere.** House style = thin axios wrappers (`services/*Api.js`) + `useState`/`useEffect` | We will **not** add TanStack Query. Divergent from every other module and a new dependency |
| Feedback UI | SweetAlert2 | `NotificationContext` + `NotificationModal` + the `app-error` window event in `services/api.js` | Reuse existing |
| Styling | Tailwind `brand-*` palette, `#8C4319` copper | Tailwind 4 + CSS variables (`--bg-card`, `--text-main`, `--sidebar-active-bg`, …) with light/dark themes | HRMS adopts ERP theme tokens. The source's copper palette is **not** carried over |
| Module gating | `ENABLED_MODULES` env allow-list + `middleware.ts` | Per-company boolean on the company doc (`orm_enabled`, `tpms_enabled`, `delegation_enabled`) surfaced via `GET /users/me` | HRMS gets `hrms_enabled`, default **OFF**, following the TPMS opt-in precedent |
| Email / notify | Nodemailer + `hrms_email_outbox` | `services/notification_service.py` — in-app + email + WhatsApp + templates + delivery log | Strictly better. Reuse it; do not build a second outbox |
| Files | S3 + local + data-URL fallback, base64 in JSON | `services/s3_service.py` (boto3, signed URLs, multipart) | Reuse. Public forms still need a base64 ingest path (§0.3-C) |
| Payroll engine | TypeScript `src/lib/payroll` (pure, config-driven, `node:test`) | — | Re-implement in Python as a pure module with the same rule set + tests |
| Test harness | `node:test` | Established convention: `python -m app.<mod>.tests.test_phaseN_<name>`, self-contained, `check()` helper, `SystemExit(1)` on failure (see `app/assistant/tests/`) | **Zero new dependencies.** HRMS follows this exact convention |

### 0.2 Role-model translation (highest design risk)

The source's six roles do not exist here. This mapping is the backbone of every permission decision in the roadmap and is the thing most worth challenging before we start.

| Source HRMS role | Meaning in source | Proposed `sparsh2.0` equivalent | Notes |
|---|---|---|---|
| `Admin` | full system owner, `/settings` console | `superadmin` (staff) | Only role that reaches the HRMS admin console |
| `Boss` / `MD` | final requisition approver | client `governance_role == "MD"`, or `clientadmin` (which `client_rank()` already treats as MD) | Reuses the existing MD>HR>HOD>IMPLEMENTOR ladder in `auth_controller.py` |
| `HR` | recruitment operator | client `governance_role == "HR"` | Already a first-class rank |
| `Manager` | hiring manager; raises reqs, co-reviews assessments | client `governance_role == "HOD"` | HOD is the existing department-head rank |
| `Employee` / `User` | self-service only | client `governance_role == "IMPLEMENTOR"` / `clientuser` | Lowest rank |
| *(none)* | — | `admin` (staff) | Sparsh internal HR operator — cross-company read + support access |

Three deliberate corrections to the source model, each fixing a defect the analysis docs themselves call out:

1. **`canAccessHrms` is not reproduced.** The docs flag it as "a trap — it now means *is authenticated*" (Frontend §5, §14.4). We define `can_access_hrms(user)` as a genuine check: internal staff always, client-side users only when `company.hrms_enabled` is true.
2. **One authorization mechanism, not four.** The backend doc's Risk #13 is "four overlapping authorization mechanisms with three different admin sets". HRMS gets a single `app/utils/hrms_access.py` exposing `hrms_role(user)`, `can(user, capability)` and route dependencies. Every gate goes through it.
3. **The phantom `"MD"` string role is dropped.** Backend §7.3 notes nothing ever creates it. MD-ness comes from `governance_role`.

### 0.3 Decisions that need your approval

**(A) Holidays — ✅ DECIDED: separate `hrms_holidays` collection.**
The ERP already ships a holiday master: `holidays` collection, `models/holiday.py`, `routes/holiday.py` and the `/tasks/holiday` page under Task Management. The HRMS spec wants a paid-holiday calendar that payroll credits.

**Decision: Option A2 — a separate `hrms_holidays` collection.** The shared holiday module is not touched at all. Consequence: **Phase 12 requires zero shared-file changes**, and the `/tasks/holiday` regression risk drops to nil.

*Accepted tradeoff + mitigation.* Two calendars can drift, and payroll pays against the HRMS one. To keep that visible rather than silent, Phase 12 ships:
- a one-click **"Import from ERP holiday master"** action on the HRMS holiday screen (read-only copy of `holidays` rows for the year; HR reviews and confirms — never an automatic write), and
- a **divergence banner** listing dates present in one calendar but not the other, so a mismatch is surfaced at the point of use instead of discovered in a payslip.

Both are read-only against `holidays`. No writes, no schema change, no behaviour change for Task Management.

**(B) Employee master — build on `staff`/`learners`, do not clone them.**
Both docs name "no employee master" as the top gap. In `sparsh2.0` the user collections already carry `designation`, `department`, `reporting_manager`, `joining_date`, `emergency_mobile`. Proposal: an `hrms_employee_profiles` side-collection keyed by `user_id` (ObjectId) holding only HR-owned fields (`base_salary`, `gender`, `joined_on`, `resigned_on`, `employee_code`, statutory ids, bank details) with a service that composes user + profile into one `Employee` view. No duplication of identity, no rename-orphan class of bug.

**(C) Public (unauthenticated) candidate routes — genuinely new infrastructure.**
`/apply/:code`, `/assess/:code`, `/offer/:code`, `/onboard/:code` must work without a login. Today **every** FastAPI router requires `get_current_user`, and the whole React app sits behind `PrivateRoute`. This needs: a dedicated `hrms_public` router with **no** auth dependency, per-IP rate limiting, high-entropy access codes (≥128-bit via `secrets.token_urlsafe`, not the source's ~40-bit `Math.random()`), and React routes mounted outside `PrivateRoute`. Called out because it is the module's only internet-facing attack surface and it accepts PII (PAN/Aadhaar/bank).

**(D) Frontend test harness — ✅ DECIDED: documented manual test scripts.**
Backend follows the existing dependency-free convention (`python -m app.<mod>.tests.test_phaseN_*`). Frontend gets reproducible step-by-step test scripts per phase, in `docs/hrms/PHASE_<n>_TEST_SCRIPT.md`, matching the `docs/TPMS_TEST_PLAN.md` convention. **No new frontend dependencies.** Every S3 "Frontend" test dimension in this roadmap is delivered as a numbered manual script with explicit expected results, so a reviewer can re-run it without me.

**(E) Attendance scope — ✅ DECIDED: bounded scope derived from the payroll rules.**
Phase 13 implements exactly what Backend §12.2 specifies and documents the scope boundary explicitly in its phase report. See §0.4.

**(F) HRMS audience — ✅ DECIDED: client-company module (TPMS-style).**
A client company's HR team hires and pays *their own* staff, scoped by `company_id`; Sparsh internal staff (`superadmin`/`admin`) get cross-company admin and support visibility. This mirrors TPMS/ORM/Delegation exactly, so tenancy, the company toggle and the data-layer scoping all follow an established, proven pattern.

**Still open (no separate decision requested — proceeding as proposed unless you say otherwise): (B) employee master as a side-collection keyed on `user_id`, (C) the new public router, and the §0.2 role mapping.**

### 0.4 Documented gaps in the analysis docs themselves

Both documents carry an explicit revision note stating the **attendance content is stale and was deliberately not updated**. Backend §13 and Frontend §9.4 both say "Not found", while the revision notes admit `/api/hrms/attendance`, `/api/hrms/attendance/team`, `hrms_attendance` and `hrms_punch_segments` all exist and are undocumented.

**Impact:** the payroll engine consumes punch data — late-entry fines (09:10/09:15 thresholds), completed-hour overtime measured to the day's last punch-out, Sunday-work OT, and absence detection. Without an attendance contract, payroll cannot be built to spec.

**Recommendation:** Phase 13 defines a minimal, explicit attendance contract from the payroll rules stated in Backend §12.2 (which *are* fully documented) and implements exactly that — check-in/out, punch segments, IST minute-since-midnight normalisation, monthly summary. Phase 14 then consumes it. Any richer attendance behaviour from the un-documented source module is out of scope until you supply an attendance analysis doc. This is the single largest specification risk in the project and is called out per the Missing Requirements policy.

Secondary documented gaps I will fix rather than reproduce (each is named as a defect in the source docs):

| Gap | Source | Fix |
|---|---|---|
| Leave sends no notification/email/audit at any step | BE §10, §14; FE §6.14 | Wire into `notification_service` from day one (Phase 12) |
| `GET /payroll` mutates `hrms_leave_balances` | BE Risk #15 | Balances updated by an explicit `POST /payroll/runs`; GET is pure |
| No payroll run record — retroactive edits silently change paid months | BE Risk #16 | Persisted, lockable run (Phase 14) |
| `hrms_settings` accepts arbitrary keys; values steer money | BE Risk #17 | Typed allow-list with per-key validators (Phase 11) |
| `leave_type` free text; payroll's paid/unpaid depends on string match | BE §14 | Enum, validated server-side (Phase 12) |
| No leave overlap/duplicate detection, no balance check at apply | BE §8 | Both enforced at apply time (Phase 12) |
| Legacy dual status (`application_status` + `STATUS_6..12`) | BE Risk #7 | Single `application_status`. Legacy columns never created |
| Business errors return HTTP 200 `{success:false}` | BE §11, Risk #6 | Proper status codes (400/403/404/409/422) via `HTTPException`, matching ERP house style |
| PAN-or-Aadhaar & duplicate-candidate validated client-side only | BE §8 | Enforced server-side |
| `hrms_leaves` has no index | BE Risk #18 | Indexed at creation |
| `manage_all_assignments` granted but unread by any route | BE §7.3 | Either implemented or not offered |

### 0.5 Housekeeping found in the baseline

`backend/app/**/__pycache__/` still contains orphaned bytecode from the deleted implementation (`hrms.cpython-311.pyc`, `hrms_payroll_service.cpython-311.pyc`, `public_guard.cpython-311.pyc`, and 11 more). The source `.py` files are gone, so Python will not import them and they are harmless — but they are misleading during review. I have **not** read them (per your no-reuse rule) and propose deleting them in Phase 1. `.gitignore` already covers `__pycache__`, so this is a working-tree cleanup only.

---

## §1 Architecture & Conventions the HRMS Will Follow

Non-negotiable house rules, derived from reading TPMS/ORM/Tasks — the module must look like it was always here.

**Backend layout**
```
backend/app/
  models/hrms.py                 # collection names, enums, Pydantic models,
                                 # HRMS_INDEXES spec, seed data  (mirrors models/tpms.py)
  utils/hrms_access.py           # single authz surface (mirrors utils/tpms_access.py)
  routes/hrms.py                 # authenticated router,  prefix="/hrms"
  routes/hrms_public.py          # unauthenticated router, prefix="/hrms/public"
  services/hrms_*_service.py     # business logic, one file per domain
  services/hrms_payroll/         # pure rule engine: config.py, rules.py, engine.py,
                                 # adapter.py, types.py   (no I/O, no clock, no DB)
  services/hrms_*/tests/         # test_phaseN_*.py, house convention
```
- Collections + indexes declared as `HRMS_INDEXES` in `models/hrms.py`; provisioned by a new `_ensure_hrms_collections(db)` in `db/mongodb.py` — idempotent, failures logged and swallowed, never blocking startup. This is the *one* shared-file change required, and it exactly mirrors the two `_ensure_*` functions already there.
- Routers mounted in `main.py` alongside the existing ones (one line each).
- Router-wide company gate via `dependencies=[Depends(_hrms_company_gate)]`, mirroring `routes/tpms.py`.
- Errors: `HTTPException` with correct status codes. Never `{success:false}` on a 200.
- Every collection prefixed `hrms_`. No existing collection is written to except as approved in §0.3-A.

**Frontend layout**
```
frontend/src/
  features/hrms/
    access.js                    # mirrors features/tpms/access.js
    HrmsGate.jsx                 # + RequireHrms  (mirrors TpmsGate.jsx)
    recruitment/…  people/…  payroll/…  common/…
  services/hrmsApi.js            # authenticated wrappers
  services/hrmsPublicApi.js      # public wrappers (no token)
  pages/hrms/public/             # unauthenticated candidate pages
```
- Thin axios wrappers over the shared `services/api.js` instance. **No react-query.**
- Sidebar: one collapsible `HRMS` group with `visibleFn: canAccessHrms`, matching the TPMS entry exactly.
- Routes in `App.jsx`: `PrivateRoute` → `RequireHrms` → `Outlet` for the app; public candidate routes registered **outside** `PrivateRoute`.
- Theme: existing CSS variables only. Icons: `lucide-react`. Charts: `recharts` (already a dependency — the source app had no chart library and hand-rolled bars; we use the ERP's).
- Export: `xlsx` / `jspdf` (already dependencies) rather than hand-rolled CSV.

**Coding standards** — Clean Architecture (routes → services → models; no business logic in routes), SOLID, DRY, KISS, Pydantic models for every request/response, secure-by-default gating, structured logging on every write, no secrets in code.

---

## §2 Standard Suites (defined once, run every phase)

Defined here so each phase lists only its **deltas**. Repeating 15 identical checklists would be padding, not rigour.

### S1 — Standard Smoke Suite (every phase, must be 100% green)
1. `uvicorn main:app` starts clean; startup log shows Mongo connected + HRMS collections provisioned; **no new warnings**.
2. `npm run build` succeeds; `npm run lint` reports no new errors.
3. Browser console clean on: Login → Dashboard → Calendar → Tasks → TPMS → ORM → Reports → Settings → Profile.
4. Zero backend 5xx in the server log during the walkthrough.
5. `GET /` returns the API banner; `GET /api/users/me` returns the caller with `orm_enabled`/`tpms_enabled`/`delegation_enabled`/`hrms_enabled`.
6. Existing modules render and perform one real write each: **Task Management** (create task), **Calendar** (create event), **TPMS** (open dashboard + a form), **CRM/ORM** (open sheet), **Notifications** (bell loads).
7. Auth: login, token refresh on reload, logout, expired-token bounce to `/login`.
8. Authorization: superadmin / admin / clientadmin / clientuser each see the correct sidebar and are refused what they should be.
9. Navigation: no dead links; deep-link + hard refresh on every new route.
10. DB: no unexpected collections; no writes to non-`hrms_*` collections other than the approved §0.3-A field additions.

### S2 — Standard Regression Suite (before every new phase, diffed against previous phase)
1. `git diff --stat <prev-phase-tag>..HEAD` — every touched file outside `hrms*` is on the approved list, with a written reason.
2. Route inventory: `grep -c "@router" backend/app/routes/*.py` unchanged for all non-HRMS routers.
3. `App.jsx` route table diff — pre-existing routes byte-identical.
4. Shared components (`components/common`, `components/layout`) and shared utils (`utils/taskAccess.js`, `services/api.js`, `context/*`) — unchanged unless approved.
5. `auth_controller.py` unchanged (HRMS adds its own access util; it never edits shared auth).
6. Permission matrix re-verified for the 4 canonical roles across Tasks / TPMS / ORM.
7. Collection inventory diff — only new `hrms_*` collections appear.
8. Existing backend test harnesses (`app/assistant/tests/test_phase*.py`) still pass.

### S3 — Standard Test Dimensions (every feature, every phase)
Positive · Negative · Edge · Permission · Validation · API (status codes + payload shape) · Database (indexes, constraints, idempotency) · Frontend (render, states, interactions) · End-to-End.

### S4 — Definition of Done (a phase is not complete until all 13 pass)
Analyze → Design → Database → Backend → Frontend → API Integration → Validation → Unit Testing → Integration Testing → Smoke Testing (S1) → Regression Testing (S2) → Bug Fixing → Documentation.
Each phase closes with a **Phase Report** in `docs/hrms/PHASE_<n>_REPORT.md`: what shipped, tests run + results, deviations, issues found and fixed (per the Missing Requirements policy), and residual risk.

---

## §3 Phase Index

| # | Phase | Delivers | Depends on |
|---|---|---|---|
| 1 | Foundation | Module scaffold, access control, collection registry, shell nav, audit/notify adapters | — |
| 2 | Employee Master | Employee profiles, Departments, Designations masters | 1 |
| 3 | Requisitions + JD | Raise → HR review → MD approval, JD co-approved | 1, 2 |
| 4 | Postings + Public Apply | Per-platform links, public intake infrastructure | 3 |
| 5 | Candidates + Screening | Pipeline, triage, journey timeline | 4 |
| 6 | Assessments | Send + dual review + public assess page | 5 |
| 7 | Interviews | Schedule, scorecard, `.ics`, assessment gating | 6 |
| 8 | Offers | Letter editor, public accept/decline, PDF | 7 |
| 9 | Onboarding | Pre-onboarding, checklist, Employee ID → employee master, req closure | 8, 2 |
| 10 | Dashboard + Reports | Recruitment analytics + exports | 9 |
| 11 | HRMS Settings & RBAC | Typed settings, permission matrix console | 1 |
| 12 | Holidays + Leave | Paid-holiday calendar, leave apply/approve + notifications | 11, 2 |
| 13 | Attendance | Check-in/out, punch segments, monthly summary | 12 |
| 14 | Payroll + Slips | Pure rule engine, persisted runs, payslips | 13 |
| 15 | Hardening | E2E, security, performance, production readiness | all |

---

## Phase 1 — Foundation: module scaffold, access control & registry

### Objectives
Stand up the HRMS skeleton so every later phase plugs in without touching shared files again. No business features — this phase exists so that Phases 2–15 have **zero** shared-file changes.

### Features
- HRMS appears in the sidebar for entitled users and nowhere else.
- `/hrms` resolves to a role-appropriate landing shell.
- Per-company `hrms_enabled` toggle on the Company Details page (mirrors the TPMS toggle).
- A single authorization surface every later gate calls.

### Backend Tasks
- `models/hrms.py` — collection name constants, `HRMS_INDEXES` (empty-but-live registry), shared enums, base Pydantic types, ID-generator helpers (`HR-REQ-YYYY-NNN`, `CAN-NNN`, `JD-YYYY-NNN`, `INT/OFR/ONB/ASM/EMP`) using an atomic `findAndModify` counter — **not** the source's row-scan (fixes BE Risk #12 race).
- `utils/hrms_access.py` — `hrms_role(user)`, `can(user, capability)`, `ensure_hrms_enabled(user, company_id)`, `hrms_enabled_company_ids()`, `require_hrms(...)` dependencies. Mirrors `utils/tpms_access.py`.
- `services/hrms_audit_service.py` — `audit(actor, action, entity, entity_id, detail)`, fire-and-forget, never raises.
- `services/hrms_notify_service.py` — thin adapter over the existing `notification_service` (in-app + email + WhatsApp), so no second outbox is built.
- `routes/hrms.py` — router with company gate + a `GET /hrms/health` returning module status/capabilities for the caller.
- `db/mongodb.py` — add `_ensure_hrms_collections(db)` and call it from `connect_to_mongo`. *(Shared file; justification: the only sanctioned provisioning point, exactly matching the two functions already present.)*
- `main.py` — mount `hrms.router`. *(Shared file; one line, the sanctioned mount point.)*
- `models/company.py` — add `hrms_enabled: bool = False`. *(Shared file; additive, default off — identical to how `tpms_enabled` was added.)*
- `routes/user.py` — surface `hrms_enabled` on `GET /users/me`. *(Shared file; one line beside the existing three flags.)*
- Delete orphaned HRMS `__pycache__` bytecode (§0.5).

### Frontend Tasks
- `features/hrms/access.js` — `canAccessHrms`, `isHrmsAdmin`, `hrmsRole`, `hrmsHome`.
- `features/hrms/HrmsGate.jsx` + `RequireHrms`.
- `services/hrmsApi.js` — axios wrappers, starting with `getHrmsHealth`.
- `components/layout/Sidebar.jsx` — one `HRMS` group with `visibleFn: canAccessHrms`. *(Shared file; additive entry in the existing `links` array, same shape as TPMS.)*
- `App.jsx` — `/hrms` gate route + `/hrms/*` outlet shell. *(Shared file; additive routes only.)*
- `components/company/` — HRMS On/Off toggle on Company Details, beside the existing TPMS/ORM/Delegation toggles.
- `features/hrms/common/` — shared shell: page header, stat tile, status badge, empty/loading/error states, all on ERP theme tokens.

### Database Changes
- New: `hrms_audit_log` — indexes `(entity, entity_id)`, `(company_id, created_at DESC)`.
- New: `hrms_counters` — `_id` = sequence key, atomic ID generation.
- Modified: `companies` — `+ hrms_enabled: bool = False` *(additive, defaulted)*.

### APIs
| Method | Route | Auth | Purpose |
|---|---|---|---|
| GET | `/api/hrms/health` | authed + HRMS gate | module status + caller capability set |
| PATCH | `/api/companies/{id}` | superadmin/admin | now accepts `hrms_enabled` *(extends existing endpoint)* |

### Validation
`hrms_enabled` strictly boolean; only `superadmin`/`admin` may flip it; missing flag = OFF; every HRMS route 403s a client-side user of a disabled company; internal staff always pass the gate (data layer scopes them instead).

### Integration
Company toggle → `/users/me` → `AuthContext` → `canAccessHrms` → sidebar + route guard. Verified end to end in one pass.

### Test Cases
- **Positive** — enabled company user sees HRMS + reaches `/hrms`; superadmin sees it for all companies.
- **Negative** — disabled-company user: no sidebar entry, `/hrms` redirects, `GET /hrms/health` → 403 with actionable detail.
- **Edge** — company with the flag absent entirely; user with no `company_id`; toggle flipped mid-session (next `/me` reflects it).
- **Permission** — `clientuser` cannot flip the toggle (403).
- **Validation** — non-boolean `hrms_enabled` rejected 422.
- **API** — correct status codes; 403 body carries a human-readable `detail`.
- **Database** — restart twice: indexes idempotent, no duplicates; counter increments atomically under 100 concurrent calls, zero collisions.
- **Frontend** — gate redirects; sidebar group expands/collapses; collapsed-rail tooltip renders.
- **E2E** — superadmin enables HRMS for Company X → user of X logs in → sees and opens HRMS.

### Smoke Testing
S1 in full, plus: TPMS/ORM/Delegation toggles on Company Details still work and are unaffected by the new one.

### Regression Testing
S2 in full. Shared-file diffs limited to: `db/mongodb.py`, `main.py`, `models/company.py`, `routes/user.py`, `Sidebar.jsx`, `App.jsx`, company-details toggle component — each additive, each justified above.

### Completion Checklist
- [ ] All 13 S4 steps pass
- [ ] Shared-file diff reviewed line by line; every change additive and justified
- [ ] Collections + indexes provisioned idempotently (verified across 2 restarts)
- [ ] Zero regressions in Tasks / Calendar / TPMS / ORM / Reports
- [ ] Orphaned `__pycache__` removed
- [ ] `docs/hrms/PHASE_1_REPORT.md` + `docs/hrms/HRMS_ARCHITECTURE.md` written
- [ ] Git tag `hrms-phase-1`

---

## Phase 2 — Employee Master, Departments & Designations

### Objectives
Close the #1 gap in both analysis docs. Every later phase (leave, payroll, onboarding, reporting) keys off this, so it lands before any of them.

### Features
Employee directory (list/search/filter) · Employee profile (personal, job, salary, documents, statutory) · Department master CRUD · Designation master CRUD · Employment lifecycle (`joined_on` / `resigned_on` / status) · Reporting-manager hierarchy view.

### Backend Tasks
- `services/hrms_employee_service.py` — composes `staff`/`learners` + `hrms_employee_profiles` into one `Employee` view; create/update profile; resolve manager chain; company-scoped listing.
- Pydantic models: `EmployeeProfile`, `EmployeeView`, `Department`, `Designation`.
- Endpoints on `routes/hrms.py` (see APIs).
- Seed departments from existing distinct `users.department` values on first provision (insert-only, like `DEPARTMENT_SEED` in TPMS).
- Salary is HR-only: `base_salary` never leaves the API for a non-HR caller.

### Frontend Tasks
`features/hrms/people/` — `EmployeeDirectory.jsx` (search + department/designation/status filters, table + card views), `EmployeeProfile.jsx` (tabs: Personal · Job · Salary · Documents · Statutory), `DepartmentMaster.jsx`, `DesignationMaster.jsx`, `EmployeeFormModal.jsx`. Salary tab rendered only when `can(user,'employee.salary.read')`.

### Database Changes
- `hrms_employee_profiles` — unique `user_id`; indexes `(company_id, status)`, `(employee_code)` unique sparse, `(department_id)`.
- `hrms_departments` — unique `(company_id, name)`.
- `hrms_designations` — unique `(company_id, name)`.
- **No changes to `staff`/`learners`.** Identity stays where it is.

### APIs
`GET/POST /hrms/employees` · `GET/PATCH /hrms/employees/{user_id}` · `GET /hrms/employees/{user_id}/hierarchy` · `GET/POST /hrms/departments` · `PATCH/DELETE /hrms/departments/{id}` · `GET/POST /hrms/designations` · `PATCH/DELETE /hrms/designations/{id}`

### Validation
`base_salary` ≥ 0, numeric, required for payroll eligibility · `joined_on` ≤ `resigned_on` · `employee_code` unique per company · department/designation must exist and belong to the company · department delete blocked while referenced (409) · PAN/Aadhaar/IFSC format-checked when supplied · `user_id` must resolve to a real user in the caller's company.

### Integration
Reads users from `staff`/`learners` without writing them. Provides `get_employee(user_id)` — the single accessor Phases 9, 12, 13, 14 depend on.

### Test Cases
- **Positive** — create/read/update profile; list scoped to company; hierarchy resolves 3 levels.
- **Negative** — profile for a user outside the caller's company → 403; duplicate `employee_code` → 409; delete a department in use → 409.
- **Edge** — user with no profile yet (composed view returns user fields + nulls); resigned employee excluded from active lists but retained in history; circular reporting-manager chain detected and refused.
- **Permission** — HOD sees own department only; IMPLEMENTOR sees own profile only; salary hidden from non-HR; superadmin cross-company.
- **Validation** — negative salary 422; `joined_on` after `resigned_on` 422; malformed PAN 422.
- **Database** — unique indexes enforce; `user_id` uniqueness prevents duplicate profiles.
- **Frontend** — directory filters; profile tabs; salary tab absent for unauthorized; validation errors surface inline.
- **E2E** — HR creates a department → creates a designation → completes an employee profile → it appears correctly in the directory.

### Smoke Testing
S1, plus: `/admin/users` (User Management) and `/team` still list users identically — verified by comparing payloads before/after.

### Regression Testing
S2. **Critical check:** `staff` and `learners` documents are byte-identical before/after a full Phase-2 exercise (dump + diff). HRMS must not have written to them.

### Completion Checklist
- [ ] 13 S4 steps · [ ] user collections provably unwritten · [ ] salary access gated and tested · [ ] no regression in User Management / Team · [ ] `PHASE_2_REPORT.md` · [ ] tag `hrms-phase-2`

---

## Phase 3 — Requisitions (FMS) + Job Descriptions

### Objectives
Deliver the recruitment entry point: raise a requisition **with** its JD, drive the 4-state approval chain, co-approve the JD. Establishes the approval-dialog + notification pattern reused by Phases 6–9.

### Features
Raise requisition + JD in one form · 4-state machine `Pending HR Review → Pending MD Approval → Approved / Rejected` · HR review (forward/reject) · MD approval (approve with revised CTC / reject) · JD library (view/edit, no independent approval) · requisition list with filters + detail drawer · closing status · notifications + audit at every transition.

### Backend Tasks
`services/hrms_requisition_service.py` (create-with-JD atomically, state machine, transition guards) · `services/hrms_jd_service.py` · endpoints · notify HR on raise, Admin/MD on forward, creator on decision · audit every transition · **no deprecated standalone JD approve route** (source's `jd/approve` is documented as dead — not built).

### Frontend Tasks
`features/hrms/recruitment/` — `RequisitionList.jsx` (stat tiles, search + department/approval/status filters, table), `RequisitionDrawer.jsx` (stepper Raised→HR Review→MD Approval→JD Posted, stage-specific action bars, JD content card), `RequisitionFormModal.jsx` (requisition + JD sections), `ApprovalDialog.jsx` (reusable), `JdLibrary.jsx` (master/detail), `JdEditorModal.jsx`.

### Database Changes
`hrms_requisitions` — unique `request_no`; indexes `(company_id, approval_status)`, `(company_id, closing_status)`, `(created_by)`, `(department_id)`.
`hrms_job_descriptions` — unique `jd_no`; indexes `(request_no)`, `(company_id, status)`.

### APIs
`GET/POST/PATCH/DELETE /hrms/requisitions` · `POST /hrms/requisitions/{no}/approve` (`hr-approve|hr-reject|md-approve|md-reject`) · `POST /hrms/requisitions/{no}/close` · `GET/PATCH /hrms/jd` · `GET /hrms/jd/{jd_no}`

### Validation
Required: department, designation, experience, required date, assignee, qualification, skills · JD mandatory (responsibilities **or** ≥1 attachment) · vacancy ≥ 1 · CTC numeric ≥ 0 · required date not in the past · **transition guards** (HR action only from `Pending HR Review`; MD action only from `Pending MD Approval`) · remark required on both rejects · revised CTC numeric when supplied · JD editable only when not Approved · closing status ∈ enum.

### Integration
Departments/designations from Phase 2 · notifications via Phase 1 adapter · audit feeds Phase 5's journey timeline · approved JD unlocks Phase 4 posting.

### Test Cases
- **Positive** — full chain raise → hr-approve → md-approve; JD flips to Approved; creator notified.
- **Negative** — md-approve while `Pending HR Review` → 409; reject without remark → 422; approve a non-existent req → 404; JD edit after approval → 409.
- **Edge** — concurrent double-approve (only one wins, second 409); requisition with vacancy 1 vs 10; JD with attachment but no responsibilities (valid) and neither (invalid).
- **Permission** — IMPLEMENTOR may raise but not HR-review; HOD cannot MD-approve; MD cannot HR-review; cross-company access 403.
- **Validation** — every required field individually omitted → 422 naming the field.
- **API** — 200/201/400/403/404/409/422 all correct; no `{success:false}` on 200.
- **Database** — `request_no`/`jd_no` unique under 50 concurrent creates; requisition + JD created atomically (failure leaves neither).
- **Frontend** — stepper reflects state; action bars appear only at the matching state and role; filters compose; drawer refreshes after approval.
- **E2E** — HOD raises → HR forwards → MD approves → JD Approved and visible in the library.

### Smoke Testing
S1, plus: notification bell shows the new HRMS notifications without breaking existing Task/TPMS notifications.

### Regression Testing
S2, plus: `notification_service` behaviour unchanged for Tasks/TPMS (send one of each and compare).

### Completion Checklist
- [ ] 13 S4 steps · [ ] state machine exhaustively tested (all 16 state×action pairs) · [ ] atomic create verified · [ ] notifications delivered · [ ] `PHASE_3_REPORT.md` · [ ] tag `hrms-phase-3`

---

## Phase 4 — Job Postings + Public Application Intake

### Objectives
Publish approved JDs and open the module's first public surface. This phase carries the project's main security work.

### Features
One posting row per platform, each with its own code and destination · `auto` (built-in form) vs `external` (poster's own URL) per platform · live status Pause/Live/Close · live application count · `requires_assessment` flag propagated to applicants · public job listing + application form · resume/photo/certificate upload.

### Backend Tasks
`services/hrms_posting_service.py` · `routes/hrms_public.py` — **new unauthenticated router**, mounted in `main.py` · `utils/hrms_public_guard.py` — per-IP + per-code rate limiting, code validation, PII-safe error messages · access codes via `secrets.token_urlsafe(16)` (≥128-bit, replacing the source's ~40-bit `Math.random()`) · base64 → `s3_service` ingest with size/MIME allow-list · application count via aggregation, never stored · notify HR + assigned recruiter on each application.

### Frontend Tasks
`features/hrms/recruitment/PostingList.jsx` (KPI row, search + status chips, card grid) · `CreatePostingModal.jsx` (JD select, platform multi-toggle, **per-platform link config with live code preview**) · `pages/hrms/public/ApplyPage.jsx` — mounted **outside** `PrivateRoute`; sections Personal / Education & Experience / Documents; declaration required; success screen with reference code; closed-posting banner.

### Database Changes
`hrms_job_postings` — unique `posting_code`; indexes `(jd_no)`, `(company_id, live_status)`, `(request_no)`.
`hrms_public_rate_limit` — TTL index on `expires_at` (auto-expiring, mirrors the existing `password_resets` TTL pattern).

### APIs
`GET/POST/PATCH/DELETE /hrms/postings` (authed) · `GET /hrms/public/apply/{code}` · `POST /hrms/public/apply/{code}` (both public)

### Validation
JD must be `Approved` (else 409) · ≥1 platform, all from the enum · `external` mode requires a full `http(s)://` URL · client-supplied code honoured only if it matches the pattern **and** is unique, else server mints one · expiry ≥ today.
Public: name required · email regex · phone required · declaration required · **server-side duplicate email+phone detection** (fixes BE §8 — source was client-only) · file size ≤ 15 MB, MIME allow-listed, ≤10 certificates · rate limit per IP and per posting code · closed/expired posting → 410.

### Integration
Consumes Phase 3 approved JDs · writes candidates read by Phase 5 · `requires_assessment` copied onto the candidate, gating Phases 6 and 7 · public router bypasses the auth dependency by design and is explicitly excluded from the company gate (the posting code carries the tenancy).

### Test Cases
- **Positive** — publish to 3 platforms → 3 codes; `auto` link opens the form; `external` link points out; application creates a candidate with `requires_assessment` copied.
- **Negative** — publish an unapproved JD → 409; `external` without URL → 422; apply to a paused/expired/closed posting → 410; apply with a bad code → 404.
- **Edge** — same email+phone applies twice (flagged, policy-enforced); 10 vs 11 certificates; 15 MB vs 15 MB + 1 byte; posting expiring mid-session; a platform re-pointed from `auto` to `external` while live.
- **Permission** — non-HR cannot publish/pause/delete; **public endpoints reachable with no token and expose no other data**.
- **Security** — rate limit trips and recovers; access code entropy verified; path traversal in `code` rejected; XSS payload in a form field stored inert and rendered escaped; no PII in error responses or logs.
- **API** — public routes return `{ok:…}` shapes with correct 200/404/410/422/429.
- **Database** — `posting_code` unique under concurrency; application count matches actual candidates; TTL prunes rate-limit rows.
- **Frontend** — public page renders logged-out; `PrivateRoute` does not intercept; success and closed states; upload progress and failure.
- **E2E** — approve JD → publish 2 platforms → copy `auto` link → apply in a logged-out browser → candidate appears for HR.

### Smoke Testing
S1, plus: public routes do **not** break `PrivateRoute` for any existing page; logging out mid-session on a public page does not error.

### Regression Testing
S2, plus: confirm no existing route now resolves publicly — enumerate every non-HRMS `/api/*` endpoint without a token and assert 401.

### Completion Checklist
- [ ] 13 S4 steps · [ ] **security review of the public surface signed off** · [ ] rate limiting verified under load · [ ] code entropy ≥128-bit · [ ] no auth regression on any existing route · [ ] `PHASE_4_REPORT.md` · [ ] tag `hrms-phase-4`

---

## Phase 5 — Candidates Pipeline, Screening & Journey

### Objectives
Give HR the working surface for applicants: pipeline views, bulk triage, and a per-candidate audit timeline.

### Features
Pipeline in 3 layouts (Kanban / List / Grid) over 8 stage groups · candidate profile drawer with stage change · manual candidate add · screening triage (shortlist/review/hold/duplicate/forward/reject, single + bulk) · duplicate detection · assessment-aware shortlist routing · candidate journey (stage rail + colour-coded timeline).

### Backend Tasks
`services/hrms_candidate_service.py` (single `application_status` — **no legacy `STATUS_6..12`**), row-scoped listing (HR/Admin all; HOD only own requisitions/interviews; others 403) · `hrms_screening_service.py` (bulk actions, `requires_assessment` → `Assessment Pending` routing, candidate emails) · `hrms_journey_service.py` (aggregates `hrms_audit_log` into typed events).

### Frontend Tasks
`recruitment/CandidatePipeline.jsx` (Pipeline/Journey toggle; Kanban/List/Grid switcher) · `CandidateDrawer.jsx` (stage select with optimistic update + rollback) · `CandidateCard.jsx`, `StageBadge.jsx` · `NewCandidateModal.jsx` · `ScreeningBoard.jsx` (stat cards, tabs, checkbox table, floating bulk bar, reject/forward modals) · `CandidateJourney.jsx` + `CandidateJourneyBoard.jsx`.

### Database Changes
`hrms_candidates` — unique `uk`; indexes `(company_id, application_status)`, `(request_no)`, `(posting_code)`, `(can_email)`, `(can_contact)`, `(assigned_recruiter)`.

### APIs
`GET/POST/PATCH/DELETE /hrms/candidates` · `POST /hrms/candidates/screen` · `GET /hrms/candidates/{uk}/journey`

### Validation
`application_status` ∈ the 18-value enum · transitions validated against the lifecycle (no Applied → Joined jump) · reject requires remarks · forward requires a valid in-company recipient · bulk action size capped · email/phone normalised before duplicate comparison · CV MIME/size checked.

### Integration
Candidates arrive from Phase 4 · journey reads Phase 1 audit + Phase 3 requisition audit · shortlist routing feeds Phase 6 · `requires_assessment` gate honoured in Phase 7.

### Test Cases
- **Positive** — bulk shortlist 10; stage change persists; journey shows every event in order.
- **Negative** — reject without remarks 422; invalid status 422; forward to an out-of-company user 403; screen a deleted candidate 404.
- **Edge** — 0 selected in bulk bar; 500-candidate pipeline (performance); candidate with no requisition; identical email different phone; stage change failing mid-flight (optimistic UI rolls back).
- **Permission** — HOD sees only own-requisition candidates; IMPLEMENTOR → 403; HR all in company; superadmin cross-company.
- **Validation** — every enum boundary.
- **Database** — `uk` unique under concurrency; indexes actually used (`explain()` shows no COLLSCAN on the pipeline query).
- **Frontend** — all 3 layouts over the same filters; drawer opens from each; optimistic rollback visible; bulk bar appears/clears.
- **E2E** — apply publicly → appears in "To screen" → bulk shortlist → moves to the right stage (assessment-aware) → journey records it.

### Smoke Testing
S1, plus: pipeline with 500 candidates renders < 2 s and does not freeze the tab.

### Regression Testing
S2. Confirm no HRMS write touches Task/TPMS collections.

### Completion Checklist
- [ ] 13 S4 steps · [ ] single-status model confirmed (no legacy columns anywhere) · [ ] row scoping tested per role · [ ] index usage verified by `explain()` · [ ] `PHASE_5_REPORT.md` · [ ] tag `hrms-phase-5`

---

## Phase 6 — Assessments (dual review) + public assess page

### Objectives
Pre-interview assessment with a two-reviewer sign-off (HR + hiring manager), and the candidate-facing submission page.

### Features
Send assessment · lifecycle `Assigned → In Progress (opened) → Submitted → Passed/Failed` · public assess page (marks Opened on first view) · dual review: both must Pass to advance · "To review by me" filter · auto-recommendation from score.

### Backend Tasks
`services/hrms_assessment_service.py` — send, open-tracking, submit, dual-review resolution (reviewer fills the **HR slot** unless they are the requisition raiser → **manager slot**), final outcome (`Assessment Passed` / `Assessment Failed`), notify the pending reviewer then both on outcome · public GET/POST on `hrms_public`.

### Frontend Tasks
`recruitment/AssessmentBoard.jsx` (4 stat tiles, status chips, card grid, decision chips) · `SendAssessmentModal.jsx` (candidate picker filtered to `requires_assessment` + assessment-stage only) · `ReviewAssessmentModal.jsx` (Pass/Fail pair, other reviewer's decision, score, remarks; read-only once Reviewed) · `pages/hrms/public/AssessPage.jsx`.

### Database Changes
`hrms_assessments` — unique `assessment_no`, unique `access_code`; indexes `(uk)`, `(company_id, status)`, `(request_no)`.

### APIs
`GET/POST/PATCH /hrms/assessments` · `GET /hrms/public/assess/{code}` · `POST /hrms/public/assess/{code}`

### Validation
`uk` + `title` required · `max_score` > 0 · decision ∈ {Pass, Fail} · review rejected unless the candidate has submitted (409 on `Sent`/`Opened`) · one decision per reviewer slot (re-submission updates, never duplicates) · public submit requires response **or** ≥1 attachment, ≤10 attachments · public submit 409 if already submitted · external link must be a valid URL.

### Integration
Candidate picker uses Phase 5 stages · outcome gates Phase 7 scheduling · manager slot resolved from the Phase 3 requisition raiser.

### Test Cases
- **Positive** — send → candidate opens (status → Opened, `opened_at` stamped) → submits → HR Pass + Manager Pass → `Assessment Passed`.
- **Negative** — review before submission 409; submit twice 409; invalid code 404; decision outside enum 422.
- **Edge** — requisition with no identifiable manager (HR decision alone finalises); HR Pass + Manager Fail → Failed; both reviewers are the same person; reviewer changes their mind before the other decides; candidate opens but never submits.
- **Permission** — IMPLEMENTOR cannot send or review; HOD reviews only own-requisition assessments; public page needs no auth and leaks nothing.
- **Security** — access code entropy; rate limiting on the public route.
- **API** — all status codes correct.
- **Database** — unique constraints; decision fields never duplicated.
- **Frontend** — "To review by me" count accurate; read-only after Reviewed; copy-link strip only when Sent/Opened.
- **E2E** — shortlist an assessment-required candidate → assessment auto-stage → send → candidate submits → dual review → `Assessment Passed`.

### Smoke Testing
S1, plus: both public pages (apply + assess) work logged-out in the same session.

### Regression Testing
S2, plus: Phase 4 public apply still works unchanged.

### Completion Checklist
- [ ] 13 S4 steps · [ ] dual-review matrix fully tested (4 combinations × manager-present/absent) · [ ] public surface security re-checked · [ ] `PHASE_6_REPORT.md` · [ ] tag `hrms-phase-6`

---

## Phase 7 — Interviews & Scorecard Evaluation

### Objectives
Schedule rounds, enforce the assessment gate, capture structured evaluations, and drive the pass-chain.

### Features
Schedule (Virtual/Offline) · day-grouped list · reschedule / complete / no-show / cancel · `.ics` calendar invite to candidate + interviewer · 6-competency scorecard (0–5) + decision + signature · `PASS_NEXT` advance map · MD-round decision restricted to MD/Admin · assessment gating on the candidate picker and server-side.

### Backend Tasks
`services/hrms_interview_service.py` — scheduling with the assessment gate, row-scoped listing (own interviews unless privileged or granted `view_all_assignments`), evaluation + `PASS_NEXT`, outcome emails · `.ics` builder (RFC-5545) as `services/hrms_ics.py`.

### Frontend Tasks
`recruitment/InterviewBoard.jsx` (stat cards, round/status filters, day-grouped cards) · `ScheduleInterviewModal.jsx` (candidate picker = schedulable only; Virtual→link / Offline→location) · `EvaluateInterviewModal.jsx` (6 star rows, remarks, decision, required typed signature; MD-round heading variant).

### Database Changes
`hrms_interviews` — unique `interview_no`; indexes `(uk)`, `(company_id, status)`, `(scheduled_at)`, `(interviewer)`.

### APIs
`GET/POST/PATCH/DELETE /hrms/interviews` · `POST /hrms/interviews/{no}/evaluate`

### Validation
Round ∈ enum · `scheduled_at` valid and (on create) not in the past · duration ≥ 15, step 15 · interviewer must be an in-company user · Virtual requires a meeting link, Offline a location · **assessment gate**: `requires_assessment` candidate must be `Assessment Passed` (409 otherwise) · scores integers 0–5 · decision ∈ {Pass, Fail, Hold} · **signature required** (source left it optional — BE §8 flags it; we require it) · MD-round evaluation requires MD/Admin · update/evaluate allowed only to HR/Admin or the assigned interviewer.

### Integration
Gated by Phase 6 · advances Phase 5 statuses · `Selected` unlocks Phase 8 · `.ics` reuses the ERP's email channel · reschedule resends the invite.

### Test Cases
- **Positive** — schedule → candidate + interviewer receive `.ics` → evaluate Pass → advances per `PASS_NEXT`.
- **Negative** — schedule an assessment-blocked candidate 409; evaluate a cancelled interview 409; MD round evaluated by HOD 403; past datetime 422.
- **Edge** — all 4 rounds × 3 outcomes (12 paths) verified against `PASS_NEXT`; reschedule across a month boundary; two interviews same candidate same slot; interviewer deactivated after scheduling; every score 0 vs every score 5.
- **Permission** — non-assigned non-HR cannot update/evaluate; `view_all_assignments` grant widens the list correctly.
- **Validation** — Virtual without link 422; Offline without location 422; score 6 → 422; missing signature 422.
- **Database** — `interview_no` unique; `(scheduled_at)` index used by the day feed.
- **Frontend** — day grouping (Today/Tomorrow/weekday/Unscheduled); star widget click-again-resets; MD heading swaps.
- **E2E** — `Assessment Passed` → schedule HR round → Pass → Technical → Pass → MD → MD approves → `Selected`.

### Smoke Testing
S1, plus: `.ics` opens correctly in Outlook/Google Calendar; existing ERP calendar events unaffected.

### Regression Testing
S2, plus: `/calendar` and TPMS calendar render unchanged — HRMS interviews must **not** leak into the ERP calendar collections unless explicitly designed to (they do not, in this roadmap).

### Completion Checklist
- [ ] 13 S4 steps · [ ] all 12 round×outcome paths tested · [ ] assessment gate enforced on both client and server · [ ] `.ics` validated in 2 clients · [ ] `PHASE_7_REPORT.md` · [ ] tag `hrms-phase-7`

---

## Phase 8 — Offers & Public Offer Page

### Objectives
Issue, version and track offer letters; let candidates accept or decline on a public, printable page.

### Features
Create draft (CTC pre-filled from JD → requisition → candidate expectation) · letter editor with versioned history · formal letterhead preview · send / revoke / delete-draft · public offer page with accept (typed signature) / decline (optional note) · print-to-PDF.

### Backend Tasks
`services/hrms_offer_service.py` — create (blocks a second active offer), save/send/revoke with version history, public accept/decline, requisition-closure reconciliation on accept · default signature resolved from HRMS settings.

### Frontend Tasks
`recruitment/OfferBoard.jsx` (3 stat tiles, status filters, card grid) · `CreateOfferModal.jsx` (candidate = Selected only, CTC + joining date mandatory) · `OfferEditorModal.jsx` + `OfferPaper.jsx` (shared letterhead, `@media print`) · `pages/hrms/public/OfferPage.jsx` (reuses `OfferPaper`).

### Database Changes
`hrms_offers` — unique `offer_no`, unique `access_code`; indexes `(uk)`, `(company_id, status)`.

### APIs
`GET/POST/PATCH/DELETE /hrms/offers` · `GET /hrms/public/offer/{code}` · `POST /hrms/public/offer/{code}`

### Validation
Candidate must be `Selected` · no existing Draft/Sent/Accepted offer (409) · CTC and joining date **both mandatory**, CTC numeric > 0, joining date ≥ today · authorised signature required to Send · editable only while Draft (409 otherwise) · Draft hidden from the public route (404) · accept requires a signature · public action rejected unless status is `Sent` (409) · delete only Draft.

### Integration
Consumes Phase 7 `Selected` · accept updates Phase 5 status and triggers requisition closure reconciliation (Phase 3) · `Offer Accepted` unlocks Phase 9 · signature from Phase 11 settings (fallback until then).

### Test Cases
- **Positive** — draft → edit → send → candidate accepts → status `Offer Accepted`, requisition reconciled.
- **Negative** — second offer for the same candidate 409; edit after send 409; accept without signature 422; accept twice 409; open a Draft publicly 404.
- **Edge** — decline with and without a note; revoke after send; version history across 3 edits; joining date exactly today; candidate accepts after the requisition is already filled.
- **Permission** — only HR/Admin create/send/revoke; public page needs no auth.
- **Security** — access code entropy; rate limiting; no candidate PII beyond their own offer.
- **API** — 200/201/403/404/409/422 correct.
- **Database** — one active offer per candidate enforced; history append-only.
- **Frontend** — preview matches print output; print CSS hides chrome; accept/decline states.
- **E2E** — Selected → create + send → candidate accepts on a logged-out browser → HR sees Accepted → requisition closes when vacancies fill.

### Smoke Testing
S1, plus: print-to-PDF produces a clean single-document letter in Chrome and Edge.

### Regression Testing
S2, plus: all three public pages coexist.

### Completion Checklist
- [ ] 13 S4 steps · [ ] version history verified · [ ] closure reconciliation correct at vacancy boundaries · [ ] print output reviewed · [ ] `PHASE_8_REPORT.md` · [ ] tag `hrms-phase-8`

---

## Phase 9 — Onboarding & Employee Creation

### Objectives
Collect pre-onboarding data, run the joining checklist, mint the Employee ID, and — the key improvement over the source — **create a real employee record**.

### Features
Start onboarding · public pre-onboarding form (identity, bank, emergency, references, documents, asset requirements) · KYC document management + verification · background-verification tracking · joining details · 12-item checklist · Employee ID generation (`EMP-YYYY-NNN`) · **automatic employee-profile creation in the Phase 2 master** · requisition auto-closure.

### Backend Tasks
`services/hrms_onboarding_service.py` — start, public submit, checklist/bg/verify-docs/details/documents actions, `generate-id` (mints the ID, creates/links the `hrms_employee_profiles` record, sets status `Joined`, reconciles closure), full-checklist → `Employee Created`.

### Frontend Tasks
`recruitment/OnboardingBoard.jsx` (master/detail, progress bars) · `OnboardingDetail.jsx` (Pre-Onboarding · KYC & Documents · Background Verification · Joining Details · checklist grid) · `StartOnboardingModal.jsx` · `pages/hrms/public/OnboardPage.jsx`.

### Database Changes
`hrms_onboarding` — unique `onb_no`, unique `access_code`, unique `employee_id` (sparse); indexes `(uk)`, `(company_id, status)`.
Writes into `hrms_employee_profiles` (Phase 2) on ID generation.

### APIs
`GET/POST/PATCH /hrms/onboarding` · `POST /hrms/onboarding/{no}/generate-id` · `GET /hrms/public/onboard/{code}` · `POST /hrms/public/onboard/{code}`

### Validation
Candidate ∈ {Offer Accepted, Selected}; no existing onboarding (409) · **PAN or Aadhaar required server-side** (fixes BE §8 — source enforced this client-side only) · PAN and IFSC format-checked; Aadhaar 12 digits · bank account numeric · ≤15 documents, size/MIME enforced · `bg_verification` ∈ enum · Employee ID generated **once** (409 on repeat) and only when pre-onboarding is submitted · joining date required before ID generation · public submit 409 if already submitted.

### Integration
Consumes Phase 8 `Offer Accepted` · **writes the Phase 2 employee master** — the link that makes Phases 12–14 possible for new joiners · reconciles Phase 3 closure · audit feeds Phase 5 journey.

### Test Cases
- **Positive** — start → candidate submits → HR verifies docs → sets joining details → generates ID → employee profile exists and is complete → checklist complete → `Employee Created`.
- **Negative** — neither PAN nor Aadhaar → 422; generate ID twice → 409; onboard a non-accepted candidate → 409; 16 documents → 422.
- **Edge** — Employee ID sequence rolls over the year boundary; concurrent ID generation (only one wins); candidate submits after HR already uploaded KYC; onboarding for the last vacancy triggers requisition `Hired`; malformed PAN/IFSC variants.
- **Permission** — only HR/Admin act; public form needs no auth.
- **Validation** — every identity-format rule.
- **Database** — `employee_id` unique; the created employee profile is linked by `user_id` where a user exists, and flagged pending-user-creation where none does (documented behaviour).
- **Frontend** — progress bar accuracy; checklist toggles persist; upload/remove; verification chip gating.
- **E2E** — full lifecycle, requisition → hired employee visible in the Phase 2 directory.

### Smoke Testing
S1, plus: the new employee appears in the Employee Directory with correct department/designation/joining date.

### Regression Testing
S2, plus: Phase 2 directory and hierarchy still correct after bulk onboarding.

### Completion Checklist
- [x] 13 S4 steps · [x] **recruitment → employee-master link verified end to end** · [x] ID generation race-tested (compare-and-swap claim) · [x] server-side PAN/Aadhaar enforced · [x] `PHASE_9_REPORT.md` · [ ] tag `hrms-phase-9`

> **✅ DELIVERED** — see [PHASE_9_REPORT.md](hrms/PHASE_9_REPORT.md). 1612/1612 checks across 19 suites.
>
> **Two deviations from this plan, both deliberate and both explained in the report:**
> 1. **`ONBOARDABLE_STATUSES` is `{Offer Accepted}` only, not `{Offer Accepted, Selected}`.** The lifecycle graph has no `Selected → Pre-Onboarding` edge, so a Selected onboarding could never reach the matching stage — and onboarding collects PAN/Aadhaar/bank details, which should not be gathered from someone who may still say no.
> 2. **The employee record is created with NO `user_id` at all** (absent, not null; `uniq_user` is now sparse), rather than HRMS creating a `learners` login. This preserves the "HRMS never writes to identity collections" invariant asserted since Phase 1. `POST /hrms/employees/link/{code}` attaches the account later. The alternative is offered for approval in the report.
>
> `OnboardingDetail.jsx` and `StartOnboardingModal.jsx` ship as components **inside** `OnboardingBoard.jsx`, matching the Phase 8 `OfferBoard` idiom rather than the file split sketched here.

---

## Phase 10 — Recruitment Dashboard & Reports

### Objectives
Read-only analytics over everything Phases 3–9 produced. No new writes.

### Features
8 KPI cards (each deep-linking) · hiring funnel with per-stage conversion · positions/vacancy summary · source-wise and department-wise breakdowns · reports page: headline KPIs, funnel, "where candidates stand" buckets, best channels, offer outcomes · detailed tabbed tables (Candidates / Requirements / Interviews / Offers) with search and per-tab export.

### Backend Tasks
`services/hrms_analytics_service.py` — **server-side aggregation pipelines** (the source computed everything in the browser and both docs flag the missing reporting backend). Company-scoped, role-scoped, index-backed. Endpoints for dashboard, funnel, breakdowns, and a paginated report feed.

### Frontend Tasks
`features/hrms/dashboard/RecruitmentDashboard.jsx` · `features/hrms/reports/RecruitmentReports.jsx` · shared `KpiCard`, `FunnelChart`, `BarList`, `MiniStat` — built on **recharts** (an existing dependency) rather than hand-rolled bars · export via `xlsx`/`jspdf` (existing dependencies).

### Database Changes
None. Adds supporting indexes only if `explain()` shows a scan.

### APIs
`GET /hrms/analytics/dashboard` · `GET /hrms/analytics/funnel` · `GET /hrms/analytics/breakdown?by=source|department` · `GET /hrms/reports/{entity}?page=&search=` · `GET /hrms/reports/{entity}/export`

### Validation
Date ranges valid and bounded · `entity` ∈ enum · pagination bounded (max page size) · export row cap with an explicit message when truncated (never silent) · every aggregation company- and role-scoped.

### Integration
Reads Phases 3–9 collections. Effective-rank logic (status ∪ offer evidence ∪ interview evidence) implemented server-side, matching FE §6.1.

### Test Cases
- **Positive** — KPIs match hand-counted fixtures; funnel percentages correct; exports open in Excel.
- **Negative** — invalid date range 422; unknown entity 404; export beyond cap returns a clear message.
- **Edge** — zero data (all KPIs 0, no divide-by-zero in conversion %); one candidate at every stage; candidate whose status and evidence disagree (effective rank wins); 10k candidates (performance).
- **Permission** — HOD sees own-scope numbers only; cross-company isolation proven with two seeded companies.
- **Database** — every aggregation index-backed; dashboard < 500 ms at 10k candidates.
- **Frontend** — loading skeletons, empty states, chart responsiveness, light/dark themes.
- **E2E** — run a full recruitment cycle → every KPI and funnel stage moves by exactly the expected amount.

### Smoke Testing
S1, plus: existing `/admin/reports` (ERP Reports) unaffected; recharts bundle size checked (lazy-loaded like `ReportsDashboard` already is).

### Regression Testing
S2, plus: bundle-size delta recorded; no shared chart component modified.

### Completion Checklist
- [x] 13 S4 steps · [x] figures reconciled against hand-counted fixtures · [x] cross-company isolation proven · [ ] performance target met (indexes in place; not benchmarked at 10k) · [x] `PHASE_10_REPORT.md` · [ ] tag `hrms-phase-10`

> **✅ DELIVERED** — see [PHASE_10_REPORT.md](hrms/PHASE_10_REPORT.md). 1876/1876 checks across 21 suites.
>
> **Three deviations from this plan, all deliberate and all explained in the report:**
> 1. **CSS bars, not recharts.** The funnel is eight horizontal bars with server-computed percentages; recharts adds no interaction worth ~100 kB. Bundle delta came in at **+1.9 kB**. With no chart library there is nothing to lazy-load, so the pages are imported eagerly like every other HRMS screen.
> 2. **Exports render server-side, and do NOT reuse `routes/reports.py`.** Rows here are already role-scoped and paginated, so rebuilding a file in the browser would ship rows the API withheld. But importing that module's private `_export_*` helpers would couple HRMS to a file outside its scope — ~40 lines are duplicated deliberately.
> 3. **`report.export` is a third capability**, separate from `report.read`. A hiring manager gets the tables and not the download.
>
> **Effective rank** is implemented as declared (`STAGE_RANK` + evidence floors), with two refinements: a **Draft** offer confers no rank, and `Offer Declined` still ranks at the offer stage.
>
> ⚠️ **Carried forward:** Phase 9's `uniq_user` sparse-index fix was found NOT to have applied in production (Atlas raises error 86, the code matched only 85). Fixed and tested here, but **not yet run against the live database** — see PHASE_10_REPORT §3 Finding #1.

---

## Phase 11 — HRMS Settings & RBAC Console

### Objectives
Own the configuration and permission model that Phases 12–14 depend on. Deliberately placed **before** the HR-ops slices, per FE §14.3.

### Features
Typed settings (payroll policy numbers, professional tax, default signature, working hours, leave entitlement) · permission matrix console (capability × role) · per-user explicit grants · settings audit trail.

### Backend Tasks
`services/hrms_settings_service.py` — **typed key allow-list with per-key validators and type coercion** (fixes BE Risk #17: the source accepted any key and its values steer money) · `services/hrms_rbac_service.py` — capability registry, role defaults, per-user overrides, effective-permission resolution · every settings write audited with before/after values.

### Frontend Tasks
`features/hrms/settings/HrmsSettings.jsx` (tabs: General · Payroll Policy · Leave Policy · Permissions) · `PermissionMatrix.jsx` (capability × role grid with per-user override drawer) · `SettingCard.jsx` with typed inputs and inline validation.

### Database Changes
`hrms_settings` — unique `(company_id, key)`.
`hrms_permissions` — unique `(company_id, user_id, capability)`; index `(company_id, capability)`.

### APIs
`GET/PUT /hrms/settings` · `GET /hrms/settings/schema` · `GET /hrms/permissions/capabilities` · `GET/PUT /hrms/permissions/roles` · `GET/PUT /hrms/permissions/users/{user_id}`

### Validation
Unknown key → 400 (**allow-list, no free keys**) · each key validated against its declared type and range (e.g. `pt_amount` 0–5000; `paid_leaves_per_year` 0–60; `late_grace_minutes` 0–120) · booleans strictly boolean · signature must be PNG within size limits · capability ∈ registry · role ∈ mapped roles · **an admin cannot remove their own admin capability** (lockout guard) · dangerous flags (e.g. absence detection) require an explicit confirmation field.

### Integration
Every gate in Phases 1–10 is refactored to resolve through `can(user, capability)` — the single-mechanism promise from §0.2. Phases 12–14 read policy values from here rather than hardcoding.

### Test Cases
- **Positive** — set/read every allow-listed key; grant/revoke a capability and see it take effect immediately.
- **Negative** — unknown key 400; out-of-range value 422; wrong type 422; non-admin write 403; self-lockout attempt 409.
- **Edge** — capability granted then role changed (effective permission recomputed); two admins editing concurrently (last-write-wins with an audit trail); company with no settings (documented defaults apply); dangerous flag toggled without confirmation (refused).
- **Permission** — only HRMS admin reaches the console; cross-company writes 403.
- **Validation** — every key's boundary values.
- **Database** — uniqueness; audit records before/after.
- **Frontend** — matrix renders and saves; typed inputs reject bad values before submit; override drawer.
- **E2E** — grant a HOD an extra capability → they can perform the action → revoke → 403.

### Smoke Testing
S1, plus: **every Phase 1–10 permission test re-run** against the refactored `can()` — this is a cross-cutting refactor and is the phase's main risk.

### Regression Testing
S2, plus: full permission regression across all prior phases (the S3 permission dimension re-executed for Phases 1–10).

### Completion Checklist
- [ ] 13 S4 steps · [ ] every prior-phase gate migrated to `can()` and re-tested · [ ] allow-list rejects unknown keys · [ ] lockout guard verified · [ ] `PHASE_11_REPORT.md` + `docs/hrms/HRMS_PERMISSIONS.md` · [ ] tag `hrms-phase-11`

---

## Phase 12 — Holidays & Leave Management

### Objectives
Deliver the HR-ops foundation payroll depends on — and close the source's sharpest documented gap (leave decisions were invisible: no notification, no email, no audit).

### Features
Paid-holiday calendar with year navigation, presets, marked/paid counts · **import-from-ERP-master action + divergence banner** (§0.3-A mitigation) · leave application (single day / range / half day) · my-leave history · HR approval queue with remarks · leave balance ledger with real-time entitlement · **notifications and audit on every leave transition**.

### Backend Tasks
- `services/hrms_holiday_service.py` — CRUD over the **separate `hrms_holidays` collection** (§0.3-A). Plus two **read-only** helpers against the shared `holidays` collection: `preview_erp_holidays(year, company_id)` (candidates for import) and `holiday_divergence(year, company_id)` (dates in one calendar but not the other). Neither writes to `holidays`.
- `services/hrms_leave_service.py` — apply (self only, from the session — never the body), approve/reject, balance computation, **overlap detection**, **balance check at apply time** (both absent in the source), IST date discipline.
- Notification + audit on apply, approve, reject — the documented gap, fixed.

### Frontend Tasks
`features/hrms/people/LeaveApply.jsx` (type · duration toggle · date pickers · half-day · reason) · `MyLeaves.jsx` · `LeaveApprovalQueue.jsx` (status filter, inline reject remark) · `LeaveBalanceCard.jsx` · `HolidayCalendar.jsx` (year stepper, presets, marked/paid tiles, **Import from ERP master** button with a review-and-confirm step, **divergence banner**) · `HrmsDatePicker.jsx` — **string-based `"YYYY-MM-DD"`, never converted to a `Date`** (the source's deliberate timezone fix, preserved).

### Database Changes
`hrms_leaves` — indexes `(company_id, user_id, start_date)`, `(company_id, status)`, `(user_id, status)`. *(The source had **no index at all** — BE Risk #18.)*
`hrms_leave_balances` — unique `(company_id, user_id, year)`.
`hrms_holidays` — unique `(company_id, holiday_date)`; index `(company_id, year)`.
**No change to the shared `holidays` collection.**

### APIs
`GET/POST /hrms/leaves` · `PATCH /hrms/leaves/{id}` · `GET /hrms/leaves/balance` · `GET/POST/DELETE /hrms/holidays` · `GET /hrms/holidays/erp-preview?year=` *(read-only)* · `GET /hrms/holidays/divergence?year=` *(read-only)*

### Validation
`leave_type` ∈ **enum** (Casual/Sick/Earned/Unpaid) — not free text (fixes BE §14, where a typo silently became paid leave · reason required · range: `end_date` > `start_date`; single day: `end_date == start_date` · half-day only in single-day mode · **no back-dating for non-HR-admins**, re-checked server-side in IST · **overlap detection** against the user's existing Pending/Approved leaves (409) · **balance check at apply** with an explicit over-balance warning · applying only for yourself (`user_id` from the session) · remark required on reject (source made it optional despite the UI implying otherwise) · holiday date `YYYY-MM-DD`, name required, date not already taken.

### Integration
Employees from Phase 2 · policy values (entitlement) from Phase 11 · notifications via Phase 1 adapter · consumed by Phase 14 payroll · holidays feed the payroll paid-day credit.

### Test Cases
- **Positive** — apply → HR approves → applicant is notified → balance decrements.
- **Negative** — back-date as a normal user 422; overlapping request 409; reject without remark 422; approve someone else's as a non-HR 403; apply on behalf of another user (ignored — session wins).
- **Edge** — **timezone: a leave applied at 23:59 IST stores the correct date** (the source's fixed off-by-one bug — explicitly re-tested); range spanning a month and a year boundary; range including a Sunday and a holiday; half-day counting 0.5; leave exceeding annual balance; leave then cancelled/revised; Feb 29.
- **Permission** — IMPLEMENTOR applies + sees own only; HR sees all in company; cross-company 403.
- **Validation** — every date rule and the type enum.
- **Database** — indexes used by the queue query (`explain()`); balance uniqueness per user-year; **`hrms_holidays` uniqueness per company-date**.
- **Holiday divergence (§0.3-A mitigation)** — ERP master has a date HRMS lacks → banner flags it; HRMS has one the ERP lacks → banner flags it; both aligned → no banner; import previews correctly and writes **only** to `hrms_holidays`; **the shared `holidays` collection is byte-identical before and after an import** (dump + diff).
- **Frontend** — date picker never shifts a date across timezones (tested at TZ=UTC, IST, and US/Pacific); end-date disabled until start chosen; queue filters; import review-and-confirm step cannot be bypassed.
- **E2E** — mark a holiday → apply a range spanning it → approve → balance and paid/unpaid split are correct.

### Smoke Testing
S1, plus: `/tasks/holiday` behaves **exactly** as before — verified by payload diff, since this phase writes nothing to `holidays`.

### Regression Testing
S2, plus: `models/holiday.py` and `routes/holiday.py` unchanged (zero diff); `holidays` documents unchanged in shape and content.

### Completion Checklist
- [ ] 13 S4 steps · [ ] **timezone suite passes under 3 server timezones** · [ ] overlap + balance enforced at apply · [ ] notifications on all 3 transitions · [ ] **zero diff on shared holiday module; `holidays` collection provably unwritten** · [ ] divergence banner + import verified · [ ] `PHASE_12_REPORT.md` · [ ] tag `hrms-phase-12`

---

## Phase 13 — Attendance

> ⚠️ **Specification risk.** Both analysis documents explicitly state their attendance content is **stale and was not updated**, while admitting the source module exists and is substantial. This phase is therefore built to a contract **derived from the payroll rules in Backend §12.2** (which *are* fully specified), not from an attendance analysis doc. Scope is deliberately bounded to exactly what payroll consumes, plus the minimum usable UI. Anything beyond that awaits an attendance analysis document. See §0.4.

### Objectives
Provide the attendance data payroll requires, with an honest, bounded scope.

### Features
Check-in / check-out with punch segments · daily attendance record · monthly attendance summary per employee · team attendance view for HR/HOD · manual correction with approval · optional geofence validation (settings-driven) · absence marking.

### Backend Tasks
`services/hrms_attendance_service.py` — punch in/out, segment assembly, daily derivation (first-in, **last-out** — the source measures overtime to the day's last punch-out so a stray punch cannot invent OT), IST minute-since-midnight normalisation, monthly aggregation, correction workflow · geofence check against Phase 11 settings.

### Frontend Tasks
`features/hrms/attendance/AttendanceOverview.jsx` (punch widget + today's status) · `MyAttendance.jsx` (monthly calendar + summary) · `TeamAttendance.jsx` (HR/HOD grid) · `CorrectionRequest.jsx` + approval queue.

### Database Changes
`hrms_attendance` — unique `(company_id, user_id, date)`; index `(company_id, date)`.
`hrms_punch_segments` — index `(user_id, date)`, `(company_id, date)`.
`hrms_attendance_corrections` — index `(company_id, status)`.

### APIs
`POST /hrms/attendance/punch` · `GET /hrms/attendance/me?month=&year=` · `GET /hrms/attendance/team?date=` · `GET /hrms/attendance/summary?month=&year=` · `POST /hrms/attendance/corrections` · `PATCH /hrms/attendance/corrections/{id}`

### Validation
One open punch at a time (double check-in 409) · check-out requires an open check-in (409) · date not in the future · geofence enforced only when enabled in settings · correction requires a reason and cannot target a locked payroll month (Phase 14) · month 1–12, year bounded · punches stored in IST minutes since midnight, normalised on write.

### Integration
Employees from Phase 2 · holidays and approved leaves from Phase 12 · geofence + working hours from Phase 11 · **sole consumer is Phase 14 payroll** — the contract is defined by what the engine needs.

### Test Cases
- **Positive** — check in → check out → daily record correct; monthly summary matches punches.
- **Negative** — double check-in 409; check-out with no check-in 409; future date 422; outside geofence when enforced 403.
- **Edge** — **midnight-spanning shift**; multiple punch pairs in a day (gaps are unpaid breaks); punch on a Sunday; punch on a holiday; punch on an approved-leave day (conflict surfaced); missing check-out at day end; DST-free IST verified against a non-IST server clock.
- **Permission** — own punches only; HOD sees own team; HR sees company; cross-company 403.
- **Validation** — every boundary.
- **Database** — one record per user per day enforced under concurrency; segment ordering stable.
- **Frontend** — punch widget state; monthly calendar colour coding; team grid at 200 employees.
- **E2E** — a month of mixed attendance (present / late / absent / leave / holiday / Sunday / overtime) produces a summary that **exactly matches** hand-computed expectations — this fixture is reused as the Phase 14 payroll input.

### Smoke Testing
S1, plus: attendance writes never touch calendar or task collections.

### Regression Testing
S2, plus: Phase 12 leave data unaffected by attendance writes.

### Completion Checklist
- [ ] 13 S4 steps · [ ] **scope boundary documented** in the phase report (what was built vs. what awaits an attendance analysis doc) · [ ] timezone suite under 3 server TZs · [ ] the golden month fixture is signed off as the Phase 14 input · [ ] `PHASE_13_REPORT.md` · [ ] tag `hrms-phase-13`

---

## Phase 14 — Payroll Engine, Runs & Salary Slips

### Objectives
Re-implement the source's payroll rule engine in Python as a pure, config-driven, unit-tested module — and fix the three payroll defects the backend doc flags as risks.

### Features
Pure rule engine · monthly payroll computation · **persisted, lockable payroll run** (source had none) · rich per-employee breakdown with plain-English notes · printable salary slip · payroll summary + export · leave-balance ledger reconciliation.

### Backend Tasks
`services/hrms_payroll/` — `config.py` (**every policy number, no magic values in the engine**), `types.py` (`EmployeeMonth` → `PayrollBreakdown`, DB-agnostic), `rules.py` (one pure function per rule), `engine.py` (`calculate_payroll(month, config)` — **no I/O, no DB, no clock**), `adapter.py` (the only DB-aware part: attendance + leaves + holidays + employee → `EmployeeMonth`).
`services/hrms_payroll_service.py` — run orchestration, persistence, locking, balance reconciliation.
**Three fixes:** (1) `GET /payroll` is pure — balances are written only by `POST /payroll/runs` (BE Risk #15); (2) runs are persisted, versioned and lockable so a retroactive edit cannot silently change a paid month (Risk #16); (3) all policy values come from the Phase 11 typed allow-list (Risk #17).

Rules implemented per BE §12.2: daily = monthly ÷ days-in-month · late after 09:10 → flat fine, after 09:15 → also 1 hour · overtime from 17:00, **completed hours only**, to the last punch-out · Sunday work entirely OT · paid-leave allowance with unpaid overflow · holidays (a holiday on a Sunday adds nothing) · unauthorised-absence penalty · rejected-but-absent penalty, **waived if they actually worked** · sandwich rule · >15 leave days → all Sundays unpaid · same-month join+resign → only worked days · mid-month proration where the **daily rate still derives from the full monthly salary** · professional tax.

### Frontend Tasks
`features/hrms/payroll/PayrollRun.jsx` (month/year, run + lock, 3 summary tiles, employee filter, table) · `PayrollBreakdownCard.jsx` (credit/debit tinting, per-row hints, engine `notes[]`) · `SalarySlipModal.jsx` (printable, `print:hidden` chrome) · `PayrollExport.jsx`.

### Database Changes
`hrms_payroll_runs` — unique `(company_id, month, year, version)`; index `(company_id, status)`.
`hrms_payroll_records` — index `(run_id)`, `(company_id, user_id, month, year)`.
`hrms_leave_balances` (Phase 12) — written **only** by a run.

### APIs
`GET /hrms/payroll/preview?month=&year=` *(pure, no writes)* · `POST /hrms/payroll/runs` · `GET /hrms/payroll/runs` · `GET /hrms/payroll/runs/{id}` · `POST /hrms/payroll/runs/{id}/lock` · `GET /hrms/payroll/runs/{id}/slip/{user_id}` · `GET /hrms/payroll/runs/{id}/export`

### Validation
Month 1–12, year bounded, both required · `base_salary` present and ≥ 0 (**refuse to compute** rather than silently defaulting to 30000 as the source does) · a locked run is immutable (409) · one active run per company-month (re-running creates a new version) · attendance and leave data must exist for the period (explicit warning if partial) · policy values validated at load from Phase 11 · engine is total — every branch produces a breakdown or raises a typed error, never a silent zero.

### Integration
Attendance (13) + leaves & holidays (12) + employees (2) + policy (11). Locking a run blocks retroactive attendance corrections for that month (enforced in Phase 13's correction validator).

### Test Cases
- **Unit (engine, pure — the priority suite)** — one test per rule from §12.2 plus their interactions: late 09:09/09:10/09:11/09:16 · OT 17:45→0h, 18:00→1h, 18:30→1h, 19:00→2h · Sunday work · paid-leave overflow · sandwich rule · >15-day rule · unauthorised absence · rejected-but-worked waiver · same-month join+resign · mid-month proration · Feb (28/29) vs. 31-day months · PT.
- **Positive** — the Phase 13 golden month produces a hand-verified net salary, to the rupee.
- **Negative** — missing `base_salary` → explicit error; locked run edit 409; month 13 422; non-HR access 403.
- **Edge** — employee joins on the 1st / on the last day; resigns mid-month; zero attendance; every day a holiday; leave exceeding the month; negative net salary (floored and flagged, not silently negative).
- **Permission** — HR/Admin only; an employee sees **only their own** slip.
- **Validation** — every policy boundary.
- **Database** — `GET /preview` provably writes nothing (dump + diff); runs are versioned; balances idempotent across re-runs.
- **Frontend** — breakdown tinting; notes rendered; print output clean; export matches the table.
- **E2E** — attendance + leave for a month → preview → run → lock → slips → retroactive correction refused.

### Smoke Testing
S1, plus: a preview leaves the database byte-identical (explicitly dumped and diffed).

### Regression Testing
S2, plus: Phase 12 balances unchanged by previews; Phase 13 corrections still work for unlocked months.

### Completion Checklist
- [ ] 13 S4 steps · [ ] **engine unit suite covers every rule in BE §12.2** · [ ] golden-month net verified by hand · [ ] `GET` proven side-effect-free · [ ] locking enforced end to end · [ ] `PHASE_14_REPORT.md` + `docs/hrms/HRMS_PAYROLL_RULES.md` · [ ] tag `hrms-phase-14`

---

## Phase 15 — Hardening, End-to-End Validation & Production Readiness

### Objectives
Prove the whole module, not its parts. No new features.

### Features
Full-lifecycle E2E automation · security review · performance validation · complete documentation · production runbook.

### Backend Tasks
Structured logging audit on every write path · error-envelope consistency sweep (no `{success:false}` on a 200 anywhere) · N+1 and index audit across all HRMS queries · rate-limit tuning on public routes · settings/permission hardening review · full audit-log read API with filters (the source had only the per-candidate timeline — BE §15).

### Frontend Tasks
Loading/empty/error states verified on every screen · light + dark theme sweep · responsive sweep (mobile/tablet/desktop) · accessibility pass (keyboard nav, focus traps in modals, labels, contrast) · bundle-size review and lazy-loading of heavy routes.

### Database Changes
Final index review against production-shaped data. Optional TTL for expired public access codes.

### APIs
`GET /hrms/audit?entity=&actor=&from=&to=` (new). No other additions.

### Validation
Full cross-phase validation matrix re-executed. Every field in the analysis docs' Form Field Reference (FE §8) confirmed present with matching required/optional/default/options.

### Integration
Every module boundary re-verified: HRMS ↔ users · HRMS ↔ companies · HRMS ↔ notifications · HRMS ↔ S3 · HRMS ↔ nothing else.

### Test Cases
- **E2E golden path** — enable HRMS → create departments/designations/employees → raise requisition → HR review → MD approve → publish 2 platforms → 3 public applications → screen → assess (dual review) → interview chain → offer → accept → onboard → Employee ID → employee master → mark holidays → apply/approve leave → a month of attendance → payroll run → lock → slips. Every KPI on dashboard and reports reconciled at the end.
- **Security** — auth bypass attempts on all 4 public routes · IDOR across companies on every authed endpoint · injection (NoSQL operator injection in query params) · XSS in every free-text field · file-upload abuse (oversized, wrong MIME, double extension, zip bomb) · rate-limit evasion · access-code brute force · PII exposure in logs and error bodies · JWT tampering/expiry.
- **Performance** — 10k candidates, 500 employees, 12 months of attendance: dashboard < 500 ms, pipeline < 2 s, payroll run < 30 s, no COLLSCAN on any hot query.
- **Permission** — the full capability × role matrix executed programmatically for all 6 mapped roles.
- **Regression** — every ERP module exercised: Task Management, Delegation, Calendar, TPMS, CRM/ORM, Auth, User Management, Notifications, Reports, Media, Assistant.
- **Data integrity** — orphan scan (candidates without requisitions, offers without candidates, payroll without employees); referential consistency report.

### Smoke Testing
S1 in full on a **production-like deployment** (docker-compose, built frontend behind nginx), not just a dev server.

### Regression Testing
S2 against the Phase-1 baseline **and** against `main` — the complete diff reviewed in one sitting.

### Completion Checklist
- [ ] 13 S4 steps · [ ] E2E golden path green · [ ] security review signed off · [ ] performance targets met · [ ] permission matrix 100% · [ ] **zero regressions across all ERP modules** · [ ] every FE + BE analysis-doc feature traced to an implementation (§4) · [ ] docs complete · [ ] `PHASE_15_REPORT.md` + `docs/hrms/HRMS_PRODUCTION_RUNBOOK.md` · [ ] tag `hrms-v1.0` · [ ] **Production Ready** declared

---

## §4 Traceability Matrix — Analysis Doc → Phase

Maintained continuously; verified in Phase 15. Every row must be **Done** or carry an explicit, approved deferral.

| Analysis reference | Feature | Phase |
|---|---|---|
| FE §6.1 / BE §5 | Recruitment Dashboard | 10 |
| FE §6.2 / BE §5.2, §6.7 | Requisitions + 4-state approval | 3 |
| FE §6.3 / BE §5.3 | Job Descriptions (co-authored, co-approved) | 3 |
| FE §6.4 / BE §5.4 | Job Postings + per-platform links | 4 |
| FE §6.5 / BE §5.5 | Candidates pipeline + journey | 5 |
| FE §6.6 / BE §5.5 | HR Screening + bulk triage | 5 |
| FE §6.7 / BE §5.8, §6.8 | Assessments + dual review | 6 |
| FE §6.8 / BE §5.6, §6.3 | Interviews + scorecard + `PASS_NEXT` | 7 |
| FE §6.9 / BE §5.7 | Offers + versioning | 8 |
| FE §6.10 / BE §5.9, §6.5 | Onboarding + Employee ID | 9 |
| FE §6.11 | Reports + export | 10 |
| FE §6.12 / BE §5.4, §5.7–5.9 | 4 public candidate pages | 4, 6, 8, 9 |
| FE §6.13 | Login | *(exists — ERP auth reused)* |
| FE §6.14 / BE §5.10, §6.11, §14 | Apply Leave + approval | 12 |
| FE §6.15 / BE §5.10, §6.12, §12 | Payroll + slips | 14 |
| FE §6.16 / BE §5.10 | Holidays | 12 |
| FE §6.17 / BE §5.11 | Settings & RBAC | 11 |
| FE §5 / BE §7.3 | Role model | 1, 11 |
| BE §6.4 | Requisition auto-closure | 8, 9 |
| BE §6.6 | Candidate journey (audit read) | 5 |
| BE §9 | Uploads | 4 (+ reused) |
| BE §10 | Notifications / email / audit | 1 (+ every phase) |
| BE §13 (stale) | Attendance | 13 *(bounded scope — §0.4)* |
| FE §15 / BE §15 | Employee Master | 2 |
| FE §15 / BE §15 | Departments / Designations CRUD | 2 |
| BE §15 | Audit read API | 15 |
| BE §15 | Assets register | **Deferred** — flagged, not in scope |
| BE §15 | Announcements | **Deferred** — flagged, not in scope |
| BE §15 | PF / ESI / TDS, salary components | **Deferred** — needs statutory spec |
| BE §15 | Server-side PDF slips | **Deferred** — browser print ships in 14 |

> Deferrals are listed openly rather than silently dropped. Say the word and any of them becomes a Phase 16.

---

## §5 Final Production-Readiness Gate

HRMS is declared Production Ready only when all of the following hold:

- [ ] Every feature in `HRMS_BACKEND_ANALYSIS.md` is implemented or explicitly, approvedly deferred (§4)
- [ ] Every feature in `HRMS_FRONTEND_ANALYSIS.md` is implemented or explicitly, approvedly deferred (§4)
- [ ] Frontend and backend behaviour match — same validation rules, same permissions, no button that 403s (the source's documented flaw, FE §5)
- [ ] Every API returns correct HTTP status codes with a consistent error envelope
- [ ] Database consistent: no orphans, all indexes present and used, all uniqueness enforced
- [ ] Authentication, authorization and role-based permissions verified across all 6 mapped roles
- [ ] Multi-tenant isolation proven with ≥2 seeded companies
- [ ] Public surface security-reviewed and rate-limited
- [ ] Payroll engine unit-tested against every rule, with a hand-verified golden month
- [ ] **Zero regressions** in Task Management, Delegation, Calendar, TPMS, CRM/ORM, Auth, User Management, Notifications, Reports, Media, Assistant
- [ ] No console errors, no backend 5xx, no API failures in the production-like smoke run
- [ ] Documentation complete: architecture, permissions, payroll rules, API reference, runbook, 15 phase reports

---

## Approval

### ✅ Settled

| # | Decision | Outcome |
|---|---|---|
| §0.3-A | Holidays | **Separate `hrms_holidays` collection.** Shared holiday module untouched (zero diff). Drift mitigated by a read-only import action + divergence banner |
| §0.3-D | Frontend tests | **Documented manual test scripts** per phase. No new frontend dependencies |
| §0.3-E / §0.4 | Attendance | **Bounded scope derived from the payroll rules** in Backend §12.2; scope boundary documented in the Phase 13 report |
| §0.3-F | Audience | **Client-company module (TPMS-style)**, `company_id`-scoped, with internal cross-company admin |

### ⏳ Proceeding as proposed unless you object

| # | Item | Proposal |
|---|---|---|
| §0.2 | Role mapping | `superadmin`→Admin · `clientadmin`/`governance_role=MD`→Boss/MD · `HR`→HR · `HOD`→Manager · `IMPLEMENTOR`/`clientuser`→Employee · staff `admin`→internal HR operator |
| §0.3-B | Employee master | `hrms_employee_profiles` side-collection keyed on `user_id` (ObjectId). Identity stays in `staff`/`learners`; no duplication, no rename-orphan bug |
| §0.3-C | Public routes | New `hrms_public` router with no auth dependency + per-IP/per-code rate limiting + 128-bit access codes; React routes mounted outside `PrivateRoute` |
| — | Phase sequence | The 15 phases in §3, in that order |

### Final confirmation needed

Reply **"approved"** (or name anything you want changed) and I will begin **Phase 1 only** — foundation scaffold, access control, collection registry, shell nav.

I will not start Phase 2 until all 13 S4 steps of Phase 1 pass and `docs/hrms/PHASE_1_REPORT.md` is in your hands.
