import api from './api';

/**
 * Task Management ▸ Templates API.
 *
 * Two backends, deliberately separate:
 *
 *  · /notify-templates  — the WIRING. Which template fires for which trigger, on which
 *    channel, and which data field fills each WhatsApp parameter. Stored in the same
 *    `notification_templates` collection Settings ▸ Notifications has always used, so a
 *    template configured here is the one that actually sends.
 *
 *  · /meta-templates    — the LIBRARY. Template definitions that live on the WhatsApp
 *    Business Account. The same endpoints TPMS ▸ Templates uses (it mounts them under
 *    /tpms/meta-templates), because both modules send through one WABA and therefore share
 *    one library.
 *
 * House style — thin wrappers over the shared axios instance, no react-query.
 */

// ── Catalogue: modules, their triggers, mappable placeholders, Meta connection health ──
export const getNotifyModules = () => api.get('/notify-templates/modules');

// ── Wiring ──
export const getNotifyTemplates = (params) => api.get('/notify-templates', { params });
export const upsertNotifyTemplate = (payload) => api.post('/notify-templates', payload);
export const setNotifyTemplateStatus = (id, isActive) =>
  api.patch(`/notify-templates/${id}/status`, { is_active: isActive });
export const deleteNotifyTemplate = (id) => api.delete(`/notify-templates/${id}`);
/** Send one configured trigger to a phone using its real wiring — proves the field mapping. */
export const testNotifyTemplate = (payload) => api.post('/notify-templates/test', payload);

// ── Reminder schedule ──
// When the time-driven reminders (daily/weekly due, overdue, verification chase) go out.
// Click-driven triggers send instantly and are not affected by this.
export const getReminderSchedule = () => api.get('/notify-templates/schedule');
export const setReminderSchedule = (hour, minute = 0) =>
  api.put('/notify-templates/schedule', { hour, minute });
/** Run today's sweep now instead of waiting. Idempotent — a cadence that already fired today
 *  will not fire again. */
export const runReminderSweepNow = () => api.post('/notify-templates/schedule/run-now');

// ── Meta template library (shared with TPMS) ──
export const getMetaTemplates = (status) =>
  api.get('/meta-templates', { params: { status: status || undefined } });
export const getApprovedMetaTemplates = () => api.get('/meta-templates/approved');
export const saveMetaTemplate = (payload) => api.post('/meta-templates', payload);
export const checkMetaTemplate = (payload) => api.post('/meta-templates/check', payload);
export const submitMetaTemplate = (id) => api.post(`/meta-templates/${id}/submit`);
export const syncMetaTemplates = () => api.post('/meta-templates/sync');
export const deleteMetaTemplate = (id) => api.delete(`/meta-templates/${id}`);
/** Test the DEFINITION (does this template render?) — the wiring test is testNotifyTemplate. */
export const testMetaTemplate = (payload) => api.post('/meta-templates/test', payload);

// Companies for the scope selector (reuses the existing endpoint).
export const getCompanies = () => api.get('/companies');
