import React, { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
  MessageCircle, RefreshCw, AlertTriangle, Save, Send, X, User, Link2, UserCog,
  Plus, Trash2, Braces, CalendarClock,
} from 'lucide-react';
import { errText } from '../../leadership/leadershipUtils';

/* ─────────────────────────────────────────────────────────────
   Leadership ▸ write the WhatsApp invitation.

   Deliberately small. A feedback invitation has ONE shape, so the only things asked for are
   the things that vary: what Meta will call it, what language it is in, and what it says.
   Category (UTILITY), variable style, header, footer and buttons are fixed by the backend —
   offering them would be asking questions with a single right answer.

   Meta needs a sample value for every variable before it will review a template. There is
   exactly one sensible sample for each of ours, so those are generated too.
   ───────────────────────────────────────────────────────────── */

const MotionDiv = motion.div;

// What the backend fills at send time. NAMED, not numbered, so any of them can be left
// out and rearranging the sentence cannot silently swap two values.
//
// `link` is minted per invitation — a fresh single-use URL for one giver — which is why
// there is nowhere to type one.
const VARIABLES = [
  { name: 'giver_name', icon: User, label: "the giver's name", sample: 'Asha Rao' },
  { name: 'feedback_link', icon: Link2, label: 'their unique feedback link', sample: 'a link only they can use' },
  {
    name: 'opens_at',
    icon: CalendarClock,
    label: 'when the window opens',
    sample: '12 Sep 2026, 10:00 AM IST',
  },
  {
    name: 'closes_at',
    icon: CalendarClock,
    label: 'the last date to give feedback',
    sample: '30 Sep 2026, 6:00 PM IST',
  },
  {
    name: 'leader_name',
    icon: UserCog,
    label: 'the leader they are rating',
    sample: 'Rahul Mehta',
    // The one variable with a cost: it puts the rated leader's name on a phone screen
    // anyone nearby can read, which works against what the module promises.
    warn: 'Names the leader in the message — anyone glancing at that phone sees who is being rated.',
  },
];

const STARTER = 'Hi {{giver_name}}, you have been asked to give confidential leadership '
  + 'feedback. Your answers are anonymous. Open your form here: {{feedback_link}} — the '
  + 'link is yours alone.';

// Meta's rule, checked here so a bad name is obvious as it is typed rather than after a
// review that takes hours.
const VALID_NAME = /^[a-z][a-z0-9_]*$/;

const inputCls =
  'w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-semibold outline-none focus:border-[var(--accent-indigo)] transition-colors disabled:opacity-60';

/** What the message looks like with real-ish values in place — the system ones sampled,
    the custom ones exactly as they will send, since those are the same every time. */
const preview = (body, custom) => {
  const withSystem = VARIABLES.reduce(
    (text, v) => text.split(`{{${v.name}}}`).join(v.sample), body || '');
  return (custom || []).reduce(
    (text, v) => (v.name ? text.split(`{{${v.name}}}`).join(v.value || `{{${v.name}}}`) : text),
    withSystem);
};

const LeadershipTemplateModal = ({ template, api, onClose, onSaved }) => {
  // The suggestion is this company's alone. Meta template names live on one shared
  // WhatsApp Business Account, so the obvious name is taken by whoever writes first —
  // starting from a company-specific one is what stops the second client hitting that.
  const [name, setName] = useState(
    template?.meta_template_name || template?.suggested_name || '');
  const [language, setLanguage] = useState(template?.language || 'en');
  // What we ASK Meta to file this as. Meta runs its own classifier over the content and
  // its answer wins — `meta_category` below is that answer, shown when the two differ.
  const [category, setCategory] = useState(template?.category || 'UTILITY');
  const [body, setBody] = useState(template?.body || '');
  const [custom, setCustom] = useState(template?.variables || []);
  const [busy, setBusy] = useState('');
  const [errors, setErrors] = useState([]);
  const [err, setErr] = useState('');
  const bodyRef = useRef(null);

  // An APPROVED template is read-only: Meta reviewed this exact wording, so changing it
  // here would leave the two out of step. Editing means resubmitting, which the page does
  // by sending it back to Draft.
  const locked = (template?.status || 'DRAFT').toUpperCase() === 'PENDING';

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !busy) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, onClose]);

  const doc = () => ({
    name: name.trim(), language: language.trim() || 'en', category, body,
    variables: custom.filter((v) => v.name.trim()),
  });

  const setVar = (i, key, value) => {
    setCustom(custom.map((v, idx) => (idx === i ? { ...v, [key]: value } : v)));
    setErrors([]);
    setErr('');
  };
  const addVar = () => setCustom([...custom, { name: '', value: '' }]);
  const dropVar = (i) => setCustom(custom.filter((_, idx) => idx !== i));

  /** Insert a variable where the cursor is, rather than making people type braces. */
  const insert = (variable) => {
    const slot = `{{${variable}}}`;
    const el = bodyRef.current;
    const at = el ? el.selectionStart : body.length;
    setBody(`${body.slice(0, at)}${slot}${body.slice(el ? el.selectionEnd : body.length)}`);
    setErrors([]);
    setErr('');
    // Put the caret after what was just inserted, once React has re-rendered.
    requestAnimationFrame(() => {
      if (!el) return;
      el.focus();
      el.setSelectionRange(at + slot.length, at + slot.length);
    });
  };

  const run = async (kind, fn) => {
    setBusy(kind);
    setErr('');
    setErrors([]);
    try {
      return await fn();
    } catch (e) {
      // Meta's rules come back as one detail string; show it where it can be acted on.
      setErr(errText(e, 'That did not work.'));
      return null;
    } finally {
      setBusy('');
    }
  };

  const check = () => run('check', async () => {
    const { data } = await api.check(doc());
    setErrors(data?.errors || []);
    if (!data?.errors?.length) setErr('');
    return data;
  });

  const save = () => run('save', async () => {
    await api.save(doc());
    onSaved?.();
  });

  const submit = () => run('submit', async () => {
    await api.save(doc());          // always submit what is on screen
    await api.submit();
    onSaved?.();
  });

  const ready = name.trim() && body.trim();

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={busy ? undefined : onClose} />
      <MotionDiv role="dialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-xl rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden max-h-[90vh] flex flex-col">

        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)] shrink-0">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shrink-0">
              <MessageCircle size={16} />
            </span>
            <div className="min-w-0">
              <h3 className="text-[15px] font-extrabold tracking-tight">Feedback invitation</h3>
              <span className="block text-[10.5px] font-bold text-[var(--text-muted)]">
                Meta reviews this before it can be sent
              </span>
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={!!busy}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4 overflow-y-auto">
          {locked && (
            <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-yellow)]">
              <AlertTriangle size={14} className="mt-[1px] shrink-0" />
              <span>This template is with Meta for review. Wait for the verdict before changing it.</span>
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <label className="flex flex-col gap-1.5 sm:col-span-2">
              <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">
                Name
              </span>
              <input value={name} disabled={!!busy || locked} autoFocus
                onChange={(e) => setName(e.target.value)}
                placeholder={template?.suggested_name || 'leadership_feedback_invite'}
                className={`${inputCls} font-mono`} />
              <span className="text-[10.5px] font-semibold text-[var(--text-muted)]">
                Lowercase letters, numbers and underscores. This name identifies the
                template at Meta and must differ from every other company's.
              </span>
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">
                Language
              </span>
              <input value={language} disabled={!!busy || locked}
                onChange={(e) => setLanguage(e.target.value)} placeholder="en" className={inputCls} />
            </label>
          </div>

          {/* Category decides how Meta PACES the message and whether it reaches someone who
              never opted in — a utility notice goes through, a marketing one is throttled
              and gated. It is the field that most affects whether an invitation arrives, so
              it is chosen rather than assumed. */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <label className="flex flex-col gap-1.5 sm:col-span-2">
              <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">
                Category
              </span>
              <select value={category} disabled={!!busy || locked}
                onChange={(e) => setCategory(e.target.value)} className={inputCls}>
                <option value="UTILITY">Utility — a notice about a process they are part of</option>
                <option value="MARKETING">Marketing — promotional, paced and opt-in gated</option>
              </select>
              <span className="text-[10.5px] font-semibold text-[var(--text-muted)]">
                A feedback invitation is normally Utility. Meta reviews the wording and may
                file it differently — its decision is final.
              </span>
            </label>

            {/* Only shown when Meta disagreed. This is the difference that explains an
                invitation Meta accepted and never delivered. */}
            {template?.meta_category && template.meta_category !== category && (
              <div className="flex flex-col justify-center gap-1 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3 py-2.5">
                <span className="inline-flex items-center gap-1.5 text-[11px] font-black uppercase tracking-wide text-[var(--accent-yellow)]">
                  <AlertTriangle size={12} /> Meta filed it as
                </span>
                <span className="text-[13px] font-extrabold text-[var(--accent-yellow)]">
                  {template.meta_category}
                </span>
                <span className="text-[10.5px] font-semibold text-[var(--accent-yellow)]">
                  An approved template&rsquo;s category cannot be changed. To move it, submit
                  a new template under a different name.
                </span>
              </div>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">
                Message
              </span>
              {!body && (
                <button type="button" onClick={() => setBody(STARTER)} disabled={!!busy || locked}
                  className="px-2.5 py-1 rounded-lg text-[11px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                  Use example
                </button>
              )}
            </div>
            <textarea ref={bodyRef} value={body} rows={5} disabled={!!busy || locked}
              onChange={(e) => { setBody(e.target.value); setErrors([]); setErr(''); }}
              placeholder="Write the message. Click a variable below to drop it in."
              className={`${inputCls} resize-y leading-relaxed`} />
            {/* The variables live here rather than as chips above the box: the list has to
                say what each one means anyway, and a row that explains AND inserts is one
                thing to read instead of two that repeat each other. */}
            <div className="flex flex-col gap-1 pt-0.5">
              {VARIABLES.map((v) => (
                <button key={v.name} type="button" onClick={() => insert(v.name)}
                  disabled={!!busy || locked} title={`Insert {{${v.name}}}`}
                  className="group flex items-start gap-2 text-left rounded-lg px-1.5 py-1 -mx-1.5 hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50 disabled:hover:bg-transparent">
                  <v.icon size={12}
                    className={`mt-[2px] shrink-0 ${v.warn ? 'text-[var(--accent-yellow)]' : 'text-[var(--accent-indigo)]'}`} />
                  <span className="text-[10.5px] font-semibold text-[var(--text-muted)]">
                    <span className={`font-mono ${v.warn ? 'text-[var(--accent-yellow)]' : 'text-[var(--accent-indigo)]'}`}>
                      {`{{${v.name}}}`}
                    </span>
                    {' — '}{v.label}
                    {v.warn && <span className="text-[var(--accent-yellow)]"> · {v.warn}</span>}
                  </span>
                </button>
              ))}
              <span className="text-[10.5px] font-semibold text-[var(--text-muted)] mt-0.5">
                Click one to drop it in. Meta will not accept a message that starts or ends
                with a variable, so keep some words around them.
              </span>
            </div>
          </div>


          {/* Custom variables are the same words for every recipient, which is exactly why
              the value is typed once here rather than per send. A system variable cannot be
              redefined — {{feedback_link}} in particular is minted per invitation and has
              nowhere to be entered. */}
          <div className="rounded-xl border border-[var(--border)] px-3.5 py-3">
            <div className="flex items-center justify-between gap-2 mb-2">
              <span className="text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)]">
                Your own variables
              </span>
              <button type="button" onClick={addVar} disabled={!!busy || locked}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity disabled:opacity-50">
                <Plus size={11} /> Add variable
              </button>
            </div>

            {custom.length === 0 ? (
              <p className="text-[11px] font-semibold text-[var(--text-muted)]">
                None yet. Add one for anything the message needs that the system does not
                already know — a deadline, a contact name, a round number.
              </p>
            ) : (
              <div className="space-y-2">
                {custom.map((v, i) => {
                  const badName = v.name.trim() && !VALID_NAME.test(v.name.trim());
                  const clashes = VARIABLES.some((sv) => sv.name === v.name.trim());
                  return (
                    <div key={i} className="flex items-start gap-2">
                      <div className="flex-1 min-w-0">
                        <input value={v.name} disabled={!!busy || locked}
                          onChange={(e) => setVar(i, 'name', e.target.value)}
                          placeholder="deadline"
                          className={`${inputCls} font-mono ${badName || clashes ? 'border-[var(--accent-red)]' : ''}`} />
                        {(badName || clashes) && (
                          <span className="block text-[10.5px] font-semibold text-[var(--accent-red)] mt-1">
                            {clashes ? 'That is a system variable — pick another name.'
                              : 'Lowercase letters, numbers and underscores, starting with a letter.'}
                          </span>
                        )}
                      </div>
                      <input value={v.value} disabled={!!busy || locked}
                        onChange={(e) => setVar(i, 'value', e.target.value)}
                        placeholder="30 September" className={`${inputCls} flex-1`} />
                      <button type="button" onClick={() => insert(v.name.trim())}
                        disabled={!!busy || locked || !v.name.trim() || badName || clashes}
                        title={`Insert {{${v.name.trim()}}} into the message`}
                        className="mt-1 w-8 h-8 shrink-0 rounded-lg flex items-center justify-center text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] transition-colors disabled:opacity-40">
                        <Braces size={14} />
                      </button>
                      <button type="button" onClick={() => dropVar(i)} disabled={!!busy || locked}
                        title="Remove this variable"
                        className="mt-1 w-8 h-8 shrink-0 rounded-lg flex items-center justify-center text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] transition-colors disabled:opacity-50">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  );
                })}
                <p className="text-[10.5px] font-semibold text-[var(--text-muted)]">
                  Name on the left, the words it sends on the right.
                </p>
              </div>
            )}
          </div>

          {/* Read the message as the recipient will, with the samples filled in. */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-3">
            <span className="block text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)] mb-1.5">
              Preview
            </span>
            <p className="text-[12.5px] font-medium whitespace-pre-wrap break-words">
              {body ? preview(body, custom) : 'Your message will appear here.'}
            </p>
          </div>

          {!!errors.length && (
            <div className="rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3.5 py-2.5">
              <span className="flex items-center gap-1.5 text-[12px] font-bold text-[var(--accent-yellow)] mb-1">
                <AlertTriangle size={14} /> Meta would reject this
              </span>
              <ul className="list-disc pl-5 space-y-0.5">
                {errors.map((e) => (
                  <li key={e} className="text-[11.5px] font-semibold text-[var(--accent-yellow)]">{e}</li>
                ))}
              </ul>
            </div>
          )}

          {err && (
            <div className="flex items-start gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} className="mt-[1px] shrink-0" /> {err}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 flex-wrap px-5 py-4 border-t border-[var(--border)] shrink-0">
          <button type="button" onClick={check} disabled={!!busy || !ready || locked}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            {busy === 'check' ? <RefreshCw size={14} className="animate-spin" /> : <AlertTriangle size={14} />}
            Check
          </button>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose} disabled={!!busy}
              className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
              Cancel
            </button>
            <button type="button" onClick={save} disabled={!!busy || !ready || locked}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
              {busy === 'save' ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />}
              Save draft
            </button>
            <button type="button" onClick={submit} disabled={!!busy || !ready || locked}
              title="Saves, then sends it to Meta for review"
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
              {busy === 'submit' ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
              {busy === 'submit' ? 'Sending…' : 'Send for review'}
            </button>
          </div>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

export default LeadershipTemplateModal;
