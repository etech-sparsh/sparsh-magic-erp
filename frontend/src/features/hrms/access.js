// HRMS ▸ client-side access rules.
//
// MUST stay in lockstep with backend/app/utils/hrms_access.py. Where the two disagree the
// server wins — that is exactly the failure the source HRMS shipped, "rendering actions
// unconditionally that the API will 403 for" (FRONTEND_ANALYSIS §5). To make divergence
// structurally unlikely, the authoritative capability list is not re-derived here: it is
// fetched from GET /hrms/health and cached on the user (see HrmsGate). The helpers below
// exist only for the pre-fetch decisions the shell has to make synchronously — sidebar
// visibility and route guarding.
//
// HRMS is Sparsh Magic's own HR and hiring module: it hires and pays Sparsh's own staff.
// The ERP's client companies are never party to it. Internal staff get admin/support
// visibility. Opt-in per company — an absent `hrms_enabled` flag means OFF.

const INTERNAL_OWNER_ROLES = new Set(['superadmin']);
const INTERNAL_STAFF_ROLES = new Set(['admin', 'coach', 'staff']);
const CLIENT_ROLES = new Set(['clientadmin', 'clientuser']);

// Mirrors models/hrms.py HrmsRole.
export const HRMS_ROLE = {
  ADMIN: 'admin',
  INTERNAL: 'internal',
  MD: 'md',
  HR: 'hr',
  MANAGER: 'manager',
  EMPLOYEE: 'employee',
};

// Mirrors models/hrms.py Cap. Grows one phase at a time, alongside the backend.
export const CAP = {
  MODULE_ACCESS: 'module.access',
  MODULE_ADMIN: 'module.admin',
  AUDIT_READ: 'audit.read',

  // Phase 2
  EMPLOYEE_READ: 'employee.read',
  EMPLOYEE_WRITE: 'employee.write',
  EMPLOYEE_SALARY_READ: 'employee.salary.read',
  EMPLOYEE_SALARY_WRITE: 'employee.salary.write',
  DEPARTMENT_READ: 'department.read',
  DEPARTMENT_WRITE: 'department.write',
  DESIGNATION_READ: 'designation.read',
  DESIGNATION_WRITE: 'designation.write',

  // Phase 3
  REQUISITION_READ: 'requisition.read',
  REQUISITION_CREATE: 'requisition.create',
  REQUISITION_WRITE: 'requisition.write',
  REQUISITION_REVIEW_HR: 'requisition.review_hr',
  REQUISITION_APPROVE_MD: 'requisition.approve_md',
  REQUISITION_CLOSE: 'requisition.close',
  JD_READ: 'jd.read',
  JD_WRITE: 'jd.write',

  // Phase 4
  POSTING_READ: 'posting.read',
  POSTING_WRITE: 'posting.write',
  POSTING_APPROVE_EXEC_SEARCH: 'posting.approve_exec_search',

  // Phase 5
  CANDIDATE_READ: 'candidate.read',
  CANDIDATE_WRITE: 'candidate.write',
  CANDIDATE_SCREEN: 'candidate.screen',

  // Phase 6
  ASSESSMENT_READ: 'assessment.read',
  ASSESSMENT_SEND: 'assessment.send',
  ASSESSMENT_REVIEW: 'assessment.review',

  // Phase 7
  INTERVIEW_READ: 'interview.read',
  INTERVIEW_SCHEDULE: 'interview.schedule',
  INTERVIEW_EVALUATE: 'interview.evaluate',
  INTERVIEW_DECIDE_MD: 'interview.decide_md',

  // Phase 8
  OFFER_READ: 'offer.read',
  OFFER_WRITE: 'offer.write',
  OFFER_SEND: 'offer.send',

  // Phase 9
  ONBOARDING_READ: 'onboarding.read',
  ONBOARDING_WRITE: 'onboarding.write',
  // Separate from write on purpose: this is the irreversible step that creates an employee.
  ONBOARDING_GENERATE_ID: 'onboarding.generate_id',

  // Phase 10 — read-only analytics
  ANALYTICS_READ: 'analytics.read',
  REPORT_READ: 'report.read',
  // Separate from read on purpose: reading figures on screen and taking a file of personal
  // data off the system are different acts. A hiring manager has read, not export.
  REPORT_EXPORT: 'report.export',

  // Phase 11-R — recruitment review enhancements
  // Item 1: the public-link registry.
  LINK_READ: 'link.read',
  // Separate from read on purpose: revoking kills a live credential a candidate is holding.
  LINK_MANAGE: 'link.manage',

  // Item 2: documentation.
  DOCUMENT_READ: 'document.read',
  DOCUMENT_WRITE: 'document.write',
  // Separate from write on purpose: collecting paperwork and ATTESTING to it are different
  // acts. Sparsh support staff hold write and deliberately not verify.
  DOCUMENT_VERIFY: 'document.verify',

  // Item 3: appointment letters. Mirrors the offer capabilities exactly.
  APPOINTMENT_READ: 'appointment.read',
  APPOINTMENT_WRITE: 'appointment.write',
  // Separate from write: issuing the letter commits the company to employing somebody.
  APPOINTMENT_SEND: 'appointment.send',

  // Item 7: sanctioned strength + the over-sanction escalation ladder.
  SANCTION_READ: 'sanction.read',
  SANCTION_WRITE: 'sanction.write',
  REQUISITION_ESCALATE: 'requisition.escalate',

  // ══ Internal (in-house) recruitment track ══
  // Sparsh Magic hiring for itself. Granted per Annexure B of the Internal Recruitment SOP:
  // where the RACI says "A" the capability is an approval, "R" a write, "C"/"I" read only.
  // The budget gate — mandatory, and nothing may be sourced before it clears.
  REQUISITION_APPROVE_BUDGET: 'requisition.approve_budget',
  SCORECARD_READ: 'scorecard.read',
  SCORECARD_WRITE: 'scorecard.write',
  SCORECARD_APPROVE: 'scorecard.approve',
  REFERENCE_READ: 'reference.read',
  REFERENCE_WRITE: 'reference.write',
  // Phase INT-4 — the telephonic screen (SOP step 5). WRITE is HR's alone; the HOD holds
  // READ because they interview off the back of the call.
  TELEPHONIC_READ: 'telephonic.read',
  TELEPHONIC_WRITE: 'telephonic.write',
  // Phase INT-10 — the salary negotiation record (SOP step 9). HR writes; the HOD
  // (consulted) and Finance (accountable for the figure) read.
  NEGOTIATION_READ: 'negotiation.read',
  NEGOTIATION_WRITE: 'negotiation.write',
  // Phase INT-5 — the per-company rule set (SLA targets, retention, probation, score
  // bands). READ is wide; WRITE is Management's and Finance's.
  SETTINGS_READ: 'settings.read',
  SETTINGS_WRITE: 'settings.write',
  // Separate from offer.send: the SOP makes Management approval of the offer mandatory.
  OFFER_APPROVE: 'offer.approve',
  PROBATION_READ: 'probation.read',
  PROBATION_REVIEW: 'probation.review',
  PROBATION_CONFIRM: 'probation.confirm',
  INDUCTION_READ: 'induction.read',
  INDUCTION_WRITE: 'induction.write',
  EXCEPTION_READ: 'exception.read',
  EXCEPTION_WRITE: 'exception.write',
  EXCEPTION_APPROVE: 'exception.approve',
  PERSONNEL_FILE_CLOSE: 'personnel_file.close',

  // ══ Phase INT-2 — the remaining Internal Recruitment SOP controls ══
  // The internal shortlisting committee (SOP §5). Deliberately NOT held by Finance:
  // Finance approves what a role costs, never who fills it.
  SHORTLIST_READ: 'shortlist.read',
  SHORTLIST_WRITE: 'shortlist.write',
  // Pre-boarding engagement (SOP §6). Tracking, not a gate — nothing is blocked by it,
  // which is why there is no third "approve" capability.
  PREBOARDING_READ: 'preboarding.read',
  PREBOARDING_WRITE: 'preboarding.write',
  // The standing salary-band master (Annexure C). WRITE is Finance and the MD; HR reads,
  // because the bands are an annual agreement WITH Finance rather than HR's to rewrite.
  SALARY_BAND_READ: 'salary_band.read',
  SALARY_BAND_WRITE: 'salary_band.write',
  // Candidate communications (Annexure C). Editing a TEMPLATE is separate from sending,
  // because the templates carry the equal-opportunity and data-use wording.
  COMM_READ: 'comm.read',
  COMM_WRITE: 'comm.write',
  COMM_TEMPLATE_WRITE: 'comm.template.write',
  // New-hire experience surveys (SOP §10). READ is the AGGREGATE only — the server refuses
  // a breakdown below its suppression threshold, so this can never read one person.
  SURVEY_READ: 'survey.read',
  // The policy register (SOP §14). APPROVE is the MD's alone: approving a revision is what
  // makes a version the one in force.
  POLICY_READ: 'policy.read',
  POLICY_WRITE: 'policy.write',
  POLICY_APPROVE: 'policy.approve',
  // Executing a retention purge (SOP §13). MD only, and the same standard as probation
  // confirmation because both destroy or end something.
  RETENTION_PURGE: 'retention.purge',

  // ── Phase 12: background verification ──
  BACKGROUND_READ: 'background.read',
  BACKGROUND_WRITE: 'background.write',
  BACKGROUND_APPROVE: 'background.approve',
  // Attaching the interview report and recording — a disclosure decision, so a separate
  // capability from scheduling or evaluating an interview.
  INTERVIEW_MEDIA: 'interview.media',
  // ── Phase EXIT-1 — Exit Management (§7.18, §22.2, §7.21) ──
  // HR runs the process end to end; the reporting manager holds the one sign-off the BA doc
  // names explicitly (handover acceptance); Finance/the MD hold the two money gates (a
  // notice waiver, and the F&F payout) — see the ROLE_CAPABILITIES comments in
  // backend/app/models/hrms.py for the full RACI this mirrors.
  SEPARATION_READ: 'separation.read',
  SEPARATION_INITIATE: 'separation.initiate',
  SEPARATION_MANAGE: 'separation.manage',
  SEPARATION_APPROVE: 'separation.approve',
  HANDOVER_READ: 'handover.read',
  HANDOVER_WRITE: 'handover.write',
  HANDOVER_APPROVE: 'handover.approve',
  CLEARANCE_READ: 'clearance.read',
  CLEARANCE_MANAGE: 'clearance.manage',
  CLEARANCE_ACT: 'clearance.act',
  EXIT_INTERVIEW_READ: 'exit_interview.read',
  EXIT_INTERVIEW_WRITE: 'exit_interview.write',
  EXIT_INTERVIEW_SUBMIT: 'exit_interview.submit',
  FNF_READ: 'fnf.read',
  FNF_PREPARE: 'fnf.prepare',
  FNF_APPROVE: 'fnf.approve',
  // ── Phase ATT-1 — Attendance & Leave (§7.8-7.12, §22.8-22.9) ──
  // See ROLE_CAPABILITIES in backend/app/models/hrms.py for the full RACI this mirrors.
  ATTENDANCE_READ: 'attendance.read',
  ATTENDANCE_MARK: 'attendance.mark',
  ATTENDANCE_REGULARIZE_REQUEST: 'attendance.regularize_request',
  ATTENDANCE_REGULARIZE_APPROVE: 'attendance.regularize_approve',
  ATTENDANCE_LOCK: 'attendance.lock',
  OD_REQUEST: 'od.request',
  OD_APPROVE: 'od.approve',
  LEAVE_READ: 'leave.read',
  LEAVE_APPLY: 'leave.apply',
  LEAVE_APPROVE: 'leave.approve',
  LEAVE_POLICY_MANAGE: 'leave.policy_manage',
  COFF_EARN_REQUEST: 'coff.earn_request',
  COFF_APPROVE: 'coff.approve',
  // ── Phase MOVE-1 — Employee Movements & Discipline (§7.16, §7.17, §7.19, §7.20) ──
  // See ROLE_CAPABILITIES in backend/app/models/hrms.py for the full RACI this mirrors.
  MOVEMENT_READ: 'movement.read',
  MOVEMENT_INITIATE: 'movement.initiate',
  MOVEMENT_APPROVE: 'movement.approve',
  DISCIPLINE_READ: 'discipline.read',
  DISCIPLINE_MANAGE: 'discipline.manage',
  DISCIPLINE_DECIDE: 'discipline.decide',
  DISCIPLINE_POSH_READ: 'discipline.posh_read',
  DISCIPLINE_POSH_MANAGE: 'discipline.posh_manage',
  ABSCONDING_READ: 'absconding.read',
  ABSCONDING_MANAGE: 'absconding.manage',
  ABSCONDING_DECIDE: 'absconding.decide',
  RETIREMENT_ALERT_READ: 'retirement_alert.read',
  // ── Phase PAY-1 — Payroll, Salary Advance & Variable Pay (§7.13-7.15, §22.7) ──
  // See ROLE_CAPABILITIES in backend/app/models/hrms.py for the full RACI this mirrors.
  PAYROLL_READ: 'payroll.read',
  PAYROLL_PROCESS: 'payroll.process',
  PAYROLL_APPROVE: 'payroll.approve',
  SALARY_STRUCTURE_READ: 'salary_structure.read',
  SALARY_STRUCTURE_MANAGE: 'salary_structure.manage',
  ADVANCE_READ: 'advance.read',
  ADVANCE_REQUEST: 'advance.request',
  ADVANCE_APPROVE: 'advance.approve',
  ADVANCE_APPROVE_EMERGENCY: 'advance.approve_emergency',
  VARIABLE_PAY_READ: 'variable_pay.read',
  VARIABLE_PAY_PROCESS: 'variable_pay.process',
  VARIABLE_PAY_APPROVE: 'variable_pay.approve',
  VARIABLE_PAY_HOLD_MANAGE: 'variable_pay.hold_manage',
  // ── Phase PIP-1 — Performance Improvement Plan (§22.5) ──
  // See ROLE_CAPABILITIES in backend/app/models/hrms.py for the full RACI this mirrors.
  PIP_READ: 'pip.read',
  PIP_MANAGE: 'pip.manage',
  PIP_DECIDE: 'pip.decide',
  PIP_ACKNOWLEDGE: 'pip.acknowledge',
  LETTER_READ: 'letter.read',
  LETTER_MANAGE: 'letter.manage',
  PULSE_READ: 'pulse.read',
  PULSE_MANAGE: 'pulse.manage',
  PULSE_SUBMIT: 'pulse.submit',
  // ── Phase GMP-1 — Group Mediclaim Policy ──
  GMP_READ: 'gmp.read',
  GMP_WRITE: 'gmp.write',

  // Client Hiring, step 1 (PRO-fit SOP section 7). A separate track: these are the
  // only HRMS capabilities a client company's user can hold, and WRITE is split from
  // REVIEW so a client can raise a requisition but never declare it feasible.
  CLIENT_REQUISITION_READ: 'client_requisition.read',
  CLIENT_REQUISITION_WRITE: 'client_requisition.write',
  CLIENT_REQUISITION_REVIEW: 'client_requisition.review',
  // Step 2 — the Position Scorecard. Sparsh drafts and reviews; only the client
  // approves, which is why no Sparsh role holds the approve capability.
  CLIENT_SCORECARD_READ: 'client_scorecard.read',
  CLIENT_SCORECARD_WRITE: 'client_scorecard.write',
  CLIENT_SCORECARD_REVIEW: 'client_scorecard.review',
  CLIENT_SCORECARD_APPROVE: 'client_scorecard.approve',

  // ── Step 2b — the job posting ──
  // Sparsh-side only. The client agrees the benchmark and reads the candidates; the
  // advert and its public link are Sparsh's professional work.
  CLIENT_POSTING_READ: 'client_posting.read',
  CLIENT_POSTING_WRITE: 'client_posting.write',
  CLIENT_POSTING_PUBLISH: 'client_posting.publish',
  // Steps 3-4 — sourcing, screening and the CV share. The recruiter writes, the
  // Team Lead delivers, the client decides; no Sparsh role holds decide.
  CLIENT_CANDIDATE_READ: 'client_candidate.read',
  CLIENT_CANDIDATE_WRITE: 'client_candidate.write',
  CLIENT_CANDIDATE_SHARE: 'client_candidate.share',
  CLIENT_CANDIDATE_DECIDE: 'client_candidate.decide',
  // Step 5 — the assessment. Managing it and marking it are separate jobs, per
  // the SOP's own responsibility table; the client only reviews the result.
  CLIENT_ASSESSMENT_READ: 'client_assessment.read',
  CLIENT_ASSESSMENT_MANAGE: 'client_assessment.manage',
  CLIENT_ASSESSMENT_SCORE: 'client_assessment.score',
  CLIENT_ASSESSMENT_SHARE: 'client_assessment.share',
  CLIENT_ASSESSMENT_REVIEW: 'client_assessment.review',
  // Step 6 — the recorded interview. Sparsh conducts and delivers the recording;
  // the client watches it and selects. No Sparsh role holds decide.
  CLIENT_INTERVIEW_READ: 'client_interview.read',
  CLIENT_INTERVIEW_MANAGE: 'client_interview.manage',
  CLIENT_INTERVIEW_SHARE: 'client_interview.share',
  CLIENT_INTERVIEW_DECIDE: 'client_interview.decide',
  // Step 7 — reference check and the offer. References are Sparsh's alone. The
  // offer follows the SOP matrix: recruiter prepares, Team Lead verifies, client
  // approves and issues.
  CLIENT_REFERENCE_READ: 'client_reference.read',
  CLIENT_REFERENCE_WRITE: 'client_reference.write',
  CLIENT_OFFER_READ: 'client_offer.read',
  CLIENT_OFFER_WRITE: 'client_offer.write',
  CLIENT_OFFER_VERIFY: 'client_offer.verify',
  CLIENT_OFFER_RELEASE: 'client_offer.release',
  // Client HR approving pay above the range they themselves approved. One of the
  // client-exclusive decisions: subtracted from every Sparsh role server-side.
  CLIENT_OFFER_DEVIATE: 'client_offer.deviate',
  // Steps 8-9 — pre-boarding, joining, handover. The client confirms in writing
  // that the person started; the Team Lead's handover closes the requisition.
  CLIENT_JOINING_READ: 'client_joining.read',
  CLIENT_JOINING_MANAGE: 'client_joining.manage',
  CLIENT_JOINING_CONFIRM: 'client_joining.confirm',
  CLIENT_JOINING_HANDOVER: 'client_joining.handover',
  // Delivery analytics for the client track, separate from the internal
  // recruitment dashboard and gated separately from it.
  CLIENT_ANALYTICS_READ: 'client_analytics.read',
  // ── Phase POLICY-LIB-1 (§22.6) — the employee's own act of acknowledging a policy. ──
  POLICY_ACKNOWLEDGE: 'policy.acknowledge',
};

/** Sparsh internal user rather than a client-side one. Same precedence the backend uses
 *  (source collection → tag → role), so the two never disagree. */
export const isInternalUser = (user) => {
  if (!user) return false;
  if (user.tag === 'staff') return true;
  if (user.tag === 'learner') return false;
  const role = (user.role || '').toLowerCase();
  return INTERNAL_OWNER_ROLES.has(role) || INTERNAL_STAFF_ROLES.has(role);
};

export const isClientSideUser = (user) => !!user && !isInternalUser(user);

/** Resolve an ERP user to their HRMS role. Mirrors hrms_access.hrms_role exactly. */
export const hrmsRole = (user) => {
  if (!user) return null;
  const role = (user.role || '').trim().toLowerCase();

  if (isInternalUser(user)) {
    return INTERNAL_OWNER_ROLES.has(role) ? HRMS_ROLE.ADMIN : HRMS_ROLE.INTERNAL;
  }
  if (role === 'clientadmin') return HRMS_ROLE.MD;
  if (CLIENT_ROLES.has(role)) {
    const governance = (user.governance_role || '').trim().toUpperCase();
    if (governance === 'MD') return HRMS_ROLE.MD;
    if (governance === 'HR') return HRMS_ROLE.HR;
    if (governance === 'HOD') return HRMS_ROLE.MANAGER;
    return HRMS_ROLE.EMPLOYEE;
  }
  return null;
};

/** Can this user open HRMS at all?
 *  Internal staff always (they administer across clients); client-side users only while
 *  their company's HRMS toggle is ON. An absent flag means OFF — the module is opt-in,
 *  so a company stays dark until explicitly enabled.
 *
 *  Use this for SIDEBAR visibility, where failing closed is correct: a nav item that
 *  appears and then vanishes is worse than one that appears a moment late. For ROUTE
 *  guarding use hrmsAccessState() instead — see the note there. */
export const canAccessHrms = (user) => {
  if (!user) return false;
  if (isInternalUser(user)) return true;
  // Neither flag is the raw company toggle. The server (routes/user.py) splits it in two,
  // mirroring the two doors in utils/hrms_access.py:
  //
  //   hrms_enabled          -> the whole module; requires `is_internal`, so no client
  //                            company can ever reach payroll, employees or exits.
  //   client_hiring_enabled -> the Client Hiring track and nothing else.
  //
  // Do not "fix" either by reading a company toggle directly -- that would offer a module
  // every API call then 403s.
  return user.hrms_enabled === true || isClientTrackUser(user);
};

/** A client company's own user, admitted to Client Hiring and to nothing else.
 *
 *  Their capability set server-side is replaced wholesale with CLIENT_TRACK_CAPS, so every
 *  other HRMS screen would 403. The sidebar uses this to show them the one entry that
 *  works rather than a menu of doors that do not. */
export const isClientTrackUser = (user) =>
  !!user && !isInternalUser(user) && user.client_hiring_enabled === true;

/** Tri-state access, for ROUTE guarding: 'allowed' | 'denied' | 'unknown'.
 *
 *  Why this exists. AuthProvider sets `user` from the JWT immediately and then merges the
 *  full profile from /users/me in the BACKGROUND. The module flags (`hrms_enabled`) live
 *  only on the profile, not in the token — so for the first moments after a hard refresh
 *  or a deep link, a perfectly entitled client user has `hrms_enabled === undefined`.
 *
 *  A boolean guard reads that as "denied" and redirects them out of the module before the
 *  profile ever arrives, i.e. the module appears broken on every refresh. Distinguishing
 *  "not allowed" (flag is explicitly false) from "not known yet" (flag absent) lets the
 *  route guard WAIT instead of bouncing.
 *
 *  Internal users are decided from the token alone, so they are never 'unknown'. */
export const hrmsAccessState = (user) => {
  if (!user) return 'denied';
  if (isInternalUser(user)) return 'allowed';
  if (user.hrms_enabled === true) return 'allowed';
  // A client company's user reaches Client Hiring, and the routes under it are guarded
  // per-capability from there. Checked BEFORE the denial below: their `hrms_enabled` is
  // correctly false -- they are not entitled to the whole module -- and reading that as
  // "denied" would bounce them out of the one track they ARE entitled to.
  if (user.client_hiring_enabled === true) return 'allowed';
  if (user.hrms_enabled === false && user.client_hiring_enabled === false) return 'denied';
  return 'unknown';
};

/** Does this user administer HRMS configuration? Used for the settings surfaces (Phase 11).
 *  Deliberately NOT a raw role check anywhere else — feature gating uses `hasCap`. */
export const isHrmsAdmin = (user) => {
  const role = hrmsRole(user);
  return role === HRMS_ROLE.ADMIN || role === HRMS_ROLE.INTERNAL || role === HRMS_ROLE.MD;
};

/** Only Admin / Super Admin may switch the module on or off for a company.
 *  Matches routes/company.py update_company_hrms_access.
 *
 *  Necessary but NOT sufficient: that route also refuses to enable HRMS for any company
 *  that is not the in-house one. Pair this with `isInternalCompany(company)` wherever the
 *  toggle is rendered, or an admin is shown a switch the server will 403. */
export const canToggleHrms = (user) =>
  ['superadmin', 'admin'].includes((user?.role || '').toLowerCase());

/** Is this COMPANY the one the ERP is operated in-house by? HRMS exists only for it.
 *  Distinct from `isInternalUser`, which is about the person (platform staff) -- a
 *  company and a user are different axes and conflating them is how the module ended up
 *  reachable by client companies in the first place. */
export const isInternalCompany = (company) => company?.is_internal === true;

/** THE capability check. `caps` comes from GET /hrms/health — the server's own answer —
 *  so the UI shows exactly what the API will allow. Falls back to false when the health
 *  payload has not loaded, which fails CLOSED rather than flashing forbidden controls. */
export const hasCap = (caps, capability) =>
  Array.isArray(caps) && caps.includes(capability);

/** Landing route for a user entering /hrms. Phase 1 has a single shell; later phases
 *  route by role here (recruitment vs. self-service), mirroring tpmsHome(). */
/** Where /hrms sends somebody.
 *
 *  A client company's user lands on Client Hiring, because it is the only track they hold
 *  any capability in -- the shared HRMS home would show them a dashboard of numbers they
 *  are refused. */
export const hrmsHome = (user) =>
  (isClientTrackUser(user) ? '/hrms/client-hiring' : '/hrms');

export const HRMS_DISABLED_MESSAGE =
  'The HRMS module is not enabled for your company. Please contact your administrator.';
