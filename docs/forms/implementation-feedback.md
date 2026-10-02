# Implementation Update Feedback — Form Spec

Source: Apps Script web app `AKfycbxHyhP1fDPLrEMtVgQ_r28rlGOlU_VpUciEjR8reFI` (Index.html + Code.gs provided by user).
Launched with URL params: `CID` (company id), `EID` (MD Employee ID), `MID` (month/period, e.g. `jan26`).

## Shape — Yes/No checklist (NOT a rating matrix)
Respondent is the **MD** (managing director), identified by `EID`. A flat list of questions;
each answered with a **checkbox (ticked = Yes, unticked = No)** plus an **optional Remark** textarea.
No per-team-member rows.

## Questions — data-driven
In the original, questions come from sheet `Implementation_update_feedback_question` with columns:
`Question_ID`, `Question` (title), `Description` (optional subtitle), `Active` (skip if false/no/0).
→ In the ERP these live in the backend form definition `questions: [{id, title, desc}]`
(collection-free; edit `FORM_DEFINITIONS` to change them). **Actual question text still to be provided.**

## Partial submission (key behaviour)
- On open, previously-saved answers for the same `(company, MD, month)` are shown **locked** with a YES/NO tag.
- The MD can fill only the remaining (unanswered) questions and submit.
- A question is submitted only if its box is ticked **or** a remark is typed (an unticked box with no remark is skipped → fill later).
- Submit appends **only** questions not already saved (slot-by-slot). Re-opening lets them finish.

## Stored data (one atomic answer per question)
Per `(company_id, period, md_id, question_id)`: `{ question, answer: "Yes"|"No", remark }` + timestamp.
Original response columns: `Timestamp, Month, Company_ID, MD_ID, MD_Name, Question_ID, Question, Answer, Remark`.
This granularity supports future Success Measure calculations. (Original also emails Admin/SMOps on
submit — out of scope here unless requested; the ERP has its own notification service.)
