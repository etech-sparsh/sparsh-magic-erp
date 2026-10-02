export const getInitials = (name) => {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].charAt(0).toUpperCase();
  return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
};

export const formatRelativeTime = (dateStr) => {
  if (!dateStr) return '';
  const then = new Date(dateStr).getTime();
  if (Number.isNaN(then)) return '';
  const diffMs = Date.now() - then;
  const diffDays = Math.floor(Math.abs(diffMs) / 86400000);
  const suffix = diffMs >= 0 ? 'ago' : 'left';
  if (diffDays === 0) {
    const diffHours = Math.floor(Math.abs(diffMs) / 3600000);
    if (diffHours === 0) return 'just now';
    return `${diffHours}h ${suffix}`;
  }
  return `${diffDays}d ${suffix}`;
};

export const formatFrequencyLabel = (repeat) => {
  if (!repeat || repeat === 'Does not repeat') return 'One Time';
  return repeat;
};

// Shared date formatting for the whole Task/Delegation module — always DD/MM/YYYY (and
// DD/MM/YYYY HH:mm for timestamps), regardless of the browser's locale.
const pad2 = (n) => String(n).padStart(2, '0');

export const formatDate = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}/${d.getFullYear()}`;
};

export const formatDateTime = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return `${formatDate(d)} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
};

// Extension-based sniff so attachment lists can preview inline (audio player / image
// thumbnail) instead of just a filename link. No file-type library is installed anywhere
// in the project, so this is a plain, dependency-free check.
const AUDIO_EXT = /\.(webm|mp3|wav|m4a|ogg|aac)$/i;
const IMAGE_EXT = /\.(png|jpe?g|gif|webp|svg|bmp)$/i;
const PDF_EXT = /\.pdf$/i;

export const getAttachmentKind = (name = '') => {
  if (AUDIO_EXT.test(name)) return 'audio';
  if (IMAGE_EXT.test(name)) return 'image';
  if (PDF_EXT.test(name)) return 'pdf';
  return 'other';
};

// A "Daily/Weekly/..." task with a deadline is materialized on the backend as one document
// per occurrence (so each day can be tracked/completed independently), all sharing the same
// recurringGroupId. List views collapse those into a single row so a 6-day daily task reads
// as "one task", while still letting the individual occurrences be expanded and tracked.
export const groupTasksByRecurrence = (tasks) => {
  const order = [];
  const groups = new Map();
  tasks.forEach(t => {
    const key = t.recurringGroupId || t.id;
    if (!groups.has(key)) { groups.set(key, []); order.push(key); }
    groups.get(key).push(t);
  });
  return order.map(key => {
    const items = groups.get(key).sort((a, b) => new Date(a.start || 0) - new Date(b.start || 0));
    // Prefer the next occurrence that isn't finished yet; fall back to the earliest one.
    const primary = items.find(t => t.status !== 'completed') || items[0];
    return { key, primary, items };
  });
};

// No dedicated CSV/export library is installed anywhere in the project, so this uses
// the plain Blob + anchor-download browser API rather than pulling in a new dependency.
export const exportTasksToCsv = (tasks, userMap, filename = 'tasks.csv') => {
  const headers = ['Title', 'Category', 'Assigned To', 'Status', 'Frequency', 'Priority', 'Due Date'];
  const rows = tasks.map(t => [
    t.title || '',
    t.category || '',
    (t.assignedTo || []).map(id => userMap[id] || id).join('; ') || 'Myself',
    t.status || '',
    formatFrequencyLabel(t.frequency),
    t.priority || 'Normal',
    t.end || t.start || '',
  ]);
  const escape = (v) => `"${String(v).replace(/"/g, '""')}"`;
  const csv = [headers, ...rows].map(r => r.map(escape).join(',')).join('\n');
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

// A task is part of a recurring series when it was created with a repeat rule. The backend
// materializes one document per occurrence sharing a recurring_group_id, but a repeat rule
// with no deadline stays a single document — so either signal counts as recurring.
export const isRecurringTask = (t) => !!t.recurringGroupId
  || !!(t.frequency && t.frequency !== 'Does not repeat');

// "Every 2 Weekly" reads badly, so the interval is only spelled out when it isn't 1.
export const formatRecurrenceRule = (task) => {
  const base = formatFrequencyLabel(task?.frequency);
  const every = task?.repeatInterval || 1;
  return every > 1 ? `${base} · every ${every}` : base;
};

// Rolls a grouped series (see groupTasksByRecurrence) up into the numbers the Recurring tab
// shows on its detail line: how far along the series is, which occurrence is next, and when
// the whole series runs out.
export const summarizeSeries = (group) => {
  const items = group?.items || [];
  const total = items.length;
  const done = items.filter(t => t.status === 'completed').length;
  const overdue = items.filter(t => t.isOverdue).length;
  // The next occurrence still to be worked on — earliest unfinished deadline.
  const nextDue = items
    .filter(t => t.status !== 'completed' && t.end)
    .sort((a, b) => new Date(a.end) - new Date(b.end))[0]?.end || null;
  // An explicit repeat end date wins; otherwise the last occurrence's deadline stands in.
  const lastEnd = items.reduce((max, t) => {
    const v = t.end ? new Date(t.end).getTime() : 0;
    return v > max ? v : max;
  }, 0);
  const seriesEnd = group?.primary?.repeatEndDate || (lastEnd ? new Date(lastEnd).toISOString() : null);
  return { total, done, overdue, nextDue, seriesEnd, percent: total ? Math.round((done / total) * 100) : 0 };
};

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

// An occurrence's identity is the day it is FOR, so the expanded series list leads with the
// weekday — on a daily/weekly routine "Tue" is what the doer actually thinks in. The date part
// stays the module-wide DD/MM/YYYY (see formatDate).
export const formatOccurrenceDate = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return `${WEEKDAYS[d.getDay()]}, ${formatDate(d)}`;
};

// Is this person the MD of their organisation?
//
// `governance_role` ONLY. Not `role === 'clientadmin'`: that is an ACCOUNT PERMISSION, not a
// job — a company routinely gives it to several people (in one client it is held by the MD,
// two HODs and a recruiter). auth_controller.client_rank maps clientadmin to MD-LEVEL because
// it is answering "how much authority does this account have", which is the right rule for
// permission checks and the wrong one here. "Include MD" must loop in the MD, not everyone who
// can administer the company.
//
// Free-text `designation` is ignored for the same reason in reverse: "Director"/"Owner"/"CEO"
// are titles people type, not the controlled field the rest of the app governs by.
export const isMdUser = (u) => !!u
  && String(u.governance_role || '').trim().toUpperCase() === 'MD';
