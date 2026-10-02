import {
  Activity, RotateCcw, UserPlus, Pencil, RefreshCw, ListPlus,
  MessageSquare, Paperclip, Trash2, Repeat,
} from 'lucide-react';

// Maps the raw `action` strings written to activity_logs (see log_activity calls in
// backend tasks.py / calendar_events.py) to a friendly label, icon and accent colour.
// Shared by the full Activity page (TaskActivity.jsx) and the Group workspace's
// embedded Timeline tab (GroupTimelineTab.jsx) so both render activity identically.
export const ACTIVITY_META = {
  'Create Task': { label: 'Task assigned', icon: UserPlus, color: 'var(--accent-green)' },
  'Create Recurring Tasks': { label: 'Recurring tasks created', icon: Repeat, color: 'var(--accent-green)' },
  'Update Task': { label: 'Task updated', icon: Pencil, color: 'var(--accent-indigo)' },
  'Update Task Status': { label: 'Status changed', icon: RefreshCw, color: 'var(--accent-orange)' },
  'Add Sub Task': { label: 'Sub-task added', icon: ListPlus, color: 'var(--accent-indigo)' },
  'Comment on Task': { label: 'Comment added', icon: MessageSquare, color: 'var(--accent-indigo)' },
  'Attach File to Task': { label: 'Attachment added', icon: Paperclip, color: 'var(--accent-indigo)' },
  'Soft Delete Task': { label: 'Task deleted', icon: Trash2, color: 'var(--accent-red)' },
  'Restore Task': { label: 'Task restored', icon: RotateCcw, color: 'var(--accent-green)' },
};

export const metaFor = (action) => ACTIVITY_META[action] || { label: action || 'Activity', icon: Activity, color: 'var(--text-muted)' };

// "Update Task Status" details read like "Task <id> -> completed" — pull the target status
// out so it can render as a small status trail chip.
export const extractStatusChange = (details) => {
  if (!details) return null;
  const m = details.match(/->\s*([a-z_]+)/i);
  return m ? m[1].replace(/_/g, ' ') : null;
};

export const formatDateTime = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  // DD/MM/YYYY HH:mm — consistent with the rest of the Task/Delegation module.
  const pad2 = (n) => String(n).padStart(2, '0');
  return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}/${d.getFullYear()} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
};
