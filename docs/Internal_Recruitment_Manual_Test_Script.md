# Internal Recruitment — Manual Test Script

A step-by-step tester's script for Sparsh Magic's **Internal Recruitment Policy & SOP**
(hiring for the operating company's own vacancies — no client involved). Follow this
document top to bottom against the running app to exercise the complete flow, end to end,
exactly as the policy defines it.

Screen names match the actual navigation labels: **HRMS → Internal hiring** tab strip for
the day-to-day hiring stages, and the **HRMS sidebar** for the broader post-hire lifecycle
screens (Pre-boarding, Probation). The **HRMS → Internal hiring → Overview** page has a
"Recruitment stages" strip at the top linking every stage below, in this same order, as a
quick way to jump between them while testing.

---

## 0. Setup

| # | What | Notes |
|---|------|-------|
| 0.1 | Pick (or create) a company with `hrms_enabled = true`. | The internal track works for whichever company is currently selected — "internal" means that company's own headcount, not only Sparsh Magic's. |
| 0.2 | Have four test accounts ready, mapped to the SOP's roles: | |
| | **HOD** (Department Head) | governance role `HOD` — raises the requisition, sits on the panel and shortlisting committee. |
| | **HR** | governance role `HR` — runs sourcing, screening, scheduling, offer and onboarding. |
| | **Management/Finance** | governance role `MD` or `FINANCE` — approves budget, scorecard (managerial+), final interview (managerial+), offer. |
| | **Candidate** | no login needed — every candidate-facing step uses a public link the app generates. |
| 0.3 | Pick two target roles to raise: one **non-managerial** (e.g. "HR Executive") and one **managerial+** (e.g. "Manager — Operations"). | Several gates (Management approval on scorecard, mandatory final MD-round interview) only fire for managerial+ roles — testing both is the only way to see every gate in this document. |

---

## 1–2. Manpower Requirement & Internal Requisition Creation

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HOD | **Internal hiring → Internal reqs** (`/hrms/internal-requisitions`) | Click **Raise**, fill role, department, designation, vacancy count, business justification, and submit. | A new requisition is created with **track = Internal** (not visible on the client-track Requisitions screens) and status **Pending HR Verification**. |
| HR | Internal reqs | Open the new requisition. | Status reads **Pending HR Verification**; no sourcing action (Job Postings, Add candidate) is available yet. |

## 3. Headcount & Budget Approval

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HR | Internal reqs → open the requisition | Click **Verify** (HR verification). | Status advances to **Pending Budget Approval**. |
| Management/Finance | Internal reqs → open the requisition | Click **Approve**, enter approved headcount and salary band. | Status advances to **Pending Scorecard Approval**, *unless* the approved headcount exceeds the sanctioned strength for that role (see 3a). |
| — | Any sourcing screen (Job Postings, Candidates → Add) for this requisition | Attempt to source before budget is approved. | Refused — "no internal role may be sourced without prior written headcount and budget approval" is enforced server-side, not just hidden in the UI. |

**3a. Over-sanction escalation (optional branch).** If the approved headcount exceeds the
role's sanctioned strength, the requisition instead moves to **Pending Escalation** and
routes up the raiser's own reporting line. Have that manager open **Internal reqs** and
either **Resolve** (advances to Pending Scorecard Approval) or reject it. Confirm a
requisition can never reach Scorecard Approval by skipping this step when it applies.

## 3. Position Scorecard

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HR | **Internal hiring → Scorecards** (`/hrms/scorecards`) | Click **New scorecard**, attach it to the requisition, add weighted criteria. | Scorecard saved, status **Pending Approval**. |
| HOD | Scorecards → open the scorecard | **Approve** with a typed signature. | For the **non-managerial** role: requisition status advances straight to **Approved**. |
| Management | Scorecards → open the scorecard (managerial+ role only) | **Approve** with a typed signature — a *different* signatory from the HOD's. | Required in addition to the HOD's sign-off for managerial+ roles; only after both does the requisition reach **Approved**. Confirm the same person cannot sign both approvals. |

At this point the requisition is **Approved** and open for sourcing — check the **Internal
hiring → Overview** page: it should now be counted under "Open positions" and no longer
under "Awaiting approval".

## 4–5. Recruitment Planning & Candidate Sourcing

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HR | **Job Postings** (`/hrms/postings`) | Publish a posting against the approved requisition; note the generated application link. | Posting goes **Live**; the link resolves to a public application form. |
| Candidate (public link) | `/apply/<code>` | Fill the form, **attach a resume** (mandatory), submit. | Application accepted; candidate appears on **Candidates** at stage **Applied**, linked to this requisition. |
| HR | **Candidates** (`/hrms/candidates`) | Alternatively, add a walk-in/referral CV by hand via **Add**. | Candidate created directly at **Applied**, same as a public applicant. |
| HR | Candidates | Confirm no application without a resume was accepted. | The public form refuses submission (and the API independently refuses it) with no resume attached. |

## 6. CV Screening

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HR | **HR Screening** (`/hrms/screening`) | Review the CV against the scorecard; **Shortlist** or **Reject**. | Shortlisted candidates move to **Shortlisted**; rejected ones to **Rejected** with a reason recorded. |
| — | **Shortlisted** tab (`/hrms/shortlisted`) | Open it. | Every shortlisted candidate across every requisition appears here in one place (not only as a column on the Candidates board). |

## 7. HR Telephonic Screening

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HR | **Phone screen** (`/hrms/telephonic-screening`) | Record the outcome of the phone screen for a shortlisted candidate. | Candidate moves to **Telephonic Passed** or **Telephonic Rejected**. |
| HR | **Interviews** (`/hrms/interviews`) | Try scheduling an interview for a candidate who has *not* cleared the phone screen. | Refused — the telephonic gate blocks scheduling until this step is recorded. |

## 8. Skill / Competency Assessment (if applicable)

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HR | **Assessments** (`/hrms/assessments`) | For a role marked "requires assessment", send an assessment to the candidate. | Candidate status moves to **Assessment Pending**; a public link is generated for them to complete it. |
| HR | Interviews | Try scheduling an interview for this candidate *before* the assessment is passed. | Refused, on **both** the dedicated scheduler and the generic "Move to stage" control on the Candidates drawer — the gate cannot be bypassed either way. |
| Candidate / Reviewer | Assessment public link, then Assessments board | Submit the assessment; two reviewers record Pass/Fail. | Candidate advances to **Assessment Passed** (or **Failed**) once both decisions are in. |

## 9. Panel Interview

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HR | **Interviews** (`/hrms/interviews`) | Schedule an HR + HOD panel round (add Management too for the managerial+ role). | Interview appears on the schedule with the correct panel. |
| HR / HOD | Interviews → the scheduled round | Submit the evaluation scorecard. | Recommendation recorded; a failed round does not auto-reject — HR can still record a separate outcome. |

## 10. Internal Shortlisting Committee

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HR + HOD | **Shortlisting** (`/hrms/shortlist-reviews`) | Record the committee's joint decision, using the 0–5 scoring guide (4.0+ strong, below 3.0 reject). | Candidate is cleared (or not) for the final round; recorded as a committee decision, not a single person's call. |
| — | Candidates → attempt to mark **Selected** without a shortlist-committee decision on file | Try it. | Refused — `Selected` requires the committee gate to have cleared, on top of every earlier gate. |

## 11. Management Final Interview (managerial+ roles)

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| Management | **Interviews** | Schedule and evaluate the MD round for the managerial+ candidate. | Only Management/MD may record this round's decision — HR attempting to record it is refused. |
| — | Candidates → attempt **Selected** on the managerial+ candidate with no passed MD round | Try it. | Refused for managerial+ roles specifically — the non-managerial candidate needs no such round. |

## 12. Reference Check

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HR | **References** (`/hrms/reference-checks`) | Record a reference check for the selected candidate (both roles — internal track requires it for **every** role, not only managerial+). | Reference recorded as Cleared or Flagged. |
| HR | **Offers** | Attempt to create an offer with no reference check on file. | Refused — the internal track's offer gate requires a cleared reference for every hire. |

## 13. Salary Negotiation

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HR | **Negotiation** (`/hrms/negotiations`) | Record the agreed salary for the candidate. | Negotiation entry saved, verdict computed against the band approved in Step 3 (`within`, `above`, or `below`). |
| HR | Negotiation | Record a figure **above** the approved band. | The round itself still saves (recording is never refused) — but is verdict-marked "above". |
| HR | **Offers** | Draft an offer at that above-band figure. | Refused — the offer gate (`assert_within_band`) blocks any internal offer outside the approved band. The only way past it: re-approve the budget at the new figure (rewinds to Step 3), or log an approved "Offer Outside Budget" exception (see E1). |

## 14–15. Offer Approval & Offer Letter Release

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HR | **Offers** (`/hrms/offers`) | Draft the offer (designation, CTC, joining date) for the candidate. | Offer = **Draft**. |
| Management/Finance | Offers | **Approve** the offer. | Offer = **Approved**. |
| HR | Offers | **Send** the offer. | Offer = **Sent** (frozen); a public accept/decline link is generated for the candidate. |
| Candidate (public link) | `/offer/:code` | **Accept**, typing a full-name signature. | Offer = **Accepted**; candidate stage moves to **Offer Accepted**, then automatically on to **Pre-Onboarding** (the onboarding case opens the instant the offer is accepted — see Step 16). |

## 16. Pre-boarding

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HR | **Pre-boarding** (sidebar → `/hrms/preboarding`) | Open the newly accepted candidate's engagement record. | An onboarding case already exists for them (opened automatically on acceptance) — confirm it shows up here without anyone having clicked "Start" by hand. |
| HR | Pre-boarding | Log an engagement touchpoint (a call, a check-in). | Informational only — this step does not gate anything further; confirm it does not block Step 17. |

## 17. Candidate Joining & Day-1 Induction

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| Candidate (public link, from the onboarding case) | `/onboard/:code` | Submit KYC documents (PAN/Aadhaar, bank details, address, emergency contact). | Onboarding checklist's document items tick off; status **Submitted**, awaiting HR verification. |
| HR | **Onboarding** (`/hrms/onboarding`) | **Verify documents**; run/record the background check. | Pre-status moves to **Verified**; a flagged background check blocks the next step until cleared. |
| HR | Onboarding | Tick the remaining Day-1 checklist items (offer signed, email created, system access, asset issued, workspace, **induction**) as each is actually done. | Every item is hand-ticked except the three system-owned ones (Employee ID, documents verified, background cleared), which the system ticks itself. |
| HR | Onboarding | Once every blocker clears, **Generate Employee ID**. | Employee ID issued; candidate becomes an **Active Employee** (stage **Joined**); the employee now appears on the **Employees** directory. |
| HR | **Appointments** (`/hrms/appointments`) | Generate → send the appointment letter (this can happen here, or earlier right after offer acceptance — both are supported). | Letter reaches the candidate via its own public link. |
| Candidate (public link) | `/appointment/:code` | **Acknowledge**, typing a signature. | Letter = **Acknowledged**. |
| Employee (self-service login) | **Employee Profile → Job tab** | Open it once linked to a login. | The acknowledged appointment letter is visible and downloadable from their own profile, not only on HR's Appointments board. |

## 18–19. Probation Monitoring & Review / Confirmation

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HR | **Probation** (sidebar → `/hrms/probation`) | Open the board before the probation end date. | The employee appears under **Due soon** as the confirmation date approaches, and under **Overdue** if it passes with no decision — this is the monitoring half of the step, distinct from the decision itself. |
| HOD (Management too, for managerial+) | Probation | At/near the end of probation, record **Confirm**, **Extend**, or **Terminate**, with remarks. | Confirm: employee status becomes **Active/Confirmed**. Extend: a new review date is set. Terminate: a separation case opens instead. |

## 20. Personnel File Closure

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| HR | Probation → the confirmed employee's record | **Close personnel file**, entering a closure note describing what was checked. | Personnel file marked closed, with the note, the closer, and a timestamp recorded — an empty note is refused. |

## 21. Recruitment Closure

| Actor | Screen | Action | Expected result |
|---|---|---|---|
| — | **Internal reqs** (`/hrms/internal-requisitions`) | Reopen the original requisition after the confirmation above. | Its status/closing status has moved to **Closed / Hired** automatically — nobody had to remember to close it by hand. For a requisition with more than one vacancy, confirm it stays open until *every* seat is filled, and only closes once the last one is confirmed. |
| — | **Internal hiring → Overview** | Reload the dashboard. | The filled position no longer counts toward "Open positions"; the recruitment stages strip's steps 1 through 21 have all been exercised for this one candidate. |

---

## Exceptions & compliance spot-checks (run once, alongside any of the above)

| # | Check | Where |
|---|---|---|
| E1 | Any deviation (extended TAT, relaxed scorecard, offer outside budget, waived reference check) is recorded in an **Exception Log** entry with reason, approver and date. | Sidebar → **Exceptions** (`/hrms/exceptions`) |
| E2 | A candidate's CV/interview data is visible only to HR/HOD/Management roles with the matching capability — log in as a plain **Employee** and confirm the Candidates/Screening/Interviews screens are not reachable. | Any account with role Employee |
| E3 | A rejected/closed candidate's data still respects the retention table (1 year for not-selected, employment + 3 years for hired). | Not independently checkable from the UI in one sitting — confirm the `retention_until` field is stamped on creation instead, via the candidate record. |

---

## Result log template

For each numbered step above, record: **Pass / Fail**, the requisition/candidate id used,
and — for any Fail — the exact screen, the action taken, and the actual vs. expected
result, so a failure is reproducible without re-running the whole script from Step 1.
