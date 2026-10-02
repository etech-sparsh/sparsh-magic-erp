# Sparsh Magic HRMS — Hiring Workflows Guide

A user guide and step-by-step testing reference for the two recruitment tracks the system
supports: **Internal Hiring** (Sparsh Magic hiring for itself) and **Client Hiring** (Sparsh
Magic recruiting on behalf of a client company). Both tracks share the same core pipeline
screens (Candidates → Screening → Assessments → Interviews → Offers → Appointments →
Onboarding); what differs is the approval chain before sourcing starts and what happens
around the offer.

Screen names below match the actual navigation labels in **HRMS → Internal hiring** /
**HRMS → Client hiring** (workspace tab strip) so a tester can follow this document directly
against the running app.

---

## 1. Internal Hiring

Sparsh Magic hiring for its own roles. The defining feature: **the budget is Sparsh's own
money**, so the chain adds a mandatory budget gate and ends on a position scorecard instead
of a single sign-off.

### 1.1 Flowchart

```mermaid
flowchart TD
    A[HOD/Manager raises Requisition\ntrack = Internal] --> B[Pending HR Verification]
    B -->|HR verifies role, headcount| C[Pending Budget Approval]
    C -->|Finance/MD approve salary band| D{Over sanctioned\nstrength?}
    D -->|Yes| E[Pending Escalation]
    D -->|No| F[Pending Scorecard Approval]
    E -->|Escalation resolved| F
    F -->|HOD + Management approve\nposition scorecard| G[Requisition Approved]

    G --> H[Sourcing: Candidate applies\nor is added to pipeline]
    H --> I[Screening]
    I --> J[Telephonic Screening\nHR-only step]
    J --> K[Shortlist Committee review]
    K --> L[Interview Rounds\nHR / Technical / Manager / MD]
    L --> M[Interview Evaluation\nscorecard, 6 competencies]
    M --> N[Reference Check\nmandatory, internal-only]
    N --> O[Salary Negotiation record]
    O --> P[Offer drafted]
    P --> Q[Offer Approval\nManagement/Finance]
    Q --> R[Offer Sent]
    R --> S{Candidate response}
    S -->|Accepted| T[Pre-boarding engagement]
    S -->|Declined| Z1[Requisition reopened\nor closed]
    T --> U[Onboarding: KYC docs,\nbackground check]
    U --> V[Employee ID generated]
    V --> W[Appointment Letter\ngenerated -> sent -> acknowledged]
    W --> X[Probation opened]
    X --> Y{Statutory checks complete?}
    Y -->|No| X
    Y -->|Yes| AA[Confirm / Extend / Terminate]
    AA -->|Confirmed| AB[Active Employee]
    AA -->|Terminated| AC[Personnel file closed]
```

### 1.2 Step-by-step test script

| # | Actor | Screen (HRMS → Internal hiring) | Action | Expected result |
|---|-------|----------------------------------|--------|------------------|
| 1 | HOD | Requisitions (Internal) | Create requisition, track = Internal | Status = **Pending HR Verification** |
| 2 | HR | Requisitions (Internal) | Verify role/headcount | Status = **Pending Budget Approval** |
| 3 | Finance/MD | Requisitions (Internal) | Approve with salary band | If within sanctioned strength → **Pending Scorecard Approval**; else → **Pending Escalation** |
| 4 | Management | Requisitions (Internal) | Resolve escalation (if raised) | Status advances to **Pending Scorecard Approval** |
| 5 | HR | Scorecard Library / Evaluation | Draft position scorecard | Scorecard awaits HOD approval |
| 6 | HOD, then Management (if managerial+) | Scorecard Evaluation | Approve scorecard | Requisition status = **Approved** |
| 7 | Recruiter | Candidate Pipeline | Add/import candidate against the requisition | Candidate appears at **Applied** stage |
| 8 | Recruiter | Screening Board | Screen candidate | Candidate moves to next allowed stage |
| 9 | HR | Telephonic Board | Record phone screen | Gate clears for interview scheduling |
| 10 | HR | Shortlist Committee | Record committee decision | Candidate cleared for interview |
| 11 | Recruiter | Interview Board | Schedule HR/Technical/Manager/MD rounds | Interview appears on the schedule |
| 12 | Interview panel | Interview Board | Submit evaluation scorecard (6 competencies) | Recommendation recorded; MD round gated to MD only |
| 13 | HR | Reference Check Board | Record reference check outcome | Required before offer for internal track |
| 14 | HR | Negotiation Board | Record agreed salary | Negotiation entry saved |
| 15 | HR | Offer Board | Draft offer (designation, CTC, DOJ) | Offer = **Draft** |
| 16 | Management/Finance | Offer Board | Approve offer | Offer = **Approved** |
| 17 | HR | Offer Board | Send offer | Offer = **Sent** (frozen); candidate link generated |
| 18 | Candidate (public link) | `/offer/:code` | Accept with typed signature | Offer = **Accepted**; candidate stage = Offer Accepted |
| 19 | HR | Pre-boarding Board | Track engagement touchpoints | Informational only — not a gate |
| 20 | Candidate (public link) | `/onboard/:code` | Submit KYC + documents (PAN or Aadhaar) | Onboarding checklist updates |
| 21 | HR | Onboarding Board | Verify documents, background check | Blockers clear one by one |
| 22 | HR | Onboarding Board | Generate Employee ID | Candidate becomes an **Active Employee**; employee code issued |
| 23 | HR | Appointments | Generate → send appointment letter | Candidate stage = Appointment Letter Sent |
| 24 | Candidate (public link) | `/appointment/:code` | Acknowledge | Letter = **Acknowledged** |
| 25 | Employee | Employee Profile (self) | Open **Job** tab | Appointment Letter card visible with View/Print |
| 26 | HR | Probation Board | Open probation record | Shows Overdue/Due-soon per policy |
| 27 | HR | Probation Board | Confirm / Extend / Terminate | Employee status updates; confirmation stamps candidate record |

---

## 2. Client Hiring

Sparsh Magic recruiting on behalf of a client company. The defining feature: **a client owns
the budget and the final hiring decision**, so a CV is shared outward and Sparsh waits on an
external verdict rather than approving internally.

### 2.1 Flowchart

```mermaid
flowchart TD
    A[Client submits Job Request\nJob Request Board] --> B[Submitted]
    B --> C[Sparsh reviews]
    C -->|Accept| D[Under Review]
    C -->|Decline| Z1[Declined]
    D --> E[Sparsh converts request\nto Requisition, track = Client]
    E --> F[Pending HR Review]
    F -->|escalation if needed| F2[Pending Escalation]
    F -->|else| G[Pending MD Approval]
    F2 --> G
    G --> H[Requisition Approved]

    H --> I[Sourcing: Candidate applies\nor is added to pipeline]
    I --> J[Screening]
    J --> K[Interview scheduling / evaluation]
    K --> L[CV Sharing: candidate shared with client]
    L --> M[CV Shared]
    M --> N[Client reviews\nShared Candidates board]
    N -->|Shortlisted| O[Interview Scheduled by client]
    N -->|Sent Back to Sparsh| I
    N -->|Rejected| Z2[Rejected]
    O --> P[Selected]
    P --> Q[Background Verification]
    Q --> R[Offer in Progress]
    R --> S[Offer drafted -> approved -> sent]
    S --> T{Candidate response}
    T -->|Accepted| U[Hired\nrecorded by Sparsh only]
    T -->|Declined| Z3[Vacancy reopened]
    U --> V[Onboarding: KYC docs]
    V --> W[Employee ID generated]
    W --> X[Appointment Letter\ngenerated -> sent -> acknowledged]
    X --> Y[Active Employee]
```

### 2.2 Step-by-step test script

| # | Actor | Screen | Action | Expected result |
|---|-------|--------|--------|------------------|
| 1 | Client user | Job Requests (client's own view) | Submit a job request | Status = **Submitted** |
| 2 | Sparsh HR | Job Requests (HRMS → Client hiring) | Review request | Accept → **Under Review**; Decline → **Declined** |
| 3 | Sparsh HR | Job Requests | Convert to requisition | New requisition created, track = **Client**, linked to the client company |
| 4 | HR | Requisitions | (automatic) | Status = **Pending HR Review** |
| 5 | HR | Requisitions | Forward / escalate if needed | **Pending Escalation** → resolved → **Pending MD Approval** |
| 6 | MD | Requisitions | Approve | Status = **Approved**, vacancy open |
| 7 | Recruiter | Candidate Pipeline | Add/import candidate | Candidate at **Applied** stage |
| 8 | Recruiter | Screening Board | Screen candidate | Candidate advances |
| 9 | Recruiter | Interview Board | Schedule + evaluate | Interview outcome recorded (no mandatory reference check on this track) |
| 10 | HR | CV Sharing Board | Share candidate with the client | Status = **CV Shared**; client can now see this candidate |
| 11 | Client user | Shared Candidates (client's own board) | Review shared candidate | Client-restricted status vocabulary — no "Hired" option visible to client |
| 12 | Client user | Shared Candidates | Move to **Shortlisted** / **Interview Scheduled**, or **Send Back to Sparsh** / **Reject** | Status updates; "Sent Back" returns candidate to Sparsh's pipeline, distinct from Reject |
| 13 | Client user | Shared Candidates | Mark **Selected** | Status = **Selected** |
| 14 | Sparsh HR | Background Check Board | Run verification | Status = **Offer in Progress** once cleared |
| 15 | HR | Offer Board | Draft → approve → send offer | Offer = **Sent**; candidate link generated |
| 16 | Candidate (public link) | `/offer/:code` | Accept with signature | Offer = **Accepted** |
| 17 | Sparsh HR | CV Sharing Board | Mark **Hired** | Recorded — this is a Sparsh-only commercial fact, never set by the client |
| 18 | Candidate (public link) | `/onboard/:code` | Submit KYC documents | Onboarding checklist updates |
| 19 | HR | Onboarding Board | Verify documents, generate Employee ID | Candidate becomes an **Active Employee** |
| 20 | HR | Appointments | Generate → send → candidate acknowledges | Appointment Letter = **Acknowledged** |
| 21 | Employee | Employee Profile (self) | Open **Job** tab | Appointment Letter downloadable |

### 2.3 What distinguishes the two tracks (for testers)

| Aspect | Internal | Client |
|---|---|---|
| Budget owner | Sparsh Magic itself | The client company |
| Approval chain | HR Verify → **Budget Approval** → [Escalation] → **Scorecard Approval** | HR Review → [Escalation] → **MD Approval** |
| Position scorecard | Required | Not used |
| Reference check | Mandatory before offer | Not required |
| Salary negotiation record | Recorded internally | N/A (client negotiates its own terms) |
| Candidate visibility | Internal panel only | Shared outward via CV Sharing; client sees a curated, read-only view |
| Who marks "Hired" | N/A (candidate simply proceeds) | Sparsh only — never the client |
| Probation | Tracked (Probation Board) | Not tracked by Sparsh (client's own employee) |

---

## 3. Notes for testers on the newly added features (this pass)

These aren't part of the hiring flow itself but affect the **post-hire** screens a tester
will pass through in steps 25 / 21 above and elsewhere in Employee 360:

- **Appointment Letter self-service** — after appointment acknowledgement, log in as the
  employee and confirm the letter shows on their own Employee Profile → Job tab (not only on
  the HR-side Appointments board).
- **GMP tab** — on Employee Profile, HR can add/edit a Group Mediclaim enrolment (insurer,
  policy number, dependants); the employee can view their own read-only.
- **PSC document category** — Document Types now offers "PSC" alongside
  Identity/Statutory/etc. when uploading employee documents.
- **HR Policy Library** — every employee has a new **HR Policy Library** sidebar entry
  separate from HR's admin-only **Policy Register**; policies HR marks "acknowledgement
  required" show a pending banner until the employee acknowledges.
- **Payslip** — once a payroll run is Calculated/Locked, an employee can open
  **Payroll → My Payslip**, pick a period, and print/save it; HR can view the same document
  for any employee via **Payroll Runs → (row) → Payslip**; HR configures the header/footer
  under **Payroll → Payslip Template**.
- **Attendance → Late Coming** — a new tab shows a calendar highlighting late-arrival dates,
  plus by-department and by-employee breakdowns for the selected month.
- **Policy acknowledgement** — a weekly background job reminds employees who still owe a
  required acknowledgement (and HR, as a rollup); **HR Policy Register** now shows a
  company-wide "acknowledgement completion" dashboard.
- **Employee 360°** — the read-only `/hrms/employees/:id/360` view (not just the edit-mode
  Profile screen) now shows the Appointment Letter and GMP sections too.
