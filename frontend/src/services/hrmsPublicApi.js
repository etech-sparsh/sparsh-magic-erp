import axios from 'axios';

/**
 * HRMS ▸ PUBLIC API client (no authentication).
 *
 * Deliberately does NOT use services/api.js. That instance attaches the bearer token from
 * localStorage and dispatches a global `app-error` event on 403 — both wrong here:
 *
 *  • A candidate has no token. Worse, if an HR user happens to be logged in on the same
 *    browser, the shared instance would silently attach THEIR credentials to a public
 *    request, which is exactly the kind of accidental privilege leak this surface must not
 *    have.
 *  • The public pages render their own errors inline; a global toast from the authenticated
 *    app would be meaningless to an applicant.
 *
 * A bare axios instance keeps the public surface genuinely anonymous.
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

const publicApi = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
});

/** The job ad behind a shared application link. */
export const getPublicJob = (code) => publicApi.get(`/hrms/public/apply/${code}`);

/** Submit an application. Files are sent as base64 in the JSON body — the public form has
 *  no token, and this keeps one ingest shape for every candidate-facing upload. */
export const submitApplication = (code, payload) =>
  publicApi.post(`/hrms/public/apply/${code}`, payload);

/** Read a File into the {name, mime_type, data} shape the API expects. */
export const readFileAsUpload = (file) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({
      name: file.name,
      mime_type: file.type || 'application/octet-stream',
      // strip the "data:...;base64," prefix — the server accepts either, but sending the
      // bare payload keeps the request smaller.
      data: String(reader.result).split(',')[1] || '',
    });
    reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
    reader.readAsDataURL(file);
  });

export default publicApi;

// ── Assessment (public) ──
/** The assessment behind a candidate's link. Viewing marks it Opened. */
export const getPublicAssessment = (code) => publicApi.get(`/hrms/public/assess/${code}`);

/** Submit an assessment — a written response, attachments, or both. */
export const submitAssessment = (code, payload) =>
  publicApi.post(`/hrms/public/assess/${code}`, payload);

// ── Offer (public) ──
/** The offer letter behind a candidate's link. A Draft is invisible here. */
export const getPublicOffer = (code) => publicApi.get(`/hrms/public/offer/${code}`);

/** Accept or decline. Accepting requires a typed signature; declining does not. */
export const respondToOffer = (code, payload) =>
  publicApi.post(`/hrms/public/offer/${code}`, payload);

// ── Pre-onboarding (public) ──
/** The joining form behind a new hire's link. */
export const getPublicOnboarding = (code) => publicApi.get(`/hrms/public/onboard/${code}`);

/** Submit joining details and KYC documents. Once only — a resubmit is a 409. */
export const submitOnboarding = (code, payload) =>
  publicApi.post(`/hrms/public/onboard/${code}`, payload);

// ── Appointment letter (public) — Phase 11-R, Item 3 ──
/** The appointment letter behind a candidate's link. A Generated (unsent) letter is
 *  invisible here and answers with the same opaque 404 as an unknown code. Viewing moves a
 *  Sent letter to Pending Acknowledgement. */
export const getPublicAppointment = (code) =>
  publicApi.get(`/hrms/public/appointment/${code}`);

/** Acknowledge the letter. A typed signature is REQUIRED — there is no "decline" here,
 *  because declining happens at the offer, one step earlier. */
export const acknowledgeAppointment = (code, payload) =>
  publicApi.post(`/hrms/public/appointment/${code}`, payload);

// ── New-hire experience survey (public) — Phase INT-2, SOP §10 ──
/** The questionnaire behind a new joiner's link.
 *
 *  Returns the questions and NOTHING about the person — no employee code, no name, no
 *  requisition. The respondent already knows who they are, and a page that echoes their
 *  identity back is a page that can be screenshotted next to their answers. */
export const getPublicSurvey = (code) => publicApi.get(`/hrms/public/survey/${code}`);

/** Submit answers. Once submitted a response is FINAL: a live link that could rewrite an
 *  average after somebody had read it would make the figure meaningless. */
export const submitSurvey = (code, payload) =>
  publicApi.post(`/hrms/public/survey/${code}`, payload);
