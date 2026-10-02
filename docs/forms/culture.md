# Culture Checklist — Form Spec

Source: Apps Script web app `AKfycbwFBS5qZ77uYl2evBKN1ZUqJ6D6-rESCL0GLup0j0sh` (Code.gs + Index.html provided by user).
Launched with URL params: `CID` (company id), `EID` (HOD employee id), `MID` (month/period, e.g. `jun26`).

## Shape — 0–5 rating matrix (same kind as Ownership / Accountability)
HOD rates each **team member** on each **question/criterion** using a 0–5 radio scale.
- Team = employees in `Company_Employees` whose `HOD_IDs` contains the HOD's EID (excludes the HOD).
- Member row shows: name + (designation - level).
- Questions come from sheet `HOD_Culture_Question` (data-driven; `Question_ID`, `Question`, `Description`, `Active`).
  **Actual Culture criteria text still to be provided** (C1–Cn).

## Cell-level partial submission (applies to ALL matrix forms)
- On open, existing ratings for `(company, HOD, month)` load and **each already-saved cell locks**
  (its radio is disabled and pre-selected).
- Submit appends **only** the newly-filled cells not already on file (no duplicates); blank cells are left
  for a later visit. Progress shows `X / Y rated`.

## Stored data (one atomic rating per cell)
Per `(company_id, period, hod_id, member_id, criterion_code)`: integer rating 0–5 + member/question snapshot.
Original response columns: `Timestamp, Month, Company_ID, HOD_ID, HOD_Name, Question_ID, Question, Employee_ID, Employee_Name, Rating`.
Supports future Success Measure calculations. (Original also emails an HOD summary to Admin/SMOps and a
per-employee scorecard to each rated employee — out of scope here unless requested.)
