import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RefreshCw, FileEdit, Pencil, X, ShieldAlert, ListChecks,
  CheckCircle2, PauseCircle, PlayCircle, AlertTriangle, Layers, Star, Plus,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, TableShell, KpiTile,
} from '../../common/dashboardKit';
import { getFormQuestions, createFormQuestion, updateFormQuestion } from '../../../../services/tpmsApi';
import { useAuth } from '../../../../context/AuthContext';
import { isTpmsAdmin } from '../../access';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Review Form Questions (M10) — reword the review-form
   questions / criteria that used to be hard-coded.

   Four forms feed the review flow:
     • accountability / ownership / culture — rating matrices; the
       displayed text lives in `title` (the criterion) + `prompt`.
     • implementation_feedback — a checklist; text in `title` + `desc`.

   Item ids are immutable (they key scoring), so only the TEXT is
   editable here via updateFormQuestion(id, {title?, prompt?, desc?, active?}).
   ───────────────────────────────────────────────────────────── */

// Alias so the animated element is a plain JSX identifier (keeps `motion` counted
// as used by no-unused-vars, which doesn't track `motion.div` member expressions).
const MotionDiv = motion.div;

/** The four review forms + a friendly label / classification. */
const FORM_META = {
  accountability:         { label: 'Accountability',   checklist: false },
  ownership:              { label: 'Ownership',        checklist: false },
  culture:                { label: 'Culture',          checklist: false },
  implementation_feedback:{ label: 'Implementation Feedback', checklist: true },
};

const FORM_ORDER = ['accountability', 'ownership', 'culture', 'implementation_feedback'];

const formLabel = (t) => FORM_META[t]?.label || t || '—';
/** A checklist form edits Title + Desc; a rating form edits Title + Prompt. */
const isChecklist = (q) => (q?.kind
  ? q.kind === 'checklist'
  : FORM_META[q?.form_type]?.checklist === true);

const FILTER_OPTIONS = [
  { id: '', name: 'All Forms' },
  ...FORM_ORDER.map((t) => ({ id: t, name: FORM_META[t].label })),
];

const TONE = {
  green:  { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  orange: { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
  indigo: { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
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

/* Shared field styles for the modal. */
const inputCls =
  'w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] transition-colors';
const labelCls = 'text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]';

const Field = ({ label, hint, children, required }) => (
  <label className="flex flex-col gap-1.5">
    <span className={labelCls}>{label}{required && <span className="text-[var(--accent-red)]"> *</span>}</span>
    {children}
    {hint && <span className="text-[10.5px] text-[var(--text-muted)] font-medium">{hint}</span>}
  </label>
);

/**
 * Edit modal — reword the TEXT of a single question. Item id + form are shown
 * read-only. Rating forms expose Title + Prompt; checklist forms Title + Desc.
 * Mounted only while open (via a keyed parent), so state seeds cleanly on mount.
 */
const QuestionModal = ({ editing, onClose, onSubmit }) => {
  const checklist = isChecklist(editing);
  const [title, setTitle] = useState(editing?.title || '');
  const [prompt, setPrompt] = useState(editing?.prompt || '');
  const [desc, setDesc] = useState(editing?.desc || '');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    if (!title.trim()) { setErr('Title is required.'); return; }
    setSaving(true);
    setErr('');
    try {
      const payload = checklist
        ? { title: title.trim(), desc: desc.trim() }
        : { title: title.trim(), prompt: prompt.trim() };
      await onSubmit(payload);
    } catch (ex) {
      setErr(ex?.response?.data?.detail || 'Failed to save question. Please try again.');
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
        className="relative w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        {/* header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              <Pencil size={16} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Edit Question Text</h3>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={submit} className="px-5 py-4 space-y-4">
          {/* read-only identity — item ids are immutable */}
          <div className="grid grid-cols-2 gap-4">
            <Field label="Form">
              <div className={`${inputCls} bg-[var(--bg-card)] opacity-90 cursor-not-allowed`}>{formLabel(editing?.form_type)}</div>
            </Field>
            <Field label="Item ID" hint="Read-only — item ids are immutable.">
              <div className={`${inputCls} bg-[var(--bg-card)] opacity-90 cursor-not-allowed font-mono`}>{editing?.item_id || '—'}</div>
            </Field>
          </div>

          <Field label="Title" required>
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Meets committed deadlines" className={inputCls} autoFocus />
          </Field>

          {checklist ? (
            <Field label="Description" hint="Supporting text shown under the checklist item.">
              <textarea value={desc} onChange={(e) => setDesc(e.target.value)} rows={3}
                placeholder="Describe what this checklist item covers…" className={`${inputCls} resize-y`} />
            </Field>
          ) : (
            <Field label="Prompt" hint="The rating question shown to reviewers.">
              <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3}
                placeholder="How would you rate this criterion…" className={`${inputCls} resize-y`} />
            </Field>
          )}

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
              {saving ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </form>
      </MotionDiv>
    </MotionDiv>
  );
};

/**
 * Add modal (C9) — create a brand-new criterion/question. Form is chosen from a
 * dropdown; the secondary text field switches between Prompt (rating forms) and
 * Description (the checklist form) based on the selected form's kind. Item id is
 * optional — leave blank to let the backend auto-generate one. Mounted only while
 * open (via a keyed parent), so state seeds cleanly on mount.
 */
const AddQuestionModal = ({ defaultForm, onClose, onSubmit }) => {
  const [formType, setFormType] = useState(
    FORM_META[defaultForm] ? defaultForm : FORM_ORDER[0],
  );
  const [itemId, setItemId] = useState('');
  const [title, setTitle] = useState('');
  const [prompt, setPrompt] = useState('');
  const [desc, setDesc] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const checklist = FORM_META[formType]?.checklist === true;

  const submit = async (e) => {
    e.preventDefault();
    if (!title.trim()) { setErr('Title is required.'); return; }
    setSaving(true);
    setErr('');
    try {
      const payload = {
        form_type: formType,
        title: title.trim(),
        ...(checklist ? { desc: desc.trim() } : { prompt: prompt.trim() }),
      };
      if (itemId.trim()) payload.item_id = itemId.trim();
      await onSubmit(payload);
    } catch (ex) {
      setErr(ex?.response?.data?.detail || 'Failed to add question. Please try again.');
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
        className="relative w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        {/* header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              <Plus size={16} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Add Question</h3>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={submit} className="px-5 py-4 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Form" required>
              <select value={formType} onChange={(e) => setFormType(e.target.value)} className={inputCls}>
                {FORM_ORDER.map((t) => (
                  <option key={t} value={t}>{FORM_META[t].label}</option>
                ))}
              </select>
            </Field>
            <Field label="Item ID" hint="Leave blank to auto-generate.">
              <input type="text" value={itemId} onChange={(e) => setItemId(e.target.value)}
                placeholder="Auto" className={`${inputCls} font-mono`} />
            </Field>
          </div>

          <Field label="Title" required>
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Meets committed deadlines" className={inputCls} autoFocus />
          </Field>

          {checklist ? (
            <Field label="Description" hint="Supporting text shown under the checklist item.">
              <textarea value={desc} onChange={(e) => setDesc(e.target.value)} rows={3}
                placeholder="Describe what this checklist item covers…" className={`${inputCls} resize-y`} />
            </Field>
          ) : (
            <Field label="Prompt" hint="The rating question shown to reviewers.">
              <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3}
                placeholder="How would you rate this criterion…" className={`${inputCls} resize-y`} />
            </Field>
          )}

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
              {saving ? <RefreshCw size={14} className="animate-spin" /> : <Plus size={14} />}
              {saving ? 'Adding…' : 'Add Question'}
            </button>
          </div>
        </form>
      </MotionDiv>
    </MotionDiv>
  );
};

/** One question table (used per form-type group and for the flat single-form view). */
const QuestionTable = ({ rows, busyId, onEdit, onToggle }) => (
  <TableShell minWidth={980}>
    <thead>
      <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
        <Th>Form</Th><Th>Item ID</Th><Th>Title</Th><Th>Prompt / Desc</Th>
        <Th align="center">Active</Th><Th align="right">Actions</Th>
      </tr>
    </thead>
    <tbody>
      {rows.map((q, i) => {
        const isActive = q.active !== false;
        const rowBusy = busyId === q._id;
        const checklist = isChecklist(q);
        const secondary = checklist ? q.desc : q.prompt;
        return (
          <tr key={q._id || i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors"
            style={{ opacity: isActive ? 1 : 0.6 }}>
            <Td>
              <Pill label={formLabel(q.form_type)} tone={checklist ? 'orange' : 'indigo'} />
            </Td>
            <Td className="font-mono text-[11.5px] text-[var(--text-muted)] whitespace-nowrap">{q.item_id || '—'}</Td>
            <Td className="font-bold max-w-[240px]">{q.title || '—'}</Td>
            <Td className="text-[var(--text-muted)] max-w-[320px]">{secondary || '—'}</Td>
            <Td align="center">
              <Pill label={isActive ? 'Active' : 'Inactive'} tone={isActive ? 'green' : 'muted'} />
            </Td>
            <Td align="right">
              <div className="inline-flex items-center gap-1.5 justify-end">
                <button type="button" onClick={() => onEdit(q)}
                  className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                  <Pencil size={12} /> Edit
                </button>
                <button type="button" onClick={() => onToggle(q)} disabled={rowBusy}
                  className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold border transition-opacity hover:opacity-90 disabled:opacity-50"
                  style={{
                    color: isActive ? 'var(--accent-red)' : 'var(--accent-green)',
                    background: isActive ? 'var(--accent-red-bg)' : 'var(--accent-green-bg)',
                    borderColor: isActive ? 'var(--accent-red-border)' : 'var(--accent-green-border)',
                  }}>
                  {rowBusy
                    ? <RefreshCw size={12} className="animate-spin" />
                    : isActive ? <PauseCircle size={12} /> : <PlayCircle size={12} />}
                  {isActive ? 'Deactivate' : 'Activate'}
                </button>
              </div>
            </Td>
          </tr>
        );
      })}
    </tbody>
  </TableShell>
);

const FormQuestionAdmin = () => {
  const { user } = useAuth();
  const admin = isTpmsAdmin(user);

  const [formType, setFormType] = useState(''); // '' = All
  const [questions, setQuestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(null);
  const [adding, setAdding] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getFormQuestions(formType || undefined);
      const list = res?.data?.questions;
      setQuestions(Array.isArray(list) ? list : []);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to load form questions.');
    } finally {
      setLoading(false);
    }
  }, [formType]);

  useEffect(() => { if (admin) load(); }, [admin, load]);

  // Sort by form (canonical order) then by `order`, then item id — so groups read cleanly.
  const sorted = useMemo(() => {
    const rank = (t) => {
      const i = FORM_ORDER.indexOf(t);
      return i === -1 ? FORM_ORDER.length : i;
    };
    return [...questions].sort((a, b) => (
      rank(a.form_type) - rank(b.form_type)
      || (a.order ?? 0) - (b.order ?? 0)
      || String(a.item_id || '').localeCompare(String(b.item_id || ''))
    ));
  }, [questions]);

  // "All" → grouped by form_type; a single filter → one flat group.
  const groups = useMemo(() => {
    const seen = [];
    const map = new Map();
    sorted.forEach((q) => {
      const key = q.form_type || 'unknown';
      if (!map.has(key)) { map.set(key, []); seen.push(key); }
      map.get(key).push(q);
    });
    return seen.map((key) => ({ key, rows: map.get(key) }));
  }, [sorted]);

  const kpis = useMemo(() => {
    const total = questions.length;
    const active = questions.filter((q) => q.active !== false).length;
    const rating = questions.filter((q) => !isChecklist(q)).length;
    return [
      { value: total, label: 'Total Questions', sub: 'Across forms', tone: 'blue', icon: Layers },
      { value: active, label: 'Active', sub: 'Shown to reviewers', tone: active ? 'green' : 'plain', icon: CheckCircle2 },
      { value: total - active, label: 'Inactive', sub: 'Hidden', tone: total - active ? 'yellow' : 'plain', icon: PauseCircle },
      { value: rating, label: 'Rating Criteria', sub: 'Non-checklist', tone: 'blue', icon: Star },
    ];
  }, [questions]);

  const handleSubmit = async (payload) => {
    if (!editing?._id) return;
    await updateFormQuestion(editing._id, payload);
    setEditing(null);
    await load();
  };

  // C9 — create a new question. Errors (incl. 409 "already exists") bubble to the
  // modal, which surfaces the backend detail; on success we close + refresh.
  const handleCreate = async (payload) => {
    await createFormQuestion(payload);
    setAdding(false);
    await load();
  };

  const toggleActive = async (row) => {
    if (!row?._id) return;
    const next = row.active === false; // currently inactive → activate
    setBusyId(row._id);
    setError('');
    try {
      await updateFormQuestion(row._id, { active: next });
      await load();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to update question status.');
    } finally {
      setBusyId(null);
    }
  };

  // Admin-only page — non-admins never see the question master.
  if (!admin) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold text-[var(--text-main)]">Admins only</p>
        <p className="text-[12.5px] text-[var(--text-muted)] max-w-sm">
          Review Form Questions is restricted to TPMS administrators.
        </p>
      </div>
    );
  }

  if (loading && questions.length === 0) {
    return <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading form questions…</div>;
  }

  return (
    <div className="space-y-5">
      <DashboardHero icon={FileEdit} title="Review Form Questions" subtitle="Reword review-form questions & criteria (M10)">
        <HeaderSelect value={formType} onChange={setFormType} options={FILTER_OPTIONS} />
        <HeroButton icon={Plus} onClick={() => setAdding(true)}>Add Question</HeroButton>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {groups.length === 0 ? (
        <Section title="Form Questions" subtitle="Nothing to show" icon={ListChecks}>
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
              <ListChecks size={20} />
            </span>
            <p className="text-[13px] font-bold text-[var(--text-main)]">No questions found</p>
            <p className="text-[12px] text-[var(--text-muted)]">
              {formType ? 'This form has no questions yet.' : 'The question master is empty.'}
            </p>
          </div>
        </Section>
      ) : (
        groups.map((g) => (
          <Section
            key={g.key}
            title={formLabel(g.key)}
            subtitle={`${g.rows.length} ${g.rows.length === 1 ? 'question' : 'questions'}${FORM_META[g.key]?.checklist ? ' · checklist' : ' · rating matrix'}`}
            icon={FORM_META[g.key]?.checklist ? ListChecks : Star}
            tone={FORM_META[g.key]?.checklist ? 'red' : 'navy'}>
            <QuestionTable rows={g.rows} busyId={busyId} onEdit={setEditing} onToggle={toggleActive} />
          </Section>
        ))
      )}

      <AnimatePresence>
        {editing && (
          <QuestionModal
            key={editing._id}
            editing={editing}
            onClose={() => setEditing(null)}
            onSubmit={handleSubmit}
          />
        )}
        {adding && (
          <AddQuestionModal
            key="add-question"
            defaultForm={formType}
            onClose={() => setAdding(false)}
            onSubmit={handleCreate}
          />
        )}
      </AnimatePresence>
    </div>
  );
};

export default FormQuestionAdmin;
