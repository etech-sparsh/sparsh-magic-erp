/**
 * HRMS ▸ internal recruitment track — shared constants and pure helpers.
 *
 * Split from internalKit.jsx for the same reason analyticsKit is split: a module that
 * exports both components and plain values breaks React Fast Refresh, so the values live
 * here and the components next door. Same rule, same pair of filenames.
 */

export const CARD =
  'rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 sm:p-5';
export const FIELD =
  'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] '
  + 'text-[13px] text-[var(--text-main)]';
export const TEXTAREA =
  'w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] '
  + 'text-[13px] text-[var(--text-main)] resize-none';
export const LABEL =
  'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';
export const SECTION_TITLE =
  'text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]';

/**
 * Which tone a status name earns.
 *
 * TONE IS MEANING. Green only where the news is good, red only where something failed,
 * amber only where somebody is being waited on. An unknown value falls back to neutral
 * rather than throwing — a status added server-side must render, not break the screen.
 */
export const toneFor = (status) => ({
  Approved: 'good', Confirmed: 'good', Positive: 'good', met: 'good', Met: 'good',
  // Phase INT-4 — telephonic outcomes. "No Answer" is warn, not bad: a call nobody picked
  // up is unfinished work, not a verdict on the candidate.
  Passed: 'good', 'No Answer': 'warn',
  Strong: 'good', Consider: 'warn', Hold: 'warn', Reject: 'bad',
  Rejected: 'bad', Terminated: 'bad', Negative: 'bad', breached: 'bad', Breached: 'bad',
  overdue: 'bad', Overdue: 'bad',
  Pending: 'warn', 'Pending Approval': 'warn', 'Pending HR Verification': 'warn',
  'Pending Budget Approval': 'warn', 'Pending Scorecard Approval': 'warn',
  'Pending Escalation': 'warn', 'Unable to Verify': 'warn', Extended: 'warn',
  Draft: 'neutral', not_started: 'neutral',
  // ── Phase EXIT-1 — Exit Management ──
  // A case's own STAGE (SeparationStage) reads left to right as progress, so it is neutral
  // throughout except the two ends: Closed/Settled are the destination, Withdrawn is the one
  // stage that means nothing further will happen here.
  Initiated: 'neutral', 'Notice in Progress': 'warn', 'Handover & Clearance': 'warn',
  'F&F Pending': 'warn', 'F&F Approved': 'good', Settled: 'good', Closed: 'good',
  Withdrawn: 'neutral',
  // Handover / clearance / access-clearance item statuses.
  Cleared: 'good', Accepted: 'good', Submitted: 'warn', Waived: 'neutral',
  Disabled: 'good', 'Not Applicable': 'neutral',
  // Asset return outcomes — Returned is the good ending; the rest all mean a recovery or a
  // conversation, which is why only Returned gets the green.
  Returned: 'good', 'Partially Returned': 'warn', Lost: 'bad', Damaged: 'warn',
  // F&F settlement lifecycle.
  Prepared: 'warn', Paid: 'good',
  // ── Phase ATT-1 — Attendance & Leave ──
  // Daily attendance status. NOTE: 'Returned' is deliberately absent here — it already
  // means "the asset came back" (good) for Exit Management's asset-return status above, but
  // Phase ATT-1 uses the SAME string for "sent back to the employee for more info" on a
  // regularisation/leave request, which is the opposite tone (warn). Screens in
  // features/hrms/attendance and features/hrms/leave use `attLeaveToneFor` below instead of
  // this shared map for exactly that reason — do not add 'Returned' here.
  Present: 'good', Absent: 'bad', 'Half Day': 'warn',
  'On Leave': 'neutral', 'On OD': 'neutral', 'Weekly Off': 'neutral', Holiday: 'neutral',
  'Manager Approved': 'warn',
  Open: 'neutral', Locked: 'good',
  Cancelled: 'neutral',
  Available: 'good', Used: 'neutral', Expired: 'bad',
  // ── Phase MOVE-1 — Employee Movements & Discipline ──
  Applied: 'good',
  // Discipline case lifecycle — neutral throughout except the two ends, the same "a stage
  // reads as progress" pattern SeparationStage already established.
  'Under Investigation': 'warn', 'Recommendation Recorded': 'warn', Decided: 'warn',
  Restricted: 'bad', 'Standard': 'neutral',
  Warning: 'warn', Censure: 'warn', 'Show Cause': 'warn', 'No Action': 'neutral',
  Termination: 'bad',
  // Absconding ladder — each stage past Flagged is a worsening sign, so warn/bad rather
  // than the neutral "just progress" reading a routine workflow gets.
  Flagged: 'warn', 'First Warning Sent': 'warn', 'Second Warning Sent': 'bad',
  'Final Action': 'bad', 'Returned to Work': 'good', 'Converted to Separation': 'bad',
  // ── Phase PAY-1 — Payroll, Salary Advance & Variable Pay ── ('Locked' already mapped
  // to 'good' in Phase ATT-1's block above; payroll reuses the exact same meaning.)
  Calculated: 'warn',
  Recovering: 'warn', Held: 'warn', Released: 'good', Forfeited: 'bad',
  // ── Phase PIP-1 — Performance Improvement Plan ──
  Active: 'warn',
  'Successfully Closed': 'good', 'Further Action Required': 'bad',
  'Separation Recommended': 'bad',
  // 'Extended' and 'Draft' already map to 'warn'/'neutral' above.
  // ── Phase LETTER-1 — HR Letter / Document Generator ──
  Issued: 'good', Superseded: 'neutral',
  // ── Phase 11-R, Item 6 — dual budget capture (BudgetStatus) ── 'Pending' already maps to
  // 'warn' above, which is the right reading here too (one figure is in, one is not).
  Matched: 'good', Mismatch: 'bad',
}[status] || 'neutral');

/**
 * Attendance/Leave screens' own tone resolver — identical to `toneFor` except it corrects
 * 'Returned' to `warn` (a regularisation/leave sent back for more info, not a completed
 * hand-back). See the comment above `toneFor`'s Phase ATT-1 block for why the shared map
 * cannot carry this mapping itself.
 */
export const attLeaveToneFor = (status) => (status === 'Returned' ? 'warn' : toneFor(status));

/** A date, or an em dash. Never "Invalid Date", which reads as a bug in the data. */
export const day = (value) => {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? '—'
    : parsed.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
};

/** An amount, grouped for reading. Currency-symbol-free on purpose: the module stores plain
 *  numbers and a company's own currency is a setting, not something to guess here. */
export const money = (value) => {
  if (value == null || value === '') return '—';
  const n = Number(value);
  return Number.isNaN(n) ? '—' : n.toLocaleString();
};

/** Tints for `Tile` (internalKit.jsx) — the headline-number card both hiring boards use. */
const TILE_TONE = {
  indigo: { bg: 'bg-[var(--accent-indigo-bg)]', text: 'text-[var(--accent-indigo)]' },
  green: { bg: 'bg-[var(--accent-green-bg)]', text: 'text-[var(--accent-green)]' },
  orange: { bg: 'bg-[var(--accent-orange-bg)]', text: 'text-[var(--accent-orange)]' },
  red: { bg: 'bg-[var(--accent-red-bg)]', text: 'text-[var(--accent-red)]' },
};

export const tint = (tone) => TILE_TONE[tone] || TILE_TONE.indigo;
