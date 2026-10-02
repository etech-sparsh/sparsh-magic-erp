import api from './api';

/**
 * TPMS ▸ core API.
 * Thin wrappers over the shared axios instance (house style — no react-query).
 * Backend routes live under /api/tpms (see backend/app/routes/tpms.py).
 *
 * The forms sub-module has its own client in tpmsFormsApi.js — keep them separate,
 * they map to two different routers.
 */

// ── Master data ──
export const getActivities = (includeInactive = false) =>
  api.get('/tpms/activities', { params: { include_inactive: includeInactive || undefined } });
// H4 — activity catalogue CRUD (Admin). Delete = soft-deactivate via updateActivity({active:false}).
export const createActivity = (payload) => api.post('/tpms/activities', payload);
export const updateActivity = (id, payload) => api.patch(`/tpms/activities/${id}`, payload);

export const getDepartments = (companyId) =>
  api.get('/tpms/departments', { params: { company_id: companyId || undefined } });
// Master lists for the Client-wise Calendar filters (companies, HODs, OMs) — dynamic.
export const getCalendarFilters = () => api.get('/tpms/calendar-filters');
// H5 — department master CRUD (Admin). Governance roles are seeded and cannot be edited.
export const createDepartment = (payload) => api.post('/tpms/departments', payload);
export const updateDepartment = (id, payload) => api.patch(`/tpms/departments/${id}`, payload);

export const getReminderRules = (activity) =>
  api.get('/tpms/reminder-rules', { params: { activity: activity || undefined } });
// M12 — reminder-rule + mail-template CRUD (Admin).
export const createReminderRule = (payload) => api.post('/tpms/reminder-rules', payload);
export const updateReminderRule = (id, payload) => api.patch(`/tpms/reminder-rules/${id}`, payload);
export const getMailTemplates = (activity) =>
  api.get('/tpms/mail-templates', { params: { activity: activity || undefined } });
export const upsertMailTemplate = (payload) => api.post('/tpms/mail-templates', payload);
export const getWhatsappTemplates = (activity) =>
  api.get('/tpms/whatsapp-templates', { params: { activity: activity || undefined } });
export const upsertWhatsappTemplate = (payload) => api.post('/tpms/whatsapp-templates', payload);
// The data fields a WhatsApp template's positional params can map to.
export const getWhatsappVariables = () => api.get('/tpms/whatsapp-variables');

/* ── WhatsApp template library (Meta approval workflow) ──
   Templates authored in TPMS and submitted to Meta for review. These are the definitions that
   live on the WhatsApp Business Account; the whatsapp-templates endpoints above are the
   notification wiring that points at an APPROVED one. */
export const getMetaTemplates = (status) =>
  api.get('/tpms/meta-templates', { params: { status: status || undefined } });
// Only APPROVED rows, each with the parameter slots it declares — what a notification may use.
export const getApprovedMetaTemplates = () => api.get('/tpms/meta-templates/approved');
// Create or update a draft. Pass `_id` to update; editing is refused once Meta owns it.
export const saveMetaTemplate = (payload) => api.post('/tpms/meta-templates', payload);
// Validate and return the exact Graph payload — the "Check payload" step, no Graph call made.
export const checkMetaTemplate = (payload) => api.post('/tpms/meta-templates/check', payload);
// Irreversible: sends the template to Meta for review.
export const submitMetaTemplate = (id) => api.post(`/tpms/meta-templates/${id}/submit`);
// Pull current approval statuses (and rejection reasons) from Meta.
export const syncMetaTemplates = () => api.post('/tpms/meta-templates/sync');
export const deleteMetaTemplate = (id) => api.delete(`/tpms/meta-templates/${id}`);
/** Send the template being composed to one number. Works before the template is saved — pass
 *  the form as `template`. An APPROVED template goes as the real thing; anything else is sent
 *  as free-form text, which only lands inside Meta's 24-hour window. */
export const testMetaTemplate = (payload) => api.post('/tpms/meta-templates/test', payload);
// Smoke-test send of one WhatsApp template to a phone number.
export const testWhatsappTemplate = (payload) => api.post('/tpms/whatsapp-templates/test', payload);
/** Activate / deactivate one template. `channel` is 'mail' or 'whatsapp'. Admin only —
 *  writes just the flag, never the subject/body, so content cannot change by toggling. */
export const setTemplateStatus = (channel, id, active) =>
  api.patch(`/tpms/${channel}-templates/${id}/status`, { active });
// H10 — per-reminder send ledger (Admin).
export const getReminderLogs = (params) => api.get('/tpms/reminder-logs', { params });
// M10 — review-form question master (Admin): reword question/criterion text.
export const getFormQuestions = (formType) =>
  api.get('/forms/questions', { params: { form_type: formType || undefined } });
export const createFormQuestion = (payload) => api.post('/forms/questions', payload);
export const updateFormQuestion = (id, payload) => api.patch(`/forms/questions/${id}`, payload);

// ── Scheduling ──
// Month feed for the calendar grid. `month` is 1-12.
export const getSchedules = (params) => api.get('/tpms/schedules', { params });

// Once-per-month duplicate warning. Returns {conflict, scope, period, existing[]}.
// Advisory only — the UI may proceed anyway.
export const checkScheduleConflict = (payload) =>
  api.post('/tpms/schedules/check-conflict', payload);

export const createSchedule = (payload) => api.post('/tpms/schedules', payload);
export const updateSchedule = (id, payload) => api.patch(`/tpms/schedules/${id}`, payload);
export const deleteSchedule = (id) => api.delete(`/tpms/schedules/${id}`);

// ── Lifecycle: two-step completion ──
// The doer claims it…
export const markLearnerDone = (id) => api.post(`/tpms/schedules/${id}/learner-done`);
// …and internal staff confirm. Only this sets status Completed.
export const confirmCompletion = (id) => api.post(`/tpms/schedules/${id}/confirm`);

// ── Lifecycle: reschedule workflow ──
export const requestReschedule = (id, payload) =>
  api.post(`/tpms/schedules/${id}/reschedule-request`, payload);
export const getRescheduleRequests = (status = 'Pending') =>
  api.get('/tpms/reschedule-requests', { params: { status } });
export const decideRescheduleRequest = (requestId, approve, note = '') =>
  api.post(`/tpms/reschedule-requests/${requestId}/decide`, { approve, note });

// ── Proof-of-work uploads ──
export const getScheduleUploads = (id) => api.get(`/tpms/schedules/${id}/uploads`);
export const uploadScheduleFile = (id, file) => {
  const form = new FormData();
  form.append('file', file);
  return api.post(`/tpms/schedules/${id}/uploads`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};
export const getCompanyUploads = (params) => api.get('/tpms/uploads', { params });

// ── Success measures ──
export const getSuccessMeasures = (params) => api.get('/tpms/success-measures', { params });
export const saveManualScore = (payload) => api.post('/tpms/manual-scores', payload);
export const syncSuccessMeasures = (period) =>
  api.post('/tpms/success-measures/sync', null, { params: { period: period || undefined } });

// ── Dashboards ──
export const getAnalyticsDashboard = (params) => api.get('/tpms/dashboards/analytics', { params });
export const getStaffDashboard = (params) => api.get('/tpms/dashboards/staff', { params });
export const getClientDashboard = (params) => api.get('/tpms/dashboards/client', { params });
export const getHodDashboard = (params) => api.get('/tpms/dashboards/hod', { params });
export const getEmployeeActivityDashboard = (params) =>
  api.get('/tpms/dashboards/employee-activity', { params });
export const getImplementationTracker = (params) =>
  api.get('/tpms/dashboards/implementation', { params });
export const getEscalationDashboard = (params) =>
  api.get('/tpms/dashboards/escalations', { params });

// ── Reports ──
export const getLogsReport = (params) => api.get('/tpms/reports/logs', { params });
export const getReviewReports = (params) => api.get('/tpms/reports/reviews', { params });

// ── Bulk export / import (admin only) ──
// The workbook is one sheet per TPMS collection, led by a fillable `Schedules` sheet. Add rows
// there leaving "Schedule ID" blank, re-import, and each becomes a real scheduled activity.
// `responseType: 'blob'` matters — without it axios parses the .xlsx bytes as text and the
// saved file is corrupt.
export const exportTpms = () => api.get('/tpms/export', { responseType: 'blob' });

// One client's complete TPMS record as an Excel / Google Sheets workbook — Summary KPIs for
// the selected period, then a sheet per dataset carrying that client's full history.
export const exportClientReport = (params) =>
  api.get('/tpms/export/client', { params, responseType: 'blob' });

export const importTpms = (file) => {
  const form = new FormData();
  form.append('file', file);
  return api.post('/tpms/import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};

// Save an exported blob to disk, preferring the filename the backend set in
// Content-Disposition so the timestamp it stamped is what the user sees.
export const saveExportedWorkbook = (response, fallback = 'tpms-export.xlsx') => {
  const disposition = response.headers?.['content-disposition'] || '';
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  const url = URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.download = match ? decodeURIComponent(match[1]) : fallback;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

/** Current month as the canonical 'YYYY-MM' the backend expects. */
export const currentPeriod = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};

/** 'YYYY-MM' → 'July26', matching the label format the sheets used. */
export const periodLabel = (p) => {
  if (!p || p.length < 7) return '';
  const months = ['January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'];
  return `${months[Number(p.slice(5, 7)) - 1]}${p.slice(2, 4)}`;
};
