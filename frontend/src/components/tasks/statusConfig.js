import {
  Clock, CheckCircle2, PlayCircle, Link2, Ban, Eye, CheckCircle, AlertTriangle, RotateCcw,
  AlertCircle, ArrowDown, ListChecks,
} from 'lucide-react';

// Central status → visual mapping for the Task Management module. Deliberately reuses
// ONLY the project's existing 5 accent tokens (green/orange/red/yellow/indigo, from
// index.css) instead of one-off hex values, so it stays visually consistent with the
// rest of the app. Green is reserved for "done" states to match the module's green
// sidebar branding.
export const STATUS_CONFIG = {
  pending: { label: 'Pending', shortLabel: 'Pending', icon: Clock, color: 'var(--text-muted)', bg: 'var(--input-bg)', border: 'var(--border)' },
  accepted: { label: 'Acknowledged Delegation', shortLabel: 'Acknowledged', icon: CheckCircle2, color: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', border: 'var(--accent-indigo-border)' },
  in_progress: { label: 'In Progress', shortLabel: 'In Progress', icon: PlayCircle, color: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', border: 'var(--accent-orange-border)' },
  dependent_on_others: { label: 'Dependent on Other', shortLabel: 'Dependent', icon: Link2, color: 'var(--accent-yellow)', bg: 'var(--accent-yellow-bg)', border: 'var(--accent-yellow-border)' },
  blocked: { label: 'Blocked', shortLabel: 'Blocked', icon: Ban, color: 'var(--accent-red)', bg: 'var(--accent-red-bg)', border: 'var(--accent-red-border)' },
  verification: { label: 'Pending Verification', shortLabel: 'Verification', icon: Eye, color: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', border: 'var(--accent-indigo-border)' },
  completed: { label: 'Completed', shortLabel: 'Completed', icon: CheckCircle, color: 'var(--accent-green)', bg: 'var(--accent-green-bg)', border: 'var(--accent-green-border)' },
  in_progress_reopened: { label: 'In Progress (Reopened)', shortLabel: 'Reopened', icon: RotateCcw, color: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', border: 'var(--accent-orange-border)' },
  // The dependency doer has finished; the task is back with the assignee who delegated it, for
  // review and final completion. Indigo (a hand-off, like Acknowledged / Pending Verification)
  // rather than green — nothing is done until the assignee completes it.
  dependency_completed: { label: 'Dependency Completed', shortLabel: 'Dependency Done', icon: Link2, color: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', border: 'var(--accent-indigo-border)' },
};

export const EXTRA_CARD_CONFIG = {
  totalTasks: { label: 'Total Tasks', shortLabel: 'Total', icon: ListChecks, color: 'var(--text-main)', bg: 'var(--input-bg)', border: 'var(--border)' },
  overdue: { label: 'Overdue', shortLabel: 'Overdue', icon: AlertTriangle, color: 'var(--accent-red)', bg: 'var(--accent-red-bg)', border: 'var(--accent-red-border)' },
  inTime: { label: 'In Time', shortLabel: 'In Time', icon: CheckCircle, color: 'var(--accent-green)', bg: 'var(--accent-green-bg)', border: 'var(--accent-green-border)' },
  delayed: { label: 'Delayed', shortLabel: 'Delayed', icon: AlertTriangle, color: 'var(--accent-red)', bg: 'var(--accent-red-bg)', border: 'var(--accent-red-border)' },
};

// Maps a summary-card response key to the underlying workflow_status value used for filtering.
export const CARD_KEY_TO_STATUS = {
  pending: 'pending',
  accepted: 'accepted',
  inProgress: 'in_progress',
  dependentOnOthers: 'dependent_on_others',
  blocked: 'blocked',
  verification: 'verification',
  completed: 'completed',
};

// Which summary card a task counts towards. Statuses with no card of their own are open work
// in the assignee's hands, so they land on In Progress — matching the backend's own bucketing
// (tasks.py status_key_map). Without this they fell through and were counted by no card at all,
// leaving the cards adding up to less than Total.
export const cardKeyForStatus = (status) => {
  const own = Object.keys(CARD_KEY_TO_STATUS).find(k => CARD_KEY_TO_STATUS[k] === status);
  return own || (status === 'completed' ? 'completed' : 'inProgress');
};

// The statuses a given card stands for — the inverse of cardKeyForStatus, so clicking a card
// filters to exactly the rows it counted.
export const statusesForCardKey = (key) =>
  WORKFLOW_STATUSES.filter(s => cardKeyForStatus(s) === key);

// Full 11-card order (Dashboard page): adds In Time / Delayed on top of the workflow states.
export const SUMMARY_CARD_ORDER = [
  ['totalTasks', EXTRA_CARD_CONFIG.totalTasks],
  ['overdue', EXTRA_CARD_CONFIG.overdue],
  ['pending', STATUS_CONFIG.pending],
  ['accepted', STATUS_CONFIG.accepted],
  ['dependentOnOthers', STATUS_CONFIG.dependent_on_others],
  ['blocked', STATUS_CONFIG.blocked],
  ['inProgress', STATUS_CONFIG.in_progress],
  ['verification', STATUS_CONFIG.verification],
  ['completed', STATUS_CONFIG.completed],
  ['inTime', EXTRA_CARD_CONFIG.inTime],
  ['delayed', EXTRA_CARD_CONFIG.delayed],
];

// Card order used on the task list pages (My/Delegated/Subscribed/All/Deleted Tasks) — no
// In Time / Delayed here, those are dashboard-only metrics. Pending is not shown either: a
// task sits at Pending only until someone opens it, so the card counted a queue nobody works
// from, between Total and the statuses that describe actual progress. The Group Dashboard
// keeps its own Pending card (GROUP_DASHBOARD_CARD_ORDER), where the backlog is the point.
export const LIST_CARD_ORDER = [
  ['totalTasks', EXTRA_CARD_CONFIG.totalTasks],
  ['overdue', EXTRA_CARD_CONFIG.overdue],
  ['accepted', STATUS_CONFIG.accepted],
  ['dependentOnOthers', STATUS_CONFIG.dependent_on_others],
  ['blocked', STATUS_CONFIG.blocked],
  ['inProgress', STATUS_CONFIG.in_progress],
  ['verification', STATUS_CONFIG.verification],
  ['completed', STATUS_CONFIG.completed],
];

// 6-card order for the Group Dashboard tab (Overdue/Pending/In Progress/Completed/In
// Time/Delayed) -- matches the reference screenshot's card set, reusing the same
// dot-style StatusSummaryCards component/configs as everywhere else in the module.
export const GROUP_DASHBOARD_CARD_ORDER = [
  ['overdue', EXTRA_CARD_CONFIG.overdue],
  ['pending', STATUS_CONFIG.pending],
  ['inProgress', STATUS_CONFIG.in_progress],
  ['completed', STATUS_CONFIG.completed],
  ['inTime', EXTRA_CARD_CONFIG.inTime],
  ['delayed', EXTRA_CARD_CONFIG.delayed],
];

// Priority renders as a filled pill (icon + label) in the table, so each level carries a full
// bg/border/icon set like STATUS_CONFIG does — red / amber / green reads as high-to-low at a
// glance without needing the label.
export const PRIORITY_CONFIG = {
  Low: { label: 'Low', color: 'var(--accent-green)', bg: 'var(--accent-green-bg)', border: 'var(--accent-green-border)', icon: ArrowDown },
  Normal: { label: 'Normal', color: 'var(--accent-yellow)', bg: 'var(--accent-yellow-bg)', border: 'var(--accent-yellow-border)', icon: AlertCircle },
  High: { label: 'High', color: 'var(--accent-red)', bg: 'var(--accent-red-bg)', border: 'var(--accent-red-border)', icon: AlertCircle },
};

export const WORKFLOW_STATUSES = Object.keys(STATUS_CONFIG);

// The initial statuses a user can actively pick from the status control: Accept,
// Dependent on Other, Blocked, Completed. "pending"/"in_progress"/"verification"/
// "in_progress_reopened" are at-rest or system/assigner-driven states, never directly
// selectable.
export const SELECTABLE_STATUSES = ['accepted', 'dependent_on_others', 'blocked', 'completed'];

// Statuses that require a Doer Name + Reason before they can be saved.
export const REASON_REQUIRED_STATUSES = ['dependent_on_others', 'blocked'];

// Pending Verification is the assigner's decision and nothing else: the ONLY two moves are
// Approve (→ Completed, final) and Reopen (→ back to the assignee for rework, with a new
// deadline + mandatory reason). The normal workflow statuses never apply at this stage.
export const VERIFICATION_ACTIONS = [
  ['completed', 'Approve'],
  ['in_progress_reopened', 'Reopen'],
];

// A dependency doer — someone the task was handed to via "Dependent on Other" — owns only that
// dependency, not the task. Their "Complete" resolves the dependency and hands the task back to
// the assignee who raised it (backend pops the dependency stack); they can also chain the
// dependency on to someone else, or ask for a deadline revision. Acknowledged Delegation, In
// Progress, Blocked and everything on the verification path belong to the real assignee and are
// never offered to them. (Revise isn't a status — the list rows have no picker, so it's added
// separately in TaskDetailsModal.)
export const DEPENDENCY_DOER_STATUSES = ['completed', 'dependent_on_others'];

// Options to show in a status <select>: the 4 selectable statuses, plus the task's current
// status prepended when it isn't one of them (so the control still displays e.g. "Pending"
// or "In Progress (Reopened)" correctly instead of falling back to a blank/mismatched value).
// A task in verification is excluded — callers must render VERIFICATION_ACTIONS instead.
export const statusOptions = (current, { isDependencyDoer = false } = {}) => {
  if (current === 'verification') return ['verification'];
  const allowed = isDependencyDoer ? DEPENDENCY_DOER_STATUSES : SELECTABLE_STATUSES;
  return allowed.includes(current) ? allowed : [current, ...allowed];
};

// Label for a status option, verification-aware: an ASSIGNEE (not the assigner) on a
// verification-required task requests verification rather than completing directly, so
// the "completed" option reads "Request for Verification" for them. A dependency doer is
// exempt — they complete a dependency, and verification is the real assignee's step later.
//
// This relabel describes the ACTION of completing, so it must not apply once the task is already
// completed (`currentStatus`) — an approved task reads "Completed", not "Request for Verification".
export const statusOptionLabel = (statusKey, { verificationRequired = false, isAssigner = false, isDependencyDoer = false, currentStatus = null } = {}) => {
  if (statusKey === 'completed' && currentStatus !== 'completed'
    && verificationRequired && !isAssigner && !isDependencyDoer) return 'Request for Verification';
  return STATUS_CONFIG[statusKey]?.label || statusKey;
};
