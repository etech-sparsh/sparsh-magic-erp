import React, { useRef, useState } from 'react';
import { AnimatePresence } from 'framer-motion';
import {
  Mail, MessageCircle, Clock, Info, Plus, CheckCircle2, AlertTriangle, Trash2, Send, X, BadgeCheck,
} from 'lucide-react';
import { Button, ConfirmDialog, Field, Modal, ModalFooter, ModalHeader, Notice } from './NtUi';
import { EmailPreview, WhatsAppMessagePreview } from './MessagePreview';
import { errMsg, inputCls, sampleFor } from './ntConfig';

/* ─────────────────────────────────────────────────────────────
   Create / edit one event's template on one channel, with a live preview beside it.

   Saves through /notify-templates, keyed exactly as before (slug "<event>_<channel>", scope,
   company) — so the template saved here is the one the event's own sending code reads.
   Mounted only while open (keyed by the host), so the form seeds cleanly from props.
   ───────────────────────────────────────────────────────────── */

const seedForm = (row, seedFrom) => {
  const src = row || seedFrom || {};
  return {
    subject: src.subject || '',
    body: src.body || '',
    meta_template_name: src.meta_template_name || '',
    meta_lang: src.meta_lang || 'en',
    meta_params: Array.isArray(src.meta_params) ? src.meta_params : [],
    meta_header_params: Array.isArray(src.meta_header_params) ? src.meta_header_params : [],
    // Stored as {index, field}; the form holds just the field, aligned to the template's
    // variable URL buttons. Bare strings are rows written before the index was recorded.
    meta_button_params: Array.isArray(src.meta_button_params)
      ? src.meta_button_params.map((b) => (typeof b === 'string' ? b : b?.field || ''))
      : [],
  };
};

const StepLabel = ({ n, title, hint }) => (
  <div className="flex items-start gap-2.5">
    <span className="w-5 h-5 mt-0.5 rounded-full flex items-center justify-center text-[10.5px] font-black text-white shrink-0"
      style={{ background: 'var(--accent-green)' }}>
      {n}
    </span>
    <div className="min-w-0">
      <p className="text-[13px] font-extrabold leading-tight">{title}</p>
      {hint && <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5 leading-relaxed">{hint}</p>}
    </div>
  </div>
);

/** One blank in the approved message → the detail that fills it. */
const DetailSelect = ({ label, value, onChange, fields }) => (
  <div className="flex items-center gap-2">
    <span className="font-mono text-[11.5px] font-black text-[var(--accent-indigo)] w-24 shrink-0 truncate" title={label}>
      {label}
    </span>
    <select value={value || ''} onChange={(e) => onChange(e.target.value)} className={`${inputCls} flex-1 cursor-pointer`}>
      <option value="">— choose a detail —</option>
      {fields.map((f) => (
        <option key={f} value={f}>
          {f.replace(/_/g, ' ')}{sampleFor(f) ? ` (e.g. ${sampleFor(f)})` : ''}
        </option>
      ))}
    </select>
  </div>
);

const TemplateEditor = ({
  module, trigger, channel, row, seedFrom, scopeLabel, approved, scheduleText,
  canSave, canDelete, canTest, onClose, onSave, onDelete, onTest, onNewMetaTemplate,
}) => {
  const [form, setForm] = useState(() => seedForm(row, seedFrom));
  const [backupOpen, setBackupOpen] = useState(() => {
    const seeded = seedForm(row, seedFrom);
    return !seeded.meta_template_name && !!seeded.body.trim();
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [removing, setRemoving] = useState(false);
  const lastFocus = useRef('body');

  const isWa = channel === 'whatsapp';
  const fields = trigger.variables || module.variables || [];
  const templateOnly = module.send_rule === 'template_only';
  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));

  // `approved` is null when this user cannot read the Meta library — the template name is
  // typed instead, exactly as Settings allowed.
  const manual = approved === null;
  const library = approved || [];
  const selected = library.find((t) => t.name === form.meta_template_name) || null;
  const bodySlots = selected
    ? selected.body_variables || []
    : (form.meta_params || []).map((_, i) => String(i + 1));
  const headerSlots = selected ? selected.header_variables || [] : [];
  const urlButtons = selected ? selected.url_buttons || [] : [];

  /** Adopt a template: keep any mapping that still fits, drop what no longer does, and take the
   *  template's own language so the two can never drift apart. */
  const pickTemplate = (name) => {
    const tpl = library.find((t) => t.name === name);
    setForm((f) => ({
      ...f,
      meta_template_name: name,
      meta_lang: tpl?.language || f.meta_lang,
      meta_params: (tpl?.body_variables || []).map((_, i) => (f.meta_params || [])[i] || ''),
      meta_header_params: (tpl?.header_variables || []).map((_, i) => (f.meta_header_params || [])[i] || ''),
      meta_button_params: (tpl?.url_buttons || []).map((_, i) => (f.meta_button_params || [])[i] || ''),
    }));
  };

  const setSlot = (key, i, value) => set(key, Object.assign([...(form[key] || [])], { [i]: value }));

  /** Insert {{detail}} where the cursor is, in whichever of subject / message was used last. */
  const insertDetail = (field) => {
    const token = `{{${field}}}`;
    const key = lastFocus.current === 'subject' ? 'subject' : 'body';
    const el = document.getElementById(key === 'subject' ? 'nt-subject' : 'nt-body');
    const text = form[key] || '';
    if (!el) { set(key, text + token); return; }
    const start = el.selectionStart ?? text.length;
    const end = el.selectionEnd ?? start;
    set(key, text.slice(0, start) + token + text.slice(end));
    requestAnimationFrame(() => {
      el.focus();
      const pos = start + token.length;
      el.setSelectionRange(pos, pos);
    });
  };

  const submit = async () => {
    setErr('');
    if (!isWa) {
      if (!form.subject.trim()) { setErr('Add a subject line.'); return; }
      if (!form.body.trim()) { setErr('Write the message — an empty email is not sent.'); return; }
    } else {
      if (!form.meta_template_name.trim() && !form.body.trim()) {
        setErr('Choose an approved Meta template.');
        return;
      }
      if (selected && bodySlots.some((_, i) => !(form.meta_params || [])[i])) {
        setErr('Choose a detail for every blank in the template.');
        return;
      }
    }

    const base = { trigger: trigger.slug, channel, name: trigger.label };
    const payload = isWa
      ? {
        ...base,
        body: form.body,
        meta_template_name: form.meta_template_name.trim(),
        meta_lang: (form.meta_lang || 'en').trim() || 'en',
        meta_params: (form.meta_params || []).filter(Boolean),
        meta_header_params: (form.meta_header_params || []).filter(Boolean),
        // Each button's real position in the template, not its position among the variable
        // ones — that is the number Meta substitutes against.
        meta_button_params: selected
          ? urlButtons
            .map((b, i) => ({ index: b.index, field: (form.meta_button_params || [])[i] || '' }))
            .filter((b) => b.field)
          : (row?.meta_button_params || []),
      }
      : { ...base, subject: form.subject.trim(), body: form.body };

    setSaving(true);
    try {
      await onSave(payload);
    } catch (e) {
      setErr(errMsg(e, 'Could not save the template. Please try again.'));
      setSaving(false);
    }
  };

  const remove = async () => {
    setRemoving(true);
    try {
      await onDelete(row);
    } catch (e) {
      setErr(errMsg(e, 'Could not remove the template.'));
      setRemoving(false);
      setConfirmRemove(false);
    }
  };

  // Plain statements of the sending rules that apply to this event on this channel.
  const sendNotes = [];
  if (scheduleText) sendNotes.push(scheduleText);
  if (isWa && templateOnly) sendNotes.push('WhatsApp for this event goes out only while its Email template is on.');
  if (isWa && (module.key === 'delegation' || module.key === 'checklist')) {
    sendNotes.push('WhatsApp is sent for internal (staff) tasks only.');
  }
  if (!isWa && !row && trigger.builtin?.email) sendNotes.push('Until you save this, the standard built-in email is sent.');

  return (
    <>
      <Modal onClose={onClose} busy={saving} width="max-w-5xl">
        <ModalHeader icon={isWa ? MessageCircle : Mail} tone={isWa ? 'green' : 'indigo'}
          title={`${row ? 'Edit' : 'Create'} ${isWa ? 'WhatsApp' : 'email'} template`}
          subtitle={`${module.label} › ${trigger.label} · ${scopeLabel}`}
          onClose={onClose} busy={saving} />

        <div className="flex-1 overflow-y-auto">
          <div className="grid lg:grid-cols-[minmax(0,1fr)_360px]">
            <div className="px-5 py-5 space-y-5 min-w-0">
              {/* When this sends — the first thing on the form, in plain words. */}
              <div className="rounded-xl border px-4 py-3 flex gap-3"
                style={{ background: 'var(--accent-indigo-bg)', borderColor: 'var(--accent-indigo-border)' }}>
                <Clock size={16} className="mt-0.5 shrink-0" style={{ color: 'var(--accent-indigo)' }} />
                <div className="min-w-0 space-y-1">
                  <p className="text-[10.5px] font-black uppercase tracking-widest" style={{ color: 'var(--accent-indigo)' }}>
                    When this sends
                  </p>
                  <p className="text-[12.5px] font-semibold leading-relaxed">{trigger.description}</p>
                  {sendNotes.map((n) => (
                    <p key={n} className="text-[11.5px] text-[var(--text-muted)] leading-relaxed">• {n}</p>
                  ))}
                </div>
              </div>

              {!isWa ? (
                <>
                  <Field label="Subject" required>
                    <input id="nt-subject" type="text" value={form.subject}
                      onFocus={() => { lastFocus.current = 'subject'; }}
                      onChange={(e) => set('subject', e.target.value)}
                      placeholder={`e.g. ${trigger.label}: {{${fields[0] || 'name'}}}`} className={inputCls} />
                  </Field>
                  <Field label="Message" required hint="Plain text or HTML. Click a detail below to add it where the cursor is.">
                    <textarea id="nt-body" value={form.body} rows={12}
                      onFocus={() => { lastFocus.current = 'body'; }}
                      onChange={(e) => set('body', e.target.value)}
                      placeholder="Hello {{name}}, …"
                      className={`${inputCls} font-mono text-[12px] leading-relaxed resize-y`} />
                  </Field>
                  <div>
                    <p className="text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)] mb-1.5">Add a detail</p>
                    <div className="flex flex-wrap gap-1.5">
                      {fields.map((f) => (
                        <button key={f} type="button" onClick={() => insertDetail(f)}
                          title={sampleFor(f) ? `e.g. ${sampleFor(f)}` : undefined}
                          className="text-[11px] font-semibold px-2 py-1 rounded-md border border-[var(--border)] bg-[var(--input-bg)] hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)] transition-colors">
                          {f.replace(/_/g, ' ')}
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className="space-y-2.5">
                    <StepLabel n={1} title="Choose an approved Meta template"
                      hint="Business messages on WhatsApp must use wording Meta has approved." />
                    <div className="sm:pl-7 space-y-2.5">
                      {manual ? (
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                          <div className="sm:col-span-2">
                            <Field label="Meta template name">
                              <input value={form.meta_template_name} onChange={(e) => set('meta_template_name', e.target.value)}
                                placeholder="e.g. task_created_staff" className={`${inputCls} font-mono`} />
                            </Field>
                          </div>
                          <Field label="Language">
                            <input value={form.meta_lang} onChange={(e) => set('meta_lang', e.target.value)}
                              placeholder="en" className={inputCls} />
                          </Field>
                        </div>
                      ) : (
                        <div className="flex flex-col sm:flex-row gap-2">
                          <select value={form.meta_template_name} onChange={(e) => pickTemplate(e.target.value)}
                            className={`${inputCls} font-mono cursor-pointer flex-1`}>
                            <option value="">— select an approved template —</option>
                            {library.map((t) => (
                              <option key={t._id} value={t.name}>{t.name} ({t.language})</option>
                            ))}
                            {/* Approved in WhatsApp Manager before the library existed — kept
                                selectable so an existing notification is never silently unwired. */}
                            {form.meta_template_name && !selected && (
                              <option value={form.meta_template_name}>{form.meta_template_name} (not in library)</option>
                            )}
                          </select>
                          {onNewMetaTemplate && (
                            <Button variant="outline" icon={Plus} onClick={onNewMetaTemplate}>New Meta template</Button>
                          )}
                        </div>
                      )}
                      {!manual && library.length === 0 && (
                        <Notice tone="orange">
                          No approved templates yet. Create one with <b>New Meta template</b> and submit it —
                          it appears here once Meta approves it (usually minutes to a few hours).
                        </Notice>
                      )}
                      {selected && (
                        <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-2.5">
                          <p className="flex items-center gap-1.5 text-[10.5px] font-black uppercase tracking-wide text-[var(--accent-green)] mb-1">
                            <BadgeCheck size={12} /> Approved wording
                          </p>
                          <p className="text-[12.5px] whitespace-pre-wrap break-words">{selected.body}</p>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="space-y-2.5">
                    <StepLabel n={2} title="Fill in the blanks"
                      hint="Pick which detail goes into each numbered blank of the approved message." />
                    <div className="sm:pl-7 space-y-2">
                      {headerSlots.map((v, i) => (
                        <DetailSelect key={`h${v}`} label={`Header {{${v}}}`} fields={fields}
                          value={(form.meta_header_params || [])[i]}
                          onChange={(val) => setSlot('meta_header_params', i, val)} />
                      ))}
                      {manual ? (
                        <>
                          {/* Keyed by position: a blank IS its position in the template. */}
                          {(form.meta_params || []).map((p, i) => (
                            <div key={i} className="flex items-center gap-2">
                              <div className="flex-1 min-w-0">
                                <DetailSelect label={`{{${i + 1}}}`} value={p} fields={fields}
                                  onChange={(val) => setSlot('meta_params', i, val)} />
                              </div>
                              <button type="button" aria-label="Remove blank"
                                onClick={() => set('meta_params', (form.meta_params || []).filter((_, j) => j !== i))}
                                className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--input-bg)] transition-colors">
                                <X size={14} />
                              </button>
                            </div>
                          ))}
                          <Button variant="outline" size="sm" icon={Plus}
                            onClick={() => set('meta_params', [...(form.meta_params || []), ''])}>
                            Add a blank
                          </Button>
                        </>
                      ) : bodySlots.length === 0 ? (
                        <p className="text-[12px] text-[var(--text-muted)] italic">
                          {form.meta_template_name ? 'This template has no blanks to fill.' : 'Choose a template first.'}
                        </p>
                      ) : (
                        bodySlots.map((v, i) => (
                          <DetailSelect key={`b${v}`} label={`{{${v}}}`} fields={fields}
                            value={(form.meta_params || [])[i]}
                            onChange={(val) => setSlot('meta_params', i, val)} />
                        ))
                      )}
                      {urlButtons.map((b, i) => (
                        <DetailSelect key={`u${b.index}`} label={b.text || `Button ${b.index + 1}`} fields={fields}
                          value={(form.meta_button_params || [])[i]}
                          onChange={(val) => setSlot('meta_button_params', i, val)} />
                      ))}
                    </div>
                  </div>

                  <details className="rounded-xl border border-[var(--border)] px-4 py-3" open={backupOpen}
                    onToggle={(e) => setBackupOpen(e.currentTarget.open)}>
                    <summary className="cursor-pointer text-[12.5px] font-bold select-none">
                      Backup text <span className="font-medium text-[var(--text-muted)]">(optional)</span>
                    </summary>
                    <div className="mt-3 space-y-2">
                      <p className="text-[11.5px] text-[var(--text-muted)] leading-relaxed">
                        Used only when no Meta template is chosen. WhatsApp delivers it only if the person
                        has messaged you in the last 24 hours, so it usually does not arrive.
                      </p>
                      <textarea id="nt-body" value={form.body} rows={3}
                        onFocus={() => { lastFocus.current = 'body'; }}
                        onChange={(e) => set('body', e.target.value)}
                        placeholder="Hello {{name}}, …"
                        className={`${inputCls} font-mono text-[12px] leading-relaxed resize-y`} />
                    </div>
                  </details>
                </>
              )}

              {err && <Notice tone="red" icon={AlertTriangle}>{err}</Notice>}
            </div>

            {/* Live preview */}
            <div className="px-5 py-5 border-t lg:border-t-0 lg:border-l border-[var(--border)]" style={{ background: 'var(--input-bg)' }}>
              <div className="lg:sticky lg:top-0 space-y-2.5">
                <p className="text-[10.5px] font-black uppercase tracking-widest text-[var(--text-muted)]">Preview</p>
                {!isWa ? (
                  <EmailPreview subject={form.subject} body={form.body} />
                ) : form.meta_template_name && !selected ? (
                  <Notice tone="orange" icon={Info}>
                    The approved wording of <b className="font-mono">{form.meta_template_name}</b> is held by
                    Meta, so it can&apos;t be previewed here.
                  </Notice>
                ) : (
                  <WhatsAppMessagePreview template={selected} bodyFields={form.meta_params} fallbackBody={form.body} />
                )}
                <p className="text-[11px] text-[var(--text-muted)]">Sample details are shown in place of the real ones.</p>
              </div>
            </div>
          </div>
        </div>

        <ModalFooter>
          {row && canDelete && (
            <Button variant="danger" icon={Trash2} className="mr-auto" disabled={saving}
              onClick={() => setConfirmRemove(true)}>
              Remove
            </Button>
          )}
          {isWa && canTest && row?.meta_template_name && (
            <Button variant="success" icon={Send} disabled={saving} onClick={() => onTest(row)}>Send test</Button>
          )}
          <Button variant="ghost" onClick={onClose} disabled={saving}>Cancel</Button>
          {canSave && (
            <Button icon={CheckCircle2} busy={saving} onClick={submit}>{saving ? 'Saving…' : 'Save template'}</Button>
          )}
        </ModalFooter>
      </Modal>

      <AnimatePresence>
        {confirmRemove && (
          <ConfirmDialog key="remove-template" title="Remove this template?" confirmLabel="Remove" busy={removing}
            body={<>
              <b>{trigger.label}</b> will stop sending this {isWa ? 'WhatsApp message' : 'email'}
              {trigger.builtin?.[channel] ? ' and go back to the standard built-in message' : ''}. The
              event itself keeps working exactly as before.
            </>}
            onCancel={() => setConfirmRemove(false)} onConfirm={remove} />
        )}
      </AnimatePresence>
    </>
  );
};

export default TemplateEditor;
