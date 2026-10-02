import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RefreshCw, Mail, Plus, Pencil, X, ShieldAlert, CheckCircle2, AlertTriangle, Filter,
  MessageCircle, BadgeCheck, Eye, Info, Trash2,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, FilterSelect, Section, Th, Td, TableShell, usePaged, Pager,
} from '../../common/dashboardKit';
import TemplateComposer from '../../../../components/whatsapp/TemplateComposer';
import { EDITABLE_STATUSES, STATUS_TONE } from '../../../../components/whatsapp/constants';
import {
  getMailTemplates, upsertMailTemplate, getActivities,
  getWhatsappTemplates, upsertWhatsappTemplate, getWhatsappVariables, setTemplateStatus,
  checkMetaTemplate, deleteMetaTemplate, getApprovedMetaTemplates, getMetaTemplates,
  saveMetaTemplate, submitMetaTemplate, syncMetaTemplates, testMetaTemplate,
} from '../../../../services/tpmsApi';
import { useAuth } from '../../../../context/AuthContext';
import { isTpmsAdmin } from '../../access';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Notification Template Management (M12 + H1b).

   Three tabs, two different jobs:

   · Email / WhatsApp — the *wiring*. Which template fires for which (activity, side, event),
     and which data field fills each parameter. Saving is an upsert, so creating and editing
     hit the same endpoint. The catch-all '*' activity is the fallback used when no
     activity-specific row exists.

   · Templates — the WhatsApp template *library*. Definitions authored here and submitted to
     Meta for approval; they live on the WhatsApp Business Account, not in this CRM. The
     WhatsApp wiring tab can only point at one Meta has APPROVED, which is why the library
     sits beside it rather than on a screen of its own.

   Shown inside Notification Templates ▸ Email / WhatsApp ▸ TPMS (embedded); the old
   /tpms/admin/mail-templates address redirects there.
   ───────────────────────────────────────────────────────────── */

// Alias so the animated element is a plain JSX identifier (keeps `motion` counted
// as used by no-unused-vars, which doesn't track `motion.div` member expressions).
const MotionDiv = motion.div;

const SIDE_OPTIONS = ['staff', 'company'];
const EVENT_OPTIONS = ['schedule', 'reminder', 'reschedule', 'cancel', 'completed', 'form_summary', 'form_scorecard'];

// Variables available to the two post-submission form emails (event = form_summary / form_scorecard).
const FORM_SUMMARY_VARS = ['Recipient_Name', 'HOD_Name', 'Company_Name', 'Month', 'Form_Type', 'Submitted_On', 'Total_Ratings', 'Response_Table'];
const FORM_SCORECARD_VARS = ['Recipient_Name', 'Employee_Name', 'Company_Name', 'Month', 'Form_Type', 'Average_Rating', 'Total_Questions', 'Score_Table'];

const errMsg = (e, fallback) => e?.response?.data?.detail || fallback;

/** A blank form — also the shape used to reset the modal. */
const EMPTY_FORM = {
  activity: '*',
  side: 'staff',
  event: 'schedule',
  subject: '',
  body_html: '',
  // WhatsApp-only fields (ignored when authoring an email template):
  meta_template_name: '',
  language: 'en',
  variables: [],        // one data field per body {{n}}, in order
  header_variables: [], // the text header's variable, when the template has one
  button_variables: [], // one per variable URL button, in button order
  active: true,
};

const TONE = {
  green:  { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  indigo: { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  orange: { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
  red:    { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
  muted:  { c: 'var(--text-muted)',    bg: 'var(--input-bg)',         bd: 'var(--border)' },
};

const Pill = ({ label, tone = 'muted' }) => {
  const s = TONE[tone] || TONE.muted;
  return (
    <span className="inline-flex items-center text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border whitespace-nowrap"
      style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      {label}
    </span>
  );
};

const SIDE_TONE = { staff: 'indigo', company: 'orange' };

const CHANNELS = [
  { id: 'mail', label: 'Email', icon: Mail },
  { id: 'whatsapp', label: 'WhatsApp', icon: MessageCircle },
];

/* The three calls the composer makes. Hoisted so its identity is stable across renders. */
const COMPOSER_API = { checkMetaTemplate, saveMetaTemplate, submitMetaTemplate, testMetaTemplate };

/* The library's status filter — the Meta approval lifecycle, left to right. */
const LIBRARY_STATUS_TABS = [
  { id: '', label: 'All' },
  { id: 'DRAFT', label: 'Draft' },
  { id: 'PENDING', label: 'Pending' },
  { id: 'APPROVED', label: 'Approved' },
  { id: 'REJECTED', label: 'Rejected' },
];

/**
 * Warns when the Meta connection is missing or incomplete.
 *
 * Deliberately silent on the healthy path — a banner that only ever says "everything is fine"
 * is noise on every visit. It appears solely when something is actually wrong, so seeing it
 * means there is something to fix.
 */
const ConnectionBanner = ({ meta }) => {
  if (!meta || (meta.configured && meta.sending_configured)) return null;
  return (
    <div className="flex items-start gap-2 rounded-2xl border px-4 py-3 text-[12px] leading-relaxed"
      style={{ background: TONE.orange.bg, borderColor: TONE.orange.bd, color: 'var(--text-main)' }}>
      <Info size={15} className="mt-0.5 shrink-0" style={{ color: TONE.orange.c }} />
      <p>
        {meta.configured ? (
          <>
            <b>Sending is not configured.</b> Approved templates cannot be delivered until{' '}
            <b className="font-mono">WHATSAPP_PHONE_NUMBER_ID</b> is set in the backend
            environment. Authoring and submitting to Meta still work.
          </>
        ) : (
          <>
            <b>Not connected.</b> Set <b className="font-mono">WHATSAPP_ACCESS_TOKEN</b> and{' '}
            <b className="font-mono">WHATSAPP_BUSINESS_ACCOUNT_ID</b> in the backend environment
            to submit templates and read their approval status. Drafting still works here.
          </>
        )}
      </p>
    </div>
  );
};

/** Confirmation before deleting a library template — it is removed from the WhatsApp Business
 *  Account too, which cannot be undone. */
const ConfirmDeleteModal = ({ target, busy, onCancel, onConfirm }) => (
  <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
    <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={busy ? undefined : onCancel} />
    <MotionDiv role="dialog" aria-modal="true"
      initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 14, scale: 0.98 }} transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
      className="relative w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
      <div className="flex items-center gap-2.5 px-5 py-4 border-b border-[var(--border)]">
        <span className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: 'var(--accent-red-bg)', color: 'var(--accent-red)' }}>
          <Trash2 size={16} />
        </span>
        <h3 className="text-[15px] font-extrabold tracking-tight">Delete this template?</h3>
      </div>
      <div className="px-5 py-4 space-y-3">
        <div className="rounded-lg bg-[var(--input-bg)] border border-[var(--border)] px-3.5 py-2.5 text-[12.5px]">
          <div className="font-bold font-mono">{target.name}</div>
          <div className="text-[var(--text-muted)] mt-0.5">
            {target.language} · {target.meta_category || target.category} · {target.status}
          </div>
        </div>
        <p className="text-[13px] leading-relaxed">
          {target.meta_template_id
            ? 'This removes the template from your WhatsApp Business Account as well. Any notification that still names it will start failing at send time.'
            : 'This draft was never submitted to Meta, so only the local record is removed.'}
        </p>
      </div>
      <div className="px-5 py-3 border-t border-[var(--border)] flex items-center justify-end gap-2">
        <button type="button" onClick={onCancel} disabled={busy}
          className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
          Cancel
        </button>
        <button type="button" onClick={onConfirm} disabled={busy}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-60"
          style={{ background: 'var(--accent-red)' }}>
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <Trash2 size={14} />}
          {busy ? 'Deleting…' : 'Delete'}
        </button>
      </div>
    </MotionDiv>
  </MotionDiv>
);

/**
 * Active/Inactive switch for one template row — the same control the ERP module toggles use.
 * Purely presentational: the parent owns the confirmation step, so a stray click can never
 * change a notification's status on its own.
 */
const StatusToggle = ({ active, disabled, onRequest }) => (
  <button
    type="button"
    role="switch"
    aria-checked={active}
    aria-label={`Notification ${active ? 'active' : 'inactive'}`}
    disabled={disabled}
    onClick={onRequest}
    title={disabled ? 'Only Admin / Super Admin can change notification status'
      : active ? 'Deactivate this notification' : 'Activate this notification'}
    className="inline-flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
  >
    <span className="relative inline-flex w-9 h-5 rounded-full transition-colors shrink-0"
      style={{ background: active ? 'var(--accent-green)' : 'var(--border)' }}>
      <span className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all"
        style={{ left: active ? '18px' : '2px' }} />
    </span>
    <span className="text-[10px] font-bold uppercase tracking-widest w-12 text-left"
      style={{ color: active ? 'var(--accent-green)' : 'var(--text-muted)' }}>
      {active ? 'Active' : 'Inactive'}
    </span>
  </button>
);

/** Confirmation step required before any status change (both directions). */
const ConfirmStatusModal = ({ target, channelLabel, busy, onCancel, onConfirm }) => {
  const turningOff = target.active !== false;
  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={busy ? undefined : onCancel} />
      <MotionDiv
        role="dialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-[var(--border)]">
          <span className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={turningOff
              ? { background: 'var(--accent-orange-bg)', color: 'var(--accent-orange)' }
              : { background: 'var(--accent-green-bg)', color: 'var(--accent-green)' }}>
            {turningOff ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
          </span>
          <h3 className="text-[15px] font-extrabold tracking-tight">
            {turningOff ? 'Deactivate notification?' : 'Activate notification?'}
          </h3>
        </div>
        <div className="px-5 py-4 space-y-3">
          <div className="rounded-lg bg-[var(--input-bg)] border border-[var(--border)] px-3.5 py-2.5 text-[12.5px]">
            <div className="font-bold">{target.activity || '*'}</div>
            <div className="text-[var(--text-muted)] mt-0.5">
              {channelLabel} · {target.side || '—'} · {target.event || '—'}
            </div>
          </div>
          <p className="text-[13px] text-[var(--text-main)] leading-relaxed">
            {turningOff
              ? `This ${channelLabel} notification will stop being sent. Everything else keeps working exactly as now — activities still schedule, complete and escalate, scores still calculate. Only the message is suppressed.`
              : `This ${channelLabel} notification will start being sent again to its usual recipients.`}
          </p>
        </div>
        <div className="px-5 py-3 border-t border-[var(--border)] flex items-center justify-end gap-2">
          <button type="button" onClick={onCancel} disabled={busy}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Cancel
          </button>
          <button type="button" onClick={onConfirm} disabled={busy}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-60"
            style={{ background: turningOff ? 'var(--accent-orange)' : 'var(--accent-green)' }}>
            {busy ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
            {busy ? 'Saving…' : turningOff ? 'Deactivate' : 'Activate'}
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

/* Shared field styles for the modal. */
const inputCls =
  'w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] transition-colors';
const labelCls = 'text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]';

const Field = ({ label, children, required }) => (
  <label className="flex flex-col gap-1.5">
    <span className={labelCls}>{label}{required && <span className="text-[var(--accent-red)]"> *</span>}</span>
    {children}
  </label>
);

const Select = ({ value, onChange, options }) => (
  <select value={value} onChange={(e) => onChange(e.target.value)} className={`${inputCls} cursor-pointer`}>
    {options.map((o) => <option key={o} value={o}>{o}</option>)}
  </select>
);

/** Seed the form from a template row (edit) or a blank (add). `preset` pre-selects fields on
 *  an add — Notification Templates opens this with the event already chosen. */
const seedForm = (editing, preset) => (editing
  ? {
    activity: editing.activity || '*',
    side: SIDE_OPTIONS.includes(editing.side) ? editing.side : 'staff',
    event: EVENT_OPTIONS.includes(editing.event) ? editing.event : 'schedule',
    subject: editing.subject || '',
    body_html: editing.body_html || '',
    meta_template_name: editing.meta_template_name || editing.name || '',
    language: editing.language || 'en',
    variables: Array.isArray(editing.variables) ? editing.variables : [],
    header_variables: Array.isArray(editing.header_variables) ? editing.header_variables : [],
    // Stored as {index, field}; the form holds just the field, aligned to the template's
    // variable URL buttons. Bare strings are rows written before the index was recorded.
    button_variables: Array.isArray(editing.button_variables)
      ? editing.button_variables.map((b) => (typeof b === 'string' ? b : b?.field || ''))
      : [],
    active: editing.active !== false,
  }
  : { ...EMPTY_FORM, ...(preset || {}) });

/**
 * Add / Edit modal — reused for both create and update flows (both upsert).
 * Mounted only while open (via a keyed parent), so state seeds cleanly from
 * props on mount — no effect-driven syncing needed.
 */
const TemplateModal = ({ editing, preset, activityOptions, channel = 'mail', variableFields = [],
  approvedTemplates = [], onClose, onSubmit }) => {
  const [form, setForm] = useState(() => seedForm(editing, preset));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const isWa = channel === 'whatsapp';

  // The approved template this notification points at, and the parameter slots it declares.
  // Rows saved before the library existed may name a template approved directly in WhatsApp
  // Manager, so an unknown name is kept and shown rather than silently cleared.
  const selected = approvedTemplates.find((t) => t.name === form.meta_template_name);
  const bodySlots = selected ? selected.body_variables || [] : (form.variables || []).map((_, i) => String(i + 1));
  const headerSlots = selected ? selected.header_variables || [] : (form.header_variables || []).map(() => '1');
  const urlButtons = selected ? selected.url_buttons || [] : [];

  /** Adopt a template: keep any mapping that still fits, drop what no longer does, and take
   *  the template's own language so the two can never drift apart. */
  const pickTemplate = (name) => {
    const tpl = approvedTemplates.find((t) => t.name === name);
    setForm((f) => ({
      ...f,
      meta_template_name: name,
      language: tpl?.language || f.language,
      variables: (tpl?.body_variables || []).map((_, i) => (f.variables || [])[i] || ''),
      header_variables: (tpl?.header_variables || []).map((_, i) => (f.header_variables || [])[i] || ''),
      button_variables: (tpl?.url_buttons || []).map((_, i) => (f.button_variables || [])[i] || ''),
    }));
  };

  const setSlot = (key, i, value) => set(key, Object.assign([...(form[key] || [])], { [i]: value }));
  // The two post-submission form emails expose their own variable set (Response_Table, etc.).
  const isForm = form.event === 'form_summary' || form.event === 'form_scorecard';
  const paletteVars = form.event === 'form_summary' ? FORM_SUMMARY_VARS
    : form.event === 'form_scorecard' ? FORM_SCORECARD_VARS
    : variableFields;

  // Insert a {{placeholder}} into the email body at the cursor.
  const insertBodyVar = (v) => {
    const token = `{{${v}}}`;
    const ta = document.getElementById('mail-body');
    if (!ta) { set('body_html', (form.body_html || '') + token); return; }
    const start = ta.selectionStart ?? (form.body_html || '').length;
    const end = ta.selectionEnd ?? start;
    set('body_html', (form.body_html || '').slice(0, start) + token + (form.body_html || '').slice(end));
    requestAnimationFrame(() => { ta.focus(); const p = start + token.length; ta.setSelectionRange(p, p); });
  };

  const submit = async (e) => {
    e.preventDefault();
    if (isWa && !form.meta_template_name.trim()) { setErr('Choose an approved WhatsApp template.'); return; }
    if (!isWa && !form.subject.trim()) { setErr('Subject is required.'); return; }
    setSaving(true);
    setErr('');
    try {
      const base = { ...form, activity: form.activity.trim() || '*' };
      await onSubmit(isWa
        ? { ...base, meta_template_name: form.meta_template_name.trim(),
            language: (form.language || 'en').trim() || 'en',
            // Unmapped slots are dropped rather than sent blank — the send layer's field
            // guesser and its "-" fallback then handle them, as they always have.
            variables: (form.variables || []).filter(Boolean),
            header_variables: (form.header_variables || []).filter(Boolean),
            // Send each button's real position in the template, not its position among the
            // variable ones — that is the number Meta substitutes against.
            button_variables: urlButtons
              .map((b, i) => ({ index: b.index, field: (form.button_variables || [])[i] || '' }))
              .filter((b) => b.field) }
        : { ...base, subject: form.subject.trim(), body_html: form.body_html });
    } catch (ex) {
      setErr(errMsg(ex, 'Failed to save template. Please try again.'));
      setSaving(false);
    }
  };

  return (
    <MotionDiv
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-xl rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden max-h-[90vh] flex flex-col">
        {/* header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              {editing ? <Pencil size={16} /> : <Plus size={16} />}
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">{editing ? 'Edit Template' : 'Add Template'}</h3>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={submit} className="px-5 py-4 space-y-4 overflow-y-auto">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Field label="Activity" required>
              <Select value={form.activity} onChange={(v) => set('activity', v)} options={activityOptions} />
            </Field>
            <Field label="Side" required>
              <Select value={form.side} onChange={(v) => set('side', v)} options={SIDE_OPTIONS} />
            </Field>
            <Field label="Event" required>
              <Select value={form.event} onChange={(v) => set('event', v)} options={EVENT_OPTIONS} />
            </Field>
          </div>

          {!isWa && (
            <>
              <Field label="Subject" required>
                <input type="text" value={form.subject} onChange={(e) => set('subject', e.target.value)}
                  placeholder="e.g. [Reminder] {{Activity}} due in 2 days | {{Company_Name}}" className={inputCls} autoFocus />
              </Field>

              <Field label="Body (HTML)">
                <textarea id="mail-body" value={form.body_html} onChange={(e) => set('body_html', e.target.value)}
                  placeholder="<p>Hello {{Recipient_Name}}, …</p>  — use {{double-brace}} placeholders" rows={7}
                  className={`${inputCls} font-mono text-[12px] leading-relaxed resize-y`} />
              </Field>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wide">Insert a variable</label>
                  <span className="text-[11px] text-[var(--text-muted)]">click to add at the cursor</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {paletteVars.map((v) => (
                    <button key={v} type="button" onClick={() => insertBodyVar(v)}
                      className={`font-mono text-[11px] px-2 py-1 rounded-md border transition-colors ${(v === 'Form_Link' || v === 'Response_Table' || v === 'Score_Table')
                        ? 'border-[var(--accent-indigo-border)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] font-bold'
                        : 'border-[var(--border)] bg-[var(--input-bg)] text-[var(--text-main)] hover:border-[var(--accent-indigo)]'}`}>
                      {`{{${v}}}`}
                    </button>
                  ))}
                </div>
                {isForm ? (
                  <p className="text-[11.5px] text-[var(--text-muted)] mt-2 leading-relaxed">
                    This mail is sent <b>after a form is submitted</b>.
                    {form.event === 'form_summary'
                      ? <> Use <b style={{ color: 'var(--accent-indigo)' }}>{'{{Response_Table}}'}</b> for the full ratings grid (HOD/MD summary).</>
                      : <> Use <b style={{ color: 'var(--accent-indigo)' }}>{'{{Score_Table}}'}</b> and <b style={{ color: 'var(--accent-indigo)' }}>{'{{Average_Rating}}'}</b> for the employee's scorecard.</>}
                    &nbsp;Leave the body empty to use the built-in default layout.
                  </p>
                ) : (
                  <p className="text-[11.5px] text-[var(--text-muted)] mt-2 leading-relaxed">
                    <b style={{ color: 'var(--accent-indigo)' }}>{'{{Form_Link}}'}</b> = the recipient's own unique,
                    single-use link (valid for that month only). For a <b>two-form</b> activity like
                    Accountability&nbsp;&amp;&nbsp;Ownership, use <b style={{ color: 'var(--accent-indigo)' }}>{'{{Form_Link_2}}'}</b>
                    for the second form, or <b style={{ color: 'var(--accent-indigo)' }}>{'{{Form_Links}}'}</b> to drop a
                    ready-made block of <em>all</em> the recipient's links at once. Put these in the <b>schedule</b> email.
                  </p>
                )}
              </div>
            </>
          )}

          {isWa && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="sm:col-span-2">
                  <Field label="Approved Template" required>
                    <select value={form.meta_template_name} onChange={(e) => pickTemplate(e.target.value)}
                      className={`${inputCls} font-mono cursor-pointer`} autoFocus>
                      <option value="">— select an approved template —</option>
                      {approvedTemplates.map((t) => (
                        <option key={t._id} value={t.name}>{t.name} ({t.language})</option>
                      ))}
                      {/* Approved in WhatsApp Manager before the library existed — keep it
                          selectable so an existing notification is never silently unwired. */}
                      {form.meta_template_name && !selected && (
                        <option value={form.meta_template_name}>{form.meta_template_name} (not in library)</option>
                      )}
                    </select>
                  </Field>
                </div>
                <Field label="Language">
                  <input type="text" value={form.language} readOnly={Boolean(selected)}
                    onChange={(e) => set('language', e.target.value)} placeholder="en"
                    title={selected ? "Taken from the approved template" : undefined}
                    className={`${inputCls} ${selected ? 'opacity-70' : ''}`} />
                </Field>
              </div>

              {approvedTemplates.length === 0 ? (
                <p className="text-[11.5px] text-[var(--text-muted)] leading-relaxed rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2.5">
                  No approved templates yet. Author one under the <b>Templates</b> tab and submit
                  it to Meta — only approved templates can be used for TPMS WhatsApp notifications.
                </p>
              ) : selected ? (
                <p className="text-[11.5px] text-[var(--text-muted)] leading-relaxed rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2.5">
                  {selected.body}
                </p>
              ) : null}

              {headerSlots.length > 0 && (
                <div>
                  <label className="block text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wide mb-1.5">
                    Header parameter
                  </label>
                  {headerSlots.map((v, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="text-[11px] font-black text-[var(--accent-indigo)] w-16 shrink-0 font-mono">{`{{${v}}}`}</span>
                      <select value={(form.header_variables || [])[i] || ''}
                        onChange={(e) => setSlot('header_variables', i, e.target.value)} className={`${inputCls} flex-1`}>
                        <option value="">— select field —</option>
                        {variableFields.map((f) => <option key={f} value={f}>{f}</option>)}
                      </select>
                    </div>
                  ))}
                </div>
              )}

              <div>
                <label className="block text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wide mb-1.5">
                  Body parameters {selected ? '(from the approved template)' : `(order = {{1}}, {{2}}…)`}
                </label>
                {bodySlots.length === 0 ? (
                  <p className="text-[11px] text-[var(--text-muted)] italic">
                    {form.meta_template_name
                      ? 'This template takes no parameters — nothing to map.'
                      : 'Select a template to see the parameters it needs.'}
                  </p>
                ) : (
                  <div className="space-y-2">
                    {bodySlots.map((v, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className="text-[11px] font-black text-[var(--accent-indigo)] w-16 shrink-0 font-mono">{`{{${v}}}`}</span>
                        <select value={(form.variables || [])[i] || ''}
                          onChange={(e) => setSlot('variables', i, e.target.value)} className={`${inputCls} flex-1`}>
                          <option value="">— select field —</option>
                          {variableFields.map((f) => <option key={f} value={f}>{f}</option>)}
                        </select>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {urlButtons.length > 0 && (
                <div>
                  <label className="block text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wide mb-1.5">
                    Button URL parameters
                  </label>
                  <div className="space-y-2">
                    {urlButtons.map((b, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className="text-[11px] font-bold text-[var(--text-muted)] w-24 shrink-0 truncate" title={b.url}>
                          {b.text || `Button ${b.index + 1}`}
                        </span>
                        <select value={(form.button_variables || [])[i] || ''}
                          onChange={(e) => setSlot('button_variables', i, e.target.value)} className={`${inputCls} flex-1`}>
                          <option value="">— select field —</option>
                          {variableFields.map((f) => <option key={f} value={f}>{f}</option>)}
                        </select>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          <Field label="Active">
            <button type="button" onClick={() => set('active', !form.active)}
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-bold transition-colors hover:border-[var(--accent-indigo)] w-fit">
              <span className="relative inline-flex w-9 h-5 rounded-full transition-colors"
                style={{ background: form.active ? 'var(--accent-green)' : 'var(--border)' }}>
                <span className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all"
                  style={{ left: form.active ? '18px' : '2px' }} />
              </span>
              <span style={{ color: form.active ? 'var(--accent-green)' : 'var(--text-muted)' }}>
                {form.active ? 'Active' : 'Inactive'}
              </span>
            </button>
          </Field>

          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} disabled={saving}
              className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
              Cancel
            </button>
            <button type="submit" disabled={saving}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-60">
              {saving ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
              {saving ? 'Saving…' : editing ? 'Save Changes' : 'Save Template'}
            </button>
          </div>
        </form>
      </MotionDiv>
    </MotionDiv>
  );
};

/**
 * `embedded` — rendered inside Notification Templates, which supplies the page header, the
 * channel (`channel`: 'mail' | 'whatsapp') and the shared Meta template library, so this screen
 * shows only its own TPMS notifications. `createPreset` opens the Add form with that event
 * chosen; `onPresetUsed` lets the host clear it.
 */
const MailTemplateAdmin = ({ embedded = false, channel: fixedChannel, createPreset, onPresetUsed }) => {
  const { user } = useAuth();
  const admin = isTpmsAdmin(user);

  const [templates, setTemplates] = useState([]);
  const [activities, setActivities] = useState([]);
  const [filter, setFilter] = useState(''); // '' = all, '*' = catch-all, else activity name
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  // Which editor is open: 'wiring' points a notification at a template, 'library' authors a
  // template and talks to Meta. Both live on the WhatsApp tab, so the kind is explicit.
  const [modalKind, setModalKind] = useState('wiring');
  const [editing, setEditing] = useState(null);
  const [channel, setChannel] = useState(fixedChannel || 'mail');
  // Fields pre-selected on an Add opened from Notification Templates.
  const [preset, setPreset] = useState(null);
  // The row awaiting confirmation before its status flips. null = no dialog open.
  const [confirmTarget, setConfirmTarget] = useState(null);
  const [statusSaving, setStatusSaving] = useState(false);
  // Fields a WhatsApp template's positional params can map to (loaded once, on demand).
  const [variableFields, setVariableFields] = useState([]);
  // ── WhatsApp template library (same tab, section above the notifications) ──
  const [library, setLibrary] = useState([]);        // template definitions + Meta status
  const [meta, setMeta] = useState(null);            // Graph connection status for the banner
  const [libStatus, setLibStatus] = useState('');    // '' | DRAFT | PENDING | APPROVED | REJECTED
  const [approved, setApproved] = useState([]);      // what the notifications may point at
  const [notice, setNotice] = useState('');
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const isWhatsapp = channel === 'whatsapp';
  const channelLabel = isWhatsapp ? 'WhatsApp' : 'Email';

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const fetcher = channel === 'whatsapp' ? getWhatsappTemplates : getMailTemplates;
      const res = await fetcher(filter || undefined);
      const list = res?.data?.templates;
      setTemplates(Array.isArray(list) ? list : []);
    } catch (e) {
      setError(errMsg(e, `Failed to load ${channel === 'whatsapp' ? 'WhatsApp' : 'mail'} notifications.`));
    } finally {
      setLoading(false);
    }
  }, [filter, channel]);

  /** The template library and the approved subset the notifications may use. Only the WhatsApp
   *  tab needs either, so it is a separate fetch from the notification list above. */
  const loadLibrary = useCallback(async () => {
    try {
      const { data } = await getMetaTemplates(libStatus || undefined);
      setLibrary(Array.isArray(data.templates) ? data.templates : []);
      setMeta(data.meta || null);
    } catch (e) {
      setError(errMsg(e, 'Failed to load the WhatsApp template library.'));
    }
    try {
      const { data } = await getApprovedMetaTemplates();
      setApproved(Array.isArray(data.templates) ? data.templates : []);
    } catch {
      setApproved([]);
    }
  }, [libStatus]);

  /** Meta reviews asynchronously and never calls back, so PENDING → APPROVED/REJECTED only
   *  becomes visible when we ask for it. */
  const handleSync = useCallback(async () => {
    setSyncing(true);
    setError('');
    setNotice('');
    try {
      const { data } = await syncMetaTemplates();
      const bits = [`${data.total} template${data.total === 1 ? '' : 's'} read from Meta`];
      if (data.imported) bits.push(`${data.imported} imported`);
      setNotice(`${bits.join(' · ')}.`);
      await loadLibrary();
    } catch (e) {
      setError(errMsg(e, 'Could not reach Meta to refresh statuses.'));
    } finally {
      setSyncing(false);
    }
  }, [loadLibrary]);

  const handleDelete = useCallback(async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteMetaTemplate(deleteTarget._id);
      setDeleteTarget(null);
      setNotice('Template deleted.');
      await loadLibrary();
    } catch (e) {
      setError(errMsg(e, 'Could not delete the template.'));
      setDeleteTarget(null);
    } finally {
      setDeleting(false);
    }
  }, [deleteTarget, loadLibrary]);

  /** The composer saved or submitted — close it and show what happened. A newly approved
   *  template must also become selectable below, hence the library refresh. */
  const onComposerSaved = useCallback(async (message) => {
    setModalOpen(false);
    setEditing(null);
    setNotice(message);
    setError('');
    await loadLibrary();
  }, [loadLibrary]);

  /** Apply the confirmed status change, then refresh so the row reflects the stored value. */
  const applyStatusChange = useCallback(async () => {
    if (!confirmTarget) return;
    setStatusSaving(true);
    try {
      await setTemplateStatus(channel, confirmTarget._id, confirmTarget.active === false);
      setConfirmTarget(null);
      await load();
    } catch (e) {
      setError(errMsg(e, 'Failed to update notification status.'));
      setConfirmTarget(null);
    } finally {
      setStatusSaving(false);
    }
  }, [confirmTarget, channel, load]);

  const loadActivities = useCallback(async () => {
    try {
      const res = await getActivities();
      const list = res?.data?.activities;
      setActivities(Array.isArray(list) ? list.map((a) => a.name).filter(Boolean) : []);
    } catch {
      setActivities([]);
    }
  }, []);

  useEffect(() => { if (admin) load(); }, [admin, load]);
  useEffect(() => { if (admin) loadActivities(); }, [admin, loadActivities]);

  // The library is WhatsApp-only. Refetched whenever the tab is opened or its status filter
  // changes, so a template approved a minute ago is selectable without a page reload.
  useEffect(() => { if (admin && isWhatsapp) loadLibrary(); }, [admin, isWhatsapp, loadLibrary]);

  // A notice belongs to the tab that produced it.
  useEffect(() => { setNotice(''); setError(''); }, [channel]);

  // Filter dropdown: All + catch-all '*' + every activity.
  const filterOptions = useMemo(
    () => [{ id: '', name: 'All activities' }, { id: '*', name: '*  (catch-all)' },
      ...activities.map((a) => ({ id: a, name: a }))],
    [activities],
  );

  // Form activity dropdown: catch-all '*' first, then every activity.
  const formActivityOptions = useMemo(() => ['*', ...activities], [activities]);

  const pTemplates = usePaged(templates || [], 10);
  const pLibrary = usePaged(library || [], 10);

  const openWiring = (row = null) => { setPreset(null); setModalKind('wiring'); setEditing(row); setModalOpen(true); };
  const openLibrary = (row = null) => { setModalKind('library'); setEditing(row); setModalOpen(true); };

  const handleSubmit = async (payload) => {
    await (channel === 'whatsapp' ? upsertWhatsappTemplate(payload) : upsertMailTemplate(payload));
    setModalOpen(false);
    setEditing(null);
    await load();
  };

  // Available {{placeholders}} for both channels — powers the email insert palette and the
  // WhatsApp parameter dropdowns. Loaded once for any admin.
  useEffect(() => {
    if (admin && variableFields.length === 0) {
      getWhatsappVariables().then(({ data }) => setVariableFields(data.fields || [])).catch(() => {});
    }
  }, [admin, variableFields.length]);

  // Opened from Notification Templates' "New template" with the event already chosen.
  useEffect(() => {
    if (!createPreset) return;
    setPreset({ event: createPreset });
    setModalKind('wiring');
    setEditing(null);
    setModalOpen(true);
    onPresetUsed?.();
  }, [createPreset, onPresetUsed]);

  if (!admin) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold text-[var(--text-main)]">Admins only</p>
        <p className="text-[12.5px] text-[var(--text-muted)] max-w-sm">
          Template Management is restricted to TPMS administrators.
        </p>
      </div>
    );
  }

  if (loading && templates.length === 0) {
    return <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading templates…</div>;
  }

  return (
    <div className="space-y-5">
      {embedded && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3 shadow-sm">
          <div className="min-w-0">
            <p className="text-[13px] font-extrabold">TPMS · {channelLabel} notifications</p>
            <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
              Each activity, side (Sparsh team or client company) and event can have its own template.
              An activity without one uses the &quot;*&quot; (all activities) template.
            </p>
          </div>
          <FilterSelect value={filter} onChange={setFilter} options={filterOptions} />
        </div>
      )}

      {!embedded && (
      <DashboardHero icon={Mail} title="Notification Templates"
        subtitle={isWhatsapp
          ? 'Create WhatsApp templates, get them approved by Meta, and wire the approved ones to activities, sides & events'
          : 'Email & WhatsApp templates keyed by activity, side & event — switch any notification off without affecting the workflow behind it'}>
        <div className="flex items-center gap-1 bg-white/20 p-1 rounded-lg">
          {CHANNELS.map((c) => (
            <button key={c.id} onClick={() => setChannel(c.id)} type="button"
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-bold transition-all ${
                channel === c.id ? 'bg-white text-[var(--accent-indigo)] shadow-sm' : 'text-white/80 hover:text-white'}`}>
              <c.icon size={13} /> {c.label}
            </button>
          ))}
        </div>
        <HeaderSelect value={filter} onChange={setFilter} options={filterOptions} />
        {isWhatsapp && (
          <HeroButton icon={Plus} onClick={() => openLibrary()}>New template</HeroButton>
        )}
        <HeroButton icon={RefreshCw} onClick={() => { load(); if (isWhatsapp) loadLibrary(); }}>
          Refresh
        </HeroButton>
      </DashboardHero>
      )}

      {isWhatsapp && !embedded && <ConnectionBanner meta={meta} />}

      {notice && (
        <div className="flex items-start gap-2 rounded-2xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-green)]">
          <CheckCircle2 size={15} className="mt-0.5 shrink-0" /> {notice}
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {/* ── The WhatsApp template library. Definitions that live on the WhatsApp Business
             Account, with where each one has got to in Meta's review. Sits above the
             notifications because a template must exist and be approved before anything can
             be wired to it. ── */}
      {isWhatsapp && !embedded && (
        <Section
          title="WhatsApp Templates"
          subtitle={library.length
            ? `${library.length} template${library.length === 1 ? '' : 's'} on your business account`
            : 'Nothing yet'}
          icon={BadgeCheck}
          action={(
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1 p-1 rounded-lg bg-[var(--input-bg)] border border-[var(--border)]">
                {LIBRARY_STATUS_TABS.map((s) => (
                  <button key={s.id} type="button" onClick={() => setLibStatus(s.id)}
                    className={`px-2.5 py-1.5 rounded-md text-[11.5px] font-bold transition-colors ${
                      libStatus === s.id
                        ? 'bg-[var(--bg-card)] text-[var(--accent-indigo)] shadow-sm'
                        : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
                    {s.label}
                  </button>
                ))}
              </div>
              <button type="button" onClick={handleSync} disabled={syncing}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-main)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                <RefreshCw size={13} className={syncing ? 'animate-spin' : undefined} />
                {syncing ? 'Syncing…' : 'Sync with Meta'}
              </button>
              <button type="button" onClick={() => openLibrary()}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold shadow-sm hover:opacity-90 transition-opacity">
                <Plus size={13} /> New template
              </button>
            </div>
          )}>
          {library.length === 0 ? (
            <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
              <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
                <BadgeCheck size={20} />
              </span>
              <p className="text-[13px] font-bold text-[var(--text-main)]">No templates yet</p>
              <p className="text-[12px] text-[var(--text-muted)] max-w-md">
                {libStatus
                  ? `No ${libStatus.toLowerCase()} templates.`
                  : 'Create your first template and submit it to Meta, or sync to pull in templates already approved on your business account.'}
              </p>
              <button onClick={() => openLibrary()}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:opacity-90 transition-opacity">
                <Plus size={14} /> New template
              </button>
            </div>
          ) : (
            <>
            <TableShell minWidth={860}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th>Name</Th><Th align="center">Category</Th><Th align="center">Language</Th>
                  <Th align="center">Status</Th><Th align="right">Action</Th>
                </tr>
              </thead>
              <tbody>
                {pLibrary.pageRows.map((t) => {
                  const rowStatus = (t.status || 'DRAFT').toUpperCase();
                  const editable = EDITABLE_STATUSES.includes(rowStatus);
                  return (
                    <tr key={t._id} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors align-top">
                      <Td>
                        <div className="font-bold font-mono text-[12.5px] break-all">{t.name}</div>
                        <div className="text-[11px] text-[var(--text-muted)] mt-0.5 max-w-[320px] truncate" title={t.body || ''}>
                          {t.body || (rowStatus === 'DRAFT' ? 'No body yet' : '—')}
                        </div>
                        {rowStatus === 'REJECTED' && t.rejected_reason && (
                          <div className="text-[11px] text-[var(--accent-red)] mt-1 max-w-[320px]">{t.rejected_reason}</div>
                        )}
                        {t.last_submit_error && rowStatus !== 'REJECTED' && (
                          <div className="text-[11px] text-[var(--accent-orange)] mt-1 max-w-[320px]">
                            Last submit failed: {t.last_submit_error}
                          </div>
                        )}
                      </Td>
                      <Td align="center"><Pill label={t.meta_category || t.category || '—'} tone="indigo" /></Td>
                      <Td align="center" className="font-medium text-[var(--text-muted)]">{t.language}</Td>
                      <Td align="center"><Pill label={rowStatus} tone={STATUS_TONE[rowStatus] || 'muted'} /></Td>
                      <Td align="right">
                        <div className="inline-flex items-center gap-1.5">
                          <button type="button" onClick={() => openLibrary(t)}
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                            {editable ? <><Pencil size={12} /> Edit</> : <><Eye size={12} /> View</>}
                          </button>
                          <button type="button" onClick={() => setDeleteTarget(t)} title="Delete template"
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-red)] bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] hover:opacity-90 transition-opacity">
                            <Trash2 size={12} /> Delete
                          </button>
                        </div>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </TableShell>
            <Pager {...pLibrary} label="templates" />
            </>
          )}
        </Section>
      )}

      {/* ── The notification wiring: which approved template fires for which activity × side ×
             event. ── */}
      <Section
        title={isWhatsapp ? 'WhatsApp Notifications' : 'Mail Templates'}
        subtitle={templates.length ? `${templates.length} notification${templates.length === 1 ? '' : 's'}` : 'Nothing yet'}
        icon={Filter}
        action={(
          <button type="button" onClick={() => openWiring()}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold shadow-sm hover:opacity-90 transition-opacity">
            <Plus size={13} /> {isWhatsapp ? 'Add Notification' : 'Add Template'}
          </button>
        )}>
        {templates.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
              {isWhatsapp ? <MessageCircle size={20} /> : <Mail size={20} />}
            </span>
            <p className="text-[13px] font-bold text-[var(--text-main)]">No notifications found</p>
            <p className="text-[12px] text-[var(--text-muted)] max-w-md">
              {filter
                ? 'None match this filter.'
                : isWhatsapp
                  ? 'Wire an approved template above to an activity, side and event to start sending.'
                  : 'Add your first mail template to get started.'}
            </p>
            <button onClick={() => openWiring()}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:opacity-90 transition-opacity">
              <Plus size={14} /> {isWhatsapp ? 'Add Notification' : 'Add Template'}
            </button>
          </div>
        ) : (
          <>
          <TableShell minWidth={920}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th>Activity</Th><Th align="center">Side</Th><Th align="center">Event</Th>
                <Th>{channel === 'whatsapp' ? 'Meta Template' : 'Subject'}</Th><Th align="center">Active</Th><Th align="right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {pTemplates.pageRows.map((t, i) => {
                const isActive = t.active !== false;
                return (
                  <tr key={t._id || i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors"
                    style={{ opacity: isActive ? 1 : 0.6 }}>
                    <Td className="font-bold whitespace-nowrap">{t.activity || '*'}</Td>
                    <Td align="center"><Pill label={t.side || '—'} tone={SIDE_TONE[t.side] || 'muted'} /></Td>
                    <Td align="center"><Pill label={t.event || '—'} tone="indigo" /></Td>
                    <Td className="font-medium max-w-[360px] truncate" title={(channel === 'whatsapp' ? (t.meta_template_name || t.name) : t.subject) || ''}>{(channel === 'whatsapp' ? (t.meta_template_name || t.name) : t.subject) || '—'}</Td>
                    <Td align="center">
                      <div className="flex justify-center">
                        <StatusToggle
                          active={isActive}
                          disabled={!admin}
                          onRequest={() => setConfirmTarget(t)}
                        />
                      </div>
                    </Td>
                    <Td align="right">
                      <button type="button" onClick={() => openWiring(t)}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                        <Pencil size={12} /> Edit
                      </button>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </TableShell>
          <Pager {...pTemplates} label="templates" />
          </>
        )}
      </Section>

      {/* Two different editors: the library authors a template definition and talks to Meta,
          the other two tabs wire an existing template to an event. */}
      <AnimatePresence>
        {modalOpen && (modalKind === 'library' ? (
          <TemplateComposer
            key={editing?._id || 'new-library'}
            editing={editing}
            api={COMPOSER_API}
            onClose={() => { setModalOpen(false); setEditing(null); }}
            onSaved={onComposerSaved}
          />
        ) : (
          <TemplateModal
            key={editing?._id || (preset ? `new-${preset.event}` : 'new')}
            editing={editing}
            preset={preset}
            activityOptions={formActivityOptions}
            channel={channel}
            variableFields={variableFields}
            approvedTemplates={approved}
            onClose={() => { setModalOpen(false); setEditing(null); }}
            onSubmit={handleSubmit}
          />
        ))}
      </AnimatePresence>

      {/* Status changes always go through a confirmation step, in both directions. */}
      <AnimatePresence>
        {confirmTarget && (
          <ConfirmStatusModal
            key={confirmTarget._id}
            target={confirmTarget}
            channelLabel={channelLabel}
            busy={statusSaving}
            onCancel={() => setConfirmTarget(null)}
            onConfirm={applyStatusChange}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {deleteTarget && (
          <ConfirmDeleteModal key={deleteTarget._id} target={deleteTarget} busy={deleting}
            onCancel={() => setDeleteTarget(null)} onConfirm={handleDelete} />
        )}
      </AnimatePresence>
    </div>
  );
};

export default MailTemplateAdmin;
