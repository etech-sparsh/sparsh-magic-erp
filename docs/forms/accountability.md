# Accountability Checklist — Form Spec

Source: Apps Script web app `AKfycby2lObXBhI6TpQczAmIC-r5q35Jj82yuypBroAG1X6d`
Launched with URL params: `CID` (company id), `EID` (HOD employee id), `MID` (month/period).

## Header (from URL params, read-only context)
- Company: `CID` (e.g. `PTOP001`)
- Month/Period: `MID` (e.g. `july26`)
- HOD: name + `EID` (e.g. `Aashu`, `EMP_223`)

## Shape
Rating **matrix**. Each question is scored per **team member row** on a **0–5 radio scale**.
A team member row shows: member **name** + **designation** (e.g. `Ram` / `IMPLEMENTOR`).
There can be multiple member rows; the sample shows one (`Ram`).

## Questions (all required)
| Code | Title | Prompt |
|------|-------|--------|
| A1 | Timely Task Completion | Is he/she ensure adherence to Position Score Card (PSC)? |
| A2 | Departmental result Adherence | Is he/she ensuring departmental processes are adhered? |
| A3 | Task Completion Without Follow-up | Is he/she ensuring task completion without followup? |
| A4 | Initiative for Better DRM Score | Is he/she ensuring to take initiatives to achieve an excellent DRM Score? |

Scale: integers 0,1,2,3,4,5 (single choice per member per question).

## Stored granularity (for future Success Measure calc)
One score per `(company_id, period, hod_id, member_id, criterion_code)`.
