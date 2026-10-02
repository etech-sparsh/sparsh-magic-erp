/* ─────────────────────────────────────────────────────────────
   Notification Templates — shared vocabulary.

   Data and pure helpers only (no components), so every screen in the module describes a
   trigger, a module and a template's state in exactly the same words.
   ───────────────────────────────────────────────────────────── */
import {
  ListChecks, Repeat, CalendarDays, PlayCircle, Hourglass, ListTodo, UserCog,
  LayoutGrid, Award, Briefcase, Mail, MessageCircle,
} from 'lucide-react';

export const inputCls =
  'w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] transition-colors';

export const errMsg = (e, fallback) => e?.response?.data?.detail || fallback;

export const CHANNEL_META = {
  email: { key: 'email', label: 'Email', icon: Mail },
  whatsapp: { key: 'whatsapp', label: 'WhatsApp', icon: MessageCircle },
};

export const TONE = {
  green: { c: 'var(--accent-green)', bg: 'var(--accent-green-bg)', bd: 'var(--accent-green-border)' },
  indigo: { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  orange: { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
  red: { c: 'var(--accent-red)', bg: 'var(--accent-red-bg)', bd: 'var(--accent-red-border)' },
  muted: { c: 'var(--text-muted)', bg: 'var(--input-bg)', bd: 'var(--border)' },
};

/* The order modules appear in, everywhere. */
export const MODULE_ORDER = [
  'delegation', 'checklist', 'event', 'session', 'upcoming', 'todo', 'system',
  'tpms', 'leadership', 'hrms',
];

export const MODULE_ICON = {
  delegation: ListChecks,
  checklist: Repeat,
  event: CalendarDays,
  session: PlayCircle,
  upcoming: Hourglass,
  todo: ListTodo,
  system: UserCog,
  tpms: LayoutGrid,
  leadership: Award,
  hrms: Briefcase,
};

/* TPMS keys a notification by (activity × side × event). The event is the trigger; activity
   and side are chosen in TPMS's own editor. Words mirror tpms_notify_service's EVENT_*. */
export const TPMS_EVENTS = [
  { slug: 'schedule', label: 'Activity Scheduled', group: 'Activity lifecycle',
    description: "An activity is put on a company's TPMS calendar." },
  { slug: 'reminder', label: 'Activity Reminder', group: 'Activity lifecycle',
    description: 'An activity is coming due — sent on the days set in TPMS Reminder Rules.' },
  { slug: 'reschedule', label: 'Activity Rescheduled', group: 'Activity lifecycle',
    description: "An activity's date is moved." },
  { slug: 'cancel', label: 'Activity Cancelled', group: 'Activity lifecycle',
    description: 'An activity is cancelled.' },
  { slug: 'completed', label: 'Activity Completed', group: 'Activity lifecycle',
    description: 'An activity is confirmed complete.' },
  { slug: 'form_summary', label: 'Form Summary (HOD / MD)', group: 'After a review form',
    description: 'A review form is submitted. The summary goes to the HOD / MD.' },
  { slug: 'form_scorecard', label: 'Employee Scorecard', group: 'After a review form',
    description: 'A review form is submitted. The scorecard goes to the employee.' },
].map((t) => ({ ...t, channels: ['email', 'whatsapp'] }));

/* Modules whose templates live in their own stores and are managed by their own, existing
   screens — embedded in Notification Templates rather than rebuilt, so nothing about how they
   are stored or sent changes. */
export const EXTERNAL_MODULES = {
  tpms: {
    key: 'tpms', label: 'TPMS', external: true, channels: ['email', 'whatsapp'],
    description: 'Activity notifications for client companies — per activity, side and event.',
    triggers: TPMS_EVENTS,
  },
  leadership: {
    key: 'leadership', label: 'Leadership Score', external: true, channels: ['whatsapp'],
    description: 'The feedback invitation, one approved WhatsApp template per company.',
    triggers: [{
      slug: 'invitation', label: 'Feedback Invitation', channels: ['whatsapp'], group: '',
      description: 'HR or an administrator sends Leadership Score links. Each person asked for feedback gets their own link.',
    }],
  },
  hrms: {
    key: 'hrms', label: 'HRMS', external: true, channels: ['email'],
    description: 'Candidate communications — acknowledgement, rejection, interview and offer emails.',
    triggers: [{
      slug: 'candidate', label: 'Candidate Communications', channels: ['email'], group: '',
      description: 'An application arrives, a candidate is rejected, or an interview is scheduled or moved.',
    }],
  },
};

/* ── Sample values for previews ── */
const SAMPLE = {
  name: 'Priya Sharma', user_name: 'Priya Sharma', assigned_user: 'Priya Sharma',
  assignee_name: 'Priya Sharma', new_assignee: 'Priya Sharma', doer_name: 'Rahul Verma',
  previous_assignee: 'Rahul Verma', loop_person: 'Neha Gupta',
  assigned_by: 'Anil Mehta', actor_name: 'Anil Mehta', assigner_name: 'Anil Mehta',
  updated_by: 'Anil Mehta', created_by: 'Anil Mehta', deleted_by: 'Anil Mehta',
  task_name: 'Prepare quarterly sales report', title: 'Prepare quarterly sales report',
  subtask_name: 'Collect branch figures', parent_task: 'Quarterly review',
  todo_title: 'Call the vendor',
  deadline: '15 Sep 2026, 05:00 PM', task_deadline: '15 Sep 2026, 05:00 PM',
  due_date: '15 Sep 2026', old_deadline: '12 Sep 2026', new_deadline: '15 Sep 2026',
  occurrence_date: '15 Sep 2026', repeat_end_date: '31 Dec 2026', assigned_date: '10 Sep 2026',
  todo_due_date: '15 Sep 2026', todo_due_time: '05:00 PM',
  date: '15 Sep 2026', day: 'Tuesday', time: '05:00 PM', event_time: '15 Sep 2026, 05:00 PM',
  event_datetime: '15 Sep 2026, 05:00 PM', reminder_time: '1 hour before',
  critical_level: 'High', priority: 'High', task_status: 'In Progress', task_category: 'Sales',
  reason: 'Waiting for branch data', remark: 'Please share an update',
  description: 'Share the final numbers with the leadership team.',
  days_overdue: '2', days_remaining: '3', repeat_type: 'Weekly', repeat_interval: '1',
  series_total: '12', occurrence_note: '',
  event_title: 'Leadership Coaching Session', topic: 'Leadership Coaching Session',
  session_type: 'Coaching', meeting_link: 'https://meet.google.com/abc-defg-hij',
  meeting_url: 'https://meet.google.com/abc-defg-hij', batch_name: 'Batch A', quarter: 'Q3',
  email: 'priya@example.com', password: 'Temp@1234', login_url: 'https://sparsh.app/login',
  new_role: 'Manager', role: 'Manager', company_name: 'Acme Industries',
};

export const sampleFor = (field) => (field in SAMPLE
  ? SAMPLE[field]
  : String(field || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()));

/** Replace every {{placeholder}} with a realistic sample, so a template reads as a message. */
export const fillSample = (text) =>
  String(text || '').replace(/\{\{\s*([A-Za-z0-9_]+)\s*\}\}/g, (_, v) => sampleFor(v));

export const looksLikeHtml = (text) => /<\s*(html|body|div|p|table|br|span|a|h\d|strong|b)[\s>/]/i.test(String(text || ''));

export const bareSlug = (slug) => String(slug || '').replace(/_(email|whatsapp)$/, '');

const pad = (n) => String(n).padStart(2, '0');
export const to12h = (h, m) => `${((h + 11) % 12) + 1}:${pad(m)} ${h < 12 ? 'AM' : 'PM'}`;

/** Triggers in their registry order, bucketed by `group` (one unnamed bucket when ungrouped). */
export const groupTriggers = (triggers = []) => {
  const out = [];
  triggers.forEach((t) => {
    const name = t.group || '';
    let bucket = out.find((b) => b.name === name);
    if (!bucket) { bucket = { name, items: [] }; out.push(bucket); }
    bucket.items.push(t);
  });
  return out;
};

/* ── What a trigger will actually do on a channel, in plain words ── */
const isOn = (row) => !!row && row.is_active !== false;
const hasBody = (row) => !!String(row?.body || '').trim();

/**
 * The state of one trigger on one channel.
 *
 *   row          the template for the scope being viewed (company or default)
 *   defaultRow   the default (staff) template, when a company is being viewed
 *   emailRow / emailDefaultRow   the same for the email channel — the WhatsApp copy of a
 *                "template_only" module is gated on its email template (see notify_modules)
 *   approved     Set of approved Meta template names, or null when unknown
 *   locked       the viewer is confined to their company and cannot see the default
 *
 * Returns { key, label, tone, hint, row, inherited }.
 */
export const triggerState = ({
  module, trigger, channel, row, defaultRow, emailRow, emailDefaultRow, approved, locked,
}) => {
  const templateOnly = module?.send_rule === 'template_only';
  const effective = row || defaultRow || null;
  const inherited = !row && !!defaultRow;
  const base = { row: row || null, inherited, effective };

  if (!(trigger.channels || ['email', 'whatsapp']).includes(channel)) {
    return { ...base, key: 'unsupported', label: 'Email only', tone: 'muted',
      hint: 'This event only ever sends an email.' };
  }

  // A company-locked viewer cannot see the default email template, so the gate is unknowable
  // for them when their company has no email copy of its own.
  if (channel === 'whatsapp' && templateOnly && !(locked && !emailRow)) {
    const email = emailRow || emailDefaultRow;
    if (!(isOn(email) && hasBody(email))) {
      return { ...base, key: 'waitingEmail', label: 'Waiting for email', tone: 'orange',
        hint: 'WhatsApp for this event only goes out while its Email template is on.' };
    }
  }

  if (!effective) {
    if (trigger.builtin?.[channel]) {
      return { ...base, key: 'builtin', label: 'Standard message', tone: 'indigo',
        hint: 'Sends the built-in message. Create a template to use your own wording.' };
    }
    if (locked) {
      return { ...base, key: 'inheritedUnknown', label: 'Standard message', tone: 'indigo',
        hint: 'Uses the Sparsh default. Create a template to send your own wording.' };
    }
    return { ...base, key: 'notSet', label: 'Not set up', tone: 'orange',
      hint: 'Nothing is sent on this channel until a template is created.' };
  }

  const prefix = inherited ? 'Default · ' : '';
  if (!isOn(effective)) {
    return { ...base, key: 'off', label: `${prefix}Turned off`, tone: 'muted',
      hint: 'Switched off — nothing is sent on this channel.' };
  }

  if (channel === 'email') {
    if (!hasBody(effective)) {
      return { ...base, key: 'empty', label: 'Empty message', tone: 'orange',
        hint: templateOnly ? 'The message is empty, so nothing is sent.' : 'The message is empty — a blank email would go out.' };
    }
    return { ...base, key: 'sending', label: `${prefix}Sending`, tone: 'green',
      hint: inherited ? 'Uses the default template.' : '' };
  }

  if (!effective.meta_template_name) {
    return { ...base, key: 'needsMeta', label: 'Needs Meta template', tone: 'orange',
      hint: 'No approved Meta template is chosen, so WhatsApp will almost never deliver it.' };
  }
  if (approved && !approved.has(effective.meta_template_name)) {
    return { ...base, key: 'notApproved', label: 'Template not approved', tone: 'red',
      hint: `"${effective.meta_template_name}" is not approved by Meta, so it cannot be delivered.` };
  }
  return { ...base, key: 'sending', label: `${prefix}Sending`, tone: 'green',
    hint: inherited ? 'Uses the default template.' : '' };
};
