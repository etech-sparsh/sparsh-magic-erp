import api from './api';

// Tasks are calendar_event docs with type:"task" (see backend/app/routes/tasks.py).
// Create/update of the core event fields still goes through /calendar/events so the
// existing recurrence, delegation, conflict-check and notification logic keeps working.

export const getTasks = (params) => api.get('/tasks', { params });
export const getTaskDashboard = (params) => api.get('/tasks/dashboard', { params });
export const getTaskActivity = (params) => api.get('/tasks/activity', { params });
export const getTaskDetail = (taskId) => api.get(`/tasks/${taskId}`);
// `doerName`/`doerId` are required (with `reason`) for Dependent on Other / Blocked; ignored
// otherwise. For Dependent on Other, a `doerId` reassigns the task to that doer (backend rule).
export const updateTaskStatus = (taskId, workflow_status, reason, doerName, doerId) =>
  api.patch(`/tasks/${taskId}/status`, { workflow_status, reason, doer_name: doerName, doer_id: doerId });
// Deadline / Date Revision. The assigner/delegator, an admin or the assignee's reporting
// manager revises the deadline outright. An ASSIGNEE's call raises a revision REQUEST instead
// (the response carries status:'pending_approval' + deadline_request) — the deadline does not
// move until the assigner approves it below. All backend-enforced.
// `context` is 'reopen' when the new deadline is part of sending a task back for rework —
// those don't count against the two-revision limit (backend: MAX_DEADLINE_REVISIONS).
export const reviseTaskDeadline = (taskId, end, reason, context) =>
  api.patch(`/tasks/${taskId}/deadline`, { end, reason, context });
// The assigner's verdict on a pending request. Approving is what actually moves the deadline;
// rejecting leaves the original one standing. `remark` is optional on both.
export const approveDeadlineRequest = (taskId, requestId, remark) =>
  api.post(`/tasks/${taskId}/deadline-requests/${requestId}/approve`, { remark });
export const rejectDeadlineRequest = (taskId, requestId, remark) =>
  api.post(`/tasks/${taskId}/deadline-requests/${requestId}/reject`, { remark });
export const softDeleteTask = (taskId) => api.delete(`/tasks/${taskId}`);
export const restoreTask = (taskId) => api.post(`/tasks/${taskId}/restore`);

export const createTask = (payload) => api.post('/calendar/events', { ...payload, type: 'task' });
export const updateTask = (taskId, updates) => api.patch(`/calendar/events/${taskId}`, updates);

export const addChecklistItem = (taskId, title) => api.post(`/tasks/${taskId}/checklist`, { title });
export const updateChecklistItem = (taskId, itemId, updates) => api.patch(`/tasks/${taskId}/checklist/${itemId}`, updates);
export const deleteChecklistItem = (taskId, itemId) => api.delete(`/tasks/${taskId}/checklist/${itemId}`);

export const addTaskComment = (taskId, text) => api.post(`/tasks/${taskId}/comments`, { text });

// Follow-Up raised by an In-Loop member (watcher) / participant — a nudge with a remark.
// The follow-up count is len(followUps) on the task detail payload.
export const addTaskFollowUp = (taskId, remark) => api.post(`/tasks/${taskId}/follow-up`, { remark });

export const uploadTaskAttachment = (taskId, file) => {
  const form = new FormData();
  form.append('file', file);
  return api.post(`/tasks/${taskId}/attachments`, form);
};

export const deleteTaskAttachment = (taskId, attachmentId) => api.delete(`/tasks/${taskId}/attachments/${attachmentId}`);

// Completion Evidence — uploaded while completing the task, stored separately from the
// assignment-time attachments above (see backend/app/routes/tasks.py).
export const uploadCompletionAttachment = (taskId, file) => {
  const form = new FormData();
  form.append('file', file);
  return api.post(`/tasks/${taskId}/completion-attachments`, form);
};

export const deleteCompletionAttachment = (taskId, attachmentId) => api.delete(`/tasks/${taskId}/completion-attachments/${attachmentId}`);

// Task & Delegation notification delivery log (email / WhatsApp). Admin only — the ledger
// spans every recipient in the organisation. Mirrors the TPMS Logs Report endpoint.
export const getTaskLogs = (params) => api.get('/tasks/logs', { params });
