import api from './api';

// Client-side CSV download (used for company-scoped exports that the server export
// endpoint doesn't cover). rows = array of arrays; headers = array of strings.
export const downloadCsv = (filename, headers, rows) => {
  const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const csv = [headers, ...rows].map((r) => r.map(esc).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// Admin Reports & Analytics API (superadmin only on the backend).
// Thin wrappers over the shared axios instance so JWT + error handling are reused.

export const getEnterpriseOverview = (params) =>
  api.get('/reports/enterprise-overview', { params }).then((r) => r.data);

export const getReportsOverview = (params) =>
  api.get('/reports/overview', { params }).then((r) => r.data);

export const getCompanyReport = (params) =>
  api.get('/reports/company', { params }).then((r) => r.data);

export const getDepartmentsReport = (params) =>
  api.get('/reports/departments', { params }).then((r) => r.data);

export const getDoers = (params) =>
  api.get('/reports/doers', { params }).then((r) => r.data);

// Comprehensive employee/learner report (includes users with zero tasks).
export const getEmployeesWide = (params) =>
  api.get('/reports/employees-wide', { params }).then((r) => r.data);

// Streams the Company-wise report as CSV / XLSX / PDF and triggers a download.
export const exportCompanies = async ({ format = 'csv', ...params }) => {
  const res = await api.get('/reports/companies/export', {
    params: { format, ...params },
    responseType: 'blob',
  });
  const blob = new Blob([res.data]);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `company_report.${format}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// Streams one company's employees as CSV / XLSX / PDF and triggers a download.
export const exportCompanyEmployees = async (companyId, { format = 'csv', ...params }) => {
  const res = await api.get(`/reports/companies/${companyId}/employees/export`, {
    params: { format, ...params },
    responseType: 'blob',
  });
  const blob = new Blob([res.data]);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `employee_report.${format}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// Streams the comprehensive employee report as CSV / XLSX / PDF and triggers a download.
export const exportEmployeesWide = async ({ format = 'csv', ...params }) => {
  const res = await api.get('/reports/employees-wide/export', {
    params: { format, ...params },
    responseType: 'blob',
  });
  const blob = new Blob([res.data]);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `employee_report.${format}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// Activity report (login/usage from activity_logs).
export const getActivityReport = (params) =>
  api.get('/reports/activity', { params }).then((r) => r.data);

// Session report (LMS sessions + attendance + duration).
export const getSessionReport = (params) =>
  api.get('/reports/sessions', { params }).then((r) => r.data);

// E2 — Companies
export const getCompanies = (params) =>
  api.get('/reports/companies', { params }).then((r) => r.data);

export const getCompanyDashboard = (companyId, params) =>
  api.get(`/reports/companies/${companyId}`, { params }).then((r) => r.data);

export const getCompanyEmployees = (companyId, params) =>
  api.get(`/reports/companies/${companyId}/employees`, { params }).then((r) => r.data);

// LMS (= Batch)
export const getLmsList = (params) =>
  api.get('/reports/lms', { params }).then((r) => r.data);

export const getLmsDashboard = (batchId, params) =>
  api.get(`/reports/lms/${batchId}`, { params }).then((r) => r.data);

export const getLmsEmployees = (batchId, params) =>
  api.get(`/reports/lms/${batchId}/employees`, { params }).then((r) => r.data);

// E3 — Employee
export const getEmployeeReport = (userId, params) =>
  api.get(`/reports/employees/${userId}`, { params }).then((r) => r.data);

export const getEmployeeAssignments = (userId, params) =>
  api.get(`/reports/employees/${userId}/assignments`, { params }).then((r) => r.data);

export const getEmployeeAssessments = (userId) =>
  api.get(`/reports/employees/${userId}/assessments`).then((r) => r.data);

export const getEmployeeAttendance = (userId) =>
  api.get(`/reports/employees/${userId}/attendance`).then((r) => r.data);

export const getEmployeeTimeline = (userId, taskId) =>
  api.get(`/reports/employees/${userId}/timeline`, { params: { task_id: taskId } }).then((r) => r.data);

// Export a single employee's report (CSV / XLSX / PDF) — triggers a browser download.
export const exportEmployeeReport = async (userId, { format = 'csv', ...params } = {}) => {
  const res = await api.get(`/reports/employees/${userId}/export`, {
    params: { format, ...params },
    responseType: 'blob',
  });
  const blob = new Blob([res.data]);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `employee_report.${format}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

export const getDoerDetail = (doerId, params) =>
  api.get(`/reports/doers/${doerId}`, { params }).then((r) => r.data);

export const getDoerHistory = (doerId, params) =>
  api.get(`/reports/doers/${doerId}/history`, { params }).then((r) => r.data);

export const getDoerTimeline = (doerId, taskId) =>
  api.get(`/reports/doers/${doerId}/timeline`, { params: { task_id: taskId } }).then((r) => r.data);

// Streams a CSV / XLSX / PDF file and triggers a browser download.
export const exportReport = async ({ format = 'csv', ...params }) => {
  const res = await api.get('/reports/export', {
    params: { format, ...params },
    responseType: 'blob',
  });
  const ext = format;
  const blob = new Blob([res.data]);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `employee_performance.${ext}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};
