/**
 * HRMS ▸ Internal Recruitment SOP ▸ status-label reconciliation.
 *
 * The SOP document (and the manual test script drawn from it) describes the flow in plain,
 * simplified language — "Under Approval", "Screening Pending", "Joining Pending" — while the
 * system's own status values are more granular ("Pending Scorecard Approval", "Under
 * Review", "Pre-Onboarding"). Both are correct; they are simply different vocabularies for
 * the same state machine. Renaming the system's actual status strings to match the SOP's
 * wording would touch every backend service, route, test and stored document that reads or
 * writes them — a wide, risky change for what is a labelling difference, not a logic one.
 *
 * This module is the reconciliation instead: a lookup from the system's REAL status value to
 * the SOP's own step number and phrasing, so a screen can show both — "Pending Scorecard
 * Approval (SOP: Under Approval)" — and a tester reading the SOP alongside the running app
 * is never left wondering whether a status they don't recognise is a bug or just a synonym.
 */

/** Internal-track requisition status (ReqApproval, backend/app/models/hrms.py) -> SOP wording. */
export const REQUISITION_SOP_LABEL = {
  'Pending HR Verification':   { step: 2, sop: 'Submitted' },
  'Pending Budget Approval':   { step: 3, sop: 'Under Approval (Budget)' },
  'Pending Escalation':        { step: 3, sop: 'Under Approval (Escalated)' },
  'Pending Scorecard Approval': { step: 4, sop: 'Under Approval (Scorecard)' },
  Approved:                    { step: 4, sop: 'Approved' },
  Rejected:                    { step: 3, sop: 'Rejected / Closed' },
};

/** Candidate application_status (AppStatus, backend/app/models/hrms.py) -> SOP wording. */
export const CANDIDATE_SOP_LABEL = {
  Applied:                     { step: 6, sop: 'Sourced' },
  'Under Review':              { step: 7, sop: 'Screening Pending' },
  Shortlisted:                 { step: 7, sop: 'Shortlisted' },
  'Telephonic Passed':         { step: 8, sop: 'Selected for Assessment/Interview' },
  'Telephonic Rejected':       { step: 8, sop: 'Rejected' },
  'Assessment Pending':        { step: 9, sop: 'Assessment In Progress' },
  'Assessment Completed':      { step: 9, sop: 'Assessment In Progress' },
  'Assessment Passed':         { step: 9, sop: 'Selected for Interview' },
  'Assessment Failed':         { step: 9, sop: 'Rejected' },
  'Interview Scheduled':       { step: 10, sop: 'Panel Interview' },
  'Technical Round':           { step: 10, sop: 'Panel Interview' },
  'MD Round':                  { step: 12, sop: 'Management Final Interview' },
  Selected:                    { step: 11, sop: 'Final Candidate Selected' },
  'Offer Generated':           { step: 15, sop: 'Offer Approved' },
  'Offer Accepted':            { step: 16, sop: 'Offer Accepted' },
  'Offer Declined':            { step: 16, sop: 'Offer Declined' },
  'Appointment Letter Sent':   { step: 16, sop: 'Offer Released' },
  'Pre-Onboarding':            { step: 17, sop: 'Joining Pending' },
  Joined:                      { step: 18, sop: 'Joined' },
  'Employee Created':          { step: 19, sop: 'Day-1 Induction Complete' },
  'Probation Confirmed':       { step: 21, sop: 'Confirmed' },
  'On Hold':                   { step: null, sop: 'On Hold' },
  Rejected:                    { step: null, sop: 'Rejected' },
  Duplicate:                   { step: null, sop: 'Duplicate' },
};

/**
 * The SOP phrasing for a system status, or null when the status carries no SOP-side synonym
 * worth showing (e.g. it already reads the same in both, or it is a client-track-only value
 * this SOP does not cover).
 */
export function sopLabelFor(status, table) {
  const hit = table[status];
  return hit ? hit.sop : null;
}
