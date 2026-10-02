"""
HRMS ▸ domain models, collection registry and capability map.

Single source of truth for:
  • every `hrms_*` collection name the module will use (namespace registry),
  • the indexes provisioned at startup (`HRMS_INDEXES` — consumed by db/mongodb.py),
  • the role translation from the ERP's identity model to HRMS roles,
  • the capability registry + default role matrix that EVERY authorization decision
    resolves through (see utils/hrms_access.py).

Mirrors the structure of app/models/tpms.py so the module reads like the rest of the ERP.

── Two deliberate departures from the source HRMS spec ──────────────────────────
1. **Identity is keyed on `user_id` (ObjectId), never on a name string.** The source
   joined every HR-ops table on `users.name`, so renaming a user silently orphaned
   their leave history, balances and permission grants (BACKEND_ANALYSIS §4.4, Risk #4).
   Keying on the immutable `_id` removes that entire class of bug by construction.
2. **One authorization mechanism.** The source had four overlapping ones with three
   different "admin" role sets (BACKEND_ANALYSIS Risk #13). Here there is exactly one:
   `can(user, capability)` in utils/hrms_access.py, resolving through the registry below.

── Phase discipline ─────────────────────────────────────────────────────────────
Collection *names* are all declared up front — they are a namespace map and prevent
later collisions. But `HRMS_INDEXES` grows ONE PHASE AT A TIME: a collection is only
provisioned once the phase that owns it lands, so every DB change stays reviewable.
Capabilities follow the same rule (see CAPABILITIES).
"""
from enum import Enum
from typing import Dict, List, Optional, Set

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────
# Collections — full namespace map (provisioning is phased, see HRMS_INDEXES)
# ─────────────────────────────────────────────────────────────
# Phase 1 — foundation
COLL_AUDIT_LOG        = "hrms_audit_log"
COLL_COUNTERS         = "hrms_counters"

# Phase 2 — employee master
COLL_EMPLOYEE_PROFILES = "hrms_employee_profiles"
COLL_DEPARTMENTS       = "hrms_departments"
COLL_DESIGNATIONS      = "hrms_designations"

# Phase 3-9 — recruitment
COLL_REQUISITIONS     = "hrms_requisitions"
COLL_JOB_DESCRIPTIONS = "hrms_job_descriptions"
COLL_JOB_POSTINGS     = "hrms_job_postings"
COLL_CANDIDATES       = "hrms_candidates"
COLL_ASSESSMENTS      = "hrms_assessments"
COLL_INTERVIEWS       = "hrms_interviews"
COLL_OFFERS           = "hrms_offers"
COLL_ONBOARDING       = "hrms_onboarding"
COLL_PUBLIC_RATELIMIT = "hrms_public_rate_limit"

# Phase 11-R — recruitment review enhancements
COLL_LINKS               = "hrms_links"
COLL_DOCUMENTS           = "hrms_documents"
COLL_DOCUMENT_TYPES      = "hrms_document_types"
COLL_APPOINTMENTS        = "hrms_appointments"
# Background verification, per candidate, one row per check performed. Separate from
# onboarding's `bg_verification` flag, which happens after the offer and cannot gate it.
COLL_BACKGROUND_CHECKS   = "hrms_background_checks"
COLL_SANCTIONED_STRENGTH = "hrms_sanctioned_strength"

# Internal (in-house) recruitment track. Every one of these carries `request_no`, and the
# candidate-linked ones also carry `uk`, so the single analytics scope filter keeps working.
COLL_POSITION_SCORECARDS = "hrms_position_scorecards"
# ── Phase INT-4 ── the SOP's step 5 telephonic screen. Carries `request_no` AND `uk`: it
# describes work done on one candidate against one vacancy.
COLL_TELEPHONIC          = "hrms_telephonic_screenings"
# ── Phase INT-10 ── SOP step 9, salary negotiation within the approved band. One row per
# ROUND, carrying `request_no` AND `uk`: it is work done on one candidate for one vacancy.
COLL_NEGOTIATIONS        = "hrms_salary_negotiations"
COLL_REFERENCE_CHECKS    = "hrms_reference_checks"
COLL_PROBATION_REVIEWS   = "hrms_probation_reviews"
COLL_EXCEPTIONS          = "hrms_exceptions"

# ── Phase INT-2 — closing the remaining SOP gaps ──
# Same rule as the block above: every one of these carries `request_no` where it describes
# WORK (a shortlist decision, a touchpoint, a message, a survey response), so the single
# analytics scope filter reaches them unchanged. The four that are CONFIGURATION rather than
# work -- interview windows, salary bands, communication templates, the policy register --
# do not, for exactly the reason hrms_document_types does not: a template belongs to a
# company, not to one vacancy.
# -- Client Hiring step 1 -- its own collection. Nothing about a client requisition
# shares storage with an internal one; that separation is the point.
COLL_CLIENT_REQUISITIONS = "hrms_client_requisitions"
COLL_CLIENT_SCORECARDS = "hrms_client_scorecards"
COLL_CLIENT_POSTINGS   = "hrms_client_job_postings"
COLL_CLIENT_CANDIDATES = "hrms_client_candidates"
COLL_CLIENT_ASSESSMENTS = "hrms_client_assessments"
COLL_CLIENT_INTERVIEWS = "hrms_client_interviews"
COLL_CLIENT_REFERENCE_CHECKS = "hrms_client_reference_checks"
COLL_CLIENT_OFFERS = "hrms_client_offers"
COLL_CLIENT_JOININGS = "hrms_client_joinings"
COLL_SHORTLIST_REVIEWS   = "hrms_shortlist_reviews"      # SOP §5 shortlisting committee
COLL_INTERVIEW_WINDOWS   = "hrms_interview_windows"      # Annexure C batch interview slots
COLL_PREBOARDING         = "hrms_preboarding_touchpoints"  # SOP §6 pre-boarding engagement
COLL_SALARY_BANDS        = "hrms_salary_bands"           # Annexure C standing bands
COLL_COMM_TEMPLATES      = "hrms_comm_templates"         # Annexure C candidate experience
COLL_COMM_LOG            = "hrms_comm_log"               # append-only send record
COLL_SURVEYS             = "hrms_surveys"                # SOP §10 new-hire experience
COLL_SURVEY_RESPONSES    = "hrms_survey_responses"
COLL_POLICIES            = "hrms_policies"               # SOP §14 policy register
COLL_POLICY_REVISIONS    = "hrms_policy_revisions"
# ── Phase POLICY-LIB-1 (§22.6) ── one row per (policy_key, version, employee_code) — keyed
# by VERSION so an employee's acknowledgement of v1 never satisfies v2's requirement, which
# is what "policy updates can trigger re-acknowledgement" (BA doc step 229) reduces to: a
# fresh version simply creates fresh Pending rows, no separate re-ack mechanism needed.
COLL_POLICY_ACKNOWLEDGEMENTS = "hrms_policy_acknowledgements"
COLL_PURGE_BATCHES       = "hrms_purge_batches"          # SOP §13 retention purge proposals

# ── Phase INT-3 ── the scheduled-job ledger (SOP §12 reminders and escalations).
#
# One row per (company, job): the stamp of the last SUCCESSFUL run. It is deliberately
# durable rather than in-memory, unlike the TPMS job state it sits beside: a TPMS sweep is
# an idempotent sync, so re-running it after a restart costs nothing, whereas re-running a
# reminder job SENDS THE REMINDER AGAIN. Process memory resets on every deploy; this does
# not.
#
# CONFIGURATION, not work, so it carries no `request_no` -- the same reason the four
# Phase INT-2 configuration collections above carry none.
#
# Carries a UNIQUE index on (company_id, job_key), declared in HRMS_INDEXES below. Without
# it, two workers claiming the same slot in the same instant can leave two rows, and a job
# reading the stale one runs a second time.
COLL_JOB_RUNS            = "hrms_job_runs"

# ── Phase INT-6 ── this company's working calendar: the dates SLA maths skips.
#
# HRMS'S OWN, NOT THE ERP'S. The ERP has a `holidays` master, and reading it directly was
# the obvious implementation and the wrong one: that collection carries NO `company_id` --
# not on read, not on write, not even in its duplicate check -- so it is one global list.
# Pointing per-company compliance figures at it would mean an admin adding a regional
# festival for one entity silently moved every other entity's SLA due dates, which is the
# objection the original deferral raised and a worse answer than counting weekends only.
#
# So the calendar is per company, opted into per company, and the ERP master is available
# as an IMPORT rather than a live dependency -- a company ADOPTS those dates, which is an
# act somebody takes and the audit trail records.
#
# CONFIGURATION, not work, so no `request_no` -- the same reason `hrms_settings` has none.
COLL_HOLIDAYS            = "hrms_holidays"

# Phase 11-14 — settings, HR operations, payroll
COLL_SETTINGS         = "hrms_settings"
COLL_PERMISSIONS      = "hrms_permissions"
COLL_LEAVES           = "hrms_leaves"
COLL_LEAVE_BALANCES   = "hrms_leave_balances"
COLL_ATTENDANCE       = "hrms_attendance"
COLL_PUNCH_SEGMENTS   = "hrms_punch_segments"
COLL_ATTENDANCE_CORRECTIONS = "hrms_attendance_corrections"
COLL_PAYROLL_RUNS     = "hrms_payroll_runs"
COLL_PAYROLL_RECORDS  = "hrms_payroll_records"

# ── Phase EXIT-1 — Exit Management (BA/Functional Design §7.18, §22.2, §7.21) ──
#
# One row per departing employee (COLL_SEPARATIONS), with child collections for the work a
# separation spawns: handover tasks, departmental clearance, asset returns and access
# clearance are each their own collection rather than arrays nested on the separation,
# because each is independently assigned, independently actioned and independently overdue —
# the same reason onboarding tasks are not stored inside the onboarding record either.
COLL_SEPARATIONS       = "hrms_separations"
COLL_HANDOVER_TASKS    = "hrms_handover_tasks"
COLL_CLEARANCE_TASKS   = "hrms_clearance_tasks"
COLL_ASSET_RETURNS     = "hrms_asset_returns"
COLL_ACCESS_CLEARANCES = "hrms_access_clearances"
COLL_EXIT_INTERVIEWS   = "hrms_exit_interviews"
COLL_FNF_SETTLEMENTS   = "hrms_fnf_settlements"
# Former employees, written at closure. A SUMMARY for rehire decisions, deliberately not
# a copy of the personnel file -- an alumni list is read by people who should not be
# reading somebody's old salary or their exit interview verbatim.
COLL_ALUMNI            = "hrms_alumni"

# ── Phase ATT-1 — Attendance & Leave (BA/Functional Design §7.8-7.12, §22.8-22.9) ──
# COLL_ATTENDANCE, COLL_PUNCH_SEGMENTS, COLL_ATTENDANCE_CORRECTIONS, COLL_LEAVES and
# COLL_LEAVE_BALANCES already existed above as unreferenced placeholders (the gap analysis'
# own finding) — this phase is the first to actually provision and write them. Four more are
# new: OD is its own workflow step in the BA doc (§7.8 step 59), not a kind of correction; a
# lock is a fact about a PERIOD, not about any one attendance row, so it cannot live on
# COLL_ATTENDANCE without turning every row in a locked month into a lock record; leave
# TYPES are configuration (entitlement/accrual/carry-forward), the same reason
# hrms_salary_bands is separate from an actual negotiation round; and C-Off is a ledger of
# individually-expiring EARNED BATCHES (§7.11), a materially different shape from the
# single-balance-per-year COLL_LEAVE_BALANCES tracks for CL/SL/EL.
COLL_OD_REQUESTS       = "hrms_od_requests"
COLL_ATTENDANCE_LOCKS  = "hrms_attendance_locks"
COLL_LEAVE_TYPES       = "hrms_leave_types"
COLL_COFF_LEDGER       = "hrms_coff_ledger"

# ── Phase MOVE-1 — Employee Movements & Discipline (§7.16, §7.17, §7.19, §7.20) ──
# Each movement/case is its OWN row, never edited into a prior one — "Never overwrite
# historical organisation/compensation state" (§7.16 BR) is satisfied by construction: the
# employee's LIVE profile holds the current value (as it already does for department_id/
# designation_id/base_salary), and every past movement stays exactly as it was applied.
COLL_EMPLOYEE_MOVEMENTS = "hrms_employee_movements"
# Discipline is deliberately its own collection rather than folded into movements or
# exceptions: §7.17 requires its own confidentiality tier (POSH cases restricted even from
# ordinary managers), which a shared collection would make one query-filter away from a leak.
COLL_DISCIPLINE_CASES   = "hrms_discipline_cases"
# §7.19's warning ladder (flag -> contact -> First/Second/Final Warning) is a case with its
# own SLA clock, materially different from a plain attendance exception, so it is not folded
# into hrms_attendance_corrections either.
COLL_ABSCONDING_CASES   = "hrms_absconding_cases"
# No new collection for §7.20: retirement is a proactive ALERT computed from the employee's
# own DOB (no state to store beyond the company's configured retirement age, itself kept in
# hrms_settings next to shift_policy), and demise/missing's nominee/legal documentation is
# exit-type-specific data on the SAME separation record hrms_separations already carries (a
# small addition to Exit Management), not a parallel record of the same case.

# ── Phase PAY-1 — Payroll, Salary Advance & Variable Pay (§7.13-7.15, §22.7) ──
# COLL_PAYROLL_RUNS and COLL_PAYROLL_RECORDS already existed above as unreferenced
# placeholders since Phase 1 (the gap analysis' own finding) — this phase is the first to
# provision and write them. §22.7 requires payroll to be COMPONENT-DRIVEN rather than a fixed
# set of fields, so a salary structure is its own small master (COLL_SALARY_COMPONENTS) plus
# a per-employee assignment (COLL_SALARY_STRUCTURES), the same "master + assignment" split
# hrms_designations/hrms_employee_profiles already uses.
COLL_SALARY_COMPONENTS = "hrms_salary_components"
COLL_SALARY_STRUCTURES = "hrms_salary_structures"
# ── Phase PAYSLIP-1 (SM-HR-064) ── one payslip header/footer template per company.
COLL_PAYROLL_TEMPLATES = "hrms_payroll_templates"
COLL_SALARY_ADVANCES   = "hrms_salary_advances"
COLL_VARIABLE_PAY_QUARTERS    = "hrms_variable_pay_quarters"
COLL_VARIABLE_PAY_RECORDS     = "hrms_variable_pay_records"
COLL_VARIABLE_PAY_HOLD_LEDGER = "hrms_variable_pay_hold_ledger"

# ── Phase PIP-1 — Performance Improvement Plan (§22.5) ──
# One row per plan, holding its own objectives/support items and an append-only review log
# as embedded arrays (each is small, bounded, and always read together with the plan — the
# same reasoning MOVE-1's investigation_log lives ON the discipline case rather than in its
# own collection). PIP stays its own restricted record, visible only in an authorised
# Employee 360° performance history (§22.5 step 222) — Employee 360° itself (§6) is a
# separate, larger gap this phase does not build.
COLL_PIP_RECORDS = "hrms_pip_records"

# ── Phase GMP-1 — Group Mediclaim Policy (§22 employee profile "GMP section") ──
# One current enrolment per employee, HR-administered in place — not an effective-dated
# history, the same shape Employee Profile's own personal/statutory fields already take.
COLL_GMP_RECORDS = "hrms_gmp_records"

# ── Phase LETTER-1 — HR Letter / Document Generator (SM-HR-041) ──
# Templates are HR-authored, mutable text (the same "operator edits the wording" model as
# COLL_COMM_TEMPLATES) — there is deliberately no per-template version history, because the
# thing the BA doc requires be immutable is the ISSUED LETTER, not the template that produced
# it. An issued/reissued letter freezes its own rendered_body and template_version snapshot,
# so it stays reproducible even after HR later edits the template.
COLL_LETTER_TEMPLATES = "hrms_letter_templates"
COLL_LETTERS          = "hrms_letters"

# ── Phase ORIENT-1 — Orientation & Training (§22.3) ──
# A plan TEMPLATE (optionally filtered to a department/designation — see the phase's own
# service docstring for why location/level filters are a documented follow-up, not built
# here) and one ASSIGNMENT per employee, created once at activation by merging every
# matching template's items. The assignment is the employee's own record from there — later
# edits to a template do not retroactively change an already-assigned employee's items,
# the same "a generated thing is a snapshot" reasoning Phase LETTER-1 applies to a letter.
COLL_ORIENTATION_PLANS       = "hrms_orientation_plans"
COLL_ORIENTATION_ASSIGNMENTS = "hrms_orientation_assignments"

# ── Phase PULSE-1 — 30/90-Day Pulse Survey (§22.4) ──
# One row per employee per milestone ("30"/"90"), IDENTIFIABLE by design — see the Cap enum's
# own comment for why this is a separate module from the existing anonymous survey system
# rather than a new SurveyKind on it.
COLL_PULSE_RESPONSES = "hrms_pulse_responses"


# ─────────────────────────────────────────────────────────────
# Index registry — provisioned idempotently at startup by db/mongodb.py
# Format: (collection, keys, options)  — identical shape to TPMS_INDEXES.
# ─────────────────────────────────────────────────────────────
HRMS_INDEXES = [
    # ── Phase 1 ──
    # Audit reads are always "what happened to this entity" or "what happened in this
    # company lately"; both are indexed so the Phase 5 candidate journey and the Phase 15
    # audit API never collection-scan.
    (COLL_AUDIT_LOG, [("entity", 1), ("entity_id", 1)],      {"name": "by_entity"}),
    (COLL_AUDIT_LOG, [("company_id", 1), ("created_at", -1)], {"name": "by_company_recent"}),
    (COLL_AUDIT_LOG, [("actor_id", 1), ("created_at", -1)],   {"name": "by_actor_recent"}),
    # Counters are fetched by _id only (the sequence key) — no secondary index needed.
    # Declared here so the collection is created at startup rather than on first write.
    (COLL_COUNTERS,  [("scope", 1)],                          {"name": "by_scope"}),

    # ── Phase 2: employee master ──
    # One profile per user, enforced at the DB level: a profile EXTENDS the identity in
    # staff/learners, it is never a second copy of it.
    # SPARSE, deliberately: Phase 9 creates an employee record at onboarding, BEFORE the
    # person has a login. Those rows omit  entirely (not null -- a null value is
    # still indexed), so any number of them can coexist while a linked profile stays unique.
    (COLL_EMPLOYEE_PROFILES, [("user_id", 1)],                {"unique": True, "sparse": True,
                                                               "name": "uniq_user"}),
    (COLL_EMPLOYEE_PROFILES, [("company_id", 1), ("employment_status", 1)],
                                                              {"name": "by_company_status"}),
    # Sparse: a profile may exist before a code is minted, but codes never collide.
    (COLL_EMPLOYEE_PROFILES, [("company_id", 1), ("employee_code", 1)],
                                                              {"unique": True, "sparse": True,
                                                               "name": "uniq_company_code"}),
    (COLL_EMPLOYEE_PROFILES, [("company_id", 1), ("department_id", 1)],
                                                              {"name": "by_company_department"}),
    (COLL_DEPARTMENTS,  [("company_id", 1), ("name", 1)],     {"unique": True, "name": "uniq_company_name"}),
    (COLL_DESIGNATIONS, [("company_id", 1), ("name", 1)],     {"unique": True, "name": "uniq_company_name"}),

    # ── Phase 3: requisitions + job descriptions ──
    # Composite with company_id, not a bare unique: next_business_id mints request_no PER
    # COMPANY (see counter_key's own docstring), so two companies legitimately both reach
    # "HR-REQ-2026-021" -- a bare unique index refuses the second one's insert with an
    # E11000 the moment both counters reach the same number. Same class of bug as
    # uniq_assessment_no below, just an earlier phase that predates that fix.
    (COLL_REQUISITIONS, [("company_id", 1), ("request_no", 1)],
                                                              {"unique": True, "name": "uniq_request_no"}),
    (COLL_REQUISITIONS, [("company_id", 1), ("approval_status", 1)],
                                                              {"name": "by_company_approval"}),
    (COLL_REQUISITIONS, [("company_id", 1), ("closing_status", 1)],
                                                              {"name": "by_company_closing"}),
    (COLL_REQUISITIONS, [("company_id", 1), ("created_by", 1)],
                                                              {"name": "by_company_creator"}),
    (COLL_REQUISITIONS, [("company_id", 1), ("department_id", 1)],
                                                              {"name": "by_company_department"}),
    # Same per-company-sequence issue as request_no above -- reproduced live as
    # "E11000 ... uniq_jd_no dup key: { jd_no: 'JD-2026-021' }" once two companies' JD
    # counters both reached 021.
    (COLL_JOB_DESCRIPTIONS, [("company_id", 1), ("jd_no", 1)],
                                                              {"unique": True, "name": "uniq_jd_no"}),
    (COLL_JOB_DESCRIPTIONS, [("request_no", 1)],              {"name": "by_request"}),
    (COLL_JOB_DESCRIPTIONS, [("company_id", 1), ("status", 1)],
                                                              {"name": "by_company_status"}),

    # ── Phase 4: job postings + public application intake ──
    (COLL_JOB_POSTINGS, [("posting_code", 1)],                {"unique": True, "name": "uniq_posting_code"}),
    (COLL_JOB_POSTINGS, [("jd_no", 1)],                       {"name": "by_jd"}),
    (COLL_JOB_POSTINGS, [("company_id", 1), ("live_status", 1)],
                                                              {"name": "by_company_live"}),
    (COLL_JOB_POSTINGS, [("request_no", 1)],                  {"name": "by_request"}),
    # Composite with company_id -- uk is minted per company by next_business_id, same as
    # every other business id in this file.
    (COLL_CANDIDATES,   [("company_id", 1), ("uk", 1)],       {"unique": True, "name": "uniq_uk"}),
    (COLL_CANDIDATES,   [("company_id", 1), ("application_status", 1)],
                                                              {"name": "by_company_status"}),
    (COLL_CANDIDATES,   [("posting_code", 1)],                {"name": "by_posting"}),
    (COLL_CANDIDATES,   [("request_no", 1)],                  {"name": "by_request"}),
    # Duplicate detection runs on every public application, so both must be indexed.
    (COLL_CANDIDATES,   [("company_id", 1), ("can_email", 1)], {"name": "by_company_email"}),
    (COLL_CANDIDATES,   [("company_id", 1), ("can_contact", 1)], {"name": "by_company_phone"}),
    # Mongo's TTL monitor sweeps roughly every 60s; that is cleanup only. Expiry is enforced
    # arithmetically in the limiter, so a late sweep can never widen the window.
    (COLL_PUBLIC_RATELIMIT, [("expires_at", 1)],              {"expireAfterSeconds": 0,
                                                               "name": "ttl_expires"}),

    # ── Phase 6: assessments ──
    # Compound with company_id, not a bare unique on assessment_no: next_business_id scopes
    # its counter PER COMPANY (counter_key's own docstring -- "a client must not be able to
    # infer another client's hiring volume from gaps in their own numbering"), so two
    # different companies legitimately mint the same "ASM-2026-008". A bare unique index
    # rejected the second company's insert with a 500 (E11000) the moment both companies'
    # counters reached the same number -- reconciled the same way Phase 9 fixed uniq_user.
    (COLL_ASSESSMENTS, [("company_id", 1), ("assessment_no", 1)],
                                                              {"unique": True, "name": "uniq_assessment_no"}),
    # The access code is the ONLY credential protecting a candidate's submission, so it is
    # both unique and indexed -- every public request looks up by it.
    (COLL_ASSESSMENTS, [("access_code", 1)],                  {"unique": True, "name": "uniq_access_code"}),
    (COLL_ASSESSMENTS, [("uk", 1)],                           {"name": "by_candidate"}),
    (COLL_ASSESSMENTS, [("company_id", 1), ("status", 1)],    {"name": "by_company_status"}),
    (COLL_ASSESSMENTS, [("request_no", 1)],                   {"name": "by_request"}),

    # ── Phase 7: interviews ──
    # Composite with company_id -- interview_no is minted per company.
    (COLL_INTERVIEWS, [("company_id", 1), ("interview_no", 1)],
                                                              {"unique": True, "name": "uniq_interview_no"}),
    (COLL_INTERVIEWS, [("uk", 1)],                            {"name": "by_candidate"}),
    (COLL_INTERVIEWS, [("company_id", 1), ("status", 1)],     {"name": "by_company_status"}),
    # The board groups by day, so the feed always sorts on this.
    (COLL_INTERVIEWS, [("company_id", 1), ("scheduled_at", 1)],
                                                              {"name": "by_company_when"}),
    # An interviewer's own list is the default view for non-privileged users.
    (COLL_INTERVIEWS, [("interviewer_id", 1)],                {"name": "by_interviewer"}),

    # ── Phase 8: offers ──
    # Composite with company_id -- offer_no is minted per company.
    (COLL_OFFERS, [("company_id", 1), ("offer_no", 1)],       {"unique": True, "name": "uniq_offer_no"}),
    # The access code is the candidate's only credential; every public request looks it up.
    (COLL_OFFERS, [("access_code", 1)],                       {"unique": True, "name": "uniq_access_code"}),
    (COLL_OFFERS, [("uk", 1)],                                {"name": "by_candidate"}),
    (COLL_OFFERS, [("company_id", 1), ("status", 1)],         {"name": "by_company_status"}),
    (COLL_OFFERS, [("request_no", 1)],                        {"name": "by_request"}),

    # ── Phase 9: onboarding ──
    # Composite with company_id -- onb_no is minted per company.
    (COLL_ONBOARDING, [("company_id", 1), ("onb_no", 1)],     {"unique": True, "name": "uniq_onb_no"}),
    (COLL_ONBOARDING, [("access_code", 1)],                   {"unique": True, "name": "uniq_access_code"}),
    # Composite with company_id -- uk is per-company too (see uniq_uk above), so without
    # this a candidate from one company blocks a same-numbered candidate from another
    # company from ever starting onboarding.
    (COLL_ONBOARDING, [("company_id", 1), ("uk", 1)],         {"unique": True, "name": "uniq_candidate"}),
    (COLL_ONBOARDING, [("company_id", 1), ("status", 1)],     {"name": "by_company_status"}),
    # Sparse: the id is minted partway through, so most rows have none yet. Composite with
    # company_id -- employee_id is minted per company by next_business_id, same as every
    # other business id in this file.
    (COLL_ONBOARDING, [("company_id", 1), ("employee_id", 1)], {"unique": True, "sparse": True,
                                                               "name": "uniq_employee_id"}),

    # -- Phase 10: date-ranged analytics ------------------------------------------
    # Every dashboard query is `company_id` + a date window. Without these the planner can
    # only use the company_id prefix of an existing (company_id, status) index and then
    # filters by date in memory, which degrades as history accumulates.
    (COLL_CANDIDATES,   [("company_id", 1), ("applied_at", -1)], {"name": "by_company_applied"}),
    (COLL_OFFERS,       [("company_id", 1), ("created_at", -1)], {"name": "by_company_created"}),
    (COLL_ONBOARDING,   [("company_id", 1), ("created_at", -1)], {"name": "by_company_created"}),
    (COLL_REQUISITIONS, [("company_id", 1), ("created_at", -1)], {"name": "by_company_created"}),

    # ── Phase 11-R: link registry, documents, appointments, clients, sanction ──
    # The registry is looked up by CODE on every public request (the revocation guard), so
    # that index is unique and is the hot one. The rest serve the Link Manager's filters.
    (COLL_LINKS, [("code", 1)],                               {"unique": True, "name": "uniq_code"}),
    # Composite with company_id -- link_id (unlike code, a random token) is minted per
    # company by next_business_id, same as every other business id in this file.
    (COLL_LINKS, [("company_id", 1), ("link_id", 1)],         {"unique": True, "name": "uniq_link_id"}),
    (COLL_LINKS, [("company_id", 1), ("kind", 1), ("status", 1)],
                                                              {"name": "by_company_kind_status"}),
    (COLL_LINKS, [("company_id", 1), ("created_at", -1)],     {"name": "by_company_created"}),
    (COLL_LINKS, [("target_id", 1)],                          {"name": "by_target"}),
    (COLL_LINKS, [("request_no", 1)],                         {"name": "by_request"}),

    # Composite with company_id -- doc_no is minted per company.
    (COLL_DOCUMENTS, [("company_id", 1), ("doc_no", 1)],      {"unique": True, "name": "uniq_doc_no"}),
    (COLL_DOCUMENTS, [("company_id", 1), ("owner_type", 1), ("owner_id", 1)],
                                                              {"name": "by_owner"}),
    (COLL_DOCUMENTS, [("company_id", 1), ("status", 1)],      {"name": "by_company_status"}),
    # Drives the expiring-soon filter, which is a range scan on this field.
    (COLL_DOCUMENTS, [("company_id", 1), ("expiry_date", 1)], {"name": "by_company_expiry"}),
    (COLL_DOCUMENTS, [("request_no", 1)],                     {"name": "by_request"}),
    (COLL_DOCUMENT_TYPES, [("company_id", 1), ("name", 1)],   {"unique": True,
                                                               "name": "uniq_company_name"}),

    # One appointment letter per candidate, enforced at the DB level: the letter confirms
    # joining terms, and two of them for one person is a contradiction, not a workflow.
    # Composite with company_id -- appointment_no and uk are both per-company (uk per
    # uniq_uk above), same fix as requisitions/JDs/candidates/interviews/offers/onboarding.
    (COLL_APPOINTMENTS, [("company_id", 1), ("appointment_no", 1)],
                                                              {"unique": True,
                                                               "name": "uniq_appointment_no"}),
    (COLL_APPOINTMENTS, [("access_code", 1)],                 {"unique": True,
                                                               "name": "uniq_access_code"}),
    (COLL_APPOINTMENTS, [("company_id", 1), ("uk", 1)],       {"unique": True,
                                                               "name": "uniq_candidate"}),
    (COLL_APPOINTMENTS, [("company_id", 1), ("status", 1)],   {"name": "by_company_status"}),
    (COLL_APPOINTMENTS, [("request_no", 1)],                  {"name": "by_request"}),

    # Every hiring list and KPI filters on the track discriminator first (see
    # REQUISITION_TRACK_INTERNAL): it is what keeps legacy client-track rows out.
    (COLL_REQUISITIONS, [("company_id", 1), ("requisition_track", 1)],
     {"name": "by_company_track"}),

    # ── Internal recruitment track ──
    # One scorecard per requisition -- the uniqueness IS the rule, exactly as it is for
    # sanctioned strength.
    # Composite with company_id -- scr_no is minted per company.
    (COLL_POSITION_SCORECARDS, [("company_id", 1), ("scr_no", 1)],
                                                              {"unique": True,
                                                               "name": "uniq_scr_no"}),
    (COLL_POSITION_SCORECARDS, [("company_id", 1), ("request_no", 1)],
     {"unique": True, "name": "uniq_company_request"}),

    # Composite with company_id -- ref_no is minted per company.
    (COLL_REFERENCE_CHECKS, [("company_id", 1), ("ref_no", 1)],
                                                              {"unique": True,
                                                               "name": "uniq_ref_no"}),
    # A candidate may have SEVERAL referees, so this is deliberately not unique.
    (COLL_REFERENCE_CHECKS, [("company_id", 1), ("uk", 1)],   {"name": "by_company_candidate"}),
    (COLL_REFERENCE_CHECKS, [("request_no", 1)],              {"name": "by_request"}),

    # Composite with company_id -- prb_no is minted per company.
    (COLL_PROBATION_REVIEWS, [("company_id", 1), ("prb_no", 1)],
                                                              {"unique": True,
                                                               "name": "uniq_prb_no"}),
    # One live probation per employee. A second term after an extension updates this record
    # rather than opening a competing one.
    (COLL_PROBATION_REVIEWS, [("company_id", 1), ("employee_code", 1)],
     {"unique": True, "name": "uniq_company_employee"}),
    # `GET /probation/due` sorts on this, and it is the field the SLA breach sweep reads.
    (COLL_PROBATION_REVIEWS, [("company_id", 1), ("ends_on", 1)], {"name": "by_company_end"}),

    # Composite with company_id -- exc_no is minted per company.
    (COLL_EXCEPTIONS, [("company_id", 1), ("exc_no", 1)],     {"unique": True,
                                                               "name": "uniq_exc_no"}),
    # The gate checks read this exact shape: "is there an APPROVED exception of this type
    # for this requisition (and candidate)".
    (COLL_EXCEPTIONS, [("company_id", 1), ("request_no", 1), ("exception_type", 1),
                       ("status", 1)],                        {"name": "by_gate_lookup"}),
    (COLL_EXCEPTIONS, [("company_id", 1), ("uk", 1)],         {"name": "by_company_candidate"}),

    # One sanctioned figure per position per company — the uniqueness IS the rule.
    (COLL_SANCTIONED_STRENGTH,
     [("company_id", 1), ("department_id", 1), ("designation_id", 1)],
     {"unique": True, "name": "uniq_company_position"}),

    # ── Phase INT-2 ──
    # Composite with company_id -- slr_no is minted per company.
    # -- Client Hiring step 1 -- every lookup is company-scoped FIRST, so a query that
    # forgot the tenant cannot ride an index that would have made it fast.
    (COLL_CLIENT_REQUISITIONS, [("company_id", 1), ("cr_no", 1)],
     {"unique": True, "name": "uniq_client_req_no"}),
    # One scorecard per requisition, enforced by the index rather than by a read-then-write
    # that two requests could both pass.
    (COLL_CLIENT_SCORECARDS, [("company_id", 1), ("cr_no", 1)],
     {"unique": True, "name": "uniq_client_scorecard_per_req"}),
    (COLL_CLIENT_SCORECARDS, [("company_id", 1), ("psc_no", 1)],
     {"unique": True, "name": "uniq_client_psc_no"}),
    (COLL_CLIENT_CANDIDATES, [("company_id", 1), ("ccn_no", 1)],
     {"unique": True, "name": "uniq_client_candidate_no"}),
    # Step 2b -- the job posting. The public code is globally unique because it is the
    # ONLY thing a public request carries: two tenants minting the same code would serve
    # one client's advert from the other's link.
    (COLL_CLIENT_POSTINGS, [("posting_code", 1)],
     {"unique": True, "name": "uniq_client_posting_code"}),
    (COLL_CLIENT_POSTINGS, [("company_id", 1), ("posting_no", 1)],
     {"unique": True, "name": "uniq_client_posting_no"}),
    (COLL_CLIENT_POSTINGS, [("company_id", 1), ("cr_no", 1)],
     {"name": "client_postings_by_req"}),
    (COLL_CLIENT_POSTINGS, [("company_id", 1), ("status", 1)],
     {"name": "client_postings_by_status"}),
    # Applications are candidates, found by the posting they came through.
    (COLL_CLIENT_CANDIDATES, [("posting_code", 1)],
     {"name": "client_candidates_by_posting"}),
    (COLL_CLIENT_ASSESSMENTS, [("company_id", 1), ("cas_no", 1)],
     {"unique": True, "name": "uniq_client_assessment_no"}),
    (COLL_CLIENT_INTERVIEWS, [("company_id", 1), ("cin_no", 1)],
     {"unique": True, "name": "uniq_client_interview_no"}),
    (COLL_CLIENT_REFERENCE_CHECKS, [("company_id", 1), ("crf_no", 1)],
     {"unique": True, "name": "uniq_client_reference_no"}),
    (COLL_CLIENT_REFERENCE_CHECKS, [("company_id", 1), ("ccn_no", 1)],
     {"name": "client_references_by_candidate"}),
    (COLL_CLIENT_OFFERS, [("company_id", 1), ("cof_no", 1)],
     {"unique": True, "name": "uniq_client_offer_no"}),
    (COLL_CLIENT_JOININGS, [("company_id", 1), ("cjn_no", 1)],
     {"unique": True, "name": "uniq_client_joining_no"}),
    (COLL_CLIENT_JOININGS, [("company_id", 1), ("ccn_no", 1)],
     {"unique": True, "name": "uniq_client_joining_per_candidate"}),
    (COLL_CLIENT_JOININGS, [("company_id", 1), ("status", 1)],
     {"name": "client_joinings_by_status"}),
    (COLL_CLIENT_OFFERS, [("company_id", 1), ("ccn_no", 1)],
     {"name": "client_offers_by_candidate"}),
    (COLL_CLIENT_OFFERS, [("company_id", 1), ("status", 1)],
     {"name": "client_offers_by_status"}),
    (COLL_CLIENT_INTERVIEWS, [("company_id", 1), ("ccn_no", 1)],
     {"name": "client_interviews_by_candidate"}),
    (COLL_CLIENT_INTERVIEWS, [("company_id", 1), ("status", 1)],
     {"name": "client_interviews_by_status"}),
    # One live assessment per candidate, enforced by the index rather than a read-then-write.
    (COLL_CLIENT_ASSESSMENTS, [("company_id", 1), ("ccn_no", 1)],
     {"unique": True, "name": "uniq_client_assessment_per_candidate"}),
    (COLL_CLIENT_ASSESSMENTS, [("company_id", 1), ("status", 1)],
     {"name": "client_assessments_by_status"}),
    (COLL_CLIENT_CANDIDATES, [("company_id", 1), ("cr_no", 1), ("status", 1)],
     {"name": "client_candidates_by_req"}),
    (COLL_CLIENT_CANDIDATES, [("company_id", 1), ("status", 1)],
     {"name": "client_candidates_by_status"}),
    (COLL_CLIENT_SCORECARDS, [("company_id", 1), ("status", 1)],
     {"name": "client_scorecard_by_status"}),
    (COLL_CLIENT_REQUISITIONS, [("company_id", 1), ("status", 1)],
     {"name": "client_req_by_status"}),
    (COLL_CLIENT_REQUISITIONS, [("status", 1), ("created_at", -1)],
     {"name": "client_req_review_queue"}),
    (COLL_SHORTLIST_REVIEWS, [("company_id", 1), ("slr_no", 1)],
                                                              {"unique": True,
                                                              "name": "uniq_slr_no"}),
    # The gate on `Selected` asks "is there a committee record covering this candidate on
    # this requisition", so both are indexed. Deliberately NOT unique: a second intake on
    # the same requisition is a second committee sitting, not a correction of the first.
    (COLL_SHORTLIST_REVIEWS, [("company_id", 1), ("request_no", 1)],
     {"name": "by_company_request"}),
    (COLL_SHORTLIST_REVIEWS, [("company_id", 1), ("candidate_uks", 1)],
     {"name": "by_company_candidate"}),

    # Scheduling looks a window up by department and weekday on every booking.
    (COLL_INTERVIEW_WINDOWS, [("company_id", 1), ("department_id", 1), ("weekday", 1)],
     {"name": "by_company_department_day"}),

    # Composite with company_id -- pbt_no is minted per company.
    (COLL_PREBOARDING, [("company_id", 1), ("pbt_no", 1)],   {"unique": True,
                                                              "name": "uniq_pbt_no"}),
    # `GET /preboarding/due` reads the LATEST touchpoint per candidate, so this is the
    # index it sorts on.
    (COLL_PREBOARDING, [("company_id", 1), ("candidate_uk", 1), ("contacted_at", -1)],
     {"name": "by_company_candidate_recent"}),
    (COLL_PREBOARDING, [("request_no", 1)],                  {"name": "by_request"}),

    # One ACTIVE band per (department, designation, grade) is a rule the service enforces
    # rather than the index, because a superseded band stays on file with its own
    # effective dates -- uniqueness here would make history impossible to keep.
    # Composite with company_id -- band_no is minted per company.
    (COLL_SALARY_BANDS, [("company_id", 1), ("band_no", 1)], {"unique": True,
                                                              "name": "uniq_band_no"}),
    (COLL_SALARY_BANDS,
     [("company_id", 1), ("department_id", 1), ("designation_id", 1), ("status", 1)],
     {"name": "by_company_position_status"}),

    # A template is addressed by its KEY, which is why the key is what must be unique.
    (COLL_COMM_TEMPLATES, [("company_id", 1), ("key", 1)],   {"unique": True,
                                                              "name": "uniq_company_key"}),
    (COLL_COMM_LOG, [("company_id", 1), ("candidate_uk", 1), ("sent_at", -1)],
     {"name": "by_company_candidate_recent"}),
    (COLL_COMM_LOG, [("request_no", 1)],                     {"name": "by_request"}),

    # Composite with company_id -- srv_no and srp_no are both minted per company.
    (COLL_SURVEYS, [("company_id", 1), ("srv_no", 1)],       {"unique": True,
                                                              "name": "uniq_srv_no"}),
    (COLL_SURVEYS, [("company_id", 1), ("kind", 1)],         {"name": "by_company_kind"}),
    (COLL_SURVEY_RESPONSES, [("company_id", 1), ("srp_no", 1)],
                                                              {"unique": True,
                                                              "name": "uniq_srp_no"}),
    # One response per instrument per employee. The uniqueness IS the de-duplication, and
    # it is the only reason `employee_code` is stored at all -- see SURVEY_MIN_RESPONSES.
    (COLL_SURVEY_RESPONSES, [("company_id", 1), ("srv_no", 1), ("employee_code", 1)],
     {"unique": True, "sparse": True, "name": "uniq_survey_employee"}),
    (COLL_SURVEY_RESPONSES, [("request_no", 1)],             {"name": "by_request"}),

    (COLL_POLICIES, [("company_id", 1), ("policy_key", 1)],  {"unique": True,
                                                              "name": "uniq_company_policy"}),
    # The review-due sweep is a range scan on this.
    (COLL_POLICIES, [("company_id", 1), ("next_review_due", 1)],
     {"name": "by_company_review_due"}),
    (COLL_POLICY_REVISIONS, [("company_id", 1), ("policy_key", 1), ("version", 1)],
     {"unique": True, "name": "uniq_company_policy_version"}),

    # Composite with company_id -- batch_no is minted per company.
    (COLL_PURGE_BATCHES, [("company_id", 1), ("batch_no", 1)], {"unique": True,
                                                              "name": "uniq_batch_no"}),
    (COLL_PURGE_BATCHES, [("company_id", 1), ("status", 1)], {"name": "by_company_status"}),

    # ── Phase INT-3: the scheduled-job ledger ──
    # UNIQUE, and load-bearing rather than tidy. The ledger is what stops a reminder job
    # running twice in one period, and it can only do that if one (company, job) means one
    # row. Two workers starting the same slot in the same instant both find no row and both
    # insert; this index is what makes the loser's insert raise instead of leaving a second
    # row that `already_ran` might read and let the job fire again.
    (COLL_JOB_RUNS, [("company_id", 1), ("job_key", 1)],     {"unique": True,
                                                              "name": "uniq_company_job"}),

    # ── Phase INT-4: telephonic screening ──
    # NOT unique on (company, candidate): a second call happens (the first was cut off, the
    # candidate asked to be rung back), and the gate asks whether ANY screen passed.
    # Composite with company_id -- tel_no is minted per company.
    (COLL_TELEPHONIC, [("company_id", 1), ("tel_no", 1)],    {"unique": True,
                                                              "name": "uniq_tel_no"}),
    (COLL_TELEPHONIC, [("company_id", 1), ("uk", 1)],        {"name": "by_candidate"}),
    (COLL_TELEPHONIC, [("company_id", 1), ("outcome", 1)],   {"name": "by_company_outcome"}),
    (COLL_TELEPHONIC, [("request_no", 1)],                   {"name": "by_request"}),

    # ── Phase INT-10: salary negotiation rounds ──
    # COMPOSITE with company_id: sequences are minted per company and rendered without
    # one, so two tenants' first round of a year both read NEG-2026-001 -- a bare unique
    # index would refuse the second tenant's first round.
    (COLL_NEGOTIATIONS, [("company_id", 1), ("neg_no", 1)],  {"unique": True,
                                                              "name": "uniq_company_neg_no"}),
    # UNIQUE: round numbers are allocated read-then-insert, and this is what turns two
    # concurrent "round 3"s into one winner and one retry instead of two round 3s.
    (COLL_NEGOTIATIONS, [("company_id", 1), ("uk", 1), ("round", 1)],
                                                             {"unique": True,
                                                              "name": "uniq_candidate_round"}),
    (COLL_NEGOTIATIONS, [("request_no", 1)],                 {"name": "by_request"}),

    # ── Phase INT-5: the per-company rule set ──
    # UNIQUE, and load-bearing: `config_for` reads ONE row per company and lays it over the
    # defaults. Two rows for one company would mean whichever the planner returned first
    # decided that company's SLA targets, which is a rule that changes when nobody changed it.
    (COLL_SETTINGS, [("company_id", 1)],                     {"unique": True,
                                                              "name": "uniq_company"}),

    # ── Phase INT-6: the working calendar ──
    # UNIQUE on (company, date): one date is either a holiday for this company or it is not.
    # Two rows for the same day would be counted once by the maths and twice by the screen.
    (COLL_HOLIDAYS, [("company_id", 1), ("holiday_date", 1)], {"unique": True,
                                                               "name": "uniq_company_date"}),
    # NOT unique on (company, candidate, type): a check is re-run when the first came back
    # inconclusive, and the gate asks whether the LATEST of each required type cleared.
    (COLL_BACKGROUND_CHECKS, [("company_id", 1), ("bgv_no", 1)],
     {"unique": True, "name": "uniq_company_bgv_no"}),
    (COLL_BACKGROUND_CHECKS, [("company_id", 1), ("uk", 1)], {"name": "by_candidate"}),
    (COLL_BACKGROUND_CHECKS, [("company_id", 1), ("status", 1)],
     {"name": "by_company_status"}),
    # ── Phase EXIT-1 — Exit Management ──
    # Compound, not a plain unique index on sep_no alone: sep_no is minted from a
    # PER-COMPANY counter (counter_key), so two different companies legitimately mint the
    # same "SEP-2026-001" — a global unique index rejects the second company's case
    # outright. This was the exact bug Phase ATT-1's uniq_leave_no shipped with and had to
    # fix live (confirmed by a real collision between two test companies); fixed here the
    # same way once found. The NAME is kept as `uniq_sep_no` (not renamed) so
    # _ensure_hrms_collections' existing by-name reconciliation (see its docstring) drops
    # and recreates it automatically on every deployment.
    (COLL_SEPARATIONS, [("company_id", 1), ("sep_no", 1)], {"unique": True, "name": "uniq_sep_no"}),
    (COLL_SEPARATIONS, [("company_id", 1), ("employee_code", 1)],
     {"name": "by_company_employee"}),
    # Listing "who is exiting" is always filtered to what is still open — the ledger of
    # closed cases is history, not a queue anyone works from day to day.
    (COLL_SEPARATIONS, [("company_id", 1), ("stage", 1)], {"name": "by_company_stage"}),
    (COLL_HANDOVER_TASKS, [("company_id", 1), ("sep_no", 1)], {"name": "by_separation"}),
    (COLL_HANDOVER_TASKS, [("company_id", 1), ("owner_id", 1), ("status", 1)],
     {"name": "by_owner_status"}),
    (COLL_CLEARANCE_TASKS, [("company_id", 1), ("sep_no", 1)], {"name": "by_separation"}),
    # "My pending clearances" is the one screen a task owner actually opens.
    (COLL_CLEARANCE_TASKS, [("company_id", 1), ("owner_type", 1), ("status", 1)],
     {"name": "by_owner_type_status"}),
    (COLL_ASSET_RETURNS, [("company_id", 1), ("sep_no", 1)], {"name": "by_separation"}),
    (COLL_ACCESS_CLEARANCES, [("company_id", 1), ("sep_no", 1)], {"name": "by_separation"}),
    # One interview per case — a re-run overwrites rather than accumulating duplicates.
    (COLL_EXIT_INTERVIEWS, [("company_id", 1), ("sep_no", 1)],
     {"unique": True, "name": "uniq_sep_interview"}),
    # One F&F row per case for the same reason — the settlement is a single evolving
    # document (draft → approved → paid), never a history of attempts.
    (COLL_FNF_SETTLEMENTS, [("company_id", 1), ("sep_no", 1)],
     {"unique": True, "name": "uniq_sep_fnf"}),
    # One alumni row per former employee. Upserted at closure, so a case reopened and
    # re-closed corrects the existing row rather than adding a second.
    (COLL_ALUMNI, [("company_id", 1), ("employee_code", 1)],
     {"unique": True, "name": "uniq_alumni_employee"}),
    # ── Phase ATT-1 — Attendance & Leave ──
    # One attendance row per employee per work date — the daily engine's whole output. The
    # regularisation flow updates this row in place (preserving the original in
    # COLL_PUNCH_SEGMENTS); it never inserts a second row for the same day.
    (COLL_ATTENDANCE, [("company_id", 1), ("employee_code", 1), ("work_date", 1)],
     {"unique": True, "name": "uniq_company_employee_date"}),
    # The monthly-closure dashboard's own query: every exception in a period, company-wide.
    (COLL_ATTENDANCE, [("company_id", 1), ("work_date", 1), ("status", 1)],
     {"name": "by_company_date_status"}),
    (COLL_PUNCH_SEGMENTS, [("company_id", 1), ("employee_code", 1), ("work_date", 1)],
     {"name": "by_employee_date"}),
    # Compound on (company_id, req_no): req_no is minted from a PER-COMPANY counter (see
    # counter_key), so two different companies legitimately mint the same "REG-2026-001" —
    # a plain unique index on req_no alone would reject the second company's row outright.
    # Every other business-id index in this phase follows the same (company_id, <no>) shape
    # for the same reason (see leave_no below, which had exactly this bug before the fix).
    (COLL_ATTENDANCE_CORRECTIONS, [("company_id", 1), ("req_no", 1)],
     {"unique": True, "name": "uniq_company_req_no"}),
    (COLL_ATTENDANCE_CORRECTIONS, [("company_id", 1), ("employee_code", 1), ("work_date", 1)],
     {"name": "by_employee_date"}),
    # The approver's queue: everything still awaiting a decision, company-wide.
    (COLL_ATTENDANCE_CORRECTIONS, [("company_id", 1), ("status", 1)],
     {"name": "by_company_status"}),
    (COLL_OD_REQUESTS, [("company_id", 1), ("od_no", 1)],
     {"unique": True, "name": "uniq_company_od_no"}),
    (COLL_OD_REQUESTS, [("company_id", 1), ("employee_code", 1), ("od_date", 1)],
     {"name": "by_employee_date"}),
    (COLL_OD_REQUESTS, [("company_id", 1), ("status", 1)], {"name": "by_company_status"}),
    # One lock row per company per calendar period — the fact a month is closed, not a
    # property of any one attendance row (so 2,000 employees' rows do not need editing to
    # lock or unlock a period).
    (COLL_ATTENDANCE_LOCKS, [("company_id", 1), ("period", 1)],
     {"unique": True, "name": "uniq_company_period"}),
    # Compound, not a plain unique index on leave_no alone: leave_no is minted from a
    # PER-COMPANY counter, so two different companies legitimately mint the same
    # "LV-2026-001" and a global unique index would reject the second company's application
    # outright — confirmed live (a throwaway test company and a real company both reached
    # their own LV-2026-002 and the second write was rejected until this was scoped). The
    # NAME is kept as `uniq_leave_no` (not renamed) so _ensure_hrms_collections' existing
    # by-name reconciliation (see its docstring) drops and recreates it automatically on
    # every deployment, rather than leaving the old global-unique index orphaned alongside
    # a differently-named new one.
    (COLL_LEAVES, [("company_id", 1), ("leave_no", 1)], {"unique": True, "name": "uniq_leave_no"}),
    (COLL_LEAVES, [("company_id", 1), ("employee_code", 1), ("start_date", 1)],
     {"name": "by_employee_start"}),
    (COLL_LEAVES, [("company_id", 1), ("status", 1)], {"name": "by_company_status"}),
    (COLL_LEAVE_BALANCES, [("company_id", 1), ("employee_code", 1), ("leave_type", 1),
                           ("year", 1)],
     {"unique": True, "name": "uniq_employee_type_year"}),
    # One row per (company, leave-type code) — the leave-type MASTER, same shape as
    # hrms_salary_bands: configuration, not a per-employee or per-request record.
    (COLL_LEAVE_TYPES, [("company_id", 1), ("code", 1)],
     {"unique": True, "name": "uniq_company_code"}),
    (COLL_COFF_LEDGER, [("company_id", 1), ("employee_code", 1), ("status", 1)],
     {"name": "by_employee_status"}),
    # FIFO consumption by nearest expiry is the workflow's own rule (§7.11 step 81); this is
    # the index that query actually walks.
    (COLL_COFF_LEDGER, [("company_id", 1), ("employee_code", 1), ("expiry_date", 1)],
     {"name": "by_employee_expiry"}),

    # ── Phase MOVE-1 — Employee Movements & Discipline ──
    # Compound on (company_id, <no>) throughout, NOT a plain unique index on the business id
    # alone: every one of these numbers is minted from a PER-COMPANY counter (counter_key),
    # so two different companies legitimately mint the same "MOV-2026-001" — a global unique
    # index would reject the second company's row outright. This is the exact bug Phase
    # ATT-1's uniq_leave_no shipped with and had to fix live; every new business-id index
    # from here on is compound from the start.
    (COLL_EMPLOYEE_MOVEMENTS, [("company_id", 1), ("move_no", 1)],
     {"unique": True, "name": "uniq_move_no"}),
    (COLL_EMPLOYEE_MOVEMENTS, [("company_id", 1), ("employee_code", 1), ("effective_date", 1)],
     {"name": "by_employee_effective"}),
    # The scheduler's own query: everything approved but not yet applied, whose effective
    # date has arrived — see hrms_movement_service.apply_due_movements.
    (COLL_EMPLOYEE_MOVEMENTS, [("company_id", 1), ("status", 1), ("effective_date", 1)],
     {"name": "by_company_status_effective"}),
    (COLL_DISCIPLINE_CASES, [("company_id", 1), ("case_no", 1)],
     {"unique": True, "name": "uniq_case_no"}),
    (COLL_DISCIPLINE_CASES, [("company_id", 1), ("status", 1)], {"name": "by_company_status"}),
    # A person's OWN discipline history — read through the persons_involved array, since a
    # case is filed against (or by) somebody, not owned by one "employee_code" field the way
    # a leave request is.
    (COLL_DISCIPLINE_CASES, [("company_id", 1), ("persons_involved.employee_code", 1)],
     {"name": "by_person"}),
    (COLL_ABSCONDING_CASES, [("company_id", 1), ("case_no", 1)],
     {"unique": True, "name": "uniq_absconding_case_no"}),
    (COLL_ABSCONDING_CASES, [("company_id", 1), ("employee_code", 1)],
     {"name": "by_company_employee"}),
    (COLL_ABSCONDING_CASES, [("company_id", 1), ("status", 1)], {"name": "by_company_status"}),

    # ── Phase PAY-1 — Payroll, Salary Advance & Variable Pay ──
    (COLL_SALARY_COMPONENTS, [("company_id", 1), ("code", 1)],
     {"unique": True, "name": "uniq_company_code"}),
    (COLL_PAYROLL_TEMPLATES, [("company_id", 1)], {"unique": True, "name": "uniq_payroll_template"}),
    (COLL_SALARY_STRUCTURES, [("company_id", 1), ("employee_code", 1), ("effective_from", 1)],
     {"name": "by_employee_effective"}),
    (COLL_PAYROLL_RUNS, [("company_id", 1), ("period", 1)],
     {"unique": True, "name": "uniq_company_period"}),
    (COLL_PAYROLL_RECORDS, [("company_id", 1), ("period", 1), ("employee_code", 1)],
     {"unique": True, "name": "uniq_period_employee"}),
    (COLL_SALARY_ADVANCES, [("company_id", 1), ("adv_no", 1)],
     {"unique": True, "name": "uniq_adv_no"}),
    (COLL_SALARY_ADVANCES, [("company_id", 1), ("employee_code", 1), ("quarter", 1)],
     {"name": "by_employee_quarter"}),
    (COLL_SALARY_ADVANCES, [("company_id", 1), ("status", 1)], {"name": "by_company_status"}),
    (COLL_VARIABLE_PAY_QUARTERS, [("company_id", 1), ("quarter", 1)],
     {"unique": True, "name": "uniq_company_quarter"}),
    (COLL_VARIABLE_PAY_RECORDS, [("company_id", 1), ("quarter", 1), ("employee_code", 1)],
     {"unique": True, "name": "uniq_quarter_employee"}),
    (COLL_VARIABLE_PAY_HOLD_LEDGER, [("company_id", 1), ("employee_code", 1), ("status", 1)],
     {"name": "by_employee_status"}),

    # ── Phase PIP-1 — Performance Improvement Plan ──
    (COLL_PIP_RECORDS, [("company_id", 1), ("pip_no", 1)],
     {"unique": True, "name": "uniq_pip_no"}),
    (COLL_PIP_RECORDS, [("company_id", 1), ("employee_code", 1)], {"name": "by_employee"}),
    (COLL_PIP_RECORDS, [("company_id", 1), ("status", 1)], {"name": "by_company_status"}),

    # ── Phase GMP-1 ── one enrolment per employee.
    (COLL_GMP_RECORDS, [("company_id", 1), ("employee_code", 1)],
     {"unique": True, "name": "uniq_gmp_employee"}),

    # ── Phase LETTER-1 — HR Letter / Document Generator ──
    (COLL_LETTER_TEMPLATES, [("company_id", 1), ("key", 1)],
     {"unique": True, "name": "uniq_company_template_key"}),
    (COLL_LETTERS, [("company_id", 1), ("letter_no", 1)],
     {"unique": True, "name": "uniq_letter_no"}),
    (COLL_LETTERS, [("company_id", 1), ("employee_code", 1)], {"name": "by_employee"}),
    (COLL_LETTERS, [("company_id", 1), ("series_no", 1)], {"name": "by_series"}),

    # ── Phase ORIENT-1 — Orientation & Training ──
    (COLL_ORIENTATION_PLANS, [("company_id", 1), ("active", 1)], {"name": "by_company_active"}),
    (COLL_ORIENTATION_ASSIGNMENTS, [("company_id", 1), ("employee_code", 1)],
     {"unique": True, "name": "uniq_company_employee"}),
    (COLL_ORIENTATION_ASSIGNMENTS, [("company_id", 1), ("overall_status", 1)],
     {"name": "by_company_status"}),

    # ── Phase PULSE-1 — 30/90-Day Pulse Survey ──
    (COLL_PULSE_RESPONSES, [("company_id", 1), ("employee_code", 1), ("milestone", 1)],
     {"unique": True, "name": "uniq_company_employee_milestone"}),
    (COLL_PULSE_RESPONSES, [("company_id", 1), ("status", 1)], {"name": "by_company_status"}),
    (COLL_PULSE_RESPONSES, [("company_id", 1), ("follow_up_required", 1)],
     {"name": "by_company_follow_up"}),
    # ── Later phases append their indexes here, one phase at a time. ──
]


# ─────────────────────────────────────────────────────────────
# Roles — translation from the ERP identity model to HRMS roles
# ─────────────────────────────────────────────────────────────
# The ERP has two user collections and two role axes:
#   • `staff`    → role: superadmin | admin | coach | staff        (Sparsh internal)
#   • `learners` → role: clientadmin | clientuser                  (client-side)
#                  + governance_role: MD | HR | FINANCE | HOD | IMPLEMENTOR
#                    (the client ladder, already used by auth_controller.client_rank)
#
# HRMS is Sparsh Magic's OWN HR and hiring module: it hires and pays Sparsh's own staff,
# scoped by company_id (the one in-house tenant). The ERP's client companies are never
# party to it. Sparsh internal staff get admin/support visibility.
class HrmsRole(str, Enum):
    ADMIN    = "admin"      # Sparsh superadmin — full HRMS owner, cross-company
    INTERNAL = "internal"   # Sparsh admin/coach/staff — cross-company operator + support
    MD       = "md"         # client MD / clientadmin — final approver within their company
    HR       = "hr"         # client HR — the recruitment + HR-ops operator
    # Internal-track budget authority. The Internal Recruitment SOP treats
    # "Management / Finance" as ONE accountable actor (Annexure B), so FINANCE holds the
    # budget and offer approvals but NOT the hiring judgement — it approves what a role
    # costs, never who fills it.
    FINANCE  = "finance"
    MANAGER  = "manager"    # client HOD — hiring manager; raises reqs, co-reviews assessments
    EMPLOYEE = "employee"   # client implementor / plain user — self-service only


# =============================================================
# Client Hiring, step 1 -- Need Mapping -> Manpower Requisition -> feasibility
# =============================================================
# PRO-fit SOP section 7. TWO forms, ONE record.
#
# The SOP describes a Need Mapping Form and a Manpower Requisition Form as separate
# documents, and they are modelled here as two STAGES of one requisition rather than two
# collections. They describe the same vacancy: the NMF captures why the client needs
# somebody, the MRF formalises what the role actually is. Splitting them would mean
# maintaining a join whose only job is to say "these two papers are the same job", and
# would make "no sourcing until BOTH are complete" a cross-collection invariant rather than
# a status on one row.
#
# Nothing here is shared with the internal requisition. Different collection, different
# statuses, different capabilities, different service. Internal Hiring's own chain
# (INTERNAL_REQ_TRANSITIONS) is untouched and must stay that way.
class ClientReqStatus(str, Enum):
    """Where a client requisition sits. The SOP's section 7, as states."""
    NEED_MAPPING        = "Need Mapping"          # client is filling the NMF
    MANPOWER_REQUISITION = "Manpower Requisition"  # NMF done; client is filling the MRF
    PENDING_FEASIBILITY = "Pending Feasibility"   # submitted; Sparsh must review
    APPROVED            = "Approved"              # activated; the scorecard stage may begin
    REJECTED            = "Rejected"              # Sparsh refused it
    CLOSED              = "Closed"                # withdrawn or no longer needed


class ClientRoleLevel(str, Enum):
    """The Role Level the SOP's section 12 interview-panel table is written in terms of.

    Carried on the Manpower Requisition because section 15 hangs a control off it: a
    reference check before offer release "for managerial and above roles". A level nobody
    records is a control that never fires, so it is asked for on the requisition rather
    than inferred from a job title.
    """
    JUNIOR      = "Junior / Executive"
    MID         = "Mid-level / Specialist"
    MANAGERIAL  = "Managerial"
    LEADERSHIP  = "Senior Leadership"


# Section 15: the pre-offer reference check applies to "managerial and above".
CLIENT_REFERENCE_REQUIRED_LEVELS = {ClientRoleLevel.MANAGERIAL.value,
                                    ClientRoleLevel.LEADERSHIP.value}

# Only a positive reference clears the gate. "Unable to Verify" is completed WORK but not
# a clearance -- the same distinction the internal track draws, and for the same reason.
CLIENT_REFERENCE_CLEARS = {"Positive"}


class ClientReferenceOutcome(str, Enum):
    POSITIVE         = "Positive"
    NEGATIVE         = "Negative"
    UNABLE_TO_VERIFY = "Unable to Verify"


class EmploymentTypeClient(str, Enum):
    """SOP section 2: the position categories a PRO-fit engagement handles."""
    PERMANENT   = "Permanent"
    CONTRACTUAL = "Contractual"
    REPLACEMENT = "Replacement"
    VOLUME      = "Volume Hiring"


class ClientReqUrgency(str, Enum):
    IMMEDIATE = "Immediate"
    HIGH      = "High"
    NORMAL    = "Normal"


# The state machine, as data. Same shape as INTERNAL_REQ_TRANSITIONS so both tracks are
# read the same way, and deliberately a SEPARATE table so a change to one cannot move the
# other.
#
#   action -> (from, to, capability, is_terminal_refusal)
#
# There is no edge out of REJECTED or CLOSED. "A rejected requisition cannot progress" is
# therefore a property of the table rather than a check somebody has to remember to write.
CLIENT_REQ_TRANSITIONS = {
    # The client completes the Need Mapping Form and moves on to the requisition form.
    "submit-need-mapping": (ClientReqStatus.NEED_MAPPING,
                            ClientReqStatus.MANPOWER_REQUISITION,
                            "CLIENT_REQUISITION_WRITE", False),
    # The client completes the Manpower Requisition Form and sends it to Sparsh.
    "submit-requisition":  (ClientReqStatus.MANPOWER_REQUISITION,
                            ClientReqStatus.PENDING_FEASIBILITY,
                            "CLIENT_REQUISITION_WRITE", False),
    # Sparsh's feasibility and budget review -- section 7 step 3.
    "feasibility-approve": (ClientReqStatus.PENDING_FEASIBILITY, ClientReqStatus.APPROVED,
                            "CLIENT_REQUISITION_REVIEW", False),
    "feasibility-reject":  (ClientReqStatus.PENDING_FEASIBILITY, ClientReqStatus.REJECTED,
                            "CLIENT_REQUISITION_REVIEW", True),
    # Sent back for the client to correct, rather than refused outright. Not a rejection:
    # the requisition is alive, it is simply back with the person who can fix it.
    "feasibility-return":  (ClientReqStatus.PENDING_FEASIBILITY,
                            ClientReqStatus.MANPOWER_REQUISITION,
                            "CLIENT_REQUISITION_REVIEW", True),
}

# Statuses from which the CLIENT may still edit their own forms.
CLIENT_REQ_EDITABLE = {ClientReqStatus.NEED_MAPPING.value,
                       ClientReqStatus.MANPOWER_REQUISITION.value}

# Terminal. Nothing leaves these, by design.
CLIENT_REQ_CLOSED = {ClientReqStatus.REJECTED.value, ClientReqStatus.CLOSED.value}

# What the feasibility reviewer must actually assess (SOP section 7 step 3). Declared so the
# screen and the service ask for the same three things, and so "reviewed" cannot mean
# "somebody clicked approve".
FEASIBILITY_CHECKS = [
    ("role_clarity",              "Role clarity"),
    ("compensation_competitive",  "Compensation competitiveness"),
    ("timeline_realistic",        "Realistic timeline"),
]

# =============================================================
# Client Hiring, step 2 -- the Position Scorecard
# =============================================================
# PRO-fit SOP section 4 (definition), section 6 (principle) and the section 8 approval
# matrix. The scorecard is the EVALUATION BENCHMARK: every later score on this track --
# the Talent Fit Score at screening, the comparative scorecard shared with the client --
# is a measurement against it. Section 6: "No candidate shall be presented to a client
# without an approved Position Scorecard as the evaluation benchmark."
#
# So it is approved before sourcing, not after, and the client's approval is mandatory.
# Approving a benchmark once candidates already exist would let the yardstick be chosen to
# fit the people already found, which is the whole reason the SOP puts it at step 4.
class ClientScorecardStatus(str, Enum):
    DRAFT                   = "Draft"                    # the recruiter is writing it
    PENDING_INTERNAL_REVIEW = "Pending Internal Review"   # Team Lead, before client sharing
    PENDING_CLIENT_APPROVAL = "Pending Client Approval"   # shared with the client
    APPROVED                = "Approved"                  # sourcing may begin


# The five sections SOP section 4 names. Declared as data so the form, the service and the
# completeness check ask for the same things, and so "what is a scorecard" is answerable
# without reading three files.
CLIENT_SCORECARD_SECTIONS = [
    ("responsibilities",      "Responsibilities"),
    ("skills",                "Skills"),
    ("experience",            "Experience"),
    ("cultural_expectations", "Cultural expectations"),
    ("success_indicators",    "Success indicators"),
]

# action -> (from, to, capability, remarks_required)
#
# Recruiter drafts, Team Lead reviews, client approves -- the section 8 matrix, as a table.
# Either reviewer may send it back, and a return is not a rejection: the scorecard returns
# to Draft with the reason on it, because a benchmark nobody agreed is a document to fix
# rather than a decision to record.
CLIENT_SCORECARD_TRANSITIONS = {
    "submit-for-review": (ClientScorecardStatus.DRAFT,
                          ClientScorecardStatus.PENDING_INTERNAL_REVIEW,
                          "CLIENT_SCORECARD_WRITE", False),
    "internal-approve":  (ClientScorecardStatus.PENDING_INTERNAL_REVIEW,
                          ClientScorecardStatus.PENDING_CLIENT_APPROVAL,
                          "CLIENT_SCORECARD_REVIEW", False),
    "internal-return":   (ClientScorecardStatus.PENDING_INTERNAL_REVIEW,
                          ClientScorecardStatus.DRAFT,
                          "CLIENT_SCORECARD_REVIEW", True),
    "client-approve":    (ClientScorecardStatus.PENDING_CLIENT_APPROVAL,
                          ClientScorecardStatus.APPROVED,
                          "CLIENT_SCORECARD_APPROVE", False),
    "client-return":     (ClientScorecardStatus.PENDING_CLIENT_APPROVAL,
                          ClientScorecardStatus.DRAFT,
                          "CLIENT_SCORECARD_APPROVE", True),
}

# Only the recruiter's own draft is editable. Once it is with a reviewer it is a document
# under consideration, and editing it underneath them would make their approval meaningless.
CLIENT_SCORECARD_EDITABLE = {ClientScorecardStatus.DRAFT.value}

# What the client is allowed to SEE. A scorecard still with Sparsh is work in progress, and
# showing a client a draft their recruiter has not finished invites approval of the wrong
# thing. Read as a set so the rule is one lookup rather than a comparison to get backwards.
CLIENT_SCORECARD_VISIBLE_TO_CLIENT = {
    ClientScorecardStatus.PENDING_CLIENT_APPROVAL.value,
    ClientScorecardStatus.APPROVED.value,
}

# =============================================================
# Client Hiring, step 2b -- the job posting
# =============================================================
# An approved Position Scorecard is a benchmark, not an advert. The posting is what turns
# it into something a person can apply to, and it is deliberately a SEPARATE record from
# the internal track's `hrms_job_postings`: same idea, different tenant, different
# audience, and one collection serving both would put a client's advert one query mistake
# away from Sparsh Magic's own.
#
# Three states and no more. A posting is being written, it is open to applications, or it
# is not. Anything finer (paused, expiring, exec-search approval) belongs to the internal
# track's own lifecycle and is not what this flow asked for.
class ClientPostingStatus(str, Enum):
    DRAFT     = "Draft"        # being written; no public link works yet
    PUBLISHED = "Published"    # live, and applications are being accepted
    CLOSED    = "Closed"       # no longer accepting; applications already in stay put


# action -> (from, to, capability, remarks_required)
CLIENT_POSTING_TRANSITIONS = {
    "publish": (ClientPostingStatus.DRAFT, ClientPostingStatus.PUBLISHED,
                "CLIENT_POSTING_PUBLISH", False),
    # Closing needs a reason: a posting that stops accepting applications mid-search is a
    # decision somebody will ask about, and "why did this close" is the question.
    "close":   (ClientPostingStatus.PUBLISHED, ClientPostingStatus.CLOSED,
                "CLIENT_POSTING_WRITE", True),
}

# Only a draft is editable. Once it is published the wording is what applicants were
# shown, and editing it underneath them rewrites the advert they answered.
CLIENT_POSTING_EDITABLE = {ClientPostingStatus.DRAFT.value}


# =============================================================
# Client Hiring, steps 3-4 -- candidates, screening and the CV share
# =============================================================
# PRO-fit SOP sections 10 (sourcing), 11 (screening), 13 (evaluation) and 14 (selection).
#
# A CLIENT candidate is a different record from an internal one. Same real person,
# perhaps, but a different process, different scores, a different owner and a different
# audience -- and above all a different tenant. Keeping them in one collection would put
# Sparsh's own applicants one query mistake away from a client's screen.
class ClientCandidateStatus(str, Enum):
    SOURCED            = "Sourced"              # found, not yet measured
    SCREENED           = "Screened"             # Talent Fit Score recorded (section 11)
    TELEPHONIC_PASSED  = "Telephonic Passed"    # PI Score recorded, passed
    TELEPHONIC_FAILED  = "Telephonic Failed"    # revivable; not a rejection of the person
    SHORTLISTED        = "Shortlisted"          # Sparsh's internal pick
    SHARED_WITH_CLIENT = "Shared with Client"   # awaiting the client's CV verdict
    CLIENT_APPROVED    = "Client Approved"      # the gate into assessment
    # Step 5 drives these two. They are set by the assessment service rather than by the
    # candidate's own action endpoint, the same way the internal interview service moves an
    # internal candidate: the stage is a consequence of work recorded elsewhere, and
    # letting somebody set it by hand would let the pipeline claim an assessment that
    # never happened.
    ASSESSMENT         = "Assessment"           # sitting the assessment
    ASSESSMENT_REVIEWED = "Assessment Reviewed"  # client has read the result
    INTERVIEW          = "Interview"            # step 6 drives this
    SELECTED           = "Selected"             # the client chose them
    OFFER_RELEASED     = "Offer Released"       # step 7 drives these two
    OFFER_ACCEPTED     = "Offer Accepted"
    OFFER_DECLINED     = "Offer Declined"
    PRE_BOARDING       = "Pre-boarding"         # steps 8-9 drive these three
    JOINED             = "Joined"
    DROPPED            = "Dropped Out"
    CLIENT_REJECTED    = "Client Rejected"      # the client passed on them
    WITHDRAWN          = "Withdrawn"            # the candidate stepped away


# SOP section 13's decision guide, as data. "No candidate shall be shortlisted solely on
# personal recommendation without meeting the minimum score threshold", so the threshold
# has to be a number the system knows rather than a paragraph somebody read once.
#
# (floor, label, may_shortlist)
CLIENT_SCORE_GUIDE = [
    (4.0, "Strong -- recommend for client presentation", True),
    (3.5, "Consider -- present with notes",              True),
    (3.0, "Hold -- compare against other candidates",    False),
    (0.0, "Reject",                                      False),
]

# Below this, section 13 says reject. Named so the gate and the guide cannot drift.
CLIENT_SHORTLIST_MIN_SCORE = 3.5


def client_score_band(score) -> dict:
    """Which band a score falls in, and whether it may be shortlisted. Pure."""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return {"score": None, "label": "Not scored", "may_shortlist": False}
    for floor, label, may in CLIENT_SCORE_GUIDE:
        if value >= floor:
            return {"score": round(value, 2), "label": label, "may_shortlist": may}
    return {"score": round(value, 2), "label": "Reject", "may_shortlist": False}


# The scores SOP section 13 names. Averaged into the figure the guide bands.
CLIENT_SCORE_FIELDS = [
    ("tfs_score",        "Talent Fit Score"),
    ("competency_score", "Competency Score"),
    ("pi_score",         "Preliminary Interview Score"),
]

# action -> (from, to, capability, remarks_required)
CLIENT_CANDIDATE_TRANSITIONS = {
    # The recruiter measures the CV against the approved Position Scorecard (section 11).
    "screen":            (ClientCandidateStatus.SOURCED, ClientCandidateStatus.SCREENED,
                          "CLIENT_CANDIDATE_WRITE", False),
    # The brief telephonic interview, section 11.
    "telephonic-pass":   (ClientCandidateStatus.SCREENED,
                          ClientCandidateStatus.TELEPHONIC_PASSED,
                          "CLIENT_CANDIDATE_WRITE", False),
    "telephonic-fail":   (ClientCandidateStatus.SCREENED,
                          ClientCandidateStatus.TELEPHONIC_FAILED,
                          "CLIENT_CANDIDATE_WRITE", True),
    # A telephonic failure is NOT a rejection of the person -- the status has said so since
    # it was written, and TELEPHONIC_FAILED is deliberately absent from
    # CLIENT_CANDIDATE_CLOSED. But there was no way back out of it, so "revivable" was a
    # comment rather than a behaviour: the candidate sat in a state that was neither closed
    # nor movable. Back to SCREENED, because the screening scores still stand and it is the
    # telephonic that is being given a second run. Remarks required -- reviving somebody a
    # colleague failed is a judgement that should carry its reason.
    "revive":            (ClientCandidateStatus.TELEPHONIC_FAILED,
                          ClientCandidateStatus.SCREENED,
                          "CLIENT_CANDIDATE_WRITE", True),
    # Sparsh's own pick, gated on the section 13 threshold.
    "shortlist":         (ClientCandidateStatus.TELEPHONIC_PASSED,
                          ClientCandidateStatus.SHORTLISTED,
                          "CLIENT_CANDIDATE_WRITE", False),
    # Delivery to the client is the Team Lead's accountability, not the recruiter's.
    "share":             (ClientCandidateStatus.SHORTLISTED,
                          ClientCandidateStatus.SHARED_WITH_CLIENT,
                          "CLIENT_CANDIDATE_SHARE", False),
    # THE GATE. The client's verdict is what lets a candidate into assessment.
    "client-approve":    (ClientCandidateStatus.SHARED_WITH_CLIENT,
                          ClientCandidateStatus.CLIENT_APPROVED,
                          "CLIENT_CANDIDATE_DECIDE", False),
    "client-reject":     (ClientCandidateStatus.SHARED_WITH_CLIENT,
                          ClientCandidateStatus.CLIENT_REJECTED,
                          "CLIENT_CANDIDATE_DECIDE", True),
}

# A client sees a candidate once they have been shared, and not one moment before. Sourcing
# and screening are Sparsh's working process; a client watching it would be reading an
# opinion that has not been formed yet.
CLIENT_CANDIDATE_VISIBLE_TO_CLIENT = {
    ClientCandidateStatus.SHARED_WITH_CLIENT.value,
    ClientCandidateStatus.CLIENT_APPROVED.value,
    ClientCandidateStatus.CLIENT_REJECTED.value,
    # Once a client has approved a CV the candidate stays theirs to follow, so every later
    # stage is visible too. Losing sight of somebody the moment they progress would be a
    # strange reading of a rule meant to hide work in progress.
    ClientCandidateStatus.ASSESSMENT.value,
    ClientCandidateStatus.ASSESSMENT_REVIEWED.value,
    ClientCandidateStatus.INTERVIEW.value,
    ClientCandidateStatus.SELECTED.value,
    ClientCandidateStatus.OFFER_RELEASED.value,
    ClientCandidateStatus.OFFER_ACCEPTED.value,
    ClientCandidateStatus.OFFER_DECLINED.value,
    ClientCandidateStatus.PRE_BOARDING.value,
    ClientCandidateStatus.JOINED.value,
    ClientCandidateStatus.DROPPED.value,
}

# Nothing leaves these -- on THIS engagement. See CLIENT_CANDIDATE_POOL below: a closed
# state ends a candidate's run at one client, not their usefulness as a person.
CLIENT_CANDIDATE_CLOSED = {ClientCandidateStatus.CLIENT_REJECTED.value,
                           ClientCandidateStatus.OFFER_DECLINED.value,
                           ClientCandidateStatus.DROPPED.value,
                           ClientCandidateStatus.WITHDRAWN.value}

# The AVAILABLE CANDIDATE POOL.
#
# A client rejecting a CV ends that candidate's run at THAT client. It says nothing about
# whether they suit somebody else, and deleting or permanently closing them would throw
# away sourcing Sparsh has already paid for -- along with the candidate's own time.
#
# So these states are terminal for the engagement and OPEN for the pool: the record stays
# exactly where it is, in the client's own tenant, visible to them as the rejection they
# made. Sparsh separately sees the person in a pool spanning every engagement, and can
# source them into a different requisition.
#
# THAT RE-SOURCE CREATES A NEW RECORD IN THE NEW TENANT. It does not move, re-point or
# share the original. Client B never sees Client A's row, never learns that Client A
# rejected them, and the two engagements keep separate histories of the same person --
# which is the only reading of "reusable" that does not breach tenant isolation.
CLIENT_CANDIDATE_POOL = {
    ClientCandidateStatus.CLIENT_REJECTED.value,     # the client passed on them
    ClientCandidateStatus.TELEPHONIC_FAILED.value,   # parked, and revivable in place
    ClientCandidateStatus.OFFER_DECLINED.value,      # they said no to this one
    ClientCandidateStatus.DROPPED.value,             # never started here
    ClientCandidateStatus.WITHDRAWN.value,           # stepped away
}


# =============================================================
# Client Hiring, step 5 -- the assessment
# =============================================================
# PRO-fit SOP section 12 ("Talent Fit Assessment test administered and evaluated against
# the Position Scorecard") and the responsibility table for the assessment stage.
#
# The order is fixed and the reason is the same one that puts scorecard approval before
# sourcing: the assessment is marked against the benchmark, so it happens after the client
# has agreed both the benchmark and this particular candidate.
class ClientAssessmentStatus(str, Enum):
    SENT      = "Sent"                  # issued to the candidate
    SUBMITTED = "Submitted"             # the candidate has completed it
    SCORED    = "Scored"                # the evaluator has marked it
    SHARED    = "Shared with Client"    # the result is with the client
    REVIEWED  = "Reviewed by Client"    # the client has read it; interviews may begin


# action -> (from, to, capability, remarks_required)
CLIENT_ASSESSMENT_TRANSITIONS = {
    # The candidate sits it. Recorded by whoever manages the assessment, because the
    # candidate is not a user of this system.
    "record-submission": (ClientAssessmentStatus.SENT, ClientAssessmentStatus.SUBMITTED,
                          "CLIENT_ASSESSMENT_MANAGE", False),
    # The designated evaluator marks it.
    "score":             (ClientAssessmentStatus.SUBMITTED, ClientAssessmentStatus.SCORED,
                          "CLIENT_ASSESSMENT_SCORE", False),
    # Delivery to the client, the Team Lead's accountability as everywhere else.
    "share":             (ClientAssessmentStatus.SCORED, ClientAssessmentStatus.SHARED,
                          "CLIENT_ASSESSMENT_SHARE", False),
    # The client reads the result. This is an acknowledgement, not a verdict: the flow goes
    # straight on to the interview, and the client's SELECTION comes later, after they have
    # seen the recording.
    "client-review":     (ClientAssessmentStatus.SHARED, ClientAssessmentStatus.REVIEWED,
                          "CLIENT_ASSESSMENT_REVIEW", False),
}

CLIENT_ASSESSMENT_VISIBLE_TO_CLIENT = {
    ClientAssessmentStatus.SHARED.value,
    ClientAssessmentStatus.REVIEWED.value,
}

# =============================================================
# Client Hiring, step 6 -- interview, recording, client selection
# =============================================================
# PRO-fit SOP section 12: "Personal interview conducted on a recorded platform
# (Zoom/virtual) by the internal recruitment panel", and section 14, which lists the
# "recorded interview link" among what the client receives.
#
# SPARSH CONDUCTS, THE CLIENT WATCHES. The SOP also describes a separate client-run
# interview; the agreed flow replaced it with the client viewing Sparsh's recording, so
# there is no client-side panel here. The recording is a LINK rather than an upload,
# which is what section 14 asks for and what a recorded meeting platform produces.
class ClientInterviewStatus(str, Enum):
    SCHEDULED       = "Scheduled"
    CONDUCTED       = "Conducted"            # held, scored, recording link captured
    SHARED          = "Shared with Client"   # the client may watch it
    CLIENT_SELECTED = "Selected by Client"   # the selection; opens the offer stage
    CLIENT_REJECTED = "Rejected by Client"


# The competencies the panel scores. Kept short and named here so the form, the service
# and any later report ask for the same things.
CLIENT_INTERVIEW_CRITERIA = [
    ("role_fit",        "Fit against the Position Scorecard"),
    ("communication",   "Communication"),
    ("technical_depth", "Technical depth"),
    ("culture_fit",     "Culture fit"),
]

# action -> (from, to, capability, remarks_required)
CLIENT_INTERVIEW_TRANSITIONS = {
    "record-outcome": (ClientInterviewStatus.SCHEDULED, ClientInterviewStatus.CONDUCTED,
                       "CLIENT_INTERVIEW_MANAGE", False),
    "share":          (ClientInterviewStatus.CONDUCTED, ClientInterviewStatus.SHARED,
                       "CLIENT_INTERVIEW_SHARE", False),
    # THE SELECTION. The client watches the recording and chooses.
    "client-select":  (ClientInterviewStatus.SHARED,
                       ClientInterviewStatus.CLIENT_SELECTED,
                       "CLIENT_INTERVIEW_DECIDE", False),
    "client-reject":  (ClientInterviewStatus.SHARED,
                       ClientInterviewStatus.CLIENT_REJECTED,
                       "CLIENT_INTERVIEW_DECIDE", True),
}

CLIENT_INTERVIEW_VISIBLE_TO_CLIENT = {
    ClientInterviewStatus.SHARED.value,
    ClientInterviewStatus.CLIENT_SELECTED.value,
    ClientInterviewStatus.CLIENT_REJECTED.value,
}

# =============================================================
# Client Hiring, step 7 -- the offer
# =============================================================
# PRO-fit SOP sections 16 and 17, and the section 8 approval matrix.
#
# Section 16 is a CHECKPOINT with three conditions, all of which are enforced before the
# offer leaves Sparsh: the client's final selection in writing, compensation inside the
# range the client approved on the Manpower Requisition, and (section 15, for managerial
# and above) a reference check. Section 17 then has the CLIENT releasing the letter
# directly to the candidate, and states that no verbal offer is valid.
class ClientOfferStatus(str, Enum):
    DRAFT                   = "Draft"                   # the recruiter prepares terms
    # SALARY DEVIATION. When the candidate's CTC lands outside the range the client
    # approved on the Manpower Requisition, the offer cannot simply be submitted -- but it
    # is not dead either. It goes STRAIGHT to Client HR, who own the money, and the
    # approved requisition range is left exactly as it is. Nothing about the range, the
    # requisition or any other stage changes; this is an extra door out of Draft, not a
    # different route through the existing ones.
    PENDING_DEVIATION       = "Pending Salary Deviation"  # with Client HR to decide
    DEVIATION_REJECTED      = "Deviation Rejected"        # Client HR said no; terminal
    PENDING_VERIFICATION    = "Pending Verification"    # Team Lead checks the paperwork
    PENDING_CLIENT_APPROVAL = "Pending Client Approval"  # with the client to approve
    RELEASED                = "Released"                # the client issued it
    ACCEPTED                = "Accepted"                # written acceptance recorded
    DECLINED                = "Declined"


# action -> (from, to, capability, remarks_required)
CLIENT_OFFER_TRANSITIONS = {
    "submit-for-verification": (ClientOfferStatus.DRAFT,
                                ClientOfferStatus.PENDING_VERIFICATION,
                                "CLIENT_OFFER_WRITE", False),
    # ── The salary deviation request ──
    # The OTHER way out of Draft, and the only one open to an offer above (or below) the
    # approved range. Remarks are mandatory: Client HR is being asked to spend more than
    # they budgeted, and "why" is the whole of what they are deciding on.
    "submit-deviation":  (ClientOfferStatus.DRAFT, ClientOfferStatus.PENDING_DEVIATION,
                          "CLIENT_OFFER_WRITE", True),
    # Client HR approves the figure -> the offer rejoins the ordinary chain at
    # verification, and runs from there exactly as any other offer does.
    "deviation-approve": (ClientOfferStatus.PENDING_DEVIATION,
                          ClientOfferStatus.PENDING_VERIFICATION,
                          "CLIENT_OFFER_DEVIATE", False),
    # Client HR refuses it -> the offer is terminal and the CANDIDATE goes down the
    # existing rejection path (Client Rejected, which is already an Available Candidates
    # pool state). Nothing new is invented for the reject case.
    "deviation-reject":  (ClientOfferStatus.PENDING_DEVIATION,
                          ClientOfferStatus.DEVIATION_REJECTED,
                          "CLIENT_OFFER_DEVIATE", True),
    "verify":        (ClientOfferStatus.PENDING_VERIFICATION,
                      ClientOfferStatus.PENDING_CLIENT_APPROVAL,
                      "CLIENT_OFFER_VERIFY", False),
    "return":        (ClientOfferStatus.PENDING_VERIFICATION, ClientOfferStatus.DRAFT,
                      "CLIENT_OFFER_VERIFY", True),
    # Section 17 -- the client releases it to the candidate.
    "client-release": (ClientOfferStatus.PENDING_CLIENT_APPROVAL,
                       ClientOfferStatus.RELEASED,
                       "CLIENT_OFFER_RELEASE", False),
    "client-return":  (ClientOfferStatus.PENDING_CLIENT_APPROVAL, ClientOfferStatus.DRAFT,
                       "CLIENT_OFFER_RELEASE", True),
    # Section 17 -- "recruiter confirms written acceptance and joining date".
    "record-acceptance": (ClientOfferStatus.RELEASED, ClientOfferStatus.ACCEPTED,
                          "CLIENT_OFFER_WRITE", False),
    "record-decline":    (ClientOfferStatus.RELEASED, ClientOfferStatus.DECLINED,
                          "CLIENT_OFFER_WRITE", True),
}

CLIENT_OFFER_EDITABLE = {ClientOfferStatus.DRAFT.value}

CLIENT_OFFER_VISIBLE_TO_CLIENT = {
    # A deviation request is addressed TO the client, so it has to be visible from the
    # moment it is raised -- and afterwards, so their own refusal stays on their record.
    ClientOfferStatus.PENDING_DEVIATION.value,
    ClientOfferStatus.DEVIATION_REJECTED.value,
    ClientOfferStatus.PENDING_CLIENT_APPROVAL.value,
    ClientOfferStatus.RELEASED.value,
    ClientOfferStatus.ACCEPTED.value,
    ClientOfferStatus.DECLINED.value,
}

# =============================================================
# Client Hiring, steps 8-9 -- pre-boarding, joining, handover, closure
# =============================================================
# PRO-fit SOP sections 18, 19 and 20.
#
# Section 19 puts the recruiter in periodic contact with the candidate between acceptance
# and Day 1, to manage counter-offer and drop-out risk. Section 18 has the CLIENT
# confirming, in writing, that the person turned up. Section 20 then has Sparsh handing
# over the candidate file and the post-joining checks, and says the requisition is closed
# "only after this handover" -- so closure is a consequence of the handover here, not a
# separate button somebody can press early.
class ClientJoiningStatus(str, Enum):
    PRE_BOARDING = "Pre-boarding"   # accepted; between offer and Day 1
    JOINED       = "Joined"         # the client confirmed it in writing
    COMPLETED    = "Completed"      # handover done, requisition closed
    DROPPED      = "Dropped Out"    # never joined


# What section 20 hands to the client's own HR team. Declared as data so the service and
# the screen ask for the same things, and so "handover" cannot mean an empty note.
CLIENT_HANDOVER_ITEMS = [
    ("candidate_file",      "Candidate file"),
    ("scorecards",          "Scorecards"),
    ("interview_records",   "Interview records"),
    ("verification_status", "Verification status"),
]

# action -> (from, to, capability, remarks_required)
CLIENT_JOINING_TRANSITIONS = {
    # Section 18 -- the client confirms joining in writing.
    "confirm-joining": (ClientJoiningStatus.PRE_BOARDING, ClientJoiningStatus.JOINED,
                        "CLIENT_JOINING_CONFIRM", False),
    # The counter-offer risk section 19 exists to manage, when it lands.
    "record-drop":     (ClientJoiningStatus.PRE_BOARDING, ClientJoiningStatus.DROPPED,
                        "CLIENT_JOINING_MANAGE", True),
    # Section 20 -- the handover note, which is also what closes the requisition.
    "share-handover":  (ClientJoiningStatus.JOINED, ClientJoiningStatus.COMPLETED,
                        "CLIENT_JOINING_HANDOVER", False),
}

# The joiner is the client's own new employee from the moment they accept, so every stage
# of this record is theirs to follow.
CLIENT_JOINING_VISIBLE_TO_CLIENT = {s.value for s in ClientJoiningStatus}

AUDIT_CLIENT_JOINING_OPENED   = "client pre-boarding opened"
AUDIT_CLIENT_JOINING_UPDATED  = "client joining record updated"
AUDIT_CLIENT_JOINING_ACTIONED = "client joining stage changed"
AUDIT_CLIENT_TOUCHPOINT       = "client pre-boarding touchpoint recorded"
ENTITY_CLIENT_JOINING = "client_joining"


AUDIT_CLIENT_REFERENCE_RECORDED = "client reference check recorded"
AUDIT_CLIENT_OFFER_CREATED      = "client offer prepared"
AUDIT_CLIENT_OFFER_UPDATED      = "client offer updated"
AUDIT_CLIENT_OFFER_ACTIONED     = "client offer stage changed"
ENTITY_CLIENT_REFERENCE = "client_reference_check"
ENTITY_CLIENT_OFFER     = "client_offer"


AUDIT_CLIENT_INTERVIEW_SCHEDULED = "client interview scheduled"
AUDIT_CLIENT_INTERVIEW_UPDATED   = "client interview updated"
AUDIT_CLIENT_INTERVIEW_ACTIONED  = "client interview stage changed"
ENTITY_CLIENT_INTERVIEW = "client_interview"


AUDIT_CLIENT_ASSESSMENT_SENT     = "client assessment issued"
AUDIT_CLIENT_ASSESSMENT_UPDATED  = "client assessment updated"
AUDIT_CLIENT_ASSESSMENT_ACTIONED = "client assessment stage changed"
ENTITY_CLIENT_ASSESSMENT = "client_assessment"


AUDIT_CLIENT_CANDIDATE_ADDED    = "client candidate sourced"
AUDIT_CLIENT_CANDIDATE_UPDATED  = "client candidate updated"
AUDIT_CLIENT_CANDIDATE_ACTIONED = "client candidate stage changed"
ENTITY_CLIENT_CANDIDATE = "client_candidate"


AUDIT_CLIENT_SCORECARD_CREATED  = "client position scorecard drafted"
AUDIT_CLIENT_SCORECARD_UPDATED  = "client position scorecard updated"
AUDIT_CLIENT_SCORECARD_ACTIONED = "client position scorecard status changed"
ENTITY_CLIENT_SCORECARD = "client_scorecard"


AUDIT_CLIENT_REQ_CREATED  = "client requisition raised"
AUDIT_CLIENT_REQ_UPDATED  = "client requisition updated"
AUDIT_CLIENT_REQ_ACTIONED = "client requisition status changed"
ENTITY_CLIENT_REQUISITION = "client_requisition"


# =============================================================
# Client Hiring -- the capability ceiling for a client company
# =============================================================
# Sparsh Magic runs TWO hiring tracks and they do not meet. Internal Hiring is Sparsh
# hiring its own staff; Client Hiring is Sparsh recruiting on behalf of a client company.
#
# A user of a client company reaching HRMS must be able to do the client half of the
# PRO-fit flow and NOTHING else -- not payroll, not employees, not exits, not Internal
# Hiring, not another client's data. Tenant scoping already stops them reading another
# company (see hrms_access.scope_company_id, which ignores a requested company id for a
# client-side caller). What tenant scoping does NOT stop is a client company's own admin
# resolving to an HRMS ladder role and running the whole module INSIDE their own tenant.
#
# This set IS what a client-side caller holds -- it replaces whatever their role inside
# their own company would otherwise grant, at the one place every gate resolves through
# (hrms_access.capabilities_for). So a capability not listed here cannot be reached by a
# client-side caller from ANY route, service or future code path, and one that is listed
# does not depend on an internal ladder role that means nothing to a client.
#
# It started EMPTY and grows one step at a time. Each increment adds ONLY the capabilities
# that increment's feature needs, so anything not listed here cannot be reached by a
# client-side caller from any route, service or future code path. Fail closed, then open
# one door at a time.
#
# Step 1 (Need Mapping / Manpower Requisition): the client may raise, read and amend their
# OWN requisition. They may NOT review it -- the feasibility and budget decision is Sparsh's
# (SOP section 7 step 3, and the RACI's "Internal feasibility review: Team Lead = A").
# Referenced lazily by name because Cap is defined above but the members are added below.
CLIENT_TRACK_CAPS: set = set()


def _seed_client_track_caps() -> None:
    """Populate the ceiling once Cap exists. Called at import, at the bottom of this module."""
    CLIENT_TRACK_CAPS.update({
        Cap.MODULE_ACCESS,
        # Step 1 -- raise, read and amend their own requisition. Never review it.
        Cap.CLIENT_REQUISITION_READ,
        Cap.CLIENT_REQUISITION_WRITE,
        # Step 2 -- read the scorecard Sparsh drafted for them, and approve it. Never
        # write it: the benchmark is Sparsh's professional work, and a client who could
        # edit it could approve their own words.
        Cap.CLIENT_SCORECARD_READ,
        Cap.CLIENT_SCORECARD_APPROVE,
        # Steps 3-4 -- see the candidates shared with them, and give the verdict that lets
        # one into assessment. Never source, never screen, never share.
        Cap.CLIENT_CANDIDATE_READ,
        Cap.CLIENT_CANDIDATE_DECIDE,
        # Step 5 -- see the assessment result once it is shared, and record that they have
        # reviewed it. Never administer the test and never mark it.
        Cap.CLIENT_ASSESSMENT_READ,
        Cap.CLIENT_ASSESSMENT_REVIEW,
        # Step 6 -- watch the recording once shared, and select or reject. Never schedule,
        # never conduct, never score.
        Cap.CLIENT_INTERVIEW_READ,
        Cap.CLIENT_INTERVIEW_DECIDE,
        # Step 7 -- see the offer and release it. NOT the reference check: those are
        # Sparsh's working enquiries about somebody not yet hired.
        Cap.CLIENT_OFFER_READ,
        Cap.CLIENT_OFFER_RELEASE,
        # A salary deviation request comes straight to Client HR, because it is their
        # budget being exceeded. They approve or refuse the figure; the approved
        # requisition range is never touched either way.
        Cap.CLIENT_OFFER_DEVIATE,
        # Steps 8-9 -- follow the joiner, and confirm in writing that they turned up.
        # Not the pre-boarding contact log: those are Sparsh's calls to the candidate.
        Cap.CLIENT_JOINING_READ,
        Cap.CLIENT_JOINING_CONFIRM,
        # A client sees the delivery board for their own engagement. Scoping decides
        # whose numbers those are; this decides whether they get a board at all.
        Cap.CLIENT_ANALYTICS_READ,
    })

# ─────────────────────────────────────────────────────────────
# The five decisions that belong to the CLIENT and to nobody at Sparsh
# ─────────────────────────────────────────────────────────────
# PRO-fit gives the client company five decision points, and the value of the whole track
# rests on them being genuinely theirs: the scorecard approval, the CV verdict, the
# selection after interview, the offer release and the joining confirmation. Sparsh
# sources, screens, administers, scores, verifies and chases -- but does not decide.
#
# Keeping them out of ROLE_CAPABILITIES was not enough. `capabilities_for` resolves the
# ADMIN role to "every member of Cap", deliberately, so that a capability added in a later
# phase can never lock the module owner out of their own system. That blanket grant swept
# these five up with everything else, and a Sparsh superadmin was offered "Approve" on a
# scorecard sitting with the client -- and could release the client's own offer.
#
# So the two ideas are separated, and this set is what separates them:
#
#   ADMIN           = administrative access. Read everything, support everything, fix
#                     everything, run the workflow. Unchanged.
#   CLIENT_DECISION = the authority to make a decision the client owns. Held by client-side
#                     callers only, by virtue of being that company, not by seniority.
#
# Subtracted in `capabilities_for` from every caller who is NOT client-side, which is the
# one function every route, service and UI hint resolves through. A future role, a widened
# ROLE_CAPABILITIES entry or a new admin branch therefore cannot reacquire them by
# accident: the subtraction is the last thing that happens before the answer is returned.
CLIENT_DECISION_CAPS: set = set()


# Capabilities that are the client's OWN WORK rather than their own decision.
#
# Different from CLIENT_DECISION_CAPS in kind, identical in effect: subtracted from every
# Sparsh role. Kept as a separate set because "decision" is a promise about authority and
# these are not decisions -- writing the Need Mapping and Manpower Requisition forms is the
# client stating what they need. Folding them into the decision list would make that list
# lie about what it contains, and the count of client decisions is asserted in a test on
# purpose.
#
# Why Sparsh cannot do it: on PRO-fit the requirement ORIGINATES with the client (SOP
# section 7 step 1). Sparsh reviews feasibility, which is a different capability
# (CLIENT_REQUISITION_REVIEW) and is Sparsh's. A supplier that could raise the client's
# requirement could also set its salary range -- the very figure the supplier is later
# measured against, and the one the client is asked to approve a deviation from.
CLIENT_OWNED_CAPS: set = set()


def _seed_client_owned_caps() -> None:
    """The client's own forms. Called at the bottom of this module, beside the decisions."""
    CLIENT_OWNED_CAPS.update({
        # Create the Need Mapping Form, amend either form, and submit them (the
        # "submit-need-mapping" and "submit-requisition" transitions both name this cap).
        Cap.CLIENT_REQUISITION_WRITE,
    })


def _seed_client_decision_caps() -> None:
    """Populate the exclusive set once Cap exists. Called at the bottom of this module."""
    CLIENT_DECISION_CAPS.update({
        Cap.CLIENT_SCORECARD_APPROVE,    # 1. the benchmark they will be measured against
        Cap.CLIENT_CANDIDATE_DECIDE,     # 2. the CV verdict, which opens the assessment
        Cap.CLIENT_INTERVIEW_DECIDE,     # 3. the selection after the interview
        Cap.CLIENT_OFFER_RELEASE,        # 4. releasing their own employment contract
        Cap.CLIENT_JOINING_CONFIRM,      # 5. confirming somebody actually started
        # 6. approving pay above the range they approved. Same logic as the five above:
        # it commits the CLIENT's money, so no Sparsh role may do it on their behalf.
        Cap.CLIENT_OFFER_DEVIATE,
    })


# Marker stamped on the request's user by the module gate when the caller belongs to a
# client company rather than to Sparsh Magic's own tenant. Read by `capabilities_for`.
#
# A flag on the in-memory user rather than a role, because the distinction is a property of
# WHICH COMPANY the caller is in, and `hrms_role()` is synchronous and cannot look a company
# up. It is set in exactly one place -- the router-wide dependency -- so it cannot be forged
# by a request body: an incoming payload never becomes the user dict.
CLIENT_TRACK_FLAG = "_hrms_client_track_only"


# Which ERP roles map into the two internal HRMS roles.
INTERNAL_OWNER_ROLES = {"superadmin"}
INTERNAL_STAFF_ROLES = {"admin", "coach", "staff"}
CLIENT_ROLES         = {"clientadmin", "clientuser"}

# Client governance ladder → HRMS role. `clientadmin` is the company's top authority and
# maps to MD independently of governance_role (auth_controller.client_rank does the same).
GOVERNANCE_TO_HRMS = {
    "MD":          HrmsRole.MD,
    "HR":          HrmsRole.HR,
    # Peer of HR on the governance ladder (auth_controller.CLIENT_RANK gives both 3): a
    # finance controller is not senior to HR, they own a different decision.
    "FINANCE":     HrmsRole.FINANCE,
    "HOD":         HrmsRole.MANAGER,
    "IMPLEMENTOR": HrmsRole.EMPLOYEE,
}

# Roles permitted to switch the HRMS module on/off for a company. Matches the TPMS
# toggle rule (utils/tpms_access.TOGGLE_ROLES) — Admin / Super Admin only.
TOGGLE_ROLES = {"superadmin", "admin"}


# ─────────────────────────────────────────────────────────────
# Capabilities — the ONE authorization vocabulary
# ─────────────────────────────────────────────────────────────
# Format: "<domain>.<action>". Every gate in every phase resolves through
# utils/hrms_access.can(user, capability) — never an ad-hoc role check.
#
# Phase discipline: each phase registers the capabilities it actually enforces.
# Phase 11 builds the admin console over whatever is registered by then.
class Cap(str, Enum):
    # ── Phase 1 ──
    MODULE_ACCESS = "module.access"   # may open HRMS at all
    MODULE_ADMIN  = "module.admin"    # may administer HRMS configuration
    AUDIT_READ    = "audit.read"      # may read the audit trail

    # ── Phase 2: employee master ──
    EMPLOYEE_READ         = "employee.read"          # browse the directory (row-scoped by role)
    EMPLOYEE_WRITE        = "employee.write"         # create / edit employee profiles
    EMPLOYEE_SALARY_READ  = "employee.salary.read"   # SEE pay figures
    EMPLOYEE_SALARY_WRITE = "employee.salary.write"  # SET pay figures
    DEPARTMENT_READ       = "department.read"
    DEPARTMENT_WRITE      = "department.write"
    DESIGNATION_READ      = "designation.read"
    DESIGNATION_WRITE     = "designation.write"

    # ── Phase 3: requisitions + job descriptions ──
    REQUISITION_READ       = "requisition.read"
    REQUISITION_CREATE     = "requisition.create"      # raise one — deliberately open to all
    REQUISITION_WRITE      = "requisition.write"       # edit / delete
    REQUISITION_REVIEW_HR  = "requisition.review_hr"   # stage 1: forward to MD, or reject
    REQUISITION_APPROVE_MD = "requisition.approve_md"  # stage 2: final approval
    REQUISITION_CLOSE      = "requisition.close"       # set Hired/Closed/Hold/Cancel
    JD_READ                = "jd.read"
    JD_WRITE               = "jd.write"

    # ── Phase 4: job postings ──
    POSTING_READ  = "posting.read"
    POSTING_WRITE = "posting.write"    # create / publish / pause / close / delete
    # Internal Recruitment SOP — Step 4: "Executive Search for Leadership Roles" requires
    # Management's own approval before such a posting may be published, separate from the
    # HR/recruiter capability that does everything else on a posting.
    POSTING_APPROVE_EXEC_SEARCH = "posting.approve_exec_search"

    # ── Phase 5: candidates + screening ──
    CANDIDATE_READ   = "candidate.read"
    CANDIDATE_WRITE  = "candidate.write"    # add / edit / delete a candidate record
    CANDIDATE_SCREEN = "candidate.screen"   # shortlist / hold / reject / forward

    # ── Phase 6: assessments ──
    ASSESSMENT_READ   = "assessment.read"
    ASSESSMENT_SEND   = "assessment.send"     # operational: issue an assessment
    ASSESSMENT_REVIEW = "assessment.review"   # a DECISION: Pass / Fail

    # ── Phase 7: interviews ──
    INTERVIEW_READ      = "interview.read"       # widens the list beyond your own
    INTERVIEW_SCHEDULE  = "interview.schedule"   # operational: book / reschedule / cancel
    INTERVIEW_EVALUATE  = "interview.evaluate"   # a DECISION: the scorecard
    INTERVIEW_DECIDE_MD = "interview.decide_md"  # the FINAL call, MD only

    # ── Phase 8: offers ──
    OFFER_READ  = "offer.read"
    OFFER_WRITE = "offer.write"   # draft / edit / delete a draft
    OFFER_SEND  = "offer.send"    # the COMMITMENT: issue or revoke a live offer

    # ── Phase 9: onboarding ──
    ONBOARDING_READ        = "onboarding.read"
    ONBOARDING_WRITE       = "onboarding.write"        # start, checklist, BG, KYC, details
    ONBOARDING_GENERATE_ID = "onboarding.generate_id"  # mints the EMPLOYEE RECORD

    # ── Phase 10: analytics & reports (READ-ONLY) ──
    ANALYTICS_READ = "analytics.read"   # dashboard, funnel, breakdowns
    REPORT_READ    = "report.read"      # the detailed tabbed tables
    REPORT_EXPORT  = "report.export"    # taking data OUT of the system

    # ── Phase 11-R: recruitment review enhancements ──
    # Item 1 — the public-link registry.
    LINK_READ   = "link.read"     # see every issued link and its open history
    LINK_MANAGE = "link.manage"   # revoke / reissue — killing a live credential
    # Item 2 — documentation.
    DOCUMENT_READ   = "document.read"
    DOCUMENT_WRITE  = "document.write"   # upload, version, edit metadata, delete
    DOCUMENT_VERIFY = "document.verify"  # a DECISION: Verified / Rejected
    # Item 3 — appointment letters. Mirrors the offer capabilities exactly: read, author,
    # and a separate COMMITMENT capability for issuing one.
    APPOINTMENT_READ  = "appointment.read"
    APPOINTMENT_WRITE = "appointment.write"
    APPOINTMENT_SEND  = "appointment.send"
    # Item 7 — sanctioned strength + the escalation ladder.
    SANCTION_READ  = "sanction.read"
    SANCTION_WRITE = "sanction.write"
    REQUISITION_ESCALATE = "requisition.escalate"   # act on an over-sanction escalation step

    # ══ Internal (in-house) recruitment track ══
    # Sparsh Magic hiring for itself. The defining difference from the client track is that
    # the budget is owned INTERNALLY, so these capabilities are all about who may commit the
    # company's own money and who may confirm its own people.
    #
    # Granted per Annexure B of the Internal Recruitment SOP (RACI). Where the SOP says
    # "A" (accountable) the capability is an approval; where it says "R" (responsible) it is
    # a write; "C"/"I" get read only.
    #
    # The mandatory budget gate. No sourcing may begin before it clears (SOP §11:
    # "No internal role may be sourced without prior written headcount and budget
    # approval"), and that is enforced in the posting and candidate services, not the UI.
    REQUISITION_APPROVE_BUDGET = "requisition.approve_budget"
    # The position scorecard: HR drafts, the HOD approves, Management also approves for
    # managerial+ roles.
    SCORECARD_READ    = "scorecard.read"
    SCORECARD_WRITE   = "scorecard.write"
    SCORECARD_APPROVE = "scorecard.approve"
    # Reference checks. Mandatory before an internal offer, because Sparsh Magic bears the
    # direct employment risk rather than a client.
    REFERENCE_READ  = "reference.read"
    REFERENCE_WRITE = "reference.write"
    # ── Phase INT-4 ── the telephonic screen (SOP step 5). Annexure B makes HR Responsible
    # and everybody else Informed, so WRITE is HR's alone; the HOD and Management read it
    # because they interview off the back of it.
    TELEPHONIC_READ  = "telephonic.read"
    TELEPHONIC_WRITE = "telephonic.write"
    # ── Phase INT-10 ── the salary negotiation record (SOP step 9). Annexure B: HR is
    # Responsible, the HOD Consulted, Management Accountable. WRITE is HR's (and the MD's,
    # as the top of every ladder); READ reaches the HOD who is consulted and FINANCE who is
    # accountable for the figure -- the one candidate-level record Finance does see,
    # because it is about money and nothing else.
    NEGOTIATION_READ  = "negotiation.read"
    NEGOTIATION_WRITE = "negotiation.write"
    # ── Phase INT-5 ── the per-company rule set. READ is wide, because a target you cannot
    # see is one you cannot plan against; WRITE is the MD's and Finance's, because these are
    # the numbers the SOP's own review cycle governs and HR is "R" on running the process,
    # not on rewriting the policy behind it (Annexure B, "Policy review": Management is "A").
    SETTINGS_READ  = "settings.read"
    SETTINGS_WRITE = "settings.write"
    # Offer approval. Annexure B marks this "A" for Management/Finance and Table 2 calls it
    # mandatory, so it is a real act and not merely a band check on the CTC.
    OFFER_APPROVE = "offer.approve"
    # Probation. Recorded against the EMPLOYEE; confirming it also stamps the candidate's
    # `Probation Confirmed` stage — see POST_HIRE_STATUSES for why that edge is one-way.
    PROBATION_READ    = "probation.read"
    PROBATION_REVIEW  = "probation.review"
    PROBATION_CONFIRM = "probation.confirm"
    # Day-1 induction checklist.
    INDUCTION_READ  = "induction.read"
    INDUCTION_WRITE = "induction.write"
    # The exception log. An APPROVED exception is the only thing that unblocks the
    # reference-check and salary-band gates — there is deliberately no override flag.
    EXCEPTION_READ    = "exception.read"
    EXCEPTION_WRITE   = "exception.write"
    EXCEPTION_APPROVE = "exception.approve"
    # Closing the personnel file, which is what closes an internal requisition (there is no
    # client handover in this track).
    PERSONNEL_FILE_CLOSE = "personnel_file.close"

    # ══ Phase INT-2 — the remaining SOP controls ══
    # The internal shortlisting committee (SOP §5). Deliberately NOT granted to FINANCE:
    # Finance approves what a role costs, never who fills it, and this record is entirely
    # about who fills it. Same line REFERENCE_* and CANDIDATE_SCREEN already draw.
    SHORTLIST_READ  = "shortlist.read"
    SHORTLIST_WRITE = "shortlist.write"
    # Pre-boarding engagement (SOP §6). Tracking, not a gate -- nothing is blocked by it,
    # which is why there is no third "approve" capability here.
    PREBOARDING_READ  = "preboarding.read"
    PREBOARDING_WRITE = "preboarding.write"
    # The standing salary-band master (Annexure C). WRITE is Finance and the MD alone: a
    # band agreed annually with Finance is Finance's artifact, and HR reading it is what
    # lets the budget gate pre-fill from it.
    SALARY_BAND_READ  = "salary_band.read"
    SALARY_BAND_WRITE = "salary_band.write"
    # Candidate communications (Annexure C). Sending and reading the log are operational;
    # editing a TEMPLATE is not -- the templates carry the equal-opportunity and data-use
    # wording, so changing one is closer to a policy act than an HR one.
    COMM_READ           = "comm.read"
    COMM_WRITE          = "comm.write"
    COMM_TEMPLATE_WRITE = "comm.template.write"
    # New-hire experience surveys (SOP §10). READ is the AGGREGATE only -- the service
    # refuses a breakdown below SURVEY_MIN_RESPONSES, so this capability can never become
    # a way to read one person's answers.
    SURVEY_READ  = "survey.read"
    # The policy register (SOP §14). APPROVE is the MD's alone: approving a revision is
    # what makes a version the one in force.
    POLICY_READ    = "policy.read"
    POLICY_WRITE   = "policy.write"
    POLICY_APPROVE = "policy.approve"
    # ── Phase POLICY-LIB-1 (§22.6) ── the employee's own act of acknowledging a published
    # policy (step 227) — a separate self-service capability, the same "distinct capability
    # for the subject's own act" pattern PIP_ACKNOWLEDGE/LEAVE_APPLY/PULSE_SUBMIT establish.
    # The HR "review access"/dashboard side (step 230) reuses POLICY_WRITE rather than adding
    # a second one: whoever may administer the register may already see who has acknowledged.
    POLICY_ACKNOWLEDGE = "policy.acknowledge"
    # Executing a retention purge (SOP §13). MD only, and the same standard as probation
    # confirmation because both destroy or end something.
    RETENTION_PURGE = "retention.purge"

    # Background verification. WRITE records a check; APPROVE is the sign-off that unlocks
    # the offer, and is deliberately a DIFFERENT capability -- the person who runs a check
    # should not be the only signature that it passed.
    BACKGROUND_READ    = "background.read"
    BACKGROUND_WRITE   = "background.write"
    BACKGROUND_APPROVE = "background.approve"
    # ── spec §10 ── the interview report and recording.
    #
    # A separate capability from `interview.schedule` and `interview.evaluate` because it is
    # a different act: booking a conversation and judging one are operational, while
    # attaching the evidence others will read and watch is a disclosure decision. A
    # company that wants a senior recruiter to control what leaves the building can grant
    # the first two widely and this one narrowly.
    INTERVIEW_MEDIA = "interview.media"
    # ── Phase EXIT-1 — Exit Management (§7.18, §22.2, §7.21) ──
    # Modelled on the same separation of duties the rest of this module already draws: HR
    # runs the process end to end ("R"), the reporting manager is the one sign-off the BA doc
    # names explicitly (handover acceptance), and Finance/the MD hold the two irreversible
    # money gates — a notice waiver and the F&F payout — for the same reason OFFER_APPROVE and
    # REQUISITION_APPROVE_MD are held apart from whoever prepares the numbers behind them.
    SEPARATION_READ     = "separation.read"
    SEPARATION_INITIATE = "separation.initiate"    # raise a case on someone else's behalf
    SEPARATION_MANAGE   = "separation.manage"      # notice decision, revised LWD, stage moves
    SEPARATION_APPROVE  = "separation.approve"     # waiver / early release (BR-016)
    HANDOVER_READ       = "handover.read"
    HANDOVER_WRITE      = "handover.write"
    HANDOVER_APPROVE    = "handover.approve"       # the reporting manager's acceptance
    CLEARANCE_READ      = "clearance.read"
    CLEARANCE_MANAGE    = "clearance.manage"       # open the clearance/asset/access tasks
    CLEARANCE_ACT       = "clearance.act"          # clear, reject or confirm ONE task
    EXIT_INTERVIEW_READ  = "exit_interview.read"
    EXIT_INTERVIEW_WRITE = "exit_interview.write"
    # A LEAVING EMPLOYEE completing their own exit interview. Deliberately its own verb
    # rather than the `.write` above, matching every other self-service grant in this
    # enum (leave.apply, pulse.submit, policy.acknowledge, attendance.regularize_request):
    # ".write" reads as "may write this record", and an employee may not -- they may
    # submit THEIRS, which the service enforces by ownership.
    EXIT_INTERVIEW_SUBMIT = "exit_interview.submit"
    FNF_READ    = "fnf.read"
    FNF_PREPARE = "fnf.prepare"                    # maker
    FNF_APPROVE = "fnf.approve"                    # checker (BR-021)
    # ── Phase ATT-1 — Attendance & Leave (§7.8-7.12, §22.8-22.9) ──
    # MARK is HR (or an eventual import job) writing the day's status directly — the only
    # write path until a real punch source exists (§7.8: "current policy references
    # Biometric... future source may be API/mobile"). REGULARIZE_REQUEST is the self-service
    # act every role gets, the same reasoning SEPARATION_INITIATE already established: taking
    # attendance is universal, not an HR-only administrative act. REGULARIZE_APPROVE is
    # deliberately ONE capability covering both the manager's first look and HR's second
    # (§7.9 step 68: "HR second-level approval is applied for configured exception types") —
    # the SERVICE enforces the two-stage order, this just says who may ever act on the queue,
    # the same shape CLEARANCE_ACT already uses for one capability across many task owners.
    ATTENDANCE_READ              = "attendance.read"
    ATTENDANCE_MARK              = "attendance.mark"
    ATTENDANCE_REGULARIZE_REQUEST = "attendance.regularize_request"
    ATTENDANCE_REGULARIZE_APPROVE = "attendance.regularize_approve"
    ATTENDANCE_LOCK              = "attendance.lock"          # monthly closure (§7.12)
    OD_REQUEST = "od.request"
    OD_APPROVE = "od.approve"
    LEAVE_READ         = "leave.read"
    LEAVE_APPLY        = "leave.apply"             # self-service, same reasoning as above
    LEAVE_APPROVE       = "leave.approve"
    LEAVE_POLICY_MANAGE = "leave.policy_manage"    # leave-type entitlements, C-Off expiry
    COFF_EARN_REQUEST = "coff.earn_request"        # claim approved work on a holiday/weekly-off
    COFF_APPROVE      = "coff.approve"             # covers both the earn credit and the use debit
    # ── Phase MOVE-1 — Employee Movements & Discipline (§7.16, §7.17, §7.19, §7.20) ──
    MOVEMENT_READ     = "movement.read"
    MOVEMENT_INITIATE = "movement.initiate"        # raise a promotion/transfer/grade/comp change
    MOVEMENT_APPROVE  = "movement.approve"
    # Discipline is split the same way Exit's F&F is: MANAGE is the committee's
    # investigation/recommendation work ("R"), DECIDE is management's separate
    # approve-and-implement act ("A") — BR-021's maker/checker shape, applied here because
    # §7.17 draws the same line explicitly ("Committee records... Recommendation...
    # Authorised management approves/implements").
    DISCIPLINE_READ    = "discipline.read"
    DISCIPLINE_MANAGE  = "discipline.manage"
    DISCIPLINE_DECIDE  = "discipline.decide"
    # A SEPARATE, narrower pair for POSH/sexual-harassment matters — the BA doc is explicit
    # that these "should not be treated as ordinary manager-visible discipline cases"
    # (§7.17 BR). Holding DISCIPLINE_MANAGE does NOT imply DISCIPLINE_POSH_MANAGE; the two
    # are checked independently at the service layer, the same isolation EXIT-1's
    # SEPARATION_APPROVE draws from SEPARATION_MANAGE.
    DISCIPLINE_POSH_READ   = "discipline.posh_read"
    DISCIPLINE_POSH_MANAGE = "discipline.posh_manage"
    ABSCONDING_READ   = "absconding.read"
    ABSCONDING_MANAGE = "absconding.manage"        # flag, log contact attempts, send warnings
    ABSCONDING_DECIDE = "absconding.decide"        # the authorised final action (§7.19 step 153)
    # §7.20: the proactive "who retires soon" alert is its own read, distinct from
    # SEPARATION_READ — it surfaces ACTIVE employees nobody has separated yet. Once HR acts,
    # retirement/demise/missing are exit_type values Exit Management (Phase EXIT-1) already
    # handles end to end; no further capability is needed there.
    RETIREMENT_ALERT_READ = "retirement_alert.read"
    # ── Phase PAY-1 — Payroll, Salary Advance & Variable Pay (§7.13-7.15, §22.7) ──
    # PROCESS is the maker's whole run (create, import, calculate, resolve exceptions,
    # rerun); APPROVE is the checker's separate sign-off that also locks the run — the same
    # maker/checker split BR-021 draws for F&F, named explicitly here too ("Payroll Maker...
    # Payroll/Finance Approver").
    PAYROLL_READ    = "payroll.read"
    PAYROLL_PROCESS = "payroll.process"
    PAYROLL_APPROVE = "payroll.approve"
    SALARY_STRUCTURE_READ   = "salary_structure.read"
    SALARY_STRUCTURE_MANAGE = "salary_structure.manage"
    # REQUEST is the self-service act every role gets (the same reasoning LEAVE_APPLY /
    # SEPARATION_INITIATE already established). APPROVE is the normal Reporting-Manager/HR
    # tier; APPROVE_EMERGENCY is the separate, narrower "Director HR / Finance" tier §7.14
    # names for the emergency route — deliberately its own capability, not a flag on the
    # normal one, the same isolation SEPARATION_APPROVE draws from SEPARATION_MANAGE.
    ADVANCE_READ    = "advance.read"
    ADVANCE_REQUEST = "advance.request"
    ADVANCE_APPROVE = "advance.approve"
    ADVANCE_APPROVE_EMERGENCY = "advance.approve_emergency"
    # PROCESS (HR/Performance Owner, "R") creates the quarter, imports scores and computes
    # the split; APPROVE (Finance/Management, "A") confirms the batch — again BR-021's
    # shape. HOLD_MANAGE is the SEPARATE act of releasing or forfeiting the held 25% at
    # FY-end/milestone (§7.15 step 119) — a different decision, at a different time, from
    # the quarterly batch approval.
    VARIABLE_PAY_READ        = "variable_pay.read"
    VARIABLE_PAY_PROCESS     = "variable_pay.process"
    VARIABLE_PAY_APPROVE     = "variable_pay.approve"
    VARIABLE_PAY_HOLD_MANAGE = "variable_pay.hold_manage"
    # ── Phase PIP-1 — Performance Improvement Plan (§22.5) ──
    # MANAGE covers everything a manager/HR does day to day (initiate, capture objectives/
    # support, record review notes, step 218) — DECIDE is the separate, narrower act of
    # recording the plan's final outcome (step 220), because "Separation Recommended" is one
    # of the four possible outcomes and a manager should not be the one sign-off away from
    # triggering that. ACKNOWLEDGE is the employee's own self-service act (step 217), the
    # same reasoning LEAVE_APPLY/SEPARATION_INITIATE already established.
    PIP_READ        = "pip.read"
    PIP_MANAGE      = "pip.manage"
    PIP_DECIDE      = "pip.decide"
    PIP_ACKNOWLEDGE = "pip.acknowledge"
    # ── Phase LETTER-1 — HR Letter / Document Generator (SM-HR-041) ──
    # READ is row-scoped in the service exactly like EMPLOYEE_READ/PIP_READ: an employee
    # holding it sees only letters addressed to them, HR/MD/INTERNAL see the company's own.
    # MANAGE covers the template register plus preview/generate/issue/reissue — the BA doc
    # names one user for this whole screen ("Users: HR") and draws no separate sign-off tier
    # the way Discipline/Payroll/PIP do, so there is no third capability here.
    LETTER_READ   = "letter.read"
    LETTER_MANAGE = "letter.manage"
    # ── Phase PULSE-1 — 30/90-Day Pulse Survey (§22.4) ──
    # A DIFFERENT capability from SURVEY_READ/WRITE on purpose, not a reuse: the existing
    # survey module (induction/probation feedback) is deliberately ANONYMOUS — responses are
    # never linkable to a person, and SURVEY_READ has only ever meant "may see the aggregate".
    # A pulse survey is the opposite by design (§22.4 step 212 needs to know WHO scored low
    # enough to need a follow-up, step 214 links results into their OWN Employee 360°), so
    # granting that under the existing capability would silently widen what every current
    # SURVEY_READ holder can see. PULSE_SUBMIT is the employee's own self-service completion
    # action, the same "separate capability for the subject's own act" pattern
    # PIP_ACKNOWLEDGE/LEAVE_APPLY already establish.
    PULSE_READ   = "pulse.read"
    PULSE_MANAGE = "pulse.manage"
    PULSE_SUBMIT = "pulse.submit"
    # ── Phase GMP-1 — Group Mediclaim Policy (§22, employee profile "GMP section") ──
    # One current enrolment per employee, HR-administered — the same "master, edited in
    # place, no approval tier the BA doc does not name" shape Employee Profile's own
    # personal/statutory fields already take. READ is row-scoped exactly like PIP_READ/
    # LETTER_READ: an employee sees their own enrolment, HR/INTERNAL see the company's.
    GMP_READ  = "gmp.read"
    GMP_WRITE = "gmp.write"

    # ── Client Hiring, step 1 (PRO-fit SOP section 7) ──
    #
    # Three, and no more. The client owns their own Need Mapping and Manpower Requisition;
    # Sparsh owns the feasibility decision. Splitting WRITE from REVIEW is the whole
    # control: a client who could review their own requisition could activate it without
    # Sparsh ever assessing role clarity, pay competitiveness or timeline, which is exactly
    # what section 7 step 3 exists to prevent.
    CLIENT_REQUISITION_READ   = "client_requisition.read"
    CLIENT_REQUISITION_WRITE  = "client_requisition.write"
    CLIENT_REQUISITION_REVIEW = "client_requisition.review"

    # ── Client Hiring, step 2 -- the Position Scorecard (PRO-fit SOP section 6, 13) ──
    #
    # Four, because four different people act on one document and the SOP's approval matrix
    # names them separately: "PSC -- Recruiter: Draft, Team Lead: Review, Client: Approve
    # (mandatory)". WRITE is Sparsh's, APPROVE is the client's, and REVIEW is the internal
    # check that sits between them. Collapsing any two would let one side both write the
    # benchmark and declare it agreed, which is the thing section 6 forbids: "no candidate
    # shall be presented to a client without an APPROVED Position Scorecard".
    CLIENT_SCORECARD_READ    = "client_scorecard.read"
    CLIENT_SCORECARD_WRITE   = "client_scorecard.write"
    CLIENT_SCORECARD_REVIEW  = "client_scorecard.review"
    CLIENT_SCORECARD_APPROVE = "client_scorecard.approve"

    # Step 2b -- the job posting. Sparsh-side only: a client agrees the benchmark
    # and reads the candidates, but the advert is Sparsh's professional work and
    # the public link is Sparsh's to open and close.
    CLIENT_POSTING_READ    = "client_posting.read"
    CLIENT_POSTING_WRITE   = "client_posting.write"
    CLIENT_POSTING_PUBLISH = "client_posting.publish"

    # ── Client Hiring, steps 3-4 -- sourcing, screening, and the CV share ──
    #
    # SHARE is separate from WRITE because the SOP's RACI makes shortlist DELIVERY the Team
    # Lead's accountability ("Shortlist delivery to client: Recruiter R, Team Lead A") while
    # sourcing and screening are the recruiter's alone. DECIDE belongs to the client and to
    # nobody at Sparsh: their verdict on a CV is the gate into assessment, and a gate the
    # supplier can open for itself is not a gate.
    CLIENT_CANDIDATE_READ   = "client_candidate.read"
    CLIENT_CANDIDATE_WRITE  = "client_candidate.write"
    CLIENT_CANDIDATE_SHARE  = "client_candidate.share"
    CLIENT_CANDIDATE_DECIDE = "client_candidate.decide"

    # ── Client Hiring, step 5 -- the assessment (PRO-fit SOP sections 12, 13) ──
    #
    # MANAGE and SCORE are separate because the SOP's own responsibility table separates
    # them: "Assessment managed -- Sparsh HR/Recruitment" and "Assessment scoring --
    # Sparsh / designated evaluator" are different rows. The person who administers a test
    # is not necessarily the person qualified to mark it, and collapsing the two would
    # make that distinction unrecordable.
    CLIENT_ASSESSMENT_READ   = "client_assessment.read"
    CLIENT_ASSESSMENT_MANAGE = "client_assessment.manage"
    CLIENT_ASSESSMENT_SCORE  = "client_assessment.score"
    CLIENT_ASSESSMENT_SHARE  = "client_assessment.share"
    CLIENT_ASSESSMENT_REVIEW = "client_assessment.review"

    # ── Client Hiring, step 6 -- interview, recording, client selection ──
    #
    # Sparsh conducts the interview on a recorded platform and shares the recording; the
    # client watches it and decides. DECIDE is the client's and nobody at Sparsh holds it,
    # because this is the selection -- the point at which a person is chosen.
    CLIENT_INTERVIEW_READ   = "client_interview.read"
    CLIENT_INTERVIEW_MANAGE = "client_interview.manage"
    CLIENT_INTERVIEW_SHARE  = "client_interview.share"
    CLIENT_INTERVIEW_DECIDE = "client_interview.decide"

    # ── Client Hiring, step 7 -- reference check and the offer (SOP sections 15-17) ──
    #
    # The reference check is SPARSH-ONLY and never reaches the ceiling. Section 15 shares
    # the background check and culture score with the client AFTER joining; a referee's
    # candid remarks about somebody who has not been hired are not the client's to read.
    CLIENT_REFERENCE_READ  = "client_reference.read"
    CLIENT_REFERENCE_WRITE = "client_reference.write"

    # The offer follows the section 8 matrix exactly: "Offer letter release -- Recruiter:
    # Facilitate, Team Lead: Verify docs, Client: Approve & Issue". Three capabilities,
    # three hands, and RELEASE is the client's -- section 17 has the client releasing the
    # letter directly to the candidate.
    CLIENT_OFFER_READ    = "client_offer.read"
    CLIENT_OFFER_WRITE   = "client_offer.write"
    CLIENT_OFFER_VERIFY  = "client_offer.verify"
    CLIENT_OFFER_RELEASE = "client_offer.release"
    # Approving pay ABOVE the range the client themselves approved. Client HR's call and
    # nobody else's -- it commits the client's money, so it sits in CLIENT_DECISION_CAPS
    # beside the other five and is subtracted from every Sparsh role, Superadmin included.
    CLIENT_OFFER_DEVIATE = "client_offer.deviate"

    # ── Client Hiring, steps 8-9 -- pre-boarding, joining, handover (sections 18-20) ──
    #
    # CONFIRM is the client's: section 18 has "the client/HR confirms candidate joining in
    # writing". HANDOVER is the Team Lead's, whom the RACI makes accountable for the
    # handover note and the requisition closure that follows it.
    CLIENT_JOINING_READ     = "client_joining.read"
    CLIENT_JOINING_MANAGE   = "client_joining.manage"
    CLIENT_JOINING_CONFIRM  = "client_joining.confirm"
    CLIENT_JOINING_HANDOVER = "client_joining.handover"

    # ── Client Hiring -- delivery analytics for the PRO-fit track ──
    #
    # Its own capability rather than riding on the record reads, so a client company can
    # be given the pipeline without the board, or the board without every record. It is
    # also what keeps this separate from the INTERNAL recruitment dashboard, which is
    # gated by ANALYTICS_READ and counts entirely different things.
    CLIENT_ANALYTICS_READ = "client_analytics.read"
    # ── Later phases append their capabilities here. ──


# Default capability set per HRMS role. Phase 11 layers per-user grants on top of this;
# until then this matrix IS the permission model.
#
# ADMIN is deliberately absent — it is granted everything implicitly in `can()`, so a new
# capability can never accidentally lock the owner out (the source had exactly this bug
# class, BACKEND_ANALYSIS Risk #13).
#
# On INTERNAL and salary: Sparsh staff administer HRMS for their clients, but they are
# deliberately NOT granted employee.salary.* — a client's pay data is not support-staff
# business. (Superadmin still sees everything via the implicit-ADMIN rule; that is the
# system owner, and it is a conscious, documented exception.)
#
# On the two approval capabilities: REVIEW_HR and APPROVE_MD are held by DIFFERENT roles on
# purpose. A two-stage approval where one person can perform both stages is not a control.
# HR forwards; MD approves. (superadmin still holds both via the implicit-ADMIN rule, which
# is the documented break-glass path — see PHASE_3_REPORT Finding #1.)
ROLE_CAPABILITIES: Dict[HrmsRole, Set[Cap]] = {
    HrmsRole.INTERNAL: {
        # -- Client Hiring step 1 -- support staff see the pipeline, decide nothing.
        Cap.CLIENT_REQUISITION_READ, Cap.CLIENT_SCORECARD_READ,
        Cap.CLIENT_POSTING_READ,
        Cap.CLIENT_CANDIDATE_READ, Cap.CLIENT_ASSESSMENT_READ,
        Cap.CLIENT_INTERVIEW_READ, Cap.CLIENT_OFFER_READ,
        Cap.CLIENT_JOINING_READ, Cap.CLIENT_ANALYTICS_READ,
        Cap.MODULE_ACCESS, Cap.MODULE_ADMIN, Cap.AUDIT_READ,
        Cap.EMPLOYEE_READ, Cap.EMPLOYEE_WRITE,
        Cap.DEPARTMENT_READ, Cap.DEPARTMENT_WRITE,
        Cap.DESIGNATION_READ, Cap.DESIGNATION_WRITE,
        # Sparsh staff support and observe the hiring pipeline, but the approval chain is
        # the client's own governance decision — hence no REVIEW_HR / APPROVE_MD here.
        Cap.REQUISITION_READ, Cap.REQUISITION_CREATE, Cap.REQUISITION_WRITE,
        Cap.REQUISITION_CLOSE, Cap.JD_READ, Cap.JD_WRITE,
        Cap.POSTING_READ, Cap.POSTING_WRITE,
        Cap.CANDIDATE_READ, Cap.CANDIDATE_WRITE,
        Cap.ASSESSMENT_READ, Cap.ASSESSMENT_SEND,
        Cap.INTERVIEW_READ, Cap.INTERVIEW_SCHEDULE,
        Cap.OFFER_READ,
        Cap.ONBOARDING_READ, Cap.ONBOARDING_WRITE, Cap.ONBOARDING_GENERATE_ID,
        # Sparsh staff support clients, which means answering "how is hiring going".
        # Read-only, and every figure is company-scoped -- see hrms_analytics_service.
        Cap.ANALYTICS_READ, Cap.REPORT_READ, Cap.REPORT_EXPORT,
        # ── Phase 11-R ──
        # Support routinely means "the candidate says the link does not work", so operating
        # the link registry is squarely support work.
        Cap.LINK_READ, Cap.LINK_MANAGE,
        # Collecting documents is operational; VERIFYING one is the client's own governance
        # act, the same boundary that keeps REQUISITION_REVIEW_HR off this list.
        Cap.DOCUMENT_READ, Cap.DOCUMENT_WRITE,
        # Read only, for the same reason OFFER_SEND is withheld: issuing an appointment
        # letter commits the client to employing somebody.
        Cap.APPOINTMENT_READ,
        # Read only, the same boundary as employee.salary.* above: Sparsh staff may see a
        # client's GMP enrolment to support the module, not administer their insurance.
        Cap.GMP_READ,
        Cap.SANCTION_READ,
        # ── Internal track ── READS ONLY, for the reason the rest of this set is shaped the
        # way it is: Sparsh staff support the client's hiring, they do not govern it. Budget
        # approval, scorecard sign-off, offer approval, probation confirmation and exception
        # approval are all the client's own acts, exactly like REQUISITION_APPROVE_MD and
        # DOCUMENT_VERIFY above.
        Cap.SCORECARD_READ,
        Cap.REFERENCE_READ,
        Cap.TELEPHONIC_READ,
        # NO NEGOTIATION_READ: a negotiation round is per-candidate pay, the same class as
        # the offer CTC this role already has stripped and the salary bands it is withheld
        # -- "a client's pay structure is not support-staff business".
        Cap.SETTINGS_READ,
        Cap.PROBATION_READ,
        Cap.INDUCTION_READ,
        Cap.EXCEPTION_READ,
        # ── Phase INT-2 ── reads only, for the same reason as the block above. Note the
        # absences: no SALARY_BAND_READ (a client's pay structure is not support-staff
        # business, exactly as EMPLOYEE_SALARY_READ is withheld) and no COMM_WRITE (a
        # message to a candidate goes out over the client's name).
        Cap.SHORTLIST_READ,
        Cap.PREBOARDING_READ,
        Cap.COMM_READ,
        Cap.SURVEY_READ,
        Cap.POLICY_READ,
        # ── Phase 12 ── Sparsh staff record background checks. Consistent with this role
        # everywhere else, they hold no approval -- BACKGROUND_APPROVE is what unlocks an
        # offer, and that is a decision.
        Cap.BACKGROUND_READ, Cap.BACKGROUND_WRITE,
        Cap.INTERVIEW_MEDIA,
        # ── Phase LETTER-1 ── read only, the same "support observes, does not issue
        # controlled correspondence" line APPOINTMENT_READ/OFFER_READ already draw.
        Cap.LETTER_READ,
    },
    HrmsRole.MD: {
        # -- Client Hiring step 1 -- Operations Head oversight of the same decision.
        Cap.CLIENT_REQUISITION_READ, Cap.CLIENT_REQUISITION_REVIEW,
        # -- step 2 -- same oversight. Note the Operations Head does NOT hold
        # CLIENT_SCORECARD_APPROVE: the client's approval is theirs alone to give.
        Cap.CLIENT_SCORECARD_READ, Cap.CLIENT_SCORECARD_REVIEW,
        # -- step 2b -- the advert. Read and publish, but the recruiter writes it.
        Cap.CLIENT_POSTING_READ, Cap.CLIENT_POSTING_PUBLISH,
        # -- steps 3-4 -- same again: oversight of delivery, never the client's
        # verdict on a CV.
        Cap.CLIENT_CANDIDATE_READ, Cap.CLIENT_CANDIDATE_SHARE,
        # -- step 5 -- oversight of delivery, never the client's review.
        Cap.CLIENT_ASSESSMENT_READ, Cap.CLIENT_ASSESSMENT_SHARE,
        # -- step 6 -- oversight of delivery, never the client's selection.
        Cap.CLIENT_INTERVIEW_READ, Cap.CLIENT_INTERVIEW_SHARE,
        # -- step 7 -- oversight, and may verify. Never issues the letter.
        Cap.CLIENT_REFERENCE_READ, Cap.CLIENT_OFFER_READ,
        Cap.CLIENT_OFFER_VERIFY,
        # -- step 9 -- same oversight of the handover.
        Cap.CLIENT_JOINING_READ, Cap.CLIENT_JOINING_HANDOVER,
        Cap.CLIENT_ANALYTICS_READ,
        Cap.MODULE_ACCESS, Cap.MODULE_ADMIN, Cap.AUDIT_READ,
        Cap.EMPLOYEE_READ, Cap.EMPLOYEE_WRITE,
        Cap.EMPLOYEE_SALARY_READ, Cap.EMPLOYEE_SALARY_WRITE,
        Cap.DEPARTMENT_READ, Cap.DEPARTMENT_WRITE,
        Cap.DESIGNATION_READ, Cap.DESIGNATION_WRITE,
        Cap.REQUISITION_READ, Cap.REQUISITION_CREATE, Cap.REQUISITION_WRITE,
        Cap.REQUISITION_APPROVE_MD, Cap.REQUISITION_CLOSE,
        Cap.JD_READ, Cap.JD_WRITE,
        Cap.POSTING_READ, Cap.POSTING_WRITE,
        Cap.CANDIDATE_READ, Cap.CANDIDATE_WRITE, Cap.CANDIDATE_SCREEN,
        Cap.ASSESSMENT_READ, Cap.ASSESSMENT_SEND, Cap.ASSESSMENT_REVIEW,
        Cap.INTERVIEW_READ, Cap.INTERVIEW_SCHEDULE, Cap.INTERVIEW_EVALUATE,
        Cap.INTERVIEW_DECIDE_MD,
        Cap.OFFER_READ, Cap.OFFER_WRITE, Cap.OFFER_SEND,
        Cap.ONBOARDING_READ, Cap.ONBOARDING_WRITE, Cap.ONBOARDING_GENERATE_ID,
        Cap.ANALYTICS_READ, Cap.REPORT_READ, Cap.REPORT_EXPORT,
        # ── Phase 11-R ──
        Cap.LINK_READ, Cap.LINK_MANAGE,
        Cap.DOCUMENT_READ, Cap.DOCUMENT_WRITE, Cap.DOCUMENT_VERIFY,
        Cap.APPOINTMENT_READ, Cap.APPOINTMENT_WRITE, Cap.APPOINTMENT_SEND,
        Cap.SANCTION_READ, Cap.SANCTION_WRITE,
        # MD holds the escalation capability as well as the final approval: an escalation
        # ladder that stalls because its top rung cannot act is not a control, it is a trap.
        Cap.REQUISITION_ESCALATE,
        # ── Internal track ── the MD is the top of the ladder and holds EVERY internal
        # capability, for the same reason it holds REQUISITION_ESCALATE: a governance chain
        # whose final authority cannot act is a trap, not a control. In a company with no
        # FINANCE user the MD alone can therefore run the whole internal track.
        Cap.REQUISITION_APPROVE_BUDGET,
        Cap.SCORECARD_READ, Cap.SCORECARD_WRITE, Cap.SCORECARD_APPROVE,
        Cap.POSTING_APPROVE_EXEC_SEARCH,
        Cap.REFERENCE_READ, Cap.REFERENCE_WRITE,
        Cap.TELEPHONIC_READ, Cap.TELEPHONIC_WRITE,
        Cap.NEGOTIATION_READ, Cap.NEGOTIATION_WRITE,
        Cap.SETTINGS_READ, Cap.SETTINGS_WRITE,
        Cap.OFFER_APPROVE,
        Cap.PROBATION_READ, Cap.PROBATION_REVIEW, Cap.PROBATION_CONFIRM,
        Cap.INDUCTION_READ, Cap.INDUCTION_WRITE,
        Cap.EXCEPTION_READ, Cap.EXCEPTION_WRITE, Cap.EXCEPTION_APPROVE,
        Cap.PERSONNEL_FILE_CLOSE,
        # ── Phase INT-2 ── the MD holds every one of these, on the same reasoning as the
        # block above: a governance chain whose final authority cannot act is a trap. Two
        # of them are the MD's ALONE -- approving a policy revision and executing a
        # retention purge -- because both are irreversible statements about the company.
        Cap.SHORTLIST_READ, Cap.SHORTLIST_WRITE,
        Cap.PREBOARDING_READ, Cap.PREBOARDING_WRITE,
        Cap.SALARY_BAND_READ, Cap.SALARY_BAND_WRITE,
        Cap.COMM_READ, Cap.COMM_WRITE, Cap.COMM_TEMPLATE_WRITE,
        Cap.SURVEY_READ,
        Cap.POLICY_READ, Cap.POLICY_WRITE, Cap.POLICY_APPROVE,
        Cap.RETENTION_PURGE,
        # ── Phase 12 ── background verification, including the sign-off that unlocks an offer.
        Cap.BACKGROUND_READ, Cap.BACKGROUND_WRITE, Cap.BACKGROUND_APPROVE,
        Cap.INTERVIEW_MEDIA,
        # ── Phase EXIT-1 ── the MD holds every one of these, on the same reasoning as the
        # blocks above: a governance chain whose final authority cannot act is a trap. The
        # notice waiver and the F&F approval are the MD's alone if there is no separate
        # Finance user — the same fallback FINANCE's absence already implies elsewhere.
        Cap.SEPARATION_READ, Cap.SEPARATION_INITIATE, Cap.SEPARATION_MANAGE,
        Cap.SEPARATION_APPROVE,
        Cap.HANDOVER_READ, Cap.HANDOVER_WRITE, Cap.HANDOVER_APPROVE,
        Cap.CLEARANCE_READ, Cap.CLEARANCE_MANAGE, Cap.CLEARANCE_ACT,
        Cap.EXIT_INTERVIEW_READ, Cap.EXIT_INTERVIEW_WRITE,
        Cap.EXIT_INTERVIEW_SUBMIT,
        Cap.FNF_READ, Cap.FNF_PREPARE, Cap.FNF_APPROVE,
        # ── Phase ATT-1 ── same reasoning as every block above: the MD holds every one of
        # these so the governance chain's top rung can always act, including in a company
        # with no separate HR user.
        Cap.ATTENDANCE_READ, Cap.ATTENDANCE_MARK,
        Cap.ATTENDANCE_REGULARIZE_REQUEST, Cap.ATTENDANCE_REGULARIZE_APPROVE,
        Cap.ATTENDANCE_LOCK,
        Cap.OD_REQUEST, Cap.OD_APPROVE,
        Cap.LEAVE_READ, Cap.LEAVE_APPLY, Cap.LEAVE_APPROVE, Cap.LEAVE_POLICY_MANAGE,
        Cap.COFF_EARN_REQUEST, Cap.COFF_APPROVE,
        # ── Phase MOVE-1 ── same reasoning as every block above: the top of the ladder holds
        # every one of these, including the POSH tier — a company with no separate HR user
        # must still be able to run a sensitive case rather than have it stall unheard.
        Cap.MOVEMENT_READ, Cap.MOVEMENT_INITIATE, Cap.MOVEMENT_APPROVE,
        Cap.DISCIPLINE_READ, Cap.DISCIPLINE_MANAGE, Cap.DISCIPLINE_DECIDE,
        Cap.DISCIPLINE_POSH_READ, Cap.DISCIPLINE_POSH_MANAGE,
        Cap.ABSCONDING_READ, Cap.ABSCONDING_MANAGE, Cap.ABSCONDING_DECIDE,
        Cap.RETIREMENT_ALERT_READ,
        # ── Phase PAY-1 ── same reasoning as every block above: the top of the ladder holds
        # every one of these, including both money gates, so a company with no separate
        # Finance user can still run payroll and variable pay to completion.
        Cap.PAYROLL_READ, Cap.PAYROLL_PROCESS, Cap.PAYROLL_APPROVE,
        Cap.SALARY_STRUCTURE_READ, Cap.SALARY_STRUCTURE_MANAGE,
        Cap.ADVANCE_READ, Cap.ADVANCE_REQUEST, Cap.ADVANCE_APPROVE, Cap.ADVANCE_APPROVE_EMERGENCY,
        Cap.VARIABLE_PAY_READ, Cap.VARIABLE_PAY_PROCESS, Cap.VARIABLE_PAY_APPROVE,
        Cap.VARIABLE_PAY_HOLD_MANAGE,
        Cap.PIP_READ, Cap.PIP_MANAGE, Cap.PIP_DECIDE, Cap.PIP_ACKNOWLEDGE,
        Cap.LETTER_READ, Cap.LETTER_MANAGE,
        Cap.PULSE_READ, Cap.PULSE_MANAGE,
    },
    HrmsRole.HR: {
        # -- Client Hiring step 1 -- the recruiter reads client requisitions but does
        # not pass them: the feasibility call is the Team Lead's (SOP RACI).
        Cap.CLIENT_REQUISITION_READ,
        # -- step 2 -- the recruiter DRAFTS the Position Scorecard (matrix: 'Draft').
        Cap.CLIENT_SCORECARD_READ, Cap.CLIENT_SCORECARD_WRITE,
        # -- step 2b -- the recruiter writes the advert and opens it for applications
        # once the client has agreed the benchmark it is written against.
        Cap.CLIENT_POSTING_READ, Cap.CLIENT_POSTING_WRITE, Cap.CLIENT_POSTING_PUBLISH,
        # -- steps 3-4 -- sources and screens. Delivery to the client is the Team
        # Lead's call (RACI: 'Shortlist delivery to client -- Team Lead A').
        Cap.CLIENT_CANDIDATE_READ, Cap.CLIENT_CANDIDATE_WRITE,
        # -- step 5 -- administers the assessment, and may be the designated
        # evaluator who marks it.
        Cap.CLIENT_ASSESSMENT_READ, Cap.CLIENT_ASSESSMENT_MANAGE,
        Cap.CLIENT_ASSESSMENT_SCORE,
        # -- step 6 -- schedules and conducts the recorded panel interview.
        Cap.CLIENT_INTERVIEW_READ, Cap.CLIENT_INTERVIEW_MANAGE,
        # -- step 7 -- takes references and prepares the offer. Facilitates its
        # release; does not verify it and cannot issue it.
        Cap.CLIENT_REFERENCE_READ, Cap.CLIENT_REFERENCE_WRITE,
        Cap.CLIENT_OFFER_READ, Cap.CLIENT_OFFER_WRITE,
        # -- steps 8-9 -- keeps the joiner warm (section 19) and records a drop.
        Cap.CLIENT_JOINING_READ, Cap.CLIENT_JOINING_MANAGE,
        Cap.CLIENT_ANALYTICS_READ,
        Cap.MODULE_ACCESS, Cap.AUDIT_READ,
        Cap.EMPLOYEE_READ, Cap.EMPLOYEE_WRITE,
        Cap.EMPLOYEE_SALARY_READ, Cap.EMPLOYEE_SALARY_WRITE,
        Cap.DEPARTMENT_READ, Cap.DEPARTMENT_WRITE,
        Cap.DESIGNATION_READ, Cap.DESIGNATION_WRITE,
        Cap.REQUISITION_READ, Cap.REQUISITION_CREATE, Cap.REQUISITION_WRITE,
        Cap.REQUISITION_REVIEW_HR, Cap.REQUISITION_CLOSE,
        Cap.JD_READ, Cap.JD_WRITE,
        Cap.POSTING_READ, Cap.POSTING_WRITE,
        Cap.CANDIDATE_READ, Cap.CANDIDATE_WRITE, Cap.CANDIDATE_SCREEN,
        Cap.ASSESSMENT_READ, Cap.ASSESSMENT_SEND, Cap.ASSESSMENT_REVIEW,
        Cap.INTERVIEW_READ, Cap.INTERVIEW_SCHEDULE, Cap.INTERVIEW_EVALUATE,
        Cap.OFFER_READ, Cap.OFFER_WRITE, Cap.OFFER_SEND,
        Cap.ONBOARDING_READ, Cap.ONBOARDING_WRITE, Cap.ONBOARDING_GENERATE_ID,
        Cap.ANALYTICS_READ, Cap.REPORT_READ, Cap.REPORT_EXPORT,
        # ── Phase 11-R ──
        Cap.LINK_READ, Cap.LINK_MANAGE,
        Cap.DOCUMENT_READ, Cap.DOCUMENT_WRITE, Cap.DOCUMENT_VERIFY,
        Cap.APPOINTMENT_READ, Cap.APPOINTMENT_WRITE, Cap.APPOINTMENT_SEND,
        Cap.SANCTION_READ, Cap.SANCTION_WRITE,
        # Deliberately NO REQUISITION_ESCALATE: the escalation ladder is the reporting
        # hierarchy above the raiser, and HR reviewing then also escalating would collapse
        # two stages into one person -- the same separation the HR/MD split already draws.
        # ── Internal track ── HR is "R" (responsible) on almost every line of Annexure B:
        # it drafts the scorecard, runs sourcing and screening, conducts the reference check,
        # releases the offer, runs induction and closes the personnel file.
        Cap.SCORECARD_READ, Cap.SCORECARD_WRITE,
        Cap.REFERENCE_READ, Cap.REFERENCE_WRITE,
        Cap.TELEPHONIC_READ, Cap.TELEPHONIC_WRITE,
        Cap.NEGOTIATION_READ, Cap.NEGOTIATION_WRITE,
        Cap.SETTINGS_READ,
        Cap.PROBATION_READ, Cap.PROBATION_REVIEW,
        Cap.INDUCTION_READ, Cap.INDUCTION_WRITE,
        Cap.EXCEPTION_READ, Cap.EXCEPTION_WRITE,
        Cap.PERSONNEL_FILE_CLOSE,
        # Deliberately ABSENT, and each for a reason the RACI states outright:
        #   REQUISITION_APPROVE_BUDGET -- Annexure B gives HR "C" on budget, Management "A".
        #   SCORECARD_APPROVE          -- HR drafts ("R"), the HOD approves ("A").
        #   OFFER_APPROVE              -- HR verifies budget compliance, Management approves.
        #   PROBATION_CONFIRM          -- HR recommends ("C"), the HOD confirms ("A/R").
        #   EXCEPTION_APPROVE          -- HR may raise one, Management/Finance approves it.
        # Every one of those is the same separation-of-duties the HR/MD split already draws.
        #
        # ── Phase INT-2 ── HR is "R" on every one of these lines too: it convenes the
        # shortlisting committee, runs pre-boarding engagement, sends candidate
        # communications, administers the surveys and maintains the policy register.
        Cap.SHORTLIST_READ, Cap.SHORTLIST_WRITE,
        Cap.PREBOARDING_READ, Cap.PREBOARDING_WRITE,
        Cap.COMM_READ, Cap.COMM_WRITE,
        Cap.SURVEY_READ,
        Cap.POLICY_READ, Cap.POLICY_WRITE,
        # READ, not write: the band master is agreed annually WITH Finance (Annexure C), so
        # HR reads what was agreed and the budget gate pre-fills from it. HR rewriting the
        # band would make the annual agreement a suggestion.
        Cap.SALARY_BAND_READ,
        # Deliberately ABSENT, each for the reason the block above states:
        #   SALARY_BAND_WRITE   -- Finance and the MD agree the bands.
        #   COMM_TEMPLATE_WRITE -- the templates carry the EEO and data-use wording.
        #   POLICY_APPROVE      -- HR drafts a revision; the MD makes it the one in force.
        #   RETENTION_PURGE     -- destroying records is not an operational act.
        # ── Phase 12 ── HR runs the client track end to end, and holds the verification
        # sign-off because requirement 8 names HR as the approver ("Background Verification
        # -> HR Approval -> Offer Letter"). WRITE and APPROVE are still separate
        # capabilities, so a company that wants two pairs of eyes can withdraw one of them
        # from a junior recruiter without touching the other.
        Cap.BACKGROUND_READ, Cap.BACKGROUND_WRITE, Cap.BACKGROUND_APPROVE,
        Cap.INTERVIEW_MEDIA,
        # ── Phase EXIT-1 ── HR runs the process end to end: raises/records a case, drives
        # notice and handover, opens and manages clearance/asset/access tasks, and prepares
        # F&F. Deliberately ABSENT, each for the reason the RACI states outright:
        #   SEPARATION_APPROVE -- the written approval a waiver/early-release needs (BR-016).
        #   HANDOVER_APPROVE   -- the reporting manager's own sign-off on a handover item.
        #   FNF_APPROVE        -- HR/Payroll prepares ("R"); Finance approves ("A"), the same
        #                         maker/checker split BR-021 asks for explicitly.
        Cap.SEPARATION_READ, Cap.SEPARATION_INITIATE, Cap.SEPARATION_MANAGE,
        Cap.HANDOVER_READ, Cap.HANDOVER_WRITE,
        Cap.CLEARANCE_READ, Cap.CLEARANCE_MANAGE, Cap.CLEARANCE_ACT,
        Cap.EXIT_INTERVIEW_READ, Cap.EXIT_INTERVIEW_WRITE,
        Cap.EXIT_INTERVIEW_SUBMIT,
        Cap.FNF_READ, Cap.FNF_PREPARE,
        # ── Phase ATT-1 ── HR runs this end to end too: marks/corrects attendance, is the
        # second-level regularisation approver (§7.9 step 68), locks the monthly period
        # (§7.12 steps 84-88), approves leave and C-Off, and owns the leave-type/policy
        # register (§22.8) since nobody else in this matrix is positioned to freeze those
        # numbers once the client confirms them.
        Cap.ATTENDANCE_READ, Cap.ATTENDANCE_MARK,
        Cap.ATTENDANCE_REGULARIZE_REQUEST, Cap.ATTENDANCE_REGULARIZE_APPROVE,
        Cap.ATTENDANCE_LOCK,
        Cap.OD_REQUEST, Cap.OD_APPROVE,
        Cap.LEAVE_READ, Cap.LEAVE_APPLY, Cap.LEAVE_APPROVE, Cap.LEAVE_POLICY_MANAGE,
        Cap.COFF_EARN_REQUEST, Cap.COFF_APPROVE,
        # ── Phase MOVE-1 ── HR runs movements, discipline and absconding end to end,
        # including the POSH tier (HR is the one non-Management role the doc trusts with
        # sensitive cases). Deliberately ABSENT, each for the reason the RACI states outright:
        #   DISCIPLINE_DECIDE / ABSCONDING_DECIDE -- "Authorised management approves/
        #   implements" (§7.17 step 133) and "authorised final decision" (§7.19 step 153) are
        #   Management's sign-off, the same maker/checker split BR-021 already draws for F&F.
        Cap.MOVEMENT_READ, Cap.MOVEMENT_INITIATE, Cap.MOVEMENT_APPROVE,
        Cap.DISCIPLINE_READ, Cap.DISCIPLINE_MANAGE,
        Cap.DISCIPLINE_POSH_READ, Cap.DISCIPLINE_POSH_MANAGE,
        Cap.ABSCONDING_READ, Cap.ABSCONDING_MANAGE,
        Cap.RETIREMENT_ALERT_READ,
        # ── Phase PAY-1 ── HR/Payroll is the maker throughout ("Payroll Maker", "HR/
        # Performance Owner"), and holds the NORMAL advance-approval tier the doc names
        # alongside the reporting manager. Deliberately ABSENT, each for the reason the RACI
        # states outright:
        #   PAYROLL_APPROVE / VARIABLE_PAY_APPROVE -- "Payroll/Finance Approver" and
        #   "Finance/Management" are the checker, the same split BR-021 already draws.
        #   ADVANCE_APPROVE_EMERGENCY -- named as "Director HR / Finance" specifically, a
        #   narrower tier than plain HR.
        #   VARIABLE_PAY_HOLD_MANAGE -- releasing/forfeiting held pay is a Finance-level
        #   call at FY-end, not a routine HR act.
        Cap.PAYROLL_READ, Cap.PAYROLL_PROCESS,
        Cap.SALARY_STRUCTURE_READ, Cap.SALARY_STRUCTURE_MANAGE,
        Cap.ADVANCE_READ, Cap.ADVANCE_APPROVE,
        Cap.VARIABLE_PAY_READ, Cap.VARIABLE_PAY_PROCESS,
        # ── Phase PIP-1 ── HR is the process owner throughout ("HR monitors overdue
        # reviews and plan expiry", step 219) and, unlike Discipline/Payroll, the doc names
        # no separate Management sign-off tier for PIP — HR holds the outcome decision too.
        Cap.PIP_READ, Cap.PIP_MANAGE, Cap.PIP_DECIDE,
        # ── Phase LETTER-1 ── "Users: HR" is the BA doc's own line for this screen.
        Cap.LETTER_READ, Cap.LETTER_MANAGE,
        # ── Phase PULSE-1 ── §22.4 step 213: "HR dashboard shows completion rate, average
        # scores, common issues and follow-up status" — HR is the one role the doc names.
        Cap.PULSE_READ, Cap.PULSE_MANAGE,
        # ── Phase GMP-1 ── HR administers the one HR Policy-adjacent record the BA doc
        # names no separate approval tier for.
        Cap.GMP_READ, Cap.GMP_WRITE,
    },
    # A hiring manager reads their own corner of the directory (enforced by row scoping in
    # hrms_employee_service, not by this set) and never sees pay. They RAISE requisitions --
    # that is the documented design intent: whoever raises one becomes its hiring manager.
    HrmsRole.MANAGER: {
        # -- Client Hiring step 1 -- Team Lead is Accountable for the feasibility and
        # budget review (SOP section 7 step 3).
        Cap.CLIENT_REQUISITION_READ, Cap.CLIENT_REQUISITION_REVIEW,
        # -- step 2 -- and reviews the scorecard before it is shared (section 5.2).
        Cap.CLIENT_SCORECARD_READ, Cap.CLIENT_SCORECARD_REVIEW,
        # -- step 2b -- accountable for what reaches the public, as for the shortlist.
        Cap.CLIENT_POSTING_READ, Cap.CLIENT_POSTING_PUBLISH,
        # -- steps 3-4 -- accountable for what goes to the client.
        Cap.CLIENT_CANDIDATE_READ, Cap.CLIENT_CANDIDATE_SHARE,
        # -- step 5 -- may mark, and delivers the result.
        Cap.CLIENT_ASSESSMENT_READ, Cap.CLIENT_ASSESSMENT_SCORE,
        Cap.CLIENT_ASSESSMENT_SHARE,
        # -- step 6 -- sits on the panel, and delivers the recording.
        Cap.CLIENT_INTERVIEW_READ, Cap.CLIENT_INTERVIEW_MANAGE,
        Cap.CLIENT_INTERVIEW_SHARE,
        # -- step 7 -- 'Team Lead: Verify docs' (section 8 matrix).
        Cap.CLIENT_REFERENCE_READ, Cap.CLIENT_OFFER_READ,
        Cap.CLIENT_OFFER_VERIFY,
        # -- step 9 -- accountable for the handover and the closure it triggers.
        Cap.CLIENT_JOINING_READ, Cap.CLIENT_JOINING_HANDOVER,
        Cap.CLIENT_ANALYTICS_READ,
        Cap.MODULE_ACCESS,
        Cap.EMPLOYEE_READ,
        Cap.DEPARTMENT_READ, Cap.DESIGNATION_READ,
        Cap.REQUISITION_READ, Cap.REQUISITION_CREATE, Cap.JD_READ,
        Cap.POSTING_READ,
        Cap.CANDIDATE_READ,
        Cap.ASSESSMENT_READ, Cap.ASSESSMENT_REVIEW,
        Cap.INTERVIEW_READ, Cap.INTERVIEW_EVALUATE,
        Cap.OFFER_READ,
        Cap.ONBOARDING_READ,
        # A hiring manager sees analytics for THEIR OWN requisitions only -- the same row
        # scoping the candidate list applies, enforced in the service rather than here.
        # Deliberately NO export: aggregate figures on screen are one thing, a downloadable
        # file of every candidate is another.
        Cap.ANALYTICS_READ, Cap.REPORT_READ,
        # ── Phase 11-R ──
        # Read only, and row-scoped to their own requisitions in the services (same
        # narrowing the candidate list applies), never enforced by this set alone.
        Cap.LINK_READ,
        Cap.DOCUMENT_READ,
        Cap.APPOINTMENT_READ,
        Cap.SANCTION_READ,
        # A hiring manager IS the reporting line an over-sanction requisition escalates
        # through -- this is the capability that lets them clear their rung.
        Cap.REQUISITION_ESCALATE,
        # ── Internal track ── the HOD is "A" on the scorecard, the shortlist, the panel
        # interview and probation confirmation (Annexure B), so those are approvals here.
        # Budget is NOT theirs: Annexure B gives the HOD "C" on headcount and budget.
        Cap.SCORECARD_READ, Cap.SCORECARD_APPROVE,
        Cap.REFERENCE_READ,
        # "I" on telephonic screening (Annexure B) -- the HOD interviews off the back of
        # the call, so they read it; recording one is HR's act alone.
        Cap.TELEPHONIC_READ,
        # "C" on salary negotiation (Annexure B): consulted, so the HOD reads the rounds
        # and never records one.
        Cap.NEGOTIATION_READ,
        # ── Phase INT-5 ── reads the rule set, never edits it. A hiring manager plans
        # against the SLA and the probation duration, so a target they cannot see is one
        # they cannot plan against; changing it is Management's act.
        Cap.SETTINGS_READ,
        Cap.PROBATION_READ, Cap.PROBATION_REVIEW, Cap.PROBATION_CONFIRM,
        # ── Phase ORIENT-1 ── §22.3 step 201 names "HR/Manager" as who schedules orientation
        # sessions and assigns a trainer/facilitator — WRITE, not just the Day-1 checklist
        # read this capability started as.
        Cap.INDUCTION_READ, Cap.INDUCTION_WRITE,
        # May RAISE an exception, never approve one -- Annexure B puts exception approval
        # with Management/Finance.
        Cap.EXCEPTION_READ, Cap.EXCEPTION_WRITE,
        # ── Phase INT-2 ── the HOD SITS on the shortlisting committee (SOP §5 requires HR
        # AND the HOD), so this is a write, not a read. Everything else is read: the HOD is
        # informed about pre-boarding and the policy register, and sees survey scores for
        # their own team through the same row scoping the candidate list applies.
        Cap.SHORTLIST_READ, Cap.SHORTLIST_WRITE,
        Cap.PREBOARDING_READ,
        Cap.SURVEY_READ,
        Cap.POLICY_READ,
        # ── Phase 12 ── a hiring manager SEES the background verification behind a hire
        # they are accountable for, and neither records nor approves one.
        Cap.BACKGROUND_READ,
        # ── Phase EXIT-1 ── the reporting manager reviews a departing report's case and is
        # the one required sign-off the BA doc names explicitly: accepting (or rejecting) a
        # submitted handover item (§22.2 step 191). They also act on whatever departmental
        # clearance task lands on them, the same way any clearance owner does. No
        # SEPARATION_MANAGE/INITIATE, no HANDOVER_WRITE (that is HR's plan to build, not the
        # manager's), no FNF_* — a manager is not part of the money chain.
        Cap.SEPARATION_READ,
        Cap.HANDOVER_READ, Cap.HANDOVER_APPROVE,
        Cap.CLEARANCE_READ, Cap.CLEARANCE_ACT,
        Cap.EXIT_INTERVIEW_READ,
        # ── Phase MOVE-1 ── the reporting manager/HOD is the named INITIATOR for their own
        # reports (§7.16 actors: "Reporting Manager / HOD, HR..."), and is named alongside
        # HR as an absconding actor too (§7.19). No MOVEMENT_APPROVE — a manager proposing
        # their own report's promotion is not also that request's approver. No
        # DISCIPLINE_DECIDE/ABSCONDING_DECIDE/POSH caps — those stay Management/HR's, the
        # same reason a manager never held SEPARATION_APPROVE. DISCIPLINE_MANAGE is
        # deliberately ABSENT too: the doc names "Employee / Manager" as who a complaint may
        # be reported BY, but building safe raise-a-complaint self-service (confidentiality,
        # anonymity) is a documented follow-up, not something to half-build here — the same
        # honesty EXIT-1's ownership-check gap already models.
        Cap.MOVEMENT_READ, Cap.MOVEMENT_INITIATE,
        Cap.ABSCONDING_READ, Cap.ABSCONDING_MANAGE,
        Cap.RETIREMENT_ALERT_READ,
        # ── Phase PAY-1 ── the reporting manager holds the NORMAL advance-approval tier the
        # doc names explicitly ("Reporting Manager/HR"), for their own reports (row-scoped in
        # the service, not by this set). No PAYROLL_*/VARIABLE_PAY_*/SALARY_STRUCTURE_* — a
        # manager is not part of the payroll chain at all, the same reason it never held
        # EMPLOYEE_SALARY_WRITE.
        Cap.ADVANCE_READ, Cap.ADVANCE_APPROVE,
        # ── Phase PIP-1 ── the manager initiates a PIP against their own report and records
        # periodic review notes (steps 215, 218) — row-scoped in the service. No PIP_DECIDE:
        # the final outcome (one option being "Separation Recommended") stays HR's, the same
        # reason a manager never held DISCIPLINE_DECIDE either.
        Cap.PIP_READ, Cap.PIP_MANAGE,
        # ── Phase ATT-1 ── the reporting manager is the named first-level approver in every
        # one of these workflows (§7.9 step 66, §7.10 step 73, §7.11 step 82, §22.9's own
        # team view) for their reports, enforced by row scoping in the service, not by this
        # set. Also has the self-service caps every role gets for their OWN record. No MARK
        # (HR's act, not a manager's), no ATTENDANCE_LOCK or LEAVE_POLICY_MANAGE — neither is
        # named as a manager act anywhere in §7.8-7.12 or §22.8.
        Cap.ATTENDANCE_READ,
        Cap.ATTENDANCE_REGULARIZE_REQUEST, Cap.ATTENDANCE_REGULARIZE_APPROVE,
        Cap.OD_REQUEST, Cap.OD_APPROVE,
        Cap.LEAVE_READ, Cap.LEAVE_APPLY, Cap.LEAVE_APPROVE,
        Cap.COFF_EARN_REQUEST, Cap.COFF_APPROVE,
    },
    # Self-service, plus the deliberate exception that ANY employee may raise a hiring
    # requisition (FRONTEND_ANALYSIS §5: "anyone may raise a hiring requisition"). Reading
    # your OWN profile is not a capability -- it is an inherent right handled in the route,
    # so it can never be revoked by a permission edit.
    HrmsRole.EMPLOYEE: {
        Cap.MODULE_ACCESS,
        Cap.REQUISITION_READ, Cap.REQUISITION_CREATE, Cap.JD_READ,
        Cap.INTERVIEW_EVALUATE,
        # ── Phase INT-2 ── the recruitment policy is the one document in this module every
        # employee is entitled to read; SOP §14 exists to keep it current and visible. It is
        # the register, not the workflow -- no write of any kind comes with it.
        Cap.POLICY_READ,
        # ── Phase POLICY-LIB-1 (§22.6) ── an employee's own act of acknowledging a
        # published, applicable policy (step 227) — the same self-service-act pattern
        # PIP_ACKNOWLEDGE/PULSE_SUBMIT already establish. Row/applicability-scoped in
        # hrms_policy_service.acknowledge_policy, not merely capability-gated.
        Cap.POLICY_ACKNOWLEDGE,
        # ── Phase ORIENT-1 ── §22.3 step 202: "Employee sees planned sessions in My
        # Onboarding" — row-scoped to their own assignment in hrms_orientation_service, the
        # same enforced-ownership pattern Phase ATT-1 established (not merely capability-
        # gated the way EXIT-1's self-service caps are still documented as pending).
        Cap.INDUCTION_READ,
        # ── Phase EXIT-1 ── an employee raises their own resignation (§7.18 step 137) and
        # completes their own exit interview (§22.2 step 195) — the same self-service
        # exception REQUISITION_CREATE above already makes for "anyone may raise a hiring
        # requisition". Ownership IS now enforced at the service layer -- see
        # `assert_own_case` in hrms_exit_service: a caller whose only route in is one of
        # these two grants may act on their OWN record and nothing else. Read access and
        # asset-return self-initiation stay HR-mediated (SEPARATION_READ, CLEARANCE_MANAGE),
        # which is a scope choice rather than a missing control.
        Cap.SEPARATION_INITIATE, Cap.EXIT_INTERVIEW_SUBMIT,
        # ── Phase ATT-1 ── an employee sees and requests their OWN attendance, leave and
        # C-Off, and raises their own regularisation/OD requests (§7.9 step 63, §7.10 step
        # 70, §7.11 step 80, §22.9's calendar). Unlike EXIT-1's self-service caps, ownership
        # scoping for these IS enforced at the service layer (see hrms_attendance_service /
        # hrms_leave_service `_scope_to_self`) — an employee's list/get calls are filtered to
        # their own employee_code, not merely gated by the capability.
        Cap.ATTENDANCE_READ, Cap.ATTENDANCE_REGULARIZE_REQUEST,
        Cap.OD_REQUEST,
        Cap.LEAVE_READ, Cap.LEAVE_APPLY,
        Cap.COFF_EARN_REQUEST,
        # ── Phase PAY-1 ── an employee requests their own salary advance (§7.14 step 100),
        # the same self-service reasoning LEAVE_APPLY already established. No ADVANCE_READ:
        # unlike attendance/leave, Phase PAY-1 does not yet build the "list my own advances"
        # self-view — a documented follow-up, the same honesty EXIT-1's ownership-check note
        # models, not an oversight.
        Cap.ADVANCE_REQUEST,
        # ── Phase PIP-1 ── an employee needs to SEE their own PIP before they can
        # acknowledge it — granting ACKNOWLEDGE without READ would be a dead-end control
        # with no screen that reaches it. Unlike EXIT-1's ownership-check gap, this one is
        # not deferred: hrms_pip_service scopes an EMPLOYEE caller's list/get to their own
        # employee_code, the same enforced pattern Phase ATT-1 established.
        Cap.PIP_READ, Cap.PIP_ACKNOWLEDGE,
        # ── Phase LETTER-1 ── read-only, row-scoped in hrms_letter_service to letters
        # addressed to this employee's own employee_code — the same self-view PIP_READ
        # already establishes above. There is no LETTER_MANAGE here: an employee reads their
        # own correspondence, they do not issue it to themselves.
        Cap.LETTER_READ,
        # ── §22 Employee Profile / BR-028 ── "Appointment Letter must remain downloadable
        # from Employee 360 to authorised users after joining." Row-scoped in
        # hrms_appointment_service._scope_filter to the one letter raised against this
        # employee's own hiring record, the same self-view LETTER_READ establishes above.
        Cap.APPOINTMENT_READ,
        # ── Phase PAYSLIP-1 (§22.7, SM-HR-031) ── an employee reads their own payslip.
        # Row-scoped in hrms_payroll_service.list_records / hrms_payslip_service.get_payslip
        # to their own employee_code, the same enforced self-view PIP_READ establishes — NOT
        # a blanket grant to the HR-facing payroll-run/records screens' other data.
        Cap.PAYROLL_READ,
        # ── Phase GMP-1 ── an employee reads their own Group Mediclaim enrolment — the
        # same self-view PIP_READ/LETTER_READ already establish. No GMP_WRITE: this stays
        # HR-administered, the employee does not edit their own coverage or dependants.
        Cap.GMP_READ,
        # ── Phase PULSE-1 ── §22.4 step 210: the employee completes their own pulse survey.
        # PULSE_READ is row-scoped to their own response the same way PIP_READ is scoped
        # above; PULSE_SUBMIT is the separate self-service completion act.
        Cap.PULSE_READ, Cap.PULSE_SUBMIT,
        # ── Phase MOVE-1 ── deliberately NOTHING here. §7.16 movements are proposed BY a
        # manager/HR, not by the employee they concern (unlike leave/attendance, this is not
        # self-service). §7.17 names "Employee" as a complaint-raising actor, but self-service
        # raise-a-complaint needs confidentiality/anonymity handling this phase does not yet
        # build — a documented follow-up, not an oversight (see the MANAGER block's note).
    },
    # ── Internal track ── the budget authority, and nothing else.
    #
    # Annexure B gives Management/Finance "A" on exactly five lines: headcount & budget
    # approval, salary negotiation, offer approval, exception approval, and KPI reporting.
    # This set is those five plus the reads needed to make them informed decisions.
    #
    # What is deliberately ABSENT is the whole hiring judgement: no CANDIDATE_SCREEN, no
    # INTERVIEW_EVALUATE, no OFFER_WRITE, no PROBATION_CONFIRM. Finance approves what a role
    # COSTS; it never decides who fills it. Nor does it hold MODULE_ADMIN.
    HrmsRole.FINANCE: {
        Cap.MODULE_ACCESS,
        # Enough context to judge a budget request: the requisition, its position, the
        # sanctioned headcount it is drawn against, and the analytics behind "KPI /
        # dashboard reporting", which Annexure B makes Management/Finance accountable for.
        Cap.REQUISITION_READ, Cap.JD_READ,
        Cap.SANCTION_READ,
        Cap.EMPLOYEE_READ,
        Cap.ANALYTICS_READ, Cap.REPORT_READ, Cap.REPORT_EXPORT,
        # Salary visibility WITHOUT salary write: approving a band requires seeing what the
        # company already pays, but the payroll record itself stays HR's and MD's.
        Cap.EMPLOYEE_SALARY_READ,
        # The two mandatory gates, and the offer read that makes the second one meaningful.
        Cap.REQUISITION_APPROVE_BUDGET,
        Cap.OFFER_READ, Cap.OFFER_APPROVE,
        # "A" on salary negotiation: Finance reads every round, because whether a proposal
        # sits inside the band it approved is exactly its question. Still no hiring
        # judgement -- it never writes a round.
        Cap.NEGOTIATION_READ,
        # Annexure B makes Management/Finance "A" on policy review, and these numbers are
        # that policy expressed as data.
        Cap.SETTINGS_READ, Cap.SETTINGS_WRITE,
        Cap.SCORECARD_READ,
        Cap.EXCEPTION_READ, Cap.EXCEPTION_APPROVE,
        # ── Phase INT-2 ── the standing salary bands are Finance's own artifact: Annexure C
        # asks Finance to agree them annually so an individual requisition does not need a
        # fresh budget conversation. Reading the survey scores follows the same line as
        # ANALYTICS_READ -- Annexure B makes Management/Finance accountable for KPI
        # reporting, and new-hire satisfaction is one of the eight KPIs.
        Cap.SALARY_BAND_READ, Cap.SALARY_BAND_WRITE,
        Cap.SURVEY_READ,
        Cap.POLICY_READ,
        # Deliberately ABSENT: SHORTLIST_* and PREBOARDING_*. Both are about WHO fills a
        # role and whether they still want it -- the hiring judgement Finance never holds.
        # ── Phase EXIT-1 ── the checker on the one gate BR-021 asks for by name: F&F
        # approval. Finance also acts on its own departmental clearance item (loans, company
        # dues) the same way any clearance owner does. No SEPARATION_MANAGE/INITIATE, no
        # HANDOVER_*, no FNF_PREPARE — Finance approves the number, HR/Payroll builds it.
        Cap.SEPARATION_READ,
        Cap.CLEARANCE_READ, Cap.CLEARANCE_ACT,
        Cap.FNF_READ, Cap.FNF_APPROVE,
        # ── Phase PAY-1 ── Finance is the checker the doc names explicitly on all three
        # money gates ("Payroll/Finance Approver", "Director HR / Finance" for emergency
        # advances, "Finance/Management" on variable pay) and the one role trusted with
        # releasing or forfeiting held variable pay at FY-end. SALARY_STRUCTURE_READ
        # mirrors EMPLOYEE_SALARY_READ just above: Finance sees what payroll is BUILT from
        # (to judge the numbers it approves) without holding SALARY_STRUCTURE_MANAGE, the
        # same "visibility without write" split that comment already draws.
        Cap.PAYROLL_READ, Cap.PAYROLL_APPROVE,
        Cap.SALARY_STRUCTURE_READ,
        Cap.ADVANCE_READ, Cap.ADVANCE_APPROVE_EMERGENCY,
        Cap.VARIABLE_PAY_READ, Cap.VARIABLE_PAY_APPROVE, Cap.VARIABLE_PAY_HOLD_MANAGE,
    },
}


# ─────────────────────────────────────────────────────────────
# Audit actions
# ─────────────────────────────────────────────────────────────
AUDIT_MODULE_ENABLED  = "hrms module enabled"
AUDIT_MODULE_DISABLED = "hrms module disabled"

# Entity names used in the audit log. Kept as constants so the Phase 5 candidate journey
# and the Phase 15 audit API filter on a closed vocabulary rather than free strings.
ENTITY_COMPANY     = "company"
ENTITY_REQUISITION = "requisition"
ENTITY_CANDIDATE   = "candidate"
ENTITY_EMPLOYEE    = "employee"
ENTITY_LEAVE       = "leave"
ENTITY_PAYROLL     = "payroll"
ENTITY_SETTING     = "setting"


# ─────────────────────────────────────────────────────────────
# Business-ID formats
# ─────────────────────────────────────────────────────────────
# The source generated these by scanning existing rows for the max suffix, which races
# under concurrency (BACKEND_ANALYSIS Risk #12). We use an atomic counter instead —
# see services/hrms_id_service.py. These are the format templates only (pure, no I/O).
ID_FORMATS = {
    # -- Client Hiring -- a prefix of its own, so a number can never be mistaken for an
    # internal requisition's in a conversation, a report or a support ticket.
    "client_requisition": ("CR", True, 3),  # CR-2026-001
    "client_scorecard":   ("PSC", True, 3),  # PSC-2026-001
    "client_posting":     ("CJP", True, 3),  # CJP-2026-001
    "client_candidate":   ("CCN", True, 3),  # CCN-2026-001
    "client_assessment":  ("CAS", True, 3),  # CAS-2026-001
    "client_interview":   ("CIN", True, 3),  # CIN-2026-001
    "client_reference":   ("CRF", True, 3),  # CRF-2026-001
    "client_offer":       ("COF", True, 3),  # COF-2026-001
    "client_joining":     ("CJN", True, 3),  # CJN-2026-001
    "requisition": ("HR-REQ", True,  3),   # HR-REQ-2026-001   (prefix, year-scoped, pad)
    "jd":          ("JD",     True,  3),   # JD-2026-001
    "interview":   ("INT",    True,  3),   # INT-2026-001
    "offer":       ("OFR",    True,  3),   # OFR-2026-001
    "onboarding":  ("ONB",    True,  3),   # ONB-2026-001
    "assessment":  ("ASM",    True,  3),   # ASM-2026-001
    "employee":    ("EMP",    True,  3),   # EMP-2026-001
    "candidate":   ("CAN",    False, 3),   # CAN-001          (not year-scoped)
    # ── Phase 11-R ──
    "link":        ("LNK",    True,  3),   # LNK-2026-001
    "document":    ("DOC",    True,  3),   # DOC-2026-001
    "appointment": ("APT",    True,  3),   # APT-2026-001
    # No "client" sequence: a client is a company and already has an id.
    # ── Internal recruitment track ──
    "scorecard":   ("SCR",    True,  3),   # SCR-2026-001
    "reference":   ("REF",    True,  3),   # REF-2026-001
    "telephonic":  ("TEL",    True,  3),   # TEL-2026-001
    "negotiation": ("NEG",    True,  3),   # NEG-2026-001
    "probation":   ("PRB",    True,  3),   # PRB-2026-001
    "exception":   ("EXC",    True,  3),   # EXC-2026-001
    # ── Phase 12: background verification ──
    "background":  ("BGV",    True,  3),   # BGV-2026-001
    # ── Phase INT-2 ──
    "shortlist":   ("SLR",    True,  3),   # SLR-2026-001  shortlisting committee record
    "preboarding": ("PBT",    True,  3),   # PBT-2026-001  pre-boarding touchpoint
    "salary_band": ("SAL",    True,  3),   # SAL-2026-001  standing band
    "survey":      ("SRV",    True,  3),   # SRV-2026-001  survey instrument
    "survey_response": ("SRP", True, 3),   # SRP-2026-001  one submission
    "purge_batch": ("PRG",    True,  3),   # PRG-2026-001  a retention purge proposal
    # No "policy" sequence: a policy is addressed by its `policy_key` (internal_recruitment,
    # profit_recruitment), which is stable across versions in a way a minted number is not.
    # No "comm_log" sequence either: the log is append-only volume, and a business id on
    # every email would burn a counter for a record nobody ever cites by number.
    # ── Phase EXIT-1 ──
    "separation":   ("SEP", True, 3),   # SEP-2026-001
    "asset_return": ("AST", True, 3),   # AST-2026-001
    "fnf":          ("FNF", True, 3),   # FNF-2026-001
    # No sequence for handover/clearance/access-clearance items or the exit interview: they
    # are child rows of a separation (see COLL_HANDOVER_TASKS etc.) and are addressed by their
    # own ObjectId plus the separation's sep_no, the same convention onboarding checklist
    # items already use.
    # ── Phase ATT-1 ──
    "leave": ("LV", True, 3),   # LV-2026-001 — covers CL/SL/EL and C-Off USE requests alike,
                                 # since §22.8 puts C-Off in the same leave dropdown as the rest.
    "regularization": ("REG", True, 3),   # REG-2026-001
    "od":            ("OD",  True, 3),    # OD-2026-001
    # No sequence for attendance rows, C-Off ledger batches or the monthly lock: attendance is
    # addressed by (employee_code, work_date), a lock by (company_id, period), and a C-Off
    # batch is a ledger line nobody cites by number — the same reasoning COLL_COMM_LOG's
    # absence above already states.
    # ── Phase MOVE-1 ──
    "movement":         ("MOV",  True, 3),   # MOV-2026-001
    "discipline_case":  ("DSC",  True, 3),   # DSC-2026-001
    "absconding_case":  ("ABS",  True, 3),   # ABS-2026-001
    # ── Phase PAY-1 ──
    "advance": ("ADV", True, 3),   # ADV-2026-001
    # No sequence for payroll runs (addressed by (company_id, period)), payroll records
    # (addressed by (period, employee_code)), variable pay quarters (addressed by
    # (company_id, quarter)) or variable pay records/hold ledger rows (child data of a
    # quarter) — none of these is a document anybody cites by a minted number.
    # ── Phase PIP-1 ──
    "pip": ("PIP", True, 3),   # PIP-2026-001
    # ── Phase LETTER-1 ──
    "letter": ("LTR", True, 3),   # LTR-2026-001
    # ── Phase ORIENT-1 ── no sequence for the ASSIGNMENT: it is addressed by employee_code,
    # one per employee, the same "no business id for a per-employee child row" convention
    # leave balances and salary structures already use.
    "orientation_plan": ("ORP", True, 3),   # ORP-2026-001
}


def format_business_id(kind: str, seq: int, year: Optional[int] = None) -> str:
    """Render a business id from its sequence number. Pure — no DB, no clock.

    The caller supplies `year` (and the atomic sequence) so this stays testable and
    free of hidden time dependencies, matching the payroll engine's discipline.
    """
    if kind not in ID_FORMATS:
        raise ValueError(f"Unknown business id kind: {kind}")
    prefix, year_scoped, pad = ID_FORMATS[kind]
    if year_scoped:
        if year is None:
            raise ValueError(f"Business id kind '{kind}' is year-scoped; `year` is required")
        return f"{prefix}-{year}-{str(seq).zfill(pad)}"
    return f"{prefix}-{str(seq).zfill(pad)}"


def counter_key(kind: str, company_id: str, year: Optional[int] = None) -> str:
    """The `_id` of the atomic counter document backing a business-id sequence.

    Scoped per company so two companies never share a sequence — a client must not be
    able to infer another client's hiring volume from gaps in their own numbering.
    """
    if kind not in ID_FORMATS:
        raise ValueError(f"Unknown business id kind: {kind}")
    _, year_scoped, _ = ID_FORMATS[kind]
    if year_scoped:
        if year is None:
            raise ValueError(f"Business id kind '{kind}' is year-scoped; `year` is required")
        return f"{company_id}:{kind}:{year}"
    return f"{company_id}:{kind}"


# ─────────────────────────────────────────────────────────────
# API models
# ─────────────────────────────────────────────────────────────
class HrmsHealthResponse(BaseModel):
    """GET /hrms/health — what the client needs to render the module shell.

    Returning the caller's resolved role + capability list here means the frontend
    never re-derives permissions from raw role strings, which is how the source ended
    up rendering buttons the API then refused (FRONTEND_ANALYSIS §5).
    """
    module: str = "hrms"
    enabled: bool
    role: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    company_id: Optional[str] = None
    is_internal: bool = False



class AuditEntry(BaseModel):
    """One row of the HRMS audit trail."""
    actor_id: Optional[str] = None
    actor_name: Optional[str] = None
    action: str
    entity: str
    entity_id: Optional[str] = None
    detail: Optional[str] = None
    company_id: Optional[str] = None


# =============================================================
# Phase 2 - Employee master, departments, designations
# =============================================================

# ── Enumerations ──
class EmploymentStatus(str, Enum):
    ACTIVE     = "Active"
    ON_NOTICE  = "On Notice"
    RESIGNED   = "Resigned"
    TERMINATED = "Terminated"
    ON_LEAVE   = "On Long Leave"


class EmploymentType(str, Enum):
    FULL_TIME = "Full-time"
    PART_TIME = "Part-time"
    CONTRACT  = "Contract"
    INTERN    = "Intern"
    CONSULTANT = "Consultant"


class Gender(str, Enum):
    MALE   = "Male"
    FEMALE = "Female"
    OTHER  = "Other"


# Statuses that mean "still on the payroll". Phase 14 payroll runs over exactly this set,
# which is why it lives here rather than being re-derived per caller.
PAYABLE_STATUSES = {EmploymentStatus.ACTIVE, EmploymentStatus.ON_NOTICE, EmploymentStatus.ON_LEAVE}

AUDIT_EMPLOYEE_CREATED   = "employee profile created"
AUDIT_EMPLOYEE_UPDATED   = "employee profile updated"
AUDIT_SALARY_CHANGED     = "employee salary changed"
AUDIT_DEPARTMENT_CREATED = "department created"
AUDIT_DEPARTMENT_UPDATED = "department updated"
AUDIT_DEPARTMENT_DELETED = "department deleted"
AUDIT_DESIGNATION_CREATED = "designation created"
AUDIT_DESIGNATION_UPDATED = "designation updated"
AUDIT_DESIGNATION_DELETED = "designation deleted"

ENTITY_DEPARTMENT  = "department"
ENTITY_DESIGNATION = "designation"


# ── Field formats ──
# Validated server-side. The source HRMS checked identity documents in the browser only
# (BACKEND_ANALYSIS §8: "PAN-or-Aadhaar ... not enforced server-side"), so malformed PII
# reached the database. These patterns close that gap for every write path.
import re as _re

PAN_RE     = _re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
AADHAAR_RE = _re.compile(r"^\d{12}$")
IFSC_RE    = _re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
UAN_RE     = _re.compile(r"^\d{12}$")
DATE_RE    = _re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_iso_date(value: str) -> bool:
    """True for a well-formed, real 'YYYY-MM-DD' date.

    Dates are handled as plain strings throughout HRMS (matching the ERP's holiday_date /
    joining_date convention) and are compared lexically, which is correct for ISO dates and
    immune to server-timezone drift.
    """
    if not value or not DATE_RE.match(value):
        return False
    try:
        from datetime import date
        y, m, d = (int(p) for p in value.split("-"))
        date(y, m, d)          # rejects 2026-02-30 and friends
        return True
    except (ValueError, TypeError):
        return False


# ── Seniority bands (Phase INT-2) ──
# The vocabulary the Internal Recruitment SOP states its interview rules in: who must sit on
# a panel (§5) and which roles need a final Management round before an offer (§5).
#
# Four values, deliberately closed. "Senior" and "managerial" differ in kind rather than
# degree -- a senior individual contributor and a manager need the same panel but are not the
# same thing -- so collapsing them would lose a distinction the org chart cares about even
# though these two rules happen to treat them alike.
class DesignationLevel(str, Enum):
    JUNIOR     = "junior"
    MID        = "mid"
    SENIOR     = "senior"
    MANAGERIAL = "managerial"


# The DEFAULT for a designation that has never been banded. `mid` rather than `junior`,
# because the whole point is that existing rows stay valid AND keep a real panel requirement:
# defaulting to junior would be the same table but would read as a deliberate "this is a
# junior role", which nobody decided.
DEFAULT_DESIGNATION_LEVEL = DesignationLevel.MID

# Levels the SOP treats as "managerial and above": a mandatory Management final round before
# the offer stage, and Management on the interview panel. Named once so the final-round gate
# and the panel table cannot disagree about which roles they cover.
MANAGERIAL_LEVELS = {DesignationLevel.SENIOR, DesignationLevel.MANAGERIAL}


def designation_level(designation: Optional[dict]) -> DesignationLevel:
    """The seniority band of a designation row. Pure -- no DB, no clock.

    An absent, empty or unrecognised value reads as the default rather than raising: a
    designation created before this phase has no band, and refusing to schedule an interview
    because of that would break hiring to enforce a field nobody has filled in yet.
    """
    raw = (designation or {}).get("designation_level")
    try:
        return DesignationLevel(raw)
    except (ValueError, TypeError):
        return DEFAULT_DESIGNATION_LEVEL


def is_managerial_level(level) -> bool:
    """Whether a seniority band counts as managerial-and-above for the SOP's §5 rules."""
    try:
        return DesignationLevel(getattr(level, "value", level)) in MANAGERIAL_LEVELS
    except (ValueError, TypeError):
        return False


# ── API models ──
class DepartmentIn(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    head_user_id: Optional[str] = None
    active: bool = True


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    head_user_id: Optional[str] = None
    active: Optional[bool] = None


class DesignationIn(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    level: Optional[int] = None          # optional grade/band, ascending seniority
    active: bool = True
    # ── Phase INT-2 ── the SENIORITY BAND, which is what the SOP's panel-composition and
    # final-round rules are stated in terms of (SOP §5). Deliberately NOT folded into
    # `level` above: that field is an integer grade a company numbers however it likes, and
    # overloading it with four fixed strings would break every row that already has one.
    # Absent reads as `mid` -- see designation_level().
    designation_level: Optional[DesignationLevel] = None


class DesignationUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    level: Optional[int] = None
    active: Optional[bool] = None
    designation_level: Optional[DesignationLevel] = None


class EmployeeProfileIn(BaseModel):
    """Create an employee profile for an EXISTING user.

    `user_id` is the join key to staff/learners. There is deliberately no name/email here:
    identity lives in the user collections and is never duplicated, so a rename can never
    desynchronise the two (BACKEND_ANALYSIS Risk #4).
    """
    user_id: str
    employee_code: Optional[str] = None          # auto-minted when omitted
    department_id: Optional[str] = None
    designation_id: Optional[str] = None
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    gender: Optional[Gender] = None
    date_of_birth: Optional[str] = None          # YYYY-MM-DD
    joined_on: Optional[str] = None              # YYYY-MM-DD
    resigned_on: Optional[str] = None            # YYYY-MM-DD
    base_salary: Optional[float] = None          # monthly; gated by employee.salary.*
    # Statutory
    pan: Optional[str] = None
    aadhaar: Optional[str] = None
    uan: Optional[str] = None
    pf_number: Optional[str] = None
    esi_number: Optional[str] = None
    # Bank
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    bank_ifsc: Optional[str] = None
    # Personal
    blood_group: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relation: Optional[str] = None


class EmployeeProfileUpdate(BaseModel):
    """Every field optional. `user_id` is intentionally absent — a profile can never be
    re-pointed at a different person; delete and recreate instead."""
    employee_code: Optional[str] = None
    department_id: Optional[str] = None
    designation_id: Optional[str] = None
    employment_status: Optional[EmploymentStatus] = None
    employment_type: Optional[EmploymentType] = None
    gender: Optional[Gender] = None
    date_of_birth: Optional[str] = None
    joined_on: Optional[str] = None
    resigned_on: Optional[str] = None
    base_salary: Optional[float] = None
    pan: Optional[str] = None
    aadhaar: Optional[str] = None
    uan: Optional[str] = None
    pf_number: Optional[str] = None
    esi_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    bank_ifsc: Optional[str] = None
    blood_group: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relation: Optional[str] = None


# =============================================================
# Phase 3 - Requisitions (FMS) + Job Descriptions
# =============================================================

# The discriminator stored on every requisition, and copied onto the records that hang
# off one. HRMS hires for Sparsh Magic only, so every requisition raised is "internal". The
# value is still STORED because rows from the decommissioned client-hiring track remain in
# the database (some carry "client", the oldest carry no field at all): every hiring read
# filters on this, which is what keeps those legacy rows out of the flow without touching
# them.
REQUISITION_TRACK_INTERNAL = "internal"

# Application statuses that only the decommissioned client-hiring track could produce.
# They are no longer members of AppStatus -- nothing can move a candidate into one -- but
# legacy candidates still carry them, so the pipeline reads exclude them by value.
LEGACY_CLIENT_TRACK_STATUSES = ("Shared with Client", "Client Shortlisted", "Client Rejected")


class ReqApproval(str, Enum):
    """The approval machine. A requisition and its JD move through ONE unified chain -- the
    source's separate JD approval was removed and the JD is co-approved at the last stage
    (BACKEND_ANALYSIS 6.7):

      Pending HR Verification -> Pending Budget Approval -> [Pending Escalation]
      -> Pending Scorecard Approval -> Approved

    A MANDATORY budget gate sits before anything may be sourced (SOP §11), and the chain
    ends on the position scorecard rather than a single sign-off.
    """
    # Phase 11-R, Item 7: an OVER-SANCTION requisition is routed through the raiser's
    # reporting line before it reaches the scorecard gate. An in-sanction requisition never
    # enters this state.
    PENDING_ESCALATION = "Pending Escalation"
    APPROVED   = "Approved"
    REJECTED   = "Rejected"
    # Named "Verification" rather than "Review" because the SOP's step is a check that the
    # requisition is complete and justified, not the headcount judgement -- that is the next
    # state, and it is Management's.
    PENDING_HR_VERIFICATION = "Pending HR Verification"
    PENDING_BUDGET          = "Pending Budget Approval"
    PENDING_SCORECARD       = "Pending Scorecard Approval"


# Approval states in which a requisition has NOT yet cleared its budget gate.
# Sourcing of any kind -- publishing a posting, creating a candidate -- is refused while a
# requisition sits in one of these. Declared once here so the posting service and the
# candidate service cannot drift apart on what "before budget approval" means.
PRE_BUDGET_STATES = {
    ReqApproval.PENDING_HR_VERIFICATION.value,
    ReqApproval.PENDING_BUDGET.value,
}


class ReqClosing(str, Enum):
    OPEN   = "Open"
    HIRED  = "Hired"
    CLOSED = "Closed"
    HOLD   = "Hold"
    CANCEL = "Cancel"


class JdStatus(str, Enum):
    DRAFT            = "Draft"
    PENDING_APPROVAL = "Pending Approval"
    APPROVED         = "Approved"
    REJECTED         = "Rejected"


class Urgency(str, Enum):
    HIGH   = "High"
    MEDIUM = "Medium"
    LOW    = "Low"


class WorkLocation(str, Enum):
    OFFICE  = "Office"
    FACTORY = "Factory"
    REMOTE  = "Remote"
    HYBRID  = "Hybrid"


class GenderPreference(str, Enum):
    ANY    = "Any"
    MALE   = "Male"
    FEMALE = "Female"


# -- The state machine, declared as data -----------------------------------------
# Encoding transitions as a table rather than a chain of ifs means the guard, the tests and
# the documentation all read from one source. An action absent from this table simply
# cannot happen, and adding a stage later is a data change rather than new control flow.
#   action -> (required_status, resulting_status, capability, remark_required)
#
# The chain differs from a plain HR -> MD sign-off in two ways the SOP requires:
#   * a MANDATORY budget gate before anything may be sourced (SOP §11), and
#   * it ends on the position SCORECARD rather than a single MD sign-off, because
#     Annexure B makes the HOD accountable for the scorecard and Management accountable
#     for the budget -- two different people, two different gates.
#
# The over-sanction detour hangs off `budget-approve`: there is no point asking a
# reporting line to justify extra headcount before anyone has agreed to pay for it.
INTERNAL_REQ_TRANSITIONS = {
    "hr-verify":         (ReqApproval.PENDING_HR_VERIFICATION, ReqApproval.PENDING_BUDGET,
                          Cap.REQUISITION_REVIEW_HR, False),
    "hr-reject":         (ReqApproval.PENDING_HR_VERIFICATION, ReqApproval.REJECTED,
                          Cap.REQUISITION_REVIEW_HR, True),
    "budget-approve":    (ReqApproval.PENDING_BUDGET, ReqApproval.PENDING_SCORECARD,
                          Cap.REQUISITION_APPROVE_BUDGET, False),
    "budget-reject":     (ReqApproval.PENDING_BUDGET, ReqApproval.REJECTED,
                          Cap.REQUISITION_APPROVE_BUDGET, True),
    # The escalation ladder returns to the scorecard gate once exhausted.
    "escalate-approve":  (ReqApproval.PENDING_ESCALATION, ReqApproval.PENDING_SCORECARD,
                          Cap.REQUISITION_ESCALATE, False),
    "escalate-reject":   (ReqApproval.PENDING_ESCALATION, ReqApproval.REJECTED,
                          Cap.REQUISITION_ESCALATE, True),
    "scorecard-approve": (ReqApproval.PENDING_SCORECARD, ReqApproval.APPROVED,
                          Cap.SCORECARD_APPROVE, False),
    "scorecard-reject":  (ReqApproval.PENDING_SCORECARD, ReqApproval.REJECTED,
                          Cap.SCORECARD_APPROVE, True),
}

INTERNAL_ESCALATION_ROUTING = {"budget-approve": ReqApproval.PENDING_ESCALATION}

def budget_approval_is_mandatory() -> bool:
    """Budget approval cannot be skipped, asserted from the table rather than trusted.

    "No internal role may be sourced without prior written headcount and budget approval"
    (SOP §11) holds exactly while: PENDING_BUDGET is on the ONLY road out of HR verification,
    the single action that leaves it forward demands REQUISITION_APPROVE_BUDGET, and APPROVED
    is unreachable without passing through it.

    A later shortcut -- an `hr-verify` that lands straight on PENDING_SCORECARD, say -- would
    silently delete the gate. This is what the test asserts, so that change fails loudly.
    """
    forward = [spec for action, spec in INTERNAL_REQ_TRANSITIONS.items()
               if spec[0] is ReqApproval.PENDING_BUDGET
               and spec[1] is not ReqApproval.REJECTED]
    if not (len(forward) == 1 and forward[0][2] is Cap.REQUISITION_APPROVE_BUDGET):
        return False
    # Nothing may reach APPROVED except through the scorecard gate, which itself is only
    # reachable from the budget gate or the escalation ladder that follows it.
    approved_from = {spec[0] for spec in INTERNAL_REQ_TRANSITIONS.values()
                     if spec[1] is ReqApproval.APPROVED}
    if approved_from != {ReqApproval.PENDING_SCORECARD}:
        return False
    scorecard_from = {spec[0] for spec in INTERNAL_REQ_TRANSITIONS.values()
                      if spec[1] is ReqApproval.PENDING_SCORECARD}
    return scorecard_from == {ReqApproval.PENDING_BUDGET, ReqApproval.PENDING_ESCALATION}

# The escalation ladder is capped. A cyclic or absurdly deep reporting chain must not turn
# one requisition into a twenty-step approval marathon.
MAX_ESCALATION_LEVELS = 5


class EscalationStatus(str, Enum):
    PENDING  = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


AUDIT_REQ_CREATED     = "requisition raised"
AUDIT_REQ_UPDATED     = "requisition updated"
AUDIT_REQ_DELETED     = "requisition deleted"
AUDIT_REQ_HR_REJECTED = "requisition rejected (HR)"
AUDIT_REQ_CLOSED      = "requisition closing status changed"
AUDIT_JD_UPDATED      = "job description updated"

# action -> audit label, so the trail cannot drift from the transition table.
AUDIT_REQ_ESCALATED   = "requisition escalated (over-sanction)"
AUDIT_REQ_ESC_APPROVED = "requisition approved (escalation)"
AUDIT_REQ_ESC_REJECTED = "requisition rejected (escalation)"

AUDIT_REQ_HR_VERIFIED  = "requisition HR-verified (internal)"
AUDIT_REQ_BUDGET_OK    = "requisition budget approved (internal)"
AUDIT_REQ_BUDGET_NO    = "requisition rejected at budget (internal)"
AUDIT_REQ_SCORECARD_OK = "requisition scorecard approved (internal)"
AUDIT_REQ_SCORECARD_NO = "requisition rejected at scorecard (internal)"

REQ_AUDIT_ACTIONS = {
    "hr-reject":  AUDIT_REQ_HR_REJECTED,
    "escalate-approve": AUDIT_REQ_ESC_APPROVED,
    "escalate-reject":  AUDIT_REQ_ESC_REJECTED,
    "hr-verify":         AUDIT_REQ_HR_VERIFIED,
    "budget-approve":    AUDIT_REQ_BUDGET_OK,
    "budget-reject":     AUDIT_REQ_BUDGET_NO,
    "scorecard-approve": AUDIT_REQ_SCORECARD_OK,
    "scorecard-reject":  AUDIT_REQ_SCORECARD_NO,
}

ENTITY_JD = "job_description"


# =============================================================
# Phase 11-R, Item 6 - dual budget capture
# =============================================================
# How far the two figures may differ and still count as agreeing. Zero by default: a
# requisition's budget is an exact number somebody signed off, not an estimate. It is a
# named constant rather than a literal `==` so a client who works in thousands can widen it
# in one reviewable place.
BUDGET_TOLERANCE = 0.0


class BudgetStatus(str, Enum):
    NOT_SET  = "Not Set"    # neither figure captured
    PENDING  = "Pending"    # one side has answered, the other has not
    MATCHED  = "Matched"
    MISMATCH = "Mismatch"


def budget_status(req: dict) -> str:
    """The budget state of a requisition, DERIVED on every read and never stored.

    A stored flag would go stale the moment somebody corrects a figure, and the correction
    is exactly the case that matters. Tolerates documents written before this phase: both
    fields absent reads as `Not Set`, which is the truth about them.
    """
    req = req or {}
    sanctioned = req.get("budget_sanctioned_amount")
    hod = req.get("budget_hod_amount")
    if sanctioned is None and hod is None:
        return BudgetStatus.NOT_SET.value
    if sanctioned is None or hod is None:
        return BudgetStatus.PENDING.value
    try:
        delta = abs(float(sanctioned) - float(hod))
    except (TypeError, ValueError):
        # Unreadable figures are not silently "Matched" -- they are a disagreement we
        # cannot resolve, which is what Mismatch means.
        return BudgetStatus.MISMATCH.value
    return (BudgetStatus.MATCHED.value if delta <= BUDGET_TOLERANCE
            else BudgetStatus.MISMATCH.value)


def budget_delta(req: dict):
    """Signed difference (HOD-approved minus management-sanctioned), or None."""
    try:
        return float(req.get("budget_hod_amount")) - float(req.get("budget_sanctioned_amount"))
    except (TypeError, ValueError):
        return None


# Actions that require remarks CONDITIONALLY, on top of the flat `remark_required` slot in
# INTERNAL_REQ_TRANSITIONS. Declared here so the whole "when must an approver explain themselves"
# rule is readable in one place rather than scattered through the handler.
#
# The rule (confirmed with the business, see PHASE_11R_REPORT §Decisions): a budget mismatch
# WARNS and notifies, it does not block. But an MD who approves a requisition whose two
# budget figures disagree must say why -- an unexplained approval over a known disagreement
# is exactly the record an audit later needs.
REQ_CONDITIONAL_REMARKS = {
    "budget-approve": lambda req: budget_status(req) == BudgetStatus.MISMATCH.value,
}

REQ_CONDITIONAL_REMARK_REASONS = {
    "budget-approve": ("The sanctioned and HOD-approved budgets do not match. "
                       "Record a remark explaining the approval."),
}


class RequisitionType(str, Enum):
    NEW_POSITION = "New Position"
    REPLACEMENT  = "Replacement"


# -- API models --
class JobDescriptionIn(BaseModel):
    """The JD authored WITH its requisition.

    Mandatory content is `responsibilities` OR at least one attachment -- enforced in the
    service, because it is a cross-field rule Pydantic cannot express cleanly.
    """
    title: Optional[str] = None          # defaults to the designation name
    # Every field below that has a counterpart on the requisition INHERITS it when left
    # blank -- see hrms_requisition_service.JD_FROM_REQUISITION. The form asks for these
    # facts once, on the requisition; a JD that wants its own wording overrides them here.
    responsibilities: Optional[str] = None
    skills: Optional[str] = None
    qualifications: Optional[str] = None
    experience: Optional[str] = None
    ctc: Optional[str] = None
    location: Optional[str] = None
    benefits: Optional[str] = None
    # ── Internal Recruitment SOP §3 — Step 3 (Job Description / Position Scorecard) ──
    # Authored by HR once headcount and budget clear, not by the HOD at raise time.
    job_summary: Optional[str] = None          # a short overview, distinct from the
                                                # line-by-line Key Responsibilities
    key_competencies: Optional[str] = None
    culture_fit: Optional[str] = None          # "Culture-Fit Expectations"
    additional_requirements: Optional[str] = None
    # None rather than FULL_TIME so "the caller said nothing" stays distinguishable from
    # "the caller chose full-time". Defaulting here silently published every Contract and
    # Intern requisition as Full-time, because the JD default outranked the requisition's
    # own answer and nothing downstream looked past it.
    employment_type: Optional[EmploymentType] = None
    attachments: List[dict] = Field(default_factory=list)   # [{name, url}]


class JobDescriptionUpdate(BaseModel):
    title: Optional[str] = None
    responsibilities: Optional[str] = None
    skills: Optional[str] = None
    qualifications: Optional[str] = None
    experience: Optional[str] = None
    ctc: Optional[str] = None
    location: Optional[str] = None
    benefits: Optional[str] = None
    job_summary: Optional[str] = None
    key_competencies: Optional[str] = None
    culture_fit: Optional[str] = None
    additional_requirements: Optional[str] = None
    employment_type: Optional[EmploymentType] = None
    attachments: Optional[List[dict]] = None


class RequisitionIn(BaseModel):
    """Raise a hiring requisition together with its job description.

    `department_id` and `designation_id` are REFERENCES to the Phase 2 masters, not free
    text. That is the point of building those masters: the source had a hard-coded
    department dropdown that disagreed with a second hard-coded dropdown on the same screen,
    and free-text designations (FRONTEND_ANALYSIS 6.2, 15).
    """
    department_id: str
    designation_id: str
    vacancy: int = 1
    experience_required: str
    qualification: str
    essential_skills: str
    required_date: str                    # YYYY-MM-DD
    # ── Internal Recruitment SOP §3 ── "the HOD raises a requisition specifying role,
    # reporting line, and business justification." Reporting line names WHO THE NEW HIRE
    # WILL REPORT TO -- a user of this company, same validation as replacement_for_user_id
    # below -- and is distinct from `assignee_id` (who RUNS the recruitment). Justification
    # is the HOD's own stated reason; both are required going forward, but Optional here so
    # a pre-SOP-redesign requisition (with neither) still deserialises.
    reporting_manager_id: Optional[str] = None
    reporting_manager_name: Optional[str] = None       # denormalised label
    business_justification: Optional[str] = None
    # No longer collected at raise time (removed from every requisition-raising form) -- a
    # requisition left unassigned is not incomplete; see create_requisition's own note.
    assignee_id: Optional[str] = None     # who will run the recruitment, once named
    offering_ctc: Optional[float] = None
    urgency_level: Urgency = Urgency.MEDIUM
    work_location: WorkLocation = WorkLocation.OFFICE
    gender_preferred: GenderPreference = GenderPreference.ANY
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    notes: Optional[str] = None
    # ── Internal Recruitment SOP §3 ── on the internal track, the JD is no longer authored
    # here -- it is HR's job, once Management/Finance has cleared headcount and budget (Step
    # 3, see hrms_requisition_service.create_jd). Optional so the raise form can stop asking
    # for it; still accepted for backward compatibility with the client track and any caller
    # that wants to seed content at raise time.
    jd: Optional[JobDescriptionIn] = None

    # ── Phase 11-R, Item 6 ── dual budget capture. All optional; omitting both preserves
    # the pre-phase behaviour exactly (budget_status reads "Not Set").
    budget_sanctioned_amount: Optional[float] = None   # sanctioned by management
    budget_sanctioned_by: Optional[str] = None         # user_id
    budget_sanctioned_ref: Optional[str] = None        # approval reference / note
    budget_sanctioned_on: Optional[str] = None         # YYYY-MM-DD
    budget_hod_amount: Optional[float] = None          # approved by the HOD
    budget_hod_by: Optional[str] = None
    budget_hod_on: Optional[str] = None
    budget_remarks: Optional[str] = None

    # ── Phase 11-R, Item 7 ── replacement vs a genuinely new position.
    requisition_type: RequisitionType = RequisitionType.NEW_POSITION
    replacement_for_user_id: Optional[str] = None      # required when Replacement
    replacement_for_name: Optional[str] = None         # denormalised label
    replacement_reason: Optional[str] = None           # required when Replacement
    last_working_day: Optional[str] = None             # YYYY-MM-DD


class RequisitionUpdate(BaseModel):
    """Edit requisition details. Approval fields are deliberately absent -- they change only
    through the /approve endpoint, so the state machine stays the single writer."""
    department_id: Optional[str] = None
    designation_id: Optional[str] = None
    vacancy: Optional[int] = None
    experience_required: Optional[str] = None
    qualification: Optional[str] = None
    essential_skills: Optional[str] = None
    required_date: Optional[str] = None
    reporting_manager_id: Optional[str] = None
    reporting_manager_name: Optional[str] = None
    business_justification: Optional[str] = None
    assignee_id: Optional[str] = None
    offering_ctc: Optional[float] = None
    urgency_level: Optional[Urgency] = None
    work_location: Optional[WorkLocation] = None
    gender_preferred: Optional[GenderPreference] = None
    employment_type: Optional[EmploymentType] = None
    notes: Optional[str] = None

    # ── Phase 11-R ── same additions as RequisitionIn, all optional.
    budget_sanctioned_amount: Optional[float] = None
    budget_sanctioned_by: Optional[str] = None
    budget_sanctioned_ref: Optional[str] = None
    budget_sanctioned_on: Optional[str] = None
    budget_hod_amount: Optional[float] = None
    budget_hod_by: Optional[str] = None
    budget_hod_on: Optional[str] = None
    budget_remarks: Optional[str] = None
    requisition_type: Optional[RequisitionType] = None
    replacement_for_user_id: Optional[str] = None
    replacement_for_name: Optional[str] = None
    replacement_reason: Optional[str] = None
    last_working_day: Optional[str] = None


class RequisitionAction(BaseModel):
    action: str                            # one of INTERNAL_REQ_TRANSITIONS
    remarks: Optional[str] = None
    salary_change: Optional[float] = None  # MD may revise the offered CTC on approval
    # ── Internal track ── required by `budget-approve` and ignored by every other action.
    # Carried on the same body rather than on a parallel endpoint so the approval chain stays
    # ONE surface, which is what keeps the UI's ApprovalDialog reusable across both tracks.
    approved_headcount: Optional[int] = None
    approved_salary_band_min: Optional[float] = None
    approved_salary_band_max: Optional[float] = None


class RequisitionClose(BaseModel):
    status: ReqClosing


# =============================================================
# Phase 4 - Job Postings + Public Application Intake
# =============================================================

class ApplyLinkMode(str, Enum):
    """Where a posting sends applicants.

    AUTO     -> the built-in public form at /apply/<posting_code>; the application lands in
                the pipeline automatically.
    EXTERNAL -> the poster's own destination (a job board listing, a Google Form, ...).
                Applications made there NEVER enter this pipeline -- nothing writes them
                back. The UI must say so plainly rather than implying tracking it cannot do.
    """
    AUTO     = "auto"
    EXTERNAL = "external"


class LiveStatus(str, Enum):
    # ── Internal Recruitment SOP — Step 4 ── Create Job Posting -> Select Sourcing Channels
    # -> Publish are three distinct moments, not one atomic action, so a posting now opens
    # as a DRAFT rather than going live at creation. PENDING_APPROVAL exists only for a
    # posting that names Executive Search among its channels (Management must clear it
    # before it can be published); every other posting skips straight from Draft to Live.
    DRAFT            = "Draft"
    PENDING_APPROVAL = "Pending Management Approval"
    LIVE    = "Live"
    PAUSED  = "Paused"
    EXPIRED = "Expired"
    CLOSED  = "Closed"


class RecruitmentChannel(str, Enum):
    """Where HR is sourcing this vacancy from — the Internal Recruitment SOP's own list.
    Independent of `ApplyLinkMode`/`source`: a channel is where HR chose to advertise it,
    `source` (on the candidate) is where the applicant says they actually found it."""
    INTERNAL_DATABASE   = "Internal Database"
    JOB_PORTALS         = "Job Portals"
    EMPLOYEE_REFERRALS  = "Employee Referrals"
    # The only channel with its own gate: SOP names it explicitly as needing Management's
    # sign-off, unlike the other three which any recruiter may select freely.
    EXECUTIVE_SEARCH    = "Executive Search"


# The master candidate lifecycle. Phase 4 only ever writes APPLIED; the rest are driven by
# Phases 5-9. Declared in full here so there is ONE list, not a growing set of string
# literals scattered across services (the source kept a modern status column AND legacy
# numbered step columns in parallel -- BACKEND_ANALYSIS Risk #7).
class AppStatus(str, Enum):
    APPLIED              = "Applied"
    UNDER_REVIEW         = "Under Review"
    SHORTLISTED          = "Shortlisted"
    ON_HOLD              = "On Hold"
    DUPLICATE            = "Duplicate"
    REJECTED             = "Rejected"
    # ── Phase INT-4 ── the SOP's step 5, "brief telephonic interview by HR", which sits
    # between CV screening and the panel. Two statuses rather than one, because the outcome
    # is the point: a phone screen nobody can see the result of is a call that may as well
    # not have happened.
    #
    # NOT a rejection reason on the candidate. TELEPHONIC_REJECTED is revivable (a candidate
    # who was unreachable on Tuesday is not permanently unsuitable), which a terminal
    # REJECTED is not.
    TELEPHONIC_PASSED    = "Telephonic Passed"
    TELEPHONIC_REJECTED  = "Telephonic Rejected"
    INTERVIEW_SCHEDULED  = "Interview Scheduled"
    ASSESSMENT_PENDING   = "Assessment Pending"
    ASSESSMENT_COMPLETED = "Assessment Completed"
    ASSESSMENT_PASSED    = "Assessment Passed"
    ASSESSMENT_FAILED    = "Assessment Failed"
    TECHNICAL_ROUND      = "Technical Round"
    MD_ROUND             = "MD Round"
    # -- Final Commit -- the committee agreed, and the role is managerial or above, so the
    # mandatory Management final round still stands between them and an offer. A status of
    # its own rather than an inference from "no passed MD Round yet": the people waiting on
    # a final interview are a group somebody has to chase, and a group nobody can list is a
    # group nobody chases.
    FINAL_INTERVIEW_REQUIRED = "Final Interview Required"
    SELECTED             = "Selected"
    OFFER_GENERATED      = "Offer Generated"
    OFFER_ACCEPTED       = "Offer Accepted"
    OFFER_DECLINED       = "Offer Declined"
    # ── Phase 11-R, Item 3 ── the appointment letter confirming joining terms has gone out.
    # OPTIONAL: the direct Offer Accepted -> Pre-Onboarding edge is kept, so a company that
    # does not issue appointment letters is never blocked by this stage existing.
    APPOINTMENT_LETTER_SENT = "Appointment Letter Sent"
    PRE_ONBOARDING       = "Pre-Onboarding"
    JOINED               = "Joined"
    EMPLOYEE_CREATED     = "Employee Created"
    # ── Phase INT-15 (SOP §7) ── the post-hire governance event. Confirmation of probation
    # is the last thing the internal track has an opinion about, and until now it lived only
    # on the employee record. It ranks 8 WITH `Employee Created` rather than opening a rank
    # 9: the funnel ends at hired, and a confirmation months later is not a ninth stage of
    # it. See POST_HIRE_STATUSES for why this edge does not un-terminalise the hire.
    PROBATION_CONFIRMED  = "Probation Confirmed"


# -- Upload limits (public surface) ----------------------------------------------
MAX_UPLOAD_BYTES = 15 * 1024 * 1024          # 15 MB, matching the source's ceiling
MAX_CERTIFICATES = 10

ALLOWED_UPLOAD_MIME = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg", "image/png", "image/webp",
}

# Posting codes are public identifiers: two letters, a dash, six upper-alnum characters.
POSTING_CODE_RE = _re.compile(r"^[A-Z]{2}-[A-Z0-9]{6}$")
EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Digits, spaces and the usual separators; 7-20 characters of actual digits.
PHONE_RE = _re.compile(r"^[0-9+\-() ]{7,25}$")

AUDIT_POSTING_CREATED       = "job posting created"
AUDIT_POSTING_PUBLISHED     = "job posting published"
AUDIT_POSTING_EXEC_APPROVED = "executive search approved"
AUDIT_POSTING_UPDATED = "job posting updated"
AUDIT_POSTING_DELETED = "job posting deleted"
AUDIT_APPLICATION     = "application received"

ENTITY_POSTING   = "job_posting"
ENTITY_CANDIDATE_APPLICATION = "candidate"


# -- API models --
class PostingIn(BaseModel):
    """Publish a JD. ONE posting, ONE link.

    There is deliberately no platform here. A posting used to be created once per job board,
    which meant one link per board and a `source` inferred from whichever URL the applicant
    happened to click -- an inference that was wrong the moment a link was forwarded. The
    single link is shared wherever the company likes, and the application form asks the
    applicant where they found the role. The answer is what fills `source`.
    """
    jd_no: str
    apply_link_mode: ApplyLinkMode = ApplyLinkMode.AUTO
    external_url: Optional[str] = None
    code: Optional[str] = None       # client-previewed code; honoured only if valid + unique
    expiry_date: Optional[str] = None          # YYYY-MM-DD ("Closing Date")
    notes: Optional[str] = None
    requires_assessment: bool = False
    # Internal Recruitment SOP -- Step 4: at least one sourcing channel must be named.
    channels: List[RecruitmentChannel] = Field(default_factory=list)


class PostingUpdate(BaseModel):
    live_status: Optional[LiveStatus] = None
    expiry_date: Optional[str] = None
    notes: Optional[str] = None
    apply_link_mode: Optional[ApplyLinkMode] = None
    external_url: Optional[str] = None
    requires_assessment: Optional[bool] = None
    channels: Optional[List[RecruitmentChannel]] = None


class PostingExecApprovalIn(BaseModel):
    """Management's own sign-off before an Executive Search posting may be published."""
    remarks: Optional[str] = None


class UploadIn(BaseModel):
    """A file arriving as base64 in a JSON body -- the public forms cannot use multipart
    without a token, so this is the ingest shape for every candidate-facing upload."""
    name: str
    mime_type: str
    data: str                                   # base64, optionally a data: URL
    # Which joining document this file answers (§7.5 Stage 3). Absent for every other
    # upload in the system -- a CV or a certificate has no catalogue to belong to.
    doc_type: Optional[str] = None


# =============================================================
# Phase 11-R, Item 5 - referral capture
# =============================================================
class ReferralSource(str, Enum):
    """Where an application came FROM, as the applicant (or the recruiter) reports it.

    Distinct from `RecruitmentChannel`, which is where HR chose to ADVERTISE the role: a
    posting advertised on Job Portals can still receive a walk-in. The four values added for
    the Applicant Pool -- Internal Database, Company Website, Direct Application, Executive
    Search -- close the gap between the two lists without renaming any existing value, so
    every candidate already filed under the old ones keeps its meaning and its place in the
    `source` breakdown.
    """
    EMPLOYEE           = "Employee"
    EX_EMPLOYEE        = "Ex-Employee"
    CONSULTANT_AGENCY  = "Consultant / Agency"
    JOB_PORTAL         = "Job Portal"
    SOCIAL_MEDIA       = "Social Media"
    WALK_IN            = "Walk-in"
    # "Client" was removed with the client-hiring track: it meant "the hiring client sent us
    # this CV", which has no meaning now every requisition is this company's own vacancy.
    # Candidates filed under it were re-filed as "Other".
    INTERNAL_DATABASE  = "Internal Database"
    COMPANY_WEBSITE    = "Company Website"
    DIRECT_APPLICATION = "Direct Application"
    EXECUTIVE_SEARCH   = "Executive Search"
    OTHER              = "Other"


# The `source` value a referred candidate is filed under, so referrals land in the existing
# Phase 10 `source` breakdown rather than needing a parallel one.
REFERRAL_SOURCE_LABEL = "Referral"

# Employee codes are EMP-<year>-<seq> (see ID_FORMATS). Validated as a shape BEFORE the
# lookup, exactly as posting and access codes are, so a crafted value never reaches Mongo.
EMPLOYEE_CODE_RE = _re.compile(r"^EMP-\d{4}-\d{3,}$")

# Deliberately vague, and identical for "no such code" and "belongs to another company".
# The public form must not become an employee-directory oracle -- the same discipline
# INVALID_LINK applies to posting codes.
INVALID_EMPLOYEE_CODE = "We could not verify that employee code."


class ReferralIn(BaseModel):
    """The referral block, shared by the public form and the manual-add path.

    Both intake paths capture the SAME thing: a referral entered by HR on a walk-in CV is
    worth exactly as much as one typed by the applicant, and reporting must not be able to
    tell them apart.
    """
    is_referral: bool = False
    referred_by: Optional[str] = None                # the referrer's name
    referral_source: Optional[ReferralSource] = None
    referrer_employee_code: Optional[str] = None     # e.g. EMP-2026-014
    referral_relation: Optional[str] = None


class PublicApplicationIn(BaseModel):
    """A candidate's application. Deliberately minimal and entirely untrusted."""
    candidate_name: str
    can_email: str
    can_contact: str
    declaration: bool = False
    current_location: Optional[str] = None
    total_experience: Optional[str] = None
    qualification: Optional[str] = None
    current_company: Optional[str] = None
    current_designation: Optional[str] = None
    current_ctc: Optional[str] = None
    expected_ctc: Optional[str] = None
    notice_period: Optional[str] = None
    linkedin: Optional[str] = None
    portfolio: Optional[str] = None
    cover_note: Optional[str] = None
    resume: Optional[UploadIn] = None
    photo: Optional[UploadIn] = None
    certificates: List[UploadIn] = Field(default_factory=list)
    # ── Phase 11-R, Item 5 ── "Were you referred?" Collapsed by default in the UI, and
    # entirely optional here: an application with no referral is unchanged by this phase.
    is_referral: bool = False
    referred_by: Optional[str] = None
    referral_source: Optional[ReferralSource] = None
    referrer_employee_code: Optional[str] = None
    referral_relation: Optional[str] = None

    # ── Phase INT-2 (SOP §11) ── the two acknowledgements the policy commits us to asking
    # for. BOTH are required on the internal track and stamped with a timestamp, because an
    # acknowledgement with no time on it cannot be tied to the wording that was shown. The
    # wording itself lives in hrms_comm_templates so legal can change it without a deploy.
    eeo_ack: bool = False
    data_use_ack: bool = False
    # ── Phase INT-2 (Annexure C talent pool) ── entirely optional, and OFF by default. A
    # candidate enters the pool only by ticking this; there is no path that opts them in
    # because somebody found their CV useful.
    consent_to_retain: bool = False


# =============================================================
# Phase 5 - Candidate pipeline, screening, journey
# =============================================================

# Stages a candidate can never leave. Reaching one of these ends the pipeline.
TERMINAL_STATUSES = {
    AppStatus.PROBATION_CONFIRMED, AppStatus.OFFER_DECLINED, AppStatus.DUPLICATE,
}

# ── Phase INT-15 ── Hired, but with one governance event still to come.
#
# `Employee Created` was terminal until this phase, and it very nearly had to stay that way.
# `allowed_next_statuses` grants ALWAYS_AVAILABLE to every non-terminal stage, so simply
# dropping it from TERMINAL_STATUSES to hang `Probation Confirmed` off it would also make
# Rejected, On Hold and Duplicate legal from a HIRED employee -- on the client track as much
# as this one, which is a lifecycle both tracks share.
#
# So a post-hire stage advances but is never parked or rejected. It is the narrowest change
# that satisfies the SOP without handing the client track three edges it never asked for.
POST_HIRE_STATUSES = {AppStatus.EMPLOYEE_CREATED}

# Available from ANY non-terminal stage. A recruiter must always be able to stop a pipeline
# or park it, whatever stage it has reached -- encoding those as per-stage edges would be
# noise, and forgetting one would trap a candidate.
ALWAYS_AVAILABLE = {AppStatus.REJECTED, AppStatus.ON_HOLD, AppStatus.DUPLICATE}

# The forward lifecycle. Only these edges advance a candidate.
#
# The source enforced NOTHING here -- any status could be set to any other, so a candidate
# could jump Applied -> Joined and skip every gate (assessment, interview, offer,
# onboarding), leaving downstream phases to reason about states that cannot legitimately
# exist. Declaring the graph makes an illegal move a 409 instead of silent corruption.
FORWARD_TRANSITIONS = {
    AppStatus.APPLIED:              {AppStatus.UNDER_REVIEW, AppStatus.SHORTLISTED},
    AppStatus.UNDER_REVIEW:         {AppStatus.SHORTLISTED},
    # Shortlisting routes by the role's assessment requirement -- the screening service
    # picks which of these two edges to take (see hrms_screening_service).
    # ── Phase INT-4 ── the telephonic edges are ADDED, not substituted. The direct
    # Shortlisted -> Assessment / Interview edges stay, so a role with an approved waiver is
    # never forced through a phone screen by the shape of the graph. The SOP's ordering is enforced by `assert_telephonic_cleared` at interview
    # scheduling, where it can be waived by an approved exception -- a missing edge cannot.
    AppStatus.SHORTLISTED:          {AppStatus.ASSESSMENT_PENDING, AppStatus.INTERVIEW_SCHEDULED,
                                     AppStatus.TELEPHONIC_PASSED,
                                     AppStatus.TELEPHONIC_REJECTED},
    # A passed phone screen leads where a shortlist does: the SOP puts the skill assessment
    # (Annexure B) between the call and the panel, so both onward edges exist.
    AppStatus.TELEPHONIC_PASSED:    {AppStatus.ASSESSMENT_PENDING, AppStatus.INTERVIEW_SCHEDULED},
    # Revivable, exactly like REJECTED: somebody unreachable on Tuesday is not
    # permanently unsuitable, and a dead end here would force HR to re-key the candidate.
    AppStatus.TELEPHONIC_REJECTED:  {AppStatus.UNDER_REVIEW},
    AppStatus.ASSESSMENT_PENDING:   {AppStatus.ASSESSMENT_COMPLETED},
    AppStatus.ASSESSMENT_COMPLETED: {AppStatus.ASSESSMENT_PASSED, AppStatus.ASSESSMENT_FAILED},
    AppStatus.ASSESSMENT_PASSED:    {AppStatus.INTERVIEW_SCHEDULED},
    # A failed assessment is not automatically a rejection -- HR may still park or reject it,
    # both of which come from ALWAYS_AVAILABLE.
    AppStatus.ASSESSMENT_FAILED:    set(),
    AppStatus.INTERVIEW_SCHEDULED:  {AppStatus.TECHNICAL_ROUND, AppStatus.MD_ROUND,
                                     AppStatus.FINAL_INTERVIEW_REQUIRED,
                                     AppStatus.SELECTED},
    AppStatus.TECHNICAL_ROUND:      {AppStatus.MD_ROUND,
                                     AppStatus.FINAL_INTERVIEW_REQUIRED,
                                     AppStatus.SELECTED},
    # Final Commit mandated the round; the candidate now sits in it, then is selected. The
    # direct edge to SELECTED is kept for the case where the round is already on record and
    # passed, which `final_commit_outcome` resolves to SELECTED rather than routing here.
    AppStatus.FINAL_INTERVIEW_REQUIRED: {AppStatus.MD_ROUND, AppStatus.SELECTED},
    AppStatus.MD_ROUND:             {AppStatus.SELECTED},
    AppStatus.SELECTED:             {AppStatus.OFFER_GENERATED},
    # SELECTED is the REVOKE walk-back: withdrawing an offer un-does the fact that one was
    # generated, returning the candidate to the pool so revised terms can be issued. Without
    # this edge a revoked candidate is stranded -- no live offer, yet unable to receive one.
    AppStatus.OFFER_GENERATED:      {AppStatus.OFFER_ACCEPTED, AppStatus.OFFER_DECLINED,
                                     AppStatus.SELECTED},
    # Both edges are kept deliberately. A company that issues appointment letters routes
    # through APPOINTMENT_LETTER_SENT; one that does not goes straight to onboarding as it
    # always has. Removing the direct edge would force a workflow on every existing client.
    AppStatus.OFFER_ACCEPTED:       {AppStatus.APPOINTMENT_LETTER_SENT,
                                     AppStatus.PRE_ONBOARDING},
    AppStatus.APPOINTMENT_LETTER_SENT: {AppStatus.PRE_ONBOARDING},
    AppStatus.PRE_ONBOARDING:       {AppStatus.JOINED},
    AppStatus.JOINED:               {AppStatus.EMPLOYEE_CREATED},
    # ── Phase INT-15 ── the only edge out of a hire, and only forwards.
    AppStatus.EMPLOYEE_CREATED:     {AppStatus.PROBATION_CONFIRMED},
    # Parked and rejected candidates can be revived -- a hold that cannot be lifted is a
    # dead end, and rejections are sometimes reversed.
    AppStatus.ON_HOLD:              {AppStatus.UNDER_REVIEW, AppStatus.SHORTLISTED},
    AppStatus.REJECTED:             {AppStatus.UNDER_REVIEW},
}


def allowed_next_statuses(current) -> set:
    """Every stage a candidate may legally move to from `current`."""
    current = AppStatus(current) if not isinstance(current, AppStatus) else current
    if current in TERMINAL_STATUSES:
        return set()
    if current in POST_HIRE_STATUSES:
        # Advance only. Somebody who has been hired is not a candidate any more and must
        # never be rejectable, parked or marked a duplicate -- see POST_HIRE_STATUSES.
        return set(FORWARD_TRANSITIONS.get(current, set()))
    return set(FORWARD_TRANSITIONS.get(current, set())) | (ALWAYS_AVAILABLE - {current})


def can_transition(current, target) -> bool:
    try:
        return AppStatus(target) in allowed_next_statuses(current)
    except ValueError:
        return False


# -- Pipeline grouping (the Kanban columns) --------------------------------------
# One declaration shared by the board, the stat tiles and the tests, so a stage can never
# be visible in one place and missing from another.
PIPELINE_COLUMNS = [
    ("applied",     "Applied",     [AppStatus.APPLIED, AppStatus.UNDER_REVIEW]),
    # TELEPHONIC_PASSED sits here, with the rest of rank 2: the board column and the funnel
    # rank must agree, or a candidate appears in one place and is counted in another.
    ("shortlisted", "Shortlisted", [AppStatus.SHORTLISTED, AppStatus.TELEPHONIC_PASSED]),
    ("assessment",  "Assessment",  [AppStatus.ASSESSMENT_PENDING, AppStatus.ASSESSMENT_COMPLETED,
                                    AppStatus.ASSESSMENT_PASSED, AppStatus.ASSESSMENT_FAILED]),
    ("interview",   "Interview",   [AppStatus.INTERVIEW_SCHEDULED, AppStatus.TECHNICAL_ROUND,
                                    AppStatus.MD_ROUND,
                                    AppStatus.FINAL_INTERVIEW_REQUIRED]),
    ("selected",    "Selected",    [AppStatus.SELECTED, AppStatus.OFFER_GENERATED,
                                    AppStatus.OFFER_ACCEPTED,
                                    AppStatus.APPOINTMENT_LETTER_SENT]),
    ("onboarding",  "Onboarding",  [AppStatus.PRE_ONBOARDING, AppStatus.JOINED,
                                    AppStatus.EMPLOYEE_CREATED,
                                    AppStatus.PROBATION_CONFIRMED]),
    ("hold",        "On Hold",     [AppStatus.ON_HOLD]),
    # TELEPHONIC_REJECTED groups with the other "declined at a stage" outcomes -- rank 2 in
    # the funnel, and it reads as a rejection here.
    ("rejected",    "Rejected",    [AppStatus.REJECTED, AppStatus.DUPLICATE,
                                    AppStatus.OFFER_DECLINED,
                                    AppStatus.TELEPHONIC_REJECTED]),
]


class ScreenAction(str, Enum):
    SHORTLIST = "shortlist"
    REVIEW    = "review"
    HOLD      = "hold"
    DUPLICATE = "duplicate"
    REJECT    = "reject"
    FORWARD   = "forward"


# action -> (target status or None, remark_required, recipient_required)
# `shortlist` has no fixed target: it resolves to Assessment Pending or straight to
# interview-ready depending on the role's assessment flag.
SCREEN_ACTIONS = {
    ScreenAction.SHORTLIST: (None, False, False),
    ScreenAction.REVIEW:    (AppStatus.UNDER_REVIEW, False, False),
    ScreenAction.HOLD:      (AppStatus.ON_HOLD, False, False),
    ScreenAction.DUPLICATE: (AppStatus.DUPLICATE, False, False),
    ScreenAction.REJECT:    (AppStatus.REJECTED, True, False),
    ScreenAction.FORWARD:   (None, False, True),
}

MAX_BULK_SCREEN = 200


class CvScreeningResult(str, Enum):
    """HR's verdict on the CV, judged against the approved Position Scorecard (SOP §1).

    Kept separate from `application_status`: the status says where the candidate IS, this
    says what HR CONCLUDED when they read the CV. A candidate can be "Shortlisted" with a
    `Meets` CV screen, or held at "Under Review" with a `Partially Meets` one — collapsing
    the two would lose the reason behind the move.
    """
    MEETS           = "Meets Requirements"
    PARTIALLY_MEETS = "Partially Meets"
    DOES_NOT_MEET   = "Does Not Meet"


class ScreeningStatus(str, Enum):
    """The overall HR screening verdict across CV, telephonic and assessment (SOP §1-§3)."""
    IN_PROGRESS = "In Progress"
    CLEARED     = "Cleared"
    ON_HOLD     = "On Hold"
    REJECTED    = "Rejected"


class CvScreeningIn(BaseModel):
    """Record the CV screening for ONE candidate, against the approved scorecard.

    Distinct from `ScreenIn`, which is the bulk triage that MOVES people. This records the
    finding; whether the candidate then moves is the triage action's job, so a screen can
    be written down before anybody decides what to do about it.
    """
    result: CvScreeningResult
    remarks: Optional[str] = None
    # HR's running note across the whole screening, and the overall verdict. Both optional:
    # the CV screen is usually the first of three, and a verdict on the whole is premature
    # until the later two are in.
    hr_remarks: Optional[str] = None
    screening_status: Optional[ScreeningStatus] = None

AUDIT_CANDIDATE_ADDED   = "candidate added"
AUDIT_CANDIDATE_UPDATED = "candidate updated"
AUDIT_CANDIDATE_DELETED = "candidate deleted"
AUDIT_STAGE_CHANGED     = "stage changed"
AUDIT_SCREENED          = "candidate screened"
AUDIT_ASSIGNED          = "candidate assigned"

# Colour keys the journey timeline renders by. Kept server-side so every consumer of the
# timeline agrees on what an event means.
JOURNEY_KINDS = {
    AUDIT_APPLICATION:       "applied",
    AUDIT_CANDIDATE_ADDED:   "applied",
    AUDIT_STAGE_CHANGED:     "info",
    AUDIT_SCREENED:          "info",
    AUDIT_ASSIGNED:          "info",
    AUDIT_CANDIDATE_UPDATED: "info",
}

# Statuses that colour a journey event regardless of which action produced it.
JOURNEY_STATUS_KINDS = {
    # ── Phase 11-R ──
    AppStatus.APPOINTMENT_LETTER_SENT: "offer",
    AppStatus.SHORTLISTED: "success", AppStatus.ASSESSMENT_PASSED: "success",
    AppStatus.SELECTED: "success", AppStatus.OFFER_ACCEPTED: "success",
    AppStatus.JOINED: "success", AppStatus.EMPLOYEE_CREATED: "success",
    AppStatus.PROBATION_CONFIRMED: "success",
    AppStatus.REJECTED: "reject", AppStatus.DUPLICATE: "reject",
    AppStatus.ASSESSMENT_FAILED: "reject", AppStatus.OFFER_DECLINED: "reject",
    AppStatus.ON_HOLD: "warning",
    AppStatus.INTERVIEW_SCHEDULED: "interview", AppStatus.TECHNICAL_ROUND: "interview",
    AppStatus.FINAL_INTERVIEW_REQUIRED: "interview",
    AppStatus.MD_ROUND: "interview",
    AppStatus.OFFER_GENERATED: "offer",
    AppStatus.PRE_ONBOARDING: "onboarding",
    AppStatus.ASSESSMENT_PENDING: "assessment", AppStatus.ASSESSMENT_COMPLETED: "assessment",
}

# The 7-step rail shown above the timeline: (label, statuses that mean it is reached).
JOURNEY_RAIL = [
    ("Applied",     {AppStatus.APPLIED, AppStatus.UNDER_REVIEW}),
    ("Shortlisted", {AppStatus.SHORTLISTED}),
    ("Assessment",  {AppStatus.ASSESSMENT_PENDING, AppStatus.ASSESSMENT_COMPLETED,
                     AppStatus.ASSESSMENT_PASSED, AppStatus.ASSESSMENT_FAILED}),
    ("Interview",   {AppStatus.INTERVIEW_SCHEDULED, AppStatus.TECHNICAL_ROUND,
                     AppStatus.MD_ROUND}),
    ("Selected",    {AppStatus.SELECTED}),
    # The rail stays 7 steps. The appointment letter joins the Offer step rather than
    # becoming an 8th: it is a second paper in the same "terms agreed" phase, and an 8th
    # step would re-flow a rail every existing screen renders. (Stated per Item 3 §2.)
    ("Offer",       {AppStatus.OFFER_GENERATED, AppStatus.OFFER_ACCEPTED,
                     AppStatus.APPOINTMENT_LETTER_SENT}),
    ("Hired",       {AppStatus.PRE_ONBOARDING, AppStatus.JOINED,
                     AppStatus.EMPLOYEE_CREATED, AppStatus.PROBATION_CONFIRMED}),
]


# -- API models --
class CandidateIn(BaseModel):
    """Manually add a candidate (walk-in, referral, agency CV)."""
    candidate_name: str
    can_email: Optional[str] = None
    can_contact: Optional[str] = None
    request_no: Optional[str] = None
    # Which published posting they came through, when there is one. A manually added
    # walk-in has no posting; an application typed in from a job board against a live
    # posting does, and the Applicant Pool wants that link kept.
    posting_code: Optional[str] = None
    source: str = "Manual"
    current_location: Optional[str] = None
    total_experience: Optional[str] = None
    qualification: Optional[str] = None
    current_company: Optional[str] = None
    current_designation: Optional[str] = None
    current_ctc: Optional[str] = None
    expected_ctc: Optional[str] = None
    notice_period: Optional[str] = None
    linkedin: Optional[str] = None
    portfolio: Optional[str] = None
    cover_note: Optional[str] = None
    resume: Optional[UploadIn] = None
    # ── Phase 11-R, Item 5 ── the manual-add path captures the same referral detail as the
    # public form. A referral typed in by HR must be as reportable as one self-declared.
    is_referral: bool = False
    referred_by: Optional[str] = None
    referral_source: Optional[ReferralSource] = None
    referrer_employee_code: Optional[str] = None
    referral_relation: Optional[str] = None


class CandidateUpdate(BaseModel):
    """Edit candidate details, or move their stage.

    `application_status` is accepted here but validated against FORWARD_TRANSITIONS -- it is
    not a free assignment.
    """
    candidate_name: Optional[str] = None
    can_email: Optional[str] = None
    can_contact: Optional[str] = None
    application_status: Optional[AppStatus] = None
    assigned_recruiter_id: Optional[str] = None
    current_location: Optional[str] = None
    total_experience: Optional[str] = None
    qualification: Optional[str] = None
    current_company: Optional[str] = None
    current_designation: Optional[str] = None
    current_ctc: Optional[str] = None
    expected_ctc: Optional[str] = None
    notice_period: Optional[str] = None
    linkedin: Optional[str] = None
    portfolio: Optional[str] = None
    cover_note: Optional[str] = None
    remarks: Optional[str] = None
    # Correctable: a CV that arrived by email and was filed as "Manual" is often later
    # found to have come from a portal or a referral, and the source breakdown is only
    # worth reading if it can be corrected.
    source: Optional[str] = None


class ScreenIn(BaseModel):
    uks: List[str]
    action: ScreenAction
    remarks: Optional[str] = None
    forward_to_id: Optional[str] = None
    # Phase 11-R, Item 4: who at the client the CV went to. Free text, not a user reference
    # — the client contact is a person at another organisation, not an ERP account.
    client_contact: Optional[str] = None


# =============================================================
# Phase 6 - Assessments + dual review
# =============================================================

class AssessmentStatus(str, Enum):
    """Assigned -> In Progress -> Submitted -> Reviewed.

    OPENED exists so HR can tell "the candidate has not looked at it" from "they opened it
    and went quiet" -- two situations that need different follow-up.
    """
    SENT      = "Sent"        # assigned, not yet opened
    OPENED    = "Opened"      # candidate has viewed it
    COMPLETED = "Completed"   # submitted, awaiting review
    REVIEWED  = "Reviewed"    # both reviewers have decided


class Decision(str, Enum):
    PASS = "Pass"
    FAIL = "Fail"


class Recommendation(str, Enum):
    RECOMMENDED     = "Recommended"
    BORDERLINE      = "Borderline"
    NOT_RECOMMENDED = "Not Recommended"


# Auto-recommendation thresholds, as a share of max_score. Advisory only -- it never decides
# the outcome, it just saves a reviewer doing the arithmetic. Both humans still choose.
RECOMMEND_THRESHOLD  = 0.70
BORDERLINE_THRESHOLD = 0.50


def recommendation_for(score, max_score) -> Optional[str]:
    """Derive the advisory recommendation from a score, or None when unscored."""
    try:
        score = float(score)
        max_score = float(max_score)
    except (TypeError, ValueError):
        return None
    if max_score <= 0:
        return None
    ratio = score / max_score
    if ratio >= RECOMMEND_THRESHOLD:
        return Recommendation.RECOMMENDED.value
    if ratio >= BORDERLINE_THRESHOLD:
        return Recommendation.BORDERLINE.value
    return Recommendation.NOT_RECOMMENDED.value


# Reviewer slots. A submission needs BOTH filled before it resolves -- unless the
# requisition has no identifiable hiring manager, in which case HR decides alone (see
# hrms_assessment_service). Two slots rather than one because "HR liked them and the hiring
# manager did not" is exactly the disagreement worth surfacing before an interview is booked.
SLOT_HR      = "hr"
SLOT_MANAGER = "manager"

MAX_ASSESSMENT_ATTACHMENTS = 10

AUDIT_ASSESSMENT_SENT      = "assessment sent"
AUDIT_ASSESSMENT_OPENED    = "assessment opened"
AUDIT_ASSESSMENT_SUBMITTED = "assessment submitted"
AUDIT_ASSESSMENT_REVIEWED  = "assessment reviewed"
AUDIT_ASSESSMENT_RESOLVED  = "assessment outcome"

ENTITY_ASSESSMENT = "assessment"

# Stages an assessment may be sent from. A candidate must be at the assessment stage --
# sending one to somebody already in interviews is a mistake, not a workflow.
ASSESSABLE_STATUSES = {
    AppStatus.SHORTLISTED, AppStatus.ASSESSMENT_PENDING,
    AppStatus.ASSESSMENT_COMPLETED, AppStatus.ASSESSMENT_FAILED,
}


# -- API models --
class AssessmentIn(BaseModel):
    uk: str
    title: str
    instructions: Optional[str] = None
    link: Optional[str] = None            # external test URL, if any
    max_score: float = 100
    due_date: Optional[str] = None        # YYYY-MM-DD


class AssessmentReviewIn(BaseModel):
    decision: Decision
    score: Optional[float] = None
    remarks: Optional[str] = None


class PublicAssessmentIn(BaseModel):
    """A candidate's assessment submission. Entirely untrusted, like every public input."""
    response: Optional[str] = None
    attachments: List[UploadIn] = Field(default_factory=list)


# =============================================================
# Phase 7 - Interviews + scorecard evaluation
# =============================================================

class InterviewRound(str, Enum):
    HR        = "HR Round"
    TECHNICAL = "Technical"
    MANAGER   = "Manager Round"
    MD        = "MD Round"


class InterviewMode(str, Enum):
    VIRTUAL = "Virtual"
    OFFLINE = "Offline"


class InterviewStatus(str, Enum):
    SCHEDULED = "Scheduled"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    NO_SHOW   = "No Show"


class Outcome(str, Enum):
    PASS = "Pass"
    FAIL = "Fail"
    HOLD = "Hold"


# The six competencies scored 0-5 on every scorecard. Declared once so the form, the
# average, the API and the tests cannot drift apart.
EVAL_COMPETENCIES = [
    ("technical",       "Technical Knowledge"),
    ("communication",   "Communication"),
    ("problem_solving", "Problem Solving"),
    ("behavior",        "Behaviour"),
    ("confidence",      "Confidence"),
    ("team_fit",        "Team Fit"),
]
COMPETENCY_KEYS = [k for k, _ in EVAL_COMPETENCIES]
MIN_SCORE, MAX_SCORE = 0, 5

# Where a candidate goes when a round is passed. Ported from BACKEND_ANALYSIS 6.3.
#
# Every edge below is already legal in the Phase 5 lifecycle graph, so this map decides
# INTENT and FORWARD_TRANSITIONS still decides LEGALITY -- two independent checks rather
# than one table trusted blindly.
PASS_NEXT = {
    InterviewRound.HR:        AppStatus.TECHNICAL_ROUND,
    InterviewRound.TECHNICAL: AppStatus.MD_ROUND,
    InterviewRound.MANAGER:   AppStatus.MD_ROUND,
    InterviewRound.MD:        AppStatus.SELECTED,
}

# Fail and Hold are round-independent.
OUTCOME_STATUS = {
    Outcome.FAIL: AppStatus.REJECTED,
    Outcome.HOLD: AppStatus.ON_HOLD,
}

# Scheduling is blocked while an assessment-required candidate has not cleared it. These are
# the stages that mean "not cleared". A candidate whose role needs no assessment is never
# measured against this list.
PRE_ASSESSMENT_STATUSES = {
    AppStatus.APPLIED, AppStatus.UNDER_REVIEW, AppStatus.SHORTLISTED,
    AppStatus.ASSESSMENT_PENDING, AppStatus.ASSESSMENT_COMPLETED,
    AppStatus.ASSESSMENT_FAILED, AppStatus.ON_HOLD,
}

MIN_DURATION_MIN = 15
DURATION_STEP_MIN = 15
DEFAULT_DURATION_MIN = 45

AUDIT_INTERVIEW_SCHEDULED   = "interview scheduled"
AUDIT_INTERVIEW_RESCHEDULED = "interview rescheduled"
AUDIT_INTERVIEW_UPDATED     = "interview updated"
AUDIT_INTERVIEW_CANCELLED   = "interview cancelled"
AUDIT_INTERVIEW_EVALUATED   = "interview evaluated"

ENTITY_INTERVIEW = "interview"


# -- API models --
class PanelMemberIn(BaseModel):
    """One person on an interview panel (Phase INT-2, SOP §5).

    Separate from `interviewer_id`, which stays exactly what it always was: the person who
    OWNS the booking, gets the invite and may score it. The panel is who else is in the room,
    and it is what the composition rule is checked against.
    """
    user_id: str
    # ── SOP §11 conflict of interest ── a member marked `recused` may not submit a scorecard
    # (422 in hrms_interview_service). Declaring a conflict is not itself disqualifying;
    # standing down is what removes it.
    coi_declared: bool = False
    coi_relationship: Optional[str] = None
    recused: bool = False


class InterviewIn(BaseModel):
    uk: str
    round: InterviewRound = InterviewRound.HR
    mode: InterviewMode = InterviewMode.VIRTUAL
    scheduled_at: str                       # ISO-8601 datetime
    duration_min: int = DEFAULT_DURATION_MIN
    interviewer_id: str
    meeting_link: Optional[str] = None      # required when mode is Virtual
    location: Optional[str] = None          # required when mode is Offline
    notes: Optional[str] = None
    # ── Phase INT-2 ── optional here and REQUIRED by the internal track's composition
    # check, which is where the 422 comes from. Optional in the model so a client-track
    # booking is byte-for-byte the call it always was.
    panel: List[PanelMemberIn] = Field(default_factory=list)


class InterviewUpdate(BaseModel):
    """Reschedule or change the status of an interview.

    Round, candidate and interviewer are deliberately absent: changing who is being
    interviewed, for what, would make the scorecard meaningless. Cancel and re-schedule
    instead.
    """
    scheduled_at: Optional[str] = None
    duration_min: Optional[int] = None
    mode: Optional[InterviewMode] = None
    meeting_link: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[InterviewStatus] = None
    # ── Phase INT-2 ── the panel may change (somebody is away, a conflict is declared) and
    # the composition rule is re-checked on every change, so a panel cannot be edited down
    # below what the SOP requires after the booking is made.
    panel: Optional[List[PanelMemberIn]] = None


class InterviewEvaluateIn(BaseModel):
    """The scorecard. Every competency 0-5, a decision, and a typed signature.

    The signature is REQUIRED here. The source left it optional despite the UI implying
    otherwise (BACKEND_ANALYSIS 8) -- an unsigned evaluation that later decides a rejection
    is exactly the record you want attributable.
    """
    technical: int = 0
    communication: int = 0
    problem_solving: int = 0
    behavior: int = 0
    confidence: int = 0
    team_fit: int = 0
    outcome: Outcome
    remarks: Optional[str] = None
    signature: str


# =============================================================
# Phase 8 - Offers + public offer page
# =============================================================

class OfferStatus(str, Enum):
    DRAFT    = "Draft"      # being written; not visible to the candidate
    SENT     = "Sent"       # link issued, awaiting a response
    ACCEPTED = "Accepted"
    DECLINED = "Declined"
    REVOKED  = "Revoked"    # withdrawn by the company after sending


# An offer in one of these states occupies the candidate: a second one cannot be raised
# while one is live. Declined and Revoked are spent, so a fresh offer may follow.
ACTIVE_OFFER_STATUSES = {OfferStatus.DRAFT, OfferStatus.SENT, OfferStatus.ACCEPTED}

# Only a Draft is editable. Once sent, the letter the candidate is reading must not change
# underneath them -- that is the whole point of versioning it instead.
EDITABLE_OFFER_STATUSES = {OfferStatus.DRAFT}

# Candidate stages that count towards filling a requisition. Reaching `vacancy` of these
# auto-closes the requisition as Hired (Module 16 / BACKEND_ANALYSIS 6.4).
FILLED_STATUSES = {
    AppStatus.OFFER_ACCEPTED, AppStatus.PRE_ONBOARDING,
    AppStatus.JOINED, AppStatus.EMPLOYEE_CREATED,
    # A confirmed employee still fills the vacancy. Omitting this would RE-OPEN the
    # requisition the moment probation was confirmed, which is the opposite of the SOP.
    AppStatus.PROBATION_CONFIRMED,
    # Phase 11-R: an issued appointment letter means the vacancy is spoken for. Omitting it
    # would make a requisition RE-OPEN the moment the letter went out, because the candidate
    # leaves Offer Accepted for this stage.
    AppStatus.APPOINTMENT_LETTER_SENT,
}

AUDIT_OFFER_CREATED  = "offer created"
AUDIT_OFFER_EDITED   = "offer edited"
AUDIT_OFFER_SENT     = "offer sent"
AUDIT_OFFER_REVOKED  = "offer revoked"
AUDIT_OFFER_DELETED  = "offer deleted"
AUDIT_OFFER_ACCEPTED = "offer accepted"
AUDIT_OFFER_DECLINED = "offer declined"
AUDIT_REQ_AUTO_CLOSED = "requisition auto-closed (Hired)"

ENTITY_OFFER = "offer"


DEFAULT_OFFER_BODY = """We are delighted to offer you the position of {designation} at {company}.

Your annual cost to company will be {ctc}, and we would like you to join us on {joining_date}.

This offer is made on the understanding that the information you have provided during the
selection process is accurate and complete, and is subject to the satisfactory completion of
any background checks and the submission of the documents we will request separately.

We were impressed by you throughout the process and are genuinely looking forward to
working together.

Please review this letter and record your response using the buttons on this page."""


def render_offer_body(template: str, *, designation: str, company: str, ctc: str,
                      joining_date: str) -> str:
    """Fill the placeholders in an offer body.

    Deliberately a plain str.format_map with a defaulting dict rather than an f-string or
    a template engine: the body is operator-editable text, and an unknown placeholder must
    render harmlessly rather than raise or execute anything.
    """
    class _Safe(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    try:
        return (template or "").format_map(_Safe(
            designation=designation or "", company=company or "",
            ctc=ctc or "", joining_date=joining_date or ""))
    except (ValueError, IndexError):
        # A stray brace in operator text should not break the letter.
        return template or ""


# -- API models --
class OfferIn(BaseModel):
    uk: str
    ctc: float
    joining_date: str                       # YYYY-MM-DD
    designation: Optional[str] = None       # defaults from the requisition
    company_name: Optional[str] = None
    location: Optional[str] = None
    content: Optional[str] = None           # defaults to DEFAULT_OFFER_BODY
    send_now: bool = False                  # create and send in one action
    # Undeclared here, this field was silently dropped by Pydantic before the service ever
    # saw it -- `send_now=True` with a typed signature still failed the "authorised
    # signatory" check every time, because the service always read `None`.
    signature: Optional[str] = None         # authorised signatory, required when send_now


class OfferUpdate(BaseModel):
    """Edit a DRAFT offer. Every change bumps the version and archives the previous body."""
    ctc: Optional[float] = None
    joining_date: Optional[str] = None
    designation: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    content: Optional[str] = None
    signature: Optional[str] = None         # authorised signatory, required to send


class OfferSendIn(BaseModel):
    signature: str                          # the company's authorised signatory


class OfferRevokeIn(BaseModel):
    reason: Optional[str] = None


class PublicOfferResponseIn(BaseModel):
    """A candidate's response. Accepting requires a typed signature; declining does not --
    demanding one from someone walking away is friction with no purpose."""
    action: str                             # "accept" | "decline"
    signature: Optional[str] = None
    note: Optional[str] = None


# =============================================================
# Phase 9 - Onboarding + employee creation
# =============================================================

class OnboardStatus(str, Enum):
    PRE_ONBOARDING = "Pre-Onboarding"   # form issued, awaiting the candidate
    ONBOARDING     = "Onboarding"       # employee id minted, checklist in progress
    COMPLETED      = "Completed"         # every checklist item done


class PreOnboardStatus(str, Enum):
    PENDING   = "Pending"
    SUBMITTED = "Submitted"
    VERIFIED  = "Verified"


class DocStatus(str, Enum):
    """Where ONE uploaded joining document has got to (§7.5 Stage 3).

    `EXCEPTION` is the controlled-continuation case: the document is not in order, and
    somebody has accepted that in writing anyway -- a graduate whose degree certificate is
    still with the university, a joiner whose previous employer will not release a relieving
    letter. It satisfies the mandatory-document gate exactly as VERIFIED does, which is the
    whole point of it, and it is deliberately NOT a silent override: it carries the note
    saying who allowed it and why, and it reads differently everywhere it is shown.
    """
    PENDING   = "Pending"
    VERIFIED  = "Verified"
    REJECTED  = "Rejected"
    EXCEPTION = "Exception"


# A rejected document is not a satisfied one: it has to be replaced. These two are what let
# a joining go ahead.
DOC_SATISFYING_STATUSES = {DocStatus.VERIFIED.value, DocStatus.EXCEPTION.value}


class BgVerification(str, Enum):
    PENDING     = "Pending"
    IN_PROGRESS = "In Progress"
    CLEARED     = "Cleared"
    FLAGGED     = "Flagged"


# The joining-day checklist. Declared once so the seed, the progress bar and the
# "all done -> Employee Created" test all read the same list.
ONBOARD_CHECKLIST = [
    ("offer_signed",      "Signed offer letter received"),
    ("documents_verified", "KYC documents verified"),
    ("bg_cleared",        "Background verification cleared"),
    ("employee_id",       "Employee ID generated"),
    ("email_created",     "Company email account created"),
    ("system_access",     "System and tool access granted"),
    ("asset_issued",      "Assets issued (laptop, ID card)"),
    ("workspace",         "Workspace allocated"),
    ("induction",         "Induction / orientation completed"),
    ("policy_ack",        "Policies acknowledged"),
    ("bank_payroll",      "Bank and payroll details recorded"),
    ("buddy_assigned",    "Reporting manager and buddy introduced"),
]


# ── BA Functional Design §7.5 Stage 8 ── who each joining task actually belongs to.
#
# The list above has always been one flat set, which made every item look like HR's job.
# It is not: IT creates the accounts, Admin allocates the desk, and the reporting manager
# runs the induction. Naming the owner is what lets each of them be told what is theirs.
#
# Anything absent from this map is HR's, which is the right default -- HR owns the case.
TASK_OWNER_IT      = "IT"
TASK_OWNER_ADMIN   = "Admin"
TASK_OWNER_MANAGER = "Reporting Manager"
TASK_OWNER_HR      = "HR"

TASK_OWNERS = {
    "email_created":           TASK_OWNER_IT,
    "system_access":           TASK_OWNER_IT,
    "asset_issued":            TASK_OWNER_IT,
    "workspace":               TASK_OWNER_ADMIN,
    "induction":               TASK_OWNER_MANAGER,
    "buddy_assigned":          TASK_OWNER_MANAGER,
    "induction_policies":      TASK_OWNER_MANAGER,
    "induction_systems":       TASK_OWNER_IT,
    "induction_introductions": TASK_OWNER_MANAGER,
    "induction_workplace":     TASK_OWNER_MANAGER,
    "induction_feedback":      TASK_OWNER_HR,
}

# The owners whose work begins when the joiner actually turns up (§7.5 Stage 8: "Once
# joining is confirmed, the system automatically creates onboarding tasks"). HR's own items
# run from the moment the case opens, so they are not in here.
TASKS_ASSIGNED_AT_JOINING = (TASK_OWNER_IT, TASK_OWNER_ADMIN, TASK_OWNER_MANAGER)


def task_owner(key: str) -> str:
    """Who owns one checklist item. Unknown keys are HR's -- HR owns the case."""
    return TASK_OWNERS.get(key, TASK_OWNER_HR)
CHECKLIST_KEYS = [k for k, _ in ONBOARD_CHECKLIST]

# Checklist items the system owns. A human toggling these by hand would let the checklist
# claim something the data does not support, so they are driven by the actions that
# actually achieve them.
SYSTEM_CHECKLIST_KEYS = {"employee_id", "documents_verified", "bg_cleared"}

# The induction keys are declared beside INDUCTION_CHECKLIST, further down this file, so this
# list is completed there rather than here -- see `induction_checklist_keys()`.

MAX_ONBOARD_DOCUMENTS = 15
MAX_REFERENCES = 5

# What the NEW HIRE has to do, as opposed to ONBOARD_CHECKLIST, which is what HR has to do.
# Mailed to them with their portal link (§7.5, "Send Secure Onboarding Portal / Task List").
# Kept beside the form's own validation (`_validate_submission`) so the two stay in step --
# telling somebody to send a document the form does not accept wastes their time.
ONBOARD_CANDIDATE_TASKS = [
    "Your PAN or Aadhaar number",
    "Date of birth and personal details",
    "Current and permanent address",
    "Bank account number and IFSC code, for payroll",
    "Statutory details (UAN / PF / ESIC), where you have them",
    "An emergency contact",
    "Professional references",
    "Scanned copies of your identity, address, bank and previous-employment documents",
]

# ── BA Functional Design §7.5 ── the document upload TASKS, as opposed to a single pile of
# files. A typed slot is what makes "your address proof is missing" answerable; an untyped
# list can only say how many files arrived.
#
# This is the DEFAULT catalogue. A company edits it through the
# `onboarding_document_types` setting, which is why the shape is {label: required?} rather
# than a fixed enum -- §7.5 asks for these six "and other configurable document types".
ONBOARD_DOC_TYPES = {
    "PAN card": True,
    "Aadhaar card": True,
    "Bank proof (cancelled cheque or passbook)": True,
    "Address proof": True,
    "Previous employment documents": False,
    "Photograph": True,
}

# The candidate portal's sections, in the order §7.5 gives them. Declared as data so the
# portal, the HR view and this file cannot drift into three different orders.
# ── BA Functional Design §7.5 Stage 7 ── the employment documents a new joiner signs
# alongside their appointment letter. The letter itself is NOT in this list: it is the
# appointment record, not an attachment to it, and it already has its own signature.
#
# Configurable per company through `employment_documents`, for the same reason the joining
# documents are: "required policies" differs by industry, and a company adding its own
# policy should not need a deploy.
EMPLOYMENT_DOCUMENTS = {
    "Non-Disclosure Agreement": True,
    "Code of Conduct": True,
    "IT & Data Security Policy": True,
    "POSH Policy": True,
    "Leave & Attendance Policy": False,
}

ONBOARD_SECTIONS = [
    {"key": "personal",  "label": "Personal information"},
    {"key": "contact",   "label": "Contact information"},
    {"key": "bank",      "label": "Bank information"},
    {"key": "statutory", "label": "Statutory information"},
    {"key": "documents", "label": "Document upload"},
]

# Candidate stages an onboarding may be started from.
#
# ONLY `Offer Accepted`. The lifecycle graph declares `SELECTED -> OFFER_GENERATED` and
# `OFFER_ACCEPTED -> PRE_ONBOARDING`, with no edge from Selected to Pre-Onboarding -- so
# allowing a Selected candidate here would create an onboarding whose candidate could never
# legally reach the matching stage. It is also wrong in substance: onboarding collects PAN,
# Aadhaar and bank details, and asking for those before the person has agreed to join
# gathers sensitive identity data on someone who may still say no.
#
# Phase 11-R adds APPOINTMENT_LETTER_SENT: it sits strictly AFTER Offer Accepted, so the
# consent argument above is satisfied a fortiori -- the candidate has agreed to join AND
# been sent their appointment letter. Both are onboardable because the letter is optional.
ONBOARDABLE_STATUSES = {AppStatus.OFFER_ACCEPTED, AppStatus.APPOINTMENT_LETTER_SENT}

AUDIT_ONBOARD_STARTED    = "onboarding started"
AUDIT_ONBOARD_SUBMITTED  = "pre-onboarding submitted"
AUDIT_ONBOARD_VERIFIED   = "kyc documents verified"
AUDIT_ONBOARD_DOCUMENTS  = "kyc documents updated"
AUDIT_ONBOARD_BG         = "background verification updated"
AUDIT_ONBOARD_DETAILS    = "joining details updated"
AUDIT_ONBOARD_CHECKLIST  = "onboarding checklist updated"
AUDIT_EMPLOYEE_ID_ISSUED = "employee id generated"
AUDIT_ONBOARD_COMPLETED  = "onboarding completed"
AUDIT_EMPLOYEE_LINKED    = "employee linked to a user account"

ENTITY_ONBOARDING = "onboarding"


def seed_checklist() -> list:
    """The checklist a new onboarding record starts with: the base twelve items, then the
    Day-1 induction items (SOP §7). The induction items are appended, never interleaved, so
    the base order is preserved."""
    items = [{"key": k, "label": label, "done": False, "done_at": None, "done_by": None,
              "owner": task_owner(k), "assigned_at": None}
             for k, label in ONBOARD_CHECKLIST]
    items += [{"key": k, "label": label, "done": False, "done_at": None,
               "done_by": None, "induction": True,
               "owner": task_owner(k), "assigned_at": None}
              for k, label in INDUCTION_CHECKLIST]
    return items


# -- API models --
class OnboardingIn(BaseModel):
    uk: str
    joining_date: Optional[str] = None       # YYYY-MM-DD; defaults from the accepted offer
    reporting_manager_id: Optional[str] = None


class OnboardingDetailsIn(BaseModel):
    joining_date: Optional[str] = None
    reporting_manager_id: Optional[str] = None
    asset_requirements: Optional[str] = None


class OnboardingJoiningIn(BaseModel):
    """HR confirming that somebody actually turned up (§7.5 Stage 6).

    `actual_doj` is separate from the planned `joining_date` on purpose: people start late,
    and overwriting the agreed date would destroy the evidence that they did. Payroll,
    probation and tenure all run from the ACTUAL date.

    The assignment fields are the nine the BA document lists. Department, designation and
    reporting manager reference records that exist; grade, location, unit and payroll group
    are free text because this codebase has no master for any of them yet.
    """
    actual_doj: str
    note: Optional[str] = None
    unit: Optional[str] = None
    department_id: Optional[str] = None
    designation_id: Optional[str] = None
    grade: Optional[str] = None
    work_location: Optional[str] = None
    reporting_manager_id: Optional[str] = None
    employment_type: Optional[EmploymentType] = None
    employment_status: Optional[EmploymentStatus] = None
    payroll_group: Optional[str] = None


# The nine attributes assigned when an employee is activated (§7.5 Stage 6). Declared as
# data so the onboarding record, the employee record and the screen cannot drift apart.
ASSIGNMENT_FIELDS = (
    "unit", "department_id", "designation_id", "grade", "work_location",
    "reporting_manager_id", "employment_type", "employment_status", "payroll_group",
)


class OnboardingBgIn(BaseModel):
    bg_verification: BgVerification
    note: Optional[str] = None


class OnboardingChecklistIn(BaseModel):
    key: str
    done: bool


class OnboardingDocumentsIn(BaseModel):
    """HR-side KYC upload. Kept separate from the candidate's public submission so HR can
    collect documents even before the candidate fills the form."""
    documents: List[UploadIn] = Field(default_factory=list)


class OnboardingDocReviewIn(BaseModel):
    """HR's verdict on one uploaded joining document (§7.5 Stage 3).

    Names the document TYPE rather than an index: the verdict belongs to "the Aadhaar card",
    and an index would silently point at a different file the moment a new version arrives.
    """
    doc_type: str
    status: DocStatus
    note: Optional[str] = None


class EmployeeLinkIn(BaseModel):
    """Attach an employee record created by onboarding to a real login account."""
    user_id: str


class PublicOnboardIn(BaseModel):
    """The candidate's pre-onboarding submission. Entirely untrusted.

    PAN-or-Aadhaar is required, enforced SERVER-SIDE. The source checked this in the browser
    only (BACKEND_ANALYSIS 8), so malformed or absent identity documents reached the
    database on any request that skipped the form.
    """
    pan: Optional[str] = None
    aadhaar: Optional[str] = None
    passport: Optional[str] = None
    driving_license: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[Gender] = None
    address: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    bank_ifsc: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relation: Optional[str] = None
    references: List[dict] = Field(default_factory=list)   # [{name, relation, phone}]
    asset_requirements: Optional[str] = None
    documents: List[UploadIn] = Field(default_factory=list)


# =============================================================
# Phase 10 - analytics & reports (READ-ONLY)
# =============================================================

# -- Effective rank ---------------------------------------------------------------
# A funnel built by counting `application_status` is wrong, and wrong in a way that is
# obvious once seen: a candidate sitting at `Offer Accepted` is NOT counted as having been
# interviewed, so the funnel can show more offers than interviews. FRONTEND_ANALYSIS 6.1
# describes the source working around this in the browser, per screen, inconsistently.
#
# The fix is to rank stages monotonically and count "reached AT LEAST this stage". A
# candidate's effective rank is the furthest point they can be SHOWN to have reached:
#
#     effective_rank = max(rank(application_status),
#                          rank implied by an assessment record,
#                          rank implied by an interview record,
#                          rank implied by an offer record)
#
# Evidence outranks the status field because evidence is a fact and the status is a label
# somebody can drag backwards. This also makes the funnel monotonically non-increasing by
# construction -- a property a funnel must have to mean anything.
STAGE_RANK = {
    AppStatus.APPLIED:              1,
    AppStatus.UNDER_REVIEW:         1,
    AppStatus.DUPLICATE:            1,
    AppStatus.ON_HOLD:              1,
    AppStatus.REJECTED:             1,   # ranked where they entered, not where they left
    AppStatus.SHORTLISTED:          2,
    # ── Phase INT-4 ── the telephonic band sits WITH Shortlisted: a phone screen is a
    # decision ABOUT a shortlisted candidate, not
    # a further stage of the funnel. Ranking it 3 would push assessment and interview up and
    # renumber every Phase 10 figure. TELEPHONIC_REJECTED is ranked where the candidate
    # ENTERED, the same treatment REJECTED gets.
    AppStatus.TELEPHONIC_PASSED:    2,
    AppStatus.TELEPHONIC_REJECTED:  2,
    AppStatus.ASSESSMENT_PENDING:   3,
    AppStatus.ASSESSMENT_COMPLETED: 3,
    AppStatus.ASSESSMENT_PASSED:    3,
    AppStatus.ASSESSMENT_FAILED:    3,
    AppStatus.INTERVIEW_SCHEDULED:  4,
    AppStatus.TECHNICAL_ROUND:      4,
    AppStatus.MD_ROUND:             4,
    # Ranked WITH the interview band, not above it. Final Commit has decided, but the
    # candidate has not cleared the round yet, and ranking them at 5 would count them as
    # selected in every funnel figure.
    AppStatus.FINAL_INTERVIEW_REQUIRED: 4,
    AppStatus.SELECTED:             5,
    AppStatus.OFFER_GENERATED:      6,
    AppStatus.OFFER_DECLINED:       6,   # they DID receive an offer -- that stage was reached
    AppStatus.OFFER_ACCEPTED:       7,
    # Same band as Offer Accepted / Pre-Onboarding. Existing ranks are NOT renumbered, so
    # the funnel stays monotonic and every Phase 10 figure keeps its meaning.
    AppStatus.APPOINTMENT_LETTER_SENT: 7,
    AppStatus.PRE_ONBOARDING:       7,
    AppStatus.JOINED:               7,
    AppStatus.EMPLOYEE_CREATED:     8,
    # Rank 8, WITH the hire. A confirmation is not a further step down the funnel,
    # so FUNNEL_STAGES keeps its 8 rows and every Phase 10 figure keeps its meaning.
    AppStatus.PROBATION_CONFIRMED:  8,
}

# The funnel, declared once. `min_rank` is the bar a candidate must clear to be counted.
FUNNEL_STAGES = [
    ("applied",     "Applied",      1),
    ("shortlisted", "Shortlisted",  2),
    ("assessment",  "Assessment",   3),
    ("interview",   "Interview",    4),
    ("selected",    "Selected",     5),
    ("offered",     "Offered",      6),
    ("accepted",    "Accepted",     7),
    ("hired",       "Hired",        8),
]

# Rank floors implied by the mere EXISTENCE of a record elsewhere in the pipeline.
RANK_IF_ASSESSED    = 3
RANK_IF_INTERVIEWED = 4
RANK_IF_OFFERED     = 6
RANK_IF_ACCEPTED    = 7


def stage_rank(status) -> int:
    """Rank of an application status. Unknown statuses rank 0 -- counted in the total but
    never credited to a funnel stage, which is the honest treatment of data we cannot
    interpret."""
    try:
        return STAGE_RANK.get(AppStatus(status), 0)
    except ValueError:
        return 0


def conversion(numerator: int, denominator: int) -> float:
    """Stage-to-stage conversion as a percentage, 1 dp. Zero denominator -> 0.0, never a
    ZeroDivisionError and never a misleading 100%."""
    if not denominator:
        return 0.0
    return round(numerator * 100.0 / denominator, 1)


# -- Reports ----------------------------------------------------------------------
# An allow-list, not a free-form collection name. `entity` arrives in the URL, and mapping
# it straight onto a collection would let a caller read any collection in the database.
# Each entry declares its collection, its sortable date field, its searchable fields and
# the EXACT columns exposed -- so a field added to a document later is not silently
# published to a report or an export.
REPORT_ENTITIES = {
    "candidates": {
        "collection": COLL_CANDIDATES,
        "date_field": "applied_at",
        "search":     ["candidate_name", "can_email", "can_contact", "uk"],
        "columns": [
            ("uk", "Candidate ID"), ("candidate_name", "Name"), ("can_email", "Email"),
            ("can_contact", "Phone"), ("source", "Source"),
            ("application_status", "Stage"), ("request_no", "Requisition"),
            ("current_location", "Location"), ("total_experience", "Experience"),
            ("expected_ctc", "Expected CTC"), ("notice_period", "Notice"),
            # ── Phase 11-R ── referral detail and the client's verdict travel with the
            # candidate into every report and export automatically.
            ("referred_by", "Referred by"), ("referral_source", "Referral source"),
            ("client_share_status", "Client verdict"),
            # ── Internal track ── empty on the client track, where no scorecard exists.
            ("scorecard_score", "Scorecard"), ("scorecard_band", "Band"),
            ("applied_at", "Applied on"),
        ],
    },
    "requisitions": {
        "collection": COLL_REQUISITIONS,
        "date_field": "created_at",
        "search":     ["request_no", "designation_name", "department_name"],
        "columns": [
            ("request_no", "Requisition"), ("designation_name", "Designation"),
            ("department_name", "Department"), ("vacancy", "Vacancy"),
            ("urgency_level", "Urgency"), ("approval_status", "Approval"),
            ("closing_status", "Status"), ("assignee_name", "Hiring manager"),
            # ── Phase 11-R ── `budget_status` is DERIVED, not a stored field; the report
            # service computes it per row (see hrms_analytics_service._derive).
            ("client_name", "Client"), ("requisition_type", "Type"),
            ("budget_status", "Budget"),
            ("required_date", "Required by"), ("created_at", "Raised on"),
        ],
    },
    "interviews": {
        "collection": COLL_INTERVIEWS,
        "date_field": "scheduled_at",
        "search":     ["interview_no", "candidate_name", "interviewer_name"],
        "columns": [
            ("interview_no", "Interview"), ("candidate_name", "Candidate"),
            ("round", "Round"), ("mode", "Mode"), ("interviewer_name", "Interviewer"),
            ("status", "Status"), ("outcome", "Outcome"),
            ("average_score", "Avg score"), ("scheduled_at", "Scheduled for"),
        ],
    },
    "offers": {
        "collection": COLL_OFFERS,
        "date_field": "created_at",
        "search":     ["offer_no", "candidate_name", "designation"],
        "columns": [
            ("offer_no", "Offer"), ("candidate_name", "Candidate"),
            ("designation", "Designation"), ("status", "Status"),
            ("ctc", "CTC"), ("joining_date", "Joining date"),
            ("sent_at", "Sent on"), ("responded_at", "Responded on"),
        ],
    },
    "onboarding": {
        "collection": COLL_ONBOARDING,
        "date_field": "created_at",
        "search":     ["onb_no", "candidate_name", "employee_id"],
        "columns": [
            ("onb_no", "Onboarding"), ("candidate_name", "New hire"),
            ("designation", "Designation"), ("status", "Status"),
            ("pre_status", "Pre-onboarding"), ("bg_verification", "Background"),
            ("employee_id", "Employee ID"), ("joining_date", "Joining date"),
            ("created_at", "Started on"),
        ],
    },
    # ── Internal recruitment track ──
    # Both carry `request_no`, so the single analytics scope filter reaches them unchanged.
    #
    # `retention_until` is on both, per SOP §13. It is the date the record may be considered
    # for disposal, computed and stored when the record is written. NOTHING PURGES IT --
    # exposing the date on a report is the whole of what this phase does with retention.
    "probation": {
        "collection": COLL_PROBATION_REVIEWS,
        "date_field": "created_at",
        "search":     ["prb_no", "employee_code", "employee_name"],
        "columns": [
            ("prb_no", "Probation"), ("employee_code", "Employee"),
            ("employee_name", "Name"), ("request_no", "Requisition"),
            ("started_on", "Started"), ("duration_months", "Months"),
            ("ends_on", "Ends"), ("outcome", "Outcome"), ("rating", "Rating"),
            ("extension_count", "Extensions"),
            ("confirmed_by_name", "Decided by"), ("confirmed_at", "Decided on"),
            ("retention_until", "Keep until"), ("created_at", "Opened on"),
        ],
    },
    "exceptions": {
        "collection": COLL_EXCEPTIONS,
        "date_field": "created_at",
        "search":     ["exc_no", "request_no", "reason"],
        "columns": [
            ("exc_no", "Exception"), ("exception_type", "Type"),
            ("gate", "Lifts gate"), ("request_no", "Requisition"),
            ("uk", "Candidate"), ("candidate_name", "Candidate name"),
            ("status", "Status"), ("reason", "Reason"),
            ("raised_by_name", "Raised by"), ("raised_at", "Raised on"),
            ("approved_by_name", "Decided by"), ("approved_at", "Decided on"),
            ("decision_remarks", "Decision remarks"), ("created_at", "Logged on"),
        ],
    },
}

# Columns carrying compensation. Redacted for a caller without `employee.salary.read`,
# reusing the Phase 2 boundary rather than inventing a second rule for reports.
SALARY_REPORT_COLUMNS = {"ctc", "expected_ctc", "offering_ctc", "current_ctc", "base_salary"}

# (collection, field, label) per breakdown dimension. Also an allow-list: `by` arrives in
# the query string and must never become an arbitrary field name to group on.
BREAKDOWN_FIELDS = {
    "source":      (COLL_CANDIDATES,   "source",           "Source"),
    "department":  (COLL_REQUISITIONS, "department_name",  "Department"),
    "designation": (COLL_REQUISITIONS, "designation_name", "Designation"),
    # A posting no longer carries a platform -- one posting, one link, shared anywhere. The
    # channel is `source`, answered by the applicant, so grouping by platform would only
    # ever count a field nothing writes.
    # ── Phase 11-R ── still an allow-list: `by` arrives in the query string and any value
    # absent from this map is rejected, so a dotted path here cannot become arbitrary.
    "client_status":   (COLL_CANDIDATES, "client_share.status", "Client verdict"),
    "referral_source": (COLL_CANDIDATES, "referral_source",     "Referral source"),
    "client":          (COLL_REQUISITIONS, "client_name",       "Client"),
}

MAX_REPORT_PAGE_SIZE = 100
DEFAULT_REPORT_PAGE_SIZE = 25
# A hard ceiling on an export. Beyond this the caller is TOLD it was truncated rather than
# handed a silently short file and left to draw conclusions from it.
MAX_EXPORT_ROWS = 5000
# The widest window an analytics query may cover. Bounds the work a single request can ask
# the database to do.
MAX_RANGE_DAYS = 1100          # ~3 years
MAX_BREAKDOWN_ROWS = 25


class ReportEntity(str, Enum):
    CANDIDATES   = "candidates"
    REQUISITIONS = "requisitions"
    INTERVIEWS   = "interviews"
    OFFERS       = "offers"
    ONBOARDING   = "onboarding"
    # ── Internal recruitment track ──
    PROBATION    = "probation"
    EXCEPTIONS   = "exceptions"


class BreakdownBy(str, Enum):
    SOURCE      = "source"
    DEPARTMENT  = "department"
    DESIGNATION = "designation"
    # ── Phase 11-R ──
    CLIENT_STATUS   = "client_status"
    REFERRAL_SOURCE = "referral_source"
    CLIENT          = "client"


class ExportFormat(str, Enum):
    CSV  = "csv"
    XLSX = "xlsx"


# =============================================================
# Phase 11-R, Item 1 - the public-link registry
# =============================================================
# Four kinds of public link already existed (apply / assessment / offer / onboarding), each
# minted independently and surfaced ad-hoc, with no registry, no open tracking, no expiry
# and no revocation. The registry does not CHANGE how any of them are generated -- it
# records them, so there is one place to answer "what links are live, who opened them, and
# how do I kill one".
class LinkKind(str, Enum):
    APPLY       = "apply"
    ASSESSMENT  = "assessment"
    OFFER       = "offer"
    ONBOARDING  = "onboarding"
    APPOINTMENT = "appointment"
    # ── Phase INT-2 ── the new-hire experience surveys (SOP §10). Registered like every
    # other public credential rather than inventing a second link mechanism, so revocation,
    # expiry and open-tracking all work on it for free.
    SURVEY      = "survey"


class LinkStatus(str, Enum):
    ACTIVE   = "Active"
    EXPIRED  = "Expired"     # past `expires_at` -- COMPUTED on read, never stored
    REVOKED  = "Revoked"     # killed by a human
    CONSUMED = "Consumed"    # its purpose completed (applied / submitted / responded)


# kind -> the relative public path template. One declaration, so the Link Manager, the
# copy-to-clipboard button and the registry can never disagree about a URL.
LINK_PATHS = {
    LinkKind.APPLY:       "/apply/{code}",
    LinkKind.ASSESSMENT:  "/assess/{code}",
    LinkKind.OFFER:       "/offer/{code}",
    LinkKind.ONBOARDING:  "/onboard/{code}",
    LinkKind.APPOINTMENT: "/appointment/{code}",
    LinkKind.SURVEY:      "/survey/{code}",
}

# Statuses in which a link still WORKS. Anything else is refused by assert_link_live().
LIVE_LINK_STATUSES = {LinkStatus.ACTIVE, LinkStatus.CONSUMED}

# Which service owns each kind, for reissue. A reissue must delegate to the owning service
# so the fresh code is one that service knows about -- minting a code here that
# hrms_offer_service has never heard of would produce a link that resolves to nothing.
REISSUABLE_KINDS = {LinkKind.ASSESSMENT, LinkKind.OFFER, LinkKind.ONBOARDING,
                    LinkKind.APPOINTMENT}

def effective_link_status(doc: dict, today: str) -> str:
    """A link's status as it actually is right now. Pure — no DB, no clock.

    Expiry is COMPUTED, exactly as hrms_posting_service._effective_status computes a
    posting's: a link past its expiry date reads Expired without a nightly job, and nothing
    is written, so the stored value still shows what an operator set.

    Revoked and Consumed are stored facts and outrank the date. A REVOKED link that is also
    past expiry is Revoked -- the human decision is the more informative answer.

    Tolerates a document with no status at all (written before this phase), which reads
    Active: the registry must never lock out a link it simply does not know about.
    """
    doc = doc or {}
    status = doc.get("status") or LinkStatus.ACTIVE.value
    if status in (LinkStatus.REVOKED.value, LinkStatus.CONSUMED.value):
        return status
    # Both are 'YYYY-MM-DD' strings, which compare correctly lexically and are immune to
    # server-timezone drift -- the same convention is_iso_date documents for every date here.
    expires = doc.get("expires_at")
    if expires and today and str(expires) < str(today):
        return LinkStatus.EXPIRED.value
    return status


AUDIT_LINK_ISSUED   = "public link issued"
AUDIT_LINK_REVOKED  = "public link revoked"
AUDIT_LINK_REISSUED = "public link reissued"

ENTITY_LINK = "link"


class LinkRevokeIn(BaseModel):
    reason: Optional[str] = None


# =============================================================
# Phase 11-R, Item 2 - documentation
# =============================================================
class DocumentOwnerType(str, Enum):
    CANDIDATE = "candidate"
    EMPLOYEE  = "employee"


class DocumentCategory(str, Enum):
    IDENTITY       = "Identity"
    EDUCATIONAL    = "Educational"
    EMPLOYMENT     = "Employment"
    STATUTORY      = "Statutory"
    COMPANY_ISSUED = "Company Issued"
    # §22.1/BR-029 — Sparsh Magic's own document category, alongside the generic ones above.
    PSC            = "PSC"
    OTHER          = "Other"


class DocumentStatus(str, Enum):
    PENDING      = "Pending"        # expected, nothing uploaded yet
    UPLOADED     = "Uploaded"
    UNDER_REVIEW = "Under Review"
    VERIFIED     = "Verified"
    REJECTED     = "Rejected"
    EXPIRED      = "Expired"        # past `expiry_date` -- COMPUTED on read, never stored


# Rejecting a document requires a reason, the same rule INTERNAL_REQ_TRANSITIONS applies to a
# rejected requisition: a refusal the owner cannot act on is not a decision, it is a wall.
DOCUMENT_STATUSES_REQUIRING_REMARKS = {DocumentStatus.REJECTED}

# A document is a small number of revisions, not a version-control system. Ten is generous
# for "the scan was blurry, here it is again" and bounds one document's storage.
MAX_DOCUMENT_VERSIONS = 10

# How many days ahead counts as "expiring soon" on the register's filter.
DOCUMENT_EXPIRY_SOON_DAYS = 30

# Seeded for a company that has no document types yet, on first read. A sensible Indian
# HR starting set -- HR edits it; nothing here is mandatory to keep.
#
# Phase INT-2 adds a sixth column, `statutory_required` (SOP §11). It is NOT the same thing
# as `mandatory`: mandatory means "collect this", statutory_required means "probation cannot
# be CONFIRMED until this is Verified". A photograph is mandatory and is not a statutory
# check; a degree certificate is both. Defaults to False everywhere else, so a type HR added
# by hand never silently starts blocking confirmations.
# (name, category, applies_to, mandatory, expires, statutory_required)
DEFAULT_DOCUMENT_TYPES = [
    ("PAN Card",              DocumentCategory.IDENTITY,       "both",      True,  False, True),
    ("Aadhaar Card",          DocumentCategory.IDENTITY,       "both",      True,  False, True),
    ("Passport",              DocumentCategory.IDENTITY,       "both",      False, True,  False),
    ("Address Proof",         DocumentCategory.IDENTITY,       "both",      False, False, False),
    # Mandatory to collect, but nobody's employment turns on a photograph.
    ("Photograph",            DocumentCategory.IDENTITY,       "both",      True,  False, False),
    ("Degree Certificate",    DocumentCategory.EDUCATIONAL,    "both",      True,  False, True),
    ("Experience Letter",     DocumentCategory.EMPLOYMENT,     "both",      False, False, False),
    ("Relieving Letter",      DocumentCategory.EMPLOYMENT,     "both",      False, False, False),
    ("Last 3 Payslips",       DocumentCategory.EMPLOYMENT,     "candidate", False, False, False),
    ("Bank Proof",            DocumentCategory.STATUTORY,      "employee",  True,  False, False),
    ("Offer Letter Signed",   DocumentCategory.COMPANY_ISSUED, "candidate", False, False, False),
    ("Appointment Letter",    DocumentCategory.COMPANY_ISSUED, "candidate", False, False, False),
]

AUDIT_DOCUMENT_UPLOADED  = "document uploaded"
AUDIT_DOCUMENT_VERSIONED = "document version added"
AUDIT_DOCUMENT_UPDATED   = "document updated"
AUDIT_DOCUMENT_STATUS    = "document status changed"
AUDIT_DOCUMENT_DELETED   = "document deleted"
AUDIT_DOCTYPE_CREATED    = "document type created"
AUDIT_DOCTYPE_UPDATED    = "document type updated"
AUDIT_DOCTYPE_DELETED    = "document type deleted"

ENTITY_DOCUMENT      = "document"
ENTITY_DOCUMENT_TYPE = "document_type"


class DocumentTypeIn(BaseModel):
    name: str
    code: Optional[str] = None
    category: DocumentCategory = DocumentCategory.OTHER
    applies_to: str = "both"                 # candidate | employee | both
    mandatory: bool = False
    expires: bool = False
    active: bool = True
    # ── Phase INT-2 ── SOP §11: a document flagged here must be Verified before probation
    # can be confirmed. Defaults False so an existing type never starts gating by surprise.
    statutory_required: bool = False


class DocumentTypeUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    category: Optional[DocumentCategory] = None
    applies_to: Optional[str] = None
    mandatory: Optional[bool] = None
    expires: Optional[bool] = None
    active: Optional[bool] = None
    statutory_required: Optional[bool] = None


class DocumentIn(BaseModel):
    """Upload a document, or a new version of one.

    Supplying `doc_no` adds a VERSION to that document; omitting it creates a new one.
    One endpoint for both because they are the same act from the operator's side -- "here
    is the paperwork" -- and splitting them would make the client decide which it is.
    """
    owner_type: DocumentOwnerType
    owner_id: str                            # uk | employee_code
    type_id: str
    doc_no: Optional[str] = None             # set to add a version to an existing document
    file: UploadIn
    issue_date: Optional[str] = None         # YYYY-MM-DD
    expiry_date: Optional[str] = None        # YYYY-MM-DD
    remarks: Optional[str] = None


class DocumentUpdate(BaseModel):
    """Metadata only. The FILE is immutable -- correcting it means a new version, so the
    record of what was actually submitted at each point survives."""
    issue_date: Optional[str] = None
    expiry_date: Optional[str] = None
    remarks: Optional[str] = None
    type_id: Optional[str] = None


class DocumentStatusIn(BaseModel):
    status: DocumentStatus
    remarks: Optional[str] = None            # REQUIRED when rejecting


# =============================================================
# Phase 11-R, Item 3 - appointment letters
# =============================================================
# Deliberately its own collection rather than extra statuses on hrms_offers. An offer and an
# appointment letter are two artifacts with two lifecycles: the offer proposes terms and is
# accepted or declined; the appointment letter confirms joining and is acknowledged. Folding
# them together would mean one `status` field trying to describe two documents -- exactly
# the "two sources of truth in one column" problem Phase 5 removed from candidates.
class AppointmentStatus(str, Enum):
    NOT_GENERATED = "Not Generated"          # the eligible-list state; never stored
    GENERATED     = "Generated"              # drafted, not yet issued
    SENT          = "Sent"
    PENDING_ACK   = "Pending Acknowledgement"  # the candidate has opened it
    ACKNOWLEDGED  = "Acknowledged"
    CANCELLED     = "Cancelled"


# Only a Generated letter is editable. Identical rule, and identical reasoning, to
# EDITABLE_OFFER_STATUSES: once sent, the document the candidate is reading must not change
# underneath them.
EDITABLE_APPOINTMENT_STATUSES = {AppointmentStatus.GENERATED}

# States in which the candidate's public link still resolves.
LIVE_APPOINTMENT_STATUSES = {AppointmentStatus.SENT, AppointmentStatus.PENDING_ACK,
                             AppointmentStatus.ACKNOWLEDGED}

AUDIT_APPOINTMENT_GENERATED = "appointment letter generated"
AUDIT_APPOINTMENT_EDITED    = "appointment letter edited"
AUDIT_APPOINTMENT_SENT      = "appointment letter sent"
AUDIT_APPOINTMENT_OPENED    = "appointment letter opened"
AUDIT_APPOINTMENT_ACK       = "appointment letter acknowledged"
AUDIT_APPOINTMENT_CANCELLED = "appointment letter cancelled"

ENTITY_APPOINTMENT = "appointment"


DEFAULT_APPOINTMENT_BODY = """Further to your acceptance of our offer, we are pleased to confirm your appointment as {designation} at {company}.

Your appointment takes effect from {joining_date} and you will be based at {location}. Your annual cost to company will be {ctc}.

This appointment is subject to the terms set out in your offer letter, to the satisfactory completion of any background verification still in progress, and to the submission of the documents requested by the HR team.

Please confirm your acceptance of this appointment by acknowledging this letter below. We look forward to welcoming you to the team."""


def render_appointment_body(template: str, *, designation: str, company: str, ctc: str,
                            joining_date: str, location: str = "") -> str:
    """Fill the placeholders in an appointment letter body.

    Same mechanism, and the same reasoning, as render_offer_body: a plain format_map with a
    defaulting dict, so operator-edited text containing an unknown placeholder renders
    harmlessly rather than raising or executing anything.
    """
    class _Safe(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    try:
        return (template or "").format_map(_Safe(
            designation=designation or "", company=company or "", ctc=ctc or "",
            joining_date=joining_date or "", location=location or ""))
    except (ValueError, IndexError):
        return template or ""


class AppointmentIn(BaseModel):
    uk: str
    joining_date: Optional[str] = None       # YYYY-MM-DD; defaults from the accepted offer
    designation: Optional[str] = None
    department: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    ctc: Optional[float] = None
    content: Optional[str] = None            # defaults to DEFAULT_APPOINTMENT_BODY
    signature: Optional[str] = None


class AppointmentUpdate(BaseModel):
    joining_date: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    ctc: Optional[float] = None
    content: Optional[str] = None
    signature: Optional[str] = None


class AppointmentSendIn(BaseModel):
    signature: str                           # the company's authorised signatory


class AppointmentCancelIn(BaseModel):
    reason: Optional[str] = None


class PublicAppointmentAckIn(BaseModel):
    """The candidate's acknowledgement. A typed signature is REQUIRED -- acknowledging an
    appointment letter is an act with consequences, so it is attributable, exactly as
    accepting an offer is."""
    signature: str
    note: Optional[str] = None
    # §7.5 Stage 7: the employment documents the joiner ticked. Named rather than counted,
    # so the record says WHICH documents that one signature covers.
    documents: List[str] = Field(default_factory=list)


# =============================================================
# Phase 11-R, Item 4 - the client master + client sharing
# =============================================================
# CONFIRMED WITH THE BUSINESS (see PHASE_11R_REPORT §Decisions): this deployment is the
# recruitment-AGENCY model. A "client" is the organisation a vacancy is being filled FOR,
# held in its own master, and is NOT the same thing as `company_id` (which remains the ERP
# tenant that OWNS the data). Every requisition may name one; scoping still runs on
# company_id throughout, so the client dimension is a reporting axis, never a security one.
# =============================================================
# Phase 12 — background verification
# =============================================================
class BackgroundCheckType(str, Enum):
    EMPLOYMENT = "Employment"
    EDUCATION  = "Education"
    ADDRESS    = "Address"
    IDENTITY   = "Identity / Document"
    CRIMINAL   = "Criminal Record"
    OTHER      = "Other"


class BackgroundCheckStatus(str, Enum):
    PENDING     = "Pending"
    IN_PROGRESS = "In Progress"
    CLEARED     = "Cleared"
    FLAGGED     = "Flagged"


# The checks that must be Cleared before an offer may be created. Declared as data so a
# company can see the list without reading code, and so the gate is one lookup.
#
# Criminal and Other are deliberately absent: the SOP names identity, education and prior
# employment, and a gate that demanded every check type would block on ones most hires
# never need.
REQUIRED_BACKGROUND_CHECKS = [
    BackgroundCheckType.IDENTITY,
    BackgroundCheckType.EDUCATION,
    BackgroundCheckType.EMPLOYMENT,
]

# Only a Cleared check satisfies the gate. In Progress is not a pass, and Flagged is
# emphatically not -- spelled out as a set for the same reason REFERENCE_CLEARS_OFFER is,
# so widening it later is a one-line, reviewable change.
BACKGROUND_CLEARS_OFFER = {BackgroundCheckStatus.CLEARED.value}


class BackgroundApprovalStatus(str, Enum):
    NOT_REQUESTED = "Not Requested"
    PENDING       = "Pending"
    APPROVED      = "Approved"
    REJECTED      = "Rejected"


AUDIT_BACKGROUND_RECORDED   = "background check recorded"
AUDIT_BACKGROUND_APPROVED   = "background verification approved"
AUDIT_BACKGROUND_REJECTED   = "background verification rejected"

# ── Internal recruitment track ──
AUDIT_BUDGET_APPROVED    = "headcount and budget approved"
AUDIT_SCORECARD_CREATED  = "position scorecard drafted"
AUDIT_SCORECARD_UPDATED  = "position scorecard updated"
AUDIT_SCORECARD_APPROVED = "position scorecard approved"
AUDIT_SCORECARD_EVALUATED = "candidate scored against the position scorecard"
AUDIT_REFERENCE_RECORDED = "reference check recorded"
AUDIT_REFERENCE_UPDATED  = "reference check updated"
AUDIT_OFFER_APPROVED     = "offer approved"
AUDIT_PROBATION_STARTED  = "probation review opened"
AUDIT_PROBATION_UPDATED  = "probation review updated"
AUDIT_PROBATION_CONFIRMED = "probation outcome recorded"
AUDIT_EXCEPTION_RAISED   = "exception raised"
AUDIT_EXCEPTION_DECIDED  = "exception decided"
AUDIT_PERSONNEL_FILE_CLOSED = "personnel file closed"
AUDIT_SLA_BREACHED       = "sla target breached"

ENTITY_SCORECARD = "position_scorecard"
ENTITY_REFERENCE = "reference_check"
ENTITY_PROBATION = "probation_review"
ENTITY_EXCEPTION = "exception"




# =============================================================
# Phase 11-R, Item 7 - sanctioned strength
# =============================================================
AUDIT_SANCTION_CREATED = "sanctioned strength set"
AUDIT_SANCTION_UPDATED = "sanctioned strength updated"
AUDIT_SANCTION_DELETED = "sanctioned strength removed"

ENTITY_SANCTION = "sanctioned_strength"


class SanctionedStrengthIn(BaseModel):
    department_id: str
    designation_id: str
    sanctioned_count: int
    effective_from: Optional[str] = None      # YYYY-MM-DD
    notes: Optional[str] = None


class SanctionedStrengthUpdate(BaseModel):
    sanctioned_count: Optional[int] = None
    effective_from: Optional[str] = None
    notes: Optional[str] = None


def is_over_sanction(sanctioned, actual: int, open_vacancies: int, requested: int) -> bool:
    """Whether filling `requested` more seats would exceed the sanctioned strength.

    `sanctioned is None` means no figure has ever been set for this position, which counts
    as over-sanction: a headcount nobody has authorised is precisely the case that should be
    escalated rather than waved through. Failing OPEN here would make the whole control
    optional by omission.
    """
    if sanctioned is None:
        return True
    try:
        return (int(actual) + int(open_vacancies) + int(requested)) > int(sanctioned)
    except (TypeError, ValueError):
        return True


# =============================================================
# Internal (in-house) recruitment track
# =============================================================
# Sparsh Magic hiring for itself, governed by the Internal Recruitment Policy & SOP.
#
# Everything below is ADDITIVE. A client-track requisition never enters any of these states,
# never has a scorecard, and is never blocked by the budget or reference gates -- so the
# agency track behaves exactly as it did before this phase.
#
# Where the two tracks differ in KIND: on the client track the client owns the budget and the
# verdict, so the module's job is to route CVs and record answers. Here Sparsh Magic owns
# both, so the module's job is to enforce its own governance -- which is why this half of the
# module is mostly gates rather than pipeline.

# -- SLA / TAT (SOP §8) -------------------------------------------------------------
# (key, label, target in WORKING days, measured from)
#
# `measured_from` names the milestone the clock starts at, so the table reads as the chain it
# is rather than four independent deadlines. None means "from the requisition itself".
#
# Working days exclude Saturday and Sunday. Public holidays are NOT excluded in this phase.
# The ERP has a holidays master (app/models/holiday.py) and honouring it is a small change,
# but doing it silently would make two companies with different holiday lists disagree about
# whether the same requisition breached -- a decision to take deliberately, not by default.
# Phase INT-2 completes the table. SOP §8 has SIX milestones and two of them are measured
# against a stored DATE rather than a preceding milestone, so the table carries an explicit
# `anchor` discriminator and stays declarative -- one table, two evaluators, no branching in
# the sweep. `sweep_open_breaches()` therefore picks the new rows up with no new sweep code.
#
#   anchor="milestone"  target_days working days after `measured_from` (None = the
#                       requisition itself). Evaluated by hrms_sla_service._status.
#   anchor="date"       due ON a date the record carries; `source` names which record and
#                       which field. `target_days` is null because there is no elapsed-time
#                       target to state, and reporting one would invent a number.
ANCHOR_MILESTONE = "milestone"
ANCHOR_DATE      = "date"

SLA_MILESTONES = [
    {"key": "budget_approved",    "label": "Budget / headcount approved",
     "anchor": ANCHOR_MILESTONE,  "target_days": 3,  "measured_from": None},
    {"key": "scorecard_approved", "label": "Position scorecard approved",
     "anchor": ANCHOR_MILESTONE,  "target_days": 2,  "measured_from": "budget_approved"},
    {"key": "shortlist_ready",    "label": "Shortlist ready for HOD review",
     "anchor": ANCHOR_MILESTONE,  "target_days": 15, "measured_from": None},
    {"key": "offer_released",     "label": "Offer released after selection",
     "anchor": ANCHOR_MILESTONE,  "target_days": 3,  "measured_from": "final_selection"},
    # ── The two date-anchored ones (Phase INT-2) ──
    # `collection` and `due_field` name where the date lives; `done` is how the service
    # decides the obligation was met. Both are per-RECORD, so one requisition with three
    # joiners reports three induction rows -- an aggregate "induction done" would hide the
    # one person nobody inducted.
    {"key": "induction_due",         "label": "Induction completed (Day 1)",
     "anchor": ANCHOR_DATE,          "target_days": None,
     "measured_from": "joining date (Day 1)",
     "collection": COLL_ONBOARDING,  "due_field": "joining_date", "id_field": "onb_no",
     "name_field": "candidate_name"},
    {"key": "probation_review_due",  "label": "Probation review before the end date",
     "anchor": ANCHOR_DATE,          "target_days": None,
     "measured_from": "probation end date",
     "collection": COLL_PROBATION_REVIEWS, "due_field": "ends_on", "id_field": "prb_no",
     "name_field": "employee_name"},
]

# The milestone keys a service may stamp. Only the milestone-anchored ones are stampable:
# a date-anchored row has nothing to stamp, its due date IS the record's own field.
STAMPABLE_MILESTONES = {m["key"] for m in SLA_MILESTONES
                        if m["anchor"] == ANCHOR_MILESTONE}


def sla_milestone(key: str) -> Optional[dict]:
    """One row of the SLA table by key, or None. Pure."""
    return next((m for m in SLA_MILESTONES if m["key"] == key), None)

# -- Record retention (SOP §13) -----------------------------------------------------
# Years to keep each record type. THIS PHASE COMPUTES AND STORES `retention_until` AND
# EXPOSES IT ON REPORTS. IT DOES NOT PURGE. There is deliberately no deletion job: an
# automated purge of employment records is a decision for the business and its auditors, not
# a side effect of a feature phase.
RETENTION_YEARS = {
    "requisition":          3,   # from requisition closure
    "candidate_selected":   3,   # from joining, then it lives on in the personnel file
    "candidate_unselected": 1,   # then securely purged -- manually, for now
    "offer":                3,   # employment + 3
    "reference":            3,   # employment + 3
    # A phone screen is candidate data, so it follows the CANDIDATE, not the employee: one
    # year for somebody who was not hired. A record of a call is not worth keeping for three
    # years about a person who never joined.
    "telephonic":           1,
    # A negotiation round is part of the OFFER record (SOP §13: "offer & acceptance --
    # employment + 3"), so it keeps the offer's floor rather than the candidate's.
    "negotiation":          3,
    "probation":            3,   # employment + 3
}


class ScorecardCategory(str, Enum):
    SKILL       = "skill"
    EXPERIENCE  = "experience"
    CULTURE_FIT = "culture_fit"


class ScorecardStatus(str, Enum):
    DRAFT            = "Draft"
    PENDING_APPROVAL = "Pending Approval"
    APPROVED         = "Approved"
    REJECTED         = "Rejected"


# The scoring decision guide. BOTH SOPs (Internal §5 and Part A §13) define FOUR bands, not
# three. The band is SURFACED, never auto-applied -- HR still decides, because a rubric that
# silently rejects people is one nobody will trust or correct.
#
#   >= 4.0        Strong      recommend
#   3.5 - 3.9     Consider    proceed with a second opinion
#   3.0 - 3.4     Hold        park; do not progress on this evidence alone
#   <  3.0        Reject
#
# Declared as an ordered floor table rather than a chain of ifs, so the boundaries are
# readable in one place and a test can walk them. The order matters: the FIRST floor a score
# clears wins, so the list runs highest to lowest.
SCORE_STRONG_AT    = 4.0
SCORE_CONSIDER_AT  = 3.5
SCORE_HOLD_AT      = 3.0
SCORE_REJECT_BELOW = 3.0     # kept: the offer/probation copy still cites "below 3.0"
SCORE_MIN = 1
SCORE_MAX = 5

SCORE_BANDS = [
    (SCORE_STRONG_AT,   "Strong"),
    (SCORE_CONSIDER_AT, "Consider"),
    (SCORE_HOLD_AT,     "Hold"),
]
SCORE_BAND_REJECT = "Reject"

# Every band, in descending order, for a UI that renders the guide beside the score. The
# label is the SAME string score_band() returns, so a legend can never drift from a result.
SCORE_BAND_GUIDE = [
    {"band": "Strong",   "from": SCORE_STRONG_AT,   "to": None,  "advice": "Recommend."},
    {"band": "Consider", "from": SCORE_CONSIDER_AT, "to": 3.9,
     "advice": "Proceed, with a second opinion."},
    {"band": "Hold",     "from": SCORE_HOLD_AT,     "to": 3.4,
     "advice": "Park. Do not progress on this evidence alone."},
    {"band": SCORE_BAND_REJECT, "from": None,       "to": 2.99, "advice": "Do not proceed."},
]


def score_band(weighted: Optional[float], bands=None) -> Optional[str]:
    """Strong / Consider / Hold / Reject for a weighted 1-5 score, or None if unscored.

    Read from a table rather than branched, so the four boundaries live in one place the
    tests walk directly. Anything below the lowest floor is Reject.

    `bands` lets a company supply its own floors (Phase INT-5). It is an optional argument
    rather than a global lookup because this function is PURE and a lot of code depends on
    that -- the tests walk it directly, and a version that reached into the database for a
    company row could not be called from a template, a report or a test without one.
    Callers that hold a company config pass `config[CONFIG_SCORE_BANDS]`; everybody else
    gets the module defaults, which is exactly the pre-INT-5 behaviour.

    Accepts either the table's own [(floor, label)] shape or the config's {label: floor}
    map, and sorts descending regardless -- a caller that hands over a dict in whatever
    order JSON happened to preserve must not silently get the wrong band.
    """
    if weighted is None:
        return None
    try:
        value = float(weighted)
    except (TypeError, ValueError):
        return None

    if bands is None:
        table = SCORE_BANDS
    elif isinstance(bands, dict):
        # A None floor is a band a company has switched off (Phase INT-10: the optional
        # Hold band). Skipped, not treated as zero -- a zero floor would catch everything.
        table = sorted(((float(f), l) for l, f in bands.items() if f is not None),
                       reverse=True)
    else:
        table = sorted(((float(f), l) for f, l in bands if f is not None), reverse=True)

    for floor, label in table:
        if value >= floor:
            return label
    return SCORE_BAND_REJECT


class ReferenceMode(str, Enum):
    PHONE     = "Phone"
    EMAIL     = "Email"
    LETTER    = "Letter"
    IN_PERSON = "In Person"


class ReferenceOutcome(str, Enum):
    POSITIVE         = "Positive"
    NEGATIVE         = "Negative"
    UNABLE_TO_VERIFY = "Unable to Verify"


# What opens the offer gate. An "Unable to Verify" reference is completed WORK but not a
# clearance, so it does not open it -- an exception must be logged instead, which is exactly
# the trail the SOP asks for.
REFERENCE_CLEARS_OFFER = {ReferenceOutcome.POSITIVE.value}


# -- Phase INT-4  The telephonic screen (SOP step 5, Annexure B "Telephonic screening") -----
class TelephonicOutcome(str, Enum):
    PASSED   = "Passed"
    REJECTED = "Rejected"
    # A call that did not happen is not a verdict. Without this, an unreachable candidate
    # forces HR to choose between recording a rejection they did not decide and recording
    # nothing at all -- and "nothing at all" is what makes a pipeline look stalled for no
    # visible reason.
    NO_ANSWER = "No Answer"


# What opens the interview gate. `No Answer` is an outcome, not a clearance -- the same
# distinction REFERENCE_CLEARS_OFFER draws for "Unable to Verify".
TELEPHONIC_CLEARS_INTERVIEW = {TelephonicOutcome.PASSED.value}

# Which candidate status each outcome moves to. Declared as data so the mapping is readable
# in one place; `No Answer` deliberately maps to NOTHING, because a call nobody answered has
# not decided anything about the candidate and must not move them.
TELEPHONIC_STATUS_FOR_OUTCOME = {
    TelephonicOutcome.PASSED.value:   AppStatus.TELEPHONIC_PASSED,
    TelephonicOutcome.REJECTED.value: AppStatus.TELEPHONIC_REJECTED,
    TelephonicOutcome.NO_ANSWER.value: None,
}

# The rated dimensions, and their weights in the overall score.
#
# Weighted rather than a flat average, and declared as a table: SOP step 5 calls this a
# screen for suitability, so how well somebody understands the role they applied for counts
# for more than how motivated they sound. Ratings run 1-5 and band through the SAME
# `score_band()` the position scorecard uses -- two scoring vocabularies in one recruitment
# process is how a "3" comes to mean two different things.
TELEPHONIC_CRITERIA = [
    ("communication",     "Communication",      0.30),
    ("role_understanding", "Role understanding", 0.30),
    ("motivation",        "Motivation",         0.20),
    ("suitability",       "Initial suitability", 0.20),
]

TELEPHONIC_RATING_MIN = 1
TELEPHONIC_RATING_MAX = 5

AUDIT_TELEPHONIC_RECORDED = "telephonic screening recorded"
AUDIT_TELEPHONIC_UPDATED  = "telephonic screening updated"
ENTITY_TELEPHONIC = "telephonic_screening"


class ProbationOutcome(str, Enum):
    PENDING    = "Pending"
    CONFIRMED  = "Confirmed"
    EXTENDED   = "Extended"
    TERMINATED = "Terminated"


class ProbationRecommendation(str, Enum):
    """What the REPORTING MANAGER proposes (§7.5 Stage 12).

    Deliberately distinct from ProbationOutcome. A recommendation is what one person
    thinks; an outcome is what the company decided. Collapsing the two -- which is what
    this module did before Stage 12 -- made the manager's opinion indistinguishable from
    an authorised decision, and left no room for HR to disagree.
    """
    CONFIRM  = "Confirm"
    EXTEND   = "Extend"
    SEPARATE = "Separate"


class HrReviewDecision(str, Enum):
    ENDORSED = "Endorsed"        # goes forward to the authorised approver
    RETURNED = "Returned"        # back to the manager, with a reason


# The five things a manager assesses before recommending anything (§7.5 Stage 12).
# Declared as data so the form, the stored record and the letter all read the same list.
PROBATION_REVIEW_CRITERIA = [
    ("performance", "Performance against the role"),
    ("conduct",     "Conduct and professionalism"),
    ("attendance",  "Attendance and punctuality"),
    ("competence",  "Competence and skill"),
    ("suitability", "Overall suitability for the role"),
]

PROBATION_CRITERIA_KEYS = [k for k, _ in PROBATION_REVIEW_CRITERIA]

# Which manager recommendation each outcome may follow from. HR and the approver can
# disagree with the manager, but the disagreement has to be deliberate -- the approver
# signs their own outcome, and the recommendation stays on the record beside it.
RECOMMENDATION_OUTCOME = {
    ProbationRecommendation.CONFIRM.value:  ProbationOutcome.CONFIRMED.value,
    ProbationRecommendation.EXTEND.value:   ProbationOutcome.EXTENDED.value,
    ProbationRecommendation.SEPARATE.value: ProbationOutcome.TERMINATED.value,
}


# SOP §7: "typically 3-6 months, per employment terms". The default is the top of that range,
# and every probation record carries its own duration -- so a shorter term is data, not code.
DEFAULT_PROBATION_MONTHS = 6
MIN_PROBATION_MONTHS = 1
MAX_PROBATION_MONTHS = 12


class ExceptionType(str, Enum):
    EXTENDED_TAT         = "Extended TAT"
    RELAXED_SCORECARD    = "Relaxed Scorecard"
    OFFER_OUTSIDE_BUDGET = "Offer Outside Budget"
    REFERENCE_WAIVED     = "Reference Check Waived"
    # ── Phase INT-2 ── SOP §11 requires statutory pre-employment checks to clear before
    # confirmation. Like every other gate on this track, the ONLY way past it is an approved
    # exception -- confirming somebody whose background check is still open is a decision a
    # company may need to take, and it must be one somebody signed.
    STATUTORY_WAIVED     = "Statutory Check Waived"
    # ── Phase INT-4 ── SOP step 5 puts a telephonic screen before the panel. Skipping it
    # is a real decision (an internal referral everybody has already met, an urgent
    # backfill), and like every other deviation on this track it must be one somebody
    # signed rather than a flag on a request body.
    TELEPHONIC_WAIVED    = "Telephonic Screening Waived"
    # ── Phase 12 ── background verification must clear before an offer, on BOTH tracks.
    # A real hire sometimes has to move before a check comes back (a verifier who will not
    # answer, a candidate with a counter-offer and a deadline), and the module's rule is
    # that such a decision is signed rather than switched off. Note this also gives every
    # candidate already mid-pipeline when the gate shipped a documented way through.
    BACKGROUND_WAIVED    = "Background Verification Waived"
    OTHER                = "Other"


class ExceptionStatus(str, Enum):
    PENDING  = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


# Which exception type unblocks which gate. Services look the gate up here rather than
# accepting an override flag on the request body: an approved, attributable record is the
# only thing that may bypass a control, and a boolean in a payload is neither.
EXCEPTION_UNBLOCKS = {
    "reference_check": ExceptionType.REFERENCE_WAIVED.value,
    "salary_band":     ExceptionType.OFFER_OUTSIDE_BUDGET.value,
    "scorecard":       ExceptionType.RELAXED_SCORECARD.value,
    "sla":             ExceptionType.EXTENDED_TAT.value,
    # ── Phase INT-2 ──
    # The statutory pre-employment gate on probation confirmation (SOP §11).
    "statutory_check": ExceptionType.STATUTORY_WAIVED.value,
    # The shortlisting-committee gate on `Selected` (SOP §5). It shares RELAXED_SCORECARD
    # rather than getting a type of its own, because that IS the deviation being approved:
    # progressing somebody the committee has not signed off is relaxing the selection
    # criteria, and the SOP names exactly one exception type for that.
    "shortlist":       ExceptionType.RELAXED_SCORECARD.value,
    # ── Phase INT-4 ── the telephonic gate on interview scheduling (SOP step 5).
    "telephonic":      ExceptionType.TELEPHONIC_WAIVED.value,
    # ── Phase 12 ── the background-verification gate on offer creation. Applies to both
    # tracks, so this is also the route through for anybody who was already at Selected
    # when the gate shipped.
    "background":      ExceptionType.BACKGROUND_WAIVED.value,
}


def gates_for_exception_type(exception_type: str) -> list:
    """Every gate one exception type lifts, in table order.

    A plain inverted dict was fine while the map was one-to-one. It is not any more:
    `Relaxed Scorecard` lifts BOTH the scorecard gate and the shortlisting-committee gate,
    and inverting would silently keep whichever happened to be declared last. Returning the
    list makes the fan-out visible instead of arbitrary; the FIRST entry stays the primary
    label, so an existing record's `gate` field reads exactly as it did before.
    """
    return [gate for gate, value in EXCEPTION_UNBLOCKS.items() if value == exception_type]

# Day-1 induction checklist (SOP §7). Same mechanism as ONBOARD_CHECKLIST, appended to an
# onboarding record on the INTERNAL track only -- a client-track onboarding still shows
# exactly the twelve items it always has.
INDUCTION_CHECKLIST = [
    ("induction_policies",      "Company policies walked through"),
    ("induction_systems",       "Systems and access set up"),
    ("induction_introductions", "Team introductions completed"),
    ("induction_workplace",     "Workplace orientation completed"),
    ("induction_feedback",      "New-hire induction feedback collected"),
]


# -- API models ---------------------------------------------------------------------
class BudgetApprovalIn(BaseModel):
    """Clear the mandatory budget gate on an internal requisition.

    The band is REQUIRED, not optional: the point of the gate is that a figure was authorised
    BEFORE sourcing began, and an approval carrying no number would leave the later offer
    check with nothing to validate against.
    """
    approved_headcount: int
    approved_salary_band_min: float
    approved_salary_band_max: float
    remarks: Optional[str] = None


class ScorecardCriterionIn(BaseModel):
    """One row of the Position Scorecard template.

    `Score (1-5)` is deliberately NOT a field here: the template defines the bar, and a
    score belongs to a CANDIDATE measured against it (see evaluate_candidate, which stores
    scores per candidate). Putting it on the template would mean one shared score for
    everyone ever interviewed for the role.
    """
    label: str                                  # "Competency / Skill"
    category: ScorecardCategory = ScorecardCategory.SKILL
    # The bar itself -- "5+ years on a production Django codebase". Distinct from
    # `evaluation_criteria`, which is HOW it is measured rather than WHAT is expected.
    expected_level: Optional[str] = None        # "Requirement / Expected Level"
    # What "good" looks like for this row, e.g. "Demonstrates via live coding exercise" --
    # free text because a evaluation method varies far more than a category does.
    evaluation_criteria: Optional[str] = None
    weight: float = 1.0                         # "Weightage"
    max_score: int = SCORE_MAX
    remarks: Optional[str] = None                # the scorecard author's own note on this row


class ScorecardIn(BaseModel):
    request_no: str
    title: Optional[str] = None
    criteria: List[ScorecardCriterionIn]
    managerial: bool = False        # managerial+ roles additionally need MD approval
    notes: Optional[str] = None


class ScorecardUpdate(BaseModel):
    title: Optional[str] = None
    criteria: Optional[List[ScorecardCriterionIn]] = None
    managerial: Optional[bool] = None
    notes: Optional[str] = None


class ScorecardApproveIn(BaseModel):
    decision: Decision = Decision.PASS
    remarks: Optional[str] = None
    signature: str


class ScorecardEvaluateIn(BaseModel):
    """Score one candidate against their requisition's scorecard.

    `scores` is {criterion_label: 1-5}. The weighted total and its band are computed
    server-side -- the browser never derives a figure this module then acts on.
    """
    scores: Dict[str, int]
    remarks: Optional[str] = None
    signature: str


class ReferenceCheckIn(BaseModel):
    uk: str
    referee_name: str
    referee_designation: Optional[str] = None
    referee_organisation: Optional[str] = None
    relationship: Optional[str] = None
    referee_contact: Optional[str] = None
    mode: ReferenceMode = ReferenceMode.PHONE
    checked_on: Optional[str] = None            # YYYY-MM-DD
    responses: Optional[str] = None
    outcome: ReferenceOutcome = ReferenceOutcome.POSITIVE
    remarks: Optional[str] = None


class ReferenceCheckUpdate(BaseModel):
    referee_name: Optional[str] = None
    referee_designation: Optional[str] = None
    referee_organisation: Optional[str] = None
    relationship: Optional[str] = None
    referee_contact: Optional[str] = None
    mode: Optional[ReferenceMode] = None
    checked_on: Optional[str] = None
    responses: Optional[str] = None
    outcome: Optional[ReferenceOutcome] = None
    remarks: Optional[str] = None


class TelephonicScreeningIn(BaseModel):
    """SOP step 5 — the brief telephonic interview by HR.

    Split into what the call ESTABLISHES (notice period, expectation, location,
    availability — facts the candidate stated) and what the caller JUDGED (the four rated
    dimensions). Mixing them would let a rating stand in for a fact, and "seemed available"
    is not an availability date anybody can plan a joining around.
    """
    uk: str
    screened_on: Optional[str] = None            # YYYY-MM-DD, defaults to today
    duration_minutes: Optional[int] = None
    # What the candidate said.
    notice_period_days: Optional[int] = None
    expected_ctc: Optional[float] = None
    current_location: Optional[str] = None
    availability: Optional[str] = None
    # What the caller judged, 1-5 each.
    communication: Optional[float] = None
    role_understanding: Optional[float] = None
    motivation: Optional[float] = None
    suitability: Optional[float] = None
    outcome: TelephonicOutcome = TelephonicOutcome.PASSED
    comments: Optional[str] = None


class TelephonicScreeningUpdate(BaseModel):
    screened_on: Optional[str] = None
    duration_minutes: Optional[int] = None
    notice_period_days: Optional[int] = None
    expected_ctc: Optional[float] = None
    current_location: Optional[str] = None
    availability: Optional[str] = None
    communication: Optional[float] = None
    role_understanding: Optional[float] = None
    motivation: Optional[float] = None
    suitability: Optional[float] = None
    outcome: Optional[TelephonicOutcome] = None
    comments: Optional[str] = None


class HolidayIn(BaseModel):
    """One non-working day on this company's HRMS calendar (Phase INT-6)."""
    holiday_date: str                              # YYYY-MM-DD
    holiday_name: str


class HolidayImportIn(BaseModel):
    """Adopt dates from the ERP's global holidays master into THIS company's calendar.

    A copy, deliberately, not a live read: the ERP master carries no company_id, so a live
    dependency would let one admin's edit move another entity's SLA due dates.
    """
    year: Optional[int] = None                     # defaults to the current year


class ConfigUpdateIn(BaseModel):
    """A PATCH of the company rule set (Phase INT-5).

    Every field optional, and a map is merged per name rather than replacing the group --
    overriding one SLA target must not silently drop the other three. Validated against
    CONFIG_SPEC in hrms_config_service, not here: the bounds and the cross-field rules live
    with the table that declares them.
    """
    sla_target_days: Optional[dict] = None
    retention_years: Optional[dict] = None
    probation_months: Optional[dict] = None
    probation_reminder_days: Optional[list] = None
    score_bands: Optional[dict] = None
    honour_holidays: Optional[bool] = None


class ConfigResetIn(BaseModel):
    """Stop overriding some settings, or all of them when `keys` is omitted."""
    keys: Optional[list] = None


# -- Phase INT-10  Salary negotiation (SOP step 9, spec §16) --------------------------------
# The RULE was always enforced: `assert_within_band` refuses an offer outside the band
# stamped at the budget gate. What was missing was the RECORD -- the rounds, what the
# candidate asked for, what was proposed, and how each proposal sat against the band -- which
# is what spec §16 asks to *display*, and what an auditor asks to *see*.
#
# THE GATE DOES NOT MOVE. Recording a round decides nothing; `assert_within_band` at the offer
# remains the control, and an above-band round still needs a fresh approval (an approved
# Offer Outside Budget exception, or a re-approved budget). The record is the history.
NEGOTIATION_WITHIN = "within"
NEGOTIATION_ABOVE  = "above"
NEGOTIATION_BELOW  = "below"
NEGOTIATION_VERDICTS = (NEGOTIATION_WITHIN, NEGOTIATION_ABOVE, NEGOTIATION_BELOW)

# Enough rounds that a real negotiation never hits it, few enough that a loop cannot fill
# the collection.
MAX_NEGOTIATION_ROUNDS = 12

AUDIT_NEGOTIATION_RECORDED = "salary negotiation round recorded"
ENTITY_NEGOTIATION = "negotiation"


def negotiation_verdict(proposed, band_min, band_max) -> Optional[str]:
    """within / above / below for a proposed figure against a band, or None if unbanded.

    Pure, and the ONE reading of "is this inside the budget" the record uses. It deliberately
    mirrors the comparison `assert_within_band` makes, so the verdict on a round and the
    refusal at the offer can never disagree about the same number.
    """
    if proposed is None or band_min is None or band_max is None:
        return None
    try:
        value, low, high = float(proposed), float(band_min), float(band_max)
    except (TypeError, ValueError):
        return None
    # NaN compares False to everything, so without this it would fall through every test
    # below and read as "within" -- the one input on which this and the offer gate would
    # disagree. Not a verdict, and never "within".
    import math
    if not (math.isfinite(value) and math.isfinite(low) and math.isfinite(high)):
        return None
    if value < low:
        return NEGOTIATION_BELOW
    if value > high:
        return NEGOTIATION_ABOVE
    return NEGOTIATION_WITHIN


class NegotiationRoundIn(BaseModel):
    """One round of salary negotiation with one candidate.

    `allow_inf_nan=False` at the boundary: a NaN is accepted by a bare `float` field, reads
    as "within" every comparison, and is unserialisable -- one crafted request would leave a
    document that 500s every read of the board. Refused here AND in the service.
    """
    uk: str
    proposed_ctc: float = Field(..., gt=0, allow_inf_nan=False)
    candidate_expectation: Optional[float] = Field(None, gt=0, allow_inf_nan=False)
    notes: Optional[str] = None


# -- Phase INT-10  Interview notice (Annexure C: "Confirm interview logistics ... at least
# 24 hours in advance") -----------------------------------------------------------------
# WARN, NEVER BLOCK -- the same rule interview windows follow. A hard refusal at 4pm on a
# Friday for a Monday-morning interview would push the booking off-system, where nothing
# sees it. So short notice is recorded on the interview (`notice_hours`, `short_notice`),
# warned about in the response, and measurable afterwards.
INTERVIEW_NOTICE_HOURS = 24


class OfferApproveIn(BaseModel):
    """Annexure B marks offer approval "A" for Management/Finance, and mandatory."""
    remarks: Optional[str] = None
    signature: str


class ProbationIn(BaseModel):
    employee_code: str
    request_no: Optional[str] = None            # carried so analytics scoping still works
    started_on: Optional[str] = None            # YYYY-MM-DD; defaults to the joining date
    duration_months: int = DEFAULT_PROBATION_MONTHS
    reviewer_id: Optional[str] = None
    notes: Optional[str] = None


class ProbationUpdate(BaseModel):
    started_on: Optional[str] = None
    duration_months: Optional[int] = None
    reviewer_id: Optional[str] = None
    rating: Optional[float] = None              # against the position scorecard, 1-5
    notes: Optional[str] = None


class ProbationReviewIn(BaseModel):
    """The reporting manager's review and recommendation (§7.5 Stage 12).

    Scores are 1-5 on the five criteria PROBATION_REVIEW_CRITERIA names. They are required
    because a recommendation with no assessment behind it is an opinion, and this review
    can end somebody's employment.
    """
    performance: float
    conduct: float
    attendance: float
    competence: float
    suitability: float
    recommendation: ProbationRecommendation
    remarks: Optional[str] = None
    signature: str


class ProbationHrReviewIn(BaseModel):
    """HR's step between the manager's recommendation and the authorised approval."""
    decision: HrReviewDecision
    remarks: Optional[str] = None
    signature: str


class ProbationConfirmIn(BaseModel):
    outcome: ProbationOutcome
    rating: Optional[float] = None
    extended_to: Optional[str] = None           # required when the outcome is Extended
    # §7.5 Stage 12, Confirm branch: the date the confirmation takes effect. Distinct
    # from the day it was signed -- a decision taken late still takes effect from the day
    # probation ended, and pay and benefits run from this date, not the signature date.
    effective_from: Optional[str] = None
    # Extend branch: when the next review falls due, so an extension is not open-ended.
    next_review_on: Optional[str] = None
    remarks: Optional[str] = None
    signature: str


class ExceptionIn(BaseModel):
    request_no: str
    exception_type: ExceptionType
    reason: str
    uk: Optional[str] = None                    # when candidate-specific
    linked_entity: Optional[str] = None         # e.g. the offer_no this would unblock
    # SOP section 6: an Offer Outside Budget request is a request for A FIGURE. Asking
    # Finance to approve "more money" and then reading the approval as "any money" is the
    # hole this closes -- see SALARY_EXCEPTION_NEEDS_AMOUNT.
    requested_ctc: Optional[float] = None


class ExceptionDecisionIn(BaseModel):
    decision: ExceptionStatus
    remarks: Optional[str] = None
    signature: str
    # Finance may grant LESS than was asked for ("I will go to 13, not 15"). Left empty, an
    # approval grants exactly what was requested.
    approved_ctc: Optional[float] = None


# Exception types whose whole meaning is a number, so an approval that does not carry one
# would be an unbounded permission. Declared as a set rather than tested inline, so adding a
# second money-shaped exception later cannot forget the rule.
SALARY_EXCEPTION_NEEDS_AMOUNT = {ExceptionType.OFFER_OUTSIDE_BUDGET.value}


def salary_exception_ceiling(exception: Optional[dict]) -> Optional[float]:
    """The highest CTC an approved Offer Outside Budget exception authorises.

    None means "this exception does not bound the figure" -- which is true only of rows
    written before the amount was recorded. Everything raised since carries one, and
    `assert_within_band` treats a missing ceiling as the legacy case rather than as
    permission for anything.
    """
    if not exception:
        return None
    for field in ("approved_ctc", "requested_ctc"):
        value = (exception or {}).get(field)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


class ClientNeedMappingIn(BaseModel):
    """SOP section 7 step 1 -- the Need Mapping Form, filled by the client.

    Only the fields the SOP names: business context, the role need, urgency, and what the
    client expects from the engagement. Nothing is inferred and nothing extra is asked for.
    """
    business_context: str
    role_need: str
    urgency: ClientReqUrgency = ClientReqUrgency.NORMAL
    engagement_expectations: Optional[str] = None


class ClientManpowerRequisitionIn(BaseModel):
    """SOP section 7 step 2 -- the Manpower Requisition Form, confirmed by the client."""
    role_title: str
    department_name: str
    reporting_line: str
    salary_range_min: float
    salary_range_max: float
    employment_type: EmploymentTypeClient = EmploymentTypeClient.PERMANENT
    urgency: Optional[ClientReqUrgency] = None
    vacancies: int = 1
    role_level: Optional[ClientRoleLevel] = None


class ClientRequisitionUpdate(BaseModel):
    """Amend either form while the requisition is still with the client."""
    business_context: Optional[str] = None
    role_need: Optional[str] = None
    engagement_expectations: Optional[str] = None
    role_title: Optional[str] = None
    department_name: Optional[str] = None
    reporting_line: Optional[str] = None
    salary_range_min: Optional[float] = None
    salary_range_max: Optional[float] = None
    employment_type: Optional[EmploymentTypeClient] = None
    urgency: Optional[ClientReqUrgency] = None
    vacancies: Optional[int] = None
    role_level: Optional[ClientRoleLevel] = None


class ClientRequisitionAction(BaseModel):
    """One move along CLIENT_REQ_TRANSITIONS.

    The three feasibility assessments are REQUIRED on an approval: SOP section 7 step 3
    names them, and an approval that records no assessment is a click, not a review.
    """
    action: str
    remarks: Optional[str] = None
    role_clarity: Optional[bool] = None
    compensation_competitive: Optional[bool] = None
    timeline_realistic: Optional[bool] = None


class ClientJoiningIn(BaseModel):
    """Open pre-boarding for a candidate whose written acceptance is on record."""
    ccn_no: str
    joining_date: Optional[str] = None


class ClientTouchpointIn(BaseModel):
    """SOP section 19 -- one periodic contact during pre-boarding."""
    contacted_on: Optional[str] = None
    channel: Optional[str] = None
    at_risk: bool = False
    notes: Optional[str] = None


class ClientJoiningUpdate(BaseModel):
    joining_date: Optional[str] = None
    client_requirements_ready: Optional[bool] = None
    # Section 20 -- the post-joining results shared with the client.
    background_check_result: Optional[str] = None
    culture_score: Optional[float] = None
    handover_note: Optional[str] = None
    candidate_file: Optional[bool] = None
    scorecards: Optional[bool] = None
    interview_records: Optional[bool] = None
    verification_status: Optional[bool] = None


class ClientJoiningAction(BaseModel):
    action: str
    remarks: Optional[str] = None
    actual_joining_date: Optional[str] = None
    acknowledged: Optional[bool] = None


class ClientReferenceCheckIn(BaseModel):
    """SOP section 15 -- last employer, conduct, reason for leaving."""
    ccn_no: str
    referee_name: str
    referee_organisation: Optional[str] = None
    relationship: Optional[str] = None
    referee_contact: Optional[str] = None
    outcome: ClientReferenceOutcome = ClientReferenceOutcome.POSITIVE
    checked_on: Optional[str] = None
    remarks: Optional[str] = None


class ClientOfferIn(BaseModel):
    """SOP section 16 -- the terms, prepared against the client's approved range."""
    ccn_no: str
    offered_ctc: float
    joining_date: Optional[str] = None
    designation: Optional[str] = None
    terms: Optional[str] = None


class ClientOfferUpdate(BaseModel):
    offered_ctc: Optional[float] = None
    joining_date: Optional[str] = None
    designation: Optional[str] = None
    terms: Optional[str] = None
    negotiation_notes: Optional[str] = None


class ClientOfferAction(BaseModel):
    action: str
    remarks: Optional[str] = None
    # Section 17: the recruiter confirms written acceptance AND the joining date.
    accepted_on: Optional[str] = None
    joining_date: Optional[str] = None


class ClientInterviewIn(BaseModel):
    """Schedule the recorded panel interview (SOP section 12)."""
    ccn_no: str
    scheduled_at: str                              # ISO datetime
    mode: Optional[str] = "Virtual"
    meeting_link: Optional[str] = None
    panel: List[str] = Field(default_factory=list)  # Sparsh's panel, by name


class ClientInterviewUpdate(BaseModel):
    scheduled_at: Optional[str] = None
    mode: Optional[str] = None
    meeting_link: Optional[str] = None
    panel: Optional[List[str]] = None
    # The recorded-platform link section 14 shares with the client.
    recording_link: Optional[str] = None
    role_fit: Optional[float] = None
    communication: Optional[float] = None
    technical_depth: Optional[float] = None
    culture_fit: Optional[float] = None
    outcome: Optional[str] = None                  # Recommend / Do Not Recommend
    panel_notes: Optional[str] = None


class ClientInterviewAction(BaseModel):
    action: str
    remarks: Optional[str] = None


class ClientAssessmentIn(BaseModel):
    """Issue the Talent Fit Assessment to a candidate the client has approved."""
    ccn_no: str
    title: str
    instructions: Optional[str] = None
    due_on: Optional[str] = None                  # YYYY-MM-DD
    max_score: float = 5.0


class ClientAssessmentUpdate(BaseModel):
    title: Optional[str] = None
    instructions: Optional[str] = None
    due_on: Optional[str] = None
    submission_reference: Optional[str] = None
    score: Optional[float] = None
    result: Optional[str] = None                  # Pass / Fail, the evaluator's call
    evaluator_notes: Optional[str] = None


class ClientAssessmentAction(BaseModel):
    action: str
    remarks: Optional[str] = None


class ClientCandidateIn(BaseModel):
    """SOP section 10 -- a candidate sourced against an approved requisition."""
    cr_no: str
    candidate_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    cv_reference: Optional[str] = None
    current_employer: Optional[str] = None
    notice_period: Optional[str] = None
    current_ctc: Optional[float] = None
    expected_ctc: Optional[float] = None


class ClientCandidateUpdate(BaseModel):
    candidate_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    cv_reference: Optional[str] = None
    current_employer: Optional[str] = None
    notice_period: Optional[str] = None
    current_ctc: Optional[float] = None
    expected_ctc: Optional[float] = None
    # SOP section 13 -- the three scores, recorded as they are established.
    tfs_score: Optional[float] = None
    competency_score: Optional[float] = None
    pi_score: Optional[float] = None
    screening_notes: Optional[str] = None


class ClientCandidateAction(BaseModel):
    """One move along CLIENT_CANDIDATE_TRANSITIONS."""
    action: str
    remarks: Optional[str] = None


class ClientPostingIn(BaseModel):
    """Draft a job posting against a requisition whose scorecard the client approved."""
    cr_no: str
    title: Optional[str] = None            # defaults to the requisition's role title
    summary: Optional[str] = None
    responsibilities: Optional[str] = None
    requirements: Optional[str] = None
    location: Optional[str] = None
    # The band is the CLIENT's to disclose. Off unless they say otherwise.
    show_salary: bool = False


class ClientPostingUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    responsibilities: Optional[str] = None
    requirements: Optional[str] = None
    location: Optional[str] = None
    show_salary: Optional[bool] = None


class ClientPostingAction(BaseModel):
    action: str
    remarks: Optional[str] = None


class ClientApplicationIn(BaseModel):
    """A public application. Every field is untrusted -- see the posting service."""
    candidate_name: str
    email: str
    phone: str
    cv_reference: Optional[str] = None
    current_employer: Optional[str] = None
    notice_period: Optional[str] = None
    declaration: bool = False


class ClientPoolSourceIn(BaseModel):
    """Source somebody from the available pool into a different requisition.

    `from_company_id` is not optional: business ids are minted per company, so `ccn_no`
    alone names a different person in every engagement.
    """
    ccn_no: str
    from_company_id: str
    cr_no: str


class ClientScorecardIn(BaseModel):
    """SOP section 4 -- the five things a Position Scorecard describes.

    Drafted by the recruiter against an ACTIVATED requisition. Nothing here is optional at
    approval time; the completeness check runs when it is submitted, so a half-written
    draft can still be saved and returned to.
    """
    cr_no: str
    responsibilities: Optional[str] = None
    skills: Optional[str] = None
    experience: Optional[str] = None
    cultural_expectations: Optional[str] = None
    success_indicators: Optional[str] = None


class ClientScorecardUpdate(BaseModel):
    responsibilities: Optional[str] = None
    skills: Optional[str] = None
    experience: Optional[str] = None
    cultural_expectations: Optional[str] = None
    success_indicators: Optional[str] = None


class ClientScorecardAction(BaseModel):
    """One move along CLIENT_SCORECARD_TRANSITIONS."""
    action: str
    remarks: Optional[str] = None


class PersonnelFileCloseIn(BaseModel):
    employee_code: str
    closure_note: str


# =============================================================
# Phase INT-2 — the remaining Internal Recruitment SOP controls
# =============================================================
# Everything below is ADDITIVE and internal-track only. No client-track requisition enters
# any of it: the panel and final-round gates return early on the client track, the
# shortlisting committee refuses a client requisition outright, and the pre-boarding,
# survey and policy surfaces are governance records with no client-track counterpart.

# -- INT-2.1  Interview governance (SOP §5) ------------------------------------------
# WHO MUST BE IN THE ROOM, as a table rather than code branching.
#
# SOP §5: "Interviews shall be conducted by a panel comprising HR and the Department Head,
# with Management joining for managerial and above." A chain of ifs would put the rule in
# four places (the scheduler, the picker, the tests and the docs); a table puts it in one,
# and adding a level later is a data change.
#
# The roles named are HRMS roles, so the check reads the same vocabulary every capability
# check does -- there is no second notion of "who counts as HR" anywhere in this module.
REQUIRED_PANEL_ROLES = {
    DesignationLevel.JUNIOR:     [HrmsRole.HR, HrmsRole.MANAGER],
    DesignationLevel.MID:        [HrmsRole.HR, HrmsRole.MANAGER],
    DesignationLevel.SENIOR:     [HrmsRole.HR, HrmsRole.MANAGER, HrmsRole.MD],
    DesignationLevel.MANAGERIAL: [HrmsRole.HR, HrmsRole.MANAGER, HrmsRole.MD],
}


def required_panel_roles(level) -> list:
    """The roles a panel must cover for this seniority band.

    Returned as a LIST, in the order the SOP states them, so the UI can show "still needed:
    HR, Management" in a stable order rather than whatever a set happens to iterate in.
    An unknown band falls back to the default band's requirement rather than to an empty
    list: failing OPEN here would make the whole control optional for any designation
    somebody forgot to band.
    """
    try:
        band = DesignationLevel(getattr(level, "value", level))
    except (ValueError, TypeError):
        band = DEFAULT_DESIGNATION_LEVEL
    return list(REQUIRED_PANEL_ROLES[band])


def final_round_is_mandatory(level) -> bool:
    """Whether SOP §5's Management final round applies to this band.

    Asserted from MANAGERIAL_LEVELS rather than re-listing the bands, so this and the panel
    table cannot drift. The test walks every band against both.
    """
    return is_managerial_level(level)


# The round that satisfies the mandatory Management final interview. Named here rather than
# hard-coded in the service, so "which round IS the final one" is answerable from the model.
FINAL_ROUND = InterviewRound.MD
# The outcome that counts as having PASSED it. A Hold is not a pass -- it is a decision
# deferred, and treating it as clearance would let an undecided candidate reach an offer.
FINAL_ROUND_PASSING = {Outcome.PASS.value}


class ShortlistOutcome(str, Enum):
    """What the committee decided -- the Final Commit.

    The three live values are NOT a menu somebody picks from. They are derived by
    `final_commit_outcome` from the members' own verdicts and the seniority of the role, so
    the record can never say "Selected" about a sitting where the Department Head objected.
    Offering them as a free choice is what made the old two-value dropdown misleading: it
    asked for a conclusion instead of the facts the conclusion follows from.
    """
    PENDING  = "Pending"          # convened, not yet decided
    SELECTED = "Selected"         # both approved, and no final round stands in the way
    REJECTED = "Rejected"         # at least one approver did not agree
    FINAL_INTERVIEW_REQUIRED = "Final Interview Required"

    # -- Legacy, read-only -------------------------------------------------------------
    # Sittings decided before Final Commit existed. They are still valid records and must
    # keep clearing the selection gate (see SHORTLIST_CLEARS_SELECTION); what they may not
    # do is be chosen for a NEW decision. Rewriting them to the new vocabulary would be
    # forging minutes -- "Finalised" is what that committee actually resolved.
    FINALISED = "Finalised"
    DEFERRED  = "Deferred"


# Outcomes that may be recorded by a new sitting. PENDING is the starting state, and the two
# legacy values are history, so neither belongs in a decision control.
SHORTLIST_LIVE_OUTCOMES = (
    ShortlistOutcome.SELECTED,
    ShortlistOutcome.REJECTED,
    ShortlistOutcome.FINAL_INTERVIEW_REQUIRED,
)

# What satisfies the gate on `Selected`.
#
# FINAL_INTERVIEW_REQUIRED belongs here, and leaving it out is a trap worth naming. This gate
# asks ONE question: did HR and the Department Head agree this person goes forward? A commit
# that routed to the final interview is a YES to exactly that -- what it withheld was the
# Management round, which `assert_final_round_complete` asks about separately and in its own
# right. Admitting only SELECTED would strand every managerial candidate the moment they
# passed the round the commit sent them to: the committee had approved them, and the gate
# would still say it had not.
#
# FINALISED is here because that is what it meant when it was recorded. Dropping it would
# retrospectively invalidate every sitting held before Final Commit existed.
SHORTLIST_CLEARS_SELECTION = {
    ShortlistOutcome.SELECTED.value,
    ShortlistOutcome.FINAL_INTERVIEW_REQUIRED.value,
    ShortlistOutcome.FINALISED.value,
}

# A sitting that ended the candidate's run. Kept as a set so "did the committee turn them
# down" is one lookup rather than a comparison somebody can get backwards.
SHORTLIST_REJECTS = {ShortlistOutcome.REJECTED.value}


class CommitteeDecision(str, Enum):
    AGREE  = "Agree"
    OBJECT = "Object"


def final_commit_outcome(members, *, level=None, final_round_passed: bool = False):
    """The Final Commit decision, derived. Pure -- no I/O, so the rule is testable alone.

    The SOP's logic, in order:

      1. Every active approver must agree. One objection from either side is a rejection,
         not a tie to be broken later: the committee is HR AND the Department Head, and a
         shortlist one of them refused is not a shortlist.
      2. For a managerial-or-above role, agreement is not selection. SOP section 5 puts a
         mandatory Management final round in the way, so the commit routes there instead.
      3. If that round has already been sat and passed, there is nothing left to route to
         and the commit is a selection.

    A RECUSED member is not an approver. They stood down, so their silence is neither an
    objection nor an agreement -- the same treatment `committee_state` gives them when it
    works out whether the committee is quorate at all.
    """
    active = [m for m in (members or []) if not (m or {}).get("recused")]
    if any((m or {}).get("decision") == CommitteeDecision.OBJECT.value for m in active):
        return ShortlistOutcome.REJECTED
    if final_round_is_mandatory(level) and not final_round_passed:
        return ShortlistOutcome.FINAL_INTERVIEW_REQUIRED
    return ShortlistOutcome.SELECTED


# SOP §5 requires HR AND the Department Head to finalise candidates. Two ROLES, and -- the
# part that makes it a control rather than a formality -- two different PEOPLE. Exactly the
# rule hrms_scorecard_service._approval_state already enforces for a managerial scorecard,
# reused here rather than re-derived.
SHORTLIST_COMMITTEE_ROLES = [HrmsRole.HR, HrmsRole.MANAGER]
SHORTLIST_MIN_MEMBERS = 2

AUDIT_SHORTLIST_CONVENED = "shortlisting committee convened"
AUDIT_SHORTLIST_DECIDED  = "shortlisting committee decision recorded"
ENTITY_SHORTLIST = "shortlist_review"


# -- Batch interview windows (Annexure C) ---------------------------------------------
# "Schedule interviews in batches to reduce panel disruption."
#
# A WARNING, never a refusal. A hard block on out-of-window scheduling would make an urgent
# hire impossible at 4pm on a Friday, which is precisely when an urgent hire happens. The
# response carries the warning; the booking goes through.
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

AUDIT_WINDOW_CREATED = "interview window defined"
AUDIT_WINDOW_UPDATED = "interview window updated"
AUDIT_WINDOW_DELETED = "interview window removed"
ENTITY_INTERVIEW_WINDOW = "interview_window"

# HH:MM, 24-hour. Validated as a shape before it is compared, so a window can never be
# stored in a form the comparison silently reads as "never matches".
TIME_RE = _re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# -- INT-2.3  Pre-boarding engagement (SOP §6) -----------------------------------------
# The window between "they accepted" and "they walked in" is where an offer is lost to a
# counter-offer. The SOP names the practice; this records it.
#
# NOTHING IS GATED ON IT. It is engagement tracking, not a control: a candidate with no
# touchpoint still onboards exactly as they always did. What it does is put them on a due
# list and raise a flag when somebody says they are wavering.
class PreboardingMode(str, Enum):
    CALL     = "Call"
    EMAIL    = "Email"
    WHATSAPP = "WhatsApp"
    MEETING  = "Meeting"


class PreboardingSentiment(str, Enum):
    POSITIVE = "Positive"
    NEUTRAL  = "Neutral"
    AT_RISK  = "At Risk"


# Candidate stages that are IN the pre-boarding window: they have accepted and have not yet
# joined. A candidate outside these is not "overdue a touchpoint", they are simply not in
# this phase of the process.
PREBOARDING_STATUSES = {
    AppStatus.OFFER_ACCEPTED, AppStatus.APPOINTMENT_LETTER_SENT, AppStatus.PRE_ONBOARDING,
}

# How long a candidate in that window may go without contact before they appear on
# `GET /preboarding/due`. Seven days, because the SOP's practice is weekly contact and a
# tighter figure would fill the list with people somebody spoke to on Friday.
PREBOARDING_CONTACT_DAYS = 7

AUDIT_PREBOARDING_LOGGED = "pre-boarding touchpoint recorded"
ENTITY_PREBOARDING = "preboarding_touchpoint"


# -- INT-2.5  The standing salary-band master (Annexure C) -----------------------------
# "Pre-define standard salary bands per role/grade with Finance annually, so individual
# requisitions don't need a fresh budget discussion each time."
#
# THE MASTER IS A CONVENIENCE, NEVER AN AUTHORITY. The budget gate pre-fills from it; the
# offer check reads the band STAMPED ON THE REQUISITION and never this table. That
# separation is the whole design: a master edited in April must not retroactively legalise
# an offer approved in March.
class SalaryBandStatus(str, Enum):
    ACTIVE      = "Active"
    SUPERSEDED  = "Superseded"   # replaced by a newer band for the same position
    RETIRED     = "Retired"      # withdrawn without a replacement


# Where the band on a requisition came from. Stamped at the budget gate so a reader can tell
# "Finance's standing figure" from "the approver typed something else", and the second case
# is required to carry a reason.
BAND_SOURCE_MASTER = "master"
BAND_SOURCE_MANUAL = "manual"

AUDIT_SALARY_BAND_CREATED    = "salary band published"
AUDIT_SALARY_BAND_UPDATED    = "salary band updated"
AUDIT_SALARY_BAND_SUPERSEDED = "salary band superseded"
ENTITY_SALARY_BAND = "salary_band"


# -- INT-2.6  Talent pool (Annexure C) --------------------------------------------------
# "Build and maintain an internal talent pool of prior applicants and referrals."
#
# The compliance shape matters more than the feature. A CV kept because it is "in the pool"
# past the retention period the candidate consented to is exactly the failure SOP §11 and
# §13 exist to prevent -- so consent is REQUIRED to enter the pool, and the consent expiry
# may never outlive `retention_until`. Enforced in the service; stated here.
AUDIT_TALENT_POOL_ADDED   = "candidate added to the talent pool"
AUDIT_TALENT_POOL_REMOVED = "candidate removed from the talent pool"

MAX_TALENT_POOL_TAGS = 12


# -- INT-2.7  Candidate communications (Annexure C) -------------------------------------
# Four commitments the SOP makes to applicants and nothing implemented them: acknowledge
# every application, keep them updated, tell them when they are out, and put the offer terms
# in writing before the formal letter.
#
# Delivery goes through hrms_notify_service. There is deliberately no second mail path --
# the module already learned that lesson once (see that module's docstring on the source's
# hrms_email_outbox).
class CommChannel(str, Enum):
    EMAIL = "email"
    INAPP = "inapp"


class CommStatus(str, Enum):
    SENT    = "Sent"
    FAILED  = "Failed"
    SKIPPED = "Skipped"       # no address / no template / suppressed in a seed run


# The six seeded templates. Seeded on FIRST READ for a company that has none, exactly as
# DEFAULT_DOCUMENT_TYPES are -- so a company that never opens the screen still gets working
# copy, and one that edits it is never overwritten.
#
# `{placeholders}` are filled by render_comm_body, which uses the same defaulting format_map
# render_offer_body does: an unknown placeholder renders harmlessly rather than raising.
#
# The EEO and data-use wording lives here (not in code) for the reason INT-2.10 requires:
# legal must be able to change it without a deploy.
# (key, channel, subject, body, variables)
DEFAULT_COMM_TEMPLATES = [
    ("application_acknowledged", CommChannel.EMAIL,
     "We have received your application for {designation}",
     "Dear {candidate_name},\n\n"
     "Thank you for applying for {designation}. Your application has been received and is "
     "with our recruitment team.\n\n"
     "We review every application we receive. If your profile matches what the role needs, "
     "we will be in touch to arrange a conversation. If we do not progress your application "
     "this time, we will tell you.\n\n"
     "Reference: {reference}\n\n"
     "Regards,\n{company}",
     ["candidate_name", "designation", "reference", "company"]),

    ("stage_update", CommChannel.EMAIL,
     "An update on your application for {designation}",
     "Dear {candidate_name},\n\n"
     "Your application for {designation} has moved to: {stage}.\n\n"
     "{note}\n\n"
     "Regards,\n{company}",
     ["candidate_name", "designation", "stage", "note", "company"]),

    ("interview_scheduled", CommChannel.EMAIL,
     "Your interview for {designation}",
     "Dear {candidate_name},\n\n"
     "We would like to invite you to the {round} for {designation}.\n\n"
     "When: {when}\nWhere: {where}\n\n"
     "If that time does not work for you, reply to this message and we will find another.\n\n"
     "Regards,\n{company}",
     ["candidate_name", "designation", "round", "when", "where", "company"]),

    ("rejection_closure", CommChannel.EMAIL,
     "Your application for {designation}",
     "Dear {candidate_name},\n\n"
     "Thank you for the time you gave to your application for {designation}.\n\n"
     "On this occasion we will not be taking it further. The decision reflects the fit "
     "between the role's requirements and the profiles we saw; it is not a judgement on your "
     "wider experience.\n\n"
     "We are grateful you considered us, and we wish you well.\n\n"
     "Regards,\n{company}",
     ["candidate_name", "designation", "company"]),

    ("offer_summary", CommChannel.EMAIL,
     "Summary of the offer we intend to make you",
     "Dear {candidate_name},\n\n"
     "Ahead of the formal letter, here is a summary of what we intend to offer:\n\n"
     "Role: {designation}\nAnnual cost to company: {ctc}\nProposed joining date: "
     "{joining_date}\nLocation: {location}\n\n"
     "This summary is for your review; the formal offer letter follows and is the binding "
     "document. Do come back to us with any questions before then.\n\n"
     "Regards,\n{company}",
     ["candidate_name", "designation", "ctc", "joining_date", "location", "company"]),

    # ── BA Functional Design §7.5 ── "Send Secure Onboarding Portal / Task List", the step
    # that follows "Create Pre-Joiner Case". The link is single-purpose and tied to the
    # onboarding record, which is why it is sent rather than a login being issued.
    ("onboarding_portal", CommChannel.EMAIL,
     "Your joining formalities for {designation}",
     "Dear {candidate_name},\n\n"
     "Welcome aboard. Now that you have accepted our offer, the next step is to complete "
     "your joining formalities.\n\n"
     "Use this secure link to upload your documents and confirm your details:\n"
     "{portal_link}\n\n"
     "What we need from you:\n{task_list}\n\n"
     "The link is personal to you -- please do not forward it. If anything is unclear, "
     "reply to this message.\n\n"
     "Regards,\n{company}",
     ["candidate_name", "designation", "portal_link", "task_list", "company"]),

    ("preboarding_checkin", CommChannel.EMAIL,
     "Looking forward to {joining_date}",
     "Dear {candidate_name},\n\n"
     "We are looking forward to you joining us on {joining_date} as {designation}.\n\n"
     "If anything has changed, or if there is anything you need from us before then, reply "
     "to this message -- we would much rather know early.\n\n"
     "Regards,\n{company}",
     ["candidate_name", "designation", "joining_date", "company"]),
]

# The equal-opportunity and data-use statements shown on the public application form (SOP
# §11). They are TEMPLATES rather than constants precisely so legal can edit the wording
# without a deploy -- the same reason the letters above are.
CONSENT_TEMPLATES = [
    ("consent_equal_opportunity", CommChannel.INAPP,
     "Equal opportunity",
     "We consider every application on merit. We do not discriminate on the basis of "
     "gender, marital status, religion, caste, disability, age or any other protected "
     "characteristic. Tick to confirm you have read this.",
     []),
    ("consent_data_use", CommChannel.INAPP,
     "How we use your information",
     "We will hold the information in this application for as long as we need it to "
     "consider you for this role, and no longer than our published retention period. We "
     "will not share it outside the hiring team without asking you. Tick to confirm you "
     "have read this and consent to us processing your application.",
     []),
]

# Templates fired automatically by a pipeline event, and the event that fires each. Declared
# as data so the wiring is readable in one place rather than inferred from five call sites.
AUTO_COMM_EVENTS = {
    "application_received": "application_acknowledged",
    "screening_rejected":   "rejection_closure",
    # ── Phase INT-10 ── Annexure C: "Confirm interview logistics (panel, duration, mode) at
    # least 24 hours in advance." Fired on every schedule AND reschedule, because a moved
    # interview is a new set of logistics the candidate has not been told.
    "interview_scheduled":  "interview_scheduled",
    # ── BA Functional Design §7.5 ── fired when the pre-joiner case opens, which is itself
    # fired by the offer being accepted. Automatic because the candidate cannot start their
    # joining formalities until they have the link.
    "onboarding_started":   "onboarding_portal",
}

# Templates that are only ever sent by hand. `offer_summary` is here deliberately: writing to
# a candidate about money is a decision, not a side effect of a status change.
MANUAL_COMM_TEMPLATES = {"offer_summary", "stage_update", "preboarding_checkin"}

AUDIT_COMM_SENT             = "candidate communication sent"
AUDIT_COMM_TEMPLATE_UPDATED = "communication template updated"
ENTITY_COMM = "communication"


def render_comm_body(template: str, values: dict) -> str:
    """Fill the placeholders in a communication template.

    Same mechanism, and the same reasoning, as render_offer_body: a plain format_map with a
    defaulting dict, so an operator-edited template containing an unknown or mistyped
    placeholder renders harmlessly rather than raising or executing anything.
    """
    class _Safe(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    try:
        return (template or "").format_map(
            _Safe({k: ("" if v is None else str(v)) for k, v in (values or {}).items()}))
    except (ValueError, IndexError):
        return template or ""


# -- INT-2.8  New-hire experience surveys (SOP §10) --------------------------------------
# Two of the SOP's KPIs are unbuildable without capture: new-hire satisfaction, and an
# induction feedback SCORE where the checklist only records that feedback happened.
#
# -- Pseudonymous to the reporting layer, and that is a hard rule --------------------------
# `employee_code` is stored for ONE purpose: stopping the same person answering twice (the
# unique index above). The analytics aggregation returns SCORES ONLY, never rows, and
# refuses any breakdown with fewer than SURVEY_MIN_RESPONSES answers. A satisfaction survey
# a manager can de-anonymise measures nothing except how much people trust the survey.
class SurveyKind(str, Enum):
    INDUCTION = "induction"
    PROBATION = "probation"


# The smallest group whose average may be shown. Five is the usual small-cell threshold; the
# point is that below it a reader who knows the team can attribute an answer.
SURVEY_MIN_RESPONSES = 5
SURVEY_SUPPRESSED = (
    f"Fewer than {SURVEY_MIN_RESPONSES} responses. Individual answers would be "
    f"identifiable, so no figure is shown.")

SURVEY_SCORE_MIN = 1
SURVEY_SCORE_MAX = 5

# The two seeded instruments. (kind, title, intro, [(question_key, prompt)])
# Deliberately short: a fifteen-question form on day one is a form nobody finishes, and an
# unfinished form is worse data than five honest answers.
DEFAULT_SURVEYS = [
    (SurveyKind.INDUCTION, "Your first days with us",
     "Five quick questions about how your joining went. Your answers are reported as "
     "averages only -- nobody sees your individual response.",
     [("welcome",     "I felt welcomed and expected on my first day."),
      ("clarity",     "It was clear what my role is and what is expected of me."),
      ("systems",     "The systems, access and equipment I need were ready."),
      ("induction",   "The induction covered what I needed to know."),
      ("overall",     "Overall, my joining experience was a good one.")]),
    (SurveyKind.PROBATION, "Your first months with us",
     "Five questions at the end of your probation. Reported as averages only.",
     [("support",     "I had the support I needed to do my job well."),
      ("feedback",    "I received useful feedback during my probation."),
      ("expectations", "The role matched what I was told at interview."),
      ("development", "I can see how I can develop here."),
      ("overall",     "Overall, I am glad I joined.")]),
]

AUDIT_SURVEY_ISSUED    = "experience survey issued"
AUDIT_SURVEY_SUBMITTED = "experience survey submitted"
ENTITY_SURVEY = "survey"


# -- INT-2.11  The policy register (SOP §14) ---------------------------------------------
# "This policy shall be reviewed annually... All amendments shall be logged in the
# Modification History table."
#
# The register answers three questions a review cannot answer without it: which version is
# in force, when it is next due to be looked at, and what changed last time.
class PolicyStatus(str, Enum):
    DRAFT       = "Draft"
    IN_FORCE    = "In Force"
    SUPERSEDED  = "Superseded"
    WITHDRAWN   = "Withdrawn"


# How far ahead a review starts being announced. Thirty days is enough notice to schedule a
# conversation and not so much that the reminder becomes background noise.
POLICY_REVIEW_NOTICE_DAYS = 30
# The SOP's own cycle. A revision approved today sets the next review a year out.
POLICY_REVIEW_MONTHS = 12

# The two policies this module actually implements, seeded on first read so the register is
# never empty on a company that has both tracks running.
# (policy_key, title, version, owner_role)
DEFAULT_POLICIES = [
    ("internal_recruitment", "Sparsh Magic Internal Recruitment Policy & SOP", "1.0",
     HrmsRole.HR),
    ("profit_recruitment",   "Sparsh Magic PRO-fit Recruitment Policy & SOP", "2.0",
     HrmsRole.HR),
]

AUDIT_POLICY_REGISTERED = "policy registered"
AUDIT_POLICY_REVISED    = "policy revision logged"
AUDIT_POLICY_APPROVED   = "policy revision approved"
# ── Phase POLICY-LIB-1 (§22.6) ──
AUDIT_POLICY_APPLICABILITY_SAVED = "policy applicability/category saved"
AUDIT_POLICY_ACKNOWLEDGED        = "policy acknowledged by employee"
AUDIT_POLICY_DOCUMENT_UPLOADED   = "policy document uploaded"
ENTITY_POLICY = "policy"


# -- INT-2.12  Retention purge (SOP §13) --------------------------------------------------
# `retention_until` has been stamped and reported since the internal track shipped, and
# nothing has ever deleted. This builds the job -- but NOT as a silent cron.
#
# Three properties, each of which is the reason the previous phase declined to build it:
#
#  1. A purge is PROPOSED, then approved by a human with a typed signature. The same
#     standard probation confirmation holds, because both destroy or end something.
#  2. It REDACTS rather than hard-deletes wherever a record is referenced by an audit row.
#     An audit trail full of dangling references proves nothing.
#  3. It never touches an open requisition or an active employment, whatever the dates say.
class PurgeBatchStatus(str, Enum):
    PROPOSED  = "Proposed"     # a dry run wrote this; nothing has happened
    APPROVED  = "Approved"     # signed off, execution may proceed
    EXECUTED  = "Executed"
    CANCELLED = "Cancelled"


# What a purge does to each record type, and which fields it clears.
#
# REDACT keeps the id and the audit spine and clears the personal detail. DELETE is reserved
# for rows that are pure PII with nothing referencing them. Every entry here is REDACT today
# -- every HRMS record is referenced by at least an audit row -- and the vocabulary exists so
# a later, deliberate decision to hard-delete something is a data change somebody reviews.
PURGE_REDACT = "redact"
PURGE_DELETE = "delete"

# (collection, id_field, retention_field, mode, [fields to clear])
PURGE_TARGETS = [
    (COLL_CANDIDATES, "uk", "retention_until", PURGE_REDACT,
     ["candidate_name", "can_email", "can_contact", "current_location", "linkedin",
      "portfolio", "cover_note", "resume", "photo", "certificates", "current_company",
      "current_designation",
      "current_ctc", "expected_ctc", "referred_by", "referrer_employee_code",
      "talent_pool_tags"]),
    (COLL_REFERENCE_CHECKS, "ref_no", "retention_until", PURGE_REDACT,
     ["referee_name", "referee_contact", "referee_organisation", "referee_designation",
      "responses", "remarks", "candidate_name"]),
    (COLL_OFFERS, "offer_no", "retention_until", PURGE_REDACT,
     ["candidate_email", "content", "history", "candidate_signature", "response_note",
      "candidate_name"]),
    (COLL_COMM_LOG, "candidate_uk", "retention_until", PURGE_REDACT,
     ["subject", "body", "recipient", "candidate_name"]),
    (COLL_PREBOARDING, "pbt_no", "retention_until", PURGE_REDACT,
     ["notes", "candidate_name"]),
    # What a candidate said about their salary, their notice period and why they want the
    # job is exactly the kind of detail retention exists to stop us keeping forever.
    # A negotiation round is what somebody asked for and what we offered back -- salary
    # detail about a named person, the kind of thing retention exists to stop us keeping.
    (COLL_NEGOTIATIONS, "neg_no", "retention_until", PURGE_REDACT,
     ["candidate_expectation", "proposed_ctc", "notes", "candidate_name"]),
    (COLL_TELEPHONIC, "tel_no", "retention_until", PURGE_REDACT,
     ["comments", "expected_ctc", "notice_period_days", "current_location",
      "availability", "candidate_name"]),
]

# What is stamped on a redacted row, so a reader never mistakes an emptied record for one
# that was always empty. This is the difference between "we purged this" and "we lost this".
PURGE_MARKER_FIELD = "purged_at"
PURGE_BATCH_FIELD  = "purged_batch_no"

AUDIT_PURGE_PROPOSED = "retention purge proposed"
AUDIT_PURGE_APPROVED = "retention purge approved"
AUDIT_PURGE_EXECUTED = "retention purge executed"
ENTITY_PURGE_BATCH = "purge_batch"


# -- Phase INT-3  The scheduled jobs (SOP §12) ---------------------------------------------
# Five governance sweeps that were written to be DRIVEN by a job runner and, until this
# phase, were driven by nothing. Declared here rather than in the service for the same
# reason SLA_MILESTONES is: the table is the specification, and a reader should be able to
# see the whole schedule without reading the loop that walks it.
#
# `hour` is a UTC gate, matched with `>=` rather than `==` so a job whose minute the process
# spent restarting still runs later that day instead of being skipped until tomorrow -- the
# rule the TPMS block beside it already follows.
#
# `cadence` picks the stamp the run is remembered against: a daily job is remembered by
# date, a weekly one by ISO year+week. A weekly job therefore runs on the first tick after
# its hour on any day of a week it has not yet run in, which is what makes it survive a
# process that was down all Monday.
JOB_CADENCE_DAILY  = "daily"
JOB_CADENCE_WEEKLY = "weekly"

JOB_SLA_SWEEP     = "sla_sweep"
JOB_PROBATION     = "probation_reminders"
JOB_PREBOARDING   = "preboarding_reminders"
JOB_POLICY_REVIEW = "policy_review"
JOB_RETENTION     = "retention_propose"
JOB_ORIENTATION   = "orientation_escalation"
JOB_PULSE_SURVEY  = "pulse_survey_issue"
# ── Phase POLICY-LIB-1 (§22.6) ── weekly, the same cadence JOB_POLICY_REVIEW already uses
# for the same reason: an unacknowledged policy stays unacknowledged, so a daily nudge would
# be noise, not a governance signal.
JOB_POLICY_ACK    = "policy_acknowledgement_reminders"
# The Last Working Day sweep: revokes access and opens the F&F on the day somebody
# actually leaves, rather than leaving both to whenever a human next opens the case.
JOB_LWD           = "last_working_day"

# (key, label, cadence, utc_hour)
SCHEDULED_JOBS = [
    (JOB_SLA_SWEEP,     "internal SLA breach sweep",      JOB_CADENCE_DAILY,  7),
    (JOB_PROBATION,     "probation review reminders",     JOB_CADENCE_DAILY,  7),
    (JOB_PREBOARDING,   "pre-boarding contact reminders", JOB_CADENCE_DAILY,  8),
    (JOB_POLICY_REVIEW, "policy review reminders",        JOB_CADENCE_WEEKLY, 8),
    (JOB_RETENTION,     "retention purge proposal",       JOB_CADENCE_WEEKLY, 3),
    (JOB_ORIENTATION,   "orientation escalation sweep",    JOB_CADENCE_DAILY,  7),
    (JOB_PULSE_SURVEY,  "30/90-day pulse survey issuance", JOB_CADENCE_DAILY,  7),
    (JOB_POLICY_ACK,    "policy acknowledgement reminders", JOB_CADENCE_WEEKLY, 8),
    # Runs early: everything else on somebody's last day (final attendance, payroll cut-off)
    # reads better once the access revocation and the F&F have been opened.
    (JOB_LWD,           "last working day sweep",          JOB_CADENCE_DAILY,  6),
]


def scheduled_job(key: str) -> Optional[tuple]:
    """One row of the job table by key, or None. Pure."""
    return next((j for j in SCHEDULED_JOBS if j[0] == key), None)


# How far ahead of a probation end date each reminder fires, in calendar days.
#
# CALENDAR days, not working days: this is a diary note to a manager, not an SLA. The SLA
# table already owns the working-day question, and measuring a "30 days before" reminder in
# working days would put it at a date nobody could predict from the end date itself.
#
# A tier fires when the end date is that close OR CLOSER and the tier has not fired for that
# record yet, rather than on an exact-day match. Exact matching loses the reminder entirely
# if the scheduler was down that one day, which is precisely the day it mattered.
#
# Nothing here handles an OVERDUE review: the `probation_review_due` row in SLA_MILESTONES
# already reports that as a breach and `sweep_open_breaches` already escalates it. Two
# subsystems announcing the same overdue review is how people learn to ignore both.
PROBATION_REMINDER_DAYS = [30, 15, 7, 1]

# Where a record remembers which tiers it has already been reminded about. On the probation
# record itself rather than in a side ledger, so the guard survives any rebuild of the job
# and is visible to anybody reading the row.
PROBATION_REMINDED_FIELD = "reminders_sent"


# -- INT-2.13  The printable documentation set (SOP §9) ------------------------------------
# Five of the SOP's nine templates have data but no artifact. One endpoint pattern serves all
# five: `GET /{entity}/{business_no}/document`, gated by the entity's EXISTING read
# capability -- printing a record is reading it, and inventing a `document.generate`
# capability would mean a user who may read a probation review might not be able to print it,
# which is a distinction nobody wants to explain.
#
# (key, title, collection, id_field, read capability)
PRINTABLE_DOCUMENTS = {
    "requisition": ("Internal Manpower Requisition Form", COLL_REQUISITIONS,
                    "request_no", Cap.REQUISITION_READ),
    "budget-note": ("Headcount & Budget Approval Note", COLL_REQUISITIONS,
                    "request_no", Cap.REQUISITION_READ),
    "reference":   ("Reference Check Report", COLL_REFERENCE_CHECKS,
                    "ref_no", Cap.REFERENCE_READ),
    "probation":   ("Probation Review & Confirmation Record", COLL_PROBATION_REVIEWS,
                    "prb_no", Cap.PROBATION_READ),
    "personnel-file": ("Personnel File Closure Note", COLL_EMPLOYEE_PROFILES,
                       "employee_code", Cap.PERSONNEL_FILE_CLOSE),
}

# How long a generated document's signed URL lives. One hour, matching s3_service's default:
# long enough to open and print, short enough that a copied URL is not a standing grant.
DOCUMENT_URL_TTL_SECONDS = 3600

AUDIT_DOCUMENT_GENERATED = "record document generated"


# ── API models ──────────────────────────────────────────────────────────────────────
class CommitteeMemberIn(BaseModel):
    user_id: str
    decision: CommitteeDecision = CommitteeDecision.AGREE
    remarks: Optional[str] = None
    # ── SOP §11 conflict of interest ── declared per MEMBER, not per sitting: the conflict
    # belongs to a person, and a committee where one member is the candidate's cousin is
    # perfectly workable as long as that member stands down.
    coi_declared: bool = False
    coi_relationship: Optional[str] = None
    recused: bool = False


class ShortlistReviewIn(BaseModel):
    """Convene the internal shortlisting committee for one requisition (SOP §5)."""
    request_no: str
    candidate_uks: List[str] = Field(default_factory=list)
    committee_members: List[CommitteeMemberIn] = Field(default_factory=list)
    outcome: ShortlistOutcome = ShortlistOutcome.PENDING
    notes: Optional[str] = None


class ShortlistReviewUpdate(BaseModel):
    candidate_uks: Optional[List[str]] = None
    committee_members: Optional[List[CommitteeMemberIn]] = None
    outcome: Optional[ShortlistOutcome] = None
    notes: Optional[str] = None


class InterviewWindowIn(BaseModel):
    """A standing batch-interview slot (Annexure C). Advisory, never a block."""
    department_id: str
    weekday: str                                  # one of WEEKDAYS
    start_time: str                               # HH:MM, 24-hour
    end_time: str
    panel_ids: List[str] = Field(default_factory=list)
    active: bool = True
    notes: Optional[str] = None


class InterviewWindowUpdate(BaseModel):
    weekday: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    panel_ids: Optional[List[str]] = None
    active: Optional[bool] = None
    notes: Optional[str] = None


class PreboardingTouchpointIn(BaseModel):
    candidate_uk: str
    mode: PreboardingMode = PreboardingMode.CALL
    sentiment: PreboardingSentiment = PreboardingSentiment.NEUTRAL
    contacted_at: Optional[str] = None            # YYYY-MM-DD; defaults to today
    counter_offer_disclosed: bool = False
    notes: Optional[str] = None


class SalaryBandIn(BaseModel):
    department_id: str
    designation_id: str
    grade: Optional[str] = None                   # a company's own grade label, if it has one
    min: float
    max: float
    currency: str = "INR"
    effective_from: Optional[str] = None          # YYYY-MM-DD; defaults to today
    effective_to: Optional[str] = None
    notes: Optional[str] = None


class SalaryBandUpdate(BaseModel):
    grade: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None
    currency: Optional[str] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    status: Optional[SalaryBandStatus] = None
    notes: Optional[str] = None


class TalentPoolIn(BaseModel):
    """Add or remove a candidate from the talent pool.

    `consent_to_retain` is not a convenience flag: without it the candidate never enters the
    pool at all, because keeping a CV to consider later is a different thing from keeping it
    to process one application, and only the candidate can agree to the second.
    """
    talent_pool: bool = True
    talent_pool_tags: List[str] = Field(default_factory=list)
    consent_to_retain: bool = False
    consent_expires_at: Optional[str] = None      # YYYY-MM-DD; capped at retention_until
    remarks: Optional[str] = None


class CommTemplateUpdate(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    channel: Optional[CommChannel] = None
    active: Optional[bool] = None


class CommSendIn(BaseModel):
    """Send one templated message to one candidate, by hand."""
    candidate_uk: str
    template_key: str
    # Extra placeholder values the caller wants to supply (a covering note, a stage name).
    # Everything the module can derive -- name, designation, CTC -- is derived, not accepted,
    # so a sender cannot quote a salary the record does not hold.
    variables: Dict[str, str] = Field(default_factory=dict)


class SurveyResponseIn(BaseModel):
    """A survey submission from the public link. Entirely untrusted."""
    scores: Dict[str, int] = Field(default_factory=dict)
    comment: Optional[str] = None


class PolicyIn(BaseModel):
    policy_key: str
    title: str
    version: str = "1.0"
    effective_date: Optional[str] = None          # YYYY-MM-DD; defaults to today
    owner_role: Optional[str] = None
    next_review_due: Optional[str] = None         # defaults to +POLICY_REVIEW_MONTHS
    document_id: Optional[str] = None             # a doc_no in the document register
    # ── Phase POLICY-LIB-1 (§22.6) ── additive; see that phase's module docstring in
    # hrms_policy_service.py for why these are added fields, not a rewrite.
    category: Optional[str] = None                # Leave/Attendance/Conduct/... or a
                                                    # client-defined string (BA doc step 223)
    department_ids: List[str] = Field(default_factory=list)   # empty = company-wide
    employment_types: List[str] = Field(default_factory=list) # empty = every employment type
    acknowledgement_required: bool = False
    acceptance_due_days: Optional[int] = None      # days from publish an employee has to ack


class PolicyRevisionIn(BaseModel):
    version: str
    summary_of_change: str
    effective_date: Optional[str] = None
    document_id: Optional[str] = None


class PolicyDocumentIn(BaseModel):
    """§22.6 — the policy's own PDF, uploaded directly against the register rather than
    through the candidate/employee document register (hrms_document_service._resolve_owner
    accepts only those two owner types, and a policy file needs none of that register's
    verification workflow — see hrms_policy_service.upload_policy_document)."""
    file: UploadIn


class PolicyApplicabilityIn(BaseModel):
    """§22.6 — metadata-only update: category, applicability filters, acknowledgement
    settings. Deliberately a separate, smaller model from PolicyIn: this is not a content
    revision and does not need MD approval, so it must not accept `title`/`version`."""
    category: Optional[str] = None
    department_ids: List[str] = Field(default_factory=list)
    employment_types: List[str] = Field(default_factory=list)
    acknowledgement_required: bool = False
    acceptance_due_days: Optional[int] = None


class PolicyApproveIn(BaseModel):
    version: str
    remarks: Optional[str] = None
    signature: str


class PurgeApproveIn(BaseModel):
    """Authorise a purge proposal to execute.

    A typed signature, for the same reason probation confirmation demands one: this is the
    call that destroys records, and it has to be attributable to a person.
    """
    signature: str
    remarks: Optional[str] = None


# =============================================================================
# Phase INT-5 — per-company configuration (spec §42, "configuration over hard-coding")
# =============================================================================
# Sparsh Magic runs several entities. Until this phase the module was multi-company for its
# DATA -- every collection is keyed on `company_id`, ids are sequenced per company, salary
# bands and communication templates are per company -- but NOT for its RULES. The SLA
# targets, the retention periods, the probation duration, the reminder tiers and the score
# bands were module constants, so a second entity under the group would have shared one
# hard-coded rule set with the first.
#
# The design is an OVERLAY, not a replacement. Every default below is READ FROM THE CONSTANT
# THAT ALREADY SHIPPED, so a company with no settings row behaves exactly as it did before
# this phase existed -- byte for byte, with no migration and nothing to backfill. A company
# overrides only the keys it actually disagrees with.
#
# WHAT IS DELIBERATELY NOT CONFIGURABLE, and why:
#
#   * The MANAGERIAL THRESHOLD. Moving it means `REQUIRED_PANEL_ROLES` has to move with it --
#     a company that made `mid` managerial would get a mandatory Management final round while
#     the panel table still said a mid role needs only HR and the HOD. Those are two tables
#     that must agree, so making one of them per-company is a design change, not a config
#     key, and it is not one this phase is entitled to make quietly.
#   * WHETHER AN ASSESSMENT IS REQUIRED. Already per POSTING (`requires_assessment`), which
#     is finer-grained than per company. A company-level default for a field that is always
#     stated explicitly would only add a second place to look.
#   * (Phase INT-6 added THE HOLIDAY CALENDAR, once the working-day maths could read it.
#     It was withheld in INT-5 on the principle that declaring a flag nothing reads is the
#     mistake that phase existed to correct.)
#
# The gates themselves are NOT configurable and never will be: no setting turns off the
# budget gate, the reference check, the scorecard approval or the telephonic screen. Those
# are the controls the SOP is made of. A deviation goes through the exception log, where it
# is attributable, and not through a settings screen where it is silent.

CONFIG_SLA_TARGET_DAYS     = "sla_target_days"
CONFIG_RETENTION_YEARS     = "retention_years"
CONFIG_PROBATION_MONTHS    = "probation_months"
CONFIG_PROBATION_REMINDERS = "probation_reminder_days"
CONFIG_SCORE_BANDS         = "score_bands"
CONFIG_HONOUR_HOLIDAYS     = "honour_holidays"
CONFIG_ONBOARD_DOC_TYPES   = "onboarding_document_types"
CONFIG_EMPLOYMENT_DOCS     = "employment_documents"

# How a value is shaped, which decides how it is validated and merged.
CONFIG_KIND_INT_MAP   = "int_map"      # {name: whole number}
CONFIG_KIND_INT_LIST  = "int_list"     # [whole numbers], strictly descending
CONFIG_KIND_FLOAT_MAP = "float_map"    # {name: number}, strictly descending by value
CONFIG_KIND_FLAG      = "flag"         # a plain on/off
# {label: required?} with OPEN names -- unlike the maps above, a company may add names of
# its own. That is the whole point of the setting: §7.5 calls for the six documents below
# plus "other configurable document types", so the catalogue has to be extensible, not
# merely toggleable.
CONFIG_KIND_FLAG_MAP  = "flag_map"

# Probation duration is one setting with three parts rather than three settings: they
# constrain each other (min <= default <= max), and a company that could save one without
# the others could leave itself a default outside its own bounds.
CONFIG_PROBATION_KEYS = ("default", "min", "max")


def _default_sla_target_days() -> dict:
    """Today's SLA targets, read from the table rather than re-typed.

    Milestone-anchored rows ONLY. A date-anchored milestone has no elapsed-time target --
    its due date IS a field on another record -- so offering one for edit would invite
    somebody to set a number nothing reads.
    """
    return {m["key"]: m["target_days"] for m in SLA_MILESTONES
            if m["anchor"] == ANCHOR_MILESTONE}


def _default_score_bands() -> dict:
    """Today's band floors as {label: floor}. `Reject` is absent on purpose: it is the floor
    of last resort, not a boundary anybody sets."""
    return {label: floor for floor, label in SCORE_BANDS}


# (key, label, kind, default factory, per-value bounds, permitted names)
#
# Declared as data for the same reason SLA_MILESTONES is: the table is the specification, so
# a reader can see everything a company may change without reading the service that changes
# it, and the settings API can validate and render from one place.
CONFIG_SPEC = [
    {"key": CONFIG_SLA_TARGET_DAYS,
     "label": "SLA targets (working days)",
     "kind": CONFIG_KIND_INT_MAP,
     "default": _default_sla_target_days,
     "min": 1, "max": 260,
     "names": sorted(STAMPABLE_MILESTONES),
     "note": "Measured in working days. A target of 0 would be breached the moment it was "
             "set, so 1 is the floor."},

    {"key": CONFIG_RETENTION_YEARS,
     "label": "Record retention (years)",
     "kind": CONFIG_KIND_INT_MAP,
     "default": lambda: dict(RETENTION_YEARS),
     "min": 1, "max": 50,
     "names": sorted(RETENTION_YEARS),
     "note": "Statutory minimums are a floor, not a ceiling -- shortening one is a decision "
             "for the business and its auditors."},

    {"key": CONFIG_PROBATION_MONTHS,
     "label": "Probation duration (months)",
     "kind": CONFIG_KIND_INT_MAP,
     "default": lambda: {"default": DEFAULT_PROBATION_MONTHS,
                         "min": MIN_PROBATION_MONTHS,
                         "max": MAX_PROBATION_MONTHS},
     "min": 1, "max": 24,
     "names": list(CONFIG_PROBATION_KEYS),
     "note": "The SOP's usual range is 3 to 6 months. `min` and `max` bound what a single "
             "probation record may be opened with."},

    {"key": CONFIG_PROBATION_REMINDERS,
     "label": "Probation reminder tiers (days before the end date)",
     "kind": CONFIG_KIND_INT_LIST,
     "default": lambda: list(PROBATION_REMINDER_DAYS),
     "min": 1, "max": 365,
     "max_entries": 6,
     "note": "Calendar days, strictly descending. Each tier fires once per review, at that "
             "distance OR CLOSER -- see hrms_scheduler_service."},

    {"key": CONFIG_ONBOARD_DOC_TYPES,
     "label": "Joining documents a new hire must upload",
     "kind": CONFIG_KIND_FLAG_MAP,
     "default": lambda: dict(ONBOARD_DOC_TYPES),
     # No `names`: this catalogue is open. A company adds a document its own statutory or
     # client obligations need, and marks each one required or optional.
     "note": "Each entry is one upload task on the new hire's portal. Ticked means they "
             "cannot submit the form without it, so mark a document optional rather than "
             "removing it when it only applies to some joiners."},

    {"key": CONFIG_EMPLOYMENT_DOCS,
     "label": "Employment documents a new joiner signs",
     "kind": CONFIG_KIND_FLAG_MAP,
     "default": lambda: dict(EMPLOYMENT_DOCUMENTS),
     "note": "Signed alongside the appointment letter (§7.5 Stage 7). Ticked means the "
             "joiner cannot complete their acknowledgement without it. The appointment "
             "letter itself is not listed here — it carries its own signature."},

    {"key": CONFIG_HONOUR_HOLIDAYS,
     "label": "Skip this company's holidays in SLA maths",
     "kind": CONFIG_KIND_FLAG,
     "default": lambda: False,
     "note": "OFF by default, and deliberately so: turning it on CHANGES WHETHER EXISTING "
             "REQUISITIONS READ AS BREACHED, which is a business decision with a visible "
             "date rather than something that should arrive with a deploy. Weekends are "
             "always excluded either way. Holidays come from this company's own HRMS "
             "calendar, never from the ERP's global master."},

    {"key": CONFIG_SCORE_BANDS,
     "label": "Score band floors (1-5)",
     "kind": CONFIG_KIND_FLOAT_MAP,
     "default": _default_score_bands,
     "min": 1.0, "max": 5.0,
     "names": [label for _floor, label in SCORE_BANDS],
     # ── Phase INT-10 (Gap 10) ── the SOP signed FOUR bands (Strong / Consider / Hold /
     # Reject); the implementation brief describes THREE (4.0+ / 3.0-3.99 / below 3.0).
     # Both are real readings, and which one a company uses is that company's call -- so
     # the middle band is OPTIONAL. Set `Hold` to null and the scale is three bands:
     # Strong, Consider, Reject. Strong and Consider cannot be switched off; a scale with
     # no bar at all is not a scale.
     "optional_names": ["Hold"],
     "note": "Strictly descending. Applies to the position scorecard, the shortlisting "
             "guide and the telephonic screen alike -- one vocabulary, so a '3' means the "
             "same thing everywhere in one company. Set Hold to null for the three-band "
             "reading (Strong / Consider / Reject)."},
]


def config_spec(key: str) -> Optional[dict]:
    """One row of the configuration table by key, or None. Pure."""
    return next((c for c in CONFIG_SPEC if c["key"] == key), None)


def default_config() -> dict:
    """The module's shipped defaults, freshly built.

    Built by CALLING each factory rather than holding one shared dict, so a caller that
    mutates what it gets back cannot alter the defaults every other company falls through
    to. That is a whole class of tenant-bleed bug not to have.
    """
    return {spec["key"]: spec["default"]() for spec in CONFIG_SPEC}


AUDIT_HOLIDAY_ADDED    = "holiday added to the working calendar"
AUDIT_HOLIDAY_REMOVED  = "holiday removed from the working calendar"
AUDIT_HOLIDAY_IMPORTED = "holidays imported from the ERP calendar"
ENTITY_HOLIDAY = "holiday"

# A working calendar is a year or two of dates, not a data set. The cap is what stops a bad
# import turning every SLA computation into a scan.
MAX_HOLIDAYS = 500

AUDIT_CONFIG_UPDATED = "company configuration updated"
AUDIT_CONFIG_RESET   = "company configuration reset to defaults"
ENTITY_CONFIG = "configuration"


# =============================================================
# Phase 12 — API models for background verification
# =============================================================
class BackgroundCheckIn(BaseModel):
    uk: str
    check_type: BackgroundCheckType
    status: BackgroundCheckStatus = BackgroundCheckStatus.PENDING
    agency: Optional[str] = None                  # who performed it
    reference: Optional[str] = None               # the vendor's own case number
    findings: Optional[str] = None
    completed_on: Optional[str] = None            # YYYY-MM-DD
    document_id: Optional[str] = None             # the report, in the document register


class BackgroundCheckUpdate(BaseModel):
    status: Optional[BackgroundCheckStatus] = None
    agency: Optional[str] = None
    reference: Optional[str] = None
    findings: Optional[str] = None
    completed_on: Optional[str] = None
    document_id: Optional[str] = None


class BackgroundApproveIn(BaseModel):
    """HR's sign-off that verification is complete. A typed signature, the same standard
    probation confirmation and the retention purge hold, because this one unlocks an
    offer."""
    decision: str                                 # Approved | Rejected
    signature: str
    remarks: Optional[str] = None


# =============================================================
# Phase 13 — interview evidence, and sending a candidate back
# =============================================================
# -- Interview report and recording (spec §10) -------------------------------------------
# Both hang off the INTERVIEW record rather than the candidate: a candidate may sit several
# rounds, and "the report" is meaningless without saying which conversation it describes.
#
# They are stored separately from `hrms_documents` on purpose. That register is a filing
# cabinet for a person's paperwork -- typed, verified, retained against the employee. An
# interview recording is evidence about one event, it is never verified, and it is shown to
# a client who has no `document.read` at all.
#
# -- What a client may do with each, and the honest limit ---------------------------------
#     CV                    view + download
#     Interview report      view          (inline; a PDF a browser renders)
#     Interview recording   watch only
#
# The recording rule is enforced as far as it honestly can be, and no further. A client is
# never given a storage URL -- the bytes are streamed through an endpoint that answers a
# short-lived, share-bound token, sends `Content-Disposition: inline`, and audits the view.
# There is no download button anywhere in their UI.
#
# What that does NOT do is make the file unsaveable. A browser must receive the bytes to
# play them, so anyone determined can keep a copy. This is a control against casual
# redistribution and an audit trail of who watched what -- claiming more would be false.
RECORDING_MIME = {
    "video/mp4", "video/webm", "video/quicktime", "video/x-matroska",
    # Audio-only interviews are common on a phone screen, and a client should be able to
    # listen to one for the same reason they can watch a video.
    "audio/mpeg", "audio/mp4", "audio/wav", "audio/webm",
}
REPORT_MIME = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# A recording is a video file, so the 15 MB document ceiling is useless here. 500 MB holds
# roughly an hour at a sensible bitrate; beyond that the answer is a link to wherever the
# conferencing tool already stored it, not a bigger upload.
MAX_RECORDING_BYTES = 500 * 1024 * 1024
MAX_REPORT_BYTES = 25 * 1024 * 1024

# How long a streaming token is good for. Long enough to watch an interview through without
# it dying mid-playback; short enough that a copied URL is worthless tomorrow.
RECORDING_TOKEN_TTL_SECONDS = 4 * 60 * 60

AUDIT_INTERVIEW_REPORT_ADDED    = "interview report uploaded"
AUDIT_INTERVIEW_RECORDING_ADDED = "interview recording uploaded"
AUDIT_INTERVIEW_MEDIA_REMOVED   = "interview evidence removed"
AUDIT_INTERVIEW_REPORT_VIEWED   = "interview report opened by client"
AUDIT_INTERVIEW_RECORDING_VIEWED = "interview recording watched by client"


class InterviewMediaIn(BaseModel):
    """A report or a recording, arriving as base64 like every other HRMS upload.

    `external_url` is the alternative to sending bytes: most recordings already live in the
    conferencing tool that made them, and re-uploading a 400 MB file to store a second copy
    helps nobody. Exactly one of the two is required.
    """
    name: Optional[str] = None
    mime_type: Optional[str] = None
    data: Optional[str] = None                  # base64, optionally a data: URL
    external_url: Optional[str] = None          # a link to where it already lives
    notes: Optional[str] = None
    duration_minutes: Optional[int] = None       # recordings only; for the player's label


# =============================================================
# Phase EXIT-1 — Exit Management (BA/Functional Design §7.18, §22.2, §7.21)
#
# Employee submits (or HR records) a resignation → notice is calculated from status and
# designation level → HR/manager records acceptance, with an MD/Finance approval gate on any
# waiver → a Handover Plan and departmental Clearance/Asset-Return/Access-Clearance tasks run
# in parallel → an Exit Interview is captured → Finance approves the F&F → the case closes and
# the employee moves to Alumni.
#
# F&F HAS NO PAYROLL ENGINE BEHIND IT (see §7.13 — unbuilt). FnfInput below therefore captures
# the figures a real payroll run would otherwise supply, entered by hand, so the settlement can
# still be prepared, reviewed and approved with a proper maker/checker gate — it cannot compute
# LOP, PF or TDS from first principles, because nothing in this codebase does yet.
# =============================================================
class ExitType(str, Enum):
    RESIGNATION  = "Resignation"
    TERMINATION  = "Termination"
    RETIREMENT   = "Retirement"
    ABSCONDING   = "Absconding"
    DEMISE       = "Demise"
    MISSING      = "Missing"
    CONTRACT_END = "End of Contract"


class SeparationStage(str, Enum):
    INITIATED          = "Initiated"
    NOTICE_IN_PROGRESS = "Notice in Progress"
    HANDOVER_CLEARANCE = "Handover & Clearance"
    FNF_PENDING        = "F&F Pending"
    FNF_APPROVED       = "F&F Approved"
    SETTLED            = "Settled"
    CLOSED             = "Closed"
    WITHDRAWN          = "Withdrawn"


# A separation is DONE working through once it reaches one of these — used to enforce "one
# open case per employee" without a unique index (a rehired-and-separated-again employee
# legitimately gets a second row, which a unique (company, employee_code) index would forbid).
CLOSED_SEPARATION_STAGES = {SeparationStage.CLOSED.value, SeparationStage.WITHDRAWN.value}


class ClearanceOwnerType(str, Enum):
    MANAGER = "Manager"
    HR      = "HR"
    IT      = "IT"
    ADMIN   = "Admin"
    FINANCE = "Finance"
    OTHER   = "Other"


class ClearanceStatus(str, Enum):
    PENDING  = "Pending"
    CLEARED  = "Cleared"
    REJECTED = "Rejected"
    WAIVED   = "Waived"


class HandoverStatus(str, Enum):
    PENDING   = "Pending"
    SUBMITTED = "Submitted"   # the doer marked it done; awaiting manager acceptance
    ACCEPTED  = "Accepted"
    REJECTED  = "Rejected"


class AssetReturnStatus(str, Enum):
    PENDING             = "Pending"
    RETURNED            = "Returned"
    PARTIALLY_RETURNED  = "Partially Returned"
    LOST                = "Lost"
    DAMAGED             = "Damaged"
    WAIVED              = "Waived"


class AccessSystemType(str, Enum):
    EMAIL           = "Email"
    APPLICATIONS    = "Applications"
    VPN             = "VPN"
    CLIENT_SYSTEMS  = "Client Systems"
    PHYSICAL_ACCESS = "Physical Access"
    CARDS_KEYS      = "Cards / Keys"
    OTHER           = "Other"


class AccessClearanceStatus(str, Enum):
    PENDING        = "Pending"
    DISABLED       = "Disabled"
    NOT_APPLICABLE = "Not Applicable"


class FnfStatus(str, Enum):
    DRAFT    = "Draft"
    PREPARED = "Prepared"   # maker done, awaiting Finance
    APPROVED = "Approved"   # Finance approved; not yet paid
    PAID     = "Paid"
    REJECTED = "Rejected"   # sent back to the maker


# ── §7.18 / BR-016 notice matrix ──
# Probation: L1 nil, L2 3 days, L3 7, L4 15, L5+ 20.  Confirmed: L1-L3 15, L4 30, L5+ 45.
# "Level" is Designation.level (1-based ascending seniority) — the same field the BA doc's
# "L1...L5+" shorthand already matches without inventing a second seniority scale.
NOTICE_DAYS_PROBATION        = {1: 0, 2: 3, 3: 7, 4: 15}
NOTICE_DAYS_PROBATION_L5PLUS = 20
NOTICE_DAYS_CONFIRMED_L1_L3  = 15
NOTICE_DAYS_CONFIRMED_L4     = 30
NOTICE_DAYS_CONFIRMED_L5PLUS = 45

# A designation with no `level` set falls back to this band — the same reasoning
# DesignationLevel gives for defaulting an unset band to "mid", pointed the other way: absent
# data should read as the outcome that is safest for the COMPANY, since notice is what the
# company is owed, not the employee. The service surfaces `notice_basis` alongside the
# calculated figure so HR can see when a number rests on this default rather than a real level.
DEFAULT_DESIGNATION_LEVEL_FOR_NOTICE = 1


def notice_days_for(on_probation: bool, level: Optional[int]) -> int:
    """Contractual notice, in days, from the BA doc's table (§7.18, BR-016).

    Pure function: whether the person is still on probation is an I/O question the SERVICE
    resolves (the latest hrms_probation_reviews outcome for their employee_code) — this is
    only the arithmetic, status + level -> days, kept separate so it can be tested without a
    database and reused anywhere the figure is needed (initiation, recalculation, display).
    """
    lvl = level if level and level >= 1 else DEFAULT_DESIGNATION_LEVEL_FOR_NOTICE
    if on_probation:
        return NOTICE_DAYS_PROBATION_L5PLUS if lvl >= 5 else NOTICE_DAYS_PROBATION.get(lvl, NOTICE_DAYS_PROBATION[4])
    if lvl >= 5:
        return NOTICE_DAYS_CONFIRMED_L5PLUS
    if lvl == 4:
        return NOTICE_DAYS_CONFIRMED_L4
    return NOTICE_DAYS_CONFIRMED_L1_L3


ENTITY_SEPARATION       = "separation"
ENTITY_HANDOVER         = "handover_task"
ENTITY_CLEARANCE        = "clearance_task"
ENTITY_ASSET_RETURN     = "asset_return"
ENTITY_ACCESS_CLEARANCE = "access_clearance"
ENTITY_EXIT_INTERVIEW   = "exit_interview"
ENTITY_FNF              = "fnf_settlement"

AUDIT_SEPARATION_INITIATED     = "separation initiated"
AUDIT_SEPARATION_DECIDED       = "separation acceptance recorded"
AUDIT_SEPARATION_WAIVED        = "notice waiver / early release approved"
AUDIT_SEPARATION_WITHDRAWN     = "separation withdrawn"
AUDIT_SEPARATION_CLOSED        = "separation closed -- employee moved to alumni"
AUDIT_HANDOVER_CREATED         = "handover task created"
AUDIT_HANDOVER_UPDATED         = "handover task updated"
AUDIT_HANDOVER_ACCEPTED        = "handover task accepted by manager"
AUDIT_CLEARANCE_CREATED        = "clearance task created"
AUDIT_CLEARANCE_ACTIONED       = "clearance task actioned"
AUDIT_ASSET_RETURN_CREATED     = "asset return request created"
AUDIT_ASSET_RETURN_UPDATED     = "asset return request updated"
AUDIT_ACCESS_CLEARANCE_CREATED = "access clearance task created"
AUDIT_ACCESS_CLEARANCE_UPDATED = "access clearance task updated"
AUDIT_EXIT_INTERVIEW_SAVED     = "exit interview recorded"
AUDIT_FNF_SAVED                = "F&F settlement saved"
AUDIT_FNF_APPROVED             = "F&F settlement approved"
AUDIT_FNF_REJECTED             = "F&F settlement sent back to maker"
AUDIT_FNF_PAID                 = "F&F settlement marked paid"

# A case must clear every mandatory task before F&F, unless HR formally waives one (BR-025).
# The cap exists for the same reason MAX_HOLIDAYS does: a runaway import or a scripted client
# must not be able to turn one case into an unbounded scan.
MAX_TASKS_PER_SEPARATION = 200


class ResignationIn(BaseModel):
    """§7.18 step 137: what the departing person (or HR, raising on their behalf) supplies.
    Notice is CALCULATED from status + designation level, never typed in here — see
    notice_days_for and hrms_exit_service.initiate_separation."""
    employee_code: str
    exit_type: ExitType = ExitType.RESIGNATION
    resignation_date: Optional[str] = None       # YYYY-MM-DD; defaults to today
    reason: Optional[str] = None
    proposed_lwd: Optional[str] = None           # YYYY-MM-DD


class SeparationDecisionIn(BaseModel):
    """§7.18 steps 140-141: HR/manager records acceptance and any revision. A waiver or
    shortfall recorded here does not take effect until SeparationApprovalIn confirms it."""
    revised_lwd: Optional[str] = None
    waiver_days: Optional[int] = None            # notice days being waived
    shortfall_days: Optional[int] = None         # notice days short, for recovery at F&F
    remarks: Optional[str] = None


class SeparationApprovalIn(BaseModel):
    """The written approval BR-016 requires before a waiver or early release takes effect."""
    approved: bool
    remarks: Optional[str] = None


class HandoverTaskIn(BaseModel):
    """§22.2 handover screen fields."""
    task: str
    description: Optional[str] = None
    assigned_to: Optional[str] = None            # successor / receiving employee (user id)
    owner_id: Optional[str] = None               # defaults to the reporting manager
    due_date: Optional[str] = None
    attachment: Optional[str] = None             # a link; base64 uploads use the document register


class HandoverTaskUpdate(BaseModel):
    task: Optional[str] = None
    description: Optional[str] = None
    assigned_to: Optional[str] = None
    owner_id: Optional[str] = None
    due_date: Optional[str] = None
    attachment: Optional[str] = None
    status: Optional[HandoverStatus] = None
    completion_evidence: Optional[str] = None
    remarks: Optional[str] = None


class HandoverAcceptIn(BaseModel):
    """The reporting manager's sign-off (or rejection) on a submitted item."""
    accepted: bool
    remarks: Optional[str] = None


class ClearanceTaskIn(BaseModel):
    owner_type: ClearanceOwnerType
    owner_id: Optional[str] = None
    task: str
    due_date: Optional[str] = None


class ClearanceActionIn(BaseModel):
    status: ClearanceStatus
    recovery_amount: Optional[float] = None      # feeds the F&F preview when set
    evidence: Optional[str] = None
    remarks: Optional[str] = None


class AssetReturnIn(BaseModel):
    """§22.2 Asset Return Request fields."""
    asset_id: Optional[str] = None
    category: Optional[str] = None
    description: str
    issued_date: Optional[str] = None
    expected_return_date: Optional[str] = None


class AssetReturnUpdate(BaseModel):
    returned_date: Optional[str] = None
    condition: Optional[str] = None
    missing_or_damaged: Optional[bool] = None
    recovery_amount: Optional[float] = None
    received_by: Optional[str] = None
    attachment: Optional[str] = None
    status: Optional[AssetReturnStatus] = None
    remarks: Optional[str] = None


class AccessClearanceIn(BaseModel):
    system_type: AccessSystemType
    description: Optional[str] = None
    owner_id: Optional[str] = None


class AccessClearanceUpdate(BaseModel):
    status: AccessClearanceStatus
    remarks: Optional[str] = None


class ExitInterviewIn(BaseModel):
    reason: Optional[str] = None
    manager_rating: Optional[int] = None         # 1-5
    team_rating: Optional[int] = None
    work_rating: Optional[int] = None
    compensation_rating: Optional[int] = None
    comments: Optional[str] = None
    rehire_recommendation: Optional[bool] = None


class FnfInput(BaseModel):
    """§7.21 F&F inputs, entered by hand because no payroll engine exists yet (§7.13).

    Every figure is kept as its OWN line rather than one lump sum, so the printed settlement
    can show its working — the same reason task_credit keeps achieved/assigned instead of only
    a percentage. Asset/clearance recoveries are NOT entered here: the service rolls those up
    automatically from the case's own asset-return and clearance records (§22.2 step 196) and
    adds them to whatever this model supplies.
    """
    payable_days: Optional[float] = None
    leave_encashment: Optional[float] = None
    notice_pay_or_shortfall: Optional[float] = None   # negative = recovery from the employee
    advance_recovery: Optional[float] = None          # positive = deducted from the settlement
    variable_pay_hold_release: Optional[float] = None
    other_earnings: Optional[float] = None
    other_deductions: Optional[float] = None
    remarks: Optional[str] = None


class FnfDecisionIn(BaseModel):
    approved: bool
    remarks: Optional[str] = None


class FnfPaidIn(BaseModel):
    paid_on: Optional[str] = None
    reference: Optional[str] = None


# =============================================================
# Phase ATT-1 — Attendance & Leave (BA/Functional Design §7.8-7.12, §22.8-22.9)
#
# Attendance is captured (manually by HR/manager for now — see ATTENDANCE_MARK) → the daily
# engine derives status/late-minutes/worked-minutes against the company's configured shift and
# grace → exceptions are regularised (employee proposes → manager → HR) → HR locks the month,
# freezing an immutable snapshot for payroll to consume later. Leave runs in parallel: apply →
# manager → HR → ledger update; C-Off is its own earn-then-use ledger of individually-expiring
# batches, exposed inside the same leave dropdown per §22.8.
#
# POLICY NUMBERS ARE NOT FROZEN. The document says so explicitly and more than once: "final
# deduction/half-day logic must be frozen before build" (§7.8), "Leave policy currently
# contains conflicting CL quantum wording; final values must be confirmed" (§7.10), "Policy
# text contains both a 60-day statement and an apparent '32 months' phrase; final expiry rule
# is a mandatory policy-freeze item" (§7.11), and §22.8 names EL's accrual/carry-forward/lapse/
# encashment/notice-period rules as undefined and required "before development". So — exactly
# like FnfInput above, which exists because §7.13's payroll engine is unbuilt — none of those
# figures are hardcoded into logic here. DEFAULT_SHIFT_POLICY and a seeded hrms_leave_types row
# per code carry the numbers the document DOES mention ("current policy references...") as
# ADJUSTABLE DEFAULTS, editable via LEAVE_POLICY_MANAGE, with `policy_confirmed: bool = False`
# surfaced so HR/Management see plainly that these are placeholders, not the client's sign-off.
# =============================================================
class AttendanceStatus(str, Enum):
    PRESENT     = "Present"
    ABSENT      = "Absent"
    HALF_DAY    = "Half Day"
    ON_LEAVE    = "On Leave"
    ON_OD       = "On OD"
    WEEKLY_OFF  = "Weekly Off"
    HOLIDAY     = "Holiday"
    PENDING     = "Pending"     # work date has passed with no capture yet — a monthly-lock exception


class CorrectionExceptionType(str, Enum):
    MISSING_PUNCH  = "Missing Punch"
    WRONG_TIME     = "Wrong Time"
    FORGOT_TO_MARK = "Forgot to Mark"
    SYSTEM_ERROR   = "System Error"
    OTHER          = "Other"


class CorrectionStatus(str, Enum):
    PENDING          = "Pending"            # awaiting the reporting manager
    MANAGER_APPROVED = "Manager Approved"   # awaiting HR's second-level sign-off
    APPROVED         = "Approved"           # HR-final; attendance row recalculated
    REJECTED         = "Rejected"
    RETURNED         = "Returned"           # sent back to the employee with a comment


class OdStatus(str, Enum):
    PENDING  = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class LockStatus(str, Enum):
    OPEN   = "Open"
    LOCKED = "Locked"


class LeaveStatus(str, Enum):
    PENDING          = "Pending"
    MANAGER_APPROVED = "Manager Approved"
    APPROVED         = "Approved"
    REJECTED         = "Rejected"
    RETURNED         = "Returned"
    CANCELLED        = "Cancelled"          # withdrawn after approval; restores the balance


class LeaveHalfSession(str, Enum):
    FIRST_HALF  = "First Half"
    SECOND_HALF = "Second Half"


class CoffLedgerStatus(str, Enum):
    PENDING_APPROVAL = "Pending Approval"   # earn claim awaiting sign-off
    AVAILABLE        = "Available"          # credited and unused
    USED             = "Used"
    EXPIRED          = "Expired"
    REJECTED         = "Rejected"


# A correction/leave/C-Off request is DONE once it reaches one of these — mirrors
# CLOSED_SEPARATION_STAGES: needed to tell "still working through the queue" apart from
# history without a second boolean that could drift out of sync with status.
OPEN_CORRECTION_STATUSES = {CorrectionStatus.PENDING.value, CorrectionStatus.MANAGER_APPROVED.value}
OPEN_LEAVE_STATUSES = {LeaveStatus.PENDING.value, LeaveStatus.MANAGER_APPROVED.value}

# §7.8: "current policy references 9:30 AM-6:30 PM, five-minute daily grace and 60-minute
# monthly buffer" — an ADJUSTABLE DEFAULT (see module docstring), read by the service when a
# company has not configured its own shift policy yet, never compiled into the status
# calculation as a constant.
DEFAULT_SHIFT_POLICY = {
    "shift_start": "09:30",
    "shift_end": "18:30",
    "daily_grace_minutes": 5,
    "monthly_buffer_minutes": 60,
    "half_day_threshold_minutes": 240,   # worked less than half a shift -> Half Day, not Present
}

# §22.8: leave types the dropdown must offer, seeded per company at first use. Every numeric
# policy value here is the ADJUSTABLE DEFAULT the doc's "current policy references" implies,
# not a frozen figure — see the module docstring.
DEFAULT_LEAVE_TYPES = [
    {"code": "CL", "name": "Casual Leave", "annual_entitlement": 12,
     "accrual_frequency": "Annual", "carry_forward_ceiling": 0, "allow_encashment": False,
     "requires_attachment_after_days": None, "notice_period_restricted": True},
    {"code": "SL", "name": "Sick Leave", "annual_entitlement": 12,
     "accrual_frequency": "Annual", "carry_forward_ceiling": 0, "allow_encashment": False,
     "requires_attachment_after_days": 2, "notice_period_restricted": True},
    {"code": "EL", "name": "Earned Leave", "annual_entitlement": 15,
     "accrual_frequency": "Annual", "carry_forward_ceiling": 30, "allow_encashment": True,
     "requires_attachment_after_days": None, "notice_period_restricted": True},
    {"code": "C-Off", "name": "Compensatory Off", "annual_entitlement": 0,
     "accrual_frequency": "None", "carry_forward_ceiling": 0, "allow_encashment": False,
     "requires_attachment_after_days": None, "notice_period_restricted": False,
     "coff_expiry_days": 60},
]


def compute_daily_status(*, scheduled_in: str, scheduled_out: str,
                          actual_in: Optional[str], actual_out: Optional[str],
                          daily_grace_minutes: int, half_day_threshold_minutes: int) -> dict:
    """The §7.8 daily engine's arithmetic, pure — no DB, no clock, testable standalone
    (matches notice_days_for's discipline in Phase EXIT-1). All timing PARAMETERS come from
    the caller's policy lookup; nothing here is a hardcoded company number.

    Times are "HH:MM" 24-hour strings. Returns worked_minutes/late_minutes/status; never
    raises on missing punches — that is a legitimate day-state (Absent), not an error.
    """
    def _mins(hhmm: str) -> int:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    if not actual_in:
        return {"status": AttendanceStatus.ABSENT.value, "worked_minutes": 0, "late_minutes": 0}

    sched_in_m = _mins(scheduled_in)
    in_m = _mins(actual_in)
    late_minutes = max(0, in_m - sched_in_m - daily_grace_minutes)

    if not actual_out:
        # Present with an open/missing out-punch — the daily status still resolves; the
        # missing out-punch itself becomes a regularisation candidate (§7.8 step 61).
        return {"status": AttendanceStatus.PRESENT.value, "worked_minutes": 0,
                "late_minutes": late_minutes}

    out_m = _mins(actual_out)
    worked_minutes = max(0, out_m - in_m)
    status = (AttendanceStatus.HALF_DAY.value if worked_minutes < half_day_threshold_minutes
              else AttendanceStatus.PRESENT.value)
    return {"status": status, "worked_minutes": worked_minutes, "late_minutes": late_minutes}


ENTITY_ATTENDANCE   = "attendance"
ENTITY_CORRECTION   = "attendance_correction"
ENTITY_OD           = "od_request"
ENTITY_ATT_LOCK     = "attendance_lock"
ENTITY_LEAVE_TYPE   = "leave_type"
ENTITY_LEAVE_REQUEST = "leave_request"
ENTITY_COFF         = "coff_ledger"

AUDIT_ATTENDANCE_MARKED       = "attendance marked"
AUDIT_CORRECTION_REQUESTED    = "attendance regularisation requested"
AUDIT_CORRECTION_ACTIONED     = "attendance regularisation actioned"
AUDIT_OD_REQUESTED            = "outdoor duty requested"
AUDIT_OD_ACTIONED             = "outdoor duty actioned"
AUDIT_ATTENDANCE_LOCKED       = "monthly attendance locked"
AUDIT_ATTENDANCE_UNLOCKED     = "monthly attendance unlocked"
AUDIT_LEAVE_TYPE_SAVED        = "leave type configuration saved"
AUDIT_LEAVE_APPLIED           = "leave applied"
AUDIT_LEAVE_ACTIONED          = "leave actioned"
AUDIT_LEAVE_CANCELLED         = "leave cancelled"
AUDIT_LEAVE_BALANCE_ADJUSTED  = "leave balance adjusted"
AUDIT_COFF_EARN_REQUESTED     = "compensatory off earn requested"
AUDIT_COFF_EARN_ACTIONED      = "compensatory off earn actioned"

# A runaway import/scripted client must not be able to force an unbounded scan when computing
# "how many open corrections/leave requests does this company have" — same reasoning as
# MAX_TASKS_PER_SEPARATION and MAX_HOLIDAYS.
MAX_ATTENDANCE_LIST_PAGE = 500


class AttendanceMarkIn(BaseModel):
    """HR/manager records a day's raw punches (or an explicit non-worked status) for one
    employee. The service derives status/worked/late from this — none of that is typed in
    here, the same discipline notice_days_for's caller-supplies-nothing-computed rule keeps."""
    employee_code: str
    work_date: str                               # YYYY-MM-DD
    actual_in: Optional[str] = None              # "HH:MM"
    actual_out: Optional[str] = None
    override_status: Optional[AttendanceStatus] = None   # explicit Weekly Off / Holiday / Leave
    notes: Optional[str] = None


class RegularizationIn(BaseModel):
    """§7.9 step 63-64: the employee's own correction request."""
    employee_code: str
    work_date: str
    exception_type: CorrectionExceptionType
    proposed_in: Optional[str] = None
    proposed_out: Optional[str] = None
    reason: str
    evidence: Optional[str] = None               # a link; base64 uploads use the document register


class RegularizationActionIn(BaseModel):
    decision: CorrectionStatus                   # Manager Approved / Approved / Rejected / Returned
    remarks: Optional[str] = None


class OdRequestIn(BaseModel):
    employee_code: str
    od_date: str
    purpose: str
    location: Optional[str] = None


class OdActionIn(BaseModel):
    approved: bool
    remarks: Optional[str] = None


class AttendanceLockIn(BaseModel):
    period: str                                   # YYYY-MM


class AttendanceUnlockIn(BaseModel):
    """Post-lock changes need authorised adjustment (§7.12 BR) — a reason is mandatory so the
    audit trail carries WHY a closed period was reopened, not just that it was."""
    reason: str


class LeaveTypeConfigIn(BaseModel):
    """§22.8 leave-type master. Every numeric field is a POLICY VALUE the document explicitly
    marks unconfirmed for CL/SL/EL/C-Off — see the module docstring. Saving this does not
    imply client sign-off; `policy_confirmed` is a separate, explicit flag for that."""
    code: str
    name: str
    annual_entitlement: float = 0
    accrual_frequency: str = "Annual"             # Annual | Monthly | None
    carry_forward_ceiling: float = 0
    allow_encashment: bool = False
    requires_attachment_after_days: Optional[int] = None
    notice_period_restricted: bool = False
    coff_expiry_days: Optional[int] = None        # only meaningful for the C-Off row
    policy_confirmed: bool = False
    active: bool = True


class LeaveApplyIn(BaseModel):
    employee_code: str
    leave_type: str                                # a hrms_leave_types `code`
    start_date: str
    end_date: str
    half_day: bool = False
    half_session: Optional[LeaveHalfSession] = None
    reason: Optional[str] = None
    attachment: Optional[str] = None


class LeaveActionIn(BaseModel):
    decision: LeaveStatus                          # Manager Approved / Approved / Rejected / Returned
    remarks: Optional[str] = None


class LeaveCancelIn(BaseModel):
    reason: str


class LeaveBalanceAdjustIn(BaseModel):
    """HR manual correction to a balance (opening balance import, goodwill grant, an error
    fix) — kept as its own audited act rather than letting anyone edit the ledger row
    directly, the same reason F&F's recoveries are rolled up rather than hand-edited."""
    employee_code: str
    leave_type: str
    year: int
    adjustment_days: float
    reason: str


class CoffEarnIn(BaseModel):
    """§7.11 steps 77-78: a claim that approved work was done on a weekly off/holiday."""
    employee_code: str
    earned_for_date: str                           # the holiday/weekly-off actually worked
    note: Optional[str] = None


class CoffEarnActionIn(BaseModel):
    approved: bool
    remarks: Optional[str] = None


# =============================================================
# Phase MOVE-1 — Employee Movements & Discipline
# (BA/Functional Design §7.16, §7.17, §7.19, §7.20)
#
# Movement: a promotion/transfer/manager/designation/grade/location/compensation change is
# proposed against the employee's CURRENT value (captured by the service, never client-
# supplied — the same "the server computes, the caller never asserts" discipline
# notice_days_for established) -> approved -> applied on its effective date, updating the
# live profile while the movement record itself becomes the permanent, never-edited history
# entry (§7.16 BR: "Never overwrite historical organisation/compensation state").
#
# Discipline: a confidential case runs case -> investigation -> recommendation -> management
# decision -> closure, with a SEPARATE, narrower capability pair for POSH/harassment matters
# (§7.17 BR: "should not be treated as ordinary manager-visible discipline case"). Self-service
# complaint-raising (the doc names "Employee" as one of the triggering actors) is NOT built in
# this pass — it needs confidentiality/anonymity handling this phase does not attempt, and is
# a documented follow-up rather than a silent gap, the same honesty EXIT-1's ownership-check
# note already models.
#
# Absconding: 3 consecutive unexplained days -> flag -> logged contact attempts -> a two-stage
# warning ladder (First/Second, each gated on a configurable window since it has elapsed) ->
# an authorised final decision that either resolves the case or hands off into Exit Management
# (initiate_separation with exit_type=Absconding).
#
# Retirement/Demise/Missing: deliberately the THINNEST of the four, because the document itself
# says so ("Exact retirement age is not fixed... must be confirmed", "Legal/benefit handling...
# should follow approved HR/legal guidance"). Retirement gets a proactive alert (DOB + a
# configurable retirement age, the same adjustable-default pattern DEFAULT_SHIFT_POLICY uses)
# rather than a new case collection; demise/missing get a small nominee/legal-documentation
# extension to the EXISTING separation record (NomineeDetailsIn below), because Exit Management
# (Phase EXIT-1) already runs the rest of that case end to end via its exit_type values.
# =============================================================
class MovementType(str, Enum):
    PROMOTION            = "Promotion"
    TRANSFER             = "Transfer"
    MANAGER_CHANGE       = "Manager Change"
    DESIGNATION_CHANGE   = "Designation Change"
    GRADE_CHANGE         = "Grade Change"
    LOCATION_CHANGE      = "Location Change"
    COMPENSATION_CHANGE  = "Compensation Change"


class MovementStatus(str, Enum):
    PENDING  = "Pending"
    APPROVED = "Approved"     # awaiting its effective date
    REJECTED = "Rejected"
    APPLIED  = "Applied"      # effective date reached; live profile updated


# Movement types the SERVICE can actually apply to a real field today. Grade and Location
# have no canonical field anywhere in this codebase yet (the earlier gap analysis flagged
# this absence) — those two are recorded and approved like any other movement, but applying
# one updates only the movement record's own history, not a live profile field, and the
# service says so explicitly in what it returns rather than silently doing nothing.
MOVEMENT_APPLIABLE_TYPES = {
    MovementType.DESIGNATION_CHANGE.value, MovementType.PROMOTION.value,
    MovementType.MANAGER_CHANGE.value, MovementType.COMPENSATION_CHANGE.value,
}


class DisciplineCategory(str, Enum):
    MISCONDUCT         = "Misconduct"
    ATTENDANCE         = "Attendance"
    INSUBORDINATION    = "Insubordination"
    HARASSMENT         = "Harassment"
    POSH               = "POSH"
    POLICY_VIOLATION   = "Policy Violation"
    OTHER              = "Other"


# A case in either of these categories is ALWAYS Restricted, regardless of what the caller
# passes — §7.17 BR is not a suggestion the UI can override.
POSH_CATEGORIES = {DisciplineCategory.HARASSMENT.value, DisciplineCategory.POSH.value}


class ConfidentialityLevel(str, Enum):
    STANDARD   = "Standard"
    RESTRICTED = "Restricted"


class DisciplineStatus(str, Enum):
    REPORTED               = "Reported"
    UNDER_INVESTIGATION    = "Under Investigation"
    RECOMMENDATION_RECORDED = "Recommendation Recorded"
    DECIDED                = "Decided"
    CLOSED                 = "Closed"


class DisciplineOutcome(str, Enum):
    WARNING     = "Warning"
    CENSURE     = "Censure"
    SHOW_CAUSE  = "Show Cause"
    TERMINATION = "Termination"
    NO_ACTION   = "No Action"
    OTHER       = "Other"


class PersonRole(str, Enum):
    COMPLAINANT = "Complainant"
    RESPONDENT  = "Respondent"
    WITNESS     = "Witness"


class AbscondingStatus(str, Enum):
    FLAGGED                   = "Flagged"
    FIRST_WARNING_SENT        = "First Warning Sent"
    SECOND_WARNING_SENT       = "Second Warning Sent"
    FINAL_ACTION              = "Final Action"
    RETURNED_TO_WORK          = "Returned to Work"
    CONVERTED_TO_SEPARATION   = "Converted to Separation"


OPEN_ABSCONDING_STATUSES = {
    AbscondingStatus.FLAGGED.value, AbscondingStatus.FIRST_WARNING_SENT.value,
    AbscondingStatus.SECOND_WARNING_SENT.value, AbscondingStatus.FINAL_ACTION.value,
}

# §7.19 BR: "Current policy uses 3 consecutive working days and two 7-day warning windows
# before final action" — an ADJUSTABLE DEFAULT (same discipline as DEFAULT_SHIFT_POLICY),
# read from hrms_settings, never compiled in as a constant the service enforces blindly.
DEFAULT_ABSCONDING_POLICY = {
    "unexplained_absence_days": 3,
    "warning_window_days": 7,
}

# §7.20 BR: "Exact retirement age is not fixed in the supplied text excerpt and must be
# confirmed" — this default is explicitly a placeholder, more so than any other number in
# this module, and is surfaced to HR as such wherever it is shown.
DEFAULT_RETIREMENT_AGE = 60
# How far ahead of the retirement date HR is alerted — again adjustable, not frozen.
DEFAULT_RETIREMENT_ALERT_MONTHS = 6


ENTITY_MOVEMENT   = "employee_movement"
ENTITY_DISCIPLINE = "discipline_case"
ENTITY_ABSCONDING = "absconding_case"

AUDIT_MOVEMENT_INITIATED = "employee movement initiated"
AUDIT_MOVEMENT_ACTIONED  = "employee movement actioned"
AUDIT_MOVEMENT_APPLIED   = "employee movement applied"
AUDIT_DISCIPLINE_CREATED       = "discipline case created"
AUDIT_DISCIPLINE_INVESTIGATED  = "discipline case investigation note added"
AUDIT_DISCIPLINE_RECOMMENDED   = "discipline case recommendation recorded"
AUDIT_DISCIPLINE_DECIDED       = "discipline case decided"
AUDIT_DISCIPLINE_CLOSED        = "discipline case closed"
AUDIT_ABSCONDING_FLAGGED   = "absconding case flagged"
AUDIT_ABSCONDING_CONTACT   = "absconding contact attempt logged"
AUDIT_ABSCONDING_WARNING   = "absconding warning sent"
AUDIT_ABSCONDING_DECIDED   = "absconding case final action recorded"
AUDIT_NOMINEE_DETAILS_SAVED = "nominee/legal details saved"

MAX_MOVEMENT_LIST_PAGE = 500


class MovementIn(BaseModel):
    """§7.16 step 120-122: the initiator names WHAT changes and to WHAT, never the current
    value — the service looks that up itself, the same discipline notice_days_for already
    established for calculated figures."""
    employee_code: str
    movement_type: MovementType
    to_value: str                                # the proposed designation_id / user_id /
                                                   # amount / free-text location or grade
    effective_date: str                           # YYYY-MM-DD
    reason: Optional[str] = None
    supporting_document: Optional[str] = None     # a link; base64 uploads use the document register


class MovementActionIn(BaseModel):
    approved: bool
    remarks: Optional[str] = None


class DisciplinePersonIn(BaseModel):
    employee_code: str
    role: PersonRole


class DisciplineCaseIn(BaseModel):
    category: DisciplineCategory
    persons_involved: list[DisciplinePersonIn]
    description: str
    confidentiality_level: Optional[ConfidentialityLevel] = None   # auto-derived if omitted


class DisciplineInvestigationIn(BaseModel):
    note: str
    evidence: Optional[str] = None


class DisciplineRecommendationIn(BaseModel):
    recommendation: str


class DisciplineDecisionIn(BaseModel):
    outcome: DisciplineOutcome
    remarks: Optional[str] = None


class DisciplineCloseIn(BaseModel):
    retention_classification: Optional[str] = None
    remarks: Optional[str] = None


class AbscondingFlagIn(BaseModel):
    employee_code: str
    flagged_date: Optional[str] = None            # YYYY-MM-DD; defaults to today
    notes: Optional[str] = None


class AbscondingContactIn(BaseModel):
    method: str                                    # Call / Email / Letter / Other — configurable, free text
    outcome: Optional[str] = None
    postal_tracking_ref: Optional[str] = None       # captured when a physical letter is used


class AbscondingWarningIn(BaseModel):
    remarks: Optional[str] = None


class AbscondingFinalActionIn(BaseModel):
    resolution: str                                 # "Returned to Work" or "Converted to Separation"
    remarks: Optional[str] = None


class RetirementPolicyIn(BaseModel):
    retirement_age: int
    alert_months_ahead: int = DEFAULT_RETIREMENT_ALERT_MONTHS


class NomineeDetailsIn(BaseModel):
    """§7.20 step 157: demise/missing nominee and legal documentation, captured on the
    separation record itself (exit_type Demise/Missing) — not a parallel case."""
    nominee_name: Optional[str] = None
    nominee_relation: Optional[str] = None
    nominee_contact: Optional[str] = None
    legal_document_ref: Optional[str] = None
    notes: Optional[str] = None


# =============================================================
# Phase PAY-1 — Payroll, Salary Advance & Variable Pay
# (BA/Functional Design §7.13-7.15, §22.7)
#
# Payroll is COMPONENT-DRIVEN (§22.7): a salary structure is a list of {component, amount}
# rows against a small configurable component master, not a fixed set of hardcoded fields.
# A payroll run imports each employee's structure, prorates it against Attendance's locked
# payable/LOP days (Phase ATT-1), auto-rolls-up open salary-advance recovery and the
# quarter's approved variable-pay payout the same way F&F auto-rolls-up asset/clearance
# recoveries, and takes every STATUTORY figure (PF/ESI/PT/TDS) by hand — §7.13's own BR says
# "Detailed statutory and salary-component configuration requires payroll workshop", so no
# Indian statutory formula is compiled in here, the same reasoning FnfInput's hand-entered
# figures already follow for the same missing-payroll-engine gap.
#
# IRM scores are ALSO taken by hand for Variable Pay, despite an IRM module already existing
# elsewhere in this codebase: that module keys on its own `person_id`, not this module's
# `employee_code`, and the BA doc itself offers "Import/enter" as two acceptable paths (step
# 111) — wiring the two together is a real, separate integration this phase does not attempt,
# a documented follow-up rather than a silent gap.
# =============================================================
class ComponentType(str, Enum):
    EARNING   = "Earning"
    DEDUCTION = "Deduction"


class PayrollRunStatus(str, Enum):
    DRAFT      = "Draft"
    CALCULATED = "Calculated"
    APPROVED   = "Approved"
    LOCKED     = "Locked"
    REJECTED   = "Rejected"     # sent back to the maker with a comment


class AdvanceStatus(str, Enum):
    PENDING    = "Pending"
    APPROVED   = "Approved"
    REJECTED   = "Rejected"
    RECOVERING = "Recovering"   # disbursed; payroll is deducting the recovery
    CLOSED     = "Closed"       # fully recovered


OPEN_ADVANCE_STATUSES = {AdvanceStatus.PENDING.value, AdvanceStatus.APPROVED.value,
                        AdvanceStatus.RECOVERING.value}


class VariablePayQuarterStatus(str, Enum):
    DRAFT      = "Draft"
    CALCULATED = "Calculated"
    APPROVED   = "Approved"
    CLOSED     = "Closed"


class HoldLedgerStatus(str, Enum):
    HELD      = "Held"
    RELEASED  = "Released"
    FORFEITED = "Forfeited"


# §7.14 BR: "Current policy baseline: 40% of gross, 20th-25th, once per quarter, confirmed
# employees, next-month deduction." An adjustable default (the same discipline
# DEFAULT_SHIFT_POLICY / DEFAULT_ABSCONDING_POLICY already established), read from
# hrms_settings, never compiled into the eligibility check as a literal number.
DEFAULT_ADVANCE_POLICY = {
    "max_percent_of_gross": 40,
    "window_start_day": 20,
    "window_end_day": 25,
}

# §7.15 BR: "Current policy: ORM >=80%, IRM >=70%; 75% payable quarterly and 25% held."
DEFAULT_VARIABLE_PAY_POLICY = {
    "orm_threshold": 80.0,
    "irm_threshold": 70.0,
    "payable_percent": 75,
    "held_percent": 25,
}


def variable_pay_multiplier(irm_score: float) -> float:
    """§7.15 BR's multiplier table, pure — no DB, no clock (same discipline notice_days_for
    established): "IRM 70-84.99% uses IRM%, 85%=100%, 85.01-90%=105%, >90%=115%." Returns a
    fraction (e.g. 0.75, not 75) so the caller multiplies it straight against the target
    amount. Callers below the IRM threshold never reach this — that gate is checked first.
    """
    if irm_score > 90:
        return 1.15
    if irm_score > 85:
        return 1.05
    if irm_score == 85:
        return 1.0
    return irm_score / 100.0


ENTITY_SALARY_COMPONENT = "salary_component"
ENTITY_SALARY_STRUCTURE = "salary_structure"
ENTITY_PAYROLL_RUN      = "payroll_run"
ENTITY_ADVANCE          = "salary_advance"
ENTITY_VARIABLE_PAY_QUARTER = "variable_pay_quarter"
ENTITY_HOLD_LEDGER          = "variable_pay_hold"

AUDIT_SALARY_COMPONENT_SAVED = "salary component saved"
AUDIT_SALARY_STRUCTURE_SAVED = "salary structure saved"
AUDIT_PAYROLL_RUN_CREATED    = "payroll run created"
AUDIT_PAYROLL_CALCULATED     = "payroll calculated"
AUDIT_PAYROLL_RECORD_ADJUSTED = "payroll record adjusted"
AUDIT_PAYROLL_ADJUSTMENTS_SET = "payroll ad-hoc components set"
AUDIT_PAYROLL_DECIDED        = "payroll run decided"
AUDIT_ADVANCE_REQUESTED = "salary advance requested"
AUDIT_ADVANCE_ACTIONED  = "salary advance actioned"
AUDIT_VP_QUARTER_CREATED = "variable pay quarter created"
AUDIT_VP_RECORD_SAVED    = "variable pay record saved"
AUDIT_VP_CALCULATED      = "variable pay calculated"
AUDIT_VP_DECIDED         = "variable pay quarter decided"
AUDIT_VP_HOLD_ACTIONED   = "variable pay hold actioned"

MAX_PAYROLL_LIST_PAGE = 500


class SalaryComponentIn(BaseModel):
    code: str
    name: str
    component_type: ComponentType
    statutory: bool = False
    active: bool = True


class SalaryStructureComponentIn(BaseModel):
    code: str
    amount: float


class SalaryStructureIn(BaseModel):
    """§7.16-adjacent, but NOT a movement: this is the detailed component breakdown behind
    the single `base_salary` figure a Compensation Change movement updates — the two stay in
    step by convention (HR updates both), not by a foreign key, the same loose coupling
    hrms_employee_profiles.legacy_department has to the masters."""
    employee_code: str
    effective_from: str                            # YYYY-MM-DD
    components: list[SalaryStructureComponentIn]


class PayslipTemplateIn(BaseModel):
    """SM-HR-064 — deliberately thin; see hrms_payslip_service.py's module docstring for
    why full statutory/component theming waits on the payroll workshop §7.13 itself names."""
    company_name: Optional[str] = None
    header_note: Optional[str] = None
    footer_note: Optional[str] = None


class PayrollRunCreateIn(BaseModel):
    period: str                                     # YYYY-MM


class PayrollRecordAdjustIn(BaseModel):
    """Every STATUTORY and manually-known figure for one employee in one run — entered by
    hand because no statutory engine exists yet (§7.13 BR). Salary-advance recovery and the
    quarter's approved variable pay are NOT here: the service rolls those up automatically."""
    pf: Optional[float] = None
    esi: Optional[float] = None
    pt: Optional[float] = None
    tds: Optional[float] = None
    arrears: Optional[float] = None
    reimbursements: Optional[float] = None
    other_earnings: Optional[float] = None
    other_deductions: Optional[float] = None
    notice_recovery: Optional[float] = None
    remarks: Optional[str] = None


class PayrollAdjustmentItemIn(BaseModel):
    """One ad-hoc line, against the SAME component master the recurring salary structure
    already uses (§22.7) — arbitrary named earnings/deductions, not the fixed handful of
    buckets PayrollRecordAdjustIn still covers alongside this."""
    code: str
    amount: float


class PayrollAdjustmentsIn(BaseModel):
    """Replaces this employee's whole ad-hoc component list for the period — the same
    "replace in place" convention save_salary_structure already uses, so re-submitting a
    corrected list never leaves a stale row behind."""
    adjustments: list[PayrollAdjustmentItemIn] = []


class PayrollApprovalIn(BaseModel):
    approved: bool
    remarks: Optional[str] = None


class AdvancePolicyIn(BaseModel):
    max_percent_of_gross: float = 40
    window_start_day: int = 20
    window_end_day: int = 25


class SalaryAdvanceIn(BaseModel):
    employee_code: str
    amount: float
    reason: Optional[str] = None


class SalaryAdvanceActionIn(BaseModel):
    approved: bool
    remarks: Optional[str] = None


class VariablePayPolicyIn(BaseModel):
    orm_threshold: float = 80.0
    irm_threshold: float = 70.0
    payable_percent: float = 75
    held_percent: float = 25


class VariablePayQuarterCreateIn(BaseModel):
    quarter: str                                    # e.g. "2026-Q1"
    orm_score: float


class VariablePayRecordIn(BaseModel):
    employee_code: str
    irm_score: float
    quarterly_target_amount: float


class VariablePayApprovalIn(BaseModel):
    approved: bool
    remarks: Optional[str] = None


class VariablePayHoldActionIn(BaseModel):
    action: str                                      # "Release" or "Forfeit"
    remarks: Optional[str] = None


# =============================================================
# Phase PIP-1 — Performance Improvement Plan (BA/Functional Design §22.5)
#
# Manager/HR initiates a PIP with objectives and support actions -> the employee
# acknowledges it -> the manager records periodic review notes -> at plan end HR (there is
# no separate Management sign-off tier named for PIP, unlike Discipline/Payroll) records the
# outcome. Objectives, support items and the review log are embedded arrays on the plan
# itself, the same "small, bounded, always read together" reasoning Phase MOVE-1's
# discipline investigation_log already follows, rather than three more child collections.
# =============================================================
class PipStatus(str, Enum):
    DRAFT  = "Draft"          # created, awaiting the employee's acknowledgement
    ACTIVE = "Active"         # acknowledged; reviews may be recorded
    CLOSED = "Closed"


class PipClosureResult(str, Enum):
    SUCCESSFULLY_CLOSED       = "Successfully Closed"
    EXTENDED                  = "Extended"
    FURTHER_ACTION_REQUIRED   = "Further Action Required"
    SEPARATION_RECOMMENDED    = "Separation Recommended"


ENTITY_PIP = "pip_record"

AUDIT_PIP_INITIATED     = "PIP initiated"
AUDIT_PIP_ACKNOWLEDGED  = "PIP acknowledged by employee"
AUDIT_PIP_REVIEW_ADDED  = "PIP review note added"
AUDIT_PIP_DECIDED       = "PIP outcome recorded"

MAX_PIP_LIST_PAGE = 500


class PipObjectiveIn(BaseModel):
    target_standard: str
    measure: Optional[str] = None
    weight: Optional[str] = None
    due_date: Optional[str] = None


class PipSupportIn(BaseModel):
    action: str
    owner: Optional[str] = None
    target_date: Optional[str] = None


class PipCreateIn(BaseModel):
    """§22.5 steps 215-216."""
    employee_code: str
    review_reference: Optional[str] = None          # the performance review / PSC this refers to
    issue_category: Optional[str] = None
    gap_statement: str
    start_date: str
    target_end_date: str
    review_frequency: Optional[str] = None          # e.g. "Monthly" — free text, no fixed enum given
    objectives: list[PipObjectiveIn] = []
    support: list[PipSupportIn] = []


class PipReviewIn(BaseModel):
    """§22.5 step 218."""
    progress: str
    evidence: Optional[str] = None
    manager_comments: Optional[str] = None
    employee_comments: Optional[str] = None


class PipDecisionIn(BaseModel):
    """§22.5 step 220."""
    closure_result: PipClosureResult
    final_rating: Optional[str] = None
    extension_date: Optional[str] = None            # only meaningful when closure_result is Extended
    next_action: Optional[str] = None
    remarks: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# Phase GMP-1 — Group Mediclaim Policy
# ─────────────────────────────────────────────────────────────
class GmpDependentIn(BaseModel):
    name: str
    relation: Optional[str] = None
    date_of_birth: Optional[str] = None


class GmpIn(BaseModel):
    """HR's upsert of one employee's GMP enrolment. Replaces the record in place —
    see hrms_gmp_service.py for why this is a current-state master, not a ledger."""
    insurer: Optional[str] = None
    policy_number: Optional[str] = None
    sum_insured: Optional[float] = None
    enrolled_on: Optional[str] = None
    status: str = "Active"                       # Active / Inactive
    dependents: list[GmpDependentIn] = []
    remarks: Optional[str] = None


ENTITY_GMP = "gmp_record"
AUDIT_GMP_SAVED = "GMP enrolment saved"


# ─────────────────────────────────────────────────────────────
# Phase ACCESS-1 — User / Role / Permission Administration (SM-HR-051)
# ─────────────────────────────────────────────────────────────
# What this phase builds vs. defers, and why:
#
#   BUILT — governance_role assignment. `hrms_role()` has always resolved a client-side
#   user's HRMS role from their `governance_role` field (HOD/HR/FINANCE/MD → MANAGER/HR/
#   FINANCE/MD), but nothing anywhere ever WROTE that field except a one-off migration
#   script — the BA doc's "assign" action (SM-HR-051) had no endpoint at all. This phase
#   is that endpoint.
#
#   BUILT — the read-only role/capability matrix ("review access"), served from
#   ROLE_CAPABILITIES itself so it can never drift from what the gates actually enforce.
#
#   REUSED, not rebuilt — "disable" (the BA doc's other primary action) already exists as
#   PATCH /users/{id}/status on the base platform, gated the same way (superadmin/admin/
#   the company's own clientadmin) this phase's own MODULE_ADMIN gate resolves to for
#   those same roles. Re-implementing account activation here would be a second, competing
#   write path over the same `is_active` field.
#
#   DEFERRED, explicitly, as workshop items rather than a silent gap — matching this
#   module's established treatment of anything the BA doc names but does not specify a
#   concrete rule for (see DEFAULT_ADVANCE_POLICY etc.): field/tab-level permission and
#   configurable data scope (today's model is all-or-nothing at the capability level,
#   company/client-scoped by tenancy — not a per-user configurable subset) and delegation
#   (temporary permission handoff to a proxy). Both are genuinely new subsystems, not gaps
#   in something already there, and the BA doc gives no rule for how either should behave.
ENTITY_ACCESS = "user_access"

AUDIT_GOVERNANCE_ROLE_CHANGED = "Governance role changed"

# Assignable via this screen. Every governance rung of the in-house tenant, and nothing
# else: HRMS has no client-company participants.
ASSIGNABLE_GOVERNANCE_ROLES = {"MD", "HR", "FINANCE", "HOD", "IMPLEMENTOR"}


class GovernanceRoleIn(BaseModel):
    """SM-HR-051. Empty string / None clears the assignment (falls back to EMPLOYEE)."""
    governance_role: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# Phase LETTER-1 — HR Letter / Document Generator (SM-HR-041)
# ─────────────────────────────────────────────────────────────
# Offer and Appointment letters already exist (render_offer_body / render_appointment_body)
# but deliberately produce HTML the browser prints, never a stored file — correct for THOSE
# two, which are always regenerable from the live offer/appointment record. SM-HR-041 is for
# every OTHER piece of controlled correspondence (confirmation, revision, warning, relieving,
# and whatever else HR needs), where there is no single source-of-truth record to regenerate
# from — the letter's rendered content IS the record, so it must actually be produced, stored
# and made immutable once issued. That is the one real gap this phase closes; it does not
# touch Offer/Appointment.
#
# Templates are HR-authored, mutable, `format_map`-based text (render_comm_body, already used
# by Offer/Appointment/Comm — no new merge-field syntax invented here). This phase seeds NO
# canned legal wording: unlike the notification/comm templates the module already ships,
# actual employee-correspondence text (a confirmation letter's exact clauses, a warning
# letter's language) is company- and jurisdiction-specific, and putting invented legal
# copy in front of a real employee is a much larger mistake than an empty template list HR
# fills in themselves — the same reasoning that kept fabricated policy text out of Phase
# ACCESS-1 and out of the HR Policy Library below.
class LetterStatus(str, Enum):
    DRAFT      = "Draft"        # generated, not yet issued — still regenerable in place
    ISSUED     = "Issued"       # locked: rendered_body and file are immutable from here
    SUPERSEDED = "Superseded"   # replaced by a reissue; content is retained for audit


ENTITY_LETTER = "letter"
ENTITY_LETTER_TEMPLATE = "letter_template"

AUDIT_LETTER_TEMPLATE_SAVED = "Letter template saved"
AUDIT_LETTER_GENERATED      = "Letter generated"
AUDIT_LETTER_ISSUED         = "Letter issued"
AUDIT_LETTER_REISSUED       = "Letter reissued"


class LetterTemplateIn(BaseModel):
    """HR authors the wording; there is no seeded default (see the phase note above)."""
    title: str
    body: str                            # format_map style, e.g. "Dear {employee_name}, ..."
    merge_fields: list[str] = []         # informational only — hints the UI, never enforced
    active: bool = True


class LetterGenerateIn(BaseModel):
    """SM-HR-041's "generate" action. `effective_date` defaults to today when omitted.
    `letter_no` regenerates an EXISTING Draft in place (only while it is still Draft) instead
    of minting a new one — the one point before `issue` where content may still change."""
    template_key: str
    employee_code: str
    letter_no: Optional[str] = None
    effective_date: Optional[str] = None
    approver_name: Optional[str] = None
    approver_designation: Optional[str] = None
    extra_fields: dict = {}               # merge values the employee record cannot supply


class LetterPreviewIn(LetterGenerateIn):
    """Same shape as generate — preview renders identically, it just never persists."""
    pass


class LetterReissueIn(LetterGenerateIn):
    """SM-HR-041's "reissue" action. A reason is mandatory: reissuing a controlled letter is
    a correction to something already issued under someone's name, not a routine edit."""
    reason: str


# ─────────────────────────────────────────────────────────────
# Phase ORIENT-1 — Orientation & Training (§22.3, screen SM-HR-057)
# ─────────────────────────────────────────────────────────────
# What this phase builds vs. defers, and why:
#
#   BUILT — a plan TEMPLATE register (optionally filtered to a department and/or
#   designation), auto-assignment of every matching template's items into one ASSIGNMENT per
#   employee at activation (§22.3 step 200), HR/Manager scheduling a trainer and date per
#   item (step 201), completion/waiver tracking with mandatory items staying open until one
#   or the other (step 204), and a daily escalation sweep for mandatory items still open past
#   a configurable number of days (step 207), built on the existing job-runner skeleton
#   (hrms_scheduler_service.py) rather than a second scheduling mechanism.
#
#   BUILT — "My Onboarding" (step 202) as the employee's own row-scoped view of the SAME
#   screen HR/Manager use, not a separate page — the identical pattern hrms_pip_service and
#   hrms_letter_service already establish for "one board, scoped by role" rather than a
#   second frontend surface per audience.
#
#   REUSES the capability this module already declared for the Day-1 checklist
#   (Cap.INDUCTION_READ/WRITE) rather than inventing a new one — see the Cap enum's own
#   comment for why its scope was broadened rather than left a dead pair.
#
#   DEFERRED, explicitly: filtering a plan by LOCATION or GRADE/LEVEL (the BA doc's "based on
#   company/unit, role, department, location or level", step 200). Department and
#   designation are the two dimensions an employee profile already carries in this codebase;
#   location and a separate grade/level master do not exist anywhere yet (confirmed: no
#   COLL_LOCATIONS, no standalone level master), and inventing one here — rather than as
#   part of whatever future phase builds SM-HR-049's organisation masters — would be scope
#   creep into a different gap. A plan with neither filter set applies company-wide, which
#   covers the common case in the meantime.
class OrientationItemStatus(str, Enum):
    PENDING   = "Pending"
    SCHEDULED = "Scheduled"
    COMPLETED = "Completed"
    WAIVED    = "Waived"


ENTITY_ORIENTATION_PLAN       = "orientation_plan"
ENTITY_ORIENTATION_ASSIGNMENT = "orientation_assignment"

AUDIT_ORIENTATION_PLAN_SAVED      = "Orientation plan saved"
AUDIT_ORIENTATION_ASSIGNED        = "Orientation plan assigned"
AUDIT_ORIENTATION_ITEM_SCHEDULED  = "Orientation session scheduled"
AUDIT_ORIENTATION_ITEM_COMPLETED  = "Orientation item completed"
AUDIT_ORIENTATION_ITEM_WAIVED     = "Orientation item waived"
AUDIT_ORIENTATION_ESCALATED       = "Orientation escalated to HR"

# Adjustable default, not frozen policy — like DEFAULT_ABSCONDING_POLICY's day-counts, the BA
# doc says escalation happens on "incomplete mandatory orientation" (step 207) without naming
# a number of days, so this ships as a sensible default rather than a hardcoded one.
DEFAULT_ORIENTATION_ESCALATION_DAYS = 14

# The field guarding against a second escalation notice for the same assignment — the same
# "burn on the record, not in process memory" pattern PROBATION_REMINDED_FIELD established.
ORIENTATION_ESCALATED_FIELD = "escalated"


class OrientationPlanItemIn(BaseModel):
    topic: str
    mandatory: bool = True
    trainer_hint: Optional[str] = None      # a suggested role/person; the actual trainer is
                                             # named when the session is scheduled (step 201)
    materials_url: Optional[str] = None     # step 205: training materials/policies linked
    sequence: int = 0


class OrientationPlanIn(BaseModel):
    """A plan applies company-wide when both filters are left unset; setting one narrows it
    to that department and/or designation. See the phase note above for why location/level
    are not filter dimensions here."""
    title: str
    department_id: Optional[str] = None
    designation_id: Optional[str] = None
    items: list[OrientationPlanItemIn] = []
    active: bool = True


class OrientationScheduleIn(BaseModel):
    """§22.3 step 201."""
    item_id: str
    trainer: str
    scheduled_at: str      # ISO date/datetime string — free text is not offered here because
                           # the escalation sweep reads it as a date


class OrientationCompleteIn(BaseModel):
    """§22.3 step 203."""
    item_id: str
    remarks: Optional[str] = None


class OrientationWaiveIn(BaseModel):
    """§22.3 step 204: a mandatory item may be formally waived instead of completed."""
    item_id: str
    reason: str


# ─────────────────────────────────────────────────────────────
# Phase PULSE-1 — 30/90-Day Pulse Survey (§22.4, screen SM-HR-058)
# ─────────────────────────────────────────────────────────────
# A DELIBERATELY SEPARATE module from hrms_survey_service.py (Phase INT-2's induction/
# probation feedback), not an extension of it — see the Cap.PULSE_READ/MANAGE/SUBMIT comment
# above for the reasoning: that module's anonymity guarantee (responses are never linkable
# to a person, aggregates suppressed below SURVEY_MIN_RESPONSES) is load-bearing for its two
# existing kinds, and this phase's requirements are the opposite of that guarantee by design
# — step 212 needs to know WHO scored low enough to need a follow-up, step 214 links a
# result into that SAME person's Employee 360°. Bolting an identifiable mode onto an
# anonymous-by-contract module would risk weakening a guarantee real responses already rely
# on; a parallel, narrowly-scoped module cannot.
#
# What this phase builds vs. defers:
#
#   BUILT — a DOJ-anchored, automatic 30-day and 90-day issuance (step 208-209), built on
#   the existing job-runner skeleton (hrms_scheduler_service.py), guarded by the response
#   row's own existence (one per employee per milestone — the unique index above) so it
#   fires exactly once per milestone even if onboarding tasks close early (BR-027).
#
#   BUILT — employee self-completion (step 210), a low-score follow-up flag with one HR
#   notification per response (step 212), and an HR completion-rate/average-score summary
#   (step 213, minus "common issues" — free-text theme extraction is a workshop item, not a
#   rule this phase can encode).
#
#   DEFERRED, explicitly: "Response visibility is configurable according to final HR policy"
#   (step 211) — the BA doc itself says the rule is not yet decided, so this phase ships the
#   simplest concrete default (HR/MD see identified responses; nobody else does) rather than
#   inventing a configurable-visibility system for a policy that does not exist yet.
class PulseMilestone(str, Enum):
    DAY_30 = "30"
    DAY_90 = "90"


class PulseResponseStatus(str, Enum):
    ISSUED    = "Issued"
    SUBMITTED = "Submitted"


ENTITY_PULSE_RESPONSE = "pulse_response"

AUDIT_PULSE_ISSUED       = "Pulse survey issued"
AUDIT_PULSE_SUBMITTED    = "Pulse survey submitted"
AUDIT_PULSE_CONFIG_SAVED = "Pulse survey questions saved"
AUDIT_PULSE_FOLLOW_UP    = "Pulse survey follow-up flagged"

# Adjustable defaults, not frozen policy — the same DEFAULT_ABSCONDING_POLICY-style pattern.
# The BA doc gives the 30/90-day milestones themselves as fixed (step 208), but names no
# specific question set or low-score threshold, so both ship as company-editable defaults.
DEFAULT_PULSE_QUESTIONS = [
    "How would you rate your onboarding experience so far?",
    "Do you have the tools and information you need to do your job?",
    "How connected do you feel to your team?",
    "How likely are you to recommend this as a good place to work?",
]
DEFAULT_PULSE_LOW_SCORE_THRESHOLD = 3.0   # out of 5 — at or below this, a follow-up is flagged


class PulseConfigIn(BaseModel):
    questions: list[str]


class PulseSubmitIn(BaseModel):
    """§22.4 step 210. `scores` keys are the question text itself (order-independent,
    survives a question-list edit between issuance and submission without index drift)."""
    scores: dict[str, float]
    comment: Optional[str] = None


# Populate the Client Hiring ceiling now that every Cap member exists. Kept at the very
# bottom so the set is complete before anything imports it, and so adding a capability to
# the client track is a one-line edit in `_seed_client_track_caps` above.
_seed_client_track_caps()
_seed_client_decision_caps()
_seed_client_owned_caps()
