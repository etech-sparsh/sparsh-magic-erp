# HRMS Module — Complete Overview

> **Audience:** an engineer or AI agent picking up this module for the first time.
> **Purpose:** everything you need to reason about HRMS without reading all 15,000 lines first.
>
> This describes what **is built and running**, not what is planned. Where something is
> declared but not implemented, it says so explicitly (see [§16](#16-what-is-not-built)).

---

## Table of contents

1. [What this module is](#1-what-this-module-is)
2. [File map](#2-file-map)
3. [Security model](#3-security-model)
4. [Core invariants](#4-core-invariants)
5. [Data model](#5-data-model)
6. [The recruitment flow, end to end](#6-the-recruitment-flow-end-to-end)
7. [Candidate lifecycle](#7-candidate-lifecycle)
8. [The client dimension](#8-the-client-dimension)
9. [Approval chain, sanction and budget](#9-approval-chain-sanction-and-budget)
10. [Supporting subsystems](#10-supporting-subsystems)
11. [The public surface](#11-the-public-surface)
12. [Analytics and reports](#12-analytics-and-reports)
13. [Frontend architecture](#13-frontend-architecture)
14. [Complete API reference](#14-complete-api-reference)
15. [Testing](#15-testing)
16. [What is NOT built](#16-what-is-not-built)
17. [Traps and gotchas](#17-traps-and-gotchas)

---

## 1. What this module is

HRMS is an **opt-in, per-company module** inside the Sparsh ERP covering the employee master
and the full recruitment pipeline, from raising a vacancy to the new joiner's employee record.

It runs **two hiring tracks on one platform**, chosen per requisition by
`requisition_track` and defaulting to `client`:

| | **Client hiring** (`client`) | **Internal hiring** (`internal`) |
|---|---|---|
| Vacancy belongs to | a client organisation | Sparsh Magic itself |
| `client_id` | set | **null** — and a `client_id` on an internal requisition is a 422 |
| Approval chain | HR review → MD | HR verification → budget → scorecard |
| Before an offer | client verdict, background verification | reference check, salary band |
| A CV goes | **out**, to the client, who decides | nowhere; Sparsh decides |
| After joining | client handover | induction → probation → confirmation |

The **agency model** shapes the client track: a CV is shared with a client who returns a
verdict, requisitions are tagged with the client they are filled for, and analytics slice
client-wise. The **internal track** has none of that and adds its own governance instead —
a mandatory budget gate, a position scorecard, a reference check and a probation.

They are two tracks, not two systems. Candidates, interviews, offers and onboarding are one
set of collections and one set of screens; the track selects which gates apply. **The track
is immutable after creation** (409): an approval granted under one track's rules means
nothing under the other's.

The module is switched on per company with `companies.hrms_enabled`. **A missing flag means
OFF** — nothing is exposed until it is explicitly enabled (unlike ORM, which defaults on).

### The one-paragraph version of the flow

*(The paragraph below traces the CLIENT track, which is the module's original spine. The
internal track's own chain is in §9.)*

A hiring manager raises a **requisition** with its **job description**. HR reviews it, the MD
approves it (via an **escalation ladder** if it exceeds sanctioned headcount). HR publishes a
**job posting**, which mints exactly **one public application link**. Applicants apply through
that link and become **candidates**. HR **screens** them in bulk, **shares** the good ones with
the client, and records the client's **verdict**. Survivors sit an **assessment**, then
**interview** rounds. A pass at the MD round marks them **Selected**. An **offer** goes out;
if accepted, an **appointment letter** follows, then **onboarding** — KYC, background check,
checklist — ending in a generated **employee ID** and a real employee record.

---

## 2. File map

### Backend

```
backend/app/
  models/hrms.py                      2,658 lines — THE single source of truth
                                      enums, state graphs, capabilities, role tables,
                                      collection names, id formats, pydantic API models
  routes/hrms.py                      1,793 lines — every authenticated endpoint
  routes/hrms_public.py                 233 lines — the 5 unauthenticated surfaces
  utils/hrms_access.py                  213 lines — identity → role → capability → scope
  utils/hrms_public_guard.py            333 lines — rate limits, access codes, uploads

  services/
    hrms_requisition_service.py       1,146   requisitions, JDs, approval chain, escalation
    hrms_analytics_service.py         1,008   dashboard, funnel, breakdowns, reports, export
    hrms_document_service.py            836   document types, uploads, verification
    hrms_employee_service.py            781   employee master, profiles, hierarchy
    hrms_onboarding_service.py          765   pre-onboarding, BG, checklist, employee ID
    hrms_candidate_service.py           711   candidates, screening, client verdicts
    hrms_appointment_service.py         628   appointment letters
    hrms_interview_service.py           609   scheduling, scorecards, round progression
    hrms_offer_service.py               603   offers, send, accept/decline, revoke
    hrms_posting_service.py             565   postings + the public application intake
    hrms_assessment_service.py          545   assessments, dual review
    hrms_link_service.py                375   the public-link registry
    hrms_sanction_service.py            345   sanctioned strength, position status
    hrms_masters_service.py             263   departments and designations
    hrms_referral_service.py            194   "how did you hear about this role"
    hrms_client_service.py              183   clients = the ERP's Companies (read-only)
    hrms_notify_service.py              147   in-app + email fan-out
    hrms_ics.py                         130   calendar invites for interviews
    hrms_audit_service.py                91   the append-only trail

  services/hrms/tests/                  29 test files, ~2,700 assertions
scripts/
  seed_hrms_recruitment_demo.py         one requisition end to end (marker: recruitment-demo)
  seed_hrms_realistic_ops.py            a full book of work      (marker: realistic-ops)
```

### Frontend

```
frontend/src/
  features/hrms/
    HrmsGate.jsx           entry redirect — decides where a user lands
    HrmsWorkspace.jsx      the module shell (outlet for every panel route)
    HrmsContext.jsx        fetches /hrms/health once; holds role + capabilities + company scope
    access.js              CAP map — MUST mirror the backend Cap enum exactly
    HrmsHome.jsx           module landing page

    common/                HrmsPageHeader, HrmsScopeBar, HrmsStates, HrmsWorkspaceBar
    people/                EmployeeDirectory, EmployeeProfile, AddEmployeeModal,
                           MasterManager (departments + designations), SanctionedStrength
    recruitment/           RequisitionList/Drawer/FormModal, ApprovalDialog, JdLibrary,
                           PostingList, CreatePostingModal, CandidatePipeline, ScreeningBoard,
                           CandidateJourney, AssessmentBoard, InterviewBoard, OfferBoard,
                           OfferPaper, AppointmentBoard, AppointmentPaper, OnboardingBoard
    analytics/             RecruitmentDashboard, RecruitmentReports, analyticsKit(.js/.jsx)
    documents/             DocumentCenter, DocumentPanel, DocumentTypeManager

  pages/hrms/public/       ApplyPage, AssessPage, OfferPage, OnboardPage, AppointmentPage
  services/hrmsApi.js      every HRMS API call the frontend makes
```

---

## 3. Security model

Four layers, applied in this order. **Every one of them is server-side.** The frontend gates
on what the server reports, never on its own derivation — that was a real defect the module
was rebuilt to prevent.

### 3.1 Identity — is this a Sparsh staff member or a client user?

`is_internal_user(user)` in `utils/hrms_access.py`. Precedence: `_source_collection` stamp
(`staff` / `learners`) → `tag` → role name. Same precedence `auth_controller` uses, so the two
cannot disagree.

### 3.2 Role — resolve the ERP user to one of eight HRMS roles

| ERP identity | HRMS role | Meaning |
|---|---|---|
| internal, `superadmin` | `ADMIN` | full owner, cross-company |
| internal, `admin`/`coach`/`staff` | `INTERNAL` | cross-company operator + support |
| client, `clientadmin` | `MD` | top of that company's ladder |
| client, `governance_role: MD` | `MD` | |
| client, `governance_role: HR` | `HR` | the recruitment + HR-ops operator |
| client, `governance_role: HOD` | `MANAGER` | hiring manager |
| client, anything else | `EMPLOYEE` | self-service only |

### 3.3 Capabilities — 100 of them, granted per role

`Cap` enum in `models/hrms.py`; `ROLE_CAPABILITIES` maps role → set. Counts: `MD` 99,
`HR` 84, `INTERNAL` 58, `MANAGER` 41, `FINANCE` 22, `CLIENT` 7, `EMPLOYEE` 6.

`MD` holds every capability but one — `requisition.review_hr`, which is HR's own step and
would collapse the two-person approval chain if the same person could take both. `ADMIN` is
deliberately absent from the map: it short-circuits in `capabilities_for`.

`test_capability_parity.py` asserts this enum matches `frontend/src/features/hrms/access.js`
exactly. A capability added to one and not the other fails that test.

Every route starts with `_require(current_user, Cap.X)`. Examples: `requisition.approve_md`,
`candidate.screen`, `offer.send`, `employee.salary.read`, `document.verify`,
`analytics.read`, `client.read`.

Notable deliberate withholdings:
- `INTERNAL` (Sparsh staff) does **not** get `employee.salary.*` — a client's pay data is not
  support-staff business.
- `INTERNAL` does not get `requisition.review_hr` / `approve_md` or `document.verify` — those
  are the client's own governance acts.
- `MANAGER` sees only **their own** requisitions and the candidates against them.

### 3.4 Company scope — the only tenant boundary

`scope_company_id(user, requested)`:
- A **client-side** caller is always pinned to their own company. A `company_id` in the query
  string is *ignored*, not honoured.
- An **internal** caller must name a company; "all companies at once" is not a valid scope.

`GET /hrms/health` returns the caller's **resolved role and capability list**, and the frontend
gates every control on that answer.

### 3.5 Client scope — a *second* narrowing, inside the tenant

`company_id` is and remains the security boundary. Client scope narrows **further**, inside one
tenant, for users who belong to a client organisation rather than to this company. It never
widens anything and never reaches across companies.

**`scope_client_ids(user, company_id)` returns `Optional[list]`, and the distinction is the
whole design:**

| Return | Means | Effect |
|---|---|---|
| `None` | the caller is **not** client-scoped (Sparsh HR, MD, Finance, a manager) | no client filter; behaviour identical to before client scope existed |
| `[]` | client-scoped, **no valid membership** | `{"client_id": {"$in": []}}` — matches nothing |
| `[...]` | the clients this user may work on | `{"client_id": {"$in": [...]}}` |

Collapsing `None` and `[]` into one empty list would either lock out every HR user or open the
gate for an unmapped client user, depending which way the collapse went. Both are wrong, and
only one of them is loud.

**Scope is resolved from engagement records, never from a request.** `assert_client_allowed()`
reconciles a requested `client_id` against the resolved scope: it can only *narrow* what the
caller already had, and returns 403 for anything outside it. That function is what keeps
`?client_id=` a filter rather than an authorisation input.

**Composition is intersection, never replacement:**

```python
query = {"company_id": company_id}
query.update(client_filter(allowed))        # client narrowing
query.update(await _scope_filter(actor, company_id))   # manager-own narrowing
```

---

## 4. Core invariants

Break any of these and something downstream silently corrupts. They are the rules to check
first when changing this module.

1. **`company_id` is the only security boundary.** `client_id`, `request_no` and role scoping
   are narrowing dimensions *inside* a tenant. Never treat `client_id` as a tenant check.
2. **Scoping filters fail CLOSED.** An empty match list becomes `$in: []` (matches nothing),
   never an absent filter (matches everything). A filter that widens when it finds nothing is
   how a scoping bug becomes a data leak.
3. **Every candidate stage move goes through `FORWARD_TRANSITIONS`.** Services propose a
   target; `can_transition()` decides legality. An illegal move is a 409, not silent
   corruption.
4. **Business ids come from an atomic counter** (`hrms_id_service.next_business_id`), never
   from scanning existing rows for a max suffix — that races.
5. **Analytics never writes.** `hrms_analytics_service` contains no insert/update/delete, and
   a test greps the source to enforce it.
6. **Nothing is computed in the browser.** Every figure is computed and role-scoped
   server-side. The frontend fetches and lays out.
7. **The frontend `CAP` map must equal the backend `Cap` enum**, asserted by
   `test_capability_parity.py`. Add a capability to one side without the other and controls
   silently vanish.
8. **The sidebar list and the workspace tab strip must stay disjoint** — anything in
   `HRMS_WORKSPACE` (Sidebar.jsx) must not also be in `hrmsSubmodules`.

---

## 5. Data model

### 5.1 Collections

| Collection | Holds |
|---|---|
| `hrms_employee_profiles` | employee master (may exist unlinked to a login user) |
| `hrms_departments`, `hrms_designations` | the masters requisitions reference |
| `hrms_sanctioned_strength` | approved headcount per department+designation |
| `hrms_requisitions` | vacancies, approval chain, budget, client tag |
| `hrms_job_descriptions` | the JD co-approved with its requisition |
| `hrms_job_postings` | published JD + its single public code |
| `hrms_candidates` | the CV and its lifecycle state |
| `hrms_assessments` | take-home tests and their dual review |
| `hrms_interviews` | scheduled rounds and scorecards |
| `hrms_offers` | offer letters and candidate responses |
| `hrms_appointments` | appointment letters |
| `hrms_onboarding` | pre-onboarding, BG check, checklist |
| `hrms_documents`, `hrms_document_types` | the document register |
| `hrms_links` | registry of every public link issued |
| `hrms_audit_log` | append-only trail |
| `hrms_counters` | atomic business-id sequences |
| `hrms_public_rate_limit` | fixed-window counters for public endpoints |
| `hrms_client_engagements` | **which companies are this tenant's clients, and which of its users work on each** |

**There is no `hrms_clients` collection.** A client *is* a company (`client_id` = a
`companies._id`) — see [§8](#8-the-client-dimension).

**The engagement is not a second company record.** It stores a reference, a status, a member
list and an audit trail; name, address and contacts stay in `companies`. It exists because a
`companies` row says an organisation *exists*, not that it is **ours** — and "is this company a
client of ours" is the question every client-scope check rests on.

```
engagement_id     CLI-ENG-2026-001
company_id        the Sparsh tenant          ← security boundary
client_id         a companies._id            ← the client
status            active | suspended | ended ← only `active` grants scope
member_user_ids   [user ids]                 ← who may work on this client
```

**Membership lives on the engagement, not on the user.** `learners`/`staff` are shared ERP
collections; HRMS writing its own array into them would widen another module's schema. Holding
the list here keeps the relationship inside HRMS, makes "manage this client's users" one
document, and makes revocation atomic — suspending an engagement removes its members' scope
immediately, with no membership row touched.

**There is no `hrms_clients` collection.** Clients are the ERP's `companies` — see [§8](#8-the-client-dimension).

### 5.2 Business ids

Minted atomically. Format `(prefix, year-scoped, pad)` from `ID_FORMATS`:

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

Sequences are **scoped per company**, so one tenant cannot infer another's hiring volume from
gaps in its own numbering.

### 5.3 Cross-collection join key

**Every HRMS collection carries `request_no`**, and candidate-linked ones also carry `uk` (the
candidate id). This is what lets analytics apply one scope filter uniformly. Preserve it on
any new collection.

---

## 6. The recruitment flow, end to end

Each step lists: **who** → **what happens** → **candidate status after** → **API**.

### Step 1 — Raise a requisition (+ JD)

Hiring manager (`MANAGER`) or HR raises a vacancy. The JD is created **in the same call** — a
requisition without a JD cannot be posted.

- `POST /api/hrms/requisitions` → `create_requisition`
- Requires: `department_id`, `designation_id`, `vacancy`, `experience_required`,
  `qualification`, `essential_skills`, `required_date`, `assignee_id`, `jd{...}`
- Optional: `client_id` (which client this is for), budget figures, `requisition_type`
  (`New Position` / `Replacement`)
- Approval status → `Pending HR Review`

### Step 2 — HR review

- `POST /api/hrms/requisitions/{request_no}/approve` with `action: "hr-approve"`
- Cap: `requisition.review_hr`
- → `Pending MD Approval`, **or** `Pending Escalation` if over sanctioned strength ([§9](#9-approval-chain-sanction-and-budget))

### Step 3 — MD approval

- Same endpoint, `action: "md-approve"` (optionally `salary_change`)
- Cap: `requisition.approve_md`
- → `Approved`. The JD becomes publishable.

### Step 4 — Publish a posting

- `POST /api/hrms/postings` with `jd_no`, `requires_assessment`, `expiry_date`
- Mints **one** posting code (`AB-123XYZ`) and **one** public link `/apply/{code}`
- `apply_link_mode`: `auto` (built-in form, lands in the pipeline) or `external` (the
  poster's own destination — those applications **never** enter this pipeline)

> **There is deliberately no "platform" on a posting.** One posting, one link, shared
> anywhere. The channel is captured by *asking the applicant* on the form, not inferred from
> which URL they clicked — an inference that breaks the moment a link is forwarded.

### Step 5 — Applications arrive

- Public: `POST /apply/{code}` → creates a candidate at **`Applied`**
- Manual: `POST /api/hrms/candidates` (HR pastes in a walk-in CV)
- The form asks "where did you hear about this role" (mandatory) → becomes `source`, and
  optionally "were you referred" → the referral block ([§10.1](#101-referrals))

### Step 6 — Screening (bulk)

- `POST /api/hrms/candidates/screen` — up to **200** candidates per call
- Cap: `candidate.screen`
- Partial success is deliberate: a batch where 3 of 50 are at an incompatible stage moves the
  47 and reports the 3.

| Action | Result |
|---|---|
| `review` | → `Under Review` |
| `shortlist` | → `Assessment Pending` if the posting requires one, else `Shortlisted` |
| `share_with_client` | → `Shared with Client`, opens a client-share record |
| `hold` | → `On Hold` |
| `duplicate` | → `Duplicate` (terminal) |
| `reject` | → `Rejected` — **remarks required** |
| `forward` | assigns an internal owner; **does not move the candidate** |

> `forward` and `share_with_client` are easy to confuse. `forward` assigns an ERP user as
> recruiter. `share_with_client` sends the CV *out* to the hiring client.

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
- Rounds: `HR Round` → `Technical` → `Manager Round` → `MD Round`
- `POST .../evaluate` with a scorecard (technical, communication, problem_solving, behavior,
  confidence, team_fit, outcome, signature)
- `GET .../invite.ics` produces a calendar invite

Progression on **Pass** (`PASS_NEXT`):

```
HR Round      → Technical Round
Technical     → MD Round
Manager Round → MD Round
MD Round      → Selected
```

On **Fail** → `Rejected`. On **Hold** → `On Hold`.

> **Scheduling in the past is refused outright.** There is no API path to create a
> back-dated interview.

### Step 10 — Offer

- `POST /api/hrms/offers` (status `Draft`) → `POST .../send` mints `/offer/{code}`
- Candidate: `POST /offer/{code}` with `accept` / `decline`
- `Offer Generated` → `Offer Accepted` or `Offer Declined` (terminal)
- `POST .../revoke` walks the candidate **back** to `Selected` so revised terms can be issued
  — without that edge a revoked candidate is stranded.

### Step 11 — Appointment letter (optional)

- `POST /api/hrms/appointments` → `.../send` mints `/appointment/{code}` → candidate
  acknowledges → `Appointment Letter Sent`
- **Optional by design.** The direct `Offer Accepted → Pre-Onboarding` edge is kept, so a
  company that does not issue appointment letters is never blocked.

### Step 12 — Onboarding

Startable from `Offer Accepted` or `Appointment Letter Sent`.

1. `POST /api/hrms/onboarding` → `Pre-Onboarding`, mints `/onboard/{code}`
2. New joiner submits KYC/bank/emergency contact/references via `POST /onboard/{code}`
3. `POST .../verify` — documents verified
4. `POST .../bg` — background verification (`Pending`/`In Progress`/`Cleared`/`Flagged`)
5. `POST .../checklist` — 12 keys: `offer_signed`, `documents_verified`, `bg_cleared`,
   `employee_id`, `email_created`, `system_access`, `asset_issued`, `workspace`, `induction`,
   `policy_ack`, `bank_payroll`, `buddy_assigned`
6. `POST .../generate-id` → mints `EMP-2026-00N`, creates the employee profile, candidate → **`Joined`**
7. Checklist completed → onboarding `Completed`, candidate → **`Employee Created`** (terminal)

---

## 7. Candidate lifecycle

### 7.1 Statuses (`AppStatus`)

```
Applied · Under Review · Shortlisted
Shared with Client · Client Shortlisted · Client Rejected
On Hold · Duplicate · Rejected
Assessment Pending · Assessment Completed · Assessment Passed · Assessment Failed
Interview Scheduled · Technical Round · MD Round
Selected · Offer Generated · Offer Accepted · Offer Declined
Appointment Letter Sent · Pre-Onboarding · Joined · Employee Created
Probation Confirmed
```

**Terminal:** `Probation Confirmed`, `Offer Declined`, `Duplicate`.
**Always available from any non-terminal stage:** `Rejected`, `On Hold`, `Duplicate` — a
recruiter must always be able to stop or park a pipeline.

**Post-hire (`POST_HIRE_STATUSES`):** `Employee Created`. It advances — to
`Probation Confirmed`, on the internal track — but never receives the always-available three.
This is the whole reason that set exists: `allowed_next_statuses` grants
`Rejected`/`On Hold`/`Duplicate` to every non-terminal stage, so merely un-terminalising the
hire would have made a hired employee rejectable, on the **client** track as much as the
internal one. Read `POST_HIRE_STATUSES` in `models/hrms.py` before touching this.

`Probation Confirmed` is stamped by `confirm_probation`, not by a pipeline action, and only
on the internal track. `get_journey` therefore decides "is this finished?" by track: a
client-track hire is done at `Employee Created`, and reporting it as unfinished for ever was
the regression that made `_journey_is_over` track-aware.

### 7.2 Stage rank (`STAGE_RANK`) — how the funnel stays honest

A funnel that counts current status can show more offers than interviews, because someone at
`Offer Accepted` no longer has an interview status. So every candidate is ranked by the
furthest point they can be **shown** to have reached — their status, **or** the existence of an
assessment/interview/offer record, whichever is further (`_effective`).

| Rank | Statuses |
|---|---|
| 1 | Applied, Under Review, Duplicate, On Hold, **Rejected** |
| 2 | Shortlisted, **Shared with Client, Client Shortlisted, Client Rejected** |
| 3 | Assessment Pending / Completed / Passed / Failed |
| 4 | Interview Scheduled, Technical Round, MD Round |
| 5 | Selected |
| 6 | Offer Generated, **Offer Declined** |
| 7 | Offer Accepted, Appointment Letter Sent, Pre-Onboarding, Joined |
| 8 | Employee Created, **Probation Confirmed** |

Two subtleties that trip people up:

- **Rejections rank where the candidate *entered*, not where they left.** That is what keeps
  the funnel monotonically non-increasing.
- **The client-share band sits WITH Shortlisted (rank 2), not after it.** Sharing a CV and
  getting a verdict is a decision *about* a shortlisted candidate; it does not move them
  further down the funnel.
- **`Probation Confirmed` shares rank 8 with `Employee Created`; there is no rank 9.** The
  funnel ends at hired. Whether somebody is confirmed six months later is a governance event
  about an employee, not a ninth stage of recruitment — and giving it its own rank would add
  an empty tail to every chart and renumber `FUNNEL_STAGES`.
- **`Applied` and `Under Review` share rank 1.** Neither has cleared a hiring gate. This is
  why "CVs reviewed" cannot be defined as `rank >= rank(Under Review)` — that counts
  everybody (see [§12.2](#122-cv-metrics-and-the-cv-funnel)).

### 7.3 Evidence-based ranks

Set by the mere existence of a record elsewhere: assessed → 3, interviewed → 4, offered → 6,
offer accepted → 7. So a candidate whose status was never updated still ranks correctly.

---

## 8. The client dimension

**A client is a company from the ERP's existing Companies section.** There is no HRMS client
master — `hrms_client_service.py` is a read-only projection of the `companies` collection into
the `{client_id, name, ...}` shape HRMS reports on, where `client_id` **is** the company's
`_id` as a string.

Why: a separate master meant the same organisation existed twice, could be spelled two ways,
and had to be re-entered by hand before it could appear on a dashboard.

Consequences to know:

- `GET /api/hrms/clients` is **read-only**. There is no POST/PATCH/DELETE — editing a client
  means editing the company, in the Companies module. `Cap.CLIENT_WRITE` does not exist.
- `requisition.client_id` holds a company id; `client_name` is denormalised at write time.
- **Client names are refreshed on read** in analytics (`_client_names`), so a rename in
  Companies shows through immediately with no sync step.
- `require_client(client_id)` takes **no** `company_id` — a client is by definition a
  different organisation from the tenant recruiting for it. Scoping that lookup would be
  security theatre; the real boundary is the requisition's own `company_id`.
- A requisition with no client is **in-house**, and analytics groups those under an explicit
  "In-house / no client" bucket rather than dropping them.
- **Visibility note:** anyone holding `client.read` sees every active company's *name* in the
  dropdown. That follows directly from making Companies the client list.

---

## 9. Approval chain, sanction and budget

### 9.1 The chain

```
Pending HR Review ──hr-approve──> [over sanction?] ──yes──> Pending Escalation ──┐
                                        │no                                      │
                                        ▼                          escalate-approve (per rung)
                                Pending MD Approval <─────────────────────────────┘
                                        │md-approve
                                        ▼
                                    Approved
```

Any step can `reject` → `Rejected`. Closing status is **separate** from approval:
`Open` / `Hired` / `Closed` / `Hold` / `Cancel` via `POST .../close`.

### 9.2 Sanctioned strength

One approved figure per (department, designation), stored in `hrms_sanctioned_strength`.
`position_status()` computes sanctioned vs **actual headcount** vs **committed vacancies**
(open requisitions).

> **A position with NO sanctioned figure recorded counts as over-sanction** — fail closed. An
> unauthorised headcount is exactly the case to escalate.

The ladder walks the raiser's reporting line, capped at `MAX_ESCALATION_LEVELS = 5`. The MD
may clear any rung.

### 9.3 Budget

Two figures captured independently: `budget_sanctioned_amount` (management) and
`budget_hod_amount` (the HOD). `budget_status()` derives:
`Not Set` · `Pending` · `Matched` · `Mismatch`. Both optional — omitting them reproduces
pre-phase behaviour exactly.

---

## 10. Supporting subsystems

### 10.1 Referrals

The application form asks two related questions: **where did you find this job** (always
captured → `source`) and **were you referred** (optional).

- `referral_source`: `Employee` · `Ex-Employee` · `Consultant / Agency` · `Job Portal` ·
  `Social Media` · `Walk-in` · `Client` · `Other`
- If `referral_source == "Employee"`, a **resolvable `referrer_employee_code` is mandatory** —
  the code *is* the claim. For any other source a code is optional context and an
  unresolvable one is dropped silently rather than failing the application.
- Referrals land in the existing `source` breakdown rather than a parallel dimension.

### 10.2 The public-link registry

Every candidate-facing link the pipeline issues is registered in `hrms_links`:
kinds `apply` · `assessment` · `offer` · `onboarding` · `appointment`; statuses
`Active` · `Expired` · `Revoked` · `Consumed`.

`GET /api/hrms/links` lists them with open counts. `POST .../revoke` kills a live credential;
`POST .../reissue` mints a fresh one and revokes the old (apply links cannot be reissued).
Enforcement is server-side in `assert_link_live`, not merely displayed.

> The admin **screen** for this registry was removed; the endpoints remain and still govern
> link validity.

### 10.3 Documents

`hrms_document_types` (12 seeded on first read) + `hrms_documents`, owned by a `candidate` or
an `employee`. Categories: Identity · Educational · Employment · Statutory · Company Issued ·
Other. Statuses: Pending · Uploaded · Under Review · Verified · Rejected · Expired
(`effective_status` derives Expired from the expiry date at read time).

Versioned uploads; `document.verify` is a separate capability from `document.write` because
verifying is a governance decision, not an operational one.

### 10.4 Audit trail

Append-only `hrms_audit_log`; every service writes through `hrms_audit_service.audit()`.
Readable via `GET /api/hrms/audit` (`audit.read`). `GET /api/hrms/candidates/{uk}/journey`
assembles a candidate's history from it.

### 10.5 Notifications

`hrms_notify_service`: `notify_user`, `notify_users`, `notify_hrms_role` — in-app rows plus
email. **Seed scripts patch these out**, because a shared database means real colleagues would
otherwise be told about invented candidates.

---

## 11. The public surface

Five unauthenticated routes in `routes/hrms_public.py`, the module's only internet-facing
endpoints. All defences live in `utils/hrms_public_guard.py`.

| Route | Purpose |
|---|---|
| `GET/POST /apply/{code}` | job ad + application form |
| `GET/POST /assess/{code}` | take-home assessment |
| `GET/POST /offer/{code}` | offer letter + accept/decline |
| `GET/POST /onboard/{code}` | pre-onboarding form |
| `GET/POST /appointment/{code}` | appointment letter + acknowledgement |

**Access codes** are `secrets.token_urlsafe(16)` — 128 bits of cryptographic randomness,
case-sensitive.

**Rate limits** are DB-backed and fixed-window (an in-process limiter loses state on restart
and is not shared across workers; a sliding window would let a flood grow the limiter's own
storage):

| Scope | Limit |
|---|---|
| view | 60 / min / IP |
| apply | 5 / hour / IP |
| apply-posting | 200 / hour / **posting code** |
| assess-view | 30 / min / IP |
| assess-submit | 10 / hour / IP |
| offer-view / onboard-view | 40 / min / IP |
| offer-respond / onboard-submit | 10 / hour / IP |

**Uploads:** max 15 MB, max 10 certificates, MIME allow-list (PDF, DOC/DOCX, JPEG/PNG/WebP).
Base64 in a JSON body, because the public forms cannot use multipart without a token.

---

## 12. Analytics and reports

All read-only, all computed server-side behind `_scope()`.

### 12.1 Endpoints

| Endpoint | Returns |
|---|---|
| `GET /analytics/dashboard` | KPI tiles, CV metrics, client metrics, **cv_funnel**, positions, offer outcomes, onboarding states, time-to-hire, client comparison |
| `GET /analytics/funnel` | the 8-stage hiring funnel by effective rank |
| `GET /analytics/breakdown?by=` | `source` · `department` · `designation` · `client_status` · `referral_source` · `client` |
| `GET /analytics/positions` | position-wise CV status matrix (rows = requisition, columns = every `AppStatus`) |
| `GET /reports/{entity}` | paginated rows — `candidates` · `requisitions` · `interviews` · `offers` · `onboarding` |
| `GET /reports/{entity}/export` | CSV / XLSX, generated **server-side** |

All accept `date_from`, `date_to`, `client_id`, `company_id`.

### 12.2 CV metrics and the CV funnel

Computed in one already-scoped pass (`_cv_metrics`), so none can escape `_scope`:

| Metric | Definition |
|---|---|
| `reviewed` | cleared the shortlist bar **or** carries a review-outcome status (`Under Review`, `Rejected`, `Duplicate`, `On Hold`) |
| `awaiting_review` | `total - reviewed` |
| `shortlisted` | effective rank ≥ rank(Shortlisted) — the internal selection |
| `selected` | effective rank ≥ rank(Selected) — the final selection, after interviews |
| `rejected` | status in the rejection set |
| `shared_with_client` | a client-share record exists |
| `client_shortlisted` / `client_rejected` / `client_awaiting` | the verdict on it |
| `joinings` | status in `{Joined, Employee Created, Probation Confirmed}` |

> `reviewed` **cannot** be `rank >= rank(Under Review)` — `Applied` shares that rank, so the
> figure would silently equal the total.

`cv_funnel` presents these as stages: *CVs received → Reviewed → Shortlisted → Shared with
client → Client shortlisted → Selected → Joined*, with `of_total` and `of_previous`.
**`of_previous` is `null` wherever a stage exceeds the one above it** — an in-house
requisition never shares a CV, so `selected` can legitimately outnumber `shared_with_client`.
That is a real shape, not a rounding error.

### 12.3 Guards

`SCAN_CAP = 20000` per read · `MAX_RANGE_DAYS = 1100` · `MAX_EXPORT_ROWS = 5000` ·
`MAX_BREAKDOWN_ROWS`. An unbounded `to_list` on an analytics endpoint is a DoS waiting for the
first client with real volume.

---

## 13. Frontend architecture

### 13.1 Routes

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

Public (no auth): /apply/:code  /assess/:code  /offer/:code  /onboard/:code  /appointment/:code
```

### 13.2 Two navigations, deliberately disjoint

- **Workspace tab strip** (`HrmsWorkspaceBar`) owns the hiring pipeline, in three labelled
  groups, because the module runs two hiring tracks and a flat row of twenty tabs said so
  nowhere:
  - **Both tracks** — Hiring Req → Job Descriptions → Job Postings → Candidates → HR
    Screening → Assessments → Interviews → Offers → Appointments → Onboarding → Reports.
  - **Internal hiring** — Overview → Internal reqs → Scorecards → Phone screen →
    Shortlisting → References → Negotiation.
  - **Client hiring** — Job requests → CV sharing → Verification.

  The breadcrumb reads `HRMS / <group> / <screen>`, so which track you are working in is
  answered before anything else. The grouping is presentational: it adds no route, hides
  nothing and gates nothing — capability filtering stays on the screens and the API.
- **Sidebar** (`Sidebar.jsx` `hrmsSubmodules`) keeps Dashboard, Employees, Documents,
  Recruitment (the way *in*), and the admin-only masters.

`HRMS_WORKSPACE` in Sidebar.jsx lists the strip's routes so "Recruitment" stays highlighted
anywhere in the workspace. **The two lists must stay disjoint.** A tab added to the strip
without a matching entry there does not break — the sidebar simply unlights itself on that
screen, which is how the Phase 12 client-track tabs went unnoticed until Phase INT-15.

### 13.3 `HrmsContext`

Fetches `GET /hrms/health` once on mount and holds `role`, `capabilities`, `isInternal`,
`companyId`, `companies`, `scope` (`{company_id}` for every API call), and `can(cap)`.

**Fails closed**: while loading and on any error, `can()` returns false.

Client-side users cannot switch company scope — the server pins them, so the UI must not
pretend otherwise (`setCompanyId` is a no-op for them).

---

## 14. Complete API reference

All authenticated routes are under `/api/hrms`. Every one takes an optional `company_id`
(ignored for client-side callers).

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
<summary><b>Requisitions, JDs, postings</b></summary>

```
GET    /requisitions                    POST /requisitions
GET    /requisitions/{no}               PATCH /requisitions/{no}   DELETE /requisitions/{no}
POST   /requisitions/{no}/approve       hr-approve | md-approve | escalate-approve | reject
POST   /requisitions/{no}/close         Open|Hired|Closed|Hold|Cancel
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
<summary><b>Clients, links, documents, sanction, analytics</b></summary>

```
GET    /clients                         GET /clients/{client_id}     READ-ONLY
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

## 15. Testing

29 self-contained test files in `backend/app/services/hrms/tests/`, ~2,700 assertions.

**House convention:** no pytest, no live database. Fake collections, ASCII output, exit 1 on
failure. Run one with:

```bash
python -m app.services.hrms.tests.test_phase5_candidate      # from backend/
```

Run all:

```bash
for f in app/services/hrms/tests/test_*.py; do
  python -m "app.services.hrms.tests.$(basename $f .py)"
done
```

`FakeCollection` (in `test_phase2_employee.py`) is shared by every test and implements the
`find`/`find_one`/`aggregate`/`update_*` subset the services actually use — anything else
raises rather than silently returning nothing.

Two structural tests worth knowing:

- `test_capability_parity.py` — backend `Cap` enum vs frontend `CAP` map, by regex.
- `test_phase10_analytics.py` — greps the analytics service source for `insert_`/`update_`/
  `delete_` to prove it never writes. **A comment containing those words fails the test.**

---

## 16. What is NOT built

`models/hrms.py` declares collection names for later phases that have **no service, no route
and no UI**. Do not assume these work:

```
hrms_settings           hrms_permissions
hrms_leaves             hrms_leave_balances       hrms_holidays
hrms_attendance         hrms_punch_segments       hrms_attendance_corrections
hrms_payroll_runs       hrms_payroll_records
```

Verified: each is referenced **only** in the models file. There is no leave management, no
attendance/punch tracking and no payroll. `EmployeeProfileIn` carries salary fields and
`employee.salary.*` capabilities exist, but they are storage and access control only — nothing
computes a payslip.

Also absent: a **public client portal**. Client verdicts are recorded by an HRMS user on the
client's behalf; building a portal would mean a second unauthenticated surface with its own
credentials and threat model.

### Multi-client: what the foundation does and does not secure

The client-scope foundation ([§3.5](#35-client-scope--a-second-narrowing-inside-the-tenant))
ships the *primitive*. It is **not** yet applied to any pipeline surface:

| Surface | Client-scoped? |
|---|---|
| engagements, membership, `/hrms/health` | ✅ yes |
| candidates | ❌ **no** — `_scope_filter` narrows by company + manager-own only |
| interviews, offers, appointments, onboarding | ❌ **no** |
| documents / CVs | ❌ **no** |
| analytics, reports, exports | ❌ **no** — `client_id` is an unvalidated query parameter |
| notifications | ❌ **no** — fan-out is company + governance role |
| requisitions | ⚠️ `client_id` stored and validated on write; **not** yet a listing filter |

**Consequence: do not provision a real client user yet.** `HrmsRole.CLIENT` is granted
`module.access`, `requisition.read` and `client.read` and nothing else, precisely because the
row-level narrowing that would make anything more safe does not exist. Granting a client user
`candidate.read` today would hand them every *other* client's pipeline — the capability is not
the missing piece, the scope is.

`require_engagement()` exists and is tested, but is **deliberately not wired** into the
requisition write path: turning it on now would refuse every existing client-track requisition,
because no engagement has been opened. The phase that owns requisition client scope enables it.

**Child collections were deliberately not denormalised with `client_id`.** The chosen model is
to *derive* client scope through `request_no → requisition.client_id`, which needs no migration,
keeps one source of truth, and cannot drift. `_scope()` in `hrms_analytics_service` already uses
exactly that pattern. Denormalisation remains available later as a measured optimisation.

---

## 17. Traps and gotchas

Things that will bite you, in rough order of likelihood:

1. **Shortlisting an assessment-required posting skips `Shortlisted`.** It lands the candidate
   directly on `Assessment Pending`, and `Shared with Client` is **not** reachable from there.
   If a role needs the client-share flow, its posting must have `requires_assessment: false`.
   Sharing happens *before* testing.

2. **Interviews cannot be scheduled in the past.** Any seed or fixture that back-dates one
   gets a 422.

3. **`reviewed` is not `rank >= rank(Under Review)`.** `Applied` shares rank 1. See
   [§12.2](#122-cv-metrics-and-the-cv-funnel).

4. **A position with no sanctioned figure escalates.** Fail-closed by design. If every
   requisition in a test suddenly climbs the ladder, that is why.

5. **An `Employee` referral needs a resolvable employee code**, or the application 422s. Other
   referral sources need only a name.

6. **Adding a capability requires editing two files** — `models/hrms.py` and
   `frontend/src/features/hrms/access.js` — or the parity test fails and controls silently
   disappear.

7. **Do not write the word `update_many` (or `insert_one`, etc.) in a comment inside
   `hrms_analytics_service.py`.** The read-only test greps the source text.

8. **`client_id` is not a tenant.** Never use it as a security check.

9. **Adding a status to `AppStatus` requires an entry in `STAGE_RANK`.** Unknown statuses rank
   0 — counted in totals but credited to no funnel stage.

10. **The two navigations must stay disjoint** — see [§13.2](#132-two-navigations-deliberately-disjoint).

11. **Seed markers are load-bearing.** Two datasets coexist: `recruitment-demo` and
    `realistic-ops`. Each script's `--undo` deletes only its own marker. Never widen that
    filter.

12. **`scope_client_ids` returning `None` is not the same as returning `[]`.** See
    [§3.5](#35-client-scope--a-second-narrowing-inside-the-tenant). Treating them alike is the
    single most likely way this control gets broken.

13. **`client_filter([])` must stay `{"client_id": {"$in": []}}`.** A caller that "optimises"
    the empty case to `{}` turns *no clients* into *all clients*.

14. **`?client_id=` is a filter, never an authorisation.** Route it through
    `assert_client_allowed()`. If you ever find `client_id = request.query_params[...]` feeding
    an access decision, that is the bug `test_client_scope.py` exists to catch.

15. **Client scope secures nothing but requisitions today.** Candidates, interviews, offers,
    documents, analytics and notifications carry **no** client narrowing yet — see
    [§16](#16-what-is-not-built). Do not provision a real client user until they do.

---

## Appendix — seeding test data

```bash
# One requisition, end to end — 6 candidates, one hire
python scripts/seed_hrms_recruitment_demo.py --company <id> [--dry-run|--undo]

# A full book of work — 8 requisitions across 5 clients, 61 candidates, 3 hires
python scripts/seed_hrms_realistic_ops.py --company <id> [--dry-run|--undo]
```

Both drive the **real services**, so every record is created the way the application creates
it: correct business ids, legal stage transitions, full audit trail, populated link registry.
Both suppress notifications and S3 uploads. Both stamp everything they create with
`demo_seed`, and `--undo` removes only that marker.

`seed_hrms_realistic_ops.py` produces a deliberately realistic spread — CVs nobody has opened,
CVs a client is sitting on, parked candidates, a live offer awaiting an answer, interviews
booked but not evaluated, and requisitions in every closing state including one raised over
sanction so it climbs the escalation ladder.

**Invented data only:** emails at `example.com` (RFC 2606, unregistrable), phone numbers
`+91 00000 xxxxx` (no Indian mobile begins with 0), Aadhaar values beginning `0000` (no real
Aadhaar does). Real users are read but never written.
