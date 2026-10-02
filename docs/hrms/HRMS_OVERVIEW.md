# HRMS — Complete Build Overview

> **What this is:** a single document covering what the HRMS module *is*, **how much of it is
> actually built**, the end-to-end flows, and every subsystem behind them.
>
> **Verified against the code on 2026-08-13, after Phase INT-2.** Every number here was counted from the source,
> not carried over from a plan. Where something is declared but not implemented, it says so
> explicitly — see [§16](#16-what-is-not-built).
>
> Supersedes `HRMS_MODULE_OVERVIEW.md`, which predates the internal-recruitment track and
> undercounts the module by roughly 40%.

---

## Table of contents

1. [What this module is](#1-what-this-module-is)
2. [Build status — how much is done](#2-build-status--how-much-is-done)
3. [File map](#3-file-map)
4. [Security model](#4-security-model)
5. [Core invariants](#5-core-invariants)
6. [Data model](#6-data-model)
7. [Flow A — client (agency) recruitment, end to end](#7-flow-a--client-agency-recruitment-end-to-end)
8. [Flow B — internal recruitment, end to end](#8-flow-b--internal-recruitment-end-to-end)
9. [Candidate lifecycle](#9-candidate-lifecycle)
10. [Governance subsystems](#10-governance-subsystems)
11. [Supporting subsystems](#11-supporting-subsystems)
12. [The public surface](#12-the-public-surface)
13. [Analytics and reports](#13-analytics-and-reports)
14. [Frontend architecture](#14-frontend-architecture)
15. [API reference](#15-api-reference)
16. [What is NOT built](#16-what-is-not-built)
17. [Testing](#17-testing)
18. [Traps and gotchas](#18-traps-and-gotchas)
19. [Appendix — seeding test data](#appendix--seeding-test-data)

---

## 1. What this module is

HRMS is an **opt-in, per-company module** inside the Sparsh ERP covering the **employee master**
and the **full recruitment pipeline**, from raising a vacancy to a confirmed employee whose
personnel file is closed.

It is switched on per company with `companies.hrms_enabled`. **A missing flag means OFF** —
nothing is exposed until it is explicitly enabled (unlike ORM, which defaults on).

### Two tracks, one module

Everything in HRMS runs on one of two **requisition tracks**, fixed at creation and immutable
afterwards (changing it mid-flight would invalidate an approval already granted under different
rules):

| Track | Who is hiring | Who owns the money | Who decides |
|---|---|---|---|
| **`client`** (default) | the tenant recruiting **for a client company** — the agency model | the client | CVs are shared with the client for a verdict; MD signs off internally |
| **`internal`** | **Sparsh Magic hiring for itself**, governed by the Internal Recruitment Policy & SOP | Sparsh Magic | Management/Finance approve headcount + budget; the HOD owns the scorecard |

The distinction shapes the whole module. On the client track the job is to **route CVs and
record answers**. On the internal track the job is to **enforce our own governance** — which is
why that half is mostly gates rather than pipeline.

The client track is byte-for-byte unchanged by the internal work: `RequisitionTrack` defaults to
`client`, every requisition raised before the internal phase has no `requisition_track` field at
all, and `track_of()` treats that absence as `client`. That default is a compatibility
guarantee, not a convenience.

### The one-paragraph version

A hiring manager raises a **requisition** with its **job description**. It walks an approval
chain (different per track), escalating up the reporting line if it exceeds **sanctioned
headcount**. HR publishes a **job posting**, which mints exactly **one public application
link**. Applicants apply and become **candidates**. HR **screens** them in bulk; on the client
track the good ones are **shared with the client** for a verdict. Survivors sit an
**assessment**, then **interview** rounds. A pass at the MD round marks them **Selected**. An
**offer** goes out — on the internal track only after a **reference check** clears and
Management approves the CTC against the **approved salary band**. If accepted, an **appointment
letter** follows, then **onboarding** — KYC, background check, checklist — ending in a generated
**employee ID** and a real employee record. Internally hired staff then run a **probation
review**, and confirmation is what **closes the personnel file** and the requisition.

---

## 2. Build status — how much is done

### 2.1 By the numbers

| | Count |
|---|---|
| Backend HRMS code (models + routes + services + utils) | **~25,650 lines** |
| Backend tests | **61 files, ~23,300 lines** |
| Frontend HRMS code (feature + public pages) | **~17,200 lines** |
| Authenticated API endpoints | **190** |
| Public (unauthenticated) endpoints | **12** (6 surfaces × GET/POST) |
| Live MongoDB collections | **38** |
| Capabilities in the `Cap` enum | **90** |
| HRMS roles | **8** |
| Backend services | **40** |
| Frontend screens (routes under `/hrms`) | **30** + 6 public pages |

### 2.2 By roadmap phase

The roadmap in `docs/HRMS_IMPLEMENTATION_ROADMAP.md` defines 15 phases. Current state:

| # | Phase | Status |
|---|---|---|
| 1 | Foundation — module scaffold, access control, registry, audit/notify | ✅ **Built** |
| 2 | Employee master, departments, designations | ✅ **Built** |
| 3 | Requisitions + job descriptions (unified approval chain) | ✅ **Built** |
| 4 | Job postings + public application intake | ✅ **Built** |
| 5 | Candidates pipeline, screening, journey timeline | ✅ **Built** |
| 6 | Assessments (dual review) + public assess page | ✅ **Built** |
| 7 | Interviews, scorecards, `.ics`, assessment gating | ✅ **Built** |
| 8 | Offers + public offer page | ✅ **Built** |
| 9 | Onboarding → employee creation → requisition closure | ✅ **Built** |
| 10 | Recruitment dashboard + reports + exports | ✅ **Built** |
| 11-R | Review enhancements — links, documents, appointments, clients, sanction + escalation | ✅ **Built** |
| — | **Internal recruitment track** (SOP) — not in the original roadmap | ✅ **Built** |
| — | **Phase INT-2** — the remaining SOP gaps (see [§2.4](#24-phase-int-2--closing-the-sop)) | ✅ **Built** |
| — | **Phase INT-3** — scheduler wiring (see [§8.11](#811-the-scheduled-jobs-phase-int-3)) | ✅ **Built** |
| — | **Phase INT-4** — telephonic screening (see [§8.12](#812-telephonic-screening-phase-int-4)) | ✅ **Built** |
| — | **Phase INT-5** — per-company configuration (see [§8.13](#813-per-company-configuration-phase-int-5)) | ✅ **Built** |
| — | **Phase INT-6** — the working calendar (see [§8.14](#814-the-working-calendar-phase-int-6)) | ✅ **Built** |
| — | **Phase INT-7** — the requisition tracker (see [§8.15](#815-the-requisition-tracker-phase-int-7)) | ✅ **Built** |
| — | **Phase INT-8** — KPI dashboard filters (see [§8.16](#816-kpi-dashboard-filters-phase-int-8)) | ✅ **Built** |
| — | **Phase INT-9** — record-level notifications (see [§8.17](#817-record-level-notifications-phase-int-9)) | ✅ **Built** |
| — | **Phase INT-10** — negotiation record, interview notice, optional score band (see [§8.18](#818-salary-negotiation-interview-notice-and-the-three-band-reading-phase-int-10)) | ✅ **Built** |
| 11 | HRMS settings + per-user RBAC console | ❌ **Not built** (role matrix *is* the model) |
| 12 | Holidays + leave management | ❌ **Not built** |
| 13 | Attendance | ❌ **Not built** |
| 14 | Payroll engine, runs, salary slips | ❌ **Not built** |
| 15 | Hardening / production readiness | ⏳ partial (tests, guards and caps exist; no formal gate run) |

**In short: the entire recruit-to-hire lifecycle is built, on both tracks. Leave, attendance and
payroll are not started.**

### 2.3 Internal-track feature set (the newest work)

| Capability area | Status |
|---|---|
| Separate internal approval chain (HR verify → budget → escalation → scorecard) | ✅ |
| Mandatory budget/headcount gate blocking all sourcing | ✅ |
| Position scorecards — draft, dual approval, candidate evaluation | ✅ |
| Reference checks + mandatory pre-offer gate | ✅ |
| Offer approval by Management/Finance + salary-band enforcement | ✅ |
| Probation reviews, confirm/extend/terminate | ✅ |
| Personnel file closure | ✅ |
| Exception log — the only sanctioned way to bypass a gate | ✅ |
| SLA / TAT tracking + breach sweep | ✅ |
| Day-1 induction checklist (internal onboarding only) | ✅ |
| Record-retention stamping (`retention_until`) | ✅ |
| Record-retention **purge** — proposal, MD approval, redaction | ✅ (Phase INT-2) |
| Automated reminders, escalations and the purge proposal | ✅ (Phase INT-3) |
| Telephonic screening + its gate on interview scheduling | ✅ (Phase INT-4) |
| Per-company SLA targets, retention, probation, tiers and score bands | ✅ (Phase INT-5) |
| Holiday-aware working days, opted into per company | ✅ (Phase INT-6) |
| The Annexure C shared requisition tracker | ✅ (Phase INT-7) |
| KPI dashboard filters (department / position / level / owner / HOD / status) | ✅ (Phase INT-8) |
| Record-level notifications: scorecard, reference, probation, exceptions | ✅ (Phase INT-9) |
| Salary negotiation record + the spec §16 comparison surface | ✅ (Phase INT-10) |
| Automatic interview confirmation to the candidate; short notice recorded | ✅ (Phase INT-10) |
| Three-band score reading, per company | ✅ (Phase INT-10) |

### 2.4 Phase INT-2 — closing the SOP

The internal track shipped with the pipeline and the money gates. This phase closed the
remaining distance between the **Sparsh Magic Internal Recruitment Policy & SOP v1.0** and
the built module. **Nothing in it changes the client track** — every control is keyed on
`requisition_track == internal` and returns early otherwise, and
`test_e2e_recruitment_journey.py` §13 asserts that structurally rather than by hoping.

| # | What it closed | Where it lives |
|---|---|---|
| INT-2.1 | Interview panel composition, the mandatory Management final round, the shortlisting committee, batch interview windows | `hrms_interview_service`, `hrms_shortlist_service`, `hrms_interview_window_service` |
| INT-2.2 | The scoring guide realigned from three bands to the SOP's **four** | `models/hrms.score_band` |
| INT-2.3 | Pre-boarding engagement — touchpoints, a due list, an At Risk flag | `hrms_preboarding_service` |
| INT-2.4 | The two **date-anchored** SLA milestones, folded into the one declarative table | `hrms_sla_service` |
| INT-2.5 | The standing salary-band master, pre-filling the budget gate | `hrms_salary_band_service` |
| INT-2.6 | The talent pool, gated on consent that cannot outlive retention | `hrms_candidate_service` |
| INT-2.7 | Candidate communications — six templates, two consent statements, an append-only log | `hrms_comm_service` |
| INT-2.8 | New-hire experience surveys, pseudonymous to the reporting layer | `hrms_survey_service` |
| INT-2.9 | All **eight** SOP KPIs, with honest denominators | `hrms_analytics_service.internal_kpis` |
| INT-2.10 | Statutory pre-employment checks, EEO + data-use acknowledgements, conflict of interest | `hrms_probation_service`, `hrms_posting_service`, panel/committee records |
| INT-2.11 | The policy register and its annual review cycle | `hrms_policy_service` |
| INT-2.12 | The retention purge — proposed, approved, **redacting** | `hrms_purge_service`, `scripts/hrms_retention_purge.py` |
| INT-2.13 | Five printable SOP forms as PDFs | `hrms_record_document_service` |

**Every SOP section 1–14 and Annexures A–C now maps to built code or to a written
deferral in [§16](#16-what-is-not-built).**

---

## 3. File map

### Backend

```
backend/app/
  models/hrms.py                      3,483 lines — THE single source of truth
                                      enums, both state graphs, capabilities, role tables,
                                      collection names, id formats, SLA/retention tables,
                                      pydantic API models
  routes/hrms.py                      2,301 lines — 137 authenticated endpoints
  routes/hrms_public.py                 233 lines — the 5 unauthenticated surfaces
  utils/hrms_access.py                  328 lines — identity → role → capability → scope
  utils/hrms_public_guard.py            333 lines — rate limits, access codes, uploads

  services/
    hrms_requisition_service.py       1,386   requisitions, JDs, both approval chains, escalation
    hrms_analytics_service.py         1,262   dashboard, funnel, breakdowns, reports, export
    hrms_document_service.py            836   document types, uploads, verification
    hrms_onboarding_service.py          802   pre-onboarding, BG, checklist, employee ID
    hrms_offer_service.py               792   offers, approval, band gate, send, accept/revoke
    hrms_employee_service.py            781   employee master, profiles, hierarchy
    hrms_candidate_service.py           727   candidates, screening, client verdicts
    hrms_appointment_service.py         628   appointment letters
    hrms_interview_service.py           621   scheduling, scorecards, round progression
    hrms_posting_service.py             576   postings + the public application intake
    hrms_scorecard_service.py           549   position scorecards, dual approval, evaluation
    hrms_assessment_service.py          545   assessments, dual review
    hrms_client_service.py              515   clients (read-only) + client engagements
    hrms_probation_service.py           437   probation reviews, personnel-file closure
    hrms_link_service.py                375   the public-link registry
    hrms_sla_service.py                 356   working-day TAT, breach detection, sweep
    hrms_sanction_service.py            345   sanctioned strength, position status
    hrms_exception_service.py           295   the exception log and what it unblocks
    hrms_reference_service.py           276   reference checks + the offer gate
    hrms_masters_service.py             263   departments and designations
    hrms_referral_service.py            194   "how did you hear about this role"
    hrms_notify_service.py              147   in-app + email fan-out
    hrms_ics.py                         130   calendar invites for interviews
    hrms_audit_service.py                91   the append-only trail

    ── Phase INT-3 ──
    hrms_scheduler_service.py           412   the five scheduled governance sweeps

    ── Phase INT-4 ──
    hrms_telephonic_service.py          489   the SOP's step 5 phone screen + its gate

    ── Phase INT-5 ──
    hrms_config_service.py              357   the per-company rule set, as an overlay

    ── Phase INT-6 ──
    hrms_holiday_service.py             210   this company's working calendar + import

    ── Phase INT-7 ──
    hrms_tracker_service.py             337   the internal tracker: one row, every stage

    ── Phase INT-10 ──
    hrms_negotiation_service.py         ~330  the salary negotiation record (SOP step 9)
    hrms_id_service.py                   65   atomic business-id counters

    ── Phase INT-2 ──
    hrms_shortlist_service.py           477   the internal shortlisting committee (SOP 5)
    hrms_salary_band_service.py         403   the standing salary-band master
    hrms_record_document_service.py     389   five printable SOP forms, as PDFs
    hrms_policy_service.py              388   the policy register + review cycle (SOP 14)
    hrms_comm_service.py                369   candidate communications: templates + log
    hrms_survey_service.py              364   new-hire experience surveys (SOP 10)
    hrms_purge_service.py               332   the retention purge (SOP 13)
    hrms_preboarding_service.py         303   pre-boarding engagement (SOP 6)
    hrms_interview_window_service.py    229   batch interview windows (Annexure C)

  services/hrms/tests/                  61 test files
scripts/
  seed_hrms_recruitment_demo.py         one requisition end to end (marker: recruitment-demo)
  seed_hrms_realistic_ops.py            a full book of work      (marker: realistic-ops)
  hrms_retention_purge.py               proposes a purge; --dry-run is the DEFAULT
```

### Frontend

```
frontend/src/
  features/hrms/
    HrmsGate.jsx           entry redirect — decides where a user lands
    HrmsWorkspace.jsx      the module shell (outlet for every panel route)
    HrmsContext.jsx        fetches /hrms/health once; holds role + capabilities + scope
    access.js              CAP map — MUST mirror the backend Cap enum exactly
    HrmsHome.jsx           module landing page

    common/      HrmsPageHeader, HrmsScopeBar, HrmsStates, HrmsWorkspaceBar
    people/      EmployeeDirectory, EmployeeProfile, AddEmployeeModal,
                 MasterManager (departments + designations), SanctionedStrength,
                 SalaryBandManager                                    (Phase INT-2)
    recruitment/ RequisitionList/Drawer/FormModal, ApprovalDialog, JdLibrary,
                 PostingList, CreatePostingModal, CandidatePipeline, ScreeningBoard,
                 CandidateJourney, AssessmentBoard, InterviewBoard, OfferBoard,
                 OfferPaper, AppointmentBoard, AppointmentPaper, OnboardingBoard
    internal/    InternalRequisitionList, ScorecardLibrary, ReferenceCheckBoard,
                 TelephonicBoard                                       (Phase INT-4)
                 NegotiationBoard                                      (Phase INT-10)
                 HrmsSettings                                          (Phase INT-5)
                 ProbationBoard, ExceptionLog, internalKit(.js/.jsx)
                 ── Phase INT-2 ──
                 ShortlistCommittee, PreboardingBoard, TalentPool,
                 CommTemplates, PolicyRegister
    analytics/   RecruitmentDashboard, RecruitmentReports, analyticsKit(.js/.jsx)
    documents/   DocumentCenter, DocumentPanel, DocumentTypeManager

  pages/hrms/public/  ApplyPage, AssessPage, OfferPage, OnboardPage, AppointmentPage,
                      SurveyPage                                  (Phase INT-2)
  services/hrmsApi.js every HRMS API call the frontend makes (380 lines)
```

---

## 4. Security model

Four layers, applied in this order. **Every one of them is server-side.** The frontend gates on
what the server reports, never on its own derivation.

### 4.1 Identity — Sparsh staff or client user?

`is_internal_user(user)` in `utils/hrms_access.py`. Precedence: `_source_collection` stamp
(`staff` / `learners`) → `tag` → role name. Same precedence `auth_controller` uses, so the two
cannot disagree.

### 4.2 Role — the ERP user resolves to one of **eight** HRMS roles

| ERP identity | HRMS role | Meaning |
|---|---|---|
| internal, `superadmin` | `ADMIN` | full owner, cross-company, implicitly holds every capability |
| internal, `admin`/`coach`/`staff` | `INTERNAL` | cross-company operator + support |
| client, `clientadmin` | `MD` | top of that company's ladder |
| client, `governance_role: MD` | `MD` | |
| client, `governance_role: HR` | `HR` | the recruitment + HR-ops operator |
| client, `governance_role: FINANCE` | `FINANCE` | **budget and offer approvals only** — never who fills a role |
| client, `governance_role: HOD` | `MANAGER` | hiring manager |
| client, `governance_role: IMPLEMENTOR` | `EMPLOYEE` | self-service only |
| client, `governance_role: CLIENT` | `CLIENT` | a user of a *client organisation* — additionally narrowed by engagement |

`FINANCE` is a **peer** of HR on the ladder, not a senior: it owns a different decision, not a
higher one.

### 4.3 Capabilities — 84, granted per role

`Cap` enum in `models/hrms.py`; `ROLE_CAPABILITIES` maps role → set:

| Role | Capabilities |
|---|---|
| `ADMIN` | **all 84**, implicitly (so a new capability can never lock the owner out) |
| `MD` | 83 |
| `HR` | 70 |
| `INTERNAL` | 48 |
| `MANAGER` | 37 |
| `FINANCE` | 19 |
| `EMPLOYEE` | 6 |
| `CLIENT` | 3 |

Every route starts with `_require(current_user, Cap.X)`. Format is always `<domain>.<action>`.

**Deliberate withholdings:**

- `INTERNAL` (Sparsh staff) does **not** get `employee.salary.*` — a client's pay data is not
  support-staff business.
- `INTERNAL` does not get `requisition.review_hr` / `approve_md` or `document.verify` — those
  are the client's own governance acts.
- `REVIEW_HR` and `APPROVE_MD` are held by **different roles**. A two-stage approval one person
  can complete alone is not a control.
- `FINANCE` holds `requisition.approve_budget` and `offer.approve` but **no** hiring-judgement
  capability: it approves what a role costs, never who fills it.
- `MANAGER` sees only **their own** requisitions and the candidates against them.

### 4.4 Company scope — the only tenant boundary

`scope_company_id(user, requested)`:

- A **client-side** caller is always pinned to their own company. A `company_id` in the query
  string is *ignored*, not honoured.
- An **internal** caller must name a company; "all companies at once" is not a valid scope.

`GET /hrms/health` returns the caller's **resolved role and capability list**, and the frontend
gates every control on that answer.

### 4.5 Client scope — a *second* narrowing, inside the tenant

`company_id` is and remains the security boundary. Client scope narrows **further**, inside one
tenant, for users belonging to a client organisation. It never widens anything.

`scope_client_ids(user, company_id)` returns `Optional[list]`, and the three-way distinction is
the whole design:

| Return | Means | Effect |
|---|---|---|
| `None` | the caller is **not** client-scoped (HR, MD, Finance, a manager) | no client filter at all |
| `[]` | client-scoped, **no valid membership** | `{"client_id": {"$in": []}}` — matches nothing |
| `[...]` | the clients this user may work on | `{"client_id": {"$in": [...]}}` |

Collapsing `None` and `[]` into one empty list either locks out every HR user or opens the gate
for an unmapped client user. Both are wrong; only one is loud.

Scope is resolved from **engagement records**, never from a request. Composition is
**intersection, never replacement**.

> ⚠️ **The primitive ships; the wiring does not.** `assert_client_allowed()` and
> `require_engagement()` exist and are tested, but are currently referenced only by
> `/hrms/health` and the engagement endpoints. See [§16.2](#162-multi-client-what-is-and-is-not-secured).

---

## 5. Core invariants

Break any of these and something downstream silently corrupts.

1. **`company_id` is the only security boundary.** `client_id`, `request_no` and role scoping
   are narrowing dimensions *inside* a tenant.
2. **Scoping filters fail CLOSED.** An empty match list becomes `$in: []`, never an absent
   filter.
3. **Every candidate stage move goes through `FORWARD_TRANSITIONS`.** Services propose a target;
   `can_transition()` decides legality. An illegal move is a 409.
4. **Every requisition approval goes through `TRACK_TRANSITIONS`** — the track selects the table,
   the table decides the edge. No branching on track inside handlers.
5. **The internal budget gate is asserted from the table, not the code.**
   `budget_approval_is_mandatory()` proves `APPROVED` is unreachable without passing
   `PENDING_BUDGET`; a test calls it. A future shortcut edge fails loudly.
6. **A gate is bypassed only by an approved exception record** — never by an override flag in a
   request body. An approved, attributable record is the only acceptable bypass.
7. **Business ids come from an atomic counter** (`hrms_id_service.next_business_id`), never from
   scanning rows for a max suffix.
8. **Analytics never writes.** A test greps the source to enforce it.
9. **Nothing is computed in the browser.** Every figure is computed and role-scoped server-side.
10. **The frontend `CAP` map must equal the backend `Cap` enum**, asserted by
    `test_capability_parity.py`.
11. **The sidebar list and the workspace tab strip must stay disjoint.**
12. **Every HRMS collection carries `request_no`** — that is what lets analytics apply one scope
    filter uniformly. The four Phase INT-2 collections that are *configuration* rather than
    work (interview windows, salary bands, communication templates, the policy register) do
    not, for the same reason `hrms_document_types` does not: a template belongs to a company,
    not to one vacancy.
13. **The salary-band MASTER never decides an offer.** The offer check reads the band stamped
    on the requisition at its budget gate. Two sources of truth for "what was authorised" is
    exactly the drift the stamp exists to prevent.
14. **Survey reporting returns scores, never rows**, and refuses any figure below
    `SURVEY_MIN_RESPONSES`. A satisfaction survey a manager can de-anonymise measures nothing.
15. **The purge redacts and never hard-deletes**, and never runs without an approval. An
    audit trail with dangling references proves nothing.

---

## 6. Data model

### 6.1 Live collections (33)

| Collection | Holds |
|---|---|
| `hrms_employee_profiles` | employee master (may exist unlinked to a login user) |
| `hrms_departments`, `hrms_designations` | the masters requisitions reference |
| `hrms_sanctioned_strength` | approved headcount per department+designation |
| `hrms_requisitions` | vacancies, track, approval chain, budget band, client tag |
| `hrms_job_descriptions` | the JD co-approved with its requisition |
| `hrms_job_postings` | published JD + its single public code |
| `hrms_candidates` | the CV and its lifecycle state |
| `hrms_assessments` | take-home tests and their dual review |
| `hrms_interviews` | scheduled rounds and evaluation scorecards |
| `hrms_offers` | offer letters, approvals, candidate responses |
| `hrms_appointments` | appointment letters |
| `hrms_onboarding` | pre-onboarding, BG check, checklist, induction |
| `hrms_documents`, `hrms_document_types` | the document register |
| `hrms_links` | registry of every public link issued |
| `hrms_audit_log` | append-only trail |
| `hrms_counters` | atomic business-id sequences |
| `hrms_public_rate_limit` | fixed-window counters for public endpoints |
| `hrms_client_engagements` | which companies are this tenant's clients, and who works on each |
| `hrms_position_scorecards` | internal-track hiring rubrics |
| `hrms_reference_checks` | internal-track reference calls and their outcomes |
| `hrms_probation_reviews` | internal-track probation and confirmation |
| `hrms_exceptions` | the exception log |
| `hrms_shortlist_reviews` | the internal shortlisting committee's sittings (SOP §5) |
| `hrms_interview_windows` | batch interview slots per department (Annexure C) |
| `hrms_preboarding_touchpoints` | contact between offer acceptance and Day 1 (SOP §6) |
| `hrms_salary_bands` | the standing bands agreed annually with Finance |
| `hrms_comm_templates`, `hrms_comm_log` | what we say to candidates, and when we said it |
| `hrms_surveys`, `hrms_survey_responses` | new-hire experience instruments and answers |
| `hrms_policies`, `hrms_policy_revisions` | the policy register and its Modification History |
| `hrms_purge_batches` | retention-purge proposals awaiting approval |
| `hrms_job_runs` | the scheduled-job ledger — last successful run per (company, job) |
| `hrms_telephonic_screenings` | the SOP step 5 phone screen, its ratings and its outcome |
| `hrms_settings` | one row per company: the rules it has adopted in place of the defaults |
| `hrms_salary_negotiations` | one row per negotiation round, with the band it was judged against |
| `hrms_holidays` | this company's working calendar — the dates SLA maths skips |

**There is no `hrms_clients` collection.** A client *is* a company (`client_id` = a
`companies._id`) — see [§11.1](#111-the-client-dimension).

### 6.2 Business ids

Minted atomically, format `(prefix, year-scoped, pad)` from `ID_FORMATS`, **sequenced per
company** so one tenant cannot infer another's hiring volume:

| Kind | Example | Year-scoped |
|---|---|---|
| requisition | `HR-REQ-2026-001` | yes |
| jd | `JD-2026-001` | yes |
| candidate | `CAN-001` | **no** |
| assessment | `ASM-2026-001` | yes |
| interview | `INT-2026-001` | yes |
| offer | `OFR-2026-001` | yes |
| appointment | `APT-2026-001` | yes |
| onboarding | `ONB-2026-001` | yes |
| employee | `EMP-2026-001` | yes |
| link | `LNK-2026-001` | yes |
| document | `DOC-2026-001` | yes |
| engagement | `CLI-ENG-2026-001` | yes |
| scorecard / reference / probation / exception | `SCR-` / `REF-` / `PRB-` / `EXC-` | yes |
| telephonic screening | `TEL-2026-001` | yes |
| negotiation round | `NEG-2026-001` | yes |
| shortlist sitting | `SLR-2026-001` | yes |
| pre-boarding touchpoint | `PBT-2026-001` | yes |
| salary band | `SAL-2026-001` | yes |
| survey / response | `SRV-2026-001` / `SRP-2026-001` | yes |
| purge batch | `PRG-2026-001` | yes |

> A **policy** has no minted id: it is addressed by its `policy_key`
> (`internal_recruitment`, `profit_recruitment`), which is stable across versions in a way a
> number is not. The **communication log** has none either — it is append-only volume, and a
> business id on every email would burn a counter for a record nobody cites by number.

---

## 7. Flow A — client (agency) recruitment, end to end

Each step lists **who** → **what happens** → **candidate status after** → **API**.

### Step 1 — Raise a requisition (+ JD)

Hiring manager (`MANAGER`) or HR raises a vacancy. The JD is created **in the same call** — a
requisition without a JD cannot be posted.

- `POST /api/hrms/requisitions` (`requisition_track` defaults to `client`)
- Requires: `department_id`, `designation_id`, `vacancy`, `experience_required`,
  `qualification`, `essential_skills`, `required_date`, `assignee_id`, `jd{...}`
- Optional: `client_id`, budget figures, `requisition_type` (`New Position` / `Replacement`)
- Approval status → **`Pending HR Review`**

### Step 2 — HR review

- `POST /api/hrms/requisitions/{request_no}/approve` with `action: "hr-approve"`
- Cap: `requisition.review_hr`
- → `Pending MD Approval`, **or** `Pending Escalation` if over sanctioned strength

### Step 3 — MD approval

- Same endpoint, `action: "md-approve"` (optionally `salary_change`)
- Cap: `requisition.approve_md`
- → **`Approved`**. The JD becomes publishable.

### Step 4 — Publish a posting

- `POST /api/hrms/postings` with `jd_no`, `requires_assessment`, `expiry_date`
- Mints **one** posting code (`AB-123XYZ`) and **one** public link `/apply/{code}`
- `apply_link_mode`: `auto` (built-in form → the pipeline) or `external` (the poster's own
  destination — those applications **never** enter this pipeline)

> **There is deliberately no "platform" on a posting.** One posting, one link, shared anywhere.
> The channel is captured by *asking the applicant*, not inferred from which URL they clicked.

### Step 5 — Applications arrive

- Public: `POST /apply/{code}` → creates a candidate at **`Applied`**
- Manual: `POST /api/hrms/candidates` (HR pastes in a walk-in CV)
- The form asks "where did you hear about this role" (mandatory) → `source`, and optionally
  "were you referred" → the referral block ([§11.2](#112-referrals))

### Step 6 — Screening (bulk, max 200 per call)

`POST /api/hrms/candidates/screen`, cap `candidate.screen`. Partial success is deliberate: a
batch where 3 of 50 are at an incompatible stage moves the 47 and reports the 3.

| Action | Result |
|---|---|
| `review` | → `Under Review` |
| `shortlist` | → `Assessment Pending` if the posting requires one, else `Shortlisted` |
| `share_with_client` | → `Shared with Client`, opens a client-share record |
| `hold` | → `On Hold` |
| `duplicate` | → `Duplicate` (terminal) |
| `reject` | → `Rejected` — **remarks required** |
| `forward` | assigns an internal owner; **does not move the candidate** |

> `forward` assigns an ERP user as recruiter. `share_with_client` sends the CV *out* to the
> hiring client. Easy to confuse; entirely different acts.

### Step 7 — Client verdict

- `POST /api/hrms/candidates/client-response` with `uk` + `status`
- Recorded **by an HRMS user on the client's behalf** — there is no public client portal.
- Rejecting **requires** remarks.

| Verdict | Candidate moves to |
|---|---|
| `Shortlisted` | `Client Shortlisted` |
| `Rejected` | `Client Rejected` |
| `On Hold` | `On Hold` |
| `Pending` | (no move — awaiting reply) |

### Step 8 — Assessment (optional per posting)

- `POST /api/hrms/assessments` → `Assessment Pending`, mints `/assess/{code}`
- Candidate: `GET/POST /assess/{code}` → `Assessment Completed`
- **Two reviewers must both record a decision** (`POST .../review`) → `Assessment Passed` /
  `Assessment Failed`
- A failed assessment is **not** an automatic rejection — HR may still park or reject.

### Step 9 — Interviews

- `POST /api/hrms/interviews` → `Interview Scheduled`
- `POST .../evaluate` with a scorecard (technical, communication, problem solving, behaviour,
  confidence, team fit, outcome, signature)
- `GET .../invite.ics` produces a calendar invite

Progression on **Pass** (`PASS_NEXT`):

```
HR Round      → Technical Round
Technical     → MD Round
Manager Round → MD Round
MD Round      → Selected
```

On **Fail** → `Rejected`. On **Hold** → `On Hold`.

> **Scheduling in the past is refused outright.** There is no API path to a back-dated interview.

### Step 10 — Offer

- `POST /api/hrms/offers` (status `Draft`) → `POST .../send` mints `/offer/{code}`
- Candidate: `POST /offer/{code}` with `accept` / `decline`
- `Offer Generated` → `Offer Accepted` or `Offer Declined` (terminal)
- `POST .../revoke` walks the candidate **back** to `Selected` so revised terms can be issued —
  without that edge a revoked candidate is stranded.

### Step 11 — Appointment letter (optional)

- `POST /api/hrms/appointments` → `.../send` mints `/appointment/{code}` → candidate
  acknowledges → `Appointment Letter Sent`
- **Optional by design.** The direct `Offer Accepted → Pre-Onboarding` edge is kept.

### Step 12 — Onboarding

Startable from `Offer Accepted` or `Appointment Letter Sent`.

1. `POST /api/hrms/onboarding` → `Pre-Onboarding`, mints `/onboard/{code}`
2. New joiner submits KYC / bank / emergency contact / references via `POST /onboard/{code}`
3. `POST .../verify` — documents verified
4. `POST .../bg` — background verification (`Pending` / `In Progress` / `Cleared` / `Flagged`)
5. `POST .../checklist` — **12 keys**: `offer_signed`, `documents_verified`, `bg_cleared`,
   `employee_id`, `email_created`, `system_access`, `asset_issued`, `workspace`, `induction`,
   `policy_ack`, `bank_payroll`, `buddy_assigned`
   (three are **system-set** and cannot be ticked by hand: `employee_id`, `documents_verified`,
   `bg_cleared`)
6. `POST .../generate-id` → mints `EMP-2026-00N`, creates the employee profile, candidate →
   **`Joined`**
7. Checklist completed → onboarding `Completed`, candidate → **`Employee Created`** (terminal)

---

## 8. Flow B — internal recruitment, end to end

Everything below is **additive**. A client-track requisition never enters these states, never
has a scorecard, and is never blocked by the budget or reference gates.

### 8.1 The approval chain

```
Pending HR Verification ──hr-verify──> Pending Budget Approval
                                              │ budget-approve
                            ┌── over sanction ┴── in sanction ──┐
                            ▼                                    ▼
                     Pending Escalation ──escalate-approve──> Pending Scorecard Approval
                                                                  │ scorecard-approve
                                                                  ▼
                                                              Approved
```

Two structural differences from the client chain, both required by the SOP:

1. **A mandatory budget gate before anything may be sourced** (SOP §11).
2. **The chain ends on the position scorecard, not a single MD sign-off** — Annexure B makes
   the HOD accountable for the scorecard and Management accountable for the budget. Two
   different people, two different gates.

The over-sanction detour hangs off `budget-approve`, not `hr-verify`: there is no point asking
a reporting line to justify extra headcount before anyone has agreed to pay for it.

### 8.2 The budget gate — the SOP's only mandatory control

`assert_sourcing_allowed(req)` lives in `hrms_requisition_service` (one copy, deliberately) and
is called by **both** entry points into the pipeline:

- `hrms_posting_service` — before publishing a posting
- `hrms_candidate_service` — before creating a candidate

While the requisition sits in `Pending HR Verification` or `Pending Budget Approval`, both
return **409**. The client track returns immediately from this function, unchanged.

`POST .../approve` with `budget-approve` carries a **required** salary band (`min`, `max`) — an
approval with no number would leave the later offer check nothing to validate against.

### 8.3 Position scorecards

`hrms_position_scorecards`, cap `scorecard.read/write/approve`.

- Criteria are weighted across three categories: `skill`, `experience`, `culture_fit`
- Scores run **1–5**; weighted result banded: **≥ 4.0 Strong**, **< 3.0 Below bar**, else
  **Consider**. The band is **surfaced, never auto-applied** — a rubric that silently rejects
  people is one nobody will trust or correct.
- **Approval is role-dual for managerial roles**: `required_approvals(managerial)` returns
  `[MANAGER, MD]` for managerial+ and `[MANAGER]` otherwise. The MD may stand in for the hiring
  manager on an ordinary role, but **not** on a managerial one — there the two signatures *are*
  the control. A belt-and-braces check also refuses two role-signatures from one user.
- `POST /candidates/{uk}/scorecard-evaluate` scores a candidate against the approved rubric.

### 8.4 Reference checks

`hrms_reference_checks`, cap `reference.read/write`.

- Modes: `Phone` · `Email` · `Letter` · `In Person`
- Outcomes: `Positive` · `Negative` · `Unable to Verify`
- **Only `Positive` clears the offer gate.** "Unable to Verify" is completed *work* but not a
  clearance — an exception must be logged instead, which is exactly the trail the SOP asks for.
- `assert_reference_cleared()` runs **before anything is written** on offer creation, so a
  refusal cannot leave a draft offer behind.

### 8.5 The internal offer path

Three gates the client track does not have:

1. **Reference check cleared** (`assert_reference_cleared`)
2. **CTC inside the approved salary band** (`assert_within_band`) — SOP §6: "salary negotiation
   must stay within the internally approved budget from Step 2"
3. **Management/Finance approval** — `POST /offers/{offer_no}/approve`, cap `offer.approve`

**Create-and-send in one call is refused (409) on the internal track**, because Management's
approval happens *between* the two — there is no moment at which both could be satisfied.
Editing the CTC after approval **withdraws** the approval and re-checks the new figure.

The band is re-checked at approval time, and the band as it stood is stamped on the approval
(`band_min_at_approval` / `band_max_at_approval`) so a later band change is visible as a change.

### 8.6 Induction (Day 1)

On the internal track only, five extra checklist keys are appended to the onboarding record:
`induction_policies`, `induction_systems`, `induction_introductions`, `induction_workplace`,
`induction_feedback`. A client-track onboarding still shows exactly its twelve items.

### 8.7 Probation → confirmation → personnel file

`hrms_probation_reviews`, recorded against the **employee**, not the candidate — the candidate
lifecycle is deliberately left alone at `Employee Created`.

- Duration **1–12 months, default 6** (SOP §7: "typically 3–6 months"); every record carries its
  own duration, so a shorter term is data, not code
- Outcomes: `Pending` → `Confirmed` / `Extended` / `Terminated`
- Confirming **requires a typed signature** — "it ends or extends employment"
- `GET /probation/due` lists reviews falling due
- **Confirmation closes the requisition** (`_close_requisition_on_confirmation`) — the internal
  track's equivalent of the client handover
- `POST /personnel-file/close` records the *act* of closing the file: who checked the set was
  complete, when, and what they said. **Refused (409) unless probation is `Confirmed`**, and
  refused (422) on an empty closure note — "an empty closure note closes nothing".

### 8.8 SLA / TAT tracking

`hrms_sla_service`, working days **excluding Saturday and Sunday** (public holidays are *not*
excluded in this phase — the ERP has a holidays master, and honouring it silently would make
two companies disagree about whether the same requisition breached).

`SLA_MILESTONES` is ONE table with an explicit `anchor` discriminator, so the two kinds of
milestone live in one declaration and `sweep_open_breaches()` picks both up with no extra
sweep code.

| Milestone | `anchor` | Target | Measured from |
|---|---|---|---|
| Budget / headcount approved | milestone | 3 working days | the requisition |
| Position scorecard approved | milestone | 2 working days | budget approval |
| Shortlist ready for HOD review | milestone | 15 working days | the requisition |
| Offer released after selection | milestone | 3 working days | final selection |
| Induction completed | **date** | Day 1 | the onboarding's joining date |
| Probation review | **date** | before it | the probation's end date |

A date-anchored row reports **one row per record**, not per requisition — a requisition that
hired three people owes three inductions, and an aggregate would hide the one person nobody
inducted. Its `target_working_days` and `working_days_taken` are `null`, because there is no
elapsed-time target and reporting one would invent a number. **Met late still counts as a
breach**: the point of a Day 1 milestone is that Day 1 was Day 1.

Endpoints: `GET /requisitions/{no}/sla`, `GET /sla/breaches`. `escalate_if_breached()` and
`sweep_open_breaches()` drive notification on breach.

### 8.9 The exception log

`hrms_exceptions`, caps `exception.read/write/approve`. **An approved exception is the only
thing that unblocks a gate** — there is deliberately no override flag anywhere in the module.

| Exception type | Unblocks |
|---|---|
| `Reference Check Waived` | the reference gate |
| `Offer Outside Budget` | the salary-band gate |
| `Relaxed Scorecard` | the scorecard gate **and** the shortlisting-committee gate |
| `Extended TAT` | the SLA gate |
| `Statutory Check Waived` | the statutory pre-employment gate on probation confirmation |
| `Telephonic Screening Waived` | the telephonic gate on interview scheduling |
| `Other` | nothing — record only |

> **One type now lifts TWO gates.** `Relaxed Scorecard` covers both, because progressing
> somebody the committee has not signed off *is* relaxing the selection criteria and the SOP
> names exactly one exception type for that. `gates_for_exception_type()` returns the list,
> so the fan-out is visible rather than whichever a dict inversion happened to keep.

Statuses: `Pending` → `Approved` / `Rejected`. Services look the gate up in `EXCEPTION_UNBLOCKS`
rather than accepting a boolean in a request body.

### 8.10 Record retention

`RETENTION_YEARS` stamps `retention_until` on records and exposes it on reports:

| Record | Years |
|---|---|
| requisition | 3 (from closure) |
| candidate (selected) | 3 (from joining, then lives on in the personnel file) |
| candidate (unselected) | 1 |
| offer / reference / probation | 3 (employment + 3) |

**Phase INT-2 built the purge** — and deliberately not as a silent cron:

1. `scripts/hrms_retention_purge.py` **proposes**. `--dry-run` is the default and writes
   nothing at all, not even the proposal; `--company` is required and there is no
   all-companies mode.
2. `POST /purge-batches/{batch_no}/approve` **executes**, gated on `retention.purge` (the MD
   alone) and a typed signature — the same standard probation confirmation holds, because
   both destroy or end something.
3. It **redacts rather than deletes**: the id and the audit spine survive, the PII fields are
   cleared, and the row is stamped `purged_at` plus the batch number. An audit trail with
   dangling references proves nothing, and the stamp is what lets a reader tell *we purged
   this, under this approval* from *we lost this*.

Never eligible: anything with **no** `retention_until` (an absent date means nobody computed
one, which is a gap to investigate rather than a licence to delete), anything on an **open**
requisition, and anything belonging to somebody **still employed** — whatever the dates say.

### 8.11 The scheduled jobs (Phase INT-3)

Everything above was written to be *driven* by a job runner, and until this phase nothing
drove it: the code was correct, tested, and never called. `hrms_scheduler_service` is the
driver, called from `reminder_scheduler.start_reminder_scheduler()` — the ERP's existing
60-second loop. **No second scheduler was introduced**, and the jobs contain no governance
logic of their own; each calls the service that already owns the decision.

`SCHEDULED_JOBS` in `models/hrms.py` is the whole schedule, in one table:

| Job | Cadence | UTC hour | Does | Per-record guard |
|---|---|---|---|---|
| `sla_sweep` | daily | 07 | `sweep_open_breaches()` | `sla_escalated` |
| `probation_reminders` | daily | 07 | tiered notice at 30 / 15 / 7 / 1 days | `reminders_sent` on the review |
| `preboarding_reminders` | daily | 08 | `due_touchpoints()`, routed to each owner | the daily stamp |
| `policy_review` | weekly | 08 | `notify_due_reviews()` | the weekly stamp |
| `retention_propose` | weekly | 03 | `propose()` — **proposal only** | an existing `Proposed` batch |

**Two independent guarantees, deliberately.** The run ledger (`hrms_job_runs`) stops a *job*
running twice in a period; the per-record guards stop a *record* being notified twice even
if it does. The second is what makes the house convention — record the stamp only on
success, retry on failure — safe for something that sends email.

**The ledger is durable, unlike the TPMS job state beside it.** A TPMS sweep is an
idempotent sync, so a restart that re-runs one costs nothing. Re-running a reminder job
sends the reminder again, and process memory resets on every deploy. The in-memory dict the
loop passes in is only a cache in front of the collection.

**The probation tiers are calendar days, and fire on "this close or closer"**, not on an
exact-day match — a tier matched exactly is a tier lost entirely if the sweep missed that one
day. When a record is found late, every passed tier is marked fired and only the closest is
sent, so one missed sweep does not become four notices on four consecutive mornings. Overdue
reviews are absent by design: `probation_review_due` in `SLA_MILESTONES` already reports them
and the SLA sweep already escalates them.

**The retention job proposes and never executes.** Redaction still requires
`POST /purge-batches/{batch_no}/approve`, `Cap.RETENTION_PURGE` (the MD alone) and a typed
signature. It also refuses to write an empty batch, and refuses to stack a second proposal
while one is still awaiting a decision.

### 8.12 Telephonic screening (Phase INT-4)

SOP **step 5**, "brief telephonic interview by HR", between CV screening (step 4) and the
panel (step 6). It was the one stage in the process flow with no code at all.

`hrms_telephonic_screenings`, caps `telephonic.read/write`. Annexure B makes HR
**Responsible** and everybody else Informed, so `telephonic.write` is HR's alone; the HOD and
the MD read it because they interview off the back of the call. **`FINANCE` holds neither** —
the same call the module already made for reference checks, whose RACI row is identical.

**Facts and judgements are stored apart.** `notice_period_days`, `expected_ctc`,
`current_location` and `availability` are what the candidate *said*; the four rated
dimensions are what the caller *thought*. Collapsing them lets a rating stand in for a fact,
and "seemed available soon" is not a joining date.

The four dimensions are weighted (`TELEPHONIC_CRITERIA`: role understanding and communication
0.30 each, motivation and suitability 0.20) and band through **the same `score_band()` the
position scorecard uses** — two scoring vocabularies in one process is how a "3" comes to mean
two different things. The score **re-normalises over whatever was actually rated**: a blank is
missing information, not a zero, and nothing rated at all scores `None` rather than 0.0.

**The gate lives on interview scheduling**, not on the record:
`assert_telephonic_cleared(company_id, candidate, req)` is called from
`hrms_interview_service.schedule_interview` inside the internal-track branch, asked *first*
because being told to make a ten-minute call is a cheaper refusal than being told the panel is
wrong after assembling one.

| Situation | Result |
|---|---|
| client track, or no `requisition_track` at all | silent |
| a screen with outcome `Passed` | opens the gate |
| only `Rejected` / `No Answer` screens | **409** |
| no screen at all | **409** |
| an approved `Telephonic Screening Waived` exception | opens the gate |
| the candidate is **already** being interviewed | silent |

That last row is deliberate: the SOP puts the call before *the panel*, so the gate guards
entry into interviewing rather than every round. Without it, shipping this phase would have
stranded every internal candidate already mid-pipeline behind a call nobody could go back and
make.

**`No Answer` is a third outcome, and it moves nobody.** A call that did not happen is not a
verdict — the same distinction `REFERENCE_CLEARS_OFFER` draws for "Unable to Verify". Without
it, an unreachable candidate forces HR to choose between recording a rejection they did not
decide and recording nothing, and "nothing" is what makes a pipeline look stalled for no
visible reason. Several screens per candidate are allowed for exactly this reason, and
`GET /telephonic-screenings/screenable` sorts the work queue by attempt count.

**Both new statuses rank 2, WITH `Shortlisted`** — a phone screen is a decision *about* a
shortlisted candidate, not a further stage, the same reasoning the client-share band follows.
`TELEPHONIC_REJECTED` is revivable to `Under Review`, like `CLIENT_REJECTED`. The direct
`Shortlisted → Interview Scheduled` edge is **kept**, so the graph never forces a client-track
candidate through a stage their process does not have.

### 8.13 Per-company configuration (Phase INT-5)

The module was multi-company for its **data** from Phase 1 — every collection keyed on
`company_id`, ids sequenced per company, salary bands and communication templates already per
company. It was not multi-company for its **rules**: the SLA targets, retention periods,
probation duration, reminder tiers and score bands were module constants, so a second Sparsh
entity would have shared one hard-coded rule set with the first. `COLL_SETTINGS` had been
declared and read by nothing since Phase 1. This is the phase that reads it.

`hrms_config_service.config_for(company_id)` returns **the shipped defaults with a company's
overrides laid on top**. Every default is read from the constant that already shipped — so a
company with no settings row reproduces pre-INT-5 behaviour key for key, with **no migration
and nothing to backfill**.

| Setting | Default | Bounds |
|---|---|---|
| `sla_target_days` | the four milestone targets from `SLA_MILESTONES` | 1–260 working days |
| `retention_years` | `RETENTION_YEARS` | 1–50 years |
| `probation_months` | default 6, min 1, max 12 | 1–24, and `min ≤ default ≤ max` |
| `probation_reminder_days` | `[30, 15, 7, 1]` | 1–365, descending, ≤ 6 entries |
| `score_bands` | Strong 4.0 · Consider 3.5 · Hold 3.0 | 1.0–5.0, strictly descending |

**Maps merge per name; lists replace whole.** Overriding one SLA target keeps the shipped
value for the other three — replacing the map would mean changing one number silently dropped
the rest, and a missing target reads as *no target* rather than as the omission it was. A
reminder-tier list, by contrast, **is** the setting: merging it would make removing a tier
impossible.

**What is stored is what somebody chose.** A value equal to the default is stored anyway
rather than pruned — a company that deliberately set retention to 3 years must not silently
move if the module default later changes. `POST /settings/reset` is how a company goes back
to *following* the default, and that distinction is the reason the endpoint exists.

**Cross-field rules are judged on the merged result**, not the payload: setting `min: 6`
against an in-force default of 3 is refused, because the group would be inconsistent even
though the number sent was fine on its own.

**No caching, deliberately.** The module has no caching layer anywhere else, and a stale rule
is worse than an indexed read. Callers that resolve config inside a loop resolve it **once**
and pass the dict down — `sla_for`, `sweep_open_breaches` and the scheduler all take an
optional `config`, so the read count is per request, not per record. That also means one sweep
judges every requisition against the same targets even if somebody edits the settings while it
runs.

**Capabilities.** `settings.read` is wide (INTERNAL, MD, HR, MANAGER, FINANCE) because a target
you cannot see is one you cannot plan against. `settings.write` is **MD and FINANCE only** —
Annexure B makes Management/Finance *accountable* for policy review, and these numbers are that
policy expressed as data. HR runs the process; it does not rewrite the policy behind it.

#### What is deliberately NOT configurable

- **The gates.** No setting turns off the budget gate, the reference check, the scorecard
  approval or the telephonic screen. Those are the controls the SOP is made of, and a
  deviation goes through the **exception log**, where it is attributable — not through a
  settings screen, where it would be silent. A test asserts the configurable set is exactly
  the five numeric tables.
- **The managerial threshold.** Moving it means `REQUIRED_PANEL_ROLES` must move with it: a
  company that made `mid` managerial would get a mandatory Management final round while the
  panel table still said a mid role needs only HR and the HOD. Two tables that must agree, so
  making one per-company is a design change rather than a config key.
- **Whether an assessment is required.** Already per *posting* (`requires_assessment`), which
  is finer-grained than per company.
- **The holiday calendar.** It belongs to the phase that teaches the working-day maths to read
  it. Declaring a flag nothing reads is precisely the mistake this phase exists to correct.

### 8.14 The working calendar (Phase INT-6)

SOP §8 states its targets in **working days**. Weekends were always excluded; public holidays
never were, and the deferral note gave a real reason — two companies looking at the same
three-day gap would disagree about whether a requisition breached. Phase INT-5 is what made
the answer available: let each entity say which days *it* does not work, rather than forcing
one answer on both.

**The calendar is HRMS's own (`hrms_holidays`), never the ERP's global `holidays` master.**
That collection carries **no `company_id`** — not on read, not on write, not even in its
duplicate check. Pointing per-company compliance figures at one global list would let an admin
adding a regional festival for one entity silently move every other entity's SLA due dates,
and nobody would see the change on the requisition that breached because of it. So the ERP
master is available as an **import** — a company *adopts* a year of dates, as an act with an
audit row — rather than as a live dependency.

**It ships OFF, per company** (`honour_holidays`). Turning it on **changes whether existing
requisitions read as breached**, which is a business decision with a visible date rather than
something that should arrive with a deploy.

| Setting | Behaviour |
|---|---|
| flag off (default) | weekends only — byte-for-byte the pre-INT-6 answer |
| flag on, calendar empty | honours a calendar that has no dates in it |
| flag on, calendar populated | weekends **and** those dates are skipped |

**`None` and an empty set are different answers**, and `holiday_set()` keeps them apart — the
same three-way distinction `scope_client_ids` draws. `None` means *this company does not
honour a calendar*; `set()` means *it does, and has no dates recorded*. Collapsing them makes
"no holidays this quarter" indistinguishable from "nobody set this up".

**The basis is reported, never assumed.** `GET /requisitions/{no}/sla` returns
`counts_holidays`, `holidays_in_calendar` (null when not honouring, so the two states stay
distinguishable on the wire) and a plain-English `basis`, so a reader never has to guess which
of the two bases produced the number in front of them.

`working_days_between()` and `add_working_days()` take the calendar as an **argument**, not a
lookup — they stay pure, the tests walk them directly, and a report or a template can still
call them. `sla_for`, `sweep_open_breaches` and `escalate_if_breached` accept a pre-resolved
`calendar` alongside `config`, so one sweep reads it **once** and judges every requisition on
the same basis even if somebody edits the calendar mid-run.

Also corrected here: `internal_kpis` measured "shortlist within Day 15" against a **hard-coded
15** while the SLA screen measured against the configured target. It now reads both the
company's target and its calendar, so the KPI and the SLA report cannot give two answers to
one question.

### 8.15 The requisition tracker (Phase INT-7)

Annexure C's first efficiency item: *"maintain a shared internal requisition tracker (status,
scores, budget approval date) visible to HR, Department Head, and Management."* The screen
existed and showed five columns; `GET /internal-requisitions/tracker` now returns the row the
annexure describes — identity, budget (with its approval date), scorecard, sourcing, pipeline
counts by stage rank, shortlist, offer, joining date, probation end, SLA health and
exceptions — one row per internal requisition, all computed server-side.

**Read-only, structurally.** `test_int7_tracker` greps the module source for the three write
prefixes, the same guarantee the analytics service carries — so those tokens must not appear
anywhere in `hrms_tracker_service.py`, comments included.

**Batched, because the obvious implementation is quadratic.** Every collection is read once
for the page with `request_no: {"$in": [...]}` — eight reads however many rows — and the test
proves the read count does not grow when the requisition count quadruples. The `$in` list is
built from the already-scoped requisition page, so it can never widen scope; an empty page
short-circuits rather than issuing eight `$in: []` reads.

**Scoped exactly as the requisition list is** — same company filter, same
`_visibility_filter` — so nobody sees a tracker row they could not open as a requisition. A
plain EMPLOYEE sees only what they raised.

**The SLA cell covers the milestone-anchored rows only**, and the payload's `sla_basis` says
so. The two date-anchored milestones are per-joiner (one requisition with three hires owes
three inductions) and cannot honestly collapse into one requisition-level cell; the
requisition's own SLA view remains the full picture. Counts follow the company's INT-5
targets and INT-6 calendar — the row leads with what is breached, or the next thing owed.

**Candidate counts are by `STAGE_RANK`**, not status lists, so a rejected candidate counts
where they entered and a stage added later cannot silently stop counting. The offer cell shows
the **live** offer (accepted beats sent beats draft beats declined/revoked); history is real
but a tracker cell shows what is in play.

The frontend adds a **view toggle on the existing internal-requisitions screen** — "Action
queue" (the five-column screen with its verify/approve buttons) and "Tracker" — same route,
so neither navigation list changes and the two-list disjointness rule is untouched.

### 8.16 KPI dashboard filters (Phase INT-8)

`internal_kpis` computed all eight SOP KPIs but took only a date range; spec §29 asks for
filtering by company, department, position, recruitment period, HR user, HOD, position level
and status. Company was always the scope and the period was the date range, so this phase
added the remaining six: `department_id`, `designation_id`, `designation_level`,
`hr_user_id` (the assignee), `hod_user_id` (the raiser — the module's documented design makes
whoever raises a requisition its hiring manager) and `status` (a `ReqApproval` value).

**One narrowing point.** Every filter narrows the *requisition* query, and every figure
downstream — candidates, offers, references, probations, onboardings — already flows from
`request_nos`. That is the whole design: a filtered KPI can never mix a filtered numerator
with an unfiltered denominator, and the test proves the budget KPI's denominator moves with
the department filter.

**The level filter reads the designation master** with the model's own `designation_level()`
reading, so an unbanded designation counts as `mid` here exactly as it does in the panel
rules — one answer everywhere to "what level is this role". A level with no designations
matches nothing (`$in: []`), never everything; a `designation_id` outside the requested
level is a contradiction and honestly returns the empty set.

**Garbage is refused (422), not matched against nothing.** A typo'd status silently
returning an all-zero dashboard reads as "hiring stopped", not "you misspelt it".

**The response echoes `filters`** (empty object when none), so a filtered dashboard can say
what its figures cover. No filters reproduces the pre-INT-8 answer figure for figure — the
dashboard's own `track=internal` call passes none.

On the dashboard, the filter bar applies to the SOP KPI block **only** — the hiring funnel
and breakdowns below keep their own scope, and the bar says so. The HR/HOD filters are
API-only for now: the module has no light "users by governance role" listing to feed a
dropdown, and a free-text id field is a worse UI than none.

Fixed on the way past: the INT-7 tracker's `designation_level` cell read a field
requisitions never carry (always null on real documents). It now resolves through the
designation master as a ninth batched read, with the same default-mid reading.

### 8.17 Record-level notifications (Phase INT-9)

The requisition approval chain always notified (25 call sites); the scorecard, reference,
probation and exception services emitted **nothing** — so "scorecard approval required",
"probation confirmation required" and "exception approval required" never reached anybody,
and a gate could stay shut with no visible reason (spec §38).

| Event | Told | Channel |
|---|---|---|
| Scorecard drafted | the requisition's raiser (HOD), + MD role when managerial | |
| Scorecard sent back | the drafter + HR role, with the reason | email |
| Scorecard partially approved | whoever is still owed — MD role, or the raiser | email |
| Scorecard fully approved | HR role ("sourcing can begin once budget clears") | email |
| Reference recorded, not clearing | HR role, naming the way forward (new referee or waiver) | in-app |
| Probation opened | the reviewer, as a heads-up | in-app |
| Probation confirmed | HR role; + MD role **informed**, managerial+ only | email / in-app |
| Probation extended | HR role — the review returns to Pending | in-app |
| Probation terminated | HR role, with the reason | email |
| Exception raised | MD **and** FINANCE roles — both hold `exception.approve` | email |
| Exception decided | the raiser — an approval names the gate it lifts | email |

Three rules the wiring follows:

- **"I" in the RACI is in-app; a decision somebody is waiting on is email.** Management's
  informed-only line on a managerial confirmation is a bell, not a mail.
- **One event, one notification.** Fired only on the signature/edit that *changes* state:
  editing remarks on a negative reference, or re-signing a scorecard, says nothing again.
- **The facade is imported late** (inside functions, the SLA service's pattern), so seed
  scripts and tests that patch `hrms_notify_service` attributes silence everything.

**A latent INT-3 bug fixed on the way past:** a probation **extension** returns the review
to `Pending` with a later end date — but the scheduler's reminder tiers are recorded as
fired on the record (`reminders_sent`), so the extended period would never have been
reminded about: its tiers had already burned on the old end date. The extension path now
resets the field, and the test pins it.

### 8.18 Salary negotiation, interview notice, and the three-band reading (Phase INT-10)

Three items closed together.

**Salary negotiation — the record (SOP step 9, spec §16).** The *rule* has been enforced since
the internal track shipped: `assert_within_band` refuses an offer outside the band stamped on
the requisition at its budget gate. What was missing was the *record*: the rounds, what the
candidate asked for, what was proposed, and how each sat against the band. `hrms_salary_
negotiations` holds one row per round, carrying `request_no` and `uk`, with **the band
stamped as it stood** — a later budget re-approval changes the requisition's band but does
not rewrite what round 2 was judged against.

**The gate does not move.** Recording a round decides nothing; an above-band round is
recorded (and Management + Finance are told — spec §38's "salary deviation"), not refused,
because the conversation is allowed to happen. The *offer* is what the band gate refuses,
until the budget is re-approved or an *Offer Outside Budget* exception is approved. The
verdict on a round (`negotiation_verdict`) and the refusal at the offer read the same numbers
the same way; the test calls both on the same figures to prove they agree.

`GET /candidates/{uk}/negotiation` is the comparison surface: band, latest round,
within/above/below against the band **now**, the approved waiver if any, and
`offer_would_pass` — a preview computed from the same facts the gate reads, not a promise.
A round needs an internal requisition with an approved band, or it is 409: a number against
no band has no meaning. `negotiation.write` is HR's (and the MD's); `negotiation.read`
reaches the HOD (consulted) and **FINANCE** (accountable for the figure — the one
candidate-level record it sees, because it is about money and nothing else).

**Interview notice (Annexure C).** "Confirm interview logistics at least 24 hours in
advance." Every schedule and reschedule now tells the candidate through the communications
log (`interview_scheduled` joined `AUTO_COMM_EVENTS`), so "did we tell them" is answerable
from one place; and `notice_hours` / `short_notice` are stamped on the booking. Short notice
**warns and never blocks** — the rule interview windows already follow, for the same reason:
a hard refusal for a Friday-for-Monday booking pushes it off-system where nothing sees it.

**The three-band reading (Gap 10).** The signed SOP has four bands (Strong / Consider / Hold /
Reject); the implementation brief describes three (4.0+ / 3.0–3.99 / below 3.0). Both are
real readings, so which one a company uses is that company's call: the `Hold` floor is
**optional** in `score_bands` — set it to `null` and the scale is Strong / Consider / Reject.
Strong and Consider cannot be switched off; a scale with no bar is not a scale. The default
stays the signed SOP's four.

---

## 9. Candidate lifecycle

### 9.1 Statuses (`AppStatus`)

```
Applied · Under Review · Shortlisted
Shared with Client · Client Shortlisted · Client Rejected
On Hold · Duplicate · Rejected
Telephonic Passed · Telephonic Rejected
Assessment Pending · Assessment Completed · Assessment Passed · Assessment Failed
Interview Scheduled · Technical Round · MD Round
Selected · Offer Generated · Offer Accepted · Offer Declined
Appointment Letter Sent · Pre-Onboarding · Joined · Employee Created
```

**Terminal:** `Employee Created`, `Offer Declined`, `Duplicate`.
**Always available from any non-terminal stage:** `Rejected`, `On Hold`, `Duplicate` — a
recruiter must always be able to stop or park a pipeline.

### 9.2 Stage rank (`STAGE_RANK`) — how the funnel stays honest

A funnel that counts *current* status can show more offers than interviews, because someone at
`Offer Accepted` no longer has an interview status. So every candidate is ranked by the furthest
point they can be **shown** to have reached — their status, **or** the existence of an
assessment/interview/offer record, whichever is further (`_effective`).

| Rank | Statuses |
|---|---|
| 1 | Applied, Under Review, Duplicate, On Hold, **Rejected** |
| 2 | Shortlisted, **Shared with Client, Client Shortlisted, Client Rejected, Telephonic Passed, Telephonic Rejected** |
| 3 | Assessment Pending / Completed / Passed / Failed |
| 4 | Interview Scheduled, Technical Round, MD Round |
| 5 | Selected |
| 6 | Offer Generated, **Offer Declined** |
| 7 | Offer Accepted, Appointment Letter Sent, Pre-Onboarding, Joined |
| 8 | Employee Created |

Three subtleties that trip people up:

- **Rejections rank where the candidate *entered*, not where they left.** That is what keeps the
  funnel monotonically non-increasing.
- **The client-share band sits WITH Shortlisted (rank 2), not after it.** Sharing a CV and
  getting a verdict is a decision *about* a shortlisted candidate.
- **`Applied` and `Under Review` share rank 1.** Neither has cleared a hiring gate — which is
  why "CVs reviewed" cannot be defined as `rank >= rank(Under Review)`.

### 9.3 Evidence-based ranks

Set by the mere existence of a record elsewhere: assessed → 3, interviewed → 4, offered → 6,
offer accepted → 7. A candidate whose status was never updated still ranks correctly.

---

## 10. Governance subsystems

### 10.1 Sanctioned strength and the escalation ladder

One approved figure per (department, designation) in `hrms_sanctioned_strength`.
`position_status()` computes sanctioned vs **actual headcount** vs **committed vacancies**
(open requisitions).

> **A position with NO sanctioned figure recorded counts as over-sanction** — fail closed. An
> unauthorised headcount is exactly the case to escalate. Failing open here would make the whole
> control optional by omission.

The ladder walks the raiser's reporting line, capped at `MAX_ESCALATION_LEVELS = 5` — a cyclic
or absurdly deep reporting chain must not turn one requisition into a twenty-step marathon. The
MD may clear any rung. The same ladder, capability and depth cap serve **both tracks**; it does
not care whose budget it is.

### 10.2 Budget

**Client track:** two figures captured independently — `budget_sanctioned_amount` (management)
and `budget_hod_amount` (the HOD). `budget_status()` derives `Not Set` · `Pending` · `Matched` ·
`Mismatch`. Both optional.

**Internal track:** a mandatory approved **band** (`approved_salary_band_min/max`) set at the
budget gate and enforced at offer time. See [§8.2](#82-the-budget-gate--the-sops-only-mandatory-control).

### 10.3 Audit trail

Append-only `hrms_audit_log`; every service writes through `hrms_audit_service.audit()`.
Readable via `GET /api/hrms/audit` (`audit.read`). `GET /api/hrms/candidates/{uk}/journey`
assembles a candidate's history from it.

---

## 11. Supporting subsystems

### 11.1 The client dimension

**A client is a company from the ERP's existing Companies section.** There is no HRMS client
master — `hrms_client_service.py` projects `companies` into the `{client_id, name, ...}` shape
HRMS reports on, where `client_id` **is** the company's `_id` as a string.

Why: a separate master meant the same organisation existed twice, could be spelled two ways, and
had to be re-entered by hand before it could appear on a dashboard.

- `GET /api/hrms/clients` is **read-only**. Editing a client means editing the company.
- Client names are **refreshed on read** in analytics, so a rename shows through with no sync.
- A requisition with no client is **in-house**, bucketed explicitly rather than dropped.
- **Engagements** (`hrms_client_engagements`) are a *different* record: they say this tenant
  recruits for that company and which of its users work on it. `client.write` manages those.
  Status `active` | `suspended` | `ended` — only `active` grants scope, so suspending an
  engagement revokes its members' scope atomically, with no membership row touched.
- Membership lives **on the engagement, not on the user** — writing an HRMS array into the
  shared `learners`/`staff` collections would widen another module's schema.

### 11.2 Referrals

The application form asks two related questions: **where did you find this job** (always →
`source`) and **were you referred** (optional).

- `referral_source`: `Employee` · `Ex-Employee` · `Consultant / Agency` · `Job Portal` ·
  `Social Media` · `Walk-in` · `Client` · `Other`
- If `referral_source == "Employee"`, a **resolvable `referrer_employee_code` is mandatory** —
  the code *is* the claim. For any other source it is optional context, and an unresolvable one
  is dropped silently rather than failing the application.

### 11.3 The public-link registry

Every candidate-facing link is registered in `hrms_links`: kinds `apply` · `assessment` ·
`offer` · `onboarding` · `appointment`; statuses `Active` · `Expired` · `Revoked` · `Consumed`.

`POST .../revoke` kills a live credential; `POST .../reissue` mints a fresh one and revokes the
old (**apply links cannot be reissued**). Enforcement is server-side in `assert_link_live`, not
merely displayed.

> The admin **screen** for this registry was removed; the endpoints remain and still govern link
> validity.

### 11.4 Documents

`hrms_document_types` (12 seeded on first read) + `hrms_documents`, owned by a `candidate` or an
`employee`. Categories: Identity · Educational · Employment · Statutory · Company Issued · Other.
Statuses: Pending · Uploaded · Under Review · Verified · Rejected · Expired (`effective_status`
derives Expired from the expiry date at read time). Up to 10 versions per document.

`document.verify` is a separate capability from `document.write` because verifying is a
governance decision, not an operational one.

### 11.5 Notifications

`hrms_notify_service`: `notify_user`, `notify_users`, `notify_hrms_role` — in-app rows plus
email. **Seed scripts patch these out**, because a shared database means real colleagues would
otherwise be told about invented candidates.

---

## 12. The public surface

Six unauthenticated routes in `routes/hrms_public.py` (GET + POST each = 12 endpoints), the
module's only internet-facing surface. All defences live in `utils/hrms_public_guard.py`.

| Route | Purpose |
|---|---|
| `GET/POST /apply/{code}` | job ad + application form |
| `GET/POST /assess/{code}` | take-home assessment |
| `GET/POST /offer/{code}` | offer letter + accept/decline |
| `GET/POST /onboard/{code}` | pre-onboarding form |
| `GET/POST /appointment/{code}` | appointment letter + acknowledgement |
| `GET/POST /survey/{code}` | a new joiner's experience survey (Phase INT-2) |

**Access codes** are `secrets.token_urlsafe(16)` — 128 bits of cryptographic randomness,
case-sensitive.

**Rate limits** are DB-backed and fixed-window (an in-process limiter loses state on restart and
is not shared across workers; a sliding window would let a flood grow the limiter's own storage):

| Scope | Limit |
|---|---|
| view | 60 / min / IP |
| apply | 5 / hour / IP |
| apply-posting | 200 / hour / **posting code** |
| assess-view | 30 / min / IP |
| assess-submit | 10 / hour / IP |
| offer-view / onboard-view / survey-view | 40 / min / IP |
| offer-respond / onboard-submit / survey-submit | 10 / hour / IP |

> The survey surface is anonymous in a **stronger** sense than the other five: the GET
> returns the questionnaire and nothing about the respondent — no employee code, no name,
> no requisition. The stored `employee_code` exists solely to stop somebody answering
> twice, and the reporting layer refuses any figure below 5 responses. A survey page that
> greets you by name is one you can screenshot beside your answers.

**Uploads:** max 15 MB, max 10 certificates, MIME allow-list (PDF, DOC/DOCX, JPEG/PNG/WebP).
Base64 in a JSON body, because the public forms cannot use multipart without a token.

---

## 13. Analytics and reports

All read-only, all computed server-side behind `_scope()`.

### 13.1 Endpoints

| Endpoint | Returns |
|---|---|
| `GET /analytics/dashboard` | KPI tiles, CV metrics, client metrics, **cv_funnel**, positions, offer outcomes, onboarding states, time-to-hire, client comparison |
| `GET /analytics/funnel` | the 8-stage hiring funnel by effective rank |
| `GET /analytics/breakdown?by=` | `source` · `department` · `designation` · `client_status` · `referral_source` · `client` |
| `GET /analytics/positions` | position-wise CV status matrix (rows = requisition, columns = every `AppStatus`) |
| `GET /reports/{entity}` | paginated rows — `candidates` · `requisitions` · `interviews` · `offers` · `onboarding` |
| `GET /reports/{entity}/export` | CSV / XLSX, generated **server-side** |
| `GET /analytics/internal-kpis` | all **8** SOP KPIs, each with `eligible_n` and `excluded_n` (Phase INT-2) |
| `GET /surveys/results` | mean experience scores — **scores only**, suppressed below 5 responses |

All accept `date_from`, `date_to`, `client_id`, `company_id`.

### 13.2 Scoping

`_scope()` is applied to **every** aggregation without exception — there is no "just this one
summary" path that skips it. A `MANAGER` is narrowed to their own requisitions; a `client_id`
filter composes by **intersection**, so a hiring manager filtering by client sees only
requisitions that are both theirs and that client's.

### 13.3 CV metrics and the CV funnel

Computed in one already-scoped pass (`_cv_metrics`):

| Metric | Definition |
|---|---|
| `reviewed` | cleared the shortlist bar **or** carries a review-outcome status (`Under Review`, `Rejected`, `Duplicate`, `On Hold`) |
| `awaiting_review` | `total - reviewed` |
| `shortlisted` | effective rank ≥ rank(Shortlisted) — the internal selection |
| `selected` | effective rank ≥ rank(Selected) — the final selection, after interviews |
| `rejected` | status in the rejection set |
| `shared_with_client` | a client-share record exists |
| `client_shortlisted` / `client_rejected` / `client_awaiting` | the verdict on it |
| `joinings` | status in `{Joined, Employee Created}` |

`cv_funnel` presents these as stages: *CVs received → Reviewed → Shortlisted → Shared with
client → Client shortlisted → Selected → Joined*, with `of_total` and `of_previous`.
**`of_previous` is `null` wherever a stage exceeds the one above it** — an in-house requisition
never shares a CV, so `selected` can legitimately outnumber `shared_with_client`.

### 13.4 Guards

`SCAN_CAP = 20000` per read · `MAX_RANGE_DAYS = 1100` (~3 years) · `MAX_EXPORT_ROWS = 5000` ·
`MAX_BREAKDOWN_ROWS = 25` · report page size max 100. An unbounded `to_list` on an analytics
endpoint is a DoS waiting for the first client with real volume.

---

## 14. Frontend architecture

### 14.1 Routes

```
/hrms/entry                     HrmsGate — decides where the user lands
/hrms                           HrmsWorkspace shell
  /hrms                         HrmsHome
  /hrms/employees[/:userId]     directory / profile
  /hrms/departments             MasterManager kind="department"
  /hrms/designations            MasterManager kind="designation"
  /hrms/sanctioned-strength     SanctionedStrength
  /hrms/requisitions            RequisitionList
  /hrms/jd                      JdLibrary
  /hrms/postings                PostingList
  /hrms/candidates              CandidatePipeline
  /hrms/screening               ScreeningBoard
  /hrms/assessments             AssessmentBoard
  /hrms/interviews              InterviewBoard
  /hrms/offers                  OfferBoard
  /hrms/appointments            AppointmentBoard
  /hrms/onboarding              OnboardingBoard
  /hrms/dashboard               RecruitmentDashboard
  /hrms/reports                 RecruitmentReports
  /hrms/documents               DocumentCenter
  /hrms/document-types          DocumentTypeManager
  ── internal track ──
  /hrms/internal-requisitions   InternalRequisitionList
  /hrms/scorecards              ScorecardLibrary
  /hrms/reference-checks        ReferenceCheckBoard
  /hrms/telephonic-screening    TelephonicBoard                        (Phase INT-4)
  /hrms/negotiations            NegotiationBoard                       (Phase INT-10)
  /hrms/settings                HrmsSettings                           (Phase INT-5)
  /hrms/probation               ProbationBoard
  /hrms/exceptions              ExceptionLog
  ── Phase INT-2 ──
  /hrms/shortlist-reviews       ShortlistCommittee    (tab strip — a hiring stage)
  /hrms/preboarding             PreboardingBoard      (sidebar — governance)
  /hrms/talent-pool             TalentPool            (sidebar)
  /hrms/salary-bands            SalaryBandManager     (sidebar, admin)
  /hrms/communications          CommTemplates         (sidebar, admin)
  /hrms/policies                PolicyRegister        (sidebar, admin)

Public (no auth): /apply/:code  /assess/:code  /offer/:code  /onboard/:code  /appointment/:code
                  /survey/:code                                        (Phase INT-2)
```

### 14.2 Two navigations, deliberately disjoint

- **Workspace tab strip** (`HrmsWorkspaceBar`) owns the pipeline: Hiring Req → Job Descriptions →
  Job Postings → Candidates → HR Screening → Assessments → Interviews → Offers → Appointments →
  Onboarding → Reports, plus the internal-track pipeline tabs (Internal reqs, Scorecards,
  References, **Shortlisting**).
- **Sidebar** (`Sidebar.jsx` `hrmsSubmodules`) keeps Dashboard, Employees, Documents, Recruitment
  (the way *in*), the governance screens (Probation, Exceptions, **Pre-boarding**,
  **Talent Pool**) and the admin-only masters (Departments, Designations, Document Types,
  Sanctioned Strength, **Salary Bands**, **Communications**, **Policy Register**).

`HRMS_WORKSPACE` in Sidebar.jsx lists the strip's routes so "Recruitment" stays highlighted
anywhere in the workspace. **The two lists must stay disjoint.**

### 14.3 `HrmsContext`

Fetches `GET /hrms/health` once on mount and holds `role`, `capabilities`, `isInternal`,
`companyId`, `companies`, `scope` and `can(cap)`.

**Fails closed**: while loading and on any error, `can()` returns false. Client-side users cannot
switch company scope — the server pins them, so `setCompanyId` is a no-op for them.

---

## 15. API reference

All authenticated routes are under `/api/hrms` (173 endpoints). Every one takes an optional
`company_id` (ignored for client-side callers).

<details>
<summary><b>Module, masters, people</b></summary>

```
GET    /health                          resolved role + capabilities  (the gate)
GET    /audit                           audit trail            audit.read
GET    /companies                       companies this caller may scope to
GET    /departments                     POST /departments  PATCH/DELETE /departments/{id}
GET    /designations                    POST /designations PATCH/DELETE /designations/{id}
GET    /masters/suggestions             derive masters from the user directory
GET    /employees                       list + search + filters
GET    /employees/linkable              login users with no profile yet
GET    /employees/me                    self-service
POST   /employees                       create a profile
GET    /employees/{user_id}             PATCH /employees/{user_id}
GET    /employees/{user_id}/hierarchy   reporting chain
POST   /employees/link/{employee_code}  attach a profile to a login user
```
</details>

<details>
<summary><b>Requisitions, JDs, postings, SLA</b></summary>

```
GET    /requisitions                    POST /requisitions
GET    /requisitions/{no}               PATCH /requisitions/{no}   DELETE /requisitions/{no}
POST   /requisitions/{no}/approve       client:   hr-approve | md-approve | escalate-approve | reject
                                        internal: hr-verify | budget-approve | escalate-approve
                                                  | scorecard-approve | *-reject
POST   /requisitions/{no}/close         Open|Hired|Closed|Hold|Cancel
GET    /requisitions/{no}/sla           milestone status for this requisition
GET    /sla/breaches                    open breaches across the company
GET    /jd                              GET/PATCH /jd/{jd_no}
GET    /postings                        POST /postings  PATCH/DELETE /postings/{code}
```
</details>

<details>
<summary><b>Candidates and screening</b></summary>

```
GET    /candidates                      POST /candidates
POST   /candidates/screen               bulk, max 200
GET    /candidates/{uk}                 PATCH/DELETE /candidates/{uk}
GET    /candidates/{uk}/journey         audit-derived history
POST   /candidates/client-response      the client's verdict
POST   /candidates/{uk}/scorecard-evaluate   score against the position scorecard
```
</details>

<details>
<summary><b>Assessments, interviews, offers</b></summary>

```
GET    /assessments                     GET /assessments/assessable
POST   /assessments                     POST /assessments/{no}/review
GET    /interviews                      GET /interviews/schedulable
POST   /interviews                      PATCH/DELETE /interviews/{no}
POST   /interviews/{no}/evaluate        GET /interviews/{no}/invite.ics
GET    /offers                          GET /offers/offerable
POST   /offers                          PATCH/DELETE /offers/{no}
POST   /offers/{no}/send                POST /offers/{no}/revoke
POST   /offers/{no}/approve             Management/Finance sign-off (internal track)
```
</details>

<details>
<summary><b>Appointments and onboarding</b></summary>

```
GET    /appointments                    GET /appointments/eligible
POST   /appointments                    GET/PATCH /appointments/{no}
POST   /appointments/{no}/send          POST /appointments/{no}/cancel
GET    /onboarding                      GET /onboarding/onboardable
POST   /onboarding                      GET/PATCH /onboarding/{onb_no}
POST   /onboarding/{no}/bg              POST /onboarding/{no}/verify
POST   /onboarding/{no}/documents       POST /onboarding/{no}/checklist
POST   /onboarding/{no}/generate-id     mints EMP-… and the employee profile
```
</details>

<details>
<summary><b>Internal track — scorecards, references, probation, exceptions</b></summary>

```
GET    /scorecards                      POST /scorecards
GET    /scorecards/{scr_no}             PATCH /scorecards/{scr_no}
POST   /scorecards/{scr_no}/approve
GET    /reference-checks                POST /reference-checks
GET    /reference-checks/{ref_no}       PATCH /reference-checks/{ref_no}
GET    /telephonic-screenings           POST /telephonic-screenings
GET    /telephonic-screenings/screenable    the work queue: who to ring today
GET    /telephonic-screenings/{tel_no}  PATCH /telephonic-screenings/{tel_no}
GET    /negotiations                    POST /negotiations
GET    /negotiations/{neg_no}           GET  /candidates/{uk}/negotiation   the §16 comparison surface
GET    /settings                        the company rule set + the shipped defaults
PATCH  /settings                        override; validated against what is in force
POST   /settings/reset                  follow the defaults again (optional `keys`)
GET    /internal-requisitions/tracker   one row per internal requisition, every stage
GET    /holidays                        this company's working calendar (optional `year`)
POST   /holidays                        POST /holidays/import   DELETE /holidays/{date}
GET    /probation                       GET /probation/due
POST   /probation                       GET/PATCH /probation/{prb_no}
POST   /probation/{prb_no}/confirm      Confirmed | Extended | Terminated (signature required)
POST   /personnel-file/close            requires a confirmed probation
GET    /exceptions                      POST /exceptions
GET    /exceptions/{exc_no}             POST /exceptions/{exc_no}/approve
```
</details>

<details>
<summary><b>Phase INT-2 — the remaining SOP controls</b></summary>

```
GET    /shortlist-reviews               POST /shortlist-reviews          SOP 5
GET    /shortlist-reviews/{slr_no}      PATCH /shortlist-reviews/{slr_no}
GET    /interview-windows               POST /interview-windows          Annexure C
PATCH  /interview-windows/{id}          DELETE /interview-windows/{id}
GET    /preboarding                     GET  /preboarding/due            SOP 6
POST   /preboarding
GET    /salary-bands                    POST /salary-bands               Annexure C
GET    /salary-bands/{band_no}          PATCH /salary-bands/{band_no}
GET    /salary-bands/for-requisition/{request_no}   the budget gate's pre-fill
POST   /candidates/{uk}/talent-pool     consent REQUIRED; expiry <= retention
POST   /candidates/{uk}/source-to/{request_no}      copies the CV forward
GET    /candidates?talent_pool=&tags=   the pool is a FILTER, not a collection
GET    /communications                  POST /communications/send        Annexure C
GET    /communications/templates        PATCH /communications/templates/{key}
GET    /surveys                         GET  /surveys/results            SOP 10
GET    /analytics/internal-kpis         all 8 SOP KPIs
GET    /probation/{prb_no}/statutory    what blocks confirmation         SOP 11
GET    /policies                        POST /policies                   SOP 14
GET    /policies/due                    GET  /policies/{policy_key}
POST   /policies/{policy_key}/revisions POST /policies/{policy_key}/approve
GET    /purge-batches                   GET  /purge-batches/{batch_no}   SOP 13
POST   /purge-batches/{batch_no}/approve            MD only, signed, REDACTS
GET    /records/{entity}/{business_no}/document     five printable forms  SOP 9
```
</details>

<details>
<summary><b>Clients, engagements, links, documents, sanction, analytics</b></summary>

```
GET    /clients                         GET /clients/{client_id}     READ-ONLY
GET    /client-engagements              POST /client-engagements
GET    /client-engagements/{id}         PATCH /client-engagements/{id}
GET    /client-engagements/{id}/members POST /client-engagements/{id}/members
DELETE /client-engagements/{id}/members/{user_id}
GET    /links                           GET /links/{link_id}
POST   /links/{id}/revoke               POST /links/{id}/reissue
GET    /document-types                  POST /document-types  PATCH/DELETE /document-types/{id}
GET    /documents                       GET /documents/checklist
POST   /documents                       GET/PATCH/DELETE /documents/{doc_no}
POST   /documents/{doc_no}/status       GET /documents/{doc_no}/url
GET    /sanctioned-strength             GET /sanctioned-strength/position
POST   /sanctioned-strength             PATCH/DELETE /sanctioned-strength/{id}
GET    /analytics/dashboard             GET /analytics/funnel
GET    /analytics/breakdown             GET /analytics/positions
GET    /reports/{entity}                GET /reports/{entity}/export
```
</details>

---

## 16. What is NOT built

### 16.1 Declared but unimplemented

`models/hrms.py` declares collection names for later phases that have **no service, no route and
no UI**. Verified: each is referenced **only** in the models file.

```
hrms_settings           hrms_permissions
hrms_leaves             hrms_leave_balances       hrms_holidays
hrms_attendance         hrms_punch_segments       hrms_attendance_corrections
hrms_payroll_runs       hrms_payroll_records
```

**There is no leave management, no attendance/punch tracking and no payroll.**
`EmployeeProfileIn` carries salary fields and `employee.salary.*` capabilities exist, but they
are storage and access control only — nothing computes a payslip.

Also absent:

- **A per-user RBAC console** (roadmap Phase 11). The `ROLE_CAPABILITIES` matrix *is* the
  permission model today; there are no per-user grants on top. (Phase INT-5 implemented
  `hrms_settings` for the module's *rules*; per-user *permissions* remain unbuilt.)
- **A public client portal.** Client verdicts are recorded by an HRMS user on the client's
  behalf; a portal would mean a second unauthenticated surface with its own threat model.
- ~~**Public-holiday awareness in SLA maths.**~~ **Built in Phase INT-6** — see
  [§8.14](#814-the-working-calendar-phase-int-6). It is still a decision taken
  deliberately rather than by default: the flag ships OFF per company, and the calendar
  is HRMS's own rather than the ERP's global master.
- **A separation WORKFLOW.** Phase INT-2 added `separation_date` to the employee profile so
  the 90-day retention KPI has something honest to read, and stopped there. A manually set
  date is enough to make the figure true; resignation, notice periods and exit interviews are
  a feature with their own approvals, not a side effect of a reporting fix.
- ~~**A scheduler.**~~ **Built in Phase INT-3** — see [§8.11](#811-the-scheduled-jobs-phase-int-3).
  `sweep_open_breaches()`, the probation and pre-boarding reminders, `notify_due_reviews()`
  and the retention *proposal* are now driven by `hrms_scheduler_service`, called from the
  ERP's existing reminder loop. Still not fired from an HTTP request: that would make
  governance alerting depend on somebody opening a screen.
- **Hard deletion in the purge.** `PURGE_TARGETS` declares a `delete` mode and every entry
  uses `redact`. The vocabulary exists so a future decision to hard-delete something is a
  reviewable data change rather than a behaviour that appears one day.

### 16.1a Phase INT-2 — deliberate deferrals inside a built block

Stated here rather than left to be inferred, per the phase's own definition of done:

- **Panel COMPOSITION is checked; panel ATTENDANCE is not.** The module knows who was
  rostered, not who turned up. Recording attendance would need a second act after the
  interview that nobody currently performs, and an unrecorded one would read as an absence.
- **`designation_level` is a new field, not a rename of `level`.** `hrms_designations.level`
  is an integer grade a company numbers however it likes; the seniority band the SOP's rules
  are stated in is a separate, closed four-value field. Overloading one column with both
  would have broken every row that already carries a grade.
- **Interview windows warn and never block.** A hard refusal would make an urgent hire
  impossible at 4pm on a Friday, and would push the booking off-system where nothing sees it.
- **Nothing is gated on pre-boarding.** It is engagement tracking. Gating onboarding on a
  touchpoint would punish the candidate for HR being busy and turn a useful signal into a box
  somebody ticks to unblock themselves.
- **The offer-summary check warns at send time, after the letter has gone.** The SOP
  recommends the summary; it does not mandate it, and refusing to send an approved offer over
  a missing courtesy email is how a control gets routed around.

### 16.2 Multi-client: what is and is not secured

The client-scope foundation ships the *primitive*. It is **not** yet applied to any pipeline
surface:

| Surface | Client-scoped? |
|---|---|
| engagements, membership, `/hrms/health` | ✅ yes |
| candidates | ❌ **no** — `_scope_filter` narrows by company + manager-own only |
| interviews, offers, appointments, onboarding | ❌ **no** |
| documents / CVs | ❌ **no** |
| analytics, reports, exports | ⚠️ `client_id` is a **reporting filter**, not an authorisation narrowing |
| notifications | ❌ **no** — fan-out is company + governance role |
| requisitions | ⚠️ `client_id` stored and validated on write; **not** yet a listing filter |

**Consequence: do not provision a real client user yet.** `HrmsRole.CLIENT` holds exactly three
capabilities (`module.access`, `requisition.read`, `client.read`) precisely because the row-level
narrowing that would make anything more safe does not exist. Granting a client user
`candidate.read` today would hand them every *other* client's pipeline — the capability is not
the missing piece, the scope is.

`assert_client_allowed()` and `require_engagement()` exist and are tested, but are **deliberately
not wired** into the write paths: turning them on now would refuse every existing client-track
requisition, because no engagement has been opened.

Child collections were deliberately **not** denormalised with `client_id`. The chosen model
derives client scope through `request_no → requisition.client_id`, which needs no migration,
keeps one source of truth, and cannot drift.

---

## 17. Testing

**61 self-contained test files** in `backend/app/services/hrms/tests/`, ~23,300 lines.

**House convention:** no pytest, no live database. Fake collections, ASCII output, exit 1 on
failure.

```bash
# from backend/
python -m app.services.hrms.tests.test_phase5_candidate

# all of them
for f in app/services/hrms/tests/test_*.py; do
  python -m "app.services.hrms.tests.$(basename $f .py)"
done
```

`FakeCollection` (in `test_phase2_employee.py`) is shared by every test and implements the
`find`/`find_one`/`aggregate`/`update_*` subset the services actually use — anything else raises
rather than silently returning nothing.

### Coverage map

| Group | Files |
|---|---|
| Phase 1–11 unit + integration | `test_phase1_*` … `test_phase11_*` (26 files) |
| Internal track | `test_internal_requisition_chain`, `test_internal_budget_gate`, `test_internal_offer_gates`, `test_internal_kpis` |
| Governance | `test_scorecard`, `test_reference_gate`, `test_probation`, `test_exceptions`, `test_sla` |
| Cross-cutting | `test_capability_parity`, `test_client_scope`, `test_e2e_recruitment_journey` |
| Phase INT-2 | `test_int2_panel_composition`, `test_int2_final_round_gate`, `test_int2_shortlist_committee`, `test_int2_score_bands`, `test_int2_sla_date_anchored`, `test_int2_salary_band`, `test_int2_talent_pool`, `test_int2_comms`, `test_int2_surveys`, `test_int2_internal_kpis`, `test_int2_statutory_gate`, `test_int2_retention_purge`, `test_int2_preboarding`, `test_int2_policy_register` (14 files) |

**Structural tests worth knowing:**

- `test_capability_parity.py` — backend `Cap` enum vs frontend `CAP` map, by regex.
- `test_phase10_analytics.py` — greps the analytics service source for `insert_`/`update_`/
  `delete_` to prove it never writes. **A comment containing those words fails the test.**
- `test_internal_budget_gate.py` — calls `budget_approval_is_mandatory()`, so a future shortcut
  edge that deletes the gate fails loudly.
- `test_e2e_recruitment_journey.py` **§13** — walks a whole client-track hire and then asserts
  STRUCTURALLY that every Phase INT-2 control is silent on it, that the two tracks still read
  from separate transition tables, and that no status was added to `AppStatus`. "The client
  track is unchanged" is a claim, and this is what makes it checkable.
- `test_int2_preboarding.py` — asserts a NEGATIVE: that no pipeline service imports the
  pre-boarding module, so a later change that quietly made a touchpoint a precondition would
  be caught.
- `test_int2_surveys.py` — asserts the anonymity promise from four angles, including that the
  audit line names the response rather than the employee.

---

## 18. Traps and gotchas

In rough order of likelihood:

1. **Shortlisting an assessment-required posting skips `Shortlisted`.** It lands the candidate
   directly on `Assessment Pending`, and `Shared with Client` is **not** reachable from there. If
   a role needs the client-share flow, its posting must have `requires_assessment: false`.
   Sharing happens *before* testing.

2. **An internal requisition blocks all sourcing before the budget gate.** Publishing a posting
   or creating a candidate returns 409 while it sits in `Pending HR Verification` or
   `Pending Budget Approval`. If a seed or test cannot add candidates, check the track first.

3. **An internal offer cannot be created and sent in one call.** 409 by design — Management's
   approval happens between the two.

4. **Only a `Positive` reference clears the internal offer gate.** "Unable to Verify" does not;
   log an approved `Reference Check Waived` exception instead.

5. **Interviews cannot be scheduled in the past.** Any fixture that back-dates one gets a 422.

6. **`reviewed` is not `rank >= rank(Under Review)`.** `Applied` shares rank 1.

7. **A position with no sanctioned figure escalates.** Fail-closed by design. If every
   requisition in a test suddenly climbs the ladder, that is why.

8. **An `Employee` referral needs a resolvable employee code**, or the application 422s.

9. **Adding a capability requires editing two files** — `models/hrms.py` and
   `frontend/src/features/hrms/access.js` — or the parity test fails and controls silently
   disappear.

10. **Do not write `update_many` (or `insert_one`, etc.) in a comment inside
    `hrms_analytics_service.py`.** The read-only test greps the source text.

11. **`client_id` is not a tenant.** Never use it as a security check. `?client_id=` is a filter;
    route it through `assert_client_allowed()`.

12. **`scope_client_ids` returning `None` is not the same as returning `[]`**, and
    `client_filter([])` must stay `{"client_id": {"$in": []}}`. A caller that "optimises" the
    empty case to `{}` turns *no clients* into *all clients*.

13. **Adding a status to `AppStatus` requires an entry in `STAGE_RANK`.** Unknown statuses rank
    0 — counted in totals but credited to no funnel stage.

14. **`requisition_track` is immutable after creation**, and its absence means `client`. Never
    backfill it onto historical rows without deciding what that changes.

15. **A managerial scorecard needs two *different* people.** The MD may stand in for the hiring
    manager on an ordinary role, never on a managerial one.

16. **The two navigations must stay disjoint** — see [§14.2](#142-two-navigations-deliberately-disjoint).

17. **Seed markers are load-bearing.** Two datasets coexist: `recruitment-demo` and
    `realistic-ops`. Each script's `--undo` deletes only its own marker. Never widen that filter.

### Phase INT-2 additions

18. **`SLA_MILESTONES` is a list of DICTS, not tuples.** It grew an `anchor` discriminator so
    the milestone-anchored and date-anchored rows live in one table. Anything unpacking it as
    `for key, label, target, measured_from in ...` will fail loudly — which is the point.

19. **Only four SLA keys are stampable.** `stamp()` raises `ValueError` for anything else. A
    date-anchored milestone has nothing to stamp: its due date IS a field on another record,
    so writing one would store a value `sla_for` never reads.

20. **The band on a REQUISITION is the authority; the band MASTER is a convenience.**
    `assert_within_band` reads `approved_salary_band_min/max` off the requisition and never
    `hrms_salary_bands`. Editing a master must not retroactively legalise — or criminalise —
    an offer approved last month.

21. **A published salary band's FIGURES cannot be edited.** Publishing a new band for the
    same position supersedes the old one. Editing in place would rewrite what Finance agreed
    and leave the requisitions approved against it citing a figure nobody ever set.

22. **`Relaxed Scorecard` lifts TWO gates now** — the scorecard gate and the shortlisting
    committee. Use `gates_for_exception_type()`; inverting `EXCEPTION_UNBLOCKS` into a dict
    silently keeps only one of them.

23. **`designation_level` is NOT `level`.** `level` is the integer grade a company already
    had; `designation_level` is the closed four-value seniority band the SOP's panel and
    final-round rules are stated in. An absent band reads as `mid`, never as "unbanded".

24. **Talent-pool tags are stored lower-cased**, and the query lower-cases too. Writing a
    tag straight into the collection with different capitalisation makes it unfindable.

25. **`set_talent_pool` only writes tags when the caller SENT some.** A call that renews
    consent must not wipe the tags somebody spent time adding.

26. **The survey aggregation refuses a figure below 5 responses — including the
    per-question breakdown.** Three respondents' question-level averages reconstruct most of
    an individual response, so the two suppress together. Never relax one without the other.

27. **`fire_event` and `send_template` swallow every delivery error.** That is deliberate —
    an acknowledgement email must never fail a job application — but it means a broken mail
    path shows up as `Failed` rows in `hrms_comm_log`, not as an exception. Seed scripts
    patch both, alongside `notify_user`.

28. **The purge REDACTS.** Fields are set to `None` rather than `$unset`, so a purged row
    still matches `{"can_email": None}` and a later audit can find exactly what was emptied.
    `$unset` would make a purged record indistinguishable from one that never had the field.

29. **A record with no `retention_until` is NEVER purged.** An absent date means nobody
    computed one — a gap to investigate, not a licence to delete.

30. **The internal application form requires `eeo_ack` and `data_use_ack`.** A fixture or
    integration that posts to `/apply/{code}` for an internal-track posting without them gets
    a 422. Client-track applications are unchanged.

31. **The two navigations are still disjoint, and Shortlisting is in the TAB STRIP.** It is a
    hiring stage between screening and the final interview. Pre-boarding, Talent Pool, Salary
    Bands, Communications and the Policy Register are sidebar governance.

### Phase INT-4 additions

32. **Any internal-track test that schedules an interview now needs a PASSING telephonic
    screen.** `test_int2_panel_composition` seeds one per candidate for exactly this reason.
    Without it every booking 409s on the telephonic gate, and a panel-composition failure
    stops telling you which of the two controls refused.

33. **`AppStatus` is 26 now, and the e2e no longer counts it as a proxy for "the client track
    is unchanged".** It asserts the property directly instead: every status ranked and
    column-mapped, the direct `Shortlisted → Interview` edge intact, and the journey's
    candidate never holding a telephonic status. Adding a status means updating
    `STAGE_RANK` **and** `PIPELINE_COLUMNS` — `test_phase5_candidate` checks the column
    totals, so a status in neither is caught, but a status in the *wrong* column is not.

34. **`No Answer` moves nobody, by design.** `TELEPHONIC_STATUS_FOR_OUTCOME` maps it to
    `None`. A caller that "fixes" this by mapping it to `TELEPHONIC_REJECTED` turns an
    unanswered phone into a decision about a candidate.

35. **The telephonic gate is silent once a candidate has any interview record.** It guards
    entry into interviewing, not every round — see [§8.12](#812-telephonic-screening-phase-int-4).
    Tightening it to every round would strand anybody who was mid-pipeline when the phase
    shipped.

36. **Do not read `current` after the update in `update_screening`.** Whether it still holds
    the pre-update state depends on whether the driver returned a copy or a live reference;
    the previous outcome is captured *before* the write for that reason. A status move that
    works against real Mongo and silently does nothing against a fake is the worst kind of
    bug to own.

### Phase INT-5 additions

37. **A settings row is stored MERGED, not sparse.** `validate()` returns the whole map with
    the change applied, so the row reads as "the rules this company adopted". A caller that
    "optimises" it to store only the changed name makes the row unreviewable without holding
    the defaults in your head — and makes `reset` ambiguous.

38. **A stored value equal to the default is NOT the same as following the default.** The
    stored one stays put if the module default ever moves. Pruning equal values would make a
    deliberately-chosen compliance number drift silently. `POST /settings/reset` is the only
    way back to tracking.

39. **`sla_for`, `sweep_open_breaches` and `escalate_if_breached` take an optional `config`.**
    Any new caller inside a LOOP must resolve once and pass it down, or it reads the settings
    row per record — and a mid-sweep edit would judge half the run against different targets.

40. **`score_band(value)` with no second argument is still the module default**, and every
    pre-INT-5 caller and test relies on that. It accepts either `[(floor, label)]` or the
    config's `{label: floor}` and sorts descending regardless, so a JSON round-trip cannot
    reorder somebody into the wrong band.

41. **`bool` is a subclass of `int`.** `_number()` rejects booleans *before* the cast, or
    `True` would sail through as an SLA target of 1 day.

42. **Adding a config key means adding it to `CONFIG_SPEC` AND to `ConfigUpdateIn`.** The
    Pydantic model is what lets the field through the route at all; the spec is what validates
    it. A key in one and not the other is silently unsettable or silently unvalidated.

### Phase INT-6 additions

43. **`holiday_set()` returns `None` OR a set, and they mean different things.** `None` =
    this company does not honour a calendar. `set()` = it does, and has no dates. Collapsing
    them makes a company that opted in but never filled the calendar in indistinguishable
    from one that opted out. Same three-way rule as `scope_client_ids`.

44. **Never read the ERP's `holidays` collection from HRMS.** It has no `company_id`, so one
    admin's edit would move every entity's SLA due dates. `hrms_holiday_service.import_from_erp`
    is the ONE place that touches it, and it COPIES. A test greps the SLA and config services
    to prove they do not.

45. **`working_days_between` / `add_working_days` take the calendar as an argument.** They are
    pure and a lot depends on that. A caller inside a LOOP must resolve the calendar once and
    pass it down — `sla_for`, `sweep_open_breaches` and `escalate_if_breached` all accept a
    pre-resolved `calendar` for exactly this.

46. **Turning `honour_holidays` on moves existing breach figures.** That is why it ships off
    and why the SLA response reports `counts_holidays` and a `basis` string. Anything that
    flips it silently — a migration, a default change — turns a compliance report into a
    different report with no notice.

47. **`add_working_days` counts forward and then pulls BACK.** Forward counting already skips
    non-working days, so the pull-back loop only bites on a zero-day target measured from a
    weekend or a holiday. Both walks are bounded by `MAX_CALENDAR_SPAN_DAYS`, or a calendar
    that marked everything non-working would spin forever.

48. **A KPI that measures a target must read the CONFIGURED one.** `internal_kpis` had a
    hard-coded `<= 15` while the SLA screen read the company's setting. Two answers to one
    question. Any new KPI with a threshold in it needs the same treatment.

### Phase INT-7 additions

49. **`hrms_tracker_service.py` is under the same source-text grep as analytics.** The three
    write prefixes must not appear in the file, comments and docstrings included — the INT-7
    test greps the text, not the behaviour. (The first draft of the module failed its own
    test by *naming* the tokens in the docstring.)

50. **Do not add a per-row query to the tracker.** The whole design is eight reads per page;
    the test counts `find()` calls and fails if the count grows with the row count. New data
    on a row means a ninth batched read, never a read inside `_row()`.

51. **`FakeCursor.sort()` is a no-op in the shared test harness.** An ordering assertion
    through the fake proves nothing either way — pin the sort the service *asks for* (by
    grepping the source) rather than the order the fake returns.

52. **Tracker fixtures need `_source_collection` + `role` on fake users**, or `hrms_role`
    resolves them to None, `_visibility_filter` returns `{}`, and a scoping test passes for
    the wrong reason.

53. **Two SLA clocks start at the raise date** — budget approval AND shortlist-ready. A test
    (or a company) that moves one target and expects the requisition to stop reading as
    breached will be corrected by the other clock. That is the tracker being right.

### Phase INT-8 additions

54. **KPI filters narrow the requisition query and NOTHING else.** Every downstream read
    flows from `request_nos`; filtering any of them separately is how a filtered numerator
    meets an unfiltered denominator. New filter = one more clause on the requisition query.

55. **`_ratio` tiles carry `numerator`/`denominator`/`eligible_n` — there is no `actual_n`.**
    Asserting on a field name that does not exist fails as a KeyError, not a clean FAIL.

56. **The requisition does not carry `designation_level`.** Anything reporting a level must
    resolve it through the designation master (`designation_level()` — unbanded reads as
    mid). The INT-7 tracker shipped reading the nonexistent field and was corrected here.

### Phase INT-9 additions

57. **Scorecard criteria use `label`, not `name`.** `_validate_criteria` 422s on a missing
    label; a fixture written with `name` fails before anything interesting runs.

58. **A probation EXTENSION must clear `reminders_sent`.** The INT-3 tiers are recorded on
    the record; without the reset an extended probation is never reminded about its new end
    date. If you add another path that moves `ends_on` forward, reset the field there too.

59. **Notify calls go AFTER the business write, and are imported late.** After: so a
    notification can never describe a write that then failed. Late: so seeds and tests
    patching `hrms_notify_service` attributes still silence everything — a module-top
    `from … import notify_user` binds early and escapes the patch.

60. **Three decisive writes are compare-and-swaps; keep them that way.** The scorecard
    signature CASes on the approvals array it merged from, the probation decision on the
    Pending state, and the scheduler's tier burn on `(ends_on, Pending)`. Each exists
    because the race it closes produced duplicate emails or a silently lost signature —
    found by the INT-9 adversarial verification, not by the unit tests.

61. **`FakeCollection._matches` now has Mongo's array-EQUALITY arm.** `{field: <list>}`
    matches an array field that equals the literal, not only one that contains it. Without
    it, every equality-CAS on a list field reads as a phantom write conflict in tests.

62. **A FakeCollection `find_one` may hand back a live reference.** Any value compared
    after an `update_one` on the same doc must be captured BEFORE the write — this bit
    `update_screening` (trap 36), then the probation reviewer handover, in the same phase
    that documented the trap. Read-before-write is the rule, not a per-site fix.

63. **The scorecard "sent back" and "needs approval" flows resolve the raiser's ROLE.**
    A raiser who cannot approve (any employee may raise a requisition) is not asked to;
    the HOD governance role is broadcast instead. `notify_hrms_role` also grew
    `exclude_user_ids` so a person addressed by name is not re-addressed by their role's
    fan-out.

### Phase INT-10 additions

64. **A `float` Pydantic field accepts `NaN`.** It passes every `<`/`>` test, reads as
    "within", and is not JSON — one crafted request leaves a row that 500s every read of its
    collection. Declare money fields `Field(..., gt=0, allow_inf_nan=False)` AND check
    `math.isfinite` in the service; neither alone is enough for direct callers.

65. **Business ids are minted per company and rendered without one.** Any unique index on a
    bare `*_no` refuses the second tenant's first record of the year. Always composite with
    `company_id` — `uniq_company_neg_no` is the pattern.

66. **A new candidate-level collection needs row scoping on day one.** Import the candidate
    pipeline's `_scope_filter` / `_require_visible`; an `actor` parameter that is accepted
    and never read is the tell.

67. **Mongo hands back naive UTC; the API hands in aware IST.** Compare instants through
    `_as_utc()`, never raw — a raw compare turned an unchanged time into a reschedule with
    a re-notify and a re-email. Label rendered times with the zone they are shown in.

68. **A warning must be worded by what happened, not what was attempted.** `fire_event`
    returns the comm-log status for exactly this; "the candidate has been told" is a claim,
    and a claim nobody checked is how a warning becomes a lie.

69. **Every new Annexure control is keyed on `_is_internal(req)` at every entry point** —
    including the reschedule path, which must re-resolve the requisition. Gap 9 shipped
    running on the client track and was caught by verification, not by the suite.

70. **The settings screen renders from `describe()`, so anything the UI must know about a
    setting — `optional_names` included — has to be in that payload.** A server-side
    capability the payload does not mention is one the screen cannot offer.

---

## Appendix — seeding test data

```bash
# One requisition, end to end — 6 candidates, one hire
python scripts/seed_hrms_recruitment_demo.py --company <id> [--dry-run|--undo]

# A full book of work — 8 requisitions across 5 clients, 61 candidates, 3 hires
python scripts/seed_hrms_realistic_ops.py --company <id> [--dry-run|--undo]
```

Both drive the **real services**, so every record is created the way the application creates it:
correct business ids, legal stage transitions, full audit trail, populated link registry. Both
suppress notifications and S3 uploads, stamp everything with `demo_seed`, and `--undo` removes
only that marker.

`seed_hrms_realistic_ops.py` produces a deliberately realistic spread — CVs nobody has opened,
CVs a client is sitting on, parked candidates, a live offer awaiting an answer, interviews booked
but not evaluated, and requisitions in every closing state including one raised over sanction so
it climbs the escalation ladder.

**Phase INT-2 added a fifth step to that script: one INTERNAL requisition that exercises every
new gate.** It deliberately produces three different outcomes on one vacancy, because a dataset
where every control is satisfied teaches nothing about what the controls do:

- one candidate walks the whole track — committee, panel, references, Management-approved
  offer, onboarding, probation confirmed, personnel file closed;
- one is **left blocked** at probation confirmation by a background check still in progress,
  so the screens show what an open statutory control actually looks like;
- one is **released** past the shortlisting-committee gate by an approved exception, so the
  exception log holds a real entry that really lifted something.

It also leaves live governance state to look at: a standing salary band the budget gate
pre-filled from, an interview window, a committee sitting convened and not decided, a
pre-boarding touchpoint flagged **At Risk** with a counter-offer disclosed, and a talent-pool
entry with recorded consent.

```bash
# Propose a retention purge (writes nothing without --propose)
python scripts/hrms_retention_purge.py --company <id>
```

**Invented data only:** emails at `example.com` (RFC 2606, unregistrable), phone numbers
`+91 00000 xxxxx` (no Indian mobile begins with 0), Aadhaar values beginning `0000` (no real
Aadhaar does). Real users are read but never written.
