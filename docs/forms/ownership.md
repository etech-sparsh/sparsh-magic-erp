# Ownership Checklist — Form Spec

Source: Apps Script web app `AKfycbwuTZxM-mHra8XoKp0nTAHGXhv-weR20a-P9oHITMBi`
Launched with URL params: `CID` (company id), `EID` (HOD employee id), `MID` (month/period).

## Header (from URL params, read-only context)
- Company: `CID` (e.g. `PTOP001`)
- Month/Period: `MID` (e.g. `july26`)
- HOD: name + `EID` (e.g. `Aashu`, `EMP_223`)

## Shape
Rating **matrix**, identical style to Accountability. Each question scored per **team member row**
on a **0–5 radio scale**. Member row shows: **name** + **designation** (e.g. `Ram` / `IMPLEMENTOR`).

## Questions (all required)
| Code | Title | Prompt |
|------|-------|--------|
| O1 | Active Departmental Participation | Is he/she getting involved and actively participating in departmental activity? |
| O2 | Departmental Problem Solving | Is he/she contributing towards solving departmental problems? |
| O3 | Process Involvement | Is he/she interested or involved to follow the process? |
| O4 | Organisational Result Alignment | Is he/she aligned with the organisational result Matrix? |

Scale: integers 0,1,2,3,4,5 (single choice per member per question).

## Stored granularity (for future Success Measure calc)
One score per `(company_id, period, hod_id, member_id, criterion_code)`.
