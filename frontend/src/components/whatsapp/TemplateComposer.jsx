import React, { useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
  AlertTriangle, Bold, Braces, Check, CheckCircle2, ChevronDown, Code2, ExternalLink, Info,
  Italic, Pencil, Phone, Plus, RefreshCw, Reply, Save, Send, Smartphone, Smile, Strikethrough, X,
} from 'lucide-react';

import WhatsappPreview from './WhatsappPreview';
import {
  BUTTON_TYPES, CATEGORIES, EDITABLE_STATUSES, HEADER_FORMATS, LANGUAGES, LIMITS,
  MEDIA_HEADERS, VARIABLE_STYLES, extractVariables, nextVariableToken, orderedVariables,
  seedTemplate, validateTemplate,
} from './constants';

/* ─────────────────────────────────────────────────────────────
   New / Edit WhatsApp template.

   Shared by every module that wires WhatsApp notifications — TPMS ▸ Templates and Task
   Management ▸ Templates both compose into the same WhatsApp Business Account library. The
   four Graph-API calls arrive through the `api` prop rather than being imported, which is what
   lets one composer serve both modules' endpoints.

   Authors a template definition and submits it to Meta for review. Submitting is
   irreversible — Meta assigns the template an id the moment it is created — so the composer
   deliberately gates the submit button behind "Check payload": you see the exact JSON that
   will be sent before it goes.

   Editing is only offered while the template is DRAFT or REJECTED. Once Meta owns the
   definition (PENDING/APPROVED) the fields are read-only, because a local edit would leave the
   CRM describing something different from what actually gets delivered.
   ───────────────────────────────────────────────────────────── */

const MotionDiv = motion.div;

const errMsg = (e, fallback) => e?.response?.data?.detail || fallback;

/* Width is deliberately NOT baked in here. Tailwind resolves conflicting utilities by
   stylesheet order, not by the order they appear in the class string, so `${inputCls} w-36`
   loses to a `w-full` baked into the base and the field silently spans the whole row. */
const inputBase =
  'px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] transition-colors disabled:opacity-60';
const inputCls = `w-full ${inputBase}`;
const labelCls = 'text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]';
const hintCls = 'text-[11px] text-[var(--text-muted)] leading-relaxed mt-1';

const Field = ({ label, required, hint, counter, children }) => (
  <div className="flex flex-col gap-1.5">
    <span className={`${labelCls} flex items-baseline justify-between gap-2`}>
      <span>{label}{required && <span className="text-[var(--accent-red)]"> *</span>}</span>
      {counter && <span className="font-medium tabular-nums normal-case tracking-normal">{counter}</span>}
    </span>
    {children}
    {hint && <p className={hintCls}>{hint}</p>}
  </div>
);

/**
 * A titled group of fields. The composer is long enough that an undifferentiated scroll is
 * hard to hold in your head — the headings give it structure and a place to stop.
 */
const FormSection = ({ title, step, hint, children }) => (
  <section className="space-y-4">
    <div className="flex items-baseline gap-2 pb-1.5 border-b border-[var(--border)]">
      <span className="w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-black shrink-0 self-center"
        style={{ background: 'var(--accent-indigo-bg)', color: 'var(--accent-indigo)' }}>
        {step}
      </span>
      <h4 className="text-[12px] font-extrabold tracking-tight">{title}</h4>
      {hint && <span className="text-[11px] text-[var(--text-muted)] truncate">{hint}</span>}
    </div>
    {children}
  </section>
);

const Select = ({ value, onChange, options, disabled }) => (
  <div className="relative">
    <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}
      className={`${inputCls} appearance-none pr-8 cursor-pointer`}>
      {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
    </select>
    <ChevronDown size={14}
      className="absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none text-[var(--text-muted)]" />
  </div>
);

const EMOJI = ['😀', '🙏', '👍', '🎉', '✅', '⚠️', '📅', '⏰', '📌', '📣', '💡', '🔔',
  '📝', '📊', '🚀', '❤️', '🙌', '👏', '✨', '🔥'];

/** Formatting toolbar under the body box — WhatsApp's own markers, applied to the selection. */
const BodyToolbar = ({ textareaId, value, onChange, disabled, onAddVariable }) => {
  const [emojiOpen, setEmojiOpen] = useState(false);

  /** Wrap the current selection in `marker`, or drop the markers at the caret when nothing is
   *  selected so the caret lands between them ready to type. */
  const wrap = (marker) => {
    const ta = document.getElementById(textareaId);
    if (!ta) return;
    const start = ta.selectionStart ?? value.length;
    const end = ta.selectionEnd ?? start;
    const selected = value.slice(start, end);
    onChange(`${value.slice(0, start)}${marker}${selected}${marker}${value.slice(end)}`);
    requestAnimationFrame(() => {
      ta.focus();
      // Selection wrapped → caret after the closing marker; nothing selected → between them.
      const caret = start + marker.length + selected.length + (selected ? marker.length : 0);
      ta.setSelectionRange(caret, caret);
    });
  };

  const insert = (text) => {
    const ta = document.getElementById(textareaId);
    const start = ta?.selectionStart ?? value.length;
    const end = ta?.selectionEnd ?? start;
    onChange(`${value.slice(0, start)}${text}${value.slice(end)}`);
    requestAnimationFrame(() => {
      ta?.focus();
      const caret = start + text.length;
      ta?.setSelectionRange(caret, caret);
    });
  };

  const btn = 'w-7 h-7 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-main)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed';

  return (
    <div className="flex flex-wrap items-center gap-1 px-2 py-1.5 border-t border-[var(--border)]">
      <div className="relative">
        <button type="button" className={btn} disabled={disabled} title="Emoji"
          onClick={() => setEmojiOpen((o) => !o)}>
          <Smile size={15} />
        </button>
        {emojiOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setEmojiOpen(false)} />
            <div className="absolute bottom-9 left-0 z-20 grid grid-cols-5 gap-0.5 p-2 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] shadow-lg">
              {EMOJI.map((e) => (
                <button key={e} type="button" className="w-7 h-7 text-[15px] rounded-md hover:bg-[var(--input-bg)]"
                  onClick={() => { insert(e); setEmojiOpen(false); }}>
                  {e}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
      <button type="button" className={btn} disabled={disabled} title="Bold — *text*" onClick={() => wrap('*')}><Bold size={14} /></button>
      <button type="button" className={btn} disabled={disabled} title="Italic — _text_" onClick={() => wrap('_')}><Italic size={14} /></button>
      <button type="button" className={btn} disabled={disabled} title="Strikethrough — ~text~" onClick={() => wrap('~')}><Strikethrough size={14} /></button>
      <button type="button" className={btn} disabled={disabled} title="Monospace — ```text```" onClick={() => wrap('```')}><Code2 size={14} /></button>
      <span className="w-px h-4 mx-1" style={{ background: 'var(--border)' }} />
      <button type="button" disabled={disabled} onClick={onAddVariable}
        className="inline-flex items-center gap-1 px-2 h-7 rounded-md text-[11.5px] font-bold text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] transition-colors disabled:opacity-40">
        <Plus size={12} /> Add variable
      </button>
      <span className="ml-auto text-[var(--text-muted)]"
        title="WhatsApp formatting: *bold*, _italic_, ~strikethrough~, ```monospace```">
        <Info size={13} />
      </span>
    </div>
  );
};

/* Icons make the three button kinds distinguishable at a glance — they are the same icons the
   preview draws on the bubble, so picking a type shows you what will appear. */
const BUTTON_TYPE_ICON = { QUICK_REPLY: Reply, URL: ExternalLink, PHONE_NUMBER: Phone };

/**
 * One button in the Buttons editor.
 *
 * The type is a segmented control rather than a dropdown: there are exactly three options,
 * they are mutually exclusive, and which one is chosen decides which fields appear below —
 * all of which a dropdown hides behind a click.
 */
const ButtonRow = ({ button, index, disabled, onChange, onRemove }) => {
  const set = (k, v) => onChange({ ...button, [k]: v });
  const urlHasVariable = button.type === 'URL' && extractVariables(button.url).length > 0;
  const overLimit = (button.text || '').length >= LIMITS.buttonText;

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] p-3 space-y-2.5">
      {/* type + remove */}
      <div className="flex items-center gap-2">
        <span className="w-5 h-5 rounded-md flex items-center justify-center text-[10px] font-black shrink-0 tabular-nums"
          style={{ background: 'var(--accent-indigo-bg)', color: 'var(--accent-indigo)' }}>
          {index + 1}
        </span>
        <div className="flex items-center gap-0.5 p-0.5 rounded-lg border border-[var(--input-border)] bg-[var(--bg-card)]">
          {BUTTON_TYPES.map((t) => {
            const Icon = BUTTON_TYPE_ICON[t.id] || Reply;
            const on = button.type === t.id;
            return (
              <button key={t.id} type="button" disabled={disabled}
                onClick={() => set('type', t.id)}
                aria-pressed={on}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11.5px] font-bold transition-colors disabled:opacity-50 ${
                  on ? '' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}
                style={on ? { background: 'var(--accent-indigo)', color: '#fff' } : undefined}>
                <Icon size={12} /> {t.label}
              </button>
            );
          })}
        </div>
        <button type="button" onClick={onRemove} disabled={disabled} title="Remove this button"
          className="ml-auto w-7 h-7 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] transition-colors disabled:opacity-40">
          <X size={14} />
        </button>
      </div>

      {/* label — what the recipient actually taps */}
      <label className="flex flex-col gap-1">
        <span className="flex items-baseline justify-between gap-2 text-[10px] font-bold uppercase tracking-wide text-[var(--text-muted)]">
          <span>Label</span>
          <span className="tabular-nums normal-case tracking-normal font-medium"
            style={overLimit ? { color: 'var(--accent-orange)' } : undefined}>
            {(button.text || '').length}/{LIMITS.buttonText}
          </span>
        </span>
        <input type="text" value={button.text} disabled={disabled} maxLength={LIMITS.buttonText}
          onChange={(e) => set('text', e.target.value)}
          placeholder={button.type === 'URL' ? 'Open form'
            : button.type === 'PHONE_NUMBER' ? 'Call us' : 'Yes, confirmed'}
          className={inputCls} />
      </label>

      {button.type === 'URL' && (
        <div className="space-y-2">
          <label className="flex flex-col gap-1">
            <span className="text-[10px] font-bold uppercase tracking-wide text-[var(--text-muted)]">
              URL
            </span>
            <input type="text" value={button.url} disabled={disabled}
              onChange={(e) => set('url', e.target.value)}
              placeholder="https://example.com/track/{{1}}"
              className={`${inputCls} font-mono text-[12px]`} />
          </label>
          {urlHasVariable && (
            <label className="flex flex-col gap-1">
              <span className="text-[10px] font-bold uppercase tracking-wide text-[var(--text-muted)]">
                Sample full URL
              </span>
              <input type="text" value={button.url_example} disabled={disabled}
                onChange={(e) => set('url_example', e.target.value)}
                placeholder="https://example.com/track/AB12"
                className={`${inputCls} text-[12px]`} />
            </label>
          )}
        </div>
      )}

      {button.type === 'PHONE_NUMBER' && (
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-bold uppercase tracking-wide text-[var(--text-muted)]">
            Phone number
          </span>
          <input type="text" value={button.phone_number} disabled={disabled}
            onChange={(e) => set('phone_number', e.target.value)}
            placeholder="+919876543210" className={`${inputCls} font-mono text-[12px]`} />
        </label>
      )}
    </div>
  );
};

const TemplateComposer = ({ editing, onClose, onSaved, api }) => {
  const [form, setForm] = useState(() => seedTemplate(editing));
  const [payload, setPayload] = useState(null);     // the checked Graph JSON; null = not checked
  const [payloadOpen, setPayloadOpen] = useState(false);
  const [busy, setBusy] = useState('');             // '' | 'check' | 'save' | 'submit' | 'test'
  const [err, setErr] = useState('');
  const [serverErrors, setServerErrors] = useState([]);
  // Test send: the number to try it on, and the outcome.
  const [testOpen, setTestOpen] = useState(false);
  const [testPhone, setTestPhone] = useState('');
  const [testResult, setTestResult] = useState(null);   // {ok, message}
  const bodyId = useRef(`wa-body-${Math.random().toString(36).slice(2)}`).current;

  const status = (editing?.status || 'DRAFT').toUpperCase();
  // A template Meta already owns is shown read-only rather than hidden — being able to read
  // what was submitted is the whole point of keeping the definition.
  const locked = Boolean(editing) && !EDITABLE_STATUSES.includes(status);
  const isAuth = form.category === 'AUTHENTICATION';

  const set = (k, v) => {
    // Any edit invalidates the checked payload — otherwise you could review one payload and
    // submit a different one.
    setPayload(null);
    setServerErrors([]);
    setForm((f) => ({ ...f, [k]: v }));
  };

  const bodyVariables = useMemo(
    () => (isAuth ? [] : orderedVariables(form.body, form.variable_style)),
    [form.body, form.variable_style, isAuth],
  );
  const headerVariables = useMemo(
    () => (form.header_format === 'TEXT' ? extractVariables(form.header_text) : []),
    [form.header_format, form.header_text],
  );
  const localErrors = useMemo(() => validateTemplate(form), [form]);

  const setExample = (key, i, value) => {
    const next = [...(form[key] || [])];
    while (next.length <= i) next.push('');
    next[i] = value;
    set(key, next);
  };

  const setButton = (i, value) => set('buttons', (form.buttons || []).map((b, j) => (j === i ? value : b)));
  const addButton = () => set('buttons', [...(form.buttons || []),
    { type: 'QUICK_REPLY', text: '', url: '', url_example: '', phone_number: '' }]);
  const removeButton = (i) => set('buttons', (form.buttons || []).filter((_, j) => j !== i));

  const addBodyVariable = () => {
    const token = nextVariableToken(form.body, form.variable_style);
    const ta = document.getElementById(bodyId);
    const start = ta?.selectionStart ?? form.body.length;
    const end = ta?.selectionEnd ?? start;
    set('body', `${form.body.slice(0, start)}${token}${form.body.slice(end)}`);
    requestAnimationFrame(() => {
      ta?.focus();
      const caret = start + token.length;
      ta?.setSelectionRange(caret, caret);
    });
  };

  /** Validate against the backend and show the exact Graph payload. Nothing is sent to Meta
   *  and nothing is stored — this only unlocks the submit button. */
  const handleCheck = async () => {
    setErr('');
    setServerErrors([]);
    setBusy('check');
    try {
      const { data } = await api.checkMetaTemplate(form);
      setServerErrors(data.errors || []);
      setPayload(data.valid ? data.payload : null);
      setPayloadOpen(true);
      if (!data.valid) setErr('Fix the problems below, then check the payload again.');
    } catch (e) {
      setErr(errMsg(e, 'Could not check the payload.'));
    } finally {
      setBusy('');
    }
  };

  /** Persist the definition without involving Meta. Returns the row id. */
  const persist = async () => {
    const { data } = await api.saveMetaTemplate({ ...form, _id: editing?._id });
    return data._id || editing?._id;
  };

  const handleSaveDraft = async () => {
    setErr('');
    setBusy('save');
    try {
      await persist();
      onSaved('Draft saved.');
    } catch (e) {
      setErr(errMsg(e, 'Could not save the draft.'));
      setBusy('');
    }
  };

  const handleSubmit = async () => {
    setErr('');
    setBusy('submit');
    try {
      const id = await persist();
      await api.submitMetaTemplate(id);
      onSaved('Submitted to Meta — the template is now pending review.');
    } catch (e) {
      setErr(errMsg(e, 'Meta rejected the submission.'));
      setPayload(null);   // the definition changed server-side or was refused — re-check
      setBusy('');
    }
  };

  /**
   * Try the template on a real phone. The composer's current form is sent, so this works on a
   * draft that has never been saved; `template_id` is passed when there is one so the backend
   * can use the stored status to decide whether a real template send is even allowed.
   */
  const handleTest = async () => {
    setTestResult(null);
    setBusy('test');
    try {
      const { data } = await api.testMetaTemplate({
        phone: testPhone.trim(),
        template_id: editing?._id,
        template: form,
      });
      setTestResult({ ok: true, message: `Sent to ${data.sent_to}. ${data.note || ''}`.trim() });
    } catch (e) {
      setTestResult({ ok: false, message: errMsg(e, 'Could not send the test message.') });
    } finally {
      setBusy('');
    }
  };

  const problems = serverErrors.length ? serverErrors : localErrors;
  const canSubmit = Boolean(payload) && !locked && !busy;
  const isApproved = status === 'APPROVED';

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={busy ? undefined : onClose} />
      <MotionDiv
        role="dialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-5xl rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden max-h-[92vh] flex flex-col">

        {/* ── header ── */}
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-start gap-2.5 min-w-0">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              {editing ? <Pencil size={16} /> : <Plus size={16} />}
            </span>
            <div className="min-w-0">
              <h3 className="text-[15px] font-extrabold tracking-tight">
                {editing ? (locked ? 'WhatsApp template' : 'Edit WhatsApp template') : 'New WhatsApp template'}
              </h3>
              <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
                {locked
                  ? `This template is ${status} at Meta — the definition can no longer be changed.`
                  : 'Check the payload first — submitting sends it to Meta for review and cannot be undone.'}
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={Boolean(busy)}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50 shrink-0">
            <X size={16} />
          </button>
        </div>

        {/* ── body: form + live preview ── */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {editing?.rejected_reason && (
            <div className="mb-4 rounded-xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3.5 py-3">
              <p className="flex items-center gap-1.5 text-[12px] font-bold text-[var(--accent-red)]">
                <AlertTriangle size={14} /> Meta rejected this template
              </p>
              <p className="text-[12px] text-[var(--text-main)] mt-1 leading-relaxed">
                {editing.rejected_reason}
              </p>
              <p className="text-[11.5px] text-[var(--text-muted)] mt-1.5">
                Correct the template below and submit it again — it keeps the same name.
              </p>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px] gap-6">
            {/* ─── left: the definition ─── */}
            <div className="space-y-6 min-w-0">
              <FormSection step="1" title="Basics"
                hint={editing?.meta_template_id ? 'name & language are fixed once Meta has the template' : undefined}>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div className="sm:col-span-2">
                    <Field label="Template name" required
                      hint="Lowercase, numbers and underscores only — Meta rejects anything else.">
                      <input type="text" value={form.name} disabled={locked || Boolean(editing?.meta_template_id)}
                        onChange={(e) => set('name', e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_'))}
                        placeholder="tpms_schedule_staff" className={`${inputCls} font-mono`} autoFocus />
                    </Field>
                  </div>
                  <Field label="Language">
                    <Select value={form.language} disabled={locked || Boolean(editing?.meta_template_id)}
                      onChange={(v) => set('language', v)} options={LANGUAGES} />
                  </Field>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <Field label="Category"
                    hint={CATEGORIES.find((c) => c.id === form.category)?.hint}>
                    <Select value={form.category} disabled={locked}
                      onChange={(v) => set('category', v)} options={CATEGORIES} />
                  </Field>
                  {!isAuth && (
                    <Field label="Type of variable"
                      hint="One style for the whole template — Meta rejects a mix.">
                      <Select value={form.variable_style} disabled={locked}
                        onChange={(v) => set('variable_style', v)} options={VARIABLE_STYLES} />
                    </Field>
                  )}
                </div>
              </FormSection>

              {isAuth ? (
                /* Authentication templates carry no author-written copy — Meta generates the
                   message and the copy-code button; only these two knobs are ours. */
                <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] p-3.5 space-y-3">
                  <p className="text-[11.5px] text-[var(--text-muted)] leading-relaxed">
                    Meta writes the body of an authentication template and adds the copy-code
                    button itself. You only choose the expiry and the security note.
                  </p>
                  <button type="button" disabled={locked}
                    onClick={() => set('add_security_recommendation', !form.add_security_recommendation)}
                    className="flex items-center gap-2 text-[12.5px] font-bold disabled:opacity-60">
                    <span className="w-4 h-4 rounded border flex items-center justify-center"
                      style={{
                        borderColor: form.add_security_recommendation ? 'var(--accent-green)' : 'var(--border)',
                        background: form.add_security_recommendation ? 'var(--accent-green)' : 'transparent',
                      }}>
                      {form.add_security_recommendation && <Check size={11} className="text-white" />}
                    </span>
                    Add Meta&apos;s &ldquo;don&apos;t share this code&rdquo; warning
                  </button>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <Field label="Code expires after (minutes)">
                      <input type="number" min={1} max={90} value={form.code_expiration_minutes} disabled={locked}
                        onChange={(e) => set('code_expiration_minutes', e.target.value)}
                        placeholder="10" className={inputCls} />
                    </Field>
                    <Field label="Copy-code button label">
                      <input type="text" value={form.buttons?.[0]?.text || ''} disabled={locked}
                        onChange={(e) => set('buttons', [{ type: 'QUICK_REPLY', text: e.target.value }])}
                        placeholder="Copy code" className={inputCls} />
                    </Field>
                  </div>
                </div>
              ) : (
                <>
                  <FormSection step="2" title="Content" hint="what the recipient reads">
                  {/* ── header ── */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <Field label="Header · optional">
                      <Select value={form.header_format} disabled={locked}
                        onChange={(v) => set('header_format', v)} options={HEADER_FORMATS} />
                    </Field>
                    {form.header_format === 'TEXT' && (
                      <Field label="Header text"
                        counter={`${(form.header_text || '').length}/${LIMITS.header}`}>
                        <input type="text" value={form.header_text} disabled={locked} maxLength={LIMITS.header}
                          onChange={(e) => set('header_text', e.target.value)}
                          placeholder="Reminder for {{1}}" className={inputCls} />
                      </Field>
                    )}
                    {MEDIA_HEADERS.includes(form.header_format) && (
                      <Field label="Sample file URL" required
                        hint="Meta reviews a sample of the media. Must be publicly reachable; we upload it on submit.">
                        <input type="text" value={form.header_media_url} disabled={locked}
                          onChange={(e) => set('header_media_url', e.target.value)}
                          placeholder="https://…/sample.jpg" className={`${inputCls} text-[12px]`} />
                      </Field>
                    )}
                  </div>
                  {form.header_format === 'TEXT' && headerVariables.length > 0 && (
                    <Field label="Header variable sample">
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] font-black text-[var(--accent-indigo)] font-mono shrink-0">
                          {`{{${headerVariables[0]}}}`}
                        </span>
                        {/* Not disabled by `locked` — see the Sample values block below. */}
                        <input type="text" value={(form.header_examples || [])[0] || ''}
                          onChange={(e) => setExample('header_examples', 0, e.target.value)}
                          placeholder="Sample value" className={inputCls} />
                      </div>
                    </Field>
                  )}

                  {/* ── body ── */}
                  <div className="flex flex-col gap-1.5">
                    <span className={labelCls}>Body <span className="text-[var(--accent-red)]">*</span></span>
                    <div className="rounded-lg border border-[var(--input-border)] bg-[var(--input-bg)] overflow-hidden focus-within:border-[var(--accent-indigo)] transition-colors">
                      <div className="relative">
                        <textarea id={bodyId} value={form.body} disabled={locked} rows={6}
                          maxLength={LIMITS.body} onChange={(e) => set('body', e.target.value)}
                          placeholder="Namaste {{1}}, your {{2}} is scheduled for {{3}}."
                          className="w-full bg-transparent px-3 pt-2.5 pb-2 pr-16 text-[13px] leading-relaxed outline-none resize-y disabled:opacity-60" />
                        <span className="absolute top-2.5 right-3 text-[11px] tabular-nums text-[var(--text-muted)] pointer-events-none">
                          {(form.body || '').length}/{LIMITS.body}
                        </span>
                      </div>
                      <BodyToolbar textareaId={bodyId} value={form.body} disabled={locked}
                        onChange={(v) => set('body', v)} onAddVariable={addBodyVariable} />
                    </div>
                    <p className={hintCls}>
                      {form.variable_style === 'numbered'
                        ? 'Numbered variables are filled in order when the message is sent.'
                        : 'Named variables are filled by name when the message is sent.'}
                    </p>
                  </div>

                  {bodyVariables.length > 0 && (
                    <div>
                      <div className="flex items-center gap-1.5 mb-1.5">
                        <Braces size={13} className="text-[var(--accent-indigo)]" />
                        <span className={labelCls}>Sample values</span>
                        <span className="text-[11px] text-[var(--text-muted)]">
                          {locked
                            ? 'stand-in text for the preview and test send'
                            : 'Meta reviews the message with these filled in'}
                        </span>
                      </div>
                      {/* Deliberately editable even when the rest of the template is locked.
                          Once Meta owns the definition these are no longer part of it — they
                          are only what the preview and Send Test Message put in the {{n}}
                          slots, so freezing them would make a test send unusable on exactly
                          the approved templates that can actually be sent. */}
                      <div className="space-y-2">
                        {bodyVariables.map((v, i) => (
                          <div key={v} className="flex items-center gap-2">
                            <span className="text-[11px] font-black text-[var(--accent-indigo)] font-mono shrink-0 min-w-[64px]">
                              {`{{${v}}}`}
                            </span>
                            <input type="text" value={(form.body_examples || [])[i] || ''}
                              onChange={(e) => setExample('body_examples', i, e.target.value)}
                              placeholder="Sample value" className={inputCls} />
                          </div>
                        ))}
                      </div>
                      {locked && (
                        <p className={hintCls}>
                          The template itself is fixed at Meta, but these fill the {'{{n}}'} slots
                          in the preview and in a test message.
                        </p>
                      )}
                    </div>
                  )}

                  {/* ── footer ── */}
                  <Field label="Footer · optional"
                    counter={`${(form.footer || '').length}/${LIMITS.footer}`}>
                    <input type="text" value={form.footer} disabled={locked} maxLength={LIMITS.footer}
                      onChange={(e) => set('footer', e.target.value)}
                      placeholder="Sparsh · reply STOP to opt out" className={inputCls} />
                  </Field>
                  </FormSection>

                  {/* ── buttons ── */}
                  <FormSection step="3" title="Buttons · optional"
                    hint={`up to ${LIMITS.maxButtons}, max ${LIMITS.maxUrlButtons} URL & ${LIMITS.maxPhoneButtons} call`}>
                    {(form.buttons || []).length === 0 ? (
                      <button type="button" onClick={addButton} disabled={locked}
                        className="w-full flex items-center justify-center gap-1.5 px-3 py-3 rounded-lg border border-dashed text-[12px] font-bold text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] transition-colors disabled:opacity-40"
                        style={{ borderColor: 'var(--input-border)' }}>
                        <Plus size={13} /> Add button
                      </button>
                    ) : (
                      <div className="space-y-2">
                        {(form.buttons || []).map((b, i) => (
                          <ButtonRow key={i} button={b} index={i} disabled={locked}
                            onChange={(v) => setButton(i, v)} onRemove={() => removeButton(i)} />
                        ))}
                        <button type="button" onClick={addButton}
                          disabled={locked || (form.buttons || []).length >= LIMITS.maxButtons}
                          className="inline-flex items-center gap-1 text-[11.5px] font-bold text-[var(--accent-indigo)] hover:underline disabled:opacity-40 disabled:no-underline">
                          <Plus size={12} /> Add another button
                        </button>
                      </div>
                    )}
                  </FormSection>
                </>
              )}
            </div>

            {/* ─── right: live preview, pinned so it stays in view while the form scrolls ─── */}
            <div className="lg:sticky lg:top-0 self-start space-y-3">
              <div className="flex items-baseline justify-between gap-2">
                <span className={labelCls}>Preview</span>
                <span className="text-[10.5px] text-[var(--text-muted)]">sample values shown</span>
              </div>

              <WhatsappPreview form={form} bodyVariables={bodyVariables}
                headerVariables={headerVariables}
                caption={`${form.category} · ${form.language}`} />

              {/* What the recipient's phone will do with the parameters, counted rather than
                  described — the quickest way to spot a slot you forgot to fill. */}
              {!isAuth && (
                <div className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2.5 space-y-1.5">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                    Parameters
                  </p>
                  {bodyVariables.length === 0 && headerVariables.length === 0 ? (
                    <p className="text-[11.5px] text-[var(--text-muted)]">
                      None — this template sends the same text every time.
                    </p>
                  ) : (
                    <ul className="text-[11.5px] space-y-0.5">
                      {headerVariables.length > 0 && (
                        <li className="flex items-center justify-between gap-2">
                          <span className="text-[var(--text-muted)]">Header</span>
                          <span className="font-bold tabular-nums">{headerVariables.length}</span>
                        </li>
                      )}
                      <li className="flex items-center justify-between gap-2">
                        <span className="text-[var(--text-muted)]">Body</span>
                        <span className="font-bold tabular-nums">{bodyVariables.length}</span>
                      </li>
                    </ul>
                  )}
                </div>
              )}

              {editing?.meta_template_id && (
                <div className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 space-y-1">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                    Meta template ID
                  </p>
                  <p className="text-[11.5px] font-mono break-all">{editing.meta_template_id}</p>
                </div>
              )}
            </div>
          </div>

          {/* ── problems + checked payload ── */}
          {problems.length > 0 && (
            <div className="mt-4 rounded-xl border border-[var(--accent-orange-border)] bg-[var(--accent-orange-bg)] px-3.5 py-3">
              <p className="flex items-center gap-1.5 text-[12px] font-bold text-[var(--accent-orange)]">
                <AlertTriangle size={14} />
                {problems.length} thing{problems.length === 1 ? '' : 's'} Meta would reject
              </p>
              <ul className="mt-1.5 space-y-1 text-[12px] text-[var(--text-main)] leading-relaxed list-disc pl-5">
                {problems.map((p, i) => <li key={i}>{p}</li>)}
              </ul>
            </div>
          )}

          {payload && (
            <div className="mt-4 rounded-xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] overflow-hidden">
              <button type="button" onClick={() => setPayloadOpen((o) => !o)}
                className="w-full flex items-center justify-between gap-2 px-3.5 py-2.5 text-left">
                <span className="flex items-center gap-1.5 text-[12px] font-bold text-[var(--accent-green)]">
                  <CheckCircle2 size={14} /> Payload checked — this is exactly what Meta receives
                </span>
                <ChevronDown size={14} className={`text-[var(--accent-green)] transition-transform ${payloadOpen ? 'rotate-180' : ''}`} />
              </button>
              {payloadOpen && (
                <pre className="px-3.5 pb-3 text-[11px] font-mono leading-relaxed overflow-x-auto text-[var(--text-main)]">
                  {JSON.stringify(payload, null, 2)}
                </pre>
              )}
            </div>
          )}

          {err && (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2.5 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {err}
            </div>
          )}
        </div>

        {/* ── actions ── */}
        <div className="px-5 py-3 border-t border-[var(--border)] flex flex-wrap items-center gap-2">
          {!locked && (
            <>
              {/* A greyed-out submit with no reason attached is a dead end. This says which of
                  the three states you are in: something to fix, ready to check, ready to go. */}
              <span className="inline-flex items-center gap-1.5 mr-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold"
                style={problems.length
                  ? { background: 'var(--accent-orange-bg)', color: 'var(--accent-orange)' }
                  : payload
                    ? { background: 'var(--accent-green-bg)', color: 'var(--accent-green)' }
                    : { background: 'var(--input-bg)', color: 'var(--text-muted)' }}>
                {problems.length ? <AlertTriangle size={13} /> : payload ? <CheckCircle2 size={13} /> : <Info size={13} />}
                {problems.length
                  ? `${problems.length} to fix`
                  : payload ? 'Ready to submit' : 'Check the payload'}
              </span>

              <button type="button" onClick={handleSaveDraft} disabled={Boolean(busy)}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border border-[var(--border)] text-[13px] font-bold text-[var(--text-main)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                {busy === 'save' ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />}
                Save draft
              </button>
              <button type="button" onClick={handleCheck} disabled={Boolean(busy)}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border border-[var(--border)] text-[13px] font-bold text-[var(--text-main)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                {busy === 'check' ? <RefreshCw size={14} className="animate-spin" /> : <Check size={14} />}
                Check payload
              </button>
              <button type="button" onClick={handleSubmit} disabled={!canSubmit}
                title={payload ? 'Send to Meta for review' : 'Check the payload first'}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
                style={{ background: 'var(--accent-indigo)' }}>
                {busy === 'submit' ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
                Submit for review
              </button>
            </>
          )}

          {/* Send Test Message — try the template on a real handset before (or after) it goes
              to Meta. Available on a draft too; the backend picks the only mode WhatsApp
              permits for the template's current status and says which it used. */}
          <div className="relative">
            <button type="button" onClick={() => setTestOpen((o) => !o)} disabled={Boolean(busy)}
              title="Send this template to a phone number"
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border text-[13px] font-bold transition-colors disabled:opacity-50"
              style={{
                borderColor: 'var(--accent-green-border)',
                background: 'var(--accent-green-bg)',
                color: 'var(--accent-green)',
              }}>
              <Smartphone size={14} /> Send Test Message
            </button>

            {testOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setTestOpen(false)} />
                <div className="absolute bottom-11 left-0 z-20 w-80 p-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] shadow-lg space-y-2">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]">
                    Send this template to
                  </p>
                  <div className="flex items-center gap-1.5">
                    <input type="tel" value={testPhone} autoFocus
                      onChange={(e) => { setTestPhone(e.target.value); setTestResult(null); }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && testPhone.trim() && !busy) { e.preventDefault(); handleTest(); }
                      }}
                      placeholder="9876543210" className={`${inputCls} font-mono`} />
                    <button type="button" onClick={handleTest}
                      disabled={!testPhone.trim() || Boolean(busy)}
                      className="inline-flex items-center justify-center w-9 h-9 shrink-0 rounded-lg text-white shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40"
                      style={{ background: 'var(--accent-green)' }}>
                      {busy === 'test' ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
                    </button>
                  </div>
                  <p className="text-[11px] text-[var(--text-muted)] leading-relaxed">
                    {isApproved
                      ? 'Sent as the real template, filled with your sample values.'
                      : 'Not approved yet — WhatsApp will not deliver an unapproved template, so '
                        + 'the copy goes as a normal message. That only reaches a number within '
                        + '24 hours of it messaging you.'}
                  </p>
                  {testResult && (
                    <p className="flex items-start gap-1.5 text-[11.5px] font-bold leading-relaxed"
                      style={{ color: testResult.ok ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                      {testResult.ok
                        ? <CheckCircle2 size={13} className="mt-0.5 shrink-0" />
                        : <AlertTriangle size={13} className="mt-0.5 shrink-0" />}
                      {testResult.message}
                    </p>
                  )}
                </div>
              </>
            )}
          </div>

          <button type="button" onClick={onClose} disabled={Boolean(busy)}
            className="ml-auto px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            {locked ? 'Close' : 'Cancel'}
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

export default TemplateComposer;