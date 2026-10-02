import api from './api';

/**
 * HRMS ▸ authenticated API client.
 * Thin wrappers over the shared axios instance (house style — no react-query, matching
 * tpmsApi.js / taskApi.js). Backend routes live under /api/hrms (backend/app/routes/hrms.py).
 *
 * The public candidate endpoints (apply / assess / offer / onboard) deliberately do NOT
 * live here — they must be callable with no token, so they get their own client in
 * hrmsPublicApi.js from Phase 4.
 */

// ── Module ──
/** Module status + the caller's resolved role and capability list.
 *  This is the authority for UI gating: the frontend renders from the server's own
 *  capability answer rather than re-deriving permissions from role strings. */
export const getHrmsHealth = () => api.get('/hrms/health');

// ── Audit ──
/** Audit trail. Tenant-scoped server-side — a client-side caller is pinned to their own
 *  company regardless of the company_id param. */
export const getHrmsAudit = (params) => api.get('/hrms/audit', { params });

// ── Phase ACCESS-1 — User / Role / Permission Administration (SM-HR-051) ──
/** Read-only role -> capability table, served from the backend's own ROLE_CAPABILITIES
 *  so "review access" can never show something the gates do not actually enforce. */
export const getHrmsRoleMatrix = () => api.get('/hrms/access/role-matrix');
/** Assign (or clear, with an empty string) the governance ladder position that
 *  hrms_role() resolves a client-side user's HRMS role from. */
export const setGovernanceRole = (userId, governanceRole, params) =>
  api.put(`/hrms/access/employees/${userId}/governance-role`,
    { governance_role: governanceRole || null }, { params });

// ── Company module toggle (Admin / Super Admin only) ──
/** Switch HRMS on or off for a company. Lives here rather than in a company client
 *  because the capability and the 403 copy are HRMS's, not Company Management's. */
export const setHrmsAccess = (companyId, enabled) =>
  api.patch(`/companies/${companyId}/hrms-access`, { enabled });

// ── Company scope ──
/** Companies this caller may work with in HRMS. Internal staff get every HRMS-enabled
 *  company (they need a scope selector); client users get exactly their own. */
export const getHrmsCompanies = () => api.get('/hrms/companies');

// ── Departments ──
// `company_id` is optional for client-side users (the server pins them to their own
// company and ignores the param); internal staff must supply it.
export const getDepartments = (params) => api.get('/hrms/departments', { params });
export const createDepartment = (payload, params) =>
  api.post('/hrms/departments', payload, { params });
export const updateDepartment = (id, payload, params) =>
  api.patch(`/hrms/departments/${id}`, payload, { params });
export const deleteDepartment = (id, params) =>
  api.delete(`/hrms/departments/${id}`, { params });

// ── Designations ──
export const getDesignations = (params) => api.get('/hrms/designations', { params });
export const createDesignation = (payload, params) =>
  api.post('/hrms/designations', payload, { params });
export const updateDesignation = (id, payload, params) =>
  api.patch(`/hrms/designations/${id}`, payload, { params });
export const deleteDesignation = (id, params) =>
  api.delete(`/hrms/designations/${id}`, { params });

/** Distinct department/designation values already on the company's users, with usage
 *  counts. Read-only — nothing is auto-created; HR reviews and creates deliberately. */
export const getMasterSuggestions = (params) =>
  api.get('/hrms/masters/suggestions', { params });

// ── Employees ──
export const getEmployees = (params) => api.get('/hrms/employees', { params });
export const getEmployee = (userId, params) =>
  api.get(`/hrms/employees/${userId}`, { params });
export const createEmployee = (payload, params) =>
  api.post('/hrms/employees', payload, { params });
export const updateEmployee = (userId, payload, params) =>
  api.patch(`/hrms/employees/${userId}`, payload, { params });
export const getEmployeeHierarchy = (userId, params) =>
  api.get(`/hrms/employees/${userId}/hierarchy`, { params });
/** Company users who do not yet have an employee profile — the "Add employee" picker. */
export const getLinkableUsers = (params) => api.get('/hrms/employees/linkable', { params });
/** Your own employee record. Never gated by employee.read, and always includes your salary. */
export const getMyEmployeeProfile = () => api.get('/hrms/employees/me');

// ── Requisitions (FMS) ──
export const getRequisitions = (params) => api.get('/hrms/requisitions', { params });
export const getRequisition = (requestNo, params) =>
  api.get(`/hrms/requisitions/${requestNo}`, { params });
export const createRequisition = (payload, params) =>
  api.post('/hrms/requisitions', payload, { params });
export const updateRequisition = (requestNo, payload, params) =>
  api.patch(`/hrms/requisitions/${requestNo}`, payload, { params });
/** One transition of the approval chain.
 *  action = 'hr-verify' | 'hr-reject' | 'budget-approve' | 'budget-reject'
 *         | 'scorecard-approve' | 'scorecard-reject' | 'escalate-approve' | 'escalate-reject' */
export const actOnRequisition = (requestNo, payload, params) =>
  api.post(`/hrms/requisitions/${requestNo}/approve`, payload, { params });

// ── Job descriptions ──
// JDs are authored with their requisition and approved together, so there is deliberately
// no create and no independent approve/reject client.
export const getJds = (params) => api.get('/hrms/jd', { params });
export const getJd = (jdNo, params) => api.get(`/hrms/jd/${jdNo}`, { params });
export const updateJd = (jdNo, payload, params) =>
  api.patch(`/hrms/jd/${jdNo}`, payload, { params });

// ── Job postings (authenticated) ──
export const getPostings = (params) => api.get('/hrms/postings', { params });
export const getPosting = (code, params) =>
  api.get(`/hrms/postings/${code}`, { params });
export const getPostingHistory = (code, params) =>
  api.get(`/hrms/postings/${code}/history`, { params });
export const createPosting = (payload, params) =>
  api.post('/hrms/postings', payload, { params });
export const publishPosting = (code, params) =>
  api.post(`/hrms/postings/${code}/publish`, {}, { params });
export const approvePostingExecSearch = (code, payload, params) =>
  api.post(`/hrms/postings/${code}/approve-exec-search`, payload || {}, { params });
export const updatePosting = (code, payload, params) =>
  api.patch(`/hrms/postings/${code}`, payload, { params });
export const deletePosting = (code, params) =>
  api.delete(`/hrms/postings/${code}`, { params });

/** Preview the public apply URL for a posting code. Kept here so the one place that knows
 *  the public URL shape is the API client, not each component. */
export const applyUrlFor = (code) => `${window.location.origin}/apply/${code}`;

// ── Candidates, screening, journey ──
export const getCandidates = (params) => api.get('/hrms/candidates', { params });
export const getCandidate = (uk, params) => api.get(`/hrms/candidates/${uk}`, { params });
export const createCandidate = (payload, params) =>
  api.post('/hrms/candidates', payload, { params });
export const updateCandidate = (uk, payload, params) =>
  api.patch(`/hrms/candidates/${uk}`, payload, { params });
export const deleteCandidate = (uk, params) =>
  api.delete(`/hrms/candidates/${uk}`, { params });
/** Bulk triage. Returns {moved, skipped} — partial success is expected, not an error. */
export const screenCandidates = (payload, params) =>
  api.post('/hrms/candidates/screen', payload, { params });
/** Full history, reconstructed server-side from the audit trail. */
export const getCandidateJourney = (uk, params) =>
  api.get(`/hrms/candidates/${uk}/journey`, { params });

/** The HR Screening page's four blocks in one call (SOP §1-§3). */
export const getCandidateScreening = (uk, params) =>
  api.get(`/hrms/candidates/${uk}/screening`, { params });
export const recordCvScreening = (uk, payload, params) =>
  api.post(`/hrms/candidates/${uk}/cv-screening`, payload, { params });

// ── Assessments (dual review) ──
export const getAssessments = (params) => api.get('/hrms/assessments', { params });
export const getAssessableCandidates = (params) =>
  api.get('/hrms/assessments/assessable', { params });
export const sendAssessment = (payload, params) =>
  api.post('/hrms/assessments', payload, { params });
/** Record ONE reviewer's Pass/Fail. The server decides which slot you fill. */
export const reviewAssessment = (assessmentNo, payload, params) =>
  api.post(`/hrms/assessments/${assessmentNo}/review`, payload, { params });

/** The candidate-facing assessment link. 128-bit access code, case-sensitive. */
export const assessUrlFor = (code) => `${window.location.origin}/assess/${code}`;

// ── Interviews + scorecard ──
export const getInterviews = (params) => api.get('/hrms/interviews', { params });
export const getSchedulableCandidates = (params) =>
  api.get('/hrms/interviews/schedulable', { params });
export const scheduleInterview = (payload, params) =>
  api.post('/hrms/interviews', payload, { params });
export const updateInterview = (no, payload, params) =>
  api.patch(`/hrms/interviews/${no}`, payload, { params });
export const cancelInterview = (no, params) =>
  api.delete(`/hrms/interviews/${no}`, { params });
/** Record the scorecard. Six competencies 0-5, a decision and a required typed signature. */
export const evaluateInterview = (no, payload, params) =>
  api.post(`/hrms/interviews/${no}/evaluate`, payload, { params });
/** Calendar invite download URL (served as a file, not emailed — see PHASE_7_REPORT). */
export const inviteUrlFor = (no) =>
  `${import.meta.env.VITE_API_BASE_URL || '/api'}/hrms/interviews/${no}/invite.ics`;

// ── Offers ──
export const getOffers = (params) => api.get('/hrms/offers', { params });
export const getOfferableCandidates = (params) =>
  api.get('/hrms/offers/offerable', { params });
export const createOffer = (payload, params) => api.post('/hrms/offers', payload, { params });
export const updateOffer = (no, payload, params) =>
  api.patch(`/hrms/offers/${no}`, payload, { params });
export const sendOffer = (no, payload, params) =>
  api.post(`/hrms/offers/${no}/send`, payload, { params });
export const revokeOffer = (no, payload, params) =>
  api.post(`/hrms/offers/${no}/revoke`, payload, { params });
export const deleteOffer = (no, params) => api.delete(`/hrms/offers/${no}`, { params });

/** The candidate-facing offer link. 128-bit access code, case-sensitive. */
export const offerUrlFor = (code) => `${window.location.origin}/offer/${code}`;

// ── Onboarding ──
export const getOnboardings = (params) => api.get('/hrms/onboarding', { params });
export const getOnboardableCandidates = (params) =>
  api.get('/hrms/onboarding/onboardable', { params });
export const getOnboarding = (no, params) => api.get(`/hrms/onboarding/${no}`, { params });
export const startOnboarding = (payload, params) =>
  api.post('/hrms/onboarding', payload, { params });
export const updateOnboarding = (no, payload, params) =>
  api.patch(`/hrms/onboarding/${no}`, payload, { params });
export const updateOnboardingBg = (no, payload, params) =>
  api.post(`/hrms/onboarding/${no}/bg`, payload, { params });
export const verifyOnboardingDocuments = (no, params) =>
  api.post(`/hrms/onboarding/${no}/verify`, {}, { params });
export const addOnboardingDocuments = (no, payload, params) =>
  api.post(`/hrms/onboarding/${no}/documents`, payload, { params });
/** HR's verdict on ONE joining document: Verified, Rejected or Exception (§7.5 Stage 3). */
export const reviewOnboardingDocument = (no, payload, params) =>
  api.post(`/hrms/onboarding/${no}/documents/review`, payload, { params });
export const setOnboardingChecklist = (no, payload, params) =>
  api.post(`/hrms/onboarding/${no}/checklist`, payload, { params });
/** HR confirming the joiner actually reported, on what date, and the assignment made
 *  (§7.5 Stage 6): unit, department, designation, grade, location, reporting manager,
 *  employment category, employment status, payroll group. */
export const confirmOnboardingJoining = (no, payload, params) =>
  api.post(`/hrms/onboarding/${no}/joining`, payload, { params });
/** The irreversible step: mints the Employee ID and creates the employee record. */
export const generateEmployeeId = (no, params) =>
  api.post(`/hrms/onboarding/${no}/generate-id`, {}, { params });
/** Attach an onboarding-created employee record to a real login account. */
export const linkEmployeeUser = (employeeCode, payload, params) =>
  api.post(`/hrms/employees/link/${employeeCode}`, payload, { params });

/** The new hire's pre-onboarding link. 128-bit access code, case-sensitive. */
export const onboardUrlFor = (code) => `${window.location.origin}/onboard/${code}`;

// ── Analytics & reports (Phase 10, read-only) ──
export const getHrmsDashboard = (params) => api.get('/hrms/analytics/dashboard', { params });
export const getHrmsFunnel = (params) => api.get('/hrms/analytics/funnel', { params });
export const getHrmsBreakdown = (params) => api.get('/hrms/analytics/breakdown', { params });
export const getHrmsReport = (entity, params) =>
  api.get(`/hrms/reports/${entity}`, { params });

/** Position-wise CV status matrix (Phase 11-R, Item 4): one row per requisition, one
 *  column per stage. Same scoping and caps as every other analytics read. */
export const getHrmsPositions = (params) => api.get('/hrms/analytics/positions', { params });

// ══════════════════════════════════════════════════════════════
// Phase 11-R — recruitment review enhancements
// ══════════════════════════════════════════════════════════════

// ── Item 1: the public-link registry ──
// The registry SCREEN was removed (HRMS ▸ Links); its /hrms/links endpoints still exist
// server-side and still govern the candidate-facing links the pipeline issues, so nothing
// about link validity changed — only the admin view over them is gone.

// ── Item 2: documentation ──
export const getDocumentTypes = (params) => api.get('/hrms/document-types', { params });
export const createDocumentType = (payload, params) =>
  api.post('/hrms/document-types', payload, { params });
export const updateDocumentType = (id, payload, params) =>
  api.patch(`/hrms/document-types/${id}`, payload, { params });
export const deleteDocumentType = (id, params) =>
  api.delete(`/hrms/document-types/${id}`, { params });

export const getDocuments = (params) => api.get('/hrms/documents', { params });
export const getDocument = (docNo, params) => api.get(`/hrms/documents/${docNo}`, { params });
/** Every applicable type for one person, with its status or `Pending`, plus the read-only
 *  view over files already attached elsewhere (resume, KYC scans). */
export const getDocumentChecklist = (params) =>
  api.get('/hrms/documents/checklist', { params });
/** Upload a document, or a new version (supply `doc_no` for a version). */
export const uploadDocument = (payload, params) =>
  api.post('/hrms/documents', payload, { params });
export const updateDocument = (docNo, payload, params) =>
  api.patch(`/hrms/documents/${docNo}`, payload, { params });
/** Verify / reject / move to Under Review. Rejecting REQUIRES remarks. */
export const setDocumentStatus = (docNo, payload, params) =>
  api.post(`/hrms/documents/${docNo}/status`, payload, { params });
/** A short-lived signed URL, minted per request — never stored. */
export const getDocumentUrl = (docNo, params) =>
  api.get(`/hrms/documents/${docNo}/url`, { params });
export const deleteDocument = (docNo, params) =>
  api.delete(`/hrms/documents/${docNo}`, { params });

// ── Item 3: appointment letters ──
export const getAppointments = (params) => api.get('/hrms/appointments', { params });
export const getAppointableCandidates = (params) =>
  api.get('/hrms/appointments/eligible', { params });
export const getAppointment = (no, params) =>
  api.get(`/hrms/appointments/${no}`, { params });
export const createAppointment = (payload, params) =>
  api.post('/hrms/appointments', payload, { params });
export const updateAppointment = (no, payload, params) =>
  api.patch(`/hrms/appointments/${no}`, payload, { params });
export const sendAppointment = (no, payload, params) =>
  api.post(`/hrms/appointments/${no}/send`, payload, { params });
export const cancelAppointment = (no, payload, params) =>
  api.post(`/hrms/appointments/${no}/cancel`, payload, { params });

/** The candidate-facing appointment link. 128-bit access code, case-sensitive. */
export const appointmentUrlFor = (code) => `${window.location.origin}/appointment/${code}`;

// ── Item 7: sanctioned strength ──
export const getSanctionedStrength = (params) =>
  api.get('/hrms/sanctioned-strength', { params });
/** Live sanctioned/actual/available for ONE position — read by the requisition form on
 *  every change, so the raiser learns about escalation before they submit. */
export const getSanctionedPosition = (params) =>
  api.get('/hrms/sanctioned-strength/position', { params });
export const setSanctionedStrength = (payload, params) =>
  api.post('/hrms/sanctioned-strength', payload, { params });
export const updateSanctionedStrength = (id, payload, params) =>
  api.patch(`/hrms/sanctioned-strength/${id}`, payload, { params });
export const deleteSanctionedStrength = (id, params) =>
  api.delete(`/hrms/sanctioned-strength/${id}`, { params });

/** Download a report. The file is rendered SERVER-side from already-scoped rows, so this
 *  only has to save the blob — it never sees rows the API withheld. */
export const exportHrmsReport = async (entity, params) => {
  const res = await api.get(`/hrms/reports/${entity}/export`, {
    params, responseType: 'blob',
  });
  const disposition = res.headers?.['content-disposition'] || '';
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const url = URL.createObjectURL(res.data);
  const a = document.createElement('a');
  a.href = url;
  a.download = match?.[1] || `hrms_${entity}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return {
    truncated: res.headers?.['x-export-truncated'] === 'true',
    rows: Number(res.headers?.['x-export-rows'] || 0),
    total: Number(res.headers?.['x-export-total'] || 0),
  };
};

// ══════════════════════════════════════════════════════════════
// Internal (in-house) recruitment track
// ══════════════════════════════════════════════════════════════
// Sparsh Magic hiring for itself, governed by the Internal Recruitment SOP. Everything here
// is ADDITIVE: no existing call changed shape, and `track` is optional everywhere it appears,
// so a caller that omits it gets exactly the behaviour it had before.

/** Position scorecards — the bar a role is hired against, agreed before sourcing. */
export const getScorecards = (params) => api.get('/hrms/scorecards', { params });
export const getScorecard = (scrNo, params) =>
  api.get(`/hrms/scorecards/${scrNo}`, { params });
export const createScorecard = (payload, params) =>
  api.post('/hrms/scorecards', payload, { params });
export const updateScorecard = (scrNo, payload, params) =>
  api.patch(`/hrms/scorecards/${scrNo}`, payload, { params });
/** One approval signature. The scorecard completes when every required role has signed. */
export const approveScorecard = (scrNo, payload, params) =>
  api.post(`/hrms/scorecards/${scrNo}/approve`, payload, { params });
/** Score a candidate against their requisition's scorecard. Records; never moves them. */
export const evaluateAgainstScorecard = (uk, payload, params) =>
  api.post(`/hrms/candidates/${uk}/scorecard-evaluate`, payload, { params });

/** Reference checks. Mandatory before an internal offer; optional on the client track. */
export const getReferenceChecks = (params) => api.get('/hrms/reference-checks', { params });
export const getReferenceCheck = (refNo, params) =>
  api.get(`/hrms/reference-checks/${refNo}`, { params });
export const createReferenceCheck = (payload, params) =>
  api.post('/hrms/reference-checks', payload, { params });
export const updateReferenceCheck = (refNo, payload, params) =>
  api.patch(`/hrms/reference-checks/${refNo}`, payload, { params });

/**
 * Telephonic screening (SOP step 5) — the brief call between CV screening and the panel.
 * Internal track only. A PASSED screen is what clears a candidate for an interview; the
 * gate itself lives server-side on interview creation.
 */
export const getTelephonicScreenings = (params) =>
  api.get('/hrms/telephonic-screenings', { params });
export const getScreenableCandidates = (params) =>
  api.get('/hrms/telephonic-screenings/screenable', { params });
export const getTelephonicScreening = (telNo, params) =>
  api.get(`/hrms/telephonic-screenings/${telNo}`, { params });
export const createTelephonicScreening = (payload, params) =>
  api.post('/hrms/telephonic-screenings', payload, { params });
export const updateTelephonicScreening = (telNo, payload, params) =>
  api.patch(`/hrms/telephonic-screenings/${telNo}`, payload, { params });

/**
 * Per-company configuration (Phase INT-5) — SLA targets, retention periods, probation
 * duration, reminder tiers and score band floors. A company with no settings row follows
 * the module defaults, so `describe` always returns a complete, renderable table.
 */
export const getHrmsSettings = (params) => api.get('/hrms/settings', { params });
export const updateHrmsSettings = (payload, params) =>
  api.patch('/hrms/settings', payload, { params });
/** Stop overriding — distinct from setting a value that happens to equal the default. */
export const resetHrmsSettings = (keys, params) =>
  api.post('/hrms/settings/reset', { keys }, { params });

/**
 * The working calendar (Phase INT-6) — the dates SLA maths skips, for THIS company.
 * HRMS's own, never the ERP's global holidays master; `importHrmsHolidays` adopts a year
 * of that master as a copy, and is safe to run twice.
 */
export const getHrmsHolidays = (params) => api.get('/hrms/holidays', { params });
export const addHrmsHoliday = (payload, params) =>
  api.post('/hrms/holidays', payload, { params });
export const importHrmsHolidays = (year, params) =>
  api.post('/hrms/holidays/import', { year }, { params });
export const removeHrmsHoliday = (date, params) =>
  api.delete(`/hrms/holidays/${date}`, { params });

/**
 * The internal requisition tracker (Phase INT-7, Annexure C) — one row per internal
 * requisition with every stage rolled up server-side. Scoped exactly as the requisition
 * list is; `sla` filters by health: breached | on_track | met | not_started.
 */
export const getInternalTracker = (params) =>
  api.get('/hrms/internal-requisitions/tracker', { params });

/**
 * Salary negotiation (SOP step 9, spec §16) — the record of the rounds. The band gate on
 * the offer is unchanged; `getCandidateNegotiation` previews whether an offer at the latest
 * figure would pass it today.
 */
export const getNegotiationRounds = (params) => api.get('/hrms/negotiations', { params });
export const recordNegotiationRound = (payload, params) =>
  api.post('/hrms/negotiations', payload, { params });
export const getCandidateNegotiation = (uk, params) =>
  api.get(`/hrms/candidates/${uk}/negotiation`, { params });

/** Management's sign-off on an internal offer, mandatory before it can be sent. */
export const approveOffer = (offerNo, payload, params) =>
  api.post(`/hrms/offers/${offerNo}/approve`, payload, { params });

/** Probation. Recorded against the EMPLOYEE; confirming it also stamps the candidate's
 *  `Probation Confirmed` stage (Phase INT-15) — see hrms_probation_service. */
export const getProbations = (params) => api.get('/hrms/probation', { params });
export const getProbationsDue = (params) => api.get('/hrms/probation/due', { params });
export const getProbation = (prbNo, params) =>
  api.get(`/hrms/probation/${prbNo}`, { params });
export const openProbation = (payload, params) =>
  api.post('/hrms/probation', payload, { params });
export const updateProbation = (prbNo, payload, params) =>
  api.patch(`/hrms/probation/${prbNo}`, payload, { params });
/** The reporting manager's scored recommendation (§7.5 Stage 12) — the step BEFORE HR
 *  endorsement and the authorised confirm/extend/separate decision below. */
export const reviewProbation = (prbNo, payload, params) =>
  api.post(`/hrms/probation/${prbNo}/review`, payload, { params });
/** HR endorses the manager's recommendation, or returns it with a reason. Only an
 *  endorsed recommendation can be confirmed. */
export const hrReviewProbation = (prbNo, payload, params) =>
  api.post(`/hrms/probation/${prbNo}/hr-review`, payload, { params });
export const confirmProbation = (prbNo, payload, params) =>
  api.post(`/hrms/probation/${prbNo}/confirm`, payload, { params });
export const closePersonnelFile = (payload, params) =>
  api.post('/hrms/personnel-file/close', payload, { params });

/** The exception log. An APPROVED exception is the only thing that lifts a gate. */
export const getExceptions = (params) => api.get('/hrms/exceptions', { params });
export const getException = (excNo, params) =>
  api.get(`/hrms/exceptions/${excNo}`, { params });
export const raiseException = (payload, params) =>
  api.post('/hrms/exceptions', payload, { params });
export const decideException = (excNo, payload, params) =>
  api.post(`/hrms/exceptions/${excNo}/approve`, payload, { params });

/** SLA milestones for one requisition, and the open-breach sweep. */
export const getRequisitionSla = (requestNo, params) =>
  api.get(`/hrms/requisitions/${requestNo}/sla`, { params });
export const getSlaBreaches = (params) => api.get('/hrms/sla/breaches', { params });


// ══ Phase INT-2 — the remaining Internal Recruitment SOP controls ══
// Every call below is internal-track only. The server refuses a client requisition outright
// rather than half-applying a control the client track has no counterpart for.

/** The internal shortlisting committee (SOP §5). HR and the Department Head jointly
 *  finalise the shortlist, and a FINALISED record is what lifts the gate on `Selected`. */
export const getShortlistReviews = (params) =>
  api.get('/hrms/shortlist-reviews', { params });
export const getShortlistReview = (slrNo, params) =>
  api.get(`/hrms/shortlist-reviews/${slrNo}`, { params });
export const createShortlistReview = (payload, params) =>
  api.post('/hrms/shortlist-reviews', payload, { params });
export const updateShortlistReview = (slrNo, payload, params) =>
  api.patch(`/hrms/shortlist-reviews/${slrNo}`, payload, { params });

/** Batch interview windows (Annexure C). A PREFERENCE, never a rule — scheduling outside
 *  one warns in the response and books the interview anyway. */
export const getInterviewWindows = (params) =>
  api.get('/hrms/interview-windows', { params });
export const createInterviewWindow = (payload, params) =>
  api.post('/hrms/interview-windows', payload, { params });
export const updateInterviewWindow = (id, payload, params) =>
  api.patch(`/hrms/interview-windows/${id}`, payload, { params });
export const deleteInterviewWindow = (id, params) =>
  api.delete(`/hrms/interview-windows/${id}`, { params });

/** Pre-boarding engagement (SOP §6). Tracking, NOT a gate: nothing is blocked by a missing
 *  touchpoint. `due` splits never-contacted from gone-quiet, because those are two
 *  different conversations. */
export const getPreboarding = (params) => api.get('/hrms/preboarding', { params });
export const getPreboardingDue = (params) =>
  api.get('/hrms/preboarding/due', { params });
export const recordPreboardingTouchpoint = (payload, params) =>
  api.post('/hrms/preboarding', payload, { params });

/** The standing salary-band master (Annexure C). A CONVENIENCE for the budget gate; the
 *  offer check still reads the band stamped on the requisition, so a band edited today can
 *  never retroactively legalise an offer approved last month. */
export const getSalaryBands = (params) => api.get('/hrms/salary-bands', { params });
export const getSalaryBand = (bandNo, params) =>
  api.get(`/hrms/salary-bands/${bandNo}`, { params });
export const getSalaryBandPrefill = (requestNo, params) =>
  api.get(`/hrms/salary-bands/for-requisition/${requestNo}`, { params });
export const createSalaryBand = (payload, params) =>
  api.post('/hrms/salary-bands', payload, { params });
export const updateSalaryBand = (bandNo, payload, params) =>
  api.patch(`/hrms/salary-bands/${bandNo}`, payload, { params });

/** The talent pool (Annexure C). Listing is `getCandidates({ talent_pool: true, tags })` —
 *  the pool is a FILTER on the candidate list, not a second collection, so a pooled
 *  candidate keeps the same scoping and the same retention as every other CV. */
export const setTalentPool = (uk, payload, params) =>
  api.post(`/hrms/candidates/${uk}/talent-pool`, payload, { params });
export const sourceFromTalentPool = (uk, requestNo, params) =>
  api.post(`/hrms/candidates/${uk}/source-to/${requestNo}`, null, { params });

/** Candidate communications (Annexure C). Delivery goes through the existing notification
 *  service; what is new is the template and the append-only log. */
export const getCommunications = (params) => api.get('/hrms/communications', { params });
export const getCommTemplates = (params) =>
  api.get('/hrms/communications/templates', { params });
export const updateCommTemplate = (key, payload, params) =>
  api.patch(`/hrms/communications/templates/${key}`, payload, { params });
export const sendCommunication = (payload, params) =>
  api.post('/hrms/communications/send', payload, { params });

/** New-hire experience surveys (SOP §10). READ IS THE AGGREGATE ONLY — there is no endpoint
 *  that returns response rows, and the server suppresses any figure below its minimum
 *  response count. A survey a manager can de-anonymise measures nothing. */
export const getSurveys = (params) => api.get('/hrms/surveys', { params });
export const getSurveyResults = (params) => api.get('/hrms/surveys/results', { params });

/** All eight SOP KPIs, computed server-side and role-scoped. Every ratio carries
 *  `eligible_n`, and `excluded_n` where records were deliberately left out. */
export const getInternalKpis = (params) =>
  api.get('/hrms/analytics/internal-kpis', { params });

/** What is outstanding before a probation can be CONFIRMED (SOP §11). Surfaced while the
 *  probation is still running rather than sprung at the moment somebody tries to confirm. */
export const getProbationStatutory = (prbNo, params) =>
  api.get(`/hrms/probation/${prbNo}/statutory`, { params });

/** The policy register and its review cycle (SOP §14). A revision is DRAFTED and then
 *  APPROVED; drafting one changes nothing about which version governs. */
export const getPolicies = (params) => api.get('/hrms/policies', { params });
export const getPolicy = (policyKey, params) =>
  api.get(`/hrms/policies/${policyKey}`, { params });
export const getPolicyReviewsDue = (params) => api.get('/hrms/policies/due', { params });
export const registerPolicy = (payload, params) =>
  api.post('/hrms/policies', payload, { params });
/** The policy's own PDF, stored directly against the register. `file` is
 *  `{ name, mime_type, data }` with `data` as base64 (optionally a data: URL). */
export const uploadPolicyDocument = (policyKey, file, params) =>
  api.post(`/hrms/policies/${policyKey}/document`, { file }, { params });
export const logPolicyRevision = (policyKey, payload, params) =>
  api.post(`/hrms/policies/${policyKey}/revisions`, payload, { params });
export const approvePolicyRevision = (policyKey, payload, params) =>
  api.post(`/hrms/policies/${policyKey}/approve`, payload, { params });

// ── Phase POLICY-LIB-1 (§22.6) — the general HR Policy Library + acknowledgement ──
/** Every published policy applicable to the caller, flagged with their own acknowledgement
 *  status for its CURRENT version — the employee-facing screen, separate from the HR-side
 *  register above. */
export const getMyPolicies = (params) => api.get('/hrms/policies/mine', { params });
/** Category, applicability (department/employment type) and acknowledgement settings —
 *  metadata, not a content revision, so this needs no MD approval. */
export const updatePolicyApplicability = (policyKey, payload, params) =>
  api.patch(`/hrms/policies/${policyKey}/applicability`, payload, { params });
/** The employee's own act of acknowledging a published, applicable policy. */
export const acknowledgePolicy = (policyKey, params) =>
  api.post(`/hrms/policies/${policyKey}/acknowledge`, null, { params });
/** HR's completion view — who has acknowledged this policy's current version. */
export const getPolicyAcknowledgements = (policyKey, params) =>
  api.get(`/hrms/policies/${policyKey}/acknowledgements`, { params });
/** §22.12 — pending/completed counts across every policy requiring acknowledgement. */
export const getAcknowledgementDashboard = (params) =>
  api.get('/hrms/policies/acknowledgements/summary', { params });

/** The retention purge (SOP §13). Proposals come from `scripts/hrms_retention_purge.py`,
 *  which defaults to a dry run. Approving one REDACTS the personal fields and keeps the ids
 *  and the audit trail — it is not reversible. */
export const getPurgeBatches = (params) => api.get('/hrms/purge-batches', { params });
export const getPurgeBatch = (batchNo, params) =>
  api.get(`/hrms/purge-batches/${batchNo}`, { params });
export const approvePurgeBatch = (batchNo, payload, params) =>
  api.post(`/hrms/purge-batches/${batchNo}/approve`, payload, { params });

/** Printable record documents (SOP §9). One pattern for all five forms, gated by the
 *  entity's existing READ capability — printing a record is reading it. Returns a signed
 *  URL; every figure on the form is read from the record and nothing is re-entered. */
export const getRecordDocument = (entity, businessNo, params) =>
  api.get(`/hrms/records/${entity}/${businessNo}/document`, { params });

/* ═══════════════════════════════════════════════════════════════
 * Background verification — a mandatory gate on offers for both hiring tracks (Phase 12),
 * not a client-only stage. The rest of Phase 12's client hiring track (job requests, CV
 * sharing, the client's own candidate hub) was removed with client-track hiring itself —
 * see `_client_hiring_disabled` in backend/app/routes/hrms.py — and its bindings here went
 * with it.
 * ═══════════════════════════════════════════════════════════════ */

/** Background verification, and the approval that unlocks an offer. */
export const getBackgroundChecks = (params) =>
  api.get('/hrms/background-checks', { params });
export const getPendingVerifications = (params) =>
  api.get('/hrms/background-checks/pending', { params });
export const recordBackgroundCheck = (payload, params) =>
  api.post('/hrms/background-checks', payload, { params });
export const updateBackgroundCheck = (bgvNo, payload, params) =>
  api.patch(`/hrms/background-checks/${bgvNo}`, payload, { params });
export const getCandidateVerification = (uk, params) =>
  api.get(`/hrms/candidates/${uk}/verification`, { params });
/** HR's sign-off. Takes a typed signature — this is the step that unlocks the offer. */
export const decideVerification = (uk, payload, params) =>
  api.post(`/hrms/candidates/${uk}/verification/decide`, payload, { params });

/** Candidate CV upload. `resume` is {name, mime_type, data} with data base64. */
export const uploadCandidateCv = (uk, payload, params) =>
  api.post(`/hrms/candidates/${uk}/cv`, payload, { params });
export const getCandidateCv = (uk, params) =>
  api.get(`/hrms/candidates/${uk}/cv`, { params });

/* The photo and certificates the applicant attached to the form. Same access rule and
 * same audit trail as the CV — they are personal data in exactly the same way. */
export const getCandidateAttachment = (uk, slot, index, params) =>
  api.get(`/hrms/candidates/${uk}/attachment`, { params: { ...params, slot, index } });

/** Sparsh-side: every interview for a candidate, with scores and panel. */
export const getCandidateInterviews = (uk, params) =>
  api.get(`/hrms/candidates/${uk}/interviews`, { params });

// ── Phase EXIT-1 — Exit Management (§7.18, §22.2, §7.21) ──
// Resignation submitted -> notice calculated -> HR/manager records acceptance (an approval
// gate applies if it waives or shortens the calculated notice) -> Handover Plan and
// departmental Clearance/Asset-Return/Access-Clearance tasks run in parallel -> Exit
// Interview -> F&F prepared and approved -> the case closes. See hrms_exit_service.py.
export const getSeparations = (params) => api.get('/hrms/separations', { params });
export const getSeparation = (sepNo, params) =>
  api.get(`/hrms/separations/${sepNo}`, { params });
export const initiateSeparation = (payload, params) =>
  api.post('/hrms/separations', payload, { params });
export const decideSeparation = (sepNo, payload, params) =>
  api.patch(`/hrms/separations/${sepNo}/decision`, payload, { params });
export const approveSeparation = (sepNo, payload, params) =>
  api.post(`/hrms/separations/${sepNo}/approve`, payload, { params });
export const withdrawSeparation = (sepNo, remarks, params) =>
  api.post(`/hrms/separations/${sepNo}/withdraw`, null, { params: { ...params, remarks } });
export const closeSeparation = (sepNo, force, params) =>
  api.post(`/hrms/separations/${sepNo}/close`, null, { params: { ...params, force } });

/** Handover Plan (§22.2 step 190-191). */
export const getHandoverTasks = (sepNo, params) =>
  api.get(`/hrms/separations/${sepNo}/handover`, { params });
export const createHandoverTask = (sepNo, payload, params) =>
  api.post(`/hrms/separations/${sepNo}/handover`, payload, { params });
export const updateHandoverTask = (sepNo, taskId, payload, params) =>
  api.patch(`/hrms/separations/${sepNo}/handover/${taskId}`, payload, { params });
/** The reporting manager's sign-off on a submitted item. */
export const acceptHandoverTask = (sepNo, taskId, payload, params) =>
  api.post(`/hrms/separations/${sepNo}/handover/${taskId}/accept`, payload, { params });

/** Departmental Clearance — the five standard tasks (Manager/HR/IT/Admin/Finance) are seeded
 *  automatically once HR records the notice decision. */
export const getClearanceTasks = (sepNo, params) =>
  api.get(`/hrms/separations/${sepNo}/clearance`, { params });
export const createClearanceTask = (sepNo, payload, params) =>
  api.post(`/hrms/separations/${sepNo}/clearance`, payload, { params });
export const actOnClearanceTask = (sepNo, taskId, payload, params) =>
  api.patch(`/hrms/separations/${sepNo}/clearance/${taskId}`, payload, { params });

/** Asset Return Requests. */
export const getAssetReturns = (sepNo, params) =>
  api.get(`/hrms/separations/${sepNo}/asset-returns`, { params });
export const createAssetReturn = (sepNo, payload, params) =>
  api.post(`/hrms/separations/${sepNo}/asset-returns`, payload, { params });
export const updateAssetReturn = (sepNo, astNo, payload, params) =>
  api.patch(`/hrms/separations/${sepNo}/asset-returns/${astNo}`, payload, { params });

/** Access Clearance (email, applications, VPN, client systems, physical access, cards/keys). */
export const getAccessClearances = (sepNo, params) =>
  api.get(`/hrms/separations/${sepNo}/access-clearance`, { params });
export const createAccessClearance = (sepNo, payload, params) =>
  api.post(`/hrms/separations/${sepNo}/access-clearance`, payload, { params });
export const updateAccessClearance = (sepNo, itemId, payload, params) =>
  api.patch(`/hrms/separations/${sepNo}/access-clearance/${itemId}`, payload, { params });

/** Exit Interview — one per case; a re-submit corrects the same record. */
export const getExitInterview = (sepNo, params) =>
  api.get(`/hrms/separations/${sepNo}/exit-interview`, { params });
export const saveExitInterview = (sepNo, payload, params) =>
  api.put(`/hrms/separations/${sepNo}/exit-interview`, payload, { params });

/** Full & Final Settlement. No payroll engine exists behind this yet (§7.13) — see
 *  FnfInput's docstring in models/hrms.py for what it can and cannot compute. */
export const getFnf = (sepNo, params) => api.get(`/hrms/separations/${sepNo}/fnf`, { params });
export const saveFnf = (sepNo, payload, params) =>
  api.put(`/hrms/separations/${sepNo}/fnf`, payload, { params });
export const approveFnf = (sepNo, payload, params) =>
  api.post(`/hrms/separations/${sepNo}/fnf/approve`, payload, { params });
export const markFnfPaid = (sepNo, payload, params) =>
  api.post(`/hrms/separations/${sepNo}/fnf/paid`, payload, { params });

// ── Phase ATT-1 — Attendance & Leave (§7.8-7.12, §22.8-22.9) ──
// Daily capture -> the engine derives status/late-minutes against the company's shift policy
// -> exceptions are regularised (employee -> manager -> HR) -> HR locks the month. Leave runs
// in parallel: apply -> manager -> HR -> ledger; C-Off is its own earn-then-use ledger. See
// hrms_attendance_service.py / hrms_leave_service.py.
export const getShiftPolicy = (params) => api.get('/hrms/attendance/shift-policy', { params });
export const saveShiftPolicy = (payload, params) =>
  api.put('/hrms/attendance/shift-policy', payload, { params });

export const markAttendance = (payload, params) =>
  api.post('/hrms/attendance/mark', payload, { params });
export const getAttendance = (params) => api.get('/hrms/attendance', { params });
export const getLateComingSummary = (params) =>
  api.get('/hrms/attendance/late-coming', { params });

export const requestRegularization = (payload, params) =>
  api.post('/hrms/attendance/regularizations', payload, { params });
export const getRegularizations = (params) =>
  api.get('/hrms/attendance/regularizations', { params });
export const actOnRegularization = (reqNo, payload, params) =>
  api.patch(`/hrms/attendance/regularizations/${reqNo}`, payload, { params });

export const requestOd = (payload, params) => api.post('/hrms/attendance/od', payload, { params });
export const getOdRequests = (params) => api.get('/hrms/attendance/od', { params });
export const actOnOd = (odNo, payload, params) =>
  api.post(`/hrms/attendance/od/${odNo}/action`, payload, { params });

/** §7.12 monthly closure — what is still open, then lock/unlock the period. */
export const getClosureDashboard = (period, params) =>
  api.get(`/hrms/attendance/closure/${period}`, { params });
export const lockPeriod = (period, params) =>
  api.post(`/hrms/attendance/closure/${period}/lock`, null, { params });
export const unlockPeriod = (period, reason, params) =>
  api.post(`/hrms/attendance/closure/${period}/unlock`, { reason }, { params });

/** §22.8 leave-type policy register — NOT frozen; see LeaveTypeConfigIn's docstring. */
export const getLeaveTypes = (params) => api.get('/hrms/leave/types', { params });
export const saveLeaveType = (code, payload, params) =>
  api.put(`/hrms/leave/types/${code}`, payload, { params });

export const getLeaveBalances = (employeeCode, year, params) =>
  api.get(`/hrms/leave/balances/${employeeCode}`, { params: { ...params, year } });
export const adjustLeaveBalance = (payload, params) =>
  api.post('/hrms/leave/balances/adjust', payload, { params });

export const applyLeave = (payload, params) => api.post('/hrms/leave', payload, { params });
export const getLeaves = (params) => api.get('/hrms/leave', { params });
export const actOnLeave = (leaveNo, payload, params) =>
  api.patch(`/hrms/leave/${leaveNo}`, payload, { params });
export const cancelLeave = (leaveNo, reason, params) =>
  api.post(`/hrms/leave/${leaveNo}/cancel`, { reason }, { params });

/** §7.11 Compensatory Off — earn (approved work on a holiday) then use (a leave application
 *  of type "C-Off", debited FIFO by nearest expiry). */
export const requestCoffEarn = (payload, params) => api.post('/hrms/coff/earn', payload, { params });
export const getCoffLedger = (params) => api.get('/hrms/coff/ledger', { params });
export const actOnCoffEarn = (batchId, payload, params) =>
  api.post(`/hrms/coff/earn/${batchId}/action`, payload, { params });

// ── Phase MOVE-1 — Employee Movements & Discipline (§7.16, §7.17, §7.19, §7.20) ──
// A movement is proposed against the employee's current value (looked up server-side) ->
// approved -> applied on its effective date. Discipline runs case -> investigation ->
// recommendation -> management decision -> closure, with POSH cases in a separate,
// narrower-access tier. Absconding is a 3-day-absence flag -> contact log -> two-stage
// warning ladder -> a final decision that resolves the case or hands off to Exit Management.
// Retirement is a proactive alert; demise/missing nominee details live on the separation
// record itself. See hrms_movement_service.py / hrms_discipline_service.py /
// hrms_absconding_service.py / hrms_retirement_service.py.
export const initiateMovement = (payload, params) => api.post('/hrms/movements', payload, { params });
export const getMovements = (params) => api.get('/hrms/movements', { params });
export const actOnMovement = (moveNo, payload, params) =>
  api.patch(`/hrms/movements/${moveNo}`, payload, { params });

export const createDisciplineCase = (payload, params) => api.post('/hrms/discipline', payload, { params });
export const getDisciplineCases = (params) => api.get('/hrms/discipline', { params });
export const getDisciplineCase = (caseNo, params) =>
  api.get(`/hrms/discipline/${caseNo}`, { params });
export const addDisciplineInvestigationNote = (caseNo, payload, params) =>
  api.post(`/hrms/discipline/${caseNo}/investigate`, payload, { params });
export const recordDisciplineRecommendation = (caseNo, payload, params) =>
  api.post(`/hrms/discipline/${caseNo}/recommend`, payload, { params });
export const decideDisciplineCase = (caseNo, payload, params) =>
  api.post(`/hrms/discipline/${caseNo}/decide`, payload, { params });
export const closeDisciplineCase = (caseNo, payload, params) =>
  api.post(`/hrms/discipline/${caseNo}/close`, payload, { params });
export const getDisciplineEmployeeSummary = (employeeCode, params) =>
  api.get(`/hrms/discipline/employee/${employeeCode}/summary`, { params });

export const getAbscondingPolicy = (params) => api.get('/hrms/absconding/policy', { params });
export const saveAbscondingPolicy = (payload, params) =>
  api.put('/hrms/absconding/policy', payload, { params });
export const flagAbscondingCase = (payload, params) => api.post('/hrms/absconding', payload, { params });
export const getAbscondingCases = (params) => api.get('/hrms/absconding', { params });
export const getAbscondingCase = (caseNo, params) =>
  api.get(`/hrms/absconding/${caseNo}`, { params });
export const logAbscondingContact = (caseNo, payload, params) =>
  api.post(`/hrms/absconding/${caseNo}/contact`, payload, { params });
export const sendAbscondingWarning = (caseNo, stage, payload, params) =>
  api.post(`/hrms/absconding/${caseNo}/warning/${stage}`, payload, { params });
export const absconderFinalAction = (caseNo, payload, params) =>
  api.post(`/hrms/absconding/${caseNo}/final-action`, payload, { params });

export const getRetirementPolicy = (params) => api.get('/hrms/retirement/policy', { params });
export const saveRetirementPolicy = (payload, params) =>
  api.put('/hrms/retirement/policy', payload, { params });
export const getUpcomingRetirements = (params) => api.get('/hrms/retirement/upcoming', { params });

/** §7.20 step 157 — demise/missing nominee & legal documentation, on the separation record. */
export const saveNomineeDetails = (sepNo, payload, params) =>
  api.put(`/hrms/separations/${sepNo}/nominee-details`, payload, { params });

// ── Phase PAY-1 — Payroll, Salary Advance & Variable Pay (§7.13-7.15, §22.7) ──
// Payroll is component-driven (§22.7): a salary structure is a list of {component, amount}
// against a small configurable master. A run imports each employee's structure, prorates it
// against Attendance's locked payable/LOP days, auto-rolls-up open salary-advance recovery
// and the quarter's approved variable pay, and takes every statutory figure (PF/ESI/PT/TDS)
// by hand — no statutory engine exists (§7.13 BR). See hrms_payroll_service.py /
// hrms_salary_advance_service.py / hrms_variable_pay_service.py.
export const listSalaryComponents = (params) => api.get('/hrms/salary-components', { params });
export const saveSalaryComponent = (code, payload, params) =>
  api.put(`/hrms/salary-components/${code}`, payload, { params });
export const saveSalaryStructure = (payload, params) =>
  api.put('/hrms/salary-structures', payload, { params });
export const getSalaryStructureHistory = (employeeCode, params) =>
  api.get(`/hrms/salary-structures/${employeeCode}`, { params });

export const createPayrollRun = (payload, params) => api.post('/hrms/payroll/runs', payload, { params });
export const listPayrollRuns = (params) => api.get('/hrms/payroll/runs', { params });
export const getPayrollRun = (period, params) => api.get(`/hrms/payroll/runs/${period}`, { params });
export const calculatePayroll = (period, params) =>
  api.post(`/hrms/payroll/runs/${period}/calculate`, null, { params });
export const listPayrollRecords = (period, params) =>
  api.get(`/hrms/payroll/runs/${period}/records`, { params });
export const adjustPayrollRecord = (period, employeeCode, payload, params) =>
  api.patch(`/hrms/payroll/runs/${period}/records/${employeeCode}`, payload, { params });
/** §22.7 — arbitrary named earning/deduction lines against the salary component master,
 *  alongside (not instead of) adjustPayrollRecord's fixed PF/ESI/arrears/etc. fields.
 *  `adjustments` is `[{code, amount}]`; replaces the employee's whole list for the period. */
export const setPayrollAdjustments = (period, employeeCode, adjustments, params) =>
  api.put(`/hrms/payroll/runs/${period}/records/${employeeCode}/adjustments`,
    { adjustments }, { params });
export const decidePayrollRun = (period, payload, params) =>
  api.post(`/hrms/payroll/runs/${period}/decision`, payload, { params });

// ── Phase PAYSLIP-1 (§22.7, SM-HR-031/SM-HR-064) ──
/** The itemised payslip for one period. An employee always gets their OWN — employee_code
 *  is ignored for that role server-side; HR/Payroll must pass one. */
export const getPayslip = (period, params) => api.get(`/hrms/payslips/${period}`, { params });
/** Every payslip in one run — HR-only bulk view, used for print/download-all. */
export const listPayslips = (period, params) =>
  api.get(`/hrms/payroll/runs/${period}/payslips`, { params });
export const getPayslipTemplate = (params) => api.get('/hrms/payslip-template', { params });
export const savePayslipTemplate = (payload, params) =>
  api.put('/hrms/payslip-template', payload, { params });

export const getAdvancePolicy = (params) => api.get('/hrms/advances/policy', { params });
export const saveAdvancePolicy = (payload, params) =>
  api.put('/hrms/advances/policy', payload, { params });
export const checkAdvanceEligibility = (employeeCode, params) =>
  api.get(`/hrms/advances/eligibility/${employeeCode}`, { params });
export const requestAdvance = (payload, params) => api.post('/hrms/advances', payload, { params });
export const listAdvances = (params) => api.get('/hrms/advances', { params });
export const getAdvance = (advNo, params) => api.get(`/hrms/advances/${advNo}`, { params });
export const actOnAdvance = (advNo, payload, params) =>
  api.post(`/hrms/advances/${advNo}/action`, payload, { params });
export const actOnAdvanceEmergency = (advNo, payload, params) =>
  api.post(`/hrms/advances/${advNo}/action-emergency`, payload, { params });

export const getVariablePayPolicy = (params) => api.get('/hrms/variable-pay/policy', { params });
export const saveVariablePayPolicy = (payload, params) =>
  api.put('/hrms/variable-pay/policy', payload, { params });
export const createVariablePayQuarter = (payload, params) =>
  api.post('/hrms/variable-pay/quarters', payload, { params });
export const listVariablePayQuarters = (params) => api.get('/hrms/variable-pay/quarters', { params });
export const getVariablePayQuarter = (quarter, params) =>
  api.get(`/hrms/variable-pay/quarters/${quarter}`, { params });
export const saveVariablePayRecord = (quarter, payload, params) =>
  api.post(`/hrms/variable-pay/quarters/${quarter}/records`, payload, { params });
export const listVariablePayRecords = (quarter, params) =>
  api.get(`/hrms/variable-pay/quarters/${quarter}/records`, { params });
export const calculateVariablePay = (quarter, params) =>
  api.post(`/hrms/variable-pay/quarters/${quarter}/calculate`, null, { params });
export const decideVariablePayQuarter = (quarter, payload, params) =>
  api.post(`/hrms/variable-pay/quarters/${quarter}/decision`, payload, { params });
export const listVariablePayHoldLedger = (params) =>
  api.get('/hrms/variable-pay/hold-ledger', { params });
export const actOnVariablePayHold = (holdId, payload, params) =>
  api.post(`/hrms/variable-pay/hold-ledger/${holdId}/action`, payload, { params });

// ── Phase PIP-1 — Performance Improvement Plan (§22.5) ──
// Manager/HR initiates with objectives/support -> employee acknowledges -> the manager
// records periodic review notes -> HR records the final outcome. See hrms_pip_service.py.
export const initiatePip = (payload, params) => api.post('/hrms/pip', payload, { params });
export const listPips = (params) => api.get('/hrms/pip', { params });
export const getPip = (pipNo, params) => api.get(`/hrms/pip/${pipNo}`, { params });
export const acknowledgePip = (pipNo, params) =>
  api.post(`/hrms/pip/${pipNo}/acknowledge`, null, { params });
export const addPipReview = (pipNo, payload, params) =>
  api.post(`/hrms/pip/${pipNo}/reviews`, payload, { params });
export const decidePip = (pipNo, payload, params) =>
  api.post(`/hrms/pip/${pipNo}/decision`, payload, { params });

// ── Phase GMP-1 — Group Mediclaim Policy ──
/** One current enrolment per employee. An employee reads only their own; HR reads/writes
 *  the company's. See hrms_gmp_service.py — this is an edited-in-place master, not a
 *  ledger, so there is no history endpoint. */
export const getGmp = (employeeCode, params) => api.get(`/hrms/gmp/${employeeCode}`, { params });
export const saveGmp = (employeeCode, payload, params) =>
  api.put(`/hrms/gmp/${employeeCode}`, payload, { params });

// ── Phase 360-1 — Employee 360° (§6) ──
// A pure aggregation over every module that already tracks this employee — no new capability
// gate. The base profile call decides who may open it at all; each section inside is
// included only if the caller separately holds that section's own read capability, so a
// missing key means "not authorised to see this", not "empty". See hrms_employee_360_service.py.
export const getEmployee360 = (userId, params) => api.get(`/hrms/employees/${userId}/360`, { params });

// ── Phase ORIENT-1 — Orientation & Training (§22.3, screen SM-HR-057) ──
// One board, scoped by role: HR/Manager manage plan templates and every assignment; an
// employee's own read is row-scoped server-side to just their own record ("My Onboarding").
export const getOrientationPlans = (params) => api.get('/hrms/orientation/plans', { params });
export const createOrientationPlan = (payload, params) =>
  api.post('/hrms/orientation/plans', payload, { params });
export const updateOrientationPlan = (planNo, payload, params) =>
  api.put(`/hrms/orientation/plans/${planNo}`, payload, { params });
export const listOrientationAssignments = (params) =>
  api.get('/hrms/orientation/assignments', { params });
export const getOrientationAssignment = (employeeCode, params) =>
  api.get(`/hrms/orientation/assignments/${employeeCode}`, { params });
export const scheduleOrientationItem = (employeeCode, payload, params) =>
  api.post(`/hrms/orientation/assignments/${employeeCode}/schedule`, payload, { params });
export const completeOrientationItem = (employeeCode, payload, params) =>
  api.post(`/hrms/orientation/assignments/${employeeCode}/complete`, payload, { params });
export const waiveOrientationItem = (employeeCode, payload, params) =>
  api.post(`/hrms/orientation/assignments/${employeeCode}/waive`, payload, { params });

// ── Phase PULSE-1 — 30/90-Day Pulse Survey (§22.4, screen SM-HR-058) ──
// Identifiable by design (see the backend Cap.PULSE_READ comment for why this is NOT the
// same capability as the existing anonymous survey module). One board, scoped by role.
export const getPulseConfig = (params) => api.get('/hrms/pulse-surveys/config', { params });
export const savePulseConfig = (questions, params) =>
  api.put('/hrms/pulse-surveys/config', { questions }, { params });
export const getPulseSummary = (params) => api.get('/hrms/pulse-surveys/summary', { params });
export const listPulseSurveys = (params) => api.get('/hrms/pulse-surveys', { params });
export const getPulseSurvey = (employeeCode, milestone, params) =>
  api.get(`/hrms/pulse-surveys/${employeeCode}/${milestone}`, { params });
export const submitPulseSurvey = (employeeCode, milestone, payload, params) =>
  api.post(`/hrms/pulse-surveys/${employeeCode}/${milestone}/submit`, payload, { params });

// ── Phase LETTER-1 — HR Letter / Document Generator (SM-HR-041) ──
// Preview renders nothing to storage. Generate produces a Draft (pass `letter_no` back in
// to regenerate that SAME draft in place). Issue locks it — from there only Reissue can
// change anything, which supersedes the old letter and creates a new Issued one.
export const getLetterTemplates = (params) => api.get('/hrms/letters/templates', { params });
export const saveLetterTemplate = (key, payload, params) =>
  api.put(`/hrms/letters/templates/${key}`, payload, { params });
export const previewLetter = (payload, params) => api.post('/hrms/letters/preview', payload, { params });
export const generateLetter = (payload, params) => api.post('/hrms/letters', payload, { params });
export const listLetters = (params) => api.get('/hrms/letters', { params });
export const getLetter = (letterNo, params) => api.get(`/hrms/letters/${letterNo}`, { params });
export const issueLetter = (letterNo, params) => api.post(`/hrms/letters/${letterNo}/issue`, null, { params });
export const reissueLetter = (letterNo, payload, params) =>
  api.post(`/hrms/letters/${letterNo}/reissue`, payload, { params });

// ── Client Hiring (PRO-fit track) ──────────────────────────────────────────
// A separate track from Internal Hiring: its own endpoints, its own capabilities, and a
// client company's user reaches these and nothing else in HRMS.
export const getClientRequisitions = (params) =>
  api.get('/hrms/client-requisitions', { params });
export const getClientRequisition = (crNo, params) =>
  api.get(`/hrms/client-requisitions/${crNo}`, { params });
export const createClientRequisition = (payload, params) =>
  api.post('/hrms/client-requisitions', payload, { params });
export const updateClientRequisition = (crNo, payload, params) =>
  api.patch(`/hrms/client-requisitions/${crNo}`, payload, { params });
export const actOnClientRequisition = (crNo, payload, params) =>
  api.post(`/hrms/client-requisitions/${crNo}/action`, payload, { params });

export const getClientScorecards = (params) => api.get('/hrms/client-scorecards', { params });
export const getClientScorecard = (pscNo, params) =>
  api.get(`/hrms/client-scorecards/${pscNo}`, { params });
export const createClientScorecard = (payload, params) =>
  api.post('/hrms/client-scorecards', payload, { params });
export const updateClientScorecard = (pscNo, payload, params) =>
  api.patch(`/hrms/client-scorecards/${pscNo}`, payload, { params });
export const actOnClientScorecard = (pscNo, payload, params) =>
  api.post(`/hrms/client-scorecards/${pscNo}/action`, payload, { params });

export const getClientCandidates = (params) => api.get('/hrms/client-candidates', { params });
export const getClientCandidate = (ccnNo, params) =>
  api.get(`/hrms/client-candidates/${ccnNo}`, { params });
export const createClientCandidate = (payload, params) =>
  api.post('/hrms/client-candidates', payload, { params });
export const updateClientCandidate = (ccnNo, payload, params) =>
  api.patch(`/hrms/client-candidates/${ccnNo}`, payload, { params });
export const actOnClientCandidate = (ccnNo, payload, params) =>
  api.post(`/hrms/client-candidates/${ccnNo}/action`, payload, { params });

export const getClientAssessments = (params) => api.get('/hrms/client-assessments', { params });
export const createClientAssessment = (payload, params) =>
  api.post('/hrms/client-assessments', payload, { params });
export const updateClientAssessment = (casNo, payload, params) =>
  api.patch(`/hrms/client-assessments/${casNo}`, payload, { params });
export const actOnClientAssessment = (casNo, payload, params) =>
  api.post(`/hrms/client-assessments/${casNo}/action`, payload, { params });

export const getClientInterviews = (params) => api.get('/hrms/client-interviews', { params });
export const createClientInterview = (payload, params) =>
  api.post('/hrms/client-interviews', payload, { params });
export const updateClientInterview = (cinNo, payload, params) =>
  api.patch(`/hrms/client-interviews/${cinNo}`, payload, { params });
export const actOnClientInterview = (cinNo, payload, params) =>
  api.post(`/hrms/client-interviews/${cinNo}/action`, payload, { params });

export const getClientOffers = (params) => api.get('/hrms/client-offers', { params });
export const getClientOfferCheckpoint = (cofNo, params) =>
  api.get(`/hrms/client-offers/${cofNo}/checkpoint`, { params });
export const createClientOffer = (payload, params) =>
  api.post('/hrms/client-offers', payload, { params });
export const updateClientOffer = (cofNo, payload, params) =>
  api.patch(`/hrms/client-offers/${cofNo}`, payload, { params });
export const actOnClientOffer = (cofNo, payload, params) =>
  api.post(`/hrms/client-offers/${cofNo}/action`, payload, { params });
export const getClientReferenceChecks = (params) =>
  api.get('/hrms/client-reference-checks', { params });
export const recordClientReferenceCheck = (payload, params) =>
  api.post('/hrms/client-reference-checks', payload, { params });

export const getClientJoinings = (params) => api.get('/hrms/client-joinings', { params });
export const openClientJoining = (payload, params) =>
  api.post('/hrms/client-joinings', payload, { params });
export const recordClientTouchpoint = (cjnNo, payload, params) =>
  api.post(`/hrms/client-joinings/${cjnNo}/touchpoints`, payload, { params });
export const updateClientJoining = (cjnNo, payload, params) =>
  api.patch(`/hrms/client-joinings/${cjnNo}`, payload, { params });
export const actOnClientJoining = (cjnNo, payload, params) =>
  api.post(`/hrms/client-joinings/${cjnNo}/action`, payload, { params });
export const getClientAnalytics = (params) =>
  api.get('/hrms/client-analytics', { params });
export const getClientCompanies = (params) =>
  api.get('/hrms/client-companies', { params });

// ── Client Hiring, step 2b — the job posting and its applications ──
export const getClientPostings = (params) =>
  api.get('/hrms/client-postings', { params });
export const getClientPosting = (postingNo, params) =>
  api.get(`/hrms/client-postings/${postingNo}`, { params });
export const createClientPosting = (payload, params) =>
  api.post('/hrms/client-postings', payload, { params });
export const updateClientPosting = (postingNo, payload, params) =>
  api.patch(`/hrms/client-postings/${postingNo}`, payload, { params });
export const actOnClientPosting = (postingNo, payload, params) =>
  api.post(`/hrms/client-postings/${postingNo}/action`, payload, { params });
export const getClientApplications = (params) =>
  api.get('/hrms/client-applications', { params });

// ── The available candidate pool ──
// Sparsh-only and deliberately unscoped: it spans every engagement, which is why the
// server refuses a client-side caller outright rather than filtering them down.
export const getClientCandidatePool = (params) =>
  api.get('/hrms/client-candidate-pool', { params });
export const sourceFromClientPool = (payload, params) =>
  api.post('/hrms/client-candidate-pool/source', payload, { params });

// ── Status history, read from the audit trail ──
export const getClientHistory = (entity, recordNo, params) =>
  api.get(`/hrms/client-history/${entity}/${recordNo}`, { params });
